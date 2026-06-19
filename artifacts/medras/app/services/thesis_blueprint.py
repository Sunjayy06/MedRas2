"""Build a thesis-ready analysis blueprint from Sigma plan/results.

This module intentionally does not render DOCX/PDF.  It creates a structured,
deterministic payload that downstream preview/export layers can use without
asking an LLM to decide statistical content.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _study_type_token(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", " ")
    if "diagnostic" in text or "roc" in text:
        return "diagnostic_accuracy"
    if "survival" in text or "kaplan" in text or "cox" in text or "time to event" in text:
        return "survival"
    if "reliability" in text or "agreement" in text or "kappa" in text or "icc" in text:
        return "reliability_agreement"
    if "bland" in text:
        return "bland_altman_method_comparison"
    if "repeated" in text or "longitudinal" in text or "pre post" in text or "pre-post" in text:
        return "repeated_measures"
    if "regression" in text or "prediction" in text or "predict" in text:
        return "regression_prediction"
    if "correlation" in text:
        return "correlation"
    if "case control" in text:
        return "case_control"
    if "cohort" in text or "prognostic" in text:
        return "cohort_prognostic_association"
    if "rct" in text or "intervention" in text or "trial" in text:
        return "rct_intervention"
    if "comparison" in text or "compare" in text or "two group" in text:
        return "two_group_comparison"
    if "association" in text or "cross sectional" in text:
        return "cross_sectional_association"
    if "prevalence" in text or "descriptive" in text:
        return "descriptive_prevalence"
    if "time series" in text or "trend" in text:
        return "time_series_trend"
    return text.replace(" ", "_") or "general_biostatistical_analysis"


def _class_lookup(classifications: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(row.get("column")): row for row in classifications or [] if row.get("column")}


def _variable_type(classes: Dict[str, Dict[str, Any]], name: Optional[str]) -> str:
    if not name:
        return ""
    return str((classes.get(str(name)) or {}).get("detected_type") or "")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _p_value(test: Dict[str, Any]) -> Optional[float]:
    for key in ("p_corrected", "p", "p_value"):
        value = test.get(key)
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric == numeric:
            return numeric
    return None


def _test_family(test: Dict[str, Any]) -> str:
    family = str(test.get("analysis_family") or "").lower()
    test_type = str(test.get("test_type") or "").lower()
    title = str(test.get("title") or "").lower()
    joined = " ".join([family, test_type, title])
    if "diagnostic" in joined or "auc" in joined or "roc" in joined:
        return "diagnostic_accuracy"
    if "survival" in joined or "cox" in joined or "kaplan" in joined:
        return "survival"
    if "kappa" in joined or "icc" in joined or "bland" in joined or "agreement" in joined:
        return "reliability_agreement"
    if "regression" in joined or "logistic" in joined or "linear_model" in joined:
        return "regression"
    if "correlation" in joined or "pearson" in joined or "spearman" in joined or "kendall" in joined:
        return "correlation"
    if any(token in joined for token in ("chi", "fisher", "ttest", "t-test", "mann", "anova", "kruskal", "wilcoxon")):
        return "bivariate"
    if "descriptive" in joined:
        return "descriptive"
    return "other"


def _graph_type_from_title(title: str) -> str:
    lower = title.lower()
    if "roc" in lower:
        return "roc_curve"
    if "forest" in lower:
        return "forest_plot"
    if "scatter" in lower:
        return "scatter_plot"
    if "box" in lower:
        return "boxplot"
    if "bland" in lower:
        return "bland_altman_plot"
    if "kaplan" in lower:
        return "kaplan_meier_curve"
    if "bar" in lower or "%" in lower:
        return "grouped_or_stacked_bar"
    if "histogram" in lower:
        return "histogram"
    return "result_figure"


def _variables_from_test(test: Dict[str, Any]) -> List[str]:
    cols = test.get("columns")
    if isinstance(cols, list):
        return [str(col) for col in cols if col]
    title = str(test.get("title") or "")
    for sep in (" vs ", " by "):
        if sep in title:
            left, right = title.split(sep, 1)
            right = right.split(":", 1)[0]
            return [left.strip(), right.strip()]
    return []


def _result_pair(test: Dict[str, Any], outcome: Optional[str]) -> tuple[str, str]:
    variables = _variables_from_test(test)
    if len(variables) >= 2:
        if outcome and variables[1] == outcome:
            return variables[0], variables[1]
        if outcome and variables[0] == outcome:
            return variables[1], variables[0]
        return variables[0], variables[1]
    return str(test.get("title") or "Variable"), str(outcome or "Outcome")


def _summary_lookup(test: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for table in test.get("tables") or []:
        headers = [str(h).strip().lower() for h in table.get("headers") or []]
        if len(headers) >= 2 and headers[0] in {"measure", "metric", "statistic"}:
            for row in table.get("rows") or []:
                if isinstance(row, list) and len(row) >= 2:
                    out[str(row[0]).strip().lower()] = str(row[1])
    for row in test.get("rows") or []:
        if isinstance(row, dict) and row.get("label") is not None:
            out[str(row.get("label")).strip().lower()] = str(row.get("value", ""))
    return out


def _fmt_value(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value)
    return "-" if text.strip() in {"", "None", "nan"} else text


def _test_applied(test: Dict[str, Any]) -> str:
    summary = _summary_lookup(test)
    value = (
        summary.get("test used")
        or test.get("actual_test_used")
        or test.get("test")
        or test.get("test_type")
        or test.get("title")
        or "Statistical test"
    )
    text = str(value)
    if ":" in text:
        text = text.split(":", 1)[-1].strip()
    return text


def _statistic_for_table(test: Dict[str, Any]) -> str:
    summary = _summary_lookup(test)
    parts = []
    stat = test.get("statistic") or test.get("stat") or test.get("chi2") or summary.get("statistic")
    if stat not in (None, "", "-"):
        parts.append(_fmt_value(stat))
    df = test.get("df") if test.get("df") is not None else test.get("dof")
    if df is None:
        df = summary.get("df") or summary.get("welch df")
    if df not in (None, "", "-"):
        parts.append(f"df = {_fmt_value(df)}")
    return ", ".join(parts) or "-"


def _effect_for_table(test: Dict[str, Any]) -> str:
    summary = _summary_lookup(test)
    effect = (
        test.get("effect_size")
        if test.get("effect_size") not in (None, "", "-", "—")
        else test.get("cramers_v")
    )
    if effect in (None, "", "-", "—"):
        effect = (
            summary.get("cramer's v / effect size")
            or summary.get("cohen's d")
            or summary.get("rank-biserial correlation")
        )
    if effect in (None, "", "-", "—"):
        return "-"
    label = str(test.get("effect_label") or "").strip()
    test_type = str(test.get("test_type") or "").lower()
    if label in {"", "-", "—"}:
        if test.get("cramers_v") is not None or "chi" in test_type or "fisher" in test_type:
            label = "Cramer's V"
        elif "welch" in test_type or "ttest" in test_type or "t_test" in test_type:
            label = "Cohen's d"
        elif "mann" in test_type:
            label = "Rank-biserial correlation"
        else:
            label = "Effect size"
    return f"{label} = {_fmt_value(effect)}"


def _p_display(test: Dict[str, Any], *, adjusted: bool = False) -> str:
    key = "p_corrected" if adjusted else None
    value = test.get(key) if key else (test.get("p") if test.get("p") is not None else test.get("p_value"))
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if numeric < 0.001:
        return "p < 0.001"
    return f"p = {numeric:.3f}"


def _warning_for_table(test: Dict[str, Any]) -> str:
    summary = _summary_lookup(test)
    return _fmt_value(
        test.get("warning")
        or test.get("note")
        or summary.get("expected-count / sparse-cell warning")
    )


def _observed_table(test: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for table in test.get("tables") or []:
        if str(table.get("title") or "").strip().lower() == "observed counts":
            return table
    return None


def _thesis_table_for_result(test: Dict[str, Any], outcome: Optional[str]) -> Dict[str, Any]:
    family = _test_family(test)
    predictor, target = _result_pair(test, outcome)
    test_id = str(test.get("id") or "result")
    warning = _warning_for_table(test)
    if family == "bivariate" and str(test.get("test_type") or "").lower() in {"chi_square", "fisher_exact"}:
        observed = _observed_table(test)
        headers = list(observed.get("headers") or []) if observed else []
        rows = []
        outcome_headers = headers[1:-1] if headers and headers[-1] == "Total" else headers[1:]
        if observed:
            for row in observed.get("rows") or []:
                if not isinstance(row, list) or not row or str(row[0]).lower() == "total":
                    continue
                counts = row[1:1 + len(outcome_headers)]
                row_total = 0.0
                parsed_counts = []
                for value in counts:
                    try:
                        numeric = float(str(value).replace("%", ""))
                    except (TypeError, ValueError):
                        numeric = 0.0
                    parsed_counts.append(numeric)
                    row_total += numeric
                formatted_counts = [
                    f"{int(count) if count.is_integer() else count:g} ({(count / row_total * 100.0):.1f}%)" if row_total else f"{count:g} (0.0%)"
                    for count in parsed_counts
                ]
                rows.append([
                    row[0],
                    *formatted_counts,
                    _p_display(test),
                    _p_display(test, adjusted=True),
                    _test_applied(test),
                    _effect_for_table(test),
                    warning,
                ])
        return {
            "table_id": f"{test_id}_thesis",
            "title": f"Association of {target} with {predictor}",
            "table_type": "categorical_association_thesis_table",
            "columns": [
                "Predictor category",
                *[f"{label} n (%)" for label in outcome_headers],
                "p-value",
                "Adjusted p-value",
                "Test applied",
                "Effect size",
                "Warnings",
            ],
            "rows": rows or [[predictor, "-", "-", _p_display(test), _p_display(test, adjusted=True), _test_applied(test), _effect_for_table(test), warning]],
            "source_variables": [predictor, target],
            "source_test_ids": [test_id],
            "interpretation": _safe_interpretation(test),
            "thesis_ready": bool(rows),
            "warnings": [warning] if warning != "-" else [],
            "detailed_tables_available": True,
        }
    if family == "bivariate":
        return {
            "table_id": f"{test_id}_thesis",
            "title": f"Comparison of {predictor} by {target}",
            "table_type": "continuous_or_group_comparison_thesis_table",
            "columns": ["Group", "n", "Summary", "Test statistic", "p-value", "Adjusted p-value", "Test applied", "Effect size", "Warnings"],
            "rows": [[
                target,
                _fmt_value(test.get("n") or test.get("n_total")),
                _clean_text(test.get("narrative")) or "See detailed statistical result.",
                _statistic_for_table(test),
                _p_display(test),
                _p_display(test, adjusted=True),
                _test_applied(test),
                _effect_for_table(test),
                warning,
            ]],
            "source_variables": [predictor, target],
            "source_test_ids": [test_id],
            "interpretation": _safe_interpretation(test),
            "thesis_ready": True,
            "warnings": [warning] if warning != "-" else [],
            "detailed_tables_available": bool(test.get("tables")),
        }
    first_table = (test.get("tables") or [{}])[0]
    return {
        "table_id": f"{test_id}_thesis",
        "title": test.get("title") or "Analysis summary",
        "table_type": _summary_table_type_for_result(test),
        "columns": list(first_table.get("headers") or ["Result", "Interpretation"]),
        "rows": list(first_table.get("rows") or [[test.get("title") or test_id, _safe_interpretation(test)]]),
        "source_variables": _variables_from_test(test),
        "source_test_ids": [test_id],
        "interpretation": _safe_interpretation(test),
        "thesis_ready": bool(first_table.get("rows")) or family in {"correlation", "regression", "diagnostic_accuracy", "reliability_agreement"},
        "warnings": [warning] if warning != "-" else [],
        "detailed_tables_available": bool(test.get("tables")),
    }


_OUTCOME_COMPONENT_TERMS = (
    "staining", "interpretation site", "interpretation", "localization",
    "localisation", "intensity", "score", "status", "expression", "marker component",
)


def _outcome_component_variables(
    classifications: List[Dict[str, Any]],
    outcome: Optional[str],
    session: Dict[str, Any],
) -> set[str]:
    marker = str(session.get("main_marker") or "").strip().lower()
    concept = str(session.get("main_outcome_concept") or "").strip().lower()
    outcome_label = str(outcome or "").strip().lower()
    if not (marker or concept or outcome_label):
        return set()
    components: set[str] = set()
    for row in classifications or []:
        col = str(row.get("column") or "")
        low = col.lower()
        if col == outcome:
            continue
        shares_marker = bool(marker and marker in low)
        shares_semantics = any(term in low for term in _OUTCOME_COMPONENT_TERMS)
        concept_tokens = {token for token in concept.replace("/", " ").split() if len(token) >= 4}
        shares_concept = bool(concept_tokens and any(token in low for token in concept_tokens))
        if shares_semantics and (shares_marker or shares_concept or "status" in outcome_label or "expression" in concept):
            components.add(col)
    return components


def _safe_interpretation(test: Dict[str, Any]) -> str:
    p = _p_value(test)
    title = _clean_text(test.get("title") or "This analysis")
    warning = _clean_text(test.get("warning") or test.get("note"))
    family = _test_family(test)
    if p is None:
        base = _clean_text(test.get("narrative")) or f"{title} was completed; review the table for estimates."
    elif family == "correlation":
        base = f"{title} showed a {'significant' if p < 0.05 else 'non-significant'} correlation."
    elif family == "diagnostic_accuracy":
        base = f"{title} produced diagnostic accuracy estimates; interpret sensitivity, specificity, and AUC together."
    elif family == "reliability_agreement":
        base = f"{title} produced agreement estimates; interpret the coefficient with its confidence interval where available."
    elif family == "regression":
        base = (
            f"{title} showed a statistically significant model term."
            if p < 0.05
            else f"{title} did not show a statistically significant model term."
        )
    else:
        base = (
            f"{title} was significantly associated with the outcome."
            if p < 0.05
            else f"{title} was not significantly associated with the outcome."
        )
    if warning:
        base += " Interpret with caution: " + warning
    return base


def _table_type_for_result(test: Dict[str, Any], table: Dict[str, Any]) -> str:
    family = _test_family(test)
    title = str(table.get("title") or "").lower()
    if family == "diagnostic_accuracy":
        return "diagnostic_accuracy_table"
    if family == "reliability_agreement":
        return "agreement_table"
    if family == "correlation":
        return "correlation_table"
    if family == "regression":
        return "regression_table"
    if "observed" in title or "expected" in title or "percentage" in title:
        return "categorical_association_table"
    if family == "bivariate":
        return "two_group_or_bivariate_comparison_table"
    return "result_table"


def _summary_table_type_for_result(test: Dict[str, Any]) -> str:
    family = _test_family(test)
    if family == "diagnostic_accuracy":
        return "diagnostic_accuracy_table"
    if family == "reliability_agreement":
        return "agreement_table"
    if family == "correlation":
        return "correlation_table"
    if family == "regression":
        return "regression_table"
    if family == "bivariate":
        return "two_group_or_bivariate_comparison_table"
    return "summary_table"


def _baseline_section(table_one: Dict[str, Any], classes: Dict[str, Dict[str, Any]], outcome: Optional[str]) -> Dict[str, Any]:
    source_vars: List[str] = []
    for row in table_one.get("rows") or []:
        variable = row.get("variable")
        if variable and variable != outcome:
            source_vars.append(str(variable))
    table = {
        "table_id": "table_one",
        "title": "Table 1. Baseline and study characteristics",
        "table_type": "descriptive_table",
        "columns": list(table_one.get("headers") or []),
        "rows": list(table_one.get("rows") or []),
        "source_variables": source_vars,
        "source_test_ids": [],
        "interpretation": "This table describes the analysed sample and variable distributions.",
        "thesis_ready": bool(table_one.get("rows")),
        "warnings": [],
    }
    return {
        "section_id": "baseline_characteristics",
        "title": "Baseline and Study Characteristics",
        "purpose": "Describe the analysed cohort/sample before inferential testing.",
        "source_results": [],
        "tables": [table],
        "figures": [],
        "interpretation": "Baseline and study characteristics are presented using descriptive statistics.",
    }


def _domain_profile_sections(table_one: Dict[str, Any], domain_profile: str) -> List[Dict[str, Any]]:
    if domain_profile != "breast_pathology":
        return []
    groups = {
        "clinical_study_characteristics": (
            "Clinical and Pathology Characteristics",
            "Summarise tumour and pathology descriptors using the active domain profile.",
            ("tumour", "tumor", "laterality", "site", "pt", "nodal", "node", "lvi", "ene", "necrosis", "dcis", "grade", "stage"),
        ),
        "immunophenotype_characteristics": (
            "Immunophenotype and Marker Characteristics",
            "Summarise receptor, marker, and molecular subtype variables.",
            ("er", "pr", "her2", "her2neu", "ar", "egfr", "ki67", "molecular", "subtype", "marker", "staining", "expression"),
        ),
    }
    sections: List[Dict[str, Any]] = []
    headers = list(table_one.get("headers") or [])
    rows = list(table_one.get("rows") or [])
    for section_id, (title, purpose, keywords) in groups.items():
        matched = [
            row for row in rows
            if any(keyword in str(row.get("variable") or "").lower() for keyword in keywords)
        ]
        if not matched:
            continue
        table = {
            "table_id": f"{section_id}_table",
            "title": title,
            "table_type": "domain_profile_descriptive_table",
            "columns": headers,
            "rows": matched,
            "source_variables": [str(row.get("variable")) for row in matched if row.get("variable")],
            "source_test_ids": [],
            "interpretation": "This table is organised by the selected domain profile; statistical tests remain generated from variable roles and executed results.",
            "thesis_ready": True,
            "warnings": [],
        }
        sections.append({
            "section_id": section_id,
            "title": title,
            "purpose": purpose,
            "source_results": [],
            "tables": [table],
            "figures": [],
            "interpretation": "Domain-profile grouping is descriptive and does not change statistical calculations.",
        })
    return sections


def _outcome_section(outcome: Optional[str], classes: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not outcome:
        return None
    kind = _variable_type(classes, outcome)
    graph_type = "bar_chart" if kind in {"nominal", "ordinal", "binary", "discrete"} else "histogram_or_boxplot"
    figure = {
        "figure_id": "primary_outcome_distribution",
        "title": f"Distribution of {outcome}",
        "graph_type": graph_type,
        "source_variables": [outcome],
        "source_result_id": None,
        "caption": f"Distribution of the primary outcome variable, {outcome}.",
        "interpretation": "Use this figure to inspect outcome balance and missingness before interpreting inferential tests.",
        "thesis_ready": False,
        "optional": False,
        "detailed_report_only": False,
        "warnings": ["Graph image is not generated here unless the executed results already contain one."],
    }
    return {
        "section_id": "primary_outcome_distribution",
        "title": "Primary Outcome Distribution",
        "purpose": "Report the distribution of the confirmed primary outcome.",
        "source_results": [],
        "tables": [],
        "figures": [figure],
        "interpretation": f"The primary outcome for this analysis is {outcome}.",
    }


def _section_template(section_id: str, title: str, purpose: str) -> Dict[str, Any]:
    return {
        "section_id": section_id,
        "title": title,
        "purpose": purpose,
        "source_results": [],
        "tables": [],
        "figures": [],
        "interpretation": "",
    }


_FAMILY_SECTIONS = {
    "bivariate": ("bivariate_associations", "Bivariate Associations / Group Comparisons", "Summarise predictor-by-outcome tests."),
    "correlation": ("correlation_analysis", "Correlation Analysis", "Summarise pairwise correlation results."),
    "regression": ("regression_adjusted_analysis", "Regression / Adjusted Analysis", "Summarise model estimates and adjusted analyses."),
    "diagnostic_accuracy": ("diagnostic_accuracy", "Diagnostic Accuracy", "Summarise diagnostic accuracy metrics."),
    "reliability_agreement": ("reliability_agreement", "Reliability and Agreement", "Summarise agreement and method-comparison analyses."),
    "survival": ("survival_analysis", "Survival / Time-to-Event Analysis", "Summarise time-to-event analyses."),
    "descriptive": ("descriptive_results", "Descriptive Results", "Summarise descriptive-only analyses."),
    "other": ("other_analyses", "Other Analyses", "Summarise additional executed analyses."),
}


def build_thesis_analysis_blueprint(
    *,
    df_shape: Optional[tuple] = None,
    classifications: Optional[List[Dict[str, Any]]] = None,
    assignment: Optional[Dict[str, Any]] = None,
    plan: Optional[Dict[str, Any]] = None,
    table_one: Optional[Dict[str, Any]] = None,
    tests: Optional[List[Dict[str, Any]]] = None,
    graphs: Optional[List[Dict[str, Any]]] = None,
    significant_findings: Optional[List[Dict[str, Any]]] = None,
    methods_text: str = "",
    results_narrative: str = "",
    session: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a general thesis results-chapter blueprint.

    The blueprint is derived from already-executed deterministic Sigma results.
    It does not introduce new tests and does not fabricate unavailable outputs.
    """
    classifications = classifications or []
    assignment = assignment or {}
    plan = plan or {}
    table_one = table_one or {"headers": [], "rows": []}
    tests = tests or []
    graphs = graphs or []
    significant_findings = significant_findings or []
    session = session or {}
    classes = _class_lookup(classifications)
    outcome = assignment.get("outcome") or session.get("outcome_col") or session.get("outcome")
    study_design = _study_type_token(
        session.get("study_type") or session.get("design") or session.get("objective") or plan.get("study_type")
    )
    warnings: List[str] = []
    unavailable: List[Dict[str, Any]] = []
    plan_debug = plan.get("debug") or {}
    excluded = sorted(set(
        session.get("analysis_excluded_columns")
        or session.get("excluded_variables")
        or plan_debug.get("excluded_variables")
        or []
    ))
    if excluded:
        warnings.append("Excluded variables are omitted from thesis tables and figures: " + ", ".join(excluded))
    mapped_outcome = session.get("mapped_outcome") or plan_debug.get("mapped_outcome")
    confirmed_outcome = session.get("confirmed_outcome_col") or plan_debug.get("confirmed_outcome_col")
    displayed_outcome = session.get("displayed_outcome") or assignment.get("outcome") or plan_debug.get("displayed_outcome")
    if mapped_outcome and displayed_outcome and mapped_outcome != displayed_outcome:
        warnings.append("Outcome mismatch detected: mapped outcome differs from the executed/displayed outcome.")
    if confirmed_outcome and displayed_outcome and confirmed_outcome != displayed_outcome:
        warnings.append("Outcome mismatch detected: confirmed outcome differs from the executed/displayed outcome.")
    for suggestion in plan.get("suggestions") or []:
        warning = suggestion.get("warning") or suggestion.get("title")
        if warning:
            warnings.append(str(warning))
    eligible_count = int(plan_debug.get("eligible_predictor_count") or 0)
    bivariate_count = int(plan_debug.get("bivariate_test_count") or 0)
    descriptive_only = any(str(test.get("id")) == "descriptive_only" for test in tests)
    association_design = study_design in {
        "cross_sectional_association", "cohort_prognostic_association",
        "case_control", "two_group_comparison",
    } or str(session.get("study_type") or plan_debug.get("study_type") or "") in {"association", "comparison"}
    if association_design and eligible_count > 0 and bivariate_count == 0:
        warnings.append("Association study has eligible predictors but no bivariate tests were executed.")
    if association_design and descriptive_only:
        warnings.append("Analysis incomplete for thesis association reporting.")

    domain_profile = str(session.get("domain_profile") or "generic")
    sections: List[Dict[str, Any]] = [_baseline_section(table_one, classes, outcome)]
    sections.extend(_domain_profile_sections(table_one, domain_profile))
    outcome_section = _outcome_section(outcome, classes)
    if outcome_section:
        sections.append(outcome_section)

    sections_by_id = {section["section_id"]: section for section in sections}
    all_tables: List[Dict[str, Any]] = [
        table for section in sections for table in section.get("tables", [])
    ]
    all_figures: List[Dict[str, Any]] = list(outcome_section["figures"] if outcome_section else [])
    outcome_components = _outcome_component_variables(classifications, outcome, session)

    for test in tests:
        family = _test_family(test)
        section_id, title, purpose = _FAMILY_SECTIONS.get(family, _FAMILY_SECTIONS["other"])
        section = sections_by_id.get(section_id)
        if section is None:
            section = _section_template(section_id, title, purpose)
            sections_by_id[section_id] = section
            sections.append(section)
        test_id = str(test.get("id") or f"result_{len(section['source_results']) + 1}")
        section["source_results"].append(test_id)
        variables = _variables_from_test(test)
        interpretation = _safe_interpretation(test)
        bp_table = _thesis_table_for_result(test, outcome)
        section["tables"].append(bp_table)
        all_tables.append(bp_table)
        for idx, fig in enumerate(test.get("figures") or [], 1):
            fig_title = str(fig.get("title") or test.get("title") or f"Figure {idx}")
            bp_fig = {
                "figure_id": f"{test_id}_figure_{idx}",
                "title": fig_title,
                "graph_type": _graph_type_from_title(fig_title),
                "source_variables": variables,
                "source_result_id": test_id,
                "caption": fig.get("caption") or fig_title,
                "interpretation": interpretation,
                "thesis_ready": bool(fig.get("png_data_uri")),
                "optional": family != "diagnostic_accuracy",
                "detailed_report_only": False,
                "warnings": [],
            }
            section["figures"].append(bp_fig)
            all_figures.append(bp_fig)
        section["interpretation"] = " ".join(
            part for part in [section.get("interpretation"), interpretation] if part
        ).strip()

    for graph in graphs:
        graph_id = str(graph.get("id") or f"graph_{len(all_figures) + 1}")
        title = str(graph.get("title") or "Planned figure")
        bp_fig = {
            "figure_id": graph_id,
            "title": title,
            "graph_type": graph.get("graph_type") or _graph_type_from_title(title),
            "source_variables": list(graph.get("columns") or []),
            "source_result_id": graph.get("source_result_id"),
            "caption": graph.get("caption") or title,
            "interpretation": graph.get("interpretation") or "Figure generated from the executed Sigma analysis.",
            "thesis_ready": bool(graph.get("png_data_uri")),
            "optional": True,
            "detailed_report_only": False,
            "warnings": [] if graph.get("png_data_uri") else ["Figure metadata is available; image rendering is pending or unavailable."],
        }
        all_figures.append(bp_fig)
        section = sections_by_id.get("bivariate_associations") or sections_by_id.get("descriptive_results")
        if section:
            section["figures"].append(bp_fig)

    max_default_figures = 8
    for idx, figure in enumerate(all_figures):
        is_primary = figure.get("figure_id") == "primary_outcome_distribution"
        if idx >= max_default_figures and not is_primary:
            figure["optional"] = True
            figure["detailed_report_only"] = True
            warning_list = list(figure.get("warnings") or [])
            warning_list.append("Held for detailed report to keep the thesis blueprint concise.")
            figure["warnings"] = warning_list

    thesis_findings = []
    for finding in significant_findings:
        variable = str(finding.get("variable") or "")
        if variable in excluded:
            continue
        if any(variable == comp or variable.startswith(f"{comp} vs ") or variable.startswith(f"{comp} by ") for comp in outcome_components):
            continue
        thesis_findings.append(finding)

    if thesis_findings:
        rows = [
            [
                finding.get("variable") or "",
                finding.get("key_finding") or "",
                finding.get("p_value") or "",
                finding.get("adjusted_p_value") or "-",
                finding.get("test_applied") or "",
                finding.get("effect_size") or "",
                finding.get("notes_warnings") or "",
            ]
            for finding in thesis_findings
        ]
        sig_table = {
            "table_id": "significant_findings",
            "title": "Summary of statistically significant findings",
            "table_type": "significant_findings_table",
            "columns": ["Variable / parameter", "Key finding", "p-value", "Adjusted p-value", "Test applied", "Effect size", "Notes/warnings"],
            "rows": rows,
            "source_variables": [],
            "source_test_ids": [str(f.get("variable") or "") for f in thesis_findings],
            "interpretation": "Only statistically significant completed tests are listed here.",
            "thesis_ready": True,
            "warnings": [],
        }
        sig_section = _section_template(
            "significant_findings_summary",
            "Significant Findings Summary",
            "Highlight statistically significant completed tests without implying causality.",
        )
        sig_section["tables"].append(sig_table)
        sig_section["interpretation"] = "Statistically significant findings should be interpreted in the context of study design and multiplicity."
        sections.append(sig_section)
        all_tables.append(sig_table)
    elif outcome_components and significant_findings:
        warnings.append(
            "Some significant detailed results were outcome/marker components and were omitted from the final thesis findings table by default."
        )

    executed_families = {_test_family(test) for test in tests}
    planned_ids = {str(test.get("id") or "") for test in plan.get("tests") or []}
    for family, (section_id, title, _) in _FAMILY_SECTIONS.items():
        if family in {"bivariate", "descriptive", "other"}:
            continue
        if family not in executed_families and any(family.split("_", 1)[0] in str(item).lower() for item in planned_ids):
            unavailable.append({
                "section_id": section_id,
                "title": title,
                "status": "recommended_only",
                "reason": "The plan referenced this analysis family, but no completed result was available.",
            })

    n_rows = df_shape[0] if df_shape else session.get("n")
    n_cols = df_shape[1] if df_shape else None
    thesis_ready = not any(
        warning in set(warnings)
        for warning in {
            "Association study has eligible predictors but no bivariate tests were executed.",
            "Analysis incomplete for thesis association reporting.",
        }
    ) and not any("Outcome mismatch detected" in warning for warning in warnings)
    return {
        "title": "Observation and Results",
        "thesis_ready": thesis_ready,
        "debug_metadata": {
            "canonical_outcome": outcome or "",
            "displayed_outcome": displayed_outcome or "",
            "mapped_outcome": mapped_outcome or "",
            "confirmed_outcome_col": confirmed_outcome or "",
            "study_type_raw": session.get("raw_study_type") or plan_debug.get("study_type_raw") or plan_debug.get("raw_study_type") or "",
            "study_type_normalized": session.get("study_type") or plan_debug.get("study_type_normalized") or plan_debug.get("study_type") or study_design,
            "predictor_source": session.get("predictor_source") or plan_debug.get("predictor_source") or "",
            "eligible_predictor_count": eligible_count,
            "bivariate_test_count": bivariate_count,
            "graph_count": int(plan_debug.get("graph_count") or len(graphs)),
            "descriptive_only_reason": plan_debug.get("descriptive_only_reason"),
            "blueprint_thesis_ready": thesis_ready,
        },
        "study_summary": {
            "n": n_rows,
            "n_variables": n_cols,
            "domain_profile": domain_profile,
            "objective": session.get("objective") or session.get("objective_text") or "",
        },
        "study_design": study_design,
        "primary_outcome": outcome or "",
        "analysis_sections": sections,
        "tables": all_tables,
        "figures": all_figures,
        "significant_findings": thesis_findings,
        "methods_text": methods_text,
        "results_narrative": results_narrative,
        "warnings": list(dict.fromkeys(warnings)),
        "unavailable_or_recommended_only": unavailable,
    }
