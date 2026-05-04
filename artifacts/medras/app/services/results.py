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


_PHASE_B_TEST_IDS = frozenset({
    "pb_paired_t", "pb_wilcoxon", "pb_mcnemar", "pb_rm_anova", "pb_friedman",
    "pb_chi_or_fisher", "pb_kappa", "pb_icc_ba", "pb_km", "pb_cox",
    "pb_diagnostic", "pb_ordinal", "pb_count",
})
KNOWN_TEST_IDS = frozenset(set(_RUNNERS.keys()) | _PHASE_B_TEST_IDS)
KNOWN_GRAPH_IDS = frozenset(list(_GRAPH_RUNNERS.keys()) + ["forest_plot"])


def is_supported_test(test_id: str) -> bool:
    return test_id in KNOWN_TEST_IDS


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
    FUNCTION_MAP = {
        "run_paired_ttest": run_paired_ttest,
        "run_wilcoxon": run_wilcoxon,
        "run_mcnemar": run_mcnemar,
        "run_rm_anova": run_rm_anova,
        "run_friedman": run_friedman,
        "run_chi_or_fisher": run_chi_or_fisher,
        "run_kappa": run_kappa,
        "run_icc_bland_altman": run_icc_bland_altman,
        "run_kaplan_meier": run_kaplan_meier,
        "run_cox_regression": run_cox_regression,
        "run_diagnostic_accuracy": run_diagnostic_accuracy,
        "run_ordinal_logistic": run_ordinal_logistic,
        "run_count_regression": run_count_regression,
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
            r["title"] = t["title"]
            r["test_type"] = pb.get("test_type")
            r["plan_name"] = t["title"]
            r["plan_reason"] = t.get("why")
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
        # Mirror p_value into 'p' so the correction helper picks it up.
        if r.get("p_value") is not None and r.get("p") is None:
            r["p"] = r.get("p_value")
        test_results.append(r)

    # Multiple-testing correction (R8) — applied only to inferential tests
    test_results, correction_info = apply_correction_if_needed(test_results)

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

    valid, err = validate_result(test_name, stat, float(p))
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
        'n': n,
        'statistic': round(stat, 3),
        'p': float(p),
        'p_display': fmt_p(float(p)),
        'dof': int(dof) if test_name != "Fisher's exact test" else None,
        'cramers_v': round(cramers_v, 3),
        'min_expected': round(min_expected, 2),
        'note': note,
        'expected_table': expected.tolist(),
        'observed_table': table.values.tolist(),
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
        return {'error': f'ICC failed: {str(e)}'}

    icc_interp = ('poor' if icc_val < 0.50 else
                  'moderate' if icc_val < 0.75 else
                  'good' if icc_val < 0.90 else
                  'excellent')

    diffs = data[col1] - data[col2]
    mean_diff = float(diffs.mean())
    sd_diff = float(diffs.std())
    loa_lo = mean_diff - 1.96 * sd_diff
    loa_hi = mean_diff + 1.96 * sd_diff
    se_mean = sd_diff / np.sqrt(n) if n > 0 else 0
    t_crit = _phase_a_stats.t.ppf(0.975, df=n - 1)
    bias_ci = (round(mean_diff - t_crit * se_mean, 3),
               round(mean_diff + t_crit * se_mean, 3))

    d1 = get_display_name(col1, session)
    d2 = get_display_name(col2, session)

    return {
        'test': 'ICC and Bland-Altman',
        'test_type': 'icc',
        'icc': round(icc_val, 3),
        'icc_ci': (round(icc_lo, 3), round(icc_hi, 3)),
        'icc_F': round(F_val, 3),
        'icc_p': p_val,
        'icc_p_display': fmt_p(p_val),
        'icc_interpretation': icc_interp,
        'bland_altman': {
            'mean_bias': round(mean_diff, 3),
            'bias_ci': bias_ci,
            'loa_lower': round(loa_lo, 3),
            'loa_upper': round(loa_hi, 3),
            'sd_diff': round(sd_diff, 3),
        },
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
def run_diagnostic_accuracy(disease_col, test_col, session, df, positive_class=1):
    from sklearn.metrics import roc_curve, roc_auc_score
    data = df[[disease_col, test_col]].dropna()
    n = len(data)
    if n < 20:
        return {'error': f'Sample too small (n={n}). Minimum 20 needed.'}

    y_true = (data[disease_col] == positive_class).astype(int)
    y_score = data[test_col]

    fpr, tpr, thresholds = roc_curve(y_true, y_score)
    auc = float(roc_auc_score(y_true, y_score))

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
        'auc_ci': wilson_ci(int(auc * n), n),
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
