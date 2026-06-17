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


def _included_analysis_variables(
    classifications: List[Dict[str, Any]],
    assignment: Dict[str, Any],
    session: Dict[str, Any],
) -> List[str]:
    preferred = [
        (assignment or {}).get("outcome"),
        (assignment or {}).get("group"),
        *((assignment or {}).get("covariates") or []),
        *(session.get("analysis_predictors") or []),
    ]
    included = [
        c.get("column") for c in classifications
        if c.get("column") and c.get("detected_type") not in ("id", "date", "exclude")
    ]
    ordered = [c for c in preferred if c in included]
    return list(dict.fromkeys(ordered + included))


def _analysis_allowed_columns(
    df: pd.DataFrame,
    classes: Dict[str, Dict[str, Any]],
    outcome: Optional[str],
) -> set[str]:
    return {
        col for col in df.columns
        if col == outcome
        or classes.get(col, {}).get("detected_type") not in ("id", "date", "exclude")
    }


def _filter_analysis_items(
    items: List[Dict[str, Any]],
    allowed: set[str],
) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for item in items:
        columns = item.get("columns") or []
        if all(col in allowed for col in columns):
            filtered.append(item)
    return filtered


def _graph_chart_type(graph_id: str) -> str:
    if graph_id.startswith("scatter"):
        return "scatter plot"
    if graph_id == "boxplot":
        return "box plot"
    if graph_id == "violin":
        return "violin plot"
    if graph_id == "stacked_bar":
        return "stacked percentage bar chart"
    if graph_id == "histogram":
        return "histogram"
    if graph_id == "forest_plot":
        return "forest plot"
    return "statistical figure"


def _graph_type_key(graph_id: str) -> str:
    if graph_id.startswith("scatter"):
        return "scatter"
    if graph_id.startswith("boxplot") or graph_id == "boxplot":
        return "boxplot"
    if graph_id == "violin":
        return "violin"
    if graph_id.startswith("stacked_bar") or graph_id == "stacked_bar":
        return "stacked_bar"
    if graph_id == "histogram":
        return "histogram"
    if graph_id == "forest_plot":
        return "forest_plot"
    return "statistical_figure"


def _enrich_graph_metadata(graphs: List[Dict[str, Any]], outcome: Optional[str]) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for graph in graphs:
        copy = dict(graph)
        graph_id = str(copy.get("id") or "")
        variables = list(copy.get("columns") or [])
        chart_type = _graph_chart_type(graph_id)
        source_result_id = copy.get("source_result_id") or copy.get("data_source_result_id")
        copy.setdefault("graph_id", graph_id)
        copy.setdefault("graph_type", _graph_type_key(graph_id))
        copy.setdefault("variables", variables)
        copy.setdefault("outcome", outcome)
        copy.setdefault("recommended_chart_type", chart_type)
        copy.setdefault("data_source_result_id", source_result_id)
        copy.setdefault("source_result_id", source_result_id)
        copy.setdefault("caption", f"{copy.get('title', 'Figure')} for {', '.join(map(str, variables))}.")
        copy.setdefault("interpretation", "Interpret alongside the corresponding statistical test and p-value.")
        copy.setdefault("why_recommended", copy.get("why") or f"{chart_type} is appropriate for the selected variable types.")
        copy.setdefault("thesis_ready", True)
        enriched.append(copy)
    return enriched


def _test_graph_recommendations(
    tests: List[Dict[str, Any]],
    classes: Dict[str, Dict[str, Any]],
    outcome: Optional[str],
) -> List[Dict[str, Any]]:
    recs: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for test in tests:
        phase = test.get("_phase_b") or {}
        args = phase.get("args") or {}
        columns = list(test.get("columns") or [])
        if len(columns) < 2 or outcome not in columns:
            continue
        predictor = next((col for col in columns if col != outcome), columns[0])
        key = f"{predictor}::{outcome}"
        if key in seen:
            continue
        seen.add(key)
        pred_type = classes.get(predictor, {}).get("detected_type")
        if test.get("analysis_family") == "correlation":
            graph_id = f"scatter_{predictor}_vs_{outcome}"
            graph_type = "scatter"
            chart = "scatter plot"
            title = f"{predictor} vs {outcome}"
            why = "Scatter plot is appropriate for a scale-scale correlation."
        elif pred_type == "scale":
            graph_id = f"boxplot_{predictor}_by_{outcome}"
            graph_type = "boxplot"
            chart = "box plot"
            title = f"{predictor} by {outcome}"
            why = "Continuous predictor compared across binary outcome groups."
        else:
            graph_id = f"stacked_bar_{predictor}_by_{outcome}"
            graph_type = "stacked_bar"
            chart = "stacked percentage bar chart"
            title = f"{predictor} status by {outcome}"
            why = "Categorical predictor distribution compared across outcome groups."
        recs.append({
            "id": graph_id,
            "graph_id": graph_id,
            "graph_type": graph_type,
            "title": title,
            "columns": [predictor, outcome],
            "variables": [predictor, outcome],
            "outcome": outcome,
            "recommended_chart_type": chart,
            "data_source_result_id": test.get("id"),
            "source_result_id": test.get("id"),
            "caption": f"{title}.",
            "interpretation": "Interpret with the matching statistical test result.",
            "why": why,
            "why_recommended": why,
            "thesis_ready": True,
        })
    return recs


def _descriptive_layer(
    df: pd.DataFrame,
    classifications: List[Dict[str, Any]],
    assignment: Dict[str, Any],
    session: Dict[str, Any],
) -> List[Dict[str, Any]]:
    classes = _classification_lookup(classifications)
    rows: List[Dict[str, Any]] = []
    for col in _included_analysis_variables(classifications, assignment, session):
        detected = classes.get(col, {}).get("detected_type", "nominal")
        n_levels = int(df[col].dropna().nunique()) if col in df.columns else 0
        if detected == "scale":
            statistics = ["n", "missing", "mean", "sd", "median", "iqr", "min", "max"]
        elif detected == "ordinal":
            statistics = ["n", "percent", "missing", "median", "iqr"]
        else:
            statistics = ["n", "percent", "missing"]
        rows.append({
            "id": f"describe_{col}",
            "variable": col,
            "variable_type": "binary" if n_levels == 2 and detected != "scale" else detected,
            "statistics": statistics,
            "analysis_family": "descriptive",
            "always_included": True,
        })
    return rows


