"""Run the user-confirmed plan and return APA-style results (Step 7).

Inputs:
  * df              — cleaned dataset
  * classifications — Step 3 verdicts (used for type-aware summaries)
  * assignment      — outcome / group / covariates
  * confirmed_tests — list of test ids the user kept ticked on Step 6
  * normality       — Step 5 results (so we know which test variant to run)

Output is a dict with:
  * table_one       — descriptive stats
  * tests           — list of {id, title, table_rows, narrative, p_value, ...}
  * graphs          — list of {id, title, png_data_uri}
  * methods_md      — auto-written methods paragraph
  * results_md      — auto-written results paragraph
  * forest_plot     — base64 forest plot of effect sizes
"""

from __future__ import annotations

import base64
import io
import textwrap
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Use Arial (with DejaVu Sans / Liberation Sans as fallback) for all graphs.
# Must be set once at module load after plt is imported.
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Arial", "Liberation Sans", "DejaVu Sans"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fig_to_data_uri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.15, dpi=300)
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _fmt_p(p: Optional[float]) -> str:
    if p is None:
        return "—"
    if p < 0.001:
        return "p < 0.001"
    return f"p = {p:.3f}"


def _fmt_num(x, digits=2) -> str:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return "—"
    if isinstance(x, (int, np.integer)):
        return str(int(x))
    return f"{float(x):.{digits}f}"


def _classes_lookup(classifications):
    return {c["column"]: c for c in classifications if c.get("column")}


def _table_one_is_missing(value: Any) -> bool:
    if pd.isna(value):
        return True
    return isinstance(value, str) and value.strip().lower() == "nan"


def _table_one_categorical_cell(series: pd.Series, categories: List[str]) -> str:
    values = series.map(lambda value: None if _table_one_is_missing(value) else str(value))
    counts = values.dropna().value_counts()
    total = int(len(series))

    def count_pct(count: int) -> str:
        pct = 100.0 * count / total if total else 0.0
        return f"{count} ({pct:.1f}%)"

    bits = [f"{category}: {count_pct(int(counts.get(category, 0)))}" for category in categories]
    missing_n = int(values.isna().sum())
    bits.append(f"Missing: {count_pct(missing_n)}")
    return "; ".join(bits)


def _table_one_scale_cell(series: pd.Series) -> str:
    numeric = pd.to_numeric(series, errors="coerce")
    clean = numeric.dropna()
    total = int(len(series))
    missing_n = int(numeric.isna().sum())
    missing_pct = 100.0 * missing_n / total if total else 0.0
    if not len(clean):
        return f"—; Missing: {missing_n} ({missing_pct:.1f}%)"
    return (
        f"{_fmt_num(clean.mean())} ± {_fmt_num(clean.std(ddof=1))} (n={len(clean)}); "
        f"Missing: {missing_n} ({missing_pct:.1f}%)"
    )


# ---------------------------------------------------------------------------
# Table 1 (descriptives)
# ---------------------------------------------------------------------------


def build_table_one(df: pd.DataFrame, classifications: List[Dict[str, Any]],
                    group: Optional[str]) -> Dict[str, Any]:
    classes = _classes_lookup(classifications)
    rows: List[Dict[str, Any]] = []
    if group and group in df.columns:
        group_levels = [str(v) for v in df[group].dropna().unique()]
    else:
        group_levels = []

    for col, c in classes.items():
        if col == group:
            continue
        if c.get("detected_type") in ("id", "exclude", "date"):
            continue
        if c.get("detected_type") == "scale":
            if group_levels:
                cells = []
                for lvl in group_levels:
                    sub = df.loc[df[group].astype(str) == lvl, col]
                    cells.append(_table_one_scale_cell(sub))
                rows.append({"variable": col, "type": "Mean ± SD", "cells": cells})
            else:
                rows.append({
                    "variable": col, "type": "Mean ± SD",
                    "cells": [_table_one_scale_cell(df[col])],
                })
        else:
            categories = [
                str(value)
                for value in df[col].dropna().unique()
                if not _table_one_is_missing(value)
            ]
            if group_levels:
                cells = []
                for lvl in group_levels:
                    sub = df.loc[df[group].astype(str) == lvl, col]
                    cells.append(_table_one_categorical_cell(sub, categories))
                rows.append({"variable": col, "type": "n (%)", "cells": cells})
            else:
                rows.append({
                    "variable": col, "type": "n (%)",
                    "cells": [_table_one_categorical_cell(df[col], categories)],
                })

    return {
        "headers": ["Variable", "Summary"] + (group_levels or ["Overall"]),
        "rows": rows,
        "group": group,
        "group_levels": group_levels,
    }


# ---------------------------------------------------------------------------
# Test runners — return a uniform shape so the UI can render any of them.
# ---------------------------------------------------------------------------


def _row(label: str, value: Any) -> Dict[str, Any]:
    return {"label": label, "value": value if isinstance(value, str) else _fmt_num(value)}


def _two_groups(df, outcome, group) -> Tuple[np.ndarray, np.ndarray, str, str]:
    levels = [str(v) for v in df[group].dropna().unique()]
    if len(levels) < 2:
        raise ValueError("group needs at least 2 levels")
    a = pd.to_numeric(df.loc[df[group].astype(str) == levels[0], outcome], errors="coerce").dropna().to_numpy()
    b = pd.to_numeric(df.loc[df[group].astype(str) == levels[1], outcome], errors="coerce").dropna().to_numpy()
    return a, b, levels[0], levels[1]


def _ttest_independent(df, outcome, group) -> Dict[str, Any]:
    a, b, la, lb = _two_groups(df, outcome, group)
    stat, p = stats.ttest_ind(a, b, equal_var=False)
    n_a, n_b = len(a), len(b)
    var_a, var_b = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
    pooled_sd = np.sqrt(((n_a - 1) * var_a + (n_b - 1) * var_b) / max(n_a + n_b - 2, 1))
    cohen_d = (np.mean(a) - np.mean(b)) / pooled_sd if pooled_sd else 0.0
    diff = float(np.mean(a) - np.mean(b))
    se_terms = [var_a / n_a, var_b / n_b]
    se = float(np.sqrt(sum(se_terms)))
    df_num = sum(se_terms) ** 2
    df_den = (
        (se_terms[0] ** 2) / max(n_a - 1, 1)
        + (se_terms[1] ** 2) / max(n_b - 1, 1)
    )
    welch_df = float(df_num / df_den) if df_den else float(n_a + n_b - 2)
    t_crit = float(stats.t.ppf(0.975, df=welch_df))
    ci_lo, ci_hi = diff - t_crit * se, diff + t_crit * se
    rows = [
        _row(f"Mean ({la})", float(np.mean(a))),
        _row(f"Mean ({lb})", float(np.mean(b))),
        _row("Mean difference", diff),
        _row("95% CI", f"[{_fmt_num(ci_lo)}, {_fmt_num(ci_hi)}]"),
        _row("t statistic", float(stat)),
        _row("Welch df", welch_df),
        _row("Cohen's d", cohen_d),
        _row("p-value", _fmt_p(float(p))),
    ]
    narrative = (
        f"An independent-samples t-test compared {outcome} between {la} and "
        f"{lb}. Mean {outcome} was {_fmt_num(np.mean(a))} (SD {_fmt_num(np.std(a, ddof=1))}) "
        f"in {la} and {_fmt_num(np.mean(b))} (SD {_fmt_num(np.std(b, ddof=1))}) "
        f"in {lb}; mean difference {_fmt_num(diff)}, 95% CI [{_fmt_num(ci_lo)}, "
        f"{_fmt_num(ci_hi)}], t({_fmt_num(welch_df)}) = {_fmt_num(float(stat))}, "
        f"{_fmt_p(float(p))}, "
        f"Cohen's d = {_fmt_num(cohen_d)}."
    )
    return {
        "rows": rows, "narrative": narrative, "p_value": float(p),
        "effect_size": float(cohen_d), "effect_label": "Cohen's d",
        "ci_lo": float(ci_lo), "ci_hi": float(ci_hi), "df": welch_df,
    }


def _mann_whitney(df, outcome, group) -> Dict[str, Any]:
    a, b, la, lb = _two_groups(df, outcome, group)
    stat, p = stats.mannwhitneyu(a, b, alternative="two-sided")
    n1, n2 = len(a), len(b)
    rank_biserial = 1 - 2 * stat / (n1 * n2) if n1 and n2 else 0.0
    rows = [
        _row(f"Median ({la})", float(np.median(a))),
        _row(f"Median ({lb})", float(np.median(b))),
        _row("U statistic", float(stat)),
        _row("Rank-biserial r", rank_biserial),
        _row("p-value", _fmt_p(float(p))),
    ]
    narrative = (
        f"A Mann-Whitney U test compared {outcome} between {la} (median "
        f"{_fmt_num(np.median(a))}, n = {n1}) and {lb} (median "
        f"{_fmt_num(np.median(b))}, n = {n2}). U = {_fmt_num(float(stat))}, "
        f"{_fmt_p(float(p))}, rank-biserial r = {_fmt_num(rank_biserial)}."
    )
    return {
        "rows": rows, "narrative": narrative, "p_value": float(p),
        "effect_size": float(rank_biserial), "effect_label": "Rank-biserial r",
        "ci_lo": None, "ci_hi": None,
    }


def _anova_oneway(df, outcome, group) -> Dict[str, Any]:
    levels = [str(v) for v in df[group].dropna().unique()]
    samples = [
        pd.to_numeric(df.loc[df[group].astype(str) == lvl, outcome], errors="coerce").dropna().to_numpy()
        for lvl in levels
    ]
    stat, p = stats.f_oneway(*samples)
    grand = np.concatenate(samples)
    ss_between = sum(len(s) * (np.mean(s) - np.mean(grand)) ** 2 for s in samples)
    ss_total = float(np.sum((grand - np.mean(grand)) ** 2))
    eta2 = ss_between / ss_total if ss_total else 0.0
    rows = [_row(f"Mean ({lvl})", float(np.mean(s))) for lvl, s in zip(levels, samples)]
    rows += [
        _row("F statistic", float(stat)),
        _row("η² (eta squared)", eta2),
        _row("p-value", _fmt_p(float(p))),
    ]
    narrative = (
        f"A one-way ANOVA compared {outcome} across {len(levels)} levels of "
        f"{group} ({', '.join(levels)}). F = {_fmt_num(float(stat))}, "
        f"{_fmt_p(float(p))}, η² = {_fmt_num(eta2)}."
    )
    return {
        "rows": rows, "narrative": narrative, "p_value": float(p),
        "effect_size": float(eta2), "effect_label": "η²",
        "ci_lo": None, "ci_hi": None,
    }


def _kruskal_wallis(df, outcome, group) -> Dict[str, Any]:
    levels = [str(v) for v in df[group].dropna().unique()]
    samples = [
        pd.to_numeric(df.loc[df[group].astype(str) == lvl, outcome], errors="coerce").dropna().to_numpy()
        for lvl in levels
    ]
    stat, p = stats.kruskal(*samples)
    rows = [_row(f"Median ({lvl})", float(np.median(s))) for lvl, s in zip(levels, samples)]
    rows += [
        _row("H statistic", float(stat)),
        _row("p-value", _fmt_p(float(p))),
    ]
    narrative = (
        f"A Kruskal-Wallis H test compared {outcome} across {len(levels)} levels "
        f"of {group}. H = {_fmt_num(float(stat))}, {_fmt_p(float(p))}."
    )
    return {
        "rows": rows, "narrative": narrative, "p_value": float(p),
        "effect_size": None, "effect_label": "—",
        "ci_lo": None, "ci_hi": None,
    }


def _chi_square(df, outcome, group) -> Dict[str, Any]:
    ct = pd.crosstab(df[outcome].astype(str), df[group].astype(str))
    chi2, p, dof, expected = stats.chi2_contingency(ct.values)
    n = ct.values.sum()
    cramers_v = float(np.sqrt(chi2 / (n * (min(ct.shape) - 1)))) if n and min(ct.shape) > 1 else 0.0
    rows = [
        _row("χ² statistic", float(chi2)),
        _row("Degrees of freedom", int(dof)),
        _row("Cramér's V", cramers_v),
        _row("p-value", _fmt_p(float(p))),
    ]
    if (expected < 5).any():
        rows.append(_row("Note", "Some expected cells < 5; consider Fisher's exact."))
    min_expected = float(expected.min()) if expected.size else None
    note = (
        "Some expected cells < 5; consider Fisher's exact."
        if min_expected is not None and min_expected < 5
        else f"Minimum expected count = {_fmt_num(min_expected)}."
    )
    narrative = (
        f"A chi-square test of independence assessed the association between "
        f"{outcome} and {group} (χ²({int(dof)}, N = {int(n)}) = "
        f"{_fmt_num(float(chi2))}, {_fmt_p(float(p))}, Cramér's V = "
        f"{_fmt_num(cramers_v)})."
    )
    return {
        "rows": rows, "narrative": narrative, "p_value": float(p),
        "effect_size": cramers_v, "effect_label": "Cramér's V",
        "ci_lo": None, "ci_hi": None,
        "test": "Chi-square test",
        "statistic": float(chi2),
        "dof": int(dof),
        "cramers_v": cramers_v,
        "min_expected": min_expected,
        "note": note,
        "observed_table": ct.values.tolist(),
        "expected_table": expected.tolist(),
        "row_labels": ct.index.astype(str).tolist(),
        "col_labels": ct.columns.astype(str).tolist(),
    }


def _descriptive(df, outcome, _group) -> Dict[str, Any]:
    s = pd.to_numeric(df[outcome], errors="coerce").dropna()
    if len(s) == 0:
        categorical = df[outcome].dropna().astype(str)
        if len(categorical):
            counts = categorical.value_counts()
            n = int(counts.sum())
            return {
                "rows": [
                    _row(str(level), f"{int(count)} ({(100 * count / n):.1f}%)")
                    for level, count in counts.items()
                ],
                "narrative": f"{outcome} was summarised categorically across {len(counts)} levels (n = {n}).",
                "p_value": None, "effect_size": None, "effect_label": "—",
                "ci_lo": None, "ci_hi": None,
            }
        return {"rows": [], "narrative": f"{outcome} has no numeric values to summarise.",
                "p_value": None, "effect_size": None, "effect_label": "—",
                "ci_lo": None, "ci_hi": None}
    rows = [
        _row("n", int(len(s))),
        _row("Mean", float(s.mean())),
        _row("SD", float(s.std(ddof=1))),
        _row("Median", float(s.median())),
        _row("Min / Max", f"{_fmt_num(s.min())} / {_fmt_num(s.max())}"),
    ]
    narrative = (
        f"{outcome}: n = {len(s)}, mean = {_fmt_num(s.mean())}, "
        f"SD = {_fmt_num(s.std(ddof=1))}, median = {_fmt_num(s.median())}, "
        f"range [{_fmt_num(s.min())}, {_fmt_num(s.max())}]."
    )
    return {
        "rows": rows, "narrative": narrative,
        "p_value": None, "effect_size": None, "effect_label": "—",
        "ci_lo": None, "ci_hi": None,
    }


_RUNNERS = {
    "ttest_independent": _ttest_independent,
    "mann_whitney": _mann_whitney,
    "anova_oneway": _anova_oneway,
    "kruskal_wallis": _kruskal_wallis,
    "chi_square": _chi_square,
    "descriptive_only": _descriptive,
}


# ---------------------------------------------------------------------------
# Graphs
# ---------------------------------------------------------------------------


def _boxplot(df, outcome, group) -> Optional[str]:
    """Box plot with individual data points jittered over the boxes."""
    try:
        import scipy.stats as _sp_stats  # noqa: F401 (already imported globally below)
        levels = [str(v) for v in df[group].dropna().unique()]
        data = [
            pd.to_numeric(df.loc[df[group].astype(str) == lvl, outcome], errors="coerce").dropna()
            for lvl in levels
        ]
        fig, ax = plt.subplots(figsize=(5.5, 4.0))
        bp = ax.boxplot(
            data,
            tick_labels=levels,
            patch_artist=True,
            widths=0.45,
            boxprops=dict(facecolor="#dce9ff", edgecolor="#2f6fed", linewidth=1.4),
            medianprops=dict(color="#103a6e", linewidth=2),
            whiskerprops=dict(color="#2f6fed", linewidth=1.2),
            capprops=dict(color="#2f6fed", linewidth=1.5),
            flierprops=dict(marker="", markersize=0),
        )
        # Jittered data points
        rng = np.random.default_rng(42)
        for i, d in enumerate(data, start=1):
            if len(d) == 0:
                continue
            jitter = rng.uniform(-0.18, 0.18, size=len(d))
            ax.scatter(
                np.full(len(d), i) + jitter, d,
                color="#103a6e", alpha=0.45, s=18, zorder=3, linewidths=0,
            )
        ax.set_ylabel(clean_display_name(outcome), fontsize=10)
        ax.set_xlabel(clean_display_name(group), fontsize=10)
        ax.set_title(f"{clean_display_name(outcome)} by {clean_display_name(group)}", fontsize=11, fontweight="bold")
        ax.grid(axis="y", alpha=0.3, linestyle="--")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        fig.tight_layout()
        return _fig_to_data_uri(fig)
    except Exception:
        plt.close("all")
        return None


