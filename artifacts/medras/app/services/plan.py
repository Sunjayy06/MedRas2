"""Statistical plan generator (Step 6).

Reads the user's variable assignment (outcome + group + covariates),
the normality verdicts produced in Step 5, and emits a structured
``plan`` describing exactly which tests, graphs and outputs MedRAS will
run when the user hits "Run analysis".

The frontend renders the plan as three groups of removable cards:
``tests``, ``graphs``, ``outputs``. The user can untick any card; the
checked subset is then POSTed back to ``/run-analysis``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd


def _norm_lookup(normality: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for row in (normality or {}).get("columns") or []:
        col = row.get("column")
        if col:
            out[col] = row
    return out


def _classification_lookup(classifications: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {c["column"]: c for c in (classifications or []) if c.get("column")}


def _is_normal(col: str, norm_lookup: Dict[str, Dict[str, Any]]) -> bool:
    row = norm_lookup.get(col)
    if not row:
        return False
    return row.get("decision") == "normal"


def _outcome_kind(col: str, classes: Dict[str, Dict[str, Any]]) -> str:
    """Coarse routing key — scale | ordinal | nominal | binary."""
    c = classes.get(col)
    if not c:
        return "nominal"
    t = c.get("detected_type")
    if t == "scale":
        return "scale"
    if t == "ordinal":
        return "ordinal"
    return "nominal"


def _group_levels(df: pd.DataFrame, col: Optional[str]) -> List[str]:
    if not col or col not in df.columns:
        return []
    s = df[col].dropna()
    return [str(v) for v in sorted(s.unique().tolist(), key=lambda x: str(x))]


def generate_plan(
    df: pd.DataFrame,
    classifications: List[Dict[str, Any]],
    assignment: Dict[str, Any],
    normality: Dict[str, Any],
) -> Dict[str, Any]:
    """Produce the full plan dict consumed by screen-6.

    ``assignment`` shape::

        {"outcome": "HHS_post", "group": "Treatment", "covariates": ["Age"]}

    Returns::

        {
          "tests": [{id, title, why, columns, parametric}, ...],
          "graphs": [{id, title, why, columns}, ...],
          "outputs": [{id, title, what}, ...],
          "summary": "human-readable one-liner",
        }
    """
    classes = _classification_lookup(classifications)
    norm = _norm_lookup(normality)

    outcome = (assignment or {}).get("outcome")
    group = (assignment or {}).get("group")
    covariates = list((assignment or {}).get("covariates") or [])
    cov_scale = [c for c in covariates if classes.get(c, {}).get("detected_type") == "scale"]

    tests: List[Dict[str, Any]] = []
    graphs: List[Dict[str, Any]] = []
    outputs: List[Dict[str, Any]] = []

    # Always describe the cohort first.
    outputs.append({
        "id": "table_one",
        "title": "Table 1 — Baseline characteristics",
        "what": "Demographics + key variables, with descriptive statistics by group.",
    })
    outputs.append({
        "id": "methods_paragraph",
        "title": "Methods paragraph (APA-style)",
        "what": "Auto-written paragraph describing the statistical approach.",
    })
    outputs.append({
        "id": "results_paragraph",
        "title": "Results paragraph (APA-style)",
        "what": "Auto-written paragraph reporting each test's result with effect size and CI.",
    })

    if not outcome:
        return {
            "tests": tests,
            "graphs": graphs,
            "outputs": outputs,
            "summary": "Pick an outcome variable on Step 4 to see the full plan.",
        }

    o_kind = _outcome_kind(outcome, classes)
    o_normal = _is_normal(outcome, norm)
    levels = _group_levels(df, group) if group else []
    n_levels = len(levels)

    # ---- Comparison tests ------------------------------------------------
    if group and o_kind == "scale" and n_levels == 2:
        if o_normal:
            tests.append({
                "id": "ttest_independent",
                "title": "Independent samples t-test",
                "why": (
                    f"{outcome} is scale and approximately normal; {group} has 2 levels "
                    f"({levels[0]} vs {levels[1]})."
                ),
                "columns": [outcome, group],
                "parametric": True,
            })
        else:
            tests.append({
                "id": "mann_whitney",
                "title": "Mann-Whitney U test",
                "why": (
                    f"{outcome} is scale but non-normal; {group} has 2 levels — "
                    "non-parametric two-sample comparison."
                ),
                "columns": [outcome, group],
                "parametric": False,
            })
    elif group and o_kind == "scale" and n_levels > 2:
        if o_normal:
            tests.append({
                "id": "anova_oneway",
                "title": "One-way ANOVA",
                "why": (
                    f"{outcome} is scale and approximately normal; {group} has "
                    f"{n_levels} levels — comparing means across groups."
                ),
                "columns": [outcome, group],
                "parametric": True,
            })
            tests.append({
                "id": "tukey_hsd",
                "title": "Tukey HSD post-hoc",
                "why": "Pairwise comparisons after a significant ANOVA.",
                "columns": [outcome, group],
                "parametric": True,
            })
        else:
            tests.append({
                "id": "kruskal_wallis",
                "title": "Kruskal-Wallis H test",
                "why": (
                    f"{outcome} is non-normal across {n_levels} groups — "
                    "non-parametric multi-sample comparison."
                ),
                "columns": [outcome, group],
                "parametric": False,
            })
    elif group and o_kind in ("nominal", "ordinal"):
        tests.append({
            "id": "chi_square",
            "title": "Chi-square test of independence",
            "why": (
                f"{outcome} is categorical; testing whether its distribution differs "
                f"across the {n_levels or '?'} levels of {group}."
            ),
            "columns": [outcome, group],
            "parametric": False,
        })
        tests.append({
            "id": "fisher_exact_if_sparse",
            "title": "Fisher's exact (fallback if expected cell < 5)",
            "why": "Used automatically when chi-square assumptions fail.",
            "columns": [outcome, group],
            "parametric": False,
        })

    # No grouping → descriptive only.
    if not group:
        tests.append({
            "id": "descriptive_only",
            "title": "Descriptive summary",
            "why": "No grouping variable selected — we'll summarise the outcome alone.",
            "columns": [outcome],
            "parametric": False,
        })

    # ---- Covariate-adjusted analysis ------------------------------------
    if covariates and o_kind == "scale" and group and n_levels >= 2:
        tests.append({
            "id": "ancova",
            "title": "ANCOVA (covariate-adjusted)",
            "why": (
                f"Adjusting {outcome} for {len(covariates)} covariate"
                f"{'s' if len(covariates) != 1 else ''} ({', '.join(covariates)})."
            ),
            "columns": [outcome, group] + covariates,
            "parametric": True,
        })
    if covariates and o_kind == "scale" and not group:
        tests.append({
            "id": "linear_regression",
            "title": "Linear regression",
            "why": (
                f"{outcome} ~ {' + '.join(covariates)} — quantifying each "
                "covariate's contribution."
            ),
            "columns": [outcome] + covariates,
            "parametric": True,
        })
    if covariates and o_kind in ("nominal", "ordinal") and len(_group_levels(df, outcome)) == 2:
        tests.append({
            "id": "logistic_regression",
            "title": "Binary logistic regression",
            "why": (
                f"Binary outcome {outcome} ~ {' + '.join(covariates)} — odds ratios with 95% CI."
            ),
            "columns": [outcome] + covariates,
            "parametric": True,
        })

    # ---- Graphs ---------------------------------------------------------
    if o_kind == "scale":
        if group and n_levels >= 2:
            graphs.append({
                "id": "boxplot",
                "title": "Box-and-whisker plot",
                "why": f"{outcome} by {group} — shows medians, IQR and outliers per group.",
                "columns": [outcome, group],
            })
            graphs.append({
                "id": "violin",
                "title": "Violin plot",
                "why": f"{outcome} by {group} — full distribution shape per group.",
                "columns": [outcome, group],
            })
        else:
            graphs.append({
                "id": "histogram",
                "title": "Histogram",
                "why": f"Distribution of {outcome}.",
                "columns": [outcome],
            })
    elif o_kind in ("nominal", "ordinal") and group:
        graphs.append({
            "id": "stacked_bar",
            "title": "Stacked bar chart",
            "why": f"{outcome} composition across {group} levels.",
            "columns": [outcome, group],
        })

    if cov_scale and o_kind == "scale":
        for cv in cov_scale[:3]:
            graphs.append({
                "id": f"scatter_{cv}",
                "title": f"Scatter — {outcome} vs {cv}",
                "why": "Linear relationship visualisation with regression line.",
                "columns": [outcome, cv],
            })

    if tests:
        graphs.append({
            "id": "forest_plot",
            "title": "Forest plot",
            "why": "Effect sizes with 95% CI for every test that runs.",
            "columns": [outcome] + ([group] if group else []),
        })

    summary_bits = []
    if group:
        summary_bits.append(f"{outcome} by {group}")
    else:
        summary_bits.append(f"{outcome} (no grouping)")
    if covariates:
        summary_bits.append(f"adjusted for {', '.join(covariates)}")
    # Filter to runners we actually implement so users never see a confirmed
    # card that ends up "planned but not yet implemented" at run time.
    from . import results as _results
    tests = [t for t in tests if _results.is_supported_test(t["id"])]
    graphs = [g for g in graphs if _results.is_supported_graph(g["id"])]

    if tests:
        summary = (
            "We will run "
            + ", ".join(t["title"] for t in tests)
            + " on " + " ".join(summary_bits) + "."
        )
    else:
        summary = "No tests will run with the current selection."

    return {
        "tests": tests,
        "graphs": graphs,
        "outputs": outputs,
        "summary": summary,
    }