def _study_design(session: Dict[str, Any]) -> str:
    explicit = str(session.get("design") or "").strip().lower()
    study_type = str(session.get("study_type") or "").strip().lower()
    objective = _objective_text(session)
    joined = " ".join((explicit, study_type, objective))
    if any(term in joined for term in ("diagnostic", "sensitivity", "specificity", "roc", "auc")):
        return "diagnostic_accuracy"
    if any(term in joined for term in ("survival", "time-to-event", "time to event", "cox", "mortality")):
        return "survival_time_to_event"
    if any(term in joined for term in ("time series", "forecast", "autocorrelation", "arima", "trend over time")):
        return "time_series"
    if any(term in joined for term in ("repeated", "longitudinal", "timepoint", "time point", "over time")):
        return "repeated_measures"
    if any(term in joined for term in ("agreement", "reliability", "kappa", "icc", "bland-altman", "bland altman", "method comparison")):
        return "reliability_agreement"
    if any(term in joined for term in ("randomized", "randomised", "interventional", "trial", "rct")):
        return "randomized_interventional"
    if "case-control" in joined or "case control" in joined:
        return "case_control"
    if any(term in joined for term in ("cohort", "prognostic", "risk factor")):
        return "cohort_prognostic"
    if any(term in joined for term in ("cross-sectional", "cross sectional", "association", "correlation")):
        return "cross_sectional_association"
    if "descriptive" in joined:
        return "descriptive_observational"
    return "generic_unknown"


def _is_multivariable_objective(session: Dict[str, Any]) -> bool:
    objective = _objective_text(session)
    study_type = str(session.get("study_type") or "").lower()
    terms = (
        "prediction", "predict", "risk factor", "prognostic", "adjust",
        "independent association", "multivariable", "multivariate", "regression",
    )
    return study_type in ("regression", "prediction") or any(term in objective for term in terms)


def _analysis_family(test: Dict[str, Any]) -> str:
    family = test.get("analysis_family")
    if family:
        return "multivariate" if str(family) == "regression" else str(family)
    test_id = str(test.get("id") or "")
    test_type = str((test.get("_phase_b") or {}).get("test_type") or "")
    if "regression" in test_id or "regression" in test_type or test_id in ("ancova", "pb_cox"):
        return "multivariate"
    if test_id == "descriptive_only":
        return "descriptive"
    return "bivariate"