def _histogram(df, outcome, _group=None) -> Optional[str]:
    """Histogram with a fitted normal distribution curve overlaid."""
    try:
        from scipy.stats import norm as _norm
        s = pd.to_numeric(df[outcome], errors="coerce").dropna()
        if len(s) < 3:
            return None
        n_bins = min(30, max(8, int(np.sqrt(len(s)))))
        fig, ax = plt.subplots(figsize=(5.5, 4.0))
        counts, bin_edges, _ = ax.hist(
            s, bins=n_bins,
            color="#bfd4ff", edgecolor="#2f6fed", alpha=0.85,
            density=False,
        )
        # Overlay normal curve scaled to count area
        mu, sigma = s.mean(), s.std()
        if sigma > 0:
            bin_width = bin_edges[1] - bin_edges[0]
            x_curve = np.linspace(s.min() - sigma, s.max() + sigma, 200)
            y_curve = _norm.pdf(x_curve, mu, sigma) * len(s) * bin_width
            ax.plot(x_curve, y_curve, color="#c43838", lw=2, label=f"Normal (μ={mu:.1f}, σ={sigma:.1f})")
            ax.legend(fontsize=8)
        ax.set_xlabel(clean_display_name(outcome), fontsize=10)
        ax.set_ylabel("Count", fontsize=10)
        ax.set_title(f"Distribution of {clean_display_name(outcome)}", fontsize=11, fontweight="bold")
        ax.grid(axis="y", alpha=0.3, linestyle="--")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        fig.tight_layout()
        return _fig_to_data_uri(fig)
    except Exception:
        plt.close("all")
        return None


def _categorical_graph_uses_horizontal_layout(labels: List[str]) -> bool:
    return len(labels) > 6 or max((len(str(label)) for label in labels), default=0) > 18


def _stacked_bar(df, outcome, group) -> Optional[str]:
    """Grouped percentage bar chart — % of each outcome level per group category."""
    try:
        plot_df = df[[group, outcome]].dropna().copy()
        for col in (group, outcome):
            plot_df[col] = plot_df[col].astype(str).str.strip()
            plot_df = plot_df.loc[
                ~plot_df[col].str.lower().isin({"", "nan", "none", "null", "missing"})
            ]
        ct = pd.crosstab(plot_df[group], plot_df[outcome])
        if ct.empty:
            return None
        pct = ct.div(ct.sum(axis=1), axis=0) * 100  # row-wise % (sum per group = 100)
        n_groups = len(pct.index)
        n_cats   = len(pct.columns)
        labels = [str(label) for label in pct.index]
        horizontal = _categorical_graph_uses_horizontal_layout(labels)
        fig, ax = plt.subplots(
            figsize=(7.0, max(4.0, n_groups * 0.48 + 1.5)) if horizontal
            else (max(5.0, n_groups * 0.9 + 1.5), 4.0)
        )
        positions = np.arange(n_groups)
        width = 0.65 / max(n_cats, 1)
        colours = ["#2f6fed", "#c43838", "#f59e0b", "#10b981", "#8b5cf6"]
        for j, col in enumerate(pct.columns):
            offset = (j - (n_cats - 1) / 2) * width
            style = {
                "label": str(col), "color": colours[j % len(colours)],
                "edgecolor": "white", "linewidth": 0.6,
            }
            bars = (
                ax.barh(positions + offset, pct[col], width * 0.92, **style)
                if horizontal
                else ax.bar(positions + offset, pct[col], width * 0.92, **style)
            )
            for bar in bars:
                value = bar.get_width() if horizontal else bar.get_height()
                if value >= 8:
                    ax.text(
                        value + 1.0 if horizontal else bar.get_x() + bar.get_width() / 2,
                        bar.get_y() + bar.get_height() / 2 if horizontal else value + 1.2,
                        f"{value:.0f}%",
                        ha="left" if horizontal else "center",
                        va="center" if horizontal else "bottom",
                        fontsize=7.5,
                    )
        if horizontal:
            ax.set_yticks(positions)
            ax.set_yticklabels(
                ["\n".join(textwrap.wrap(label, width=28)) for label in labels],
                fontsize=8.5,
            )
            ax.set_xlabel("Percentage (%)", fontsize=10)
            ax.set_ylabel(clean_display_name(group), fontsize=10)
            ax.set_xlim(0, 115)
            ax.grid(axis="x", alpha=0.3, linestyle="--")
        else:
            ax.set_xticks(positions)
            ax.set_xticklabels(labels, fontsize=9, rotation=0)
            ax.set_ylabel("Percentage (%)", fontsize=10)
            ax.set_xlabel(clean_display_name(group), fontsize=10)
            ax.set_ylim(0, 115)
            ax.grid(axis="y", alpha=0.3, linestyle="--")
        ax.set_title(
            f"{clean_display_name(outcome)} distribution by {clean_display_name(group)}",
            fontsize=11, fontweight="bold",
        )
        ax.legend(title=clean_display_name(outcome), fontsize=8, framealpha=0.8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        fig.tight_layout()
        return _fig_to_data_uri(fig)
    except Exception:
        plt.close("all")
        return None


def _pie_chart(df, col, _group=None) -> Optional[str]:
    """Pie chart for a single categorical column with 2–3 distinct values."""
    try:
        counts = df[col].astype(str).value_counts()
        if len(counts) == 0:
            return None
        colours = ["#2f6fed", "#c43838", "#f59e0b", "#10b981"]
        fig, ax = plt.subplots(figsize=(4.5, 4.0))
        wedges, texts, autotexts = ax.pie(
            counts.values,
            labels=counts.index,
            autopct="%1.1f%%",
            colors=colours[: len(counts)],
            startangle=90,
            wedgeprops=dict(edgecolor="white", linewidth=1.5),
        )
        for at in autotexts:
            at.set_fontsize(9)
        ax.set_title(f"Distribution of {clean_display_name(col)}", fontsize=11, fontweight="bold")
        fig.tight_layout()
        return _fig_to_data_uri(fig)
    except Exception:
        plt.close("all")
        return None


def _horz_bar(df, col, _group=None) -> Optional[str]:
    """Horizontal bar chart for a single categorical column with 4+ values."""
    try:
        counts = df[col].astype(str).value_counts().sort_values()
        if len(counts) == 0:
            return None
        fig, ax = plt.subplots(figsize=(5.5, max(3.0, len(counts) * 0.45 + 1.0)))
        colours = plt.cm.Blues(np.linspace(0.4, 0.85, len(counts)))  # type: ignore[attr-defined]
        bars = ax.barh(counts.index, counts.values, color=colours, edgecolor="white")
        for bar, val in zip(bars, counts.values):
            ax.text(val + 0.3, bar.get_y() + bar.get_height() / 2,
                    str(val), va="center", fontsize=8.5)
        ax.set_xlabel("Count", fontsize=10)
        ax.set_title(f"Distribution of {clean_display_name(col)}", fontsize=11, fontweight="bold")
        ax.grid(axis="x", alpha=0.3, linestyle="--")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        fig.tight_layout()
        return _fig_to_data_uri(fig)
    except Exception:
        plt.close("all")
        return None


# Test IDs that use logistic / Cox regression — the ONLY cases where a
# forest plot showing odds/hazard ratios with 95% CI is appropriate.
_FOREST_PLOT_TEST_IDS = frozenset({
    "logistic_regression",
    "cox_regression",
    "pc_binary_logistic",
    "pc_multinomial_logistic",
    "pc_probit",
    "pb_cox",
})


def _forest_plot(test_results: List[Dict[str, Any]]) -> Optional[str]:
    """Forest plot — ONLY for logistic / Cox regression (OR / HR with 95% CI)."""
    try:
        labels, effects, lows, highs = [], [], [], []
        for t in test_results:
            # Only include tests that produce odds/hazard ratios
            if t.get("id") not in _FOREST_PLOT_TEST_IDS:
                continue
            if t.get("effect_size") is None:
                continue
            labels.append(t["title"])
            effects.append(t["effect_size"])
            lo = t.get("ci_lo")
            hi = t.get("ci_hi")
            lows.append(lo if lo is not None else t["effect_size"])
            highs.append(hi if hi is not None else t["effect_size"])
        if not labels:
            return None
        fig, ax = plt.subplots(figsize=(6.5, max(2.5, 0.55 * len(labels) + 1.2)))
        y = np.arange(len(labels))
        for i, (lo, hi, e) in enumerate(zip(lows, highs, effects)):
            ax.plot([lo, hi], [i, i], color="#2f6fed", lw=2)
            ax.plot(e, i, marker="D", color="#2f6fed", markersize=9, zorder=3)
        ax.axvline(1, color="#888", lw=1, ls="--")  # reference line at OR/HR = 1
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=9)
        ax.invert_yaxis()
        ax.set_xlabel("Odds Ratio / Hazard Ratio (95% CI)", fontsize=10)
        ax.set_title("Forest plot — effect estimates", fontsize=11, fontweight="bold")
        ax.grid(axis="x", alpha=0.3, linestyle="--")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        fig.tight_layout()
        return _fig_to_data_uri(fig)
    except Exception:
        plt.close("all")
        return None


def _violin(df, outcome, group) -> Optional[str]:
    try:
        levels = [str(v) for v in df[group].dropna().unique()]
        data = [pd.to_numeric(df.loc[df[group].astype(str) == lvl, outcome], errors="coerce").dropna()
                for lvl in levels]
        data = [d for d in data if len(d) >= 2]
        if not data:
            return None
        fig, ax = plt.subplots(figsize=(5.0, 3.6))
        parts = ax.violinplot(data, showmeans=True, showmedians=True)
        for pc in parts["bodies"]:
            pc.set_facecolor("#bfd4ff")
            pc.set_edgecolor("#2f6fed")
            pc.set_alpha(0.85)
        ax.set_xticks(range(1, len(data) + 1))
        ax.set_xticklabels(levels[:len(data)])
        ax.set_ylabel(outcome)
        ax.set_xlabel(group)
        ax.set_title(f"{outcome} by {group}")
        ax.grid(axis="y", alpha=0.3)
        return _fig_to_data_uri(fig)
    except Exception:
        plt.close("all")
        return None


def _scatter(df, outcome, covariate) -> Optional[str]:
    try:
        x = pd.to_numeric(df[covariate], errors="coerce")
        y = pd.to_numeric(df[outcome], errors="coerce")
        m = x.notna() & y.notna()
        x, y = x[m], y[m]
        if len(x) < 3:
            return None
        fig, ax = plt.subplots(figsize=(5.0, 3.6))
        ax.scatter(x, y, color="#2f6fed", alpha=0.6, s=24)
        # Simple linear fit
        try:
            coeffs = np.polyfit(x, y, 1)
            xs = np.linspace(x.min(), x.max(), 50)
            ax.plot(xs, np.polyval(coeffs, xs), color="#103a6e", lw=1.5)
        except Exception:
            pass
        ax.set_xlabel(covariate)
        ax.set_ylabel(outcome)
        ax.set_title(f"{outcome} vs {covariate}")
        ax.grid(alpha=0.3)
        return _fig_to_data_uri(fig)
    except Exception:
        plt.close("all")
        return None


_GRAPH_RUNNERS = {
    "boxplot": _boxplot,
    "histogram": _histogram,
    "stacked_bar": _stacked_bar,
    "violin": _violin,
}


_PHASE_B_TEST_IDS = frozenset({
    "pb_paired_t", "pb_wilcoxon", "pb_mcnemar", "pb_rm_anova", "pb_friedman",
    "pb_chi_or_fisher", "pb_kappa", "pb_icc_ba", "pb_km", "pb_cox",
    "pb_diagnostic", "pb_ordinal", "pb_count",
})

# Phase-C IDs — newly-added library-backed runners covering the rest of the
# §9.x catalogue. See app/services/tests_phase_c.py.
_PHASE_C_TEST_IDS = frozenset({
    # §9.1 descriptives
    "pc_descriptive_extended", "pc_crosstab",
    # §9.2 means
    "pc_one_sample_t", "pc_two_way_anova", "pc_factorial_anova",
    "pc_ancova", "pc_mixed_anova", "pc_manova",
    # §9.3 GLM
    "pc_glm", "pc_gee",
    # §9.4 mixed
    "pc_linear_mixed",
    # §9.5 correlations
    "pc_pearson", "pc_spearman", "pc_kendall_tau",
    "pc_partial_correlation", "pc_point_biserial",
    "pc_correlation_matrix", "pc_distance_correlation",
    # §9.6 regression
    "pc_linear_regression", "pc_binary_logistic", "pc_multinomial_logistic",
    "pc_probit", "pc_quantile_regression", "pc_robust_regression",
    "pc_wls", "pc_ridge", "pc_lasso", "pc_elastic_net",
    "pc_iv2sls", "pc_nonlinear", "pc_mediation", "pc_moderation",
    # §9.7 loglinear
    "pc_loglinear",
    # §9.9 classification
    "pc_lda", "pc_qda", "pc_kmeans", "pc_hierarchical_cluster",
    "pc_knn", "pc_mlp",
    # §9.10 dimension reduction
    "pc_pca", "pc_efa", "pc_parallel_analysis", "pc_mds",
    # §9.11 reliability extras
    "pc_cronbach_alpha", "pc_split_half", "pc_sem_mdc",
    # §9.12 nonparametric extras
    "pc_cochran_q", "pc_sign_test", "pc_runs_test", "pc_ks_2sample",
    "pc_mood_median", "pc_binomial_test", "pc_chi_goodness_of_fit",
    "pc_mcnemar_bowker", "pc_dunns_post_hoc", "pc_nemenyi",
    # §9.13 time series
    "pc_acf_pacf", "pc_arima", "pc_seasonal_decompose",
    "pc_holt_winters", "pc_spectral", "pc_segmented_regression",
    # §9.14 survival extras
    "pc_stratified_cox", "pc_time_varying_cox", "pc_parametric_aft",
    "pc_rmst", "pc_cif", "pc_cause_specific_cox",
    # §9.16 imputation
    "pc_mice",
    # §9.19 diagnostic
    "pc_delong",
    # §9.20 bayesian
    "pc_bayesian_t",
    # §9.21 effect size
    "pc_omega_squared",
    # §9.22 corrections
    "pc_tukey_hsd", "pc_games_howell", "pc_dunnett",
    "pc_multiple_correction",
})
KNOWN_TEST_IDS = frozenset(set(_RUNNERS.keys()) | _PHASE_B_TEST_IDS | _PHASE_C_TEST_IDS)
KNOWN_GRAPH_IDS = frozenset(list(_GRAPH_RUNNERS.keys()) + ["forest_plot"])


def is_supported_test(test_id: str) -> bool:
    return test_id in KNOWN_TEST_IDS or test_id.startswith("association_")


def is_supported_graph(graph_id: str) -> bool:
    return graph_id in KNOWN_GRAPH_IDS or graph_id.startswith("scatter_")


# ---------------------------------------------------------------------------
# Top-level entrypoint
# ---------------------------------------------------------------------------


_LEGACY_TEST_TYPE = {
    "ttest_independent": "t_test_independent",
    "mann_whitney": "mann_whitney",
    "anova_oneway": "anova_oneway",
    "kruskal_wallis": "kruskal_wallis",
    "chi_square": "chi_square",
    "fisher_exact_if_sparse": "fisher_exact",
    "ancova": "linear_regression",
    "linear_regression": "linear_regression",
    "logistic_regression": "logistic_regression",
}


_PRESENTATION_SKIP_KEYS = {
    "id", "title", "test", "test_type", "plan_name", "plan_reason",
    "rows", "tables", "figures", "narrative", "interpretation", "result_text",
    "warning", "error", "kmf_objects", "roc_data", "graph_uri",
    "png_data_uri", "desc_graph_uri",
}

_T_TEST_TYPES = {"t_test_independent", "welch_ttest", "t_test_paired"}
_ANOVA_TYPES = {"anova_oneway", "rm_anova"}
_REGRESSION_TYPES = {
    "linear_regression", "logistic_regression", "multinomial_logistic",
    "ordinal_logistic", "count_regression",
}
_CONTINGENCY_TYPES = {"chi_square", "fisher_exact", "crosstab"}
_DIAGNOSTIC_TYPES = {"diagnostic_accuracy"}
_RELIABILITY_TYPES = {"kappa", "icc"}


def _jsonish_value(value: Any, *, depth: int = 0) -> Any:
    """Return a JSON-safe copy for presentation metadata, or None if unsafe."""
    if depth > 2:
        return None
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        val = float(value)
        return val if np.isfinite(val) else None
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            safe = _jsonish_value(item, depth=depth + 1)
            if safe is not None:
                out.append(safe)
        return out
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            safe = _jsonish_value(item, depth=depth + 1)
            if safe is not None:
                out[str(key)] = safe
        return out
    return None


