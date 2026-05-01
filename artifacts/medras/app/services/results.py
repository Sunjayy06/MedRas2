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
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fig_to_data_uri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.1, dpi=110)
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
            data = pd.to_numeric(df[col], errors="coerce")
            if group_levels:
                cells = []
                for lvl in group_levels:
                    sub = data[df[group].astype(str) == lvl].dropna()
                    cells.append(
                        f"{_fmt_num(sub.mean())} ± {_fmt_num(sub.std(ddof=1))} (n={len(sub)})"
                    ) if len(sub) else cells.append("—")
                rows.append({"variable": col, "type": "Mean ± SD", "cells": cells})
            else:
                clean = data.dropna()
                rows.append({
                    "variable": col, "type": "Mean ± SD",
                    "cells": [f"{_fmt_num(clean.mean())} ± {_fmt_num(clean.std(ddof=1))} (n={len(clean)})"],
                })
        else:
            counts = df[col].astype(str).value_counts(dropna=False)
            top = counts.head(6)
            if group_levels:
                cells = []
                for lvl in group_levels:
                    sub = df[df[group].astype(str) == lvl][col].astype(str).value_counts()
                    bits = [f"{lab}: {sub.get(lab, 0)}" for lab in top.index]
                    cells.append("; ".join(bits))
                rows.append({"variable": col, "type": "n (count)", "cells": cells})
            else:
                bits = [f"{lab}: {cnt}" for lab, cnt in top.items()]
                rows.append({
                    "variable": col, "type": "n (count)", "cells": ["; ".join(bits)],
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
    pooled_sd = np.sqrt(((len(a) - 1) * np.var(a, ddof=1) + (len(b) - 1) * np.var(b, ddof=1)) / max(len(a) + len(b) - 2, 1))
    cohen_d = (np.mean(a) - np.mean(b)) / pooled_sd if pooled_sd else 0.0
    diff = float(np.mean(a) - np.mean(b))
    se = float(np.sqrt(np.var(a, ddof=1) / len(a) + np.var(b, ddof=1) / len(b)))
    ci_lo, ci_hi = diff - 1.96 * se, diff + 1.96 * se
    rows = [
        _row(f"Mean ({la})", float(np.mean(a))),
        _row(f"Mean ({lb})", float(np.mean(b))),
        _row("Mean difference", diff),
        _row("95% CI", f"[{_fmt_num(ci_lo)}, {_fmt_num(ci_hi)}]"),
        _row("t statistic", float(stat)),
        _row("Cohen's d", cohen_d),
        _row("p-value", _fmt_p(float(p))),
    ]
    narrative = (
        f"An independent-samples t-test compared {outcome} between {la} and "
        f"{lb}. Mean {outcome} was {_fmt_num(np.mean(a))} (SD {_fmt_num(np.std(a, ddof=1))}) "
        f"in {la} and {_fmt_num(np.mean(b))} (SD {_fmt_num(np.std(b, ddof=1))}) "
        f"in {lb}; mean difference {_fmt_num(diff)}, 95% CI [{_fmt_num(ci_lo)}, "
        f"{_fmt_num(ci_hi)}], t = {_fmt_num(float(stat))}, {_fmt_p(float(p))}, "
        f"Cohen's d = {_fmt_num(cohen_d)}."
    )
    return {
        "rows": rows, "narrative": narrative, "p_value": float(p),
        "effect_size": float(cohen_d), "effect_label": "Cohen's d",
        "ci_lo": float(ci_lo), "ci_hi": float(ci_hi),
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
    }


def _descriptive(df, outcome, _group) -> Dict[str, Any]:
    s = pd.to_numeric(df[outcome], errors="coerce").dropna()
    if len(s) == 0:
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
    try:
        levels = [str(v) for v in df[group].dropna().unique()]
        data = [pd.to_numeric(df.loc[df[group].astype(str) == lvl, outcome], errors="coerce").dropna()
                for lvl in levels]
        fig, ax = plt.subplots(figsize=(5.0, 3.6))
        ax.boxplot(data, tick_labels=levels, patch_artist=True,
                   boxprops=dict(facecolor="#bfd4ff", edgecolor="#2f6fed"),
                   medianprops=dict(color="#103a6e"))
        ax.set_ylabel(outcome)
        ax.set_xlabel(group)
        ax.set_title(f"{outcome} by {group}")
        ax.grid(axis="y", alpha=0.3)
        return _fig_to_data_uri(fig)
    except Exception:
        plt.close("all")
        return None


def _histogram(df, outcome, _group=None) -> Optional[str]:
    try:
        s = pd.to_numeric(df[outcome], errors="coerce").dropna()
        fig, ax = plt.subplots(figsize=(5.0, 3.6))
        ax.hist(s, bins=min(30, max(8, int(np.sqrt(len(s))))),
                color="#bfd4ff", edgecolor="#2f6fed")
        ax.set_xlabel(outcome)
        ax.set_ylabel("Count")
        ax.set_title(f"Distribution of {outcome}")
        ax.grid(axis="y", alpha=0.3)
        return _fig_to_data_uri(fig)
    except Exception:
        plt.close("all")
        return None


def _stacked_bar(df, outcome, group) -> Optional[str]:
    try:
        ct = pd.crosstab(df[group].astype(str), df[outcome].astype(str))
        fig, ax = plt.subplots(figsize=(5.0, 3.6))
        ct.plot(kind="bar", stacked=True, ax=ax, colormap="Blues", edgecolor="#103a6e")
        ax.set_ylabel("Count")
        ax.set_xlabel(group)
        ax.set_title(f"{outcome} by {group}")
        ax.legend(title=outcome, fontsize=8)
        return _fig_to_data_uri(fig)
    except Exception:
        plt.close("all")
        return None


def _forest_plot(test_results: List[Dict[str, Any]]) -> Optional[str]:
    try:
        labels = []
        effects = []
        lows = []
        highs = []
        for t in test_results:
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
        fig, ax = plt.subplots(figsize=(6.5, max(2.0, 0.5 * len(labels) + 1.0)))
        y = np.arange(len(labels))
        for i, (lo, hi, e) in enumerate(zip(lows, highs, effects)):
            ax.plot([lo, hi], [i, i], color="#2f6fed", lw=2)
            ax.plot(e, i, marker="s", color="#2f6fed", markersize=10)
        ax.axvline(0, color="#888", lw=1, ls="--")
        ax.set_yticks(y)
        ax.set_yticklabels(labels)
        ax.invert_yaxis()
        ax.set_xlabel("Effect size (95% CI shown when available)")
        ax.set_title("Forest plot — effect sizes")
        ax.grid(axis="x", alpha=0.3)
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


KNOWN_TEST_IDS = frozenset(_RUNNERS.keys())
KNOWN_GRAPH_IDS = frozenset(list(_GRAPH_RUNNERS.keys()) + ["forest_plot"])


def is_supported_test(test_id: str) -> bool:
    return test_id in KNOWN_TEST_IDS


def is_supported_graph(graph_id: str) -> bool:
    return graph_id in KNOWN_GRAPH_IDS or graph_id.startswith("scatter_")


# ---------------------------------------------------------------------------
# Top-level entrypoint
# ---------------------------------------------------------------------------


def run_plan(
    df: pd.DataFrame,
    classifications: List[Dict[str, Any]],
    assignment: Dict[str, Any],
    plan: Dict[str, Any],
    confirmed_test_ids: Optional[List[str]] = None,
    confirmed_graph_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    outcome = (assignment or {}).get("outcome")
    group = (assignment or {}).get("group")
    confirmed_test_ids = confirmed_test_ids or [t["id"] for t in (plan.get("tests") or [])]
    confirmed_graph_ids = confirmed_graph_ids or [g["id"] for g in (plan.get("graphs") or [])]

    # Run tests --------------------------------------------------------------
    test_results: List[Dict[str, Any]] = []
    for t in plan.get("tests") or []:
        if t["id"] not in confirmed_test_ids:
            continue
        runner = _RUNNERS.get(t["id"])
        if runner is None:
            test_results.append({
                "id": t["id"], "title": t["title"], "rows": [],
                "narrative": f"{t['title']} is planned but not yet implemented in this build.",
                "p_value": None, "effect_size": None, "effect_label": "—",
                "ci_lo": None, "ci_hi": None,
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
        test_results.append(r)

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
    methods_lines = []
    methods_lines.append(
        f"Continuous variables are summarised as mean ± SD; categorical "
        f"variables as counts. Normality of {outcome} was assessed using "
        "Shapiro-Wilk (n < 50) or Kolmogorov-Smirnov (50 ≤ n ≤ 2000); for "
        "n > 2000 we relied on skewness and kurtosis (|skew| ≤ 2, |kurt| ≤ 7)."
    )
    if any(t["id"] == "ttest_independent" for t in test_results):
        methods_lines.append("Group means were compared with Welch's t-test.")
    if any(t["id"] == "mann_whitney" for t in test_results):
        methods_lines.append("Non-parametric two-sample comparisons used the Mann-Whitney U test.")
    if any(t["id"] == "anova_oneway" for t in test_results):
        methods_lines.append("Means across more than two groups were compared with one-way ANOVA.")
    if any(t["id"] == "kruskal_wallis" for t in test_results):
        methods_lines.append("Non-parametric multi-group comparisons used the Kruskal-Wallis H test.")
    if any(t["id"] == "chi_square" for t in test_results):
        methods_lines.append("Categorical associations were tested with the chi-square test of independence.")
    methods_lines.append("All tests are two-sided with α = 0.05.")
    methods_md = " ".join(methods_lines)

    results_md = "\n\n".join(t["narrative"] for t in test_results) or (
        "No tests were confirmed for this run."
    )

    return {
        "table_one": table_one,
        "tests": test_results,
        "graphs": graph_results,
        "forest_plot": _forest_plot(test_results),
        "methods_md": methods_md,
        "results_md": results_md,
        "summary": {
            "outcome": outcome,
            "group": group,
            "n_tests": len(test_results),
            "n_graphs": len(graph_results),
        },
    }