def _layered_contract(
    df: pd.DataFrame,
    classifications: List[Dict[str, Any]],
    assignment: Dict[str, Any],
    session: Dict[str, Any],
    tests: List[Dict[str, Any]],
    suggestions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    classes = _classification_lookup(classifications)
    outcome = (assignment or {}).get("outcome")
    predictors = [
        c for c in (session.get("analysis_predictors") or [])
        if c in df.columns and c != outcome
        and classes.get(c, {}).get("detected_type") not in ("id", "date", "exclude")
    ]
    covariates = [
        c for c in (assignment or {}).get("covariates", [])
        if c in df.columns and c != outcome
        and classes.get(c, {}).get("detected_type") not in ("id", "date", "exclude")
    ]
    candidate_predictors = list(dict.fromkeys(covariates + predictors))
    eligible_predictors = list(candidate_predictors)
    descriptive = _descriptive_layer(df, classifications, assignment, session)
    bivariate = [dict(t, analysis_family="bivariate") for t in tests if _analysis_family(t) == "bivariate"]
    multivariate = [
        dict(t, analysis_family="multivariate", execution_status="confirmed")
        for t in tests if _analysis_family(t) == "multivariate"
    ]
    eligibility_notes: List[str] = []
    warnings: List[str] = []
    unavailable: List[Dict[str, Any]] = []
    requires_confirmation = not bool(outcome)
    objective = _objective_text(session)
    design = _study_design(session)

    assumption_checks = [
        {"id": "missingness", "title": "Missing-data review", "status": "required"},
        {"id": "normality", "title": "Normality review for scale variables", "status": "required"},
        {"id": "sparse_cells", "title": "Expected-count review for categorical tables", "status": "required"},
    ]

    if not outcome:
        eligibility_notes.append(
            "No main outcome has been confirmed; only descriptive analysis is planned."
        )
        warnings.append("Confirm the main outcome before generating bivariate or multivariate analyses.")
    else:
        outcome_kind = _outcome_kind(outcome, classes)
        outcome_levels = int(df[outcome].dropna().nunique())
        eligibility_notes.append(
            f"Confirmed main outcome: {outcome} ({'binary' if outcome_levels == 2 and outcome_kind != 'scale' else outcome_kind})."
        )
        if candidate_predictors and _is_multivariable_objective(session):
            model_columns = [outcome] + candidate_predictors
            complete_n = int(df[model_columns].dropna().shape[0])
            complete_fraction = complete_n / max(len(df), 1)
            eligibility_notes.append(
                f"Adjusted-model complete cases: {complete_n}/{len(df)} ({complete_fraction:.1%})."
            )
            if complete_fraction < 0.70:
                warnings.append(
                    "Adjusted-model missingness is substantial; confirm the missing-data strategy "
                    "and perform sensitivity analysis before interpretation."
                )
                requires_confirmation = True

        if outcome_levels == 2 and outcome_kind != "scale":
            counts = df[outcome].dropna().value_counts()
            smaller_events = int(counts.min()) if len(counts) == 2 else 0
            max_predictors = smaller_events // 10
            eligibility_notes.append(
                f"Smaller outcome class has {smaller_events} events; conservative EPV permits at most {max_predictors} predictor(s)."
            )
            if _is_multivariable_objective(session) and candidate_predictors:
                if max_predictors < 1:
                    eligible_predictors = []
                    unavailable.append({
                        "id": "logistic_regression_low_events",
                        "title": "Binary logistic regression",
                        "reason": "Too few events in the smaller outcome class for a stable adjusted model.",
                    })
                    warnings.append(
                        f"Only {smaller_events} events are available in the smaller outcome class; "
                        "a multivariable logistic model is not eligible."
                    )
                elif len(candidate_predictors) > max_predictors:
                    eligible_predictors = candidate_predictors[:max_predictors]
                    warnings.append(
                        f"Only {smaller_events} events are available in the smaller outcome class; "
                        f"multivariate model limited to {max_predictors} predictor(s)."
                    )
                    requires_confirmation = True

        if _is_multivariable_objective(session) and not multivariate:
            model = (
                "Binary logistic regression" if outcome_levels == 2 and outcome_kind != "scale"
                else "Multiple linear regression" if outcome_kind == "scale"
                else "Adjusted model"
            )
            multivariate.append({
                "id": "recommended_multivariable_model",
                "title": model,
                "columns": [outcome] + eligible_predictors,
                "analysis_family": "multivariate",
                "execution_status": "recommended_only",
                "requires_confirmation": True,
                "why": "Candidate predictors require researcher confirmation before an adjusted model runs.",
            })
            requires_confirmation = True

    if design == "diagnostic_accuracy" and not any(
        (t.get("_phase_b") or {}).get("test_type") == "diagnostic_accuracy" for t in tests
    ):
        unavailable.append({
            "id": "diagnostic_accuracy_inputs",
            "title": "Diagnostic accuracy",
            "reason": "A binary reference and test result/score must be confirmed.",
        })
        warnings.append("Diagnostic objective detected, but diagnostic inputs are incomplete.")
        requires_confirmation = True

    if design == "repeated_measures" and not any(
        (t.get("_phase_b") or {}).get("test_type") in ("rm_anova", "friedman") for t in tests
    ):
        unavailable.append({
            "id": "repeated_measures_unavailable",
            "title": "Repeated-measures analysis",
            "reason": "Repeated timepoints or subject/within-factor metadata are incomplete.",
        })
        warnings.append("Repeated-measures objective detected; no repeated-measures test was fabricated.")

    if design == "survival_time_to_event" and not any(
        (t.get("_phase_b") or {}).get("test_type") in ("log_rank", "cox_regression") for t in tests
    ):
        unavailable.append({
            "id": "survival_inputs_unavailable",
            "title": "Survival analysis",
            "reason": "A time-to-event variable and binary event indicator must be confirmed.",
        })
        warnings.append("Survival objective detected; no survival result will be fabricated.")

    if design == "time_series":
        unavailable.append({
            "id": "time_series_unavailable",
            "title": "Time-series analysis",
            "reason": "A true ordered time variable and an implemented time-series model must be confirmed.",
        })
        warnings.append("Time-series objective detected; no time-series model was fabricated.")
        requires_confirmation = True

    if design == "reliability_agreement" and not any(
        (t.get("_phase_b") or {}).get("test_type") in ("kappa", "icc") for t in tests
    ):
        unavailable.append({
            "id": "reliability_inputs_unavailable",
            "title": "Reliability / agreement analysis",
            "reason": "Two or more rater/method columns measuring the same subjects must be confirmed.",
        })
        warnings.append("Reliability objective detected, but rater/method inputs are incomplete.")
        requires_confirmation = True

    if any(t.get("id") == "descriptive_only" for t in tests):
        unavailable.append({
            "id": "no_inferential_match",
            "title": "Primary inferential analysis",
            "reason": "No executable inferential test matched the confirmed objective and variable types.",
        })

    if outcome and _outcome_kind(outcome, classes) in ("nominal", "ordinal"):
        ordinal_predictors = [
            predictor for predictor in predictors
            if classes.get(predictor, {}).get("detected_type") == "ordinal"
        ]
        if ordinal_predictors:
            eligibility_notes.append(
                "Ordinal predictors use categorical association fallback; a dedicated trend test is not implemented."
            )
            unavailable.append({
                "id": "ordinal_trend_test_unavailable",
                "title": "Dedicated ordinal trend test",
                "reason": "Not implemented; ordinal predictors are routed through the supported categorical association test.",
            })

    for suggestion in suggestions:
        if suggestion.get("blocking"):
            warnings.append(str(suggestion.get("warning") or suggestion.get("title") or "Blocking issue"))
            requires_confirmation = True

    return {
        "analysis_layers": {
            "descriptive": descriptive,
            "bivariate": bivariate,
            "multivariate": multivariate,
        },
        "study_design": design,
        "main_outcome": outcome,
        "predictors": predictors,
        "covariates": covariates,
        "confounders": covariates,
        "descriptive_plan": descriptive,
        "bivariate_plan": bivariate,
        "multivariate_plan": multivariate,
        "assumption_checks": assumption_checks,
        "eligibility_notes": eligibility_notes,
        "warnings": list(dict.fromkeys(warnings)),
        "unavailable_tests": unavailable,
        "requires_confirmation": requires_confirmation,
    }


def generate_plan(
    df: pd.DataFrame,
    classifications: List[Dict[str, Any]],
    assignment: Dict[str, Any],
    normality: Dict[str, Any],
    session: Optional[Dict[str, Any]] = None,
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
    session = session or {}

    outcome = (assignment or {}).get("outcome")
    group = (assignment or {}).get("group")
    covariates = list((assignment or {}).get("covariates") or [])
    allowed_columns = _analysis_allowed_columns(df, classes, outcome)
    if group and group not in allowed_columns:
        group = None
    covariates = [c for c in covariates if c in allowed_columns and c != outcome]
    cov_scale = [c for c in covariates if classes.get(c, {}).get("detected_type") == "scale"]

    tests: List[Dict[str, Any]] = []
    graphs: List[Dict[str, Any]] = []
    outputs: List[Dict[str, Any]] = []
    suggestions: List[Dict[str, Any]] = []

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
        plan = {
            "tests": tests,
            "graphs": graphs,
            "outputs": outputs,
            "suggestions": suggestions,
            "summary": "Pick an outcome variable on Step 4 to see the full plan.",
        }
        plan.update(_layered_contract(
            df, classifications, assignment, session, tests, suggestions
        ))
        return plan

    o_kind = _outcome_kind(outcome, classes)
    o_normal = _is_normal(outcome, norm)
    levels = _group_levels(df, group) if group else []
    n_levels = len(levels)
    study_type = str(session.get("study_type") or "").lower()
    analysis_predictors = [
        col for col in (session.get("analysis_predictors") or [])
        if col in allowed_columns and col != outcome
    ]
    outcome_levels = int(df[outcome].dropna().nunique())
    study_type_confirmed = bool(session.get("study_type_confirmed"))
    association_objective = study_type in ("association", "comparison") or not study_type_confirmed
    correlation_objective = study_type == "correlation"
    regression_objective = study_type in ("regression", "prediction")
    from . import category_merger
    outcome_duplicates = category_merger.detect_category_duplicates(
        df[outcome], profile=session.get("domain_profile")
    )
    likely_typo_groups = list(outcome_duplicates["obvious"])
    for group_item in outcome_duplicates["borderline"]:
        counts = sorted((group_item.get("counts") or {}).values(), reverse=True)
        total = sum(counts)
        if len(counts) >= 2 and counts[-1] <= max(2, int(total * 0.05)):
            likely_typo_groups.append(group_item)
    if likely_typo_groups:
        groups = likely_typo_groups
        labels = "; ".join(" / ".join(group["members"]) for group in groups)
        suggestions.append({
            "id": "outcome_duplicate_labels",
            "title": f"Resolve likely duplicate labels in outcome {outcome}",
            "requires_confirmation": True,
            "blocking": True,
            "warning": (
                f"Likely duplicate outcome labels were detected: {labels}. "
                "Merge or explicitly resolve them before running inferential analyses; "
                "otherwise group counts and test routing may be invalid."
            ),
        })

    for predictor in analysis_predictors:
        if predictor == outcome or predictor not in df.columns:
            continue
        if classes.get(predictor, {}).get("detected_type") not in ("nominal", "ordinal"):
            continue
        predictor_duplicates = category_merger.detect_category_duplicates(
            df[predictor], profile=session.get("domain_profile")
        )
        predictor_typo_groups = list(predictor_duplicates["obvious"])
        for group_item in predictor_duplicates["borderline"]:
            counts = sorted((group_item.get("counts") or {}).values(), reverse=True)
            total = sum(counts)
            if len(counts) >= 2 and counts[-1] <= max(2, int(total * 0.05)):
                predictor_typo_groups.append(group_item)
        if predictor_typo_groups:
            labels = "; ".join(
                " / ".join(group_item["members"]) for group_item in predictor_typo_groups
            )
            suggestions.append({
                "id": f"predictor_duplicate_labels_{predictor}",
                "title": f"Review likely duplicate labels in predictor {predictor}",
                "requires_confirmation": True,
                "blocking": False,
                "warning": (
                    f"Likely duplicate predictor labels were detected: {labels}. "
                    "Analysis can continue, but split categories may affect estimates and should be reviewed."
                ),
            })

    # ---- Comparison tests ------------------------------------------------
    if group and o_kind == "scale" and n_levels == 2:
        if o_normal:
            tests.append({
                "id": "ttest_independent",
                "title": "Welch's t-test",
                "why": (
                    f"{outcome} is scale and approximately normal; {group} has 2 levels "
                    f"({levels[0]} vs {levels[1]}). Welch's t-test is used by default."
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
                "id": "pc_tukey_hsd",
                "title": "Tukey HSD post-hoc",
                "why": "Pairwise comparisons after a significant ANOVA.",
                "columns": [outcome, group],
                "parametric": True,
                "_phase_b": {
                    "function": "pc_tukey_hsd",
                    "test_type": "tukey_hsd",
                    "args": {"outcome": outcome, "group": group},
                },
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
        # The smart Phase-B entry below chooses Fisher only for sparse 2x2
        # tables and retains chi-square with a warning for sparse RxC tables.
        pass

    # No explicit group: route selected predictors by objective and variable type.
    if not group and analysis_predictors and association_objective:
        for index, predictor in enumerate(analysis_predictors):
            predictor_kind = classes.get(predictor, {}).get("detected_type")
            predictor_levels = int(df[predictor].dropna().nunique())
            test_id = f"association_{index}"

            if o_kind in ("nominal", "ordinal") and predictor_kind in ("nominal", "ordinal", "discrete"):
                tests.append({
                    "id": test_id,
                    "title": f"{predictor} vs {outcome}: Chi-square / Fisher's exact",
                    "why": f"Association between categorical {predictor} and categorical outcome {outcome}.",
                    "columns": [predictor, outcome],
                    "parametric": False,
                    "analysis_family": "bivariate",
                    "_phase_b": {
                        "function": "run_chi_or_fisher",
                        "test_type": "chi_square",
                        "args": {"col1": predictor, "col2": outcome},
                    },
                })
                continue

            scale_variable = predictor if o_kind in ("nominal", "ordinal") else outcome
            grouping_variable = outcome if o_kind in ("nominal", "ordinal") else predictor
            group_count = outcome_levels if grouping_variable == outcome else predictor_levels
            valid_group_comparison = (
                predictor_kind == "scale" and o_kind in ("nominal", "ordinal")
            ) or (
                o_kind == "scale" and predictor_kind in ("nominal", "ordinal", "discrete")
            )
            if not valid_group_comparison or group_count < 2:
                continue

            scale_normal = _is_normal(scale_variable, norm)
            if group_count == 2 and scale_normal:
                function, test_type, test_name, parametric = (
                    "run_pairwise_welch", "welch_ttest", "Welch's t-test", True
                )
            elif group_count == 2:
                function, test_type, test_name, parametric = (
                    "run_pairwise_mann_whitney", "mann_whitney", "Mann-Whitney U", False
                )
            elif scale_normal:
                function, test_type, test_name, parametric = (
                    "run_pairwise_anova", "anova_oneway", "One-way ANOVA", True
                )
            else:
                function, test_type, test_name, parametric = (
                    "run_pairwise_kruskal", "kruskal_wallis", "Kruskal-Wallis H", False
                )
            tests.append({
                "id": test_id,
                "title": f"{scale_variable} by {grouping_variable}: {test_name}",
                "why": f"Comparing scale variable {scale_variable} across levels of {grouping_variable}.",
                "columns": [scale_variable, grouping_variable],
                "parametric": parametric,
                "analysis_family": "bivariate",
                "_phase_b": {
                    "function": function,
                    "test_type": test_type,
                    "args": {"predictor": scale_variable, "outcome": grouping_variable},
                },
            })

    if not group and correlation_objective:
        for index, predictor in enumerate(analysis_predictors):
            if o_kind != "scale" or classes.get(predictor, {}).get("detected_type") != "scale":
                continue
            normal_pair = o_normal and _is_normal(predictor, norm)
            function = "pc_pearson" if normal_pair else "pc_spearman"
            test_type = "pearson" if normal_pair else "spearman"
            title = "Pearson correlation" if normal_pair else "Spearman rank correlation"
            tests.append({
                "id": f"association_{index}",
                "title": f"{predictor} vs {outcome}: {title}",
                "why": f"Correlation objective selected for two scale variables ({predictor}, {outcome}).",
                "columns": [predictor, outcome],
                "parametric": normal_pair,
                "analysis_family": "correlation",
                "_phase_b": {
                    "function": function,
                    "test_type": test_type,
                    "args": {"col1": predictor, "col2": outcome},
                },
            })

    if not group and regression_objective:
        model_predictors = covariates or [
            c for c in analysis_predictors
            if classes.get(c, {}).get("detected_type") == "scale"
        ]
        model_predictors = list(dict.fromkeys(model_predictors))
        if o_kind == "scale" and model_predictors:
            tests.append({
                "id": "pc_linear_regression",
                "title": "Multiple linear regression",
                "why": f"Regression / prediction objective selected for scale outcome {outcome}.",
                "columns": [outcome] + model_predictors,
                "parametric": True,
                "analysis_family": "regression",
                "_phase_b": {
                    "function": "pc_linear_regression",
                    "test_type": "linear_regression",
                    "args": {"outcome": outcome, "predictors": model_predictors},
                },
            })
        elif o_kind in ("nominal", "ordinal") and outcome_levels == 2 and model_predictors:
            counts = df[outcome].dropna().value_counts()
            min_events = int(counts.min()) if len(counts) == 2 else 0
            recommended_events = max(10, 10 * len(model_predictors))
            if min_events >= recommended_events:
                tests.append({
                    "id": "pc_binary_logistic",
                    "title": "Binary logistic regression",
                    "why": f"Regression / prediction objective selected for binary outcome {outcome}.",
                    "columns": [outcome] + model_predictors,
                    "parametric": True,
                    "analysis_family": "regression",
                    "_phase_b": {
                        "function": "pc_binary_logistic",
                        "test_type": "logistic_regression",
                        "args": {"outcome": outcome, "predictors": model_predictors},
                    },
                })
            else:
                suggestions.append({
                    "id": "binary_logistic_sparse_warning",
                    "title": "Binary logistic regression not added",
                    "requires_confirmation": True,
                    "warning": (
                        f"The smaller outcome group has {min_events} observations; "
                        f"about {recommended_events} are recommended for {len(model_predictors)} predictors. "
                        "Sparse events may cause unstable estimates or separation."
                    ),
                })

    if (
        not regression_objective
        and o_kind in ("nominal", "ordinal")
        and len(_group_levels(df, outcome)) == 2
        and analysis_predictors
    ):
        suggestions.append({
            "id": "suggest_binary_logistic",
            "title": "Optional multivariable binary logistic regression",
            "requires_confirmation": True,
            "warning": "Add only after confirming predictors and checking event counts and separation risk.",
        })

    numeric_predictors = [
        c for c in analysis_predictors
        if classes.get(c, {}).get("detected_type") == "scale"
    ]
    if not correlation_objective and len(numeric_predictors) >= 2:
        suggestions.append({
            "id": "suggest_correlation_matrix",
            "title": "Optional numeric correlation matrix",
            "requires_confirmation": True,
            "warning": "Run separately under the Correlation objective; it is not part of the main outcome association results.",
        })

    if not group and not tests:
        tests.append({
            "id": "descriptive_only",
            "title": "Descriptive summary",
            "why": "No valid inferential test matched the selected objective and variable types.",
            "columns": [outcome],
            "parametric": False,
            "analysis_family": "descriptive",
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
    if (
        covariates
        and o_kind == "scale"
        and not group
        and not regression_objective
        and session.get("add_multivariable_model")
    ):
        tests.append({
            "id": "pc_linear_regression",
            "title": "Linear regression",
            "why": (
                f"{outcome} ~ {' + '.join(covariates)} — quantifying each "
                "covariate's contribution."
            ),
            "columns": [outcome] + covariates,
            "parametric": True,
            "_phase_b": {
                "function": "pc_linear_regression",
                "test_type": "linear_regression",
                "args": {"outcome": outcome, "predictors": covariates},
            },
        })
    if (
        covariates
        and o_kind in ("nominal", "ordinal")
        and len(_group_levels(df, outcome)) == 2
        and not regression_objective
        and session.get("add_multivariable_model")
    ):
        tests.append({
            "id": "pc_binary_logistic",
            "title": "Binary logistic regression",
            "why": (
                f"Binary outcome {outcome} ~ {' + '.join(covariates)} — odds ratios with 95% CI."
            ),
            "columns": [outcome] + covariates,
            "parametric": True,
            "_phase_b": {
                "function": "pc_binary_logistic",
                "test_type": "logistic_regression",
                "args": {"outcome": outcome, "predictors": covariates},
            },
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

    # Forest plot is only appropriate for logistic / Cox regression
    # (where the effect is an OR or HR with 95% CI). Never for standard
    # comparison or correlation studies.
    _fp_ids = {
        "logistic_regression", "cox_regression",
        "pc_binary_logistic", "pc_multinomial_logistic", "pc_probit", "pb_cox",
    }
    if tests and any(t["id"] in _fp_ids for t in tests):
        graphs.append({
            "id": "forest_plot",
            "title": "Forest plot — odds / hazard ratios",
            "why": "Odds or hazard ratios with 95% CI from regression models.",
            "columns": [outcome] + ([group] if group else []),
        })

    summary_bits = []
    if group:
        summary_bits.append(f"{outcome} by {group}")
    else:
        summary_bits.append(f"{outcome} (no grouping)")
    if covariates:
        summary_bits.append(f"adjusted for {', '.join(covariates)}")
    # ---- Phase B: trigger-based extra tests -----------------------------
    # Each trigger only fires if the relevant session keys / dataset shape
    # is present.  Existing logic above is untouched — these are additive.
    _add_phase_b_triggers(
        tests=tests,
        df=df,
        classes=classes,
        norm=norm,
        outcome=outcome,
        group=group,
        o_kind=o_kind,
        o_normal=o_normal,
        n_levels=n_levels,
        session=session,
    )

    # Filter to runners we actually implement so users never see a confirmed
    # card that ends up "planned but not yet implemented" at run time.
    from . import results as _results
    tests = [t for t in tests if _results.is_supported_test(t["id"])]
    graphs = [g for g in graphs if _results.is_supported_graph(g["id"])]
    tests = _filter_analysis_items(tests, allowed_columns)
    graphs = _filter_analysis_items(graphs, allowed_columns)
    graphs.extend(_test_graph_recommendations(tests, classes, outcome))
    graphs = _filter_analysis_items(graphs, allowed_columns)
    graphs = _enrich_graph_metadata(graphs, outcome)

    if tests and not group and association_objective and analysis_predictors:
        summary = (
            f"We will compare eligible predictors against {outcome}: "
            + ", ".join(t["title"] for t in tests)
            + "."
        )
    elif tests:
        summary = (
            "We will run "
            + ", ".join(t["title"] for t in tests)
            + " on " + " ".join(summary_bits) + "."
        )
    else:
        summary = "No tests will run with the current selection."

    plan = {
        "tests": tests,
        "graphs": graphs,
        "outputs": outputs,
        "suggestions": suggestions,
        "summary": summary,
    }
    plan.update(_layered_contract(
        df, classifications, assignment, session, tests, suggestions
    ))
    return plan


# ---------------------------------------------------------------------------
# Phase B — trigger-based test selection (additive)
# ---------------------------------------------------------------------------
import re as _re


_RATER_WORDS = ('rater', 'observer', 'assessor', 'scorer', 'reader')
_DIAG_WORDS = ('sensitivity', 'specificity', 'roc', 'diagnostic',
               'screening', 'accuracy', 'ppv', 'npv', 'auc')
_SURVIVAL_WORDS = ('survival', 'mortality', 'time to', 'death',
                   'recurrence', 'progression', 'discharge')
_KAPPA_WORDS = ('agreement', 'reliability', 'kappa', 'icc',
                'inter-rater', 'reproducibility')
_PAIRED_WORDS = ('before and after', 'pre and post', 'pre vs post',
                 'paired', 'matched', 'same patient', 'same subject',
                 'repeated on the same')
_RM_WORDS = ('repeated measures', 'longitudinal', 'over time',
             'follow-up at', 'multiple timepoints')


def _objective_text(session: Dict[str, Any]) -> str:
    parts = [
        session.get('objective') or session.get('objective_text') or '',
        session.get('study_type') or '',
        session.get('design') or '',
    ]
    return ' '.join(str(part) for part in parts if part).lower()


def _detect_rater_cols(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns
            if any(w in str(c).lower() for w in _RATER_WORDS)]


def _detect_time_event(df: pd.DataFrame,
                       classes: Dict[str, Dict[str, Any]],
                       session: Dict[str, Any]) -> tuple:
    time_col = session.get('time_variable')
    event_col = session.get('event_variable')
    if time_col and event_col:
        return time_col, event_col
    # Auto-detect: time-like column name + binary event column
    time_candidates = [c for c in df.columns
                       if _re.search(r'time[_ ]?to|follow.?up|duration|months|weeks|days',
                                     str(c), _re.I)]
    event_candidates = []
    for c in df.columns:
        s = str(c).lower()
        if any(w in s for w in ('event', 'death', 'died', 'status',
                                 'outcome_binary', 'censor')):
            try:
                vals = set(df[c].dropna().unique().tolist())
                if vals.issubset({0, 1, 0.0, 1.0, True, False}):
                    event_candidates.append(c)
            except Exception:
                pass
    if time_candidates and event_candidates:
        return time_candidates[0], event_candidates[0]
    return None, None


def _detect_paired_cols(df: pd.DataFrame, outcome: Optional[str]) -> tuple:
    """Look for `<x>_pre` / `<x>_post` style pairs."""
    if not outcome:
        return None, None
    cols = [str(c) for c in df.columns]
    for c in cols:
        cl = c.lower()
        if cl.endswith('_pre') or cl.endswith('_baseline'):
            base = c.rsplit('_', 1)[0]
            for p in cols:
                pl = p.lower()
                if pl.startswith(base.lower() + '_') and (
                    pl.endswith('_post') or pl.endswith('_followup') or
                    pl.endswith('_final') or pl.endswith('_end')
                ):
                    return c, p
    return None, None


def _detect_timepoint_cols(df: pd.DataFrame) -> List[str]:
    """Find columns belonging to a repeated-measures design."""
    pat = _re.compile(r'(?:_|^)(t\d|wk\d+|week\d+|m\d+|month\d+|day\d+|baseline|followup|final)$', _re.I)
    cols = [c for c in df.columns if pat.search(str(c))]
    return cols if len(cols) >= 3 else []


def _is_binary_outcome(df: pd.DataFrame, col: Optional[str]) -> bool:
    if not col or col not in df.columns:
        return False
    try:
        return df[col].dropna().nunique() == 2
    except Exception:
        return False


def _is_count_outcome(df: pd.DataFrame, col: Optional[str]) -> bool:
    if not col or col not in df.columns:
        return False
    try:
        s = pd.to_numeric(df[col], errors='coerce').dropna()
        if len(s) == 0:
            return False
        return bool((s >= 0).all() and (s == s.astype(int)).all())
    except Exception:
        return False


def _add_phase_b_triggers(
    tests: List[Dict[str, Any]],
    df: pd.DataFrame,
    classes: Dict[str, Dict[str, Any]],
    norm: Dict[str, Dict[str, Any]],
    outcome: Optional[str],
    group: Optional[str],
    o_kind: str,
    o_normal: bool,
    n_levels: int,
    session: Dict[str, Any],
) -> None:
    objective = _objective_text(session)

    # ---- TRIGGER 1 — Paired t-test / Wilcoxon -------------------------
    paired_flag = bool(session.get('paired')) or any(w in objective for w in _PAIRED_WORDS)
    p_col1 = session.get('paired_col1') or outcome
    p_col2 = session.get('paired_col2')
    if not p_col2 and paired_flag:
        d1, d2 = _detect_paired_cols(df, outcome)
        if d1 and d2:
            p_col1, p_col2 = d1, d2
    if paired_flag and p_col1 and p_col2 and p_col2 in df.columns:
        normality_ok = norm.get(p_col1, {}).get('decision') == 'normal'
        if normality_ok:
            tests.append({
                'id': 'pb_paired_t',
                'title': 'Paired samples t-test',
                'why': 'Same subjects measured twice with normally distributed outcome.',
                'columns': [p_col1, p_col2],
                'parametric': True,
                '_phase_b': {
                    'function': 'run_paired_ttest',
                    'test_type': 't_test_paired',
                    'args': {'col1': p_col1, 'col2': p_col2},
                },
            })
        else:
            tests.append({
                'id': 'pb_wilcoxon',
                'title': 'Wilcoxon signed-rank test',
                'why': 'Same subjects measured twice with non-normally distributed outcome.',
                'columns': [p_col1, p_col2],
                'parametric': False,
                '_phase_b': {
                    'function': 'run_wilcoxon',
                    'test_type': 'wilcoxon',
                    'args': {'col1': p_col1, 'col2': p_col2},
                },
            })

    # ---- TRIGGER 2 — McNemar -----------------------------------------
    if paired_flag and _is_binary_outcome(df, p_col1) and p_col2 and p_col2 in df.columns:
        tests.append({
            'id': 'pb_mcnemar',
            'title': 'McNemar test',
            'why': 'Paired binary outcomes — comparing proportions before and after in the same subjects.',
            'columns': [p_col1, p_col2],
            'parametric': False,
            '_phase_b': {
                'function': 'run_mcnemar',
                'test_type': 'mcnemar',
                'args': {'col1': p_col1, 'col2': p_col2},
            },
        })

    # ---- TRIGGER 3 — Repeated measures ANOVA / Friedman --------------
    timepoints = list(session.get('timepoints') or _detect_timepoint_cols(df))
    rm_flag = (session.get('design') == 'repeated_measures'
               or any(w in objective for w in _RM_WORDS))
    if rm_flag and len(timepoints) >= 3 and outcome:
        normality_ok = norm.get(outcome, {}).get('decision') == 'normal'
        within = session.get('within_factor')
        subject = session.get('subject_col')
        if normality_ok and within and subject:
            tests.append({
                'id': 'pb_rm_anova',
                'title': 'Repeated Measures ANOVA',
                'why': 'Same subjects at 3 or more timepoints with normally distributed outcome.',
                'columns': [outcome, within, subject],
                'parametric': True,
                '_phase_b': {
                    'function': 'run_rm_anova',
                    'test_type': 'rm_anova',
                    'args': {'dv': outcome, 'within': within, 'subject': subject},
                },
            })
        elif not normality_ok:
            tests.append({
                'id': 'pb_friedman',
                'title': 'Friedman test',
                'why': 'Same subjects at 3 or more timepoints with non-normally distributed outcome.',
                'columns': list(timepoints),
                'parametric': False,
                '_phase_b': {
                    'function': 'run_friedman',
                    'test_type': 'friedman',
                    'args': {'cols': list(timepoints)},
                },
            })

    # ---- TRIGGER 4 — Chi or Fisher swap ------------------------------
    # When the existing logic queued a generic chi_square + fisher fallback,
    # add a single smart entry that picks Fisher automatically when expected
    # cells fall below 5.
    if outcome and group and o_kind in ('nominal', 'ordinal'):
        tests.append({
            'id': 'pb_chi_or_fisher',
            'title': "Chi-square / Fisher's exact (auto-select)",
            'why': "Picks Fisher's exact automatically if any expected cell count is below 5.",
            'columns': [outcome, group],
            'parametric': False,
            '_phase_b': {
                'function': 'run_chi_or_fisher',
                'test_type': 'chi_square',
                'args': {'col1': outcome, 'col2': group},
            },
        })

    # ---- TRIGGER 5 — Kappa / ICC -------------------------------------
    rater_cols = list(session.get('rater_cols') or _detect_rater_cols(df))
    kappa_in_objective = any(w in objective for w in _KAPPA_WORDS)
    if (len(rater_cols) >= 2 or kappa_in_objective) and len(rater_cols) >= 2:
        outcome_type = session.get('outcome_type')
        if outcome_type is None and outcome:
            outcome_type = ('binary' if _is_binary_outcome(df, outcome)
                            else o_kind)
        if outcome_type in ('nominal', 'binary', 'ordinal'):
            is_ordinal = outcome_type == 'ordinal'
            tests.append({
                'id': 'pb_kappa',
                'title': "Weighted Kappa" if is_ordinal else "Cohen's Kappa",
                'why': (
                    'Ordinal ratings from two raters - assessing weighted agreement.'
                    if is_ordinal
                    else 'Two rater columns detected or reliability mentioned in objective.'
                ),
                'columns': rater_cols[:2],
                'parametric': False,
                '_phase_b': {
                    'function': 'run_kappa',
                    'test_type': 'kappa',
                    'args': {
                        'rater_cols': rater_cols[:2],
                        'weighted': is_ordinal,
                    },
                },
            })
        else:
            tests.append({
                'id': 'pb_icc_ba',
                'title': 'ICC and Bland-Altman',
                'why': 'Continuous ratings from two raters — assessing agreement.',
                'columns': rater_cols[:2],
                'parametric': True,
                '_phase_b': {
                    'function': 'run_icc_bland_altman',
                    'test_type': 'icc',
                    'args': {'col1': rater_cols[0], 'col2': rater_cols[1]},
                },
            })

    # ---- TRIGGER 6 — Kaplan-Meier / Cox ------------------------------
    time_col, event_col = _detect_time_event(df, classes, session)
    survival_in_objective = any(w in objective for w in _SURVIVAL_WORDS)
    if (time_col and event_col) or survival_in_objective:
        if group and time_col and event_col:
            tests.append({
                'id': 'pb_km',
                'title': 'Kaplan-Meier + Log-rank',
                'why': 'Time-to-event outcome with group comparison.',
                'columns': [time_col, event_col, group],
                'parametric': False,
                '_phase_b': {
                    'function': 'run_kaplan_meier',
                    'test_type': 'log_rank',
                    'args': {'time_col': time_col,
                             'event_col': event_col,
                             'group_col': group},
                },
            })
        predictors = list(session.get('continuous_predictors') or [])
        if not predictors:
            # Fall back to scale covariates from the assignment
            predictors = [c for c in (session.get('covariates') or [])
                          if classes.get(c, {}).get('detected_type') == 'scale']
        if predictors and time_col and event_col:
            tests.append({
                'id': 'pb_cox',
                'title': 'Cox proportional hazards',
                'why': 'Survival outcome with predictor variables present.',
                'columns': [time_col, event_col] + predictors,
                'parametric': True,
                '_phase_b': {
                    'function': 'run_cox_regression',
                    'test_type': 'cox_regression',
                    'args': {'time_col': time_col,
                             'event_col': event_col,
                             'predictors': predictors},
                },
            })

    # ---- TRIGGER 7 — Diagnostic accuracy / ROC -----------------------
    diagnostic_in_objective = any(w in objective for w in _DIAG_WORDS)
    disease_col = session.get('disease_col')
    test_result_col = session.get('test_result_col')
    if diagnostic_in_objective or (disease_col and test_result_col):
        d_col = disease_col or outcome
        t_col = test_result_col or group
        if d_col and t_col and d_col in df.columns and t_col in df.columns:
            tests.append({
                'id': 'pb_diagnostic',
                'title': 'Diagnostic accuracy + ROC',
                'why': 'Diagnostic accuracy assessment requested in objective.',
                'columns': [d_col, t_col],
                'parametric': False,
                '_phase_b': {
                    'function': 'run_diagnostic_accuracy',
                    'test_type': 'diagnostic_accuracy',
                    'args': {'disease_col': d_col, 'test_col': t_col},
                },
            })

    # ---- TRIGGER 8 — Ordinal logistic regression ---------------------
    outcome_type = session.get('outcome_type')
    if outcome_type is None and outcome and o_kind == 'ordinal':
        outcome_type = 'ordinal'
    if outcome_type == 'ordinal' and outcome:
        predictors = list(session.get('regression_predictors')
                          or session.get('covariates') or [])
        if predictors:
            tests.append({
                'id': 'pb_ordinal',
                'title': 'Ordinal logistic regression',
                'why': 'Outcome variable is ordinal (ordered categories).',
                'columns': [outcome] + predictors,
                'parametric': True,
                '_phase_b': {
                    'function': 'run_ordinal_logistic',
                    'test_type': 'ordinal_logistic',
                    'args': {'outcome': outcome, 'predictors': predictors},
                },
            })

    # ---- TRIGGER 9 — Poisson / Negative binomial ---------------------
    if outcome_type is None and _is_count_outcome(df, outcome):
        outcome_type = 'count'
    if outcome_type == 'count' and outcome:
        predictors = list(session.get('regression_predictors')
                          or session.get('covariates') or [])
        if predictors:
            tests.append({
                'id': 'pb_count',
                'title': 'Poisson / Negative binomial',
                'why': ('Count outcome (whole numbers with no upper limit). '
                        'Model selected based on overdispersion check.'),
                'columns': [outcome] + predictors,
                'parametric': True,
                '_phase_b': {
                    'function': 'run_count_regression',
                    'test_type': 'count_regression',
                    'args': {'outcome': outcome, 'predictors': predictors},
                },
            })


# ---------------------------------------------------------------------------
# Correlation study — pairwise all-vs-outcome plan
# ---------------------------------------------------------------------------


def generate_correlation_plan(
    df: pd.DataFrame,
    classifications: List[Dict[str, Any]],
    outcome_col: str,
) -> Dict[str, Any]:
    """Generate a per-variable pairwise plan for a correlation study.

    For each column that is not the outcome and not excluded/id/date,
    pick the appropriate test and graph type based on variable types.

    Returns::

        {
          "study_type":    "correlation",
          "outcome_col":   str,
          "outcome_levels": int,   # 2 for binary, >2 for multi-level
          "pairs": [
            {
              "predictor":    str,
              "predictor_type": "scale"|"ordinal"|"nominal",
              "outcome_type": "binary"|"nominal"|"scale",
              "test_id":      str,
              "test_title":   str,
              "graph_type":   "stacked_bar"|"boxplot",
            },
            ...
          ],
          "excluded": [{"column": str, "reason": str}, ...],
        }
    """
    classes = _classification_lookup(classifications)
    outcome_class = classes.get(outcome_col, {})
    outcome_dtype = outcome_class.get("detected_type", "nominal")

    # Determine whether outcome is binary, multi-level nominal, or scale
    if outcome_dtype == "scale":
        outcome_kind = "scale"
    elif outcome_dtype in ("nominal", "ordinal"):
        try:
            n_levels = int(df[outcome_col].dropna().nunique())
        except Exception:
            n_levels = 2
        outcome_kind = "binary" if n_levels == 2 else "nominal"
    else:
        outcome_kind = "nominal"

    try:
        outcome_levels = int(df[outcome_col].dropna().nunique())
    except Exception:
        outcome_levels = 2

    pairs: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []

    for c in classifications:
        col = c["column"]
        if col == outcome_col:
            continue
        dtype = c.get("detected_type", "nominal")
        if dtype in ("id", "date", "exclude"):
            excluded.append({"column": col, "reason": dtype})
            continue

        # Pick test + graph based on predictor × outcome type combination
        if dtype == "scale":
            if outcome_kind in ("binary", "nominal"):
                if outcome_levels == 2:
                    test_id = "corr_mann_whitney"
                    test_title = "Mann-Whitney U test"
                else:
                    test_id = "corr_kruskal"
                    test_title = "Kruskal-Wallis H test"
                graph_type = "boxplot"
            else:
                # scale × scale — Spearman (non-parametric default)
                test_id = "corr_spearman"
                test_title = "Spearman rank correlation"
                graph_type = "scatter"
            pred_kind = "scale"
        elif dtype in ("nominal", "ordinal", "discrete"):
            if outcome_kind == "scale":
                excluded.append({
                    "column": col,
                    "reason": "categorical predictor excluded from continuous correlation objective",
                })
                continue
            test_id = "corr_chi_or_fisher"
            test_title = "Chi-square / Fisher's exact"
            graph_type = "stacked_bar"
            pred_kind = "nominal"
        else:
            excluded.append({"column": col, "reason": f"unsupported type: {dtype}"})
            continue

        pairs.append({
            "predictor": col,
            "predictor_type": pred_kind,
            "outcome_type": outcome_kind,
            "test_id": test_id,
            "test_title": test_title,
            "graph_type": graph_type,
        })

    return {
        "study_type": "correlation",
        "outcome_col": outcome_col,
        "outcome_levels": outcome_levels,
        "pairs": pairs,
        "excluded": excluded,
    }