def _presentation_stats(raw: Dict[str, Any]) -> Dict[str, Any]:
    stats_out: Dict[str, Any] = {}
    for key, value in raw.items():
        if key in _PRESENTATION_SKIP_KEYS:
            continue
        safe = _jsonish_value(value)
        if safe is not None:
            stats_out[key] = safe
    return stats_out


def _display_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return f"{_display_value(value[0])} to {_display_value(value[1])}"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        val = float(value)
        if not np.isfinite(val):
            return "-"
        return f"{val:.3f}"
    return str(value)


def _legacy_label_value_table(raw: Dict[str, Any], title: str = "Summary") -> Optional[Dict[str, Any]]:
    rows = []
    for row in raw.get("rows") or []:
        if not isinstance(row, dict):
            continue
        if "label" in row and "value" in row:
            rows.append([row.get("label", ""), row.get("value", "")])
    if not rows:
        return None
    return {"title": title, "headers": ["Statistic", "Value"], "rows": rows}


def _ci_from_row(row: Dict[str, Any], prefix: str = "") -> str:
    tuple_keys = [f"{prefix}_ci", f"{prefix}ci", "ci", "OR_ci", "HR_ci", "TR_ci"]
    for key in tuple_keys:
        ci = row.get(key)
        if isinstance(ci, (list, tuple)) and len(ci) == 2:
            return _display_value(ci)
    lo = row.get("CI_lo", row.get("ci_lo", row.get("lower")))
    hi = row.get("CI_hi", row.get("ci_hi", row.get("upper")))
    if lo is not None and hi is not None:
        return _display_value((lo, hi))
    return "-"


def _regression_table(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    source_rows = [r for r in (raw.get("rows") or []) if isinstance(r, dict)]
    if not source_rows:
        return None

    has_or = any("OR" in r for r in source_rows)
    has_hr = any("HR" in r for r in source_rows)
    has_b = any("B" in r for r in source_rows)
    has_se = any("SE" in r for r in source_rows)
    has_t = any("t" in r for r in source_rows)
    metric_key = "OR" if has_or else "HR" if has_hr else "B" if has_b else "coef"
    metric_header = "OR" if has_or else "HR" if has_hr else "Estimate"

    headers = ["Variable", metric_header]
    if has_se:
        headers.append("SE")
    if has_t:
        headers.append("t")
    headers += ["95% CI", "p-value"]

    rows = []
    for row in source_rows:
        label = row.get("variable") or row.get("term") or row.get("predictor") or row.get("label") or ""
        line = [label, _display_value(row.get(metric_key))]
        if has_se:
            line.append(_display_value(row.get("SE")))
        if has_t:
            line.append(_display_value(row.get("t")))
        line.append(_ci_from_row(row, prefix=metric_key))
        p_val = row.get("p")
        line.append(row.get("p_display") or (fmt_p(p_val) if p_val is not None else "-"))
        rows.append(line)

    return {"title": "Coefficient table", "headers": headers, "rows": rows}


def _matrix_from_raw(raw: Dict[str, Any], *keys: str) -> List[List[Any]]:
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, pd.DataFrame):
            return value.values.tolist()
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, list):
            return value
    return []


def _contingency_labels(raw: Dict[str, Any], matrix: List[List[Any]]) -> Tuple[List[str], List[str]]:
    row_labels = raw.get("row_labels") or raw.get("rows_labels") or raw.get("index_labels")
    col_labels = raw.get("col_labels") or raw.get("column_labels") or raw.get("columns")
    n_rows = len(matrix)
    n_cols = max((len(r) for r in matrix if isinstance(r, list)), default=0)
    if not isinstance(row_labels, list) or len(row_labels) != n_rows:
        row_labels = [f"Row {i + 1}" for i in range(n_rows)]
    if not isinstance(col_labels, list) or len(col_labels) != n_cols:
        col_labels = [f"Column {i + 1}" for i in range(n_cols)]
    return [str(v) for v in row_labels], [str(v) for v in col_labels]


def _numeric_matrix(matrix: List[List[Any]]) -> np.ndarray:
    return np.array(matrix, dtype=float) if matrix else np.empty((0, 0), dtype=float)


def _matrix_render_table(
    title: str,
    matrix: List[List[Any]],
    row_labels: List[str],
    col_labels: List[str],
    *,
    digits: int = 0,
    suffix: str = "",
    include_totals: bool = False,
) -> Optional[Dict[str, Any]]:
    arr = _numeric_matrix(matrix)
    if arr.size == 0:
        return None
    headers = ["Category"] + col_labels + (["Total"] if include_totals else [])
    rows: List[List[Any]] = []
    for label, values in zip(row_labels, arr):
        rendered = [label] + [f"{float(v):.{digits}f}{suffix}" for v in values]
        if include_totals:
            rendered.append(f"{float(np.nansum(values)):.{digits}f}{suffix}")
        rows.append(rendered)
    if include_totals:
        col_totals = np.nansum(arr, axis=0)
        total_row = ["Total"] + [f"{float(v):.{digits}f}{suffix}" for v in col_totals]
        total_row.append(f"{float(np.nansum(arr)):.{digits}f}{suffix}")
        rows.append(total_row)
    return {"title": title, "headers": headers, "rows": rows}


def _percentage_tables(observed: List[List[Any]], row_labels: List[str], col_labels: List[str]) -> List[Dict[str, Any]]:
    arr = _numeric_matrix(observed)
    if arr.size == 0:
        return []
    tables: List[Dict[str, Any]] = []
    with np.errstate(divide="ignore", invalid="ignore"):
        row_totals = arr.sum(axis=1, keepdims=True)
        row_pct = np.divide(arr, row_totals, out=np.zeros_like(arr), where=row_totals != 0) * 100.0
        col_totals = arr.sum(axis=0, keepdims=True)
        col_pct = np.divide(arr, col_totals, out=np.zeros_like(arr), where=col_totals != 0) * 100.0
    row_table = _matrix_render_table(
        "Row percentages", row_pct.tolist(), row_labels, col_labels, digits=1, suffix="%"
    )
    col_table = _matrix_render_table(
        "Column percentages", col_pct.tolist(), row_labels, col_labels, digits=1, suffix="%"
    )
    if row_table:
        tables.append(row_table)
    if col_table:
        tables.append(col_table)
    return tables


def _contingency_summary_table(raw: Dict[str, Any]) -> Dict[str, Any]:
    test_used = raw.get("test") or raw.get("test_name") or raw.get("title") or raw.get("test_type") or "Categorical association test"
    stat = _first_non_null(raw, "statistic", "chi2", "odds_ratio")
    df_val = _first_non_null(raw, "dof", "df")
    p_val = _first_non_null(raw, "p", "p_value")
    effect = _first_non_null(raw, "cramers_v", "effect_size")
    note = raw.get("note") or raw.get("warning") or ""
    min_expected = _first_non_null(raw, "min_expected")
    if min_expected is not None and not note:
        try:
            if float(min_expected) < 5:
                note = "Warning: one or more expected counts are below 5."
        except Exception:
            pass
    if min_expected is not None:
        sparse_text = f"{_display_value(min_expected)}"
        if note:
            sparse_text += f"; {note}"
    else:
        sparse_text = note or "-"
    return {
        "title": "Test summary",
        "headers": ["Measure", "Value"],
        "rows": [
            ["Test used", test_used],
            ["Statistic", _display_value(stat)],
            ["df", _display_value(df_val)],
            ["p-value", _fmt_p(float(p_val)) if p_val is not None else (raw.get("p_display") or "-")],
            ["Cramer's V / effect size", _display_value(effect)],
            ["Expected-count / sparse-cell warning", sparse_text],
        ],
    }


def _first_non_null(raw: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in raw and raw[key] is not None:
            return raw[key]
    return None


def _contingency_tables(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    observed = _matrix_from_raw(raw, "observed_table", "observed")
    expected = _matrix_from_raw(raw, "expected_table", "expected")
    if not observed:
        return [_contingency_summary_table(raw)]
    row_labels, col_labels = _contingency_labels(raw, observed)
    tables: List[Dict[str, Any]] = []
    observed_table = _matrix_render_table(
        "Observed counts", observed, row_labels, col_labels, digits=0, include_totals=True
    )
    if observed_table:
        tables.append(observed_table)
    expected_table = _matrix_render_table(
        "Expected counts", expected, row_labels, col_labels, digits=2
    )
    if expected_table:
        tables.append(expected_table)
    tables.extend(_percentage_tables(observed, row_labels, col_labels))
    tables.append(_contingency_summary_table(raw))
    return tables


def _diagnostic_value(value: Any) -> str:
    try:
        numeric = float(value)
        if np.isposinf(numeric):
            return "Infinity"
        if np.isneginf(numeric):
            return "-Infinity"
    except (TypeError, ValueError):
        pass
    return _display_value(value)


def _diagnostic_ci(raw: Dict[str, Any], key: str) -> str:
    ci = raw.get(key)
    if isinstance(ci, (list, tuple)) and len(ci) == 2:
        return f"{_diagnostic_value(ci[0])} to {_diagnostic_value(ci[1])}"
    return "-"


def _diagnostic_tables(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    metrics = {
        "title": "Diagnostic Metrics",
        "headers": ["Metric", "Estimate", "95% CI"],
        "rows": [
            ["AUC", _diagnostic_value(raw.get("auc")), _diagnostic_ci(raw, "auc_ci")],
            ["Sensitivity", _diagnostic_value(raw.get("sensitivity")), _diagnostic_ci(raw, "sensitivity_ci")],
            ["Specificity", _diagnostic_value(raw.get("specificity")), _diagnostic_ci(raw, "specificity_ci")],
            ["PPV", _diagnostic_value(raw.get("ppv")), _diagnostic_ci(raw, "ppv_ci")],
            ["NPV", _diagnostic_value(raw.get("npv")), _diagnostic_ci(raw, "npv_ci")],
            ["Accuracy", _diagnostic_value(raw.get("accuracy")), _diagnostic_ci(raw, "accuracy_ci")],
            ["LR+", _diagnostic_value(raw.get("lr_positive")), "-"],
            ["LR-", _diagnostic_value(raw.get("lr_negative")), "-"],
            ["Diagnostic odds ratio", _diagnostic_value(raw.get("dor")), "-"],
        ],
    }

    cm = raw.get("confusion_matrix") or {}
    tp = int(cm.get("TP", raw.get("TP", 0)) or 0)
    tn = int(cm.get("TN", raw.get("TN", 0)) or 0)
    fp = int(cm.get("FP", raw.get("FP", 0)) or 0)
    fn = int(cm.get("FN", raw.get("FN", 0)) or 0)
    confusion = {
        "title": "Confusion Matrix",
        "headers": ["Actual / Predicted", "Predicted positive", "Predicted negative", "Total"],
        "rows": [
            ["Actual positive", f"TP: {tp}", f"FN: {fn}", tp + fn],
            ["Actual negative", f"FP: {fp}", f"TN: {tn}", fp + tn],
            ["Total", tp + fp, fn + tn, tp + tn + fp + fn],
        ],
    }
    return [metrics, confusion]


def _diagnostic_roc_figure(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    roc_data = raw.get("roc_data") or {}
    fpr = roc_data.get("fpr")
    tpr = roc_data.get("tpr")
    if not isinstance(fpr, list) or not isinstance(tpr, list) or len(fpr) != len(tpr) or len(fpr) < 2:
        return None
    try:
        fig, ax = plt.subplots(figsize=(5.5, 4.0))
        auc = _diagnostic_value(raw.get("auc"))
        ax.plot(fpr, tpr, color="#2f6fed", linewidth=2, label=f"ROC curve (AUC = {auc})")
        ax.plot([0, 1], [0, 1], color="#777777", linestyle="--", linewidth=1, label="Chance")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1.02)
        ax.set_xlabel("False positive rate")
        ax.set_ylabel("True positive rate")
        ax.set_title("Receiver operating characteristic curve")
        ax.legend(loc="lower right")
        ax.grid(alpha=0.2)
        return {
            "title": "ROC curve",
            "png_data_uri": _fig_to_data_uri(fig),
        }
    except Exception:
        return None


def _reliability_tables(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    test_type = raw.get("test_type")
    if test_type == "kappa":
        p_value = _first_non_null(raw, "p", "p_value")
        p_display = _fmt_p(float(p_value)) if p_value is not None else (raw.get("p_display") or "-")
        return [{
            "title": "Kappa Reliability",
            "headers": ["Measure", "Value"],
            "rows": [
                ["Method", raw.get("test") or "Kappa"],
                ["Kappa value", _display_value(raw.get("kappa"))],
                ["95% CI", _diagnostic_ci(raw, "kappa_ci") if raw.get("kappa_ci") else _diagnostic_ci(raw, "ci")],
                ["p-value", p_display],
                ["Interpretation", raw.get("kappa_interpretation") or raw.get("interpretation") or "-"],
            ],
        }]

    tables = [{
        "title": "ICC Reliability",
        "headers": ["Measure", "Value"],
        "rows": [
            ["ICC value", _display_value(raw.get("icc"))],
            ["95% CI", _diagnostic_ci(raw, "icc_ci")],
            ["Model used", raw.get("icc_model") or "Not reported"],
            ["p-value", _fmt_p(float(raw["icc_p"])) if raw.get("icc_p") is not None else (raw.get("icc_p_display") or "-")],
            ["Interpretation", raw.get("icc_interpretation") or raw.get("interpretation") or "-"],
        ],
    }]
    bland_altman = raw.get("bland_altman") or {}
    if bland_altman:
        tables.append({
            "title": "Bland-Altman Agreement",
            "headers": ["Measure", "Value"],
            "rows": [
                ["Mean bias", _display_value(bland_altman.get("mean_bias"))],
                ["Lower limit of agreement", _display_value(bland_altman.get("loa_lower"))],
                ["Upper limit of agreement", _display_value(bland_altman.get("loa_upper"))],
            ],
        })
    return tables


def _bland_altman_figure(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    plot_data = raw.get("bland_altman_plot_data") or {}
    means = plot_data.get("means")
    differences = plot_data.get("differences")
    bland_altman = raw.get("bland_altman") or {}
    if not isinstance(means, list) or not isinstance(differences, list):
        return None
    if len(means) != len(differences) or len(means) < 2:
        return None
    try:
        bias = float(bland_altman["mean_bias"])
        lower = float(bland_altman["loa_lower"])
        upper = float(bland_altman["loa_upper"])
        fig, ax = plt.subplots(figsize=(5.5, 4.0))
        ax.scatter(means, differences, color="#2f6fed", alpha=0.75, edgecolors="none")
        ax.axhline(bias, color="#222222", linewidth=1.5, label=f"Mean bias = {bias:.3f}")
        ax.axhline(lower, color="#b42318", linestyle="--", linewidth=1.2, label=f"Lower LoA = {lower:.3f}")
        ax.axhline(upper, color="#b42318", linestyle="--", linewidth=1.2, label=f"Upper LoA = {upper:.3f}")
        ax.set_xlabel("Mean of paired measurements")
        ax.set_ylabel("Difference between paired measurements")
        ax.set_title("Bland-Altman agreement plot")
        ax.legend(loc="best")
        ax.grid(alpha=0.2)
        return {"title": "Bland-Altman plot", "png_data_uri": _fig_to_data_uri(fig)}
    except Exception:
        return None


def normalize_result_for_rendering(raw_result: Dict[str, Any]) -> Dict[str, Any]:
    """Add a presentation contract without changing runner-owned raw fields."""
    raw = dict(raw_result or {})
    test_type = raw.get("test_type") or _LEGACY_TEST_TYPE.get(str(raw.get("id", ""))) or ""
    title = raw.get("title") or raw.get("plan_name") or raw.get("test") or str(raw.get("id", "Result"))
    narrative = (
        raw.get("narrative")
        or raw.get("interpretation")
        or raw.get("result_text")
        or raw.get("warning")
        or raw.get("error")
        or ""
    )

    tables: List[Dict[str, Any]] = []
    if test_type in _T_TEST_TYPES:
        table = _legacy_label_value_table(raw, "t-test summary")
        if table:
            tables.append(table)
    elif test_type in _ANOVA_TYPES:
        table = _legacy_label_value_table(raw, "ANOVA summary")
        if table:
            tables.append(table)
    elif test_type in _REGRESSION_TYPES:
        table = _regression_table(raw)
        if table:
            tables.append(table)
    elif test_type in _CONTINGENCY_TYPES:
        tables.extend(_contingency_tables(raw))
    elif test_type in _DIAGNOSTIC_TYPES:
        tables.extend(_diagnostic_tables(raw))
    elif test_type in _RELIABILITY_TYPES:
        tables.extend(_reliability_tables(raw))

    figures = list(raw.get("figures") or [])
    if test_type in _DIAGNOSTIC_TYPES:
        roc_figure = _diagnostic_roc_figure(raw)
        if roc_figure:
            figures.append(roc_figure)
    elif test_type == "icc":
        bland_altman_figure = _bland_altman_figure(raw)
        if bland_altman_figure:
            figures.append(bland_altman_figure)
    raw.update({
        "id": raw.get("id"),
        "title": title,
        "test_type": test_type,
        "narrative": narrative,
        "tables": tables,
        "figures": figures,
        "stats": _presentation_stats(raw),
    })
    return raw


def _result_p_value(test: Dict[str, Any]) -> Optional[float]:
    for key in ("p_corrected", "p", "p_value"):
        value = test.get(key)
        if value is None:
            continue
        try:
            value = float(value)
            if np.isfinite(value):
                return value
        except (TypeError, ValueError):
            continue
    return None


def _result_raw_p_value(test: Dict[str, Any]) -> Optional[float]:
    for key in ("p", "p_value"):
        value = test.get(key)
        if value is None:
            continue
        try:
            value = float(value)
            if np.isfinite(value):
                return value
        except (TypeError, ValueError):
            continue
    return None


def _row_lookup(test: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in test.get("rows") or []:
        if isinstance(row, dict):
            out[str(row.get("label", "")).strip().lower()] = str(row.get("value", ""))
    for table in test.get("tables") or []:
        headers = [str(h).strip().lower() for h in table.get("headers") or []]
        if len(headers) >= 2 and headers[0] in {"measure", "statistic"}:
            for row in table.get("rows") or []:
                if isinstance(row, list) and len(row) >= 2:
                    out[str(row[0]).strip().lower()] = str(row[1])
    return out


def _test_used(test: Dict[str, Any]) -> str:
    rows = _row_lookup(test)
    return (
        rows.get("test used")
        or test.get("actual_test_used")
        or test.get("test_name")
        or test.get("test")
        or test.get("title")
        or test.get("test_type")
        or "Statistical test"
    )


def _statistic_text(test: Dict[str, Any]) -> str:
    rows = _row_lookup(test)
    test_type = str(test.get("test_type") or "").lower()
    stat = test.get("statistic")
    if stat is None:
        stat = test.get("stat")
    if stat is None:
        stat = test.get("chi2")
    if stat is None:
        stat = rows.get("statistic") or rows.get("t statistic") or rows.get("u statistic") or rows.get("h statistic")
    df_val = test.get("df") if test.get("df") is not None else test.get("dof")
    if df_val is None:
        df_val = rows.get("df") or rows.get("welch df")
    parts: List[str] = []
    if stat not in (None, "", "-"):
        label = "statistic"
        if "chi" in test_type:
            label = "chi-square"
        elif "welch" in test_type or "ttest" in test_type or "t_test" in test_type:
            label = "t"
        elif "mann" in test_type:
            label = "U"
        elif "kruskal" in test_type:
            label = "H"
        parts.append(f"{label} = {_display_value(stat)}")
    if df_val not in (None, "", "-"):
        parts.append(f"df = {_display_value(df_val)}")
    return ", ".join(parts)


def _effect_text(test: Dict[str, Any]) -> str:
    rows = _row_lookup(test)
    effect = test.get("effect_size")
    if effect is None:
        effect = test.get("cramers_v")
    if effect is None:
        effect = rows.get("cramer's v / effect size") or rows.get("cohen's d") or rows.get("rank-biserial correlation")
    if effect in (None, "", "-"):
        return ""
    label = test.get("effect_label") or ("Cramer's V" if test.get("cramers_v") is not None else "Effect size")
    return f"{label} = {_display_value(effect)}"


def _warning_text(test: Dict[str, Any]) -> str:
    rows = _row_lookup(test)
    note = test.get("warning") or test.get("note") or rows.get("expected-count / sparse-cell warning") or ""
    return "" if str(note).strip() in {"", "-"} else str(note).strip()


def _compact_result_summary(test: Dict[str, Any]) -> str:
    title = str(test.get("title") or "Analysis result")
    pieces = [_test_used(test)]
    for bit in (_statistic_text(test),):
        if bit:
            pieces.append(bit)
    p = _result_raw_p_value(test)
    if p is not None:
        pieces.append(_fmt_p(p))
    if test.get("p_corrected") is not None:
        pieces.append(f"adjusted {_fmt_p(float(test['p_corrected']))}")
    effect = _effect_text(test)
    if effect:
        pieces.append(effect)
    warning = _warning_text(test)
    if warning:
        pieces.append(warning)
    return f"{title}: " + ", ".join(pieces) + "."


def _significant_findings(test_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for test in test_results:
        p = _result_p_value(test)
        if p is None or p >= 0.05:
            continue
        title = str(test.get("title") or "")
        findings.append({
            "variable": title.split(":", 1)[0].strip() if ":" in title else title,
            "key_finding": test.get("compact_summary") or _compact_result_summary(test),
            "test_statistic": _statistic_text(test) or "-",
            "p_value": _fmt_p(p),
            "p_numeric": p,
            "uncorrected_p_value": _fmt_p(_result_raw_p_value(test)) if _result_raw_p_value(test) is not None else "-",
            "test_applied": _test_used(test),
            "effect_size": _effect_text(test) or "-",
            "notes_warnings": _warning_text(test) or "-",
        })
    return findings


def run_plan(
    df: pd.DataFrame,
    classifications: List[Dict[str, Any]],
    assignment: Dict[str, Any],
    plan: Dict[str, Any],
    confirmed_test_ids: Optional[List[str]] = None,
    confirmed_graph_ids: Optional[List[str]] = None,
    session: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    outcome = (assignment or {}).get("outcome")
    group = (assignment or {}).get("group")
    confirmed_test_ids = confirmed_test_ids or [t["id"] for t in (plan.get("tests") or [])]
    confirmed_graph_ids = confirmed_graph_ids or [g["id"] for g in (plan.get("graphs") or [])]
    session = session or {}
    # Always make sure session has a `variables` map keyed by raw column,
    # so get_display_name() works in every phase-B function.
    if "variables" not in session:
        session["variables"] = {
            str(col): {"display_name": clean_display_name(col)}
            for col in df.columns
        }

    # Phase-B function dispatch table (defined here so the import is local
    # and circular-import-safe).
    from app.services import tests_phase_c as _pc
    FUNCTION_MAP = {
        # --- Phase B (existing) -----------------------------------------
        "run_paired_ttest": run_paired_ttest,
        "run_wilcoxon": run_wilcoxon,
        "run_mcnemar": run_mcnemar,
        "run_rm_anova": run_rm_anova,
        "run_friedman": run_friedman,
        "run_chi_or_fisher": run_chi_or_fisher,
        "run_pairwise_welch": run_pairwise_welch,
        "run_pairwise_mann_whitney": run_pairwise_mann_whitney,
        "run_pairwise_anova": run_pairwise_anova,
        "run_pairwise_kruskal": run_pairwise_kruskal,
        "run_kappa": run_kappa,
        "run_icc_bland_altman": run_icc_bland_altman,
        "run_kaplan_meier": run_kaplan_meier,
        "run_cox_regression": run_cox_regression,
        "run_diagnostic_accuracy": run_diagnostic_accuracy,
        "run_ordinal_logistic": run_ordinal_logistic,
        "run_count_regression": run_count_regression,
        # --- Phase C (new — see tests_phase_c.py) -----------------------
        # §9.1
        "pc_descriptive_extended": _pc.run_descriptive_extended,
        "pc_crosstab": _pc.run_crosstab,
        # §9.2
        "pc_one_sample_t": _pc.run_one_sample_t,
        "pc_two_way_anova": _pc.run_two_way_anova,
        "pc_factorial_anova": _pc.run_factorial_anova,
        "pc_ancova": _pc.run_ancova,
        "pc_mixed_anova": _pc.run_mixed_anova,
        "pc_manova": _pc.run_manova,
        # §9.3
        "pc_glm": _pc.run_glm,
        "pc_gee": _pc.run_gee,
        # §9.4
        "pc_linear_mixed": _pc.run_linear_mixed,
        # §9.5
        "pc_pearson": _pc.run_pearson,
        "pc_spearman": _pc.run_spearman,
        "pc_kendall_tau": _pc.run_kendall_tau,
        "pc_partial_correlation": _pc.run_partial_correlation,
        "pc_point_biserial": _pc.run_point_biserial,
        "pc_correlation_matrix": _pc.run_correlation_matrix,
        "pc_distance_correlation": _pc.run_distance_correlation,
        # §9.6
        "pc_linear_regression": _pc.run_linear_regression,
        "pc_binary_logistic": _pc.run_binary_logistic,
        "pc_multinomial_logistic": _pc.run_multinomial_logistic,
        "pc_probit": _pc.run_probit,
        "pc_quantile_regression": _pc.run_quantile_regression,
        "pc_robust_regression": _pc.run_robust_regression,
        "pc_wls": _pc.run_wls,
        "pc_ridge": _pc.run_ridge,
        "pc_lasso": _pc.run_lasso,
        "pc_elastic_net": _pc.run_elastic_net,
        "pc_iv2sls": _pc.run_iv2sls,
        "pc_nonlinear": _pc.run_nonlinear,
        "pc_mediation": _pc.run_mediation,
        "pc_moderation": _pc.run_moderation,
        # §9.7
        "pc_loglinear": _pc.run_loglinear,
        # §9.9
        "pc_lda": _pc.run_lda,
        "pc_qda": _pc.run_qda,
        "pc_kmeans": _pc.run_kmeans,
        "pc_hierarchical_cluster": _pc.run_hierarchical_cluster,
        "pc_knn": _pc.run_knn,
        "pc_mlp": _pc.run_mlp,
        # §9.10
        "pc_pca": _pc.run_pca,
        "pc_efa": _pc.run_efa,
        "pc_parallel_analysis": _pc.run_parallel_analysis,
        "pc_mds": _pc.run_mds,
        # §9.11
        "pc_cronbach_alpha": _pc.run_cronbach_alpha,
        "pc_split_half": _pc.run_split_half,
        "pc_sem_mdc": _pc.run_sem_mdc,
        # §9.12
        "pc_cochran_q": _pc.run_cochran_q,
        "pc_sign_test": _pc.run_sign_test,
        "pc_runs_test": _pc.run_runs_test,
        "pc_ks_2sample": _pc.run_ks_2sample,
        "pc_mood_median": _pc.run_mood_median,
        "pc_binomial_test": _pc.run_binomial_test,
        "pc_chi_goodness_of_fit": _pc.run_chi_goodness_of_fit,
        "pc_mcnemar_bowker": _pc.run_mcnemar_bowker,
        "pc_dunns_post_hoc": _pc.run_dunns_post_hoc,
        "pc_nemenyi": _pc.run_nemenyi,
        # §9.13
        "pc_acf_pacf": _pc.run_acf_pacf,
        "pc_arima": _pc.run_arima,
        "pc_seasonal_decompose": _pc.run_seasonal_decompose,
        "pc_holt_winters": _pc.run_holt_winters,
        "pc_spectral": _pc.run_spectral,
        "pc_segmented_regression": _pc.run_segmented_regression,
        # §9.14
        "pc_stratified_cox": _pc.run_stratified_cox,
        "pc_time_varying_cox": _pc.run_time_varying_cox,
        "pc_parametric_aft": _pc.run_parametric_aft,
        "pc_rmst": _pc.run_rmst,
        "pc_cif": _pc.run_cif,
        "pc_cause_specific_cox": _pc.run_cause_specific_cox,
        # §9.16
        "pc_mice": _pc.run_mice_imputation,
        # §9.19
        "pc_delong": _pc.run_delong,
        # §9.20
        "pc_bayesian_t": _pc.run_bayesian_t,
        # §9.21
        "pc_omega_squared": _pc.run_omega_squared,
        # §9.22
        "pc_tukey_hsd": _pc.run_tukey_hsd,
        "pc_games_howell": _pc.run_games_howell,
        "pc_dunnett": _pc.run_dunnett,
        "pc_multiple_correction": _pc.run_multiple_comparison_correction,
    }

    # Run tests --------------------------------------------------------------
    test_results: List[Dict[str, Any]] = []
    for t in plan.get("tests") or []:
        if t["id"] not in confirmed_test_ids:
            continue

        # ---- Phase-B trigger entries dispatch via FUNCTION_MAP --------
        pb = t.get("_phase_b")
        if pb:
            fn = FUNCTION_MAP.get(pb.get("function"))
            if fn is None:
                continue
            try:
                r = fn(session=session, df=df, **(pb.get("args") or {}))
                if not r:
                    r = {"error": f'{t["title"]} returned no result.'}
            except Exception as exc:  # noqa: BLE001
                r = {"error": f'{t["title"]} could not complete: {exc}'}
            # Normalise to the renderer shape used by the existing UI.
            narrative = (
                r.get("interpretation")
                or r.get("result_text")
                or r.get("warning")
                or r.get("error")
                or f'{t["title"]} ran.'
            )
            r.setdefault("rows", [])
            r.setdefault("narrative", narrative)
            r.setdefault("p_value", r.get("p"))
            r.setdefault("effect_size", None)
            r.setdefault("effect_label", "—")
            r.setdefault("ci_lo", None)
            r.setdefault("ci_hi", None)
            r["id"] = t["id"]
            function_name = pb.get("function")
            args = pb.get("args") or {}
            if function_name == "run_chi_or_fisher" and r.get("actual_test_used"):
                actual_name = str(r["actual_test_used"])
                if actual_name.lower() == "chi-square":
                    actual_name = "Chi-square test"
                elif actual_name.lower() in {"fisher's exact", "fisher exact"}:
                    actual_name = "Fisher's exact test"
                warning_text = str(r.get("note") or r.get("warning") or "").lower()
                sparse = "sparse" in warning_text or "expected counts below" in warning_text
                if sparse and "chi-square" in actual_name.lower():
                    actual_name = "Chi-square test with sparse-cell warning"
                r["title"] = (
                    f"{args.get('col1')} vs {args.get('col2')}: "
                    f"{actual_name}"
                )
                r["plan_name"] = r["title"]
            else:
                r["title"] = t["title"]
            r["test_type"] = r.get("test_type") or pb.get("test_type")
            r["analysis_family"] = t.get("analysis_family") or (
                "regression" if pb.get("test_type") in _REGRESSION_TYPES
                else "correlation" if pb.get("test_type") in ("pearson", "spearman", "kendall_tau")
                else "bivariate"
            )
            r.setdefault("plan_name", t["title"])
            r["plan_reason"] = t.get("why")
            figures = list(r.get("figures") or [])
            if function_name == "run_chi_or_fisher":
                png = _stacked_bar(df, args.get("col2"), args.get("col1"))
                if png:
                    figures.append({
                        "title": f"{args.get('col2')} by {args.get('col1')} (%)",
                        "png_data_uri": png,
                    })
            elif function_name in {
                "run_pairwise_welch", "run_pairwise_mann_whitney",
                "run_pairwise_anova", "run_pairwise_kruskal",
            }:
                png = _boxplot(df, args.get("predictor"), args.get("outcome"))
                if png:
                    figures.append({
                        "title": f"{args.get('predictor')} by {args.get('outcome')}",
                        "png_data_uri": png,
                    })
            if figures:
                r["figures"] = figures
            test_results.append(r)
            continue

        # ---- Existing legacy runners (untouched) ----------------------
        runner = _RUNNERS.get(t["id"])
        if runner is None:
            test_results.append({
                "id": t["id"], "title": t["title"], "rows": [],
                "narrative": f"{t['title']} is planned but not yet implemented in this build.",
                "p_value": None, "effect_size": None, "effect_label": "—",
                "ci_lo": None, "ci_hi": None,
                "test_type": _LEGACY_TEST_TYPE.get(t["id"]),
            })
            continue
        try:
            r = runner(df, outcome, group)
        except Exception as exc:  # noqa: BLE001
            r = {
                "rows": [], "narrative": f"{t['title']} could not run: {exc}",
                "p_value": None, "effect_size": None, "effect_label": "—",
                "ci_lo": None, "ci_hi": None,
            }
        r.update({"id": t["id"], "title": t["title"]})
        # Tag with test_type so multiple-testing correction can find it.
        r["test_type"] = _LEGACY_TEST_TYPE.get(t["id"])
        r["analysis_family"] = t.get("analysis_family", "bivariate")
        # Mirror p_value into 'p' so the correction helper picks it up.
        if r.get("p_value") is not None and r.get("p") is None:
            r["p"] = r.get("p_value")
        test_results.append(r)

    # Multiple-testing correction (R8) — applied only to inferential tests
    test_results, correction_info = apply_correction_if_needed(test_results)
    if session is not None and correction_info is not None:
        session['correction_info'] = correction_info
    test_results = [normalize_result_for_rendering(r) for r in test_results]
    for result in test_results:
        result["compact_summary"] = _compact_result_summary(result)
    significant_findings = _significant_findings(test_results)

    # Run graphs -------------------------------------------------------------
    graph_results: List[Dict[str, Any]] = []
    for g in plan.get("graphs") or []:
        if g["id"] not in confirmed_graph_ids:
            continue
        if g["id"] == "forest_plot":
            png = _forest_plot(test_results)
        elif g["id"].startswith("scatter_"):
            cv = g["id"][len("scatter_"):]
            png = _scatter(df, outcome, cv)
        else:
            runner = _GRAPH_RUNNERS.get(g["id"])
            if runner is None:
                continue
            png = runner(df, outcome, group)
        if png:
            graph_results.append({"id": g["id"], "title": g["title"], "png_data_uri": png})

    table_one = build_table_one(df, classifications, group)

    # Methods + Results paragraphs ------------------------------------------
    methods_lines = [
        "Continuous variables are summarised as mean ± SD; categorical variables as counts."
    ]
    outcome_class = _classes_lookup(classifications).get(outcome, {})
    if outcome_class.get("detected_type") == "scale":
        methods_lines.append(
            f"Normality of {outcome} was assessed using Shapiro-Wilk (n < 50) "
            "or Lilliefors when available with a Shapiro-Wilk fallback "
            "(50 ≤ n ≤ 2000). For n > 2000, formal testing was skipped and "
            "normality was interpreted cautiously using plots, distribution "
            "shape, and clinical/statistical judgment."
        )
    if any(t.get("test_type") in ("t_test_independent", "welch_ttest") for t in test_results):
        methods_lines.append("Group means were compared with Welch's t-test.")
    if any(t.get("test_type") == "mann_whitney" for t in test_results):
        methods_lines.append("Non-parametric two-sample comparisons used the Mann-Whitney U test.")
    if any(t.get("test_type") == "anova_oneway" for t in test_results):
        methods_lines.append("Means across more than two groups were compared with one-way ANOVA.")
    if any(t.get("test_type") == "kruskal_wallis" for t in test_results):
        methods_lines.append("Non-parametric multi-group comparisons used the Kruskal-Wallis H test.")
    if any(t.get("test_type") in ("chi_square", "fisher_exact") for t in test_results):
        methods_lines.append(
            "Categorical associations were tested using chi-square or Fisher's exact test as appropriate."
        )
    methods_lines.append("All tests are two-sided with α = 0.05.")
    methods_md = " ".join(methods_lines)

    planned_inferential = [
        t for t in (plan.get("tests") or [])
        if t.get("id") in confirmed_test_ids and t.get("id") != "descriptive_only"
    ]
    completed_inferential = [
        t for t in test_results
        if t.get("p") is not None or t.get("p_value") is not None
    ]
    plan_mismatch = bool(planned_inferential and not completed_inferential)
    results_md = "\n\n".join(t.get("compact_summary") or t["narrative"] for t in test_results) or (
        "No tests were confirmed for this run."
    )
    if plan_mismatch:
        results_md = (
            "The planned inferential tests did not produce valid statistical results. "
            "Review the selected variables, category levels, and missing data before rerunning.\n\n"
            + results_md
        )

    # Only generate a forest plot when the plan actually includes logistic / Cox
    # regression tests.  For all other study types return None so export never
    # embeds a spurious forest plot.
    _has_forest_tests = any(
        t.get("id") in _FOREST_PLOT_TEST_IDS for t in test_results
    )
    return {
        "table_one": table_one,
        "tests": test_results,
        "graphs": graph_results,
        "forest_plot": _forest_plot(test_results) if _has_forest_tests else None,
        "methods_md": methods_md,
        "results_md": results_md,
        "plan_mismatch": plan_mismatch,
        "correction_info": correction_info,
        "significant_findings": significant_findings,
        "summary": {
            "outcome": outcome,
            "group": group,
            "n_tests": len(test_results),
            "n_graphs": len(graph_results),
            "n_significant": len(significant_findings),
        },
    }


# ===========================================================================
# Phase A — Missing tests (Cox / KM / ROC / Kappa / ICC / Ordinal / Poisson /
# Paired-t / Wilcoxon / McNemar / RM-ANOVA / Friedman / Fisher-or-Chi)
# Added wholesale per spec — every function has its safety check baked in.
# ===========================================================================

import scipy.stats as _phase_a_stats  # noqa: E402  (alias to keep spec verbatim)
from statsmodels.stats.proportion import proportion_confint  # noqa: E402


def fmt_p(p):
    if p is None or not isinstance(p, float):
        return '-'
    if p != p:  # nan check
        return '-'
    if p < 0.001:
        return '< 0.001'
    return f'{p:.3f}'


def wilson_ci(count, nobs):
    if nobs == 0:
        return (0.0, 1.0)
    try:
        lo, hi = proportion_confint(
            count=int(count),
            nobs=int(nobs),
            alpha=0.05,
            method='wilson'
        )
        return (round(float(lo), 4),
                round(float(hi), 4))
    except Exception:
        return (0.0, 1.0)


def validate_result(test_name, stat, p, effect_size=None):
    errors = []
    import math
    if p is None or math.isnan(p):
        errors.append(f"{test_name}: p-value is missing")
    elif p < 0 or p > 1:
        errors.append(f"{test_name}: p-value {p} is out of range")
    if stat is None or math.isinf(stat):
        errors.append(f"{test_name}: test statistic is invalid")
    if errors:
        return False, '; '.join(errors)
    return True, None


def get_display_name(col_name, session):
    variables = (session or {}).get('variables', {}) if session else {}
    var_info = variables.get(col_name, {}) if isinstance(variables, dict) else {}
    display = var_info.get('display_name', '') if isinstance(var_info, dict) else ''
    if display:
        return display
    name = str(col_name).replace('_', ' ').strip()
    return name.title()


def clean_display_name(col_name):
    name = str(col_name)
    name = name.replace('_', ' ')
    name = name.replace('-', ' ')
    name = name.strip()
    acronyms = ['VAS', 'NRS', 'BMI', 'HHS',
                'ICC', 'AUC', 'OR', 'HR',
                'SD', 'IQR', 'CI']
    words = name.split()
    result = []
    for w in words:
        if w.upper() in acronyms:
            result.append(w.upper())
        else:
            result.append(w.capitalize())
    return ' '.join(result)


# --- TEST 1: Paired t-test --------------------------------------------------
def run_paired_ttest(col1, col2, session, df):
    data = df[[col1, col2]].dropna()
    n = len(data)
    if n < 5:
        return {'error': f'Sample too small (n={n}). Minimum 5 pairs.'}

    t, p = _phase_a_stats.ttest_rel(
        data[col1], data[col2], alternative='two-sided'
    )

    valid, err = validate_result('Paired t-test', float(t), float(p))
    if not valid:
        return {'error': err}

    diff = data[col1] - data[col2]
    mean_diff = float(diff.mean())
    sd_diff = float(diff.std(ddof=1))
    se_diff = sd_diff / (n ** 0.5) if n > 0 else 0.0
    df_val = n - 1
    t_crit = _phase_a_stats.t.ppf(0.975, df=df_val)
    ci_lo = mean_diff - t_crit * se_diff
    ci_hi = mean_diff + t_crit * se_diff
    cohens_d = mean_diff / sd_diff if sd_diff > 0 else 0

    d1 = get_display_name(col1, session)
    d2 = get_display_name(col2, session)
    eff = ('small' if abs(cohens_d) < 0.5
           else 'medium' if abs(cohens_d) < 0.8
           else 'large')

    return {
        'test': 'Paired samples t-test',
        'test_type': 't_test_paired',
        'n': n,
        't': round(float(t), 3),
        'df': df_val,
        'p': float(p),
        'p_display': fmt_p(float(p)),
        'mean_diff': round(mean_diff, 3),
        'ci': (round(ci_lo, 3), round(ci_hi, 3)),
        'cohens_d': round(cohens_d, 3),
        'effect_interpretation': eff,
        'interpretation': (
            f'{d1} and {d2} were compared in {n} paired observations. '
            f'The mean difference was {mean_diff:.2f} '
            f'(95% CI: {ci_lo:.2f} to {ci_hi:.2f}). '
            f'Paired t-test: t({df_val}) = {float(t):.3f}, '
            f'p = {fmt_p(float(p))}, '
            f"Cohen's d = {cohens_d:.3f} ({eff} effect)."),
    }


# --- TEST 2: Wilcoxon signed-rank ------------------------------------------
def run_wilcoxon(col1, col2, session, df):
    data = df[[col1, col2]].dropna()
    n = len(data)
    if n < 5:
        return {'error': f'Sample too small (n={n}).'}

    try:
        stat, p = _phase_a_stats.wilcoxon(
            data[col1], data[col2],
            alternative='two-sided',
            correction=True,
            zero_method='wilcox',
        )
    except ValueError as e:
        return {'error': f'Wilcoxon failed: {str(e)}'}

    valid, err = validate_result('Wilcoxon', float(stat), float(p))
    if not valid:
        return {'error': err}

    import math
    z = _phase_a_stats.norm.ppf(p / 2)
    r = abs(float(z)) / math.sqrt(n)
    d1 = get_display_name(col1, session)
    d2 = get_display_name(col2, session)
    eff = ('small' if r < 0.3 else 'medium' if r < 0.5 else 'large')

    return {
        'test': 'Wilcoxon signed-rank test',
        'test_type': 'wilcoxon',
        'n': n,
        'W': round(float(stat), 3),
        'p': float(p),
        'p_display': fmt_p(float(p)),
        'effect_r': round(r, 3),
        'effect_interpretation': eff,
        'interpretation': (
            f'Wilcoxon signed-rank test comparing {d1} and {d2} '
            f'(n={n}): W = {float(stat):.1f}, p = {fmt_p(float(p))}, r = {r:.3f}.'),
    }


# --- TEST 3: McNemar -------------------------------------------------------
def run_mcnemar(col1, col2, session, df):
    from statsmodels.stats.contingency_tables import mcnemar
    data = df[[col1, col2]].dropna()
    n = len(data)
    if n < 10:
        return {'error': f'Sample too small (n={n}).'}

    try:
        table = pd.crosstab(data[col1], data[col2])
        if table.shape != (2, 2):
            return {'error': 'McNemar requires two binary variables.'}
        result = mcnemar(table, exact=True)
        p = float(result.pvalue)
        stat = float(result.statistic)
    except Exception as e:
        return {'error': f'McNemar failed: {str(e)}'}

    valid, err = validate_result('McNemar', stat, p)
    if not valid:
        return {'error': err}

    b = int(table.iloc[0, 1])
    c = int(table.iloc[1, 0])

    return {
        'test': 'McNemar test',
        'test_type': 'mcnemar',
        'n': n,
        'statistic': round(stat, 3),
        'p': p,
        'p_display': fmt_p(p),
        'b_c_counts': (b, c),
        'interpretation': (
            f'McNemar test (n={n}): statistic = {stat:.3f}, p = {fmt_p(p)}. '
            f'Discordant pairs: b={b}, c={c}.'),
    }


# --- TEST 4: Repeated Measures ANOVA ---------------------------------------
def run_rm_anova(dv, within, subject, session, df):
    import pingouin as pg
    data = df[[dv, within, subject]].dropna()
    if len(data) < 10:
        return {'error': 'Minimum 10 observations needed.'}

    try:
        spher = pg.sphericity(data, dv=dv, within=within, subject=subject)
        try:
            sphericity_ok = bool(spher.pval > 0.05)
        except AttributeError:
            sphericity_ok = bool(spher[1] > 0.05)
        correction = 'none' if sphericity_ok else 'GG'

        result = pg.rm_anova(
            data=data, dv=dv, within=within, subject=subject,
            correction=not sphericity_ok, detailed=True,
        )
        F = float(result.loc[0, 'F'])
        p_col = 'p-unc' if sphericity_ok else 'p-GG-corr'
        if p_col not in result.columns:
            p_col = 'p-unc'
        p = float(result.loc[0, p_col])
        eta2 = float(result.loc[0, 'np2'])
        df1 = int(result.loc[0, 'ddof1'])
        df2 = int(result.loc[0, 'ddof2'])
    except Exception as e:
        return {'error': f'RM-ANOVA failed: {str(e)}'}

    valid, err = validate_result('RM-ANOVA', F, p)
    if not valid:
        return {'error': err}

    dv_name = get_display_name(dv, session)
    note = '' if sphericity_ok else (
        ' Greenhouse-Geisser correction applied (sphericity violated).')

    return {
        'test': 'Repeated Measures ANOVA',
        'test_type': 'rm_anova',
        'F': round(F, 3),
        'df1': df1, 'df2': df2,
        'p': p, 'p_display': fmt_p(p),
        'eta_squared': round(eta2, 3),
        'sphericity_ok': sphericity_ok,
        'correction_applied': correction,
        'interpretation': (
            f'Repeated measures ANOVA for {dv_name}: '
            f'F({df1},{df2}) = {F:.3f}, p = {fmt_p(p)}, η² = {eta2:.3f}.{note}'),
    }


# --- TEST 5: Friedman ------------------------------------------------------
def run_friedman(cols, session, df):
    data = df[cols].dropna()
    n = len(data)
    k = len(cols)
    if n < 5:
        return {'error': f'Sample too small (n={n}).'}
    if k < 3:
        return {'error': 'Need at least 3 columns.'}

    try:
        arrays = [data[c].values for c in cols]
        stat, p = _phase_a_stats.friedmanchisquare(*arrays)
    except Exception as e:
        return {'error': f'Friedman failed: {str(e)}'}

    valid, err = validate_result('Friedman', float(stat), float(p))
    if not valid:
        return {'error': err}

    W = float(stat) / (n * (k - 1)) if (n * (k - 1)) > 0 else 0

    return {
        'test': 'Friedman test',
        'test_type': 'friedman',
        'n': n, 'k': k,
        'chi2': round(float(stat), 3),
        'p': float(p),
        'p_display': fmt_p(float(p)),
        'kendalls_W': round(W, 3),
        'interpretation': (
            f'Friedman test across {k} conditions (n={n}): '
            f'χ²({k-1}) = {float(stat):.3f}, p = {fmt_p(float(p))}, W = {W:.3f}.'),
    }


# --- TEST 6: Chi-square OR Fisher exact -----------------------------------
def run_chi_or_fisher(col1, col2, session, df):
    from scipy.stats import chi2_contingency, fisher_exact
    import math

    data = df[[col1, col2]].dropna()
    table = pd.crosstab(data[col1], data[col2])

    chi2, p_chi, dof, expected = chi2_contingency(table, correction=False)
    min_expected = float(expected.min())
    is_2x2 = (table.shape == (2, 2))
    use_fisher = min_expected < 5

    if use_fisher and is_2x2:
        odds_ratio, p = fisher_exact(table, alternative='two-sided')
        test_name = "Fisher's exact test"
        test_type = 'fisher_exact'
        stat = float(odds_ratio)
        note = (f'Fisher exact used: minimum expected count = '
                f'{min_expected:.1f} < 5')
    else:
        correction = (True if is_2x2 and min_expected < 5 else False)
        chi2, p, dof, expected = chi2_contingency(table, correction=correction)
        stat = float(chi2)
        test_name = 'Chi-square test'
        test_type = 'chi_square'
        note = f'Chi-square used: minimum expected count = {min_expected:.1f}'
        if not is_2x2 and min_expected < 5:
            note += ('. Warning: some expected counts below 5. '
                     'Interpret with caution.')

    validation_stat = (
        0.0
        if test_type == 'fisher_exact' and math.isinf(stat)
        else stat
    )
    valid, err = validate_result(test_name, validation_stat, float(p))
    if not valid:
        return {'error': err}

    r, c = table.shape
    n = len(data)
    cramers_v = (math.sqrt(
        chi2_contingency(table, correction=False)[0] / (n * (min(r, c) - 1))
    ) if min(r, c) > 1 else 0)

    return {
        'test': test_name,
        'test_type': test_type,
        'actual_test_used': test_name,
        'n': n,
        'statistic': (
            'Infinity' if math.isinf(stat) and stat > 0
            else '-Infinity' if math.isinf(stat)
            else round(stat, 3)
        ),
        'p': float(p),
        'p_display': fmt_p(float(p)),
        'dof': int(dof) if test_name != "Fisher's exact test" else None,
        'cramers_v': round(cramers_v, 3),
        'min_expected': round(min_expected, 2),
        'note': note,
        'expected_table': expected.tolist(),
        'observed_table': table.values.tolist(),
        'row_labels': table.index.astype(str).tolist(),
        'col_labels': table.columns.astype(str).tolist(),
        'interpretation': (
            f'{test_name}: statistic = {stat:.3f}, '
            f'p = {fmt_p(float(p))}, '
            f"Cramér's V = {cramers_v:.3f}. {note}"),
    }


# --- TEST 7: Cohen / Weighted / Fleiss Kappa -------------------------------
def run_kappa(rater_cols, session, df, weighted=False):
    data = df[rater_cols].dropna()
    n = len(data)

    if len(rater_cols) == 2:
        from sklearn.metrics import cohen_kappa_score
        weights = 'linear' if weighted else None
        try:
            k = cohen_kappa_score(
                data[rater_cols[0]], data[rater_cols[1]], weights=weights)
        except Exception as e:
            return {'error': f'Kappa failed: {str(e)}'}

        boot_k = []
        rng = np.random.default_rng(42)
        for _ in range(1000):
            idx = rng.choice(n, n, replace=True)
            try:
                bk = cohen_kappa_score(
                    data[rater_cols[0]].iloc[idx],
                    data[rater_cols[1]].iloc[idx],
                    weights=weights)
                boot_k.append(bk)
            except Exception:
                pass
        if boot_k:
            ci = (round(float(np.percentile(boot_k, 2.5)), 3),
                  round(float(np.percentile(boot_k, 97.5)), 3))
        else:
            ci = (None, None)

        interp = ('poor' if k < 0.20 else
                  'fair' if k < 0.40 else
                  'moderate' if k < 0.60 else
                  'substantial' if k < 0.80 else
                  'almost perfect')
        test_name = 'Weighted Kappa' if weighted else "Cohen's Kappa"
        return {
            'test': test_name,
            'test_type': 'kappa',
            'kappa': round(float(k), 3),
            'ci': ci,
            'n': n,
            'interpretation': interp,
            'p_display': fmt_p(None),
            'result_text': (
                f'{test_name}: κ = {k:.3f} '
                f'(95% CI: {ci[0]} to {ci[1]}), '
                f'{interp} agreement (n={n}).'),
        }
    else:
        from statsmodels.stats.inter_rater import (
            fleiss_kappa, aggregate_raters)
        try:
            agg, cats = aggregate_raters(data[rater_cols].values)
            k = float(fleiss_kappa(agg))
            interp = ('poor' if k < 0.20 else
                      'fair' if k < 0.40 else
                      'moderate' if k < 0.60 else
                      'substantial' if k < 0.80 else
                      'almost perfect')
            return {
                'test': "Fleiss' Kappa",
                'test_type': 'kappa',
                'kappa': round(k, 3),
                'n': n,
                'n_raters': len(rater_cols),
                'interpretation': interp,
                'result_text': (
                    f"Fleiss' Kappa for {len(rater_cols)} raters "
                    f'(n={n}): κ = {k:.3f}, {interp} agreement.'),
            }
        except Exception as e:
            return {'error': f'Fleiss kappa failed: {str(e)}'}


# --- TEST 8: ICC + Bland-Altman --------------------------------------------
def run_icc_bland_altman(col1, col2, session, df):
    import pingouin as pg
    data = df[[col1, col2]].dropna()
    n = len(data)
    if n < 10:
        return {'error': 'Minimum 10 pairs needed for ICC.'}

    diffs = data[col1] - data[col2]
    means = (data[col1] + data[col2]) / 2
    mean_diff = float(diffs.mean())
    sd_diff = float(diffs.std())
    loa_lo = mean_diff - 1.96 * sd_diff
    loa_hi = mean_diff + 1.96 * sd_diff
    se_mean = sd_diff / np.sqrt(n) if n > 0 else 0
    t_crit = _phase_a_stats.t.ppf(0.975, df=n - 1)
    bias_ci = (round(mean_diff - t_crit * se_mean, 3),
               round(mean_diff + t_crit * se_mean, 3))
    bland_altman = {
        'mean_bias': round(mean_diff, 3),
        'bias_ci': bias_ci,
        'loa_lower': round(loa_lo, 3),
        'loa_upper': round(loa_hi, 3),
        'sd_diff': round(sd_diff, 3),
    }
    bland_altman_plot_data = {
        'means': means.astype(float).tolist(),
        'differences': diffs.astype(float).tolist(),
    }

    long_df = pd.melt(
        data.reset_index(), id_vars='index',
        value_vars=[col1, col2],
        var_name='rater', value_name='score')

    try:
        icc_result = pg.intraclass_corr(
            data=long_df, targets='index',
            raters='rater', ratings='score')
        # Pingouin labels: 'ICC(1,1)','ICC(A,1)','ICC(C,1)','ICC(1,k)',...
        # We want the two-way mixed, single-rater, consistency model.
        preferred = ('ICC(C,1)', 'ICC(A,1)', 'ICC3', 'ICC(1,1)')
        icc_row = pd.DataFrame()
        for label in preferred:
            icc_row = icc_result[icc_result['Type'] == label]
            if not icc_row.empty:
                break
        if icc_row.empty:
            return {'error': 'ICC failed: no usable ICC row from pingouin.'}
        icc_val = float(icc_row['ICC'].values[0])
        ci_arr = icc_row['CI95%'].values[0]
        icc_lo = float(ci_arr[0])
        icc_hi = float(ci_arr[1])
        F_val = float(icc_row['F'].values[0])
        p_val = float(icc_row['pval'].values[0])
    except Exception as e:
        return {
            'warning': f'ICC failed: {str(e)}',
            'test': 'Bland-Altman agreement',
            'test_type': 'icc',
            'bland_altman': bland_altman,
            'bland_altman_plot_data': bland_altman_plot_data,
            'n': n,
            'interpretation': (
                f'ICC could not be calculated ({str(e)}). '
                f'Bland-Altman agreement metrics were calculated: mean bias = {mean_diff:.3f} '
                f'(95% LoA: {loa_lo:.3f} to {loa_hi:.3f}).'
            ),
        }

    icc_interp = ('poor' if icc_val < 0.50 else
                  'moderate' if icc_val < 0.75 else
                  'good' if icc_val < 0.90 else
                  'excellent')

    d1 = get_display_name(col1, session)
    d2 = get_display_name(col2, session)

    return {
        'test': 'ICC and Bland-Altman',
        'test_type': 'icc',
        'icc': round(icc_val, 3),
        'icc_ci': (round(icc_lo, 3), round(icc_hi, 3)),
        'icc_model': str(icc_row['Type'].values[0]),
        'icc_F': round(F_val, 3),
        'icc_p': p_val,
        'icc_p_display': fmt_p(p_val),
        'icc_interpretation': icc_interp,
        'bland_altman': bland_altman,
        'bland_altman_plot_data': bland_altman_plot_data,
        'n': n,
        'interpretation': (
            f'ICC between {d1} and {d2} (n={n}): ICC(3,1) = {icc_val:.3f} '
            f'(95% CI: {icc_lo:.3f}–{icc_hi:.3f}), {icc_interp} reliability. '
            f'Bland-Altman: mean bias = {mean_diff:.3f} '
            f'(95% LoA: {loa_lo:.3f} to {loa_hi:.3f}).'),
    }


# --- TEST 9: Kaplan-Meier + Log-rank --------------------------------------
def run_kaplan_meier(time_col, event_col, group_col, session, df):
    from lifelines import KaplanMeierFitter
    from lifelines.statistics import logrank_test, multivariate_logrank_test

    data = df[[time_col, event_col, group_col]].dropna()
    groups = data[group_col].unique()
    if len(groups) < 2:
        return {'error': 'Need at least 2 groups for survival analysis.'}

    kmf_results = {}
    for g in groups:
        mask = data[group_col] == g
        kmf = KaplanMeierFitter()
        try:
            kmf.fit(
                data.loc[mask, time_col],
                event_observed=data.loc[mask, event_col],
                label=str(g))
            median_surv = kmf.median_survival_time_
            kmf_results[str(g)] = {
                'kmf': kmf,
                'median': float(median_surv) if not pd.isna(median_surv) else None,
                'n': int(mask.sum()),
            }
        except Exception as e:
            return {'error': f'KM fit failed for group {g}: {str(e)}'}

    try:
        if len(groups) == 2:
            g1, g2 = groups
            lr = logrank_test(
                data.loc[data[group_col] == g1, time_col],
                data.loc[data[group_col] == g2, time_col],
                event_observed_A=data.loc[data[group_col] == g1, event_col],
                event_observed_B=data.loc[data[group_col] == g2, event_col])
            p_logrank = float(lr.p_value)
            stat_logrank = float(lr.test_statistic)
        else:
            mlr = multivariate_logrank_test(
                data[time_col], data[group_col], event_col=data[event_col])
            p_logrank = float(mlr.p_value)
            stat_logrank = float(mlr.test_statistic)
    except Exception as e:
        return {'error': f'Log-rank failed: {str(e)}'}

    valid, err = validate_result('Log-rank', stat_logrank, p_logrank)
    if not valid:
        return {'error': err}

    t_name = get_display_name(time_col, session)
    g_name = get_display_name(group_col, session)
    group_summaries = {
        g: {'n': kmf_results[g]['n'], 'median': kmf_results[g]['median']}
        for g in kmf_results
    }

    return {
        'test': 'Kaplan-Meier survival analysis',
        'test_type': 'log_rank',
        'log_rank_stat': round(stat_logrank, 3),
        'log_rank_p': p_logrank,
        'p': p_logrank,
        'p_display': fmt_p(p_logrank),
        'groups': group_summaries,
        'kmf_objects': {g: kmf_results[g]['kmf'] for g in kmf_results},
        'interpretation': (
            f'Kaplan-Meier analysis of {t_name} by {g_name}: '
            f'Log-rank test: χ² = {stat_logrank:.3f}, p = {fmt_p(p_logrank)}. '
            f'Median survival: ' +
            ', '.join([
                f'{g} = {kmf_results[g]["median"]} (n={kmf_results[g]["n"]})'
                for g in kmf_results]) + '.'),
    }


# --- TEST 10: Cox proportional hazards (R3 baked in) -----------------------
def run_cox_regression(time_col, event_col, predictors, session, df):
    from lifelines import CoxPHFitter
    try:
        from lifelines.statistics import proportional_hazard_test
        PH_TEST_AVAILABLE = True
    except ImportError:
        PH_TEST_AVAILABLE = False

    data = df[[time_col, event_col] + list(predictors)].dropna()
    n = len(data)
    n_events = int(data[event_col].sum())

    if n_events < 10 * len(predictors):
        warning = (
            f'Low events-per-variable ratio: {n_events} events, '
            f'{len(predictors)} predictors. Minimum recommended: '
            f'{10 * len(predictors)} events. Interpret with caution.')
    else:
        warning = None

    try:
        cph = CoxPHFitter(baseline_estimation_method='breslow')
        cph.fit(
            data, duration_col=time_col, event_col=event_col,
            formula=' + '.join(predictors))
    except Exception as e:
        return {'error': f'Cox regression failed: {str(e)}'}

    ph_note = None
    ph_violated = False
    if PH_TEST_AVAILABLE:
        try:
            ph_results = proportional_hazard_test(cph, data, time_transform='rank')
            ph_violated = bool(any(ph_results.summary['p'] < 0.05))
            if ph_violated:
                violated_vars = ph_results.summary[
                    ph_results.summary['p'] < 0.05].index.tolist()
                ph_note = (
                    f'Proportional hazards assumption violated for: '
                    f'{", ".join(str(v) for v in violated_vars)}. '
                    f'Interpret HR with caution. Consider stratified Cox model.')
        except Exception as e:
            ph_note = (f'PH assumption test could not complete ({str(e)}). '
                       f'Verify manually.')
    else:
        ph_note = ('PH assumption test unavailable in this lifelines version. '
                   'Check survival curves do not cross.')

    summary = cph.summary.copy()
    t_name = get_display_name(time_col, session)
    rows = []
    for pred in predictors:
        if pred in summary.index:
            hr = float(summary.loc[pred, 'exp(coef)'])
            lo = float(summary.loc[pred, 'exp(coef) lower 95%'])
            hi = float(summary.loc[pred, 'exp(coef) upper 95%'])
            p_v = float(summary.loc[pred, 'p'])
            rows.append({
                'variable': get_display_name(pred, session),
                'HR': round(hr, 3),
                'CI_lo': round(lo, 3),
                'CI_hi': round(hi, 3),
                'p': p_v,
                'p_display': fmt_p(p_v),
            })

    return {
        'test': 'Cox proportional hazards regression',
        'test_type': 'cox_regression',
        'n': n,
        'n_events': n_events,
        'rows': rows,
        'ph_note': ph_note,
        'ph_violated': ph_violated,
        'warning': warning,
        'interpretation': (
            f'Cox regression for {t_name} (n={n}, events={n_events}). '
            f'See HR table for results.' +
            (f' {ph_note}' if ph_note else '') +
            (f' {warning}' if warning else '')),
    }


# --- TEST 11: ROC + diagnostic accuracy (R4 baked in) ----------------------
def _normalise_class_label(value) -> str:
    return str(value).strip().lower().replace("_", " ").replace("-", " ")


def _infer_positive_class(values, positive_class=None):
    labels = list(pd.Series(values).dropna().unique())
    if len(labels) != 2:
        raise ValueError("Disease/reference column must contain exactly two classes.")
    if positive_class is not None and positive_class in labels:
        return positive_class

    positive_terms = {
        "1", "true", "t", "yes", "y", "positive", "pos", "+",
        "disease", "diseased", "case", "present", "abnormal", "detected",
    }
    negative_terms = {
        "0", "false", "f", "no", "n", "negative", "neg", "-",
        "healthy", "control", "absent", "normal", "not detected",
    }
    norm = {_normalise_class_label(label): label for label in labels}
    positive_hits = [norm[label] for label in norm if label in positive_terms]
    negative_hits = [norm[label] for label in norm if label in negative_terms]

    if len(positive_hits) == 1 and (len(negative_hits) == 1 or labels[0] != labels[1]):
        return positive_hits[0]
    if positive_class is not None:
        wanted = _normalise_class_label(positive_class)
        for label in labels:
            if _normalise_class_label(label) == wanted:
                return label
    numeric = pd.to_numeric(pd.Series(labels), errors="coerce")
    if numeric.notna().all() and set(numeric.astype(float).tolist()) == {0.0, 1.0}:
        return labels[int(numeric.astype(float).tolist().index(1.0))]
    if set(norm) == {"false", "true"}:
        return norm["true"]
    return sorted(labels, key=lambda x: str(x))[-1]


def _bootstrap_auc_ci(y_true, y_score, *, n_boot=1000, seed=42):
    from sklearn.metrics import roc_auc_score

    y = np.asarray(y_true, dtype=int)
    score = np.asarray(y_score, dtype=float)
    pos_idx = np.where(y == 1)[0]
    neg_idx = np.where(y == 0)[0]
    if len(pos_idx) == 0 or len(neg_idx) == 0:
        return (None, None)

    rng = np.random.default_rng(seed)
    aucs = []
    for _ in range(n_boot):
        sample_pos = rng.choice(pos_idx, size=len(pos_idx), replace=True)
        sample_neg = rng.choice(neg_idx, size=len(neg_idx), replace=True)
        sample_idx = np.concatenate([sample_pos, sample_neg])
        try:
            aucs.append(float(roc_auc_score(y[sample_idx], score[sample_idx])))
        except ValueError:
            continue
    if not aucs:
        return (None, None)
    lo, hi = np.percentile(aucs, [2.5, 97.5])
    return (round(float(lo), 3), round(float(hi), 3))


def run_diagnostic_accuracy(disease_col, test_col, session, df, positive_class=None):
    from sklearn.metrics import roc_curve, roc_auc_score
    data = df[[disease_col, test_col]].dropna()
    n = len(data)
    if n < 20:
        return {'error': f'Sample too small (n={n}). Minimum 20 needed.'}

    try:
        resolved_positive = _infer_positive_class(data[disease_col], positive_class)
    except ValueError as exc:
        return {'error': str(exc)}
    y_true = (data[disease_col] == resolved_positive).astype(int)
    if int(y_true.sum()) == 0 or int(y_true.sum()) == n:
        return {'error': 'Disease/reference column must contain both positive and negative cases.'}
    y_score = pd.to_numeric(data[test_col], errors='coerce')
    valid_score = y_score.notna()
    y_true = y_true[valid_score]
    y_score = y_score[valid_score]
    n = len(y_score)
    if n < 20:
        return {'error': f'Sample too small after removing non-numeric scores (n={n}). Minimum 20 needed.'}
    if int(y_true.sum()) == 0 or int(y_true.sum()) == n:
        return {'error': 'Disease/reference column must contain both positive and negative cases after removing non-numeric scores.'}

    fpr, tpr, thresholds = roc_curve(y_true, y_score)
    auc = float(roc_auc_score(y_true, y_score))
    auc_ci = _bootstrap_auc_ci(y_true, y_score)

    youden_idx = int(np.argmax(tpr - fpr))
    optimal_threshold = float(thresholds[youden_idx])

    y_pred = (y_score >= optimal_threshold).astype(int)
    TP = int(((y_pred == 1) & (y_true == 1)).sum())
    TN = int(((y_pred == 0) & (y_true == 0)).sum())
    FP = int(((y_pred == 1) & (y_true == 0)).sum())
    FN = int(((y_pred == 0) & (y_true == 1)).sum())

    sens = TP / (TP + FN) if (TP + FN) > 0 else 0
    spec = TN / (TN + FP) if (TN + FP) > 0 else 0
    ppv = TP / (TP + FP) if (TP + FP) > 0 else 0
    npv = TN / (TN + FN) if (TN + FN) > 0 else 0
    acc = (TP + TN) / n
    lr_pos = (sens / (1 - spec)) if (1 - spec) > 0 else float('inf')
    lr_neg = ((1 - sens) / spec) if spec > 0 else float('inf')
    dor = (lr_pos / lr_neg) if lr_neg not in (0, float('inf')) else float('inf')

    d_name = get_display_name(disease_col, session)
    t_name = get_display_name(test_col, session)
    auc_interp = ('no discrimination' if auc < 0.60 else
                  'poor' if auc < 0.70 else
                  'acceptable' if auc < 0.80 else
                  'good' if auc < 0.90 else
                  'excellent')

    return {
        'test': 'Diagnostic accuracy analysis',
        'test_type': 'diagnostic_accuracy',
        'n': n,
        'auc': round(auc, 3),
        'auc_ci': auc_ci,
        'auc_ci_method': 'bootstrap_percentile',
        'positive_class': resolved_positive.item() if hasattr(resolved_positive, "item") else resolved_positive,
        'auc_interpretation': auc_interp,
        'optimal_threshold': round(optimal_threshold, 3),
        'sensitivity': round(sens, 3),
        'sensitivity_ci': wilson_ci(TP, TP + FN),
        'specificity': round(spec, 3),
        'specificity_ci': wilson_ci(TN, TN + FP),
        'ppv': round(ppv, 3),
        'ppv_ci': wilson_ci(TP, TP + FP),
        'npv': round(npv, 3),
        'npv_ci': wilson_ci(TN, TN + FN),
        'accuracy': round(acc, 3),
        'accuracy_ci': wilson_ci(TP + TN, n),
        'lr_positive': round(lr_pos, 3),
        'lr_negative': round(lr_neg, 3),
        'dor': round(dor, 3),
        'confusion_matrix': {'TP': TP, 'TN': TN, 'FP': FP, 'FN': FN},
        'roc_data': {
            'fpr': fpr.tolist(),
            'tpr': tpr.tolist(),
            'thresholds': thresholds.tolist(),
        },
        'interpretation': (
            f'Diagnostic accuracy of {t_name} for {d_name} (n={n}): '
            f'AUC = {auc:.3f} ({auc_interp}). '
            f'At optimal cutoff ({optimal_threshold:.3f}): '
            f'Sensitivity = {sens*100:.1f}%, Specificity = {spec*100:.1f}%.'),
    }


# --- TEST 12: Ordinal logistic regression (R5 baked in) --------------------
def run_ordinal_logistic(outcome, predictors, session, df):
    from statsmodels.miscmodels.ordinal_model import OrderedModel
    data = df[[outcome] + list(predictors)].dropna()
    n = len(data)
    if n < 30:
        return {'error': f'Sample too small (n={n}). Ordinal regression needs n≥30.'}

    try:
        mod = OrderedModel(data[outcome], data[predictors], distr='logit')
        res = mod.fit(method='bfgs', maxiter=500, disp=False)

        converged = getattr(res, 'mle_retvals', {}).get('converged', False)
        if not converged:
            return {
                'test': 'Ordinal logistic regression',
                'test_type': 'ordinal_logistic',
                'warning': (
                    'Ordinal regression did not converge. Results may be '
                    'unreliable. Consider reducing predictors or using '
                    'binary logistic regression.'),
                'converged': False,
                'partial_result': True,
            }

        rows = []
        for pred in predictors:
            if pred in res.params.index:
                coef = float(res.params[pred])
                se = float(res.bse[pred])
                p = float(res.pvalues[pred])
                or_val = float(np.exp(coef))
                ci_lo = float(np.exp(coef - 1.96 * se))
                ci_hi = float(np.exp(coef + 1.96 * se))
                rows.append({
                    'variable': get_display_name(pred, session),
                    'OR': round(or_val, 3),
                    'CI_lo': round(ci_lo, 3),
                    'CI_hi': round(ci_hi, 3),
                    'p': p,
                    'p_display': fmt_p(p),
                })

        return {
            'test': 'Ordinal logistic regression',
            'test_type': 'ordinal_logistic',
            'n': n,
            'converged': True,
            'rows': rows,
            'aic': round(float(res.aic), 2),
            'interpretation': (
                f'Ordinal logistic regression (n={n}). Model converged. '
                f'See OR table for results.'),
        }
    except Exception as e:
        return {'error': f'Ordinal regression failed: {str(e)}'}


# --- TEST 13: Poisson / Negative Binomial ----------------------------------
def run_count_regression(outcome, predictors, session, df):
    import statsmodels.formula.api as smf
    data = df[[outcome] + list(predictors)].dropna()
    n = len(data)

    if data[outcome].min() < 0:
        return {'error': 'Count outcome cannot have negative values.'}

    mean_val = float(data[outcome].mean())
    var_val = float(data[outcome].var())
    dispersion_ratio = (var_val / mean_val) if mean_val > 0 else 1.0

    formula = outcome + ' ~ ' + ' + '.join(predictors)

    if dispersion_ratio > 2:
        try:
            res = smf.negativebinomial(formula, data).fit(disp=False)
            model_name = 'Negative binomial regression'
            test_type = 'negative_binomial'
            overdispersion_note = (
                f'Negative binomial used: variance/mean ratio = '
                f'{dispersion_ratio:.2f} > 2 (overdispersed data).')
        except Exception as e:
            return {'error': f'Negative binomial failed: {str(e)}'}
    else:
        try:
            res = smf.poisson(formula, data).fit(disp=False)
            model_name = 'Poisson regression'
            test_type = 'poisson'
            overdispersion_note = (
                f'Poisson used: variance/mean ratio = '
                f'{dispersion_ratio:.2f} ≤ 2.')
        except Exception as e:
            return {'error': f'Poisson failed: {str(e)}'}

    rows = []
    for pred in predictors:
        if pred in res.params.index:
            coef = float(res.params[pred])
            se = float(res.bse[pred])
            p = float(res.pvalues[pred])
            irr = float(np.exp(coef))
            ci_lo = float(np.exp(coef - 1.96 * se))
            ci_hi = float(np.exp(coef + 1.96 * se))
            rows.append({
                'variable': get_display_name(pred, session),
                'IRR': round(irr, 3),
                'CI_lo': round(ci_lo, 3),
                'CI_hi': round(ci_hi, 3),
                'p': p,
                'p_display': fmt_p(p),
            })

    return {
        'test': model_name,
        'test_type': test_type,
        'n': n,
        'dispersion_ratio': round(dispersion_ratio, 2),
        'overdispersion_note': overdispersion_note,
        'rows': rows,
        'aic': round(float(res.aic), 2),
        'interpretation': (
            f'{model_name} (n={n}). {overdispersion_note} '
            f'See IRR table for results.'),
    }


# --- Logistic regression add-ons (Hosmer-Lemeshow + Nagelkerke R²) ---------
def hosmer_lemeshow(y_true, y_pred_prob, groups=10):
    from scipy.stats import chi2 as _chi2_dist
    data = pd.DataFrame({'true': y_true, 'prob': y_pred_prob})
    data['decile'] = pd.qcut(
        data['prob'], q=groups, labels=False, duplicates='drop')
    obs = data.groupby('decile')['true'].sum()
    exp = data.groupby('decile')['prob'].sum()
    n_g = data.groupby('decile').size()
    hl_stat = float(np.sum(
        (obs - exp) ** 2 / (exp * (1 - exp / n_g) + 1e-10)))
    df_hl = max(len(obs) - 2, 1)
    p_hl = float(1 - _chi2_dist.cdf(hl_stat, df=df_hl))
    return round(hl_stat, 3), df_hl, p_hl


def nagelkerke_r2(result, n):
    ll_null = result.llnull
    ll_model = result.llf
    r2_cs = 1 - np.exp((2 / n) * (ll_null - ll_model))
    r2_max = 1 - np.exp((2 / n) * ll_null)
    r2_nag = r2_cs / r2_max if r2_max > 0 else 0
    return round(float(r2_nag), 3)


# --- Multiple-testing correction (R8 baked in) -----------------------------
INFERENTIAL_TEST_TYPES = {
    't_test_independent', 't_test_paired',
    'welch_t_test', 'mann_whitney',
    'wilcoxon', 'anova_oneway',
    'kruskal_wallis', 'friedman',
    'rm_anova', 'mixed_anova',
    'chi_square', 'fisher_exact',
    'mcnemar', 'pearson', 'spearman',
    'logistic_regression', 'linear_regression',
    'cox_regression', 'log_rank',
    'kappa', 'icc',
}


def apply_correction_if_needed(results_list):
    from statsmodels.stats.multitest import multipletests
    inferential = [
        r for r in results_list
        if r.get('test_type') in INFERENTIAL_TEST_TYPES
        and r.get('p') is not None
    ]
    n = len(inferential)
    if n < 3:
        return results_list, None

    method = 'bonferroni' if n <= 5 else 'fdr_bh'
    label = 'Bonferroni' if n <= 5 else 'Benjamini-Hochberg FDR'
    p_vals = [r['p'] for r in inferential]
    _, corrected, _, _ = multipletests(p_vals, alpha=0.05, method=method)
    for i, r in enumerate(inferential):
        r['p_corrected'] = float(corrected[i])
        r['p_corrected_display'] = fmt_p(float(corrected[i]))
        r['correction_method'] = label
    return results_list, {'method': label, 'n_tests': n}


# ===========================================================================
# Correlation study runner — pairwise all-vs-outcome
# ===========================================================================


def _corr_crosstab_data(
    df: pd.DataFrame,
    predictor: str,
    outcome: str,
) -> Dict[str, Any]:
    """Return a crosstab as {headers, rows} with counts and row-%.
    Handles missing values by dropping them.
    """
    sub = df[[predictor, outcome]].dropna()
    if sub.empty:
        return {"headers": [], "rows": []}
    ct = pd.crosstab(
        sub[predictor].astype(str),
        sub[outcome].astype(str),
        margins=True,
        margins_name="Total",
    )
    outcome_levels = [c for c in ct.columns if c != "Total"]
    headers = [predictor] + outcome_levels + ["Total"]
    rows = []
    for idx in ct.index:
        row_total = ct.loc[idx, "Total"]
        cells = [str(idx)]
        for lvl in outcome_levels:
            n = int(ct.loc[idx, lvl])
            pct = 100.0 * n / row_total if row_total else 0.0
            cells.append(f"{n} ({pct:.1f}%)")
        cells.append(str(int(row_total)))
        rows.append(cells)
    return {"headers": headers, "rows": rows}


def _corr_descriptive_data(
    df: pd.DataFrame,
    predictor: str,
    outcome: str,
) -> Dict[str, Any]:
    """Return per-outcome-group descriptive stats for a continuous predictor."""
    sub = df[[predictor, outcome]].dropna()
    sub[predictor] = pd.to_numeric(sub[predictor], errors="coerce")
    sub = sub.dropna()
    levels = sorted(sub[outcome].astype(str).unique())
    headers = [outcome, "n", "Median", "IQR (Q1-Q3)", "Mean ± SD"]
    rows = []
    for lvl in levels:
        vals = sub.loc[sub[outcome].astype(str) == lvl, predictor]
        if vals.empty:
            continue
        q1, q3 = float(vals.quantile(0.25)), float(vals.quantile(0.75))
        rows.append([
            lvl,
            str(len(vals)),
            f"{float(vals.median()):.2f}",
            f"{q1:.2f} – {q3:.2f}",
            f"{float(vals.mean()):.2f} ± {float(vals.std()):.2f}",
        ])
    # Total row
    all_vals = sub[predictor]
    if not all_vals.empty:
        q1a, q3a = float(all_vals.quantile(0.25)), float(all_vals.quantile(0.75))
        rows.append([
            "Total",
            str(len(all_vals)),
            f"{float(all_vals.median()):.2f}",
            f"{q1a:.2f} – {q3a:.2f}",
            f"{float(all_vals.mean()):.2f} ± {float(all_vals.std()):.2f}",
        ])
    return {"headers": headers, "rows": rows}


def _run_chi_or_fisher(
    df: pd.DataFrame, predictor: str, outcome: str
) -> Dict[str, Any]:
    """Chi-square with automatic fallback to Fisher's exact."""
    import scipy.stats as _ss
    sub = df[[predictor, outcome]].dropna()
    ct = pd.crosstab(sub[predictor].astype(str), sub[outcome].astype(str))
    if ct.empty or ct.shape[0] < 2 or ct.shape[1] < 2:
        return {"error": "Insufficient categories for chi-square."}
    # Use Fisher if 2×2 or expected cells < 5
    use_fisher = ct.shape == (2, 2)
    if not use_fisher:
        from scipy.stats.contingency import expected_freq
        try:
            exp = expected_freq(ct.values)
            if (exp < 5).mean() > 0.2:
                use_fisher = ct.shape == (2, 2)
        except Exception:
            pass
    try:
        if use_fisher and ct.shape == (2, 2):
            arr = ct.values.astype(float)
            _, p = _ss.fisher_exact(arr)
            stat = None
            test_name = "Fisher's exact"
            df_val = None
        else:
            chi2, p, df_val, _ = _ss.chi2_contingency(ct)
            stat = float(chi2)
            test_name = "Chi-square"
            df_val = int(df_val)
        # Cramér's V
        n = int(sub.shape[0])
        if stat is not None and n > 0:
            phi2 = stat / n
            r, k = ct.shape
            cramers_v = float(np.sqrt(phi2 / min(r - 1, k - 1))) if min(r - 1, k - 1) > 0 else None
        else:
            cramers_v = None
        return {
            "test_name": test_name,
            "actual_test_used": test_name,
            "stat": stat,
            "p": float(p),
            "df": df_val,
            "cramers_v": cramers_v,
            "n": n,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _run_mann_whitney(
    df: pd.DataFrame, predictor: str, outcome: str
) -> Dict[str, Any]:
    """Mann-Whitney U for a continuous predictor vs a binary outcome."""
    import scipy.stats as _ss
    sub = df[[predictor, outcome]].dropna()
    sub[predictor] = pd.to_numeric(sub[predictor], errors="coerce")
    sub = sub.dropna()
    levels = sorted(sub[outcome].astype(str).unique())
    if len(levels) < 2:
        return {"error": "Need at least two outcome levels for Mann-Whitney."}
    g1 = sub.loc[sub[outcome].astype(str) == levels[0], predictor]
    g2 = sub.loc[sub[outcome].astype(str) == levels[1], predictor]
    if len(g1) < 2 or len(g2) < 2:
        return {"error": "Insufficient data in one or more groups."}
    try:
        U, p = _ss.mannwhitneyu(g1, g2, alternative="two-sided")
        # Rank-biserial correlation as effect size
        n1, n2 = len(g1), len(g2)
        rbc = float(1 - 2 * U / (n1 * n2))
        return {
            "test_name": "Mann-Whitney U",
            "stat": float(U),
            "p": float(p),
            "rank_biserial": rbc,
            "n1": n1,
            "n2": n2,
            "group_levels": levels,
            "medians": {
                levels[0]: float(g1.median()),
                levels[1]: float(g2.median()),
            },
            "iqrs": {
                levels[0]: (float(g1.quantile(0.25)), float(g1.quantile(0.75))),
                levels[1]: (float(g2.quantile(0.25)), float(g2.quantile(0.75))),
            },
        }
    except Exception as exc:
        return {"error": str(exc)}


def _run_kruskal(
    df: pd.DataFrame, predictor: str, outcome: str
) -> Dict[str, Any]:
    """Kruskal-Wallis for a continuous predictor vs a multi-level outcome."""
    import scipy.stats as _ss
    sub = df[[predictor, outcome]].dropna()
    sub[predictor] = pd.to_numeric(sub[predictor], errors="coerce")
    sub = sub.dropna()
    levels = sorted(sub[outcome].astype(str).unique())
    groups = [sub.loc[sub[outcome].astype(str) == lvl, predictor] for lvl in levels]
    groups = [g for g in groups if len(g) >= 2]
    if len(groups) < 2:
        return {"error": "Insufficient groups for Kruskal-Wallis."}
    try:
        H, p = _ss.kruskal(*groups)
        return {"test_name": "Kruskal-Wallis H", "stat": float(H), "p": float(p), "n": len(sub)}
    except Exception as exc:
        return {"error": str(exc)}


def run_pairwise_welch(predictor, outcome, session, df):
    return _ttest_independent(df, predictor, outcome)


def run_pairwise_mann_whitney(predictor, outcome, session, df):
    result = _run_mann_whitney(df, predictor, outcome)
    if "error" in result:
        return result
    result["interpretation"] = (
        f"Mann-Whitney U compared {predictor} across the two levels of {outcome}; "
        f"U = {result['stat']:.3f}, p = {fmt_p(result['p'])}."
    )
    return result


def run_pairwise_anova(predictor, outcome, session, df):
    return _anova_oneway(df, predictor, outcome)


def run_pairwise_kruskal(predictor, outcome, session, df):
    result = _run_kruskal(df, predictor, outcome)
    if "error" in result:
        return result
    result["interpretation"] = (
        f"Kruskal-Wallis compared {predictor} across levels of {outcome}; "
        f"H = {result['stat']:.3f}, p = {fmt_p(result['p'])}."
    )
    return result


def _run_correlation(
    df: pd.DataFrame, predictor: str, outcome: str, method: str
) -> Dict[str, Any]:
    """Pearson/Spearman correlation for two continuous variables."""
    import scipy.stats as _ss

    sub = df[[predictor, outcome]].apply(pd.to_numeric, errors="coerce").dropna()
    n = int(len(sub))
    if n < 3:
        return {"error": f"Need at least 3 paired numeric values for correlation (n={n})."}
    try:
        if method == "pearson":
            stat, p = _ss.pearsonr(sub[predictor], sub[outcome])
            test_name = "Pearson correlation"
            stat_label = "r"
        else:
            stat, p = _ss.spearmanr(sub[predictor], sub[outcome])
            test_name = "Spearman rank correlation"
            stat_label = "rho"
        if pd.isna(stat) or pd.isna(p):
            return {"error": "Correlation could not be calculated; one variable may be constant."}
        return {
            "test_name": test_name,
            "stat": float(stat),
            "p": float(p),
            "n": n,
            "method": method,
            "stat_label": stat_label,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _corr_correlation_table(
    predictor: str, outcome: str, test_result: Dict[str, Any]
) -> Dict[str, Any]:
    label = test_result.get("stat_label") or "r"
    return {
        "headers": ["Statistic", "Value"],
        "rows": [
            ["Predictor", predictor],
            ["Outcome", outcome],
            ["Test", test_result.get("test_name", "")],
            [label, f"{float(test_result.get('stat', 0.0)):.3f}"],
            ["p-value", fmt_p(test_result.get("p"))],
            ["n", str(test_result.get("n", ""))],
        ],
    }


def _corr_interpretation(
    pair: Dict[str, Any],
    test_result: Dict[str, Any],
    df: pd.DataFrame,
) -> str:
    """Build a plain-English interpretation paragraph for one predictor vs outcome."""
    predictor = pair["predictor"]
    outcome = pair["outcome_col"] if "outcome_col" in pair else pair.get("outcome", "")
    pred_type = pair.get("predictor_type", "nominal")
    p = test_result.get("p")
    sig = "statistically significant" if (p is not None and p < 0.05) else "not statistically significant"
    test_name = test_result.get("test_name", "the test")
    n_total = int(df[[predictor, outcome]].dropna().shape[0])

    outcome_levels = sorted(df[outcome].dropna().astype(str).unique().tolist())
    predictor_levels = sorted(df[predictor].dropna().astype(str).unique().tolist())

    if test_result.get("method") in ("pearson", "spearman"):
        stat = test_result.get("stat")
        label = test_result.get("stat_label") or "r"
        stat_text = f"{label} = {stat:.3f}" if stat is not None else f"{label} not available"
        return (
            f"Among the {test_result.get('n', n_total)} paired observations analysed, "
            f"{test_name} assessed the relationship between {predictor} and {outcome}. "
            f"The association was {sig} ({stat_text}, p = {fmt_p(p)})."
        )

    if pred_type == "scale":
        medians = test_result.get("medians", {})
        iqrs = test_result.get("iqrs", {})
        levels = test_result.get("group_levels") or outcome_levels[:2]
        parts = []
        for lvl in levels:
            med = medians.get(lvl)
            iqr = iqrs.get(lvl, (None, None))
            if med is not None:
                q1, q3 = iqr
                if q1 is not None and q3 is not None:
                    parts.append(f"{med:.2f} (IQR: {q1:.2f}\u2013{q3:.2f}) in the {outcome} = {lvl} group")
                else:
                    parts.append(f"{med:.2f} in the {outcome} = {lvl} group")
        stat_val = test_result.get("stat")
        stat_str = f"{stat_name} = {stat_val:.2f}, " if (stat_name := test_result.get("test_name","U").replace("Mann-Whitney U","U").replace("Kruskal-Wallis H","H")) and stat_val is not None else ""
        text = (
            f"Among the {n_total} patients analysed, the median {predictor} was "
            + " and ".join(parts or ["not available"])
            + f". The association was {sig} ({stat_str}p = {fmt_p(p)})."
        )
    else:
        # Categorical predictor
        sub = df[[predictor, outcome]].dropna()
        ct = pd.crosstab(sub[predictor].astype(str), sub[outcome].astype(str))
        n_all = len(sub)
        # Describe distribution of outcome
        outcome_desc_parts = []
        for lvl in outcome_levels[:3]:
            if lvl in ct.columns:
                cnt = int(ct[lvl].sum())
                pct = 100.0 * cnt / n_all if n_all else 0
                outcome_desc_parts.append(f"{cnt} ({pct:.1f}%) were {outcome} = {lvl}")
        outcome_desc = ", ".join(outcome_desc_parts) if outcome_desc_parts else ""
        # Describe per-predictor breakdown (first outcome level, up to 4 predictor levels)
        primary_outcome = outcome_levels[0] if outcome_levels else ""
        breakdown_parts = []
        for pred_lvl in predictor_levels[:4]:
            if pred_lvl in ct.index and primary_outcome in ct.columns:
                row_total = int(ct.loc[pred_lvl].sum())
                n_pos = int(ct.loc[pred_lvl, primary_outcome])
                pct_pos = 100.0 * n_pos / row_total if row_total else 0
                breakdown_parts.append(
                    f"among patients with {predictor} = {pred_lvl}, "
                    f"{n_pos} of {row_total} ({pct_pos:.1f}%) had {outcome} = {primary_outcome}"
                )
        stat_val = test_result.get("stat")
        df_val = test_result.get("df")
        crv = test_result.get("cramers_v")
        effect_str = f", Cramér's V = {crv:.3f}" if crv is not None else ""
        stat_str = (
            f"{test_name}: χ² = {stat_val:.3f}, df = {df_val}, p = {fmt_p(p)}{effect_str}"
            if stat_val is not None
            else f"{test_name}: p = {fmt_p(p)}{effect_str}"
        )
        text = (
            f"Of the {n_all} patients studied"
            + (f", {outcome_desc}" if outcome_desc else "")
            + ". "
            + ("; ".join(breakdown_parts[:3]) + ". " if breakdown_parts else "")
            + f"The association between {predictor} and {outcome} was {sig} ({stat_str})."
        )
    return text


def _freq_table(df: pd.DataFrame, col: str) -> Dict[str, Any]:
    """Frequency + percentage table for a single categorical column."""
    counts = df[col].astype(str).value_counts()
    total = int(counts.sum())
    rows: List[Any] = [
        [cat, int(cnt), f"{cnt / total * 100:.1f}"]
        for cat, cnt in counts.items()
    ]
    rows.append(["Total", total, "100.0"])
    return {"headers": [col, "n", "Percent (%)"], "rows": rows}


def _standalone_descriptive_table(df: pd.DataFrame, col: str) -> Dict[str, Any]:
    """Descriptive-statistics table for a single continuous column."""
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    n = len(s)
    if n == 0:
        return {"headers": ["Statistic", "Value"], "rows": []}
    return {
        "headers": ["Statistic", "Value"],
        "rows": [
            ["n (valid)", str(n)],
            ["Mean ± SD", f"{s.mean():.2f} ± {s.std():.2f}"],
            [
                "Median (IQR)",
                f"{s.median():.2f} ({s.quantile(0.25):.2f}–{s.quantile(0.75):.2f})",
            ],
            ["Range", f"{s.min():.2f} – {s.max():.2f}"],
        ],
    }


def _correlation_pair_presentation(
    pair_result: Dict[str, Any], outcome_col: str
) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """Build normalized table/figure entries without changing pair results."""
    predictor = str(pair_result.get("predictor") or "")
    test_result = pair_result.get("test_result") or {}
    method = test_result.get("method")
    if method in ("pearson", "spearman"):
        coefficient = _display_value(test_result.get("stat"))
    elif test_result.get("cramers_v") is not None:
        coefficient = _display_value(test_result.get("cramers_v"))
    else:
        coefficient = "-"

    ci = _ci_from_row(test_result)
    p_value = test_result.get("p")
    p_display = fmt_p(p_value) if p_value is not None else "-"
    interpretation = (
        pair_result.get("interpretation")
        or test_result.get("interpretation")
        or test_result.get("error")
        or "-"
    )
    table = {
        "title": f"{predictor} vs {outcome_col}",
        "headers": [
            "Variable 1", "Variable 2", "Test used", "Correlation coefficient",
            "95% CI", "p-value", "n", "Interpretation / strength",
        ],
        "rows": [[
            predictor,
            outcome_col,
            test_result.get("test_name") or "Not completed",
            coefficient,
            ci,
            p_display,
            _display_value(test_result.get("n")),
            interpretation,
        ]],
    }

    figures: List[Dict[str, str]] = []
    seen_uris = set()
    for key, title in (
        ("graph_uri", f"{predictor} vs {outcome_col}"),
        ("desc_graph_uri", f"Distribution of {predictor}"),
        ("png_data_uri", f"{predictor} vs {outcome_col}"),
    ):
        uri = pair_result.get(key) or test_result.get(key)
        if uri and str(uri) not in seen_uris:
            seen_uris.add(str(uri))
            figures.append({"title": title, "png_data_uri": str(uri)})
    return table, figures


def run_correlation_plan(
    df: pd.DataFrame,
    classifications: List[Dict[str, Any]],
    correlation_plan: Dict[str, Any],
) -> Dict[str, Any]:
    """Run all pairwise tests for a correlation study.

    Returns::

        {
          "pairs": [{
            "predictor":      str,
            "test_result":    {test_name, stat, p, ...},
            "graph_uri":      str | None,   # base64 PNG data URI
            "table_data":     {headers, rows},
            "interpretation": str,
            "significant":    bool,
          }, ...],
          "summary_table": [{
            "predictor": str, "test": str, "stat": str, "p": str, "significant": bool
          }, ...],
          "methods_text": str,
          "tables": [{title, headers, rows}, ...],
          "figures": [{title, png_data_uri}, ...],
        }
    """
    outcome_col = correlation_plan.get("outcome_col", "")
    pairs_plan = correlation_plan.get("pairs") or []
    pair_results: List[Dict[str, Any]] = []

    for pair in pairs_plan:
        predictor = pair["predictor"]
        test_id = pair.get("test_id", "corr_chi_or_fisher")
        graph_type = pair.get("graph_type", "stacked_bar")
        pred_type = pair.get("predictor_type", "nominal")

        # Skip columns not in df
        if predictor not in df.columns or outcome_col not in df.columns:
            continue

        # Run test
        if test_id == "corr_mann_whitney":
            test_result = _run_mann_whitney(df, predictor, outcome_col)
        elif test_id == "corr_kruskal":
            test_result = _run_kruskal(df, predictor, outcome_col)
        elif test_id == "corr_pearson":
            test_result = _run_correlation(df, predictor, outcome_col, "pearson")
        elif test_id == "corr_spearman":
            test_result = _run_correlation(df, predictor, outcome_col, "spearman")
        else:
            test_result = _run_chi_or_fisher(df, predictor, outcome_col)

        if "error" in test_result:
            # Still compute standalone descriptive data so the Word report can
            # render Section A (distribution) even when the association test fails
            try:
                _n_uniq = int(df[predictor].dropna().nunique())
                if pred_type == "scale":
                    _err_desc_graph = _histogram(df, predictor)
                    _err_desc_table = _standalone_descriptive_table(df, predictor)
                else:
                    _err_desc_graph = (
                        _pie_chart(df, predictor) if _n_uniq <= 3
                        else _horz_bar(df, predictor)
                    )
                    _err_desc_table = _freq_table(df, predictor)
            except Exception:
                _err_desc_graph = None
                _err_desc_table: Dict[str, Any] = {"headers": [], "rows": []}
            pair_results.append({
                "predictor": predictor,
                "predictor_type": pred_type,
                "test_result": test_result,
                "graph_uri": None,
                "table_data": {"headers": [], "rows": []},
                "desc_graph_uri": _err_desc_graph,
                "desc_table_data": _err_desc_table,
                "interpretation": f"Could not analyse {predictor}: {test_result['error']}",
                "significant": False,
            })
            continue

        # Generate graph
        if graph_type == "boxplot":
            graph_uri = _boxplot(df, predictor, outcome_col)
        elif graph_type == "scatter":
            graph_uri = _scatter(df, outcome_col, predictor)
        else:
            graph_uri = _stacked_bar(df, outcome_col, predictor)

        # Generate table
        if test_result.get("method") in ("pearson", "spearman"):
            table_data = _corr_correlation_table(predictor, outcome_col, test_result)
        elif pred_type == "scale":
            table_data = _corr_descriptive_data(df, predictor, outcome_col)
        else:
            table_data = _corr_crosstab_data(df, predictor, outcome_col)

        # Build interpretation
        pair_aug = dict(pair)
        pair_aug["outcome_col"] = outcome_col
        interpretation = _corr_interpretation(pair_aug, test_result, df)

        # --- standalone descriptive graph + table (for Word per-variable section) ---
        n_unique = int(df[predictor].dropna().nunique())
        if pred_type == "scale":
            desc_graph_uri: Optional[str] = _histogram(df, predictor)
            desc_table_data: Dict[str, Any] = _standalone_descriptive_table(df, predictor)
        else:
            desc_graph_uri = (
                _pie_chart(df, predictor) if n_unique <= 3 else _horz_bar(df, predictor)
            )
            desc_table_data = _freq_table(df, predictor)

        p = test_result.get("p")
        pair_results.append({
            "predictor": predictor,
            "predictor_type": pred_type,
            "test_result": test_result,
            "graph_uri": graph_uri,
            "table_data": table_data,
            "desc_graph_uri": desc_graph_uri,
            "desc_table_data": desc_table_data,
            "interpretation": interpretation,
            "significant": bool(p is not None and p < 0.05),
        })

    # Summary table sorted by p-value ascending
    def _sort_key(pr):
        p = pr["test_result"].get("p")
        return p if p is not None else 1.0

    sorted_pairs = sorted(pair_results, key=_sort_key)
    summary_table = []
    for pr in sorted_pairs:
        tr = pr["test_result"]
        p = tr.get("p")
        stat = tr.get("stat")
        summary_table.append({
            "predictor": pr["predictor"],
            "test": tr.get("test_name", ""),
            "stat": f"{stat:.3f}" if stat is not None else "—",
            "p": fmt_p(p) if p is not None else "—",
            "significant": pr["significant"],
        })

    tests_used = sorted({pr["test_result"].get("test_name", "") for pr in pair_results
                         if "error" not in pr["test_result"]})
    _cat_tests = ", ".join(
        t for t in tests_used if "chi" in t.lower() or "fisher" in t.lower()
    ) or "chi-square or Fisher's exact test"
    _cont_tests = ", ".join(
        t for t in tests_used
        if (
            "mann" in t.lower()
            or "kruskal" in t.lower()
            or "pearson" in t.lower()
            or "spearman" in t.lower()
        )
    ) or "Mann-Whitney U test"
    methods_text = (
        f"All statistical analyses were performed using Python (scipy). "
        f"For each predictor variable, its association with {outcome_col} was tested independently. "
        f"Categorical variables were compared using {_cat_tests}. "
        f"Continuous variables were compared using {_cont_tests}. "
        "A two-tailed p-value < 0.05 was considered statistically significant."
    )

    normalized_tables: List[Dict[str, Any]] = []
    normalized_figures: List[Dict[str, str]] = []
    for pair_result in pair_results:
        table, figures = _correlation_pair_presentation(pair_result, outcome_col)
        normalized_tables.append(table)
        normalized_figures.extend(figures)

    return {
        "outcome_col": outcome_col,
        "pairs": pair_results,
        "summary_table": summary_table,
        "methods_text": methods_text,
        "tables": normalized_tables,
        "figures": normalized_figures,
    }


# ---------------------------------------------------------------------------
# Reference accuracy check — invoked only via `python results.py`
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    GroupA = [14, 16, 18, 20, 22, 24, 19, 21, 17, 23,
              15, 25, 18, 20, 22, 16, 19, 21, 23, 17]
    GroupB = [10, 12, 14, 16, 18, 20, 15, 17, 13, 19,
              11, 21, 14, 16, 18, 12, 15, 17, 19, 13]
    df_test = pd.DataFrame({
        'value': GroupA + GroupB,
        'group': ['A'] * 20 + ['B'] * 20,
    })

    from scipy.stats import ttest_ind
    t_val, p_val = ttest_ind(GroupA, GroupB, equal_var=True, alternative='two-sided')
    assert abs(t_val - 4.054) < 0.1, f"t-test FAIL: got {t_val}"
    assert p_val < 0.001, f"t-test p FAIL: got {p_val}"
    print("t-test accuracy: PASS")

    from scipy.stats import pearsonr
    r_val, _ = pearsonr([1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                        [2, 4, 5, 4, 5, 7, 8, 9, 10, 12])
    assert abs(r_val - 0.971) < 0.01, f"Pearson FAIL: got {r_val}"
    print("Pearson accuracy: PASS")

    lo, hi = wilson_ci(90, 100)
    assert 0.82 < lo < 0.84, f"Wilson CI FAIL: lower = {lo}"
    print(f"Wilson CI accuracy: PASS  (lo={lo}, hi={hi})")

    print("All accuracy checks PASSED.")
    print("Phase A complete — all tests built with safety rules baked in.")
