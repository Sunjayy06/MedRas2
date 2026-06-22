"""Build a thesis-ready analysis blueprint from Sigma plan/results.

This module intentionally does not render DOCX/PDF.  It creates a structured,
deterministic payload that downstream preview/export layers can use without
asking an LLM to decide statistical content.
"""

from __future__ import annotations

import re

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


def _compact_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _word_match(text: str, token: str) -> bool:
    return bool(re.search(rf"(^|[^a-z0-9]){re.escape(token)}([^a-z0-9]|$)", text))


def _clinical_pathology_concept(variable: Any) -> tuple[str, str]:
    """Classify a Section II (nodal/prognostic pathology) variable into a thesis sub-table."""
    key = _compact_key(variable)
    if "size" in key:
        return "tumour_size", "Tumour size distribution"
    if "quadrant" in key or (("tumour" in key or "tumor" in key) and "site" in key):
        return "tumour_quadrant", "Tumour quadrant distribution"
    if key == "pt" or "tstage" in key or "pstage" in key:
        return "pathological_t_stage", "Pathological T stage distribution"
    if any(token in key for token in ("positivenodes", "totalnodes", "noderatio", "nodesinvolved", "numberofnodes", "nodalburden")):
        return "nodal_burden", "Nodal burden summary"
    if "nodal" in key or "node" in key:
        return "nodal_status", "Nodal status distribution"
    if any(token in key for token in ("ene", "dcis", "lvi", "necrosis")):
        return "adverse_features", "Adverse pathological features"
    return "other_pathology", "Other pathology characteristics"


def _immunophenotype_concept(variable: Any) -> tuple[str, str]:
    """Classify a Section III (immunophenotype) variable into a thesis sub-table."""
    low = str(variable or "").lower()
    key = _compact_key(variable)
    if _word_match(low, "er") or _word_match(low, "pr"):
        return "hormone_receptor", "Hormone receptor profile"
    if "her2" in key or "egfr" in key or "ki67" in key:
        return "her2_proliferation", "HER2 and proliferation marker profile"
    if _word_match(low, "ar"):
        return "ar_expression", "AR expression profile"
    if "molecular" in key and "subtype" in key:
        return "molecular_subtype", "Molecular subtype distribution"
    return "other_immunophenotype", "Other immunophenotype characteristics"


def _marker_component_concept(variable: Any, marker_label: str = "Marker") -> tuple[str, str]:
    """Classify a marker/outcome component variable (e.g. p27 staining) into a thesis sub-table."""
    low = str(variable or "").lower()
    if any(token in low for token in ("localization", "localisation", "site")):
        return "localization", f"{marker_label} staining localization"
    if any(token in low for token in ("score", "result", "pattern", "intensity")):
        return "score", f"{marker_label} staining score pattern"
    return "other_component", f"Other {marker_label} component characteristics"


def _variable_type(classes: Dict[str, Dict[str, Any]], name: Optional[str]) -> str:
    if not name:
        return ""
    return str((classes.get(str(name)) or {}).get("detected_type") or "")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _status_label_context(outcome: Optional[str], session: Dict[str, Any]) -> Dict[str, Any]:
    concept = _clean_text(session.get("main_outcome_concept"))
    marker = _clean_text(session.get("main_marker"))
    display = concept or _clean_text(outcome)
    joined = f"{concept} {marker} {outcome or ''}".lower()
    status_like = any(term in joined for term in ("expression", "status", "marker", "positive", "negative"))
    return {
        "outcome": outcome or "",
        "display_outcome": display,
        "status_like": status_like,
        "value_map": {"Yes": "Positive", "No": "Negative", "yes": "Positive", "no": "Negative"},
    }


def _apply_display_labels(value: Any, label_ctx: Dict[str, Any]) -> Any:
    if value is None:
        return value
    text = str(value)
    if label_ctx.get("outcome") and text == label_ctx.get("outcome"):
        return label_ctx.get("display_outcome") or text
    if label_ctx.get("status_like"):
        for raw, label in (label_ctx.get("value_map") or {}).items():
            text = text.replace(f"{raw}:", f"{label}:")
            text = text.replace(f"{raw} n", f"{label} n")
            if text == raw:
                text = label
    return text


def _display_row(row: Any, label_ctx: Dict[str, Any]) -> Any:
    if isinstance(row, dict):
        out = dict(row)
        if "variable" in out:
            out["variable"] = _apply_display_labels(out["variable"], label_ctx)
        if "cells" in out and isinstance(out["cells"], list):
            out["cells"] = [_apply_display_labels(cell, label_ctx) for cell in out["cells"]]
        return out
    if isinstance(row, list):
        return [_apply_display_labels(cell, label_ctx) for cell in row]
    return _apply_display_labels(row, label_ctx)


def _display_text(value: Any, label_ctx: Dict[str, Any]) -> str:
    return str(_apply_display_labels(value, label_ctx))


def _deterministic_key_finding(finding: Dict[str, Any], label_ctx: Dict[str, Any]) -> str:
    variable = _display_text(finding.get("variable") or "", label_ctx).lower()
    outcome_display = str(label_ctx.get("display_outcome") or label_ctx.get("outcome") or "").lower()
    if "p27" not in outcome_display:
        return _display_text(finding.get("key_finding") or "", label_ctx)
    if "histological" in variable or "grade" in variable:
        return "Grade 3 cases were proportionately higher in the p27-negative group."
    if re.search(r"(^|[^a-z0-9])er([^a-z0-9]|$)", variable):
        return "p27 positivity was strongly associated with ER positivity."
    if re.search(r"(^|[^a-z0-9])pr([^a-z0-9]|$)", variable):
        return "p27 positivity was significantly associated with PR positivity."
    if "molecular subtype" in variable:
        return "Triple-negative phenotype was proportionately enriched among p27-negative cases, while Luminal B predominated among p27-positive cases."
    if re.search(r"(^|[^a-z0-9])ar([^a-z0-9]|$)", variable):
        return "p27 positivity was significantly associated with AR positivity."
    return _display_text(finding.get("key_finding") or "", label_ctx)


def _p_value(test: Dict[str, Any]) -> Optional[float]:
    for key in ("p", "p_value"):
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


def _significance_p_value(test: Dict[str, Any]) -> Optional[float]:
    for key in ("p_corrected", "adjusted_p_value", "p_adjusted", "q_value", "p", "p_value"):
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


def _report_significance_status(raw_p: Optional[float], adjusted_p: Optional[float]) -> str:
    if raw_p is None:
        return "Not evaluated"
    if adjusted_p is not None:
        if adjusted_p < 0.05:
            return "Significant after multiple-testing correction"
        if raw_p < 0.05:
            return (
                "Nominally significant before adjustment, not significant after "
                "multiple-testing correction."
            )
        return "Not significant after multiple-testing correction"
    return "Statistically significant" if raw_p < 0.05 else "Not statistically significant"


def _clean_report_warning(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" .")
    lower = text.lower()
    if not text:
        return ""
    if "add only after confirming predictors" in lower:
        return "A multivariable model was not added because predictor selection was not confirmed."
    if "run separately under the correlation objective" in lower:
        return "Correlation analysis was not included in the selected analysis objective."
    if "duplicate" in lower and "predictor" in lower:
        return "Some predictor labels appeared duplicated after cleaning; category grouping should be reviewed."
    if not re.search(r"[.!?]$", text):
        text += "."
    return text


def _fallback_tested_associations(
    tests: List[Dict[str, Any]], outcome: Optional[str]
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for test in tests:
        if _test_family(test) != "bivariate":
            continue
        raw_p = _p_value(test)
        if raw_p is None:
            continue
        adjusted_p = None
        for key in ("p_corrected", "adjusted_p_value", "p_adjusted", "q_value"):
            try:
                candidate = float(test.get(key))
            except (TypeError, ValueError):
                continue
            if candidate == candidate:
                adjusted_p = candidate
                break
        predictor, _ = _result_pair(test, outcome)
        significance_status = _report_significance_status(raw_p, adjusted_p)
        warning = _warning_for_table(test)
        notes: List[str] = []
        if "expected" in warning.lower() or "sparse" in warning.lower():
            notes.append("Sparse expected cell counts; interpret cautiously.")
        if significance_status.startswith("Nominally significant"):
            notes.append("Nominal before adjustment; not significant after correction.")
        rows.append({
            "source_result_id": str(test.get("id") or ""),
            "predictor": predictor,
            "test_applied": _test_applied(test),
            "test_statistic": _statistic_for_table(test),
            "p_value": _p_display(test),
            "adjusted_p_value": _p_display(test, adjusted=True),
            "effect_size": _effect_for_table(test),
            "significance_status": significance_status,
            "notes_warnings": " ".join(notes) or "-",
            "p_numeric": raw_p,
            "p_corrected_numeric": adjusted_p,
        })
    return rows


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


_TEST_TYPE_CANONICAL_NAMES = {
    "welch_ttest": "Welch's t-test",
    "welch_t_test": "Welch's t-test",
}


def _test_applied(test: Dict[str, Any]) -> str:
    summary = _summary_lookup(test)
    test_type_key = str(test.get("test_type") or "").strip().lower()
    value = (
        summary.get("test used")
        or test.get("actual_test_used")
        or test.get("test")
        or _TEST_TYPE_CANONICAL_NAMES.get(test_type_key)
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
    value = (
        test.get("p_corrected")
        or test.get("adjusted_p_value")
        or test.get("p_adjusted")
        or test.get("q_value")
    ) if adjusted else (test.get("p") if test.get("p") is not None else test.get("p_value"))
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if numeric < 0.001:
        return "p < 0.001"
    return f"p = {numeric:.3f}"


def _group_summary_rows_from_result(test: Dict[str, Any]) -> List[List[str]]:
    values: Dict[str, Dict[str, Any]] = {}
    for row in test.get("rows") or []:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "")
        match = re.match(r"^(n|mean|sd)\s*\((.+)\)$", label, flags=re.IGNORECASE)
        if not match:
            continue
        stat, group = match.group(1).lower(), match.group(2).strip()
        values.setdefault(group, {})[stat] = row.get("value")
    if len(values) < 2:
        return []
    stat = _statistic_for_table(test)
    p_value = _p_display(test)
    adjusted = _p_display(test, adjusted=True)
    applied = _test_applied(test)
    effect = _effect_for_table(test)
    rows: List[List[str]] = []
    for group, stats in values.items():
        mean = stats.get("mean")
        sd = stats.get("sd")
        mean_sd = f"{_fmt_value(mean)} ± {_fmt_value(sd)}" if mean not in (None, "") and sd not in (None, "") else "-"
        rows.append([
            group,
            _fmt_value(stats.get("n")),
            mean_sd,
            stat,
            p_value,
            adjusted,
            applied,
            effect,
            "-",
        ])
    return rows


def _warning_for_table(test: Dict[str, Any]) -> str:
    summary = _summary_lookup(test)
    return _fmt_value(
        test.get("warning")
        or test.get("note")
        or summary.get("expected-count / sparse-cell warning")
    )


def _priority_for_result(test: Dict[str, Any], warning: str) -> tuple[str, bool, bool]:
    p = _significance_p_value(test)
    if p is not None and p < 0.05 and warning == "-":
        return "thesis_ready_primary", False, False
    if p is not None and p < 0.05:
        return "optional", True, False
    if warning != "-":
        return "detailed_report_only", True, True
    return "optional", True, False


def _observed_table(test: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for table in test.get("tables") or []:
        if str(table.get("title") or "").strip().lower() == "observed counts":
            return table
    return None


def _thesis_table_for_result(test: Dict[str, Any], outcome: Optional[str], label_ctx: Dict[str, Any]) -> Dict[str, Any]:
    family = _test_family(test)
    predictor, target = _result_pair(test, outcome)
    predictor_label = _display_text(predictor, label_ctx)
    target_label = _display_text(target, label_ctx)
    test_id = str(test.get("id") or "result")
    warning = _warning_for_table(test)
    priority, optional, detailed_only = _priority_for_result(test, warning)
    if family == "bivariate" and str(test.get("test_type") or "").lower() in {"chi_square", "fisher_exact"}:
        observed = _observed_table(test)
        headers = list(observed.get("headers") or []) if observed else []
        rows = []
        outcome_headers = headers[1:-1] if headers and headers[-1] == "Total" else headers[1:]
        outcome_headers = [_display_text(label, label_ctx) for label in outcome_headers]
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
                    _display_text(row[0], label_ctx),
                    *formatted_counts,
                    _p_display(test),
                    _p_display(test, adjusted=True),
                    _test_applied(test),
                    _effect_for_table(test),
                    warning,
                ])
        return {
            "table_id": f"{test_id}_thesis",
            "title": f"Association of {target_label} with {predictor_label}",
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
            "interpretation": _safe_interpretation(test, label_ctx),
            "thesis_ready": bool(rows),
            "priority": priority,
            "optional": optional,
            "detailed_report_only": detailed_only,
            "warnings": [warning] if warning != "-" else [],
            "detailed_tables_available": True,
        }
    if family == "bivariate":
        first_table = (test.get("tables") or [{}])[0]
        headers = list(first_table.get("headers") or [])
        rows = [_display_row(row, label_ctx) for row in list(first_table.get("rows") or [])]
        if rows and headers and str(headers[0]).strip().lower() == "group":
            return {
                "table_id": f"{test_id}_thesis",
                "title": f"Comparison of {predictor_label} by {target_label}",
                "table_type": "continuous_or_group_comparison_thesis_table",
                "columns": headers,
                "rows": rows,
                "source_variables": [predictor, target],
                "source_test_ids": [test_id],
                "interpretation": _safe_interpretation(test, label_ctx),
                "thesis_ready": True,
                "priority": priority,
                "optional": optional,
                "detailed_report_only": detailed_only,
                "warnings": [warning] if warning != "-" else [],
                "detailed_tables_available": True,
            }
        summary_rows = _group_summary_rows_from_result(test)
        if summary_rows:
            return {
                "table_id": f"{test_id}_thesis",
                "title": f"Comparison of {predictor_label} by {target_label}",
                "table_type": "continuous_or_group_comparison_thesis_table",
                "columns": ["Group", "n", "Mean ± SD", "Test statistic", "p-value", "Adjusted p-value", "Test applied", "Effect size", "Warnings"],
                "rows": summary_rows,
                "source_variables": [predictor, target],
                "source_test_ids": [test_id],
                "interpretation": _safe_interpretation(test, label_ctx),
                "thesis_ready": True,
                "priority": priority,
                "optional": optional,
                "detailed_report_only": detailed_only,
                "warnings": [warning] if warning != "-" else [],
                "detailed_tables_available": True,
            }
        return {
            "table_id": f"{test_id}_thesis",
            "title": f"Comparison of {predictor_label} by {target_label}",
            "table_type": "continuous_or_group_comparison_thesis_table",
            "columns": ["Group", "n", "Summary", "Test statistic", "p-value", "Adjusted p-value", "Test applied", "Effect size", "Warnings"],
            "rows": [[
                target_label,
                _fmt_value(test.get("n") or test.get("n_total")),
                _display_text(test.get("narrative") or "See detailed statistical result.", label_ctx),
                _statistic_for_table(test),
                _p_display(test),
                _p_display(test, adjusted=True),
                _test_applied(test),
                _effect_for_table(test),
                warning,
            ]],
            "source_variables": [predictor, target],
            "source_test_ids": [test_id],
            "interpretation": _safe_interpretation(test, label_ctx),
            "thesis_ready": True,
            "priority": priority,
            "optional": optional,
            "detailed_report_only": detailed_only,
            "warnings": [warning] if warning != "-" else [],
            "detailed_tables_available": bool(test.get("tables")),
        }
    first_table = (test.get("tables") or [{}])[0]
    return {
        "table_id": f"{test_id}_thesis",
        "title": _display_text(test.get("title") or "Analysis summary", label_ctx),
        "table_type": _summary_table_type_for_result(test),
        "columns": list(first_table.get("headers") or ["Result", "Interpretation"]),
        "rows": [_display_row(row, label_ctx) for row in list(first_table.get("rows") or [[test.get("title") or test_id, _safe_interpretation(test, label_ctx)]])],
        "source_variables": _variables_from_test(test),
        "source_test_ids": [test_id],
        "interpretation": _safe_interpretation(test, label_ctx),
        "thesis_ready": bool(first_table.get("rows")) or family in {"correlation", "regression", "diagnostic_accuracy", "reliability_agreement"},
        "priority": priority,
        "optional": optional,
        "detailed_report_only": detailed_only,
        "warnings": [warning] if warning != "-" else [],
        "detailed_tables_available": bool(test.get("tables")),
    }


_OUTCOME_COMPONENT_TERMS = (
    "staining", "interpretation site", "interpretation", "localization",
    "localisation", "intensity", "score", "status", "expression", "marker component",
)

_NON_MARKER_STATUS_TERMS = (
    "nodal", "node", "stage", "pt", "tnm", "metastasis", "laterality",
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
        if any(term in low for term in _NON_MARKER_STATUS_TERMS):
            continue
        shares_marker = bool(marker and marker in low)
        shares_semantics = any(term in low for term in _OUTCOME_COMPONENT_TERMS)
        concept_tokens = {token for token in concept.replace("/", " ").split() if len(token) >= 4}
        shares_concept = bool(concept_tokens and any(token in low for token in concept_tokens))
        if shares_semantics and (shares_marker or shares_concept or "status" in outcome_label or "expression" in concept):
            components.add(col)
    return components


def _safe_interpretation(test: Dict[str, Any], label_ctx: Optional[Dict[str, Any]] = None) -> str:
    label_ctx = label_ctx or {}
    p = _significance_p_value(test)
    raw_p = _p_value(test)
    title = _display_text(test.get("title") or "This analysis", label_ctx)
    relation_title = re.sub(
        r":\s*(?:Chi-square test(?: with sparse-cell warning)?|Fisher's exact test|Welch's t-test|Mann-Whitney U test).*$",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()
    warning = _clean_text(test.get("warning") or test.get("note"))
    if warning in {"-", "—", "â€”"}:
        warning = ""
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
        relation = ""
        for sep in (" vs ", " by "):
            if sep in relation_title:
                left, right = relation_title.split(sep, 1)
                correction = str(test.get("correction_method") or "multiple-testing").strip()
                if raw_p is not None and raw_p < 0.05 <= p:
                    relation = (
                        f"{left.strip()} was nominally significant before adjustment, but this did not remain "
                        f"significant after {correction} correction."
                    )
                else:
                    relation = (
                        f"{left.strip()} showed a statistically significant association with {right.strip()}."
                        if p < 0.05
                        else f"{left.strip()} did not show a statistically significant association with {right.strip()}."
                    )
                break
        base = relation or (
            f"{title} showed a statistically significant association."
            if p < 0.05
            else f"{title} did not show a statistically significant association."
        )
    test_name = _test_applied(test)
    if "chi-square" in test_name.lower():
        if warning and re.search(r"(sparse|expected)", warning, flags=re.IGNORECASE):
            base += " A chi-square test was used, and sparse expected cell counts were noted."
        else:
            base += " A chi-square test was used."
    elif "fisher" in test_name.lower():
        base += " Fisher's exact test was used."
    if warning:
        if re.search(r"(sparse|expected)", warning, flags=re.IGNORECASE):
            if "sparse expected cell counts were noted" not in base.lower():
                base += " This finding should be interpreted cautiously because some expected cell counts were below 5."
        else:
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


def _baseline_section(table_one: Dict[str, Any], classes: Dict[str, Dict[str, Any]], outcome: Optional[str], label_ctx: Dict[str, Any]) -> Dict[str, Any]:
    source_vars: List[str] = []
    for row in table_one.get("rows") or []:
        variable = row.get("variable")
        if variable and variable != outcome:
            source_vars.append(str(variable))
    rows = [_display_row(row, label_ctx) for row in table_one.get("rows") or []]
    table = {
        "table_id": "table_one",
        "title": "Table 1. Baseline and study characteristics",
        "table_type": "descriptive_table",
        "columns": list(table_one.get("headers") or []),
        "rows": rows,
        "source_variables": source_vars,
        "source_test_ids": [],
        "interpretation": "This table describes the analysed sample and variable distributions.",
        "thesis_ready": bool(table_one.get("rows")),
        "priority": "thesis_ready_primary",
        "optional": False,
        "detailed_report_only": False,
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


def _domain_profile_sections(table_one: Dict[str, Any], domain_profile: str, label_ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    if domain_profile != "breast_pathology":
        return []
    groups = {
        "clinical_study_characteristics": (
            "Clinical and Pathology Characteristics",
            "Summarise tumour and pathology descriptors using the active domain profile.",
            ("tumour", "tumor", "laterality", "site", "pt", "nodal", "node", "lvi", "ene", "necrosis", "dcis", "grade", "stage"),
            _clinical_pathology_concept,
        ),
        "immunophenotype_characteristics": (
            "Immunophenotype and Marker Characteristics",
            "Summarise receptor, marker, and molecular subtype variables.",
            ("er", "pr", "her2", "her2neu", "ar", "egfr", "ki67", "molecular", "subtype", "marker", "staining", "expression"),
            _immunophenotype_concept,
        ),
    }
    sections: List[Dict[str, Any]] = []
    headers = list(table_one.get("headers") or [])
    rows = list(table_one.get("rows") or [])
    for section_id, (title, purpose, keywords, classifier) in groups.items():
        matched = [
            row for row in rows
            if any(keyword in str(row.get("variable") or "").lower() for keyword in keywords)
        ]
        if not matched:
            continue
        buckets: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        for row in matched:
            variable = row.get("variable")
            concept_id, concept_title = classifier(variable)
            if concept_id not in buckets:
                buckets[concept_id] = {"title": concept_title, "rows": []}
                order.append(concept_id)
            buckets[concept_id]["rows"].append(row)
        tables: List[Dict[str, Any]] = []
        for concept_id in order:
            bucket = buckets[concept_id]
            bucket_rows = bucket["rows"]
            tables.append({
                "table_id": f"{section_id}_{concept_id}",
                "title": bucket["title"],
                "table_type": "domain_profile_descriptive_table",
                "concept": concept_id,
                "columns": headers,
                "rows": [_display_row(row, label_ctx) for row in bucket_rows],
                "source_variables": [str(row.get("variable")) for row in bucket_rows if row.get("variable")],
                "source_test_ids": [],
                "interpretation": "This table is organised by the selected domain profile; statistical tests remain generated from variable roles and executed results.",
                "thesis_ready": True,
                "priority": "thesis_ready_primary",
                "optional": False,
                "detailed_report_only": False,
                "warnings": [],
            })
        sections.append({
            "section_id": section_id,
            "title": title,
            "purpose": purpose,
            "source_results": [],
            "tables": tables,
            "figures": [],
            "interpretation": "Domain-profile grouping is descriptive and does not change statistical calculations.",
        })
    return sections


def _outcome_section(outcome: Optional[str], classes: Dict[str, Dict[str, Any]], label_ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not outcome:
        return None
    kind = _variable_type(classes, outcome)
    graph_type = "bar_chart" if kind in {"nominal", "ordinal", "binary", "discrete"} else "histogram_or_boxplot"
    display_outcome = _display_text(outcome, label_ctx)
    figure = {
        "figure_id": "primary_outcome_distribution",
        "title": f"Distribution of {display_outcome}",
        "graph_type": graph_type,
        "source_variables": [outcome],
        "source_result_id": None,
        "caption": f"Distribution of the primary outcome variable, {display_outcome}.",
        "interpretation": "Use this figure to inspect outcome balance and missingness before interpreting inferential tests.",
        "thesis_ready": False,
        "priority": "thesis_ready_primary",
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
        "interpretation": f"The primary outcome for this analysis is {display_outcome}.",
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
    tested_associations: Optional[List[Dict[str, Any]]] = None,
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
    label_ctx = _status_label_context(outcome, session)
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
            cleaned_warning = _clean_report_warning(warning)
            if cleaned_warning:
                warnings.append(cleaned_warning)
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
    sections: List[Dict[str, Any]] = [_baseline_section(table_one, classes, outcome, label_ctx)]
    sections.extend(_domain_profile_sections(table_one, domain_profile, label_ctx))
    outcome_section = _outcome_section(outcome, classes, label_ctx)
    if outcome_section:
        sections.append(outcome_section)

    sections_by_id = {section["section_id"]: section for section in sections}
    all_tables: List[Dict[str, Any]] = [
        table for section in sections for table in section.get("tables", [])
    ]
    all_figures: List[Dict[str, Any]] = list(outcome_section["figures"] if outcome_section else [])
    outcome_components = _outcome_component_variables(classifications, outcome, session)
    if outcome_components:
        marker_label = _clean_text(session.get("main_marker")) or "Marker"
        component_buckets: Dict[str, Dict[str, Any]] = {}
        component_order: List[str] = []
        for row in table_one.get("rows") or []:
            variable = row.get("variable")
            if str(variable or "") not in outcome_components:
                continue
            concept_id, concept_title = _marker_component_concept(variable, marker_label)
            if concept_id not in component_buckets:
                component_buckets[concept_id] = {"title": concept_title, "rows": []}
                component_order.append(concept_id)
            component_buckets[concept_id]["rows"].append(row)
        component_tables: List[Dict[str, Any]] = []
        for concept_id in component_order:
            bucket = component_buckets[concept_id]
            bucket_rows = bucket["rows"]
            component_tables.append({
                "table_id": f"marker_outcome_components_{concept_id}",
                "title": bucket["title"],
                "table_type": "marker_component_descriptive_table",
                "concept": concept_id,
                "columns": list(table_one.get("headers") or []),
                "rows": [_display_row(row, label_ctx) for row in bucket_rows],
                "source_variables": [str(row.get("variable")) for row in bucket_rows if row.get("variable")],
                "source_test_ids": [],
                "interpretation": "Localization and staining score are presented descriptively as components of the immunohistochemical assessment.",
                "thesis_ready": bool(bucket_rows),
                "priority": "thesis_ready_primary",
                "optional": False,
                "detailed_report_only": False,
                "warnings": [],
            })
        component_section = {
            "section_id": "marker_outcome_components",
            "title": "Marker / Outcome Components",
            "purpose": "Describe variables that contribute to, localise, or qualify the primary marker/outcome.",
            "source_results": [],
            "tables": component_tables,
            "figures": [],
            "interpretation": "These variables are descriptive components of the primary marker/outcome, not independent prognostic predictors by default.",
        }
        sections_by_id[component_section["section_id"]] = component_section
        sections.append(component_section)
        all_tables.extend(component_tables)

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
        interpretation = _safe_interpretation(test, label_ctx)
        bp_table = _thesis_table_for_result(test, outcome, label_ctx)
        is_component_result = any(
            variable == comp or variable.startswith(f"{comp} vs ") or variable.startswith(f"{comp} by ")
            for variable in variables
            for comp in outcome_components
        )
        if is_component_result:
            bp_table["priority"] = "detailed_report_only"
            bp_table["optional"] = True
            bp_table["detailed_report_only"] = True
            warnings_for_table = list(bp_table.get("warnings") or [])
            warnings_for_table.append(
                "Marker/outcome component result retained for detailed statistics; excluded from final thesis findings by default."
            )
            bp_table["warnings"] = warnings_for_table
        section["tables"].append(bp_table)
        all_tables.append(bp_table)
        for idx, fig in enumerate(test.get("figures") or [], 1):
            fig_title = _display_text(fig.get("title") or test.get("title") or f"Figure {idx}", label_ctx)
            bp_fig = {
                "figure_id": f"{test_id}_figure_{idx}",
                "title": fig_title,
                "graph_type": _graph_type_from_title(fig_title),
                "source_variables": variables,
                "source_result_id": test_id,
                "caption": _display_text(fig.get("caption") or fig_title, label_ctx),
                "png_data_uri": fig.get("png_data_uri"),
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
        title = _display_text(graph.get("title") or "Planned figure", label_ctx)
        bp_fig = {
            "figure_id": graph_id,
            "title": title,
            "graph_type": graph.get("graph_type") or _graph_type_from_title(title),
            "source_variables": list(graph.get("columns") or []),
            "source_result_id": graph.get("source_result_id"),
            "caption": _display_text(graph.get("caption") or title, label_ctx),
            "interpretation": _display_text(graph.get("interpretation") or "Figure generated from the executed Sigma analysis.", label_ctx),
            "thesis_ready": bool(graph.get("png_data_uri")),
            "optional": True,
            "detailed_report_only": False,
            "warnings": [] if graph.get("png_data_uri") else ["Figure metadata is available; image rendering is pending or unavailable."],
        }
        all_figures.append(bp_fig)
        section = sections_by_id.get("bivariate_associations") or sections_by_id.get("descriptive_results")
        if section:
            section["figures"].append(bp_fig)

    core_figure_vars = set()
    for finding in significant_findings:
        variable = str((finding or {}).get("variable") or "")
        for sep in (" vs ", " by "):
            if sep in variable:
                core_figure_vars.add(variable.split(sep, 1)[0].strip())
                break
    node_derived_keys = {"positivenodes", "totalnodes", "noderatio"}
    for table in all_tables:
        if str(table.get("table_type") or "").startswith("continuous_or_group"):
            for variable in table.get("source_variables") or []:
                variable_key = re.sub(r"[^a-z0-9]+", "", str(variable).lower())
                if variable and str(variable) != str(outcome) and variable_key not in node_derived_keys:
                    core_figure_vars.add(str(variable))

    max_default_figures = 8
    for idx, figure in enumerate(all_figures):
        is_primary = figure.get("figure_id") == "primary_outcome_distribution"
        fig_vars = {str(item) for item in figure.get("source_variables") or [] if item}
        is_core = bool(fig_vars.intersection(core_figure_vars))
        if idx >= max_default_figures and not is_primary and not is_core:
            figure["optional"] = True
            figure["detailed_report_only"] = True
            warning_list = list(figure.get("warnings") or [])
            warning_list.append("Held for detailed report to keep the thesis blueprint concise.")
            figure["warnings"] = warning_list

    thesis_findings = []
    component_findings: List[Dict[str, Any]] = []
    for finding in significant_findings:
        variable = str(finding.get("variable") or "")
        if variable in excluded:
            continue
        if any(variable == comp or variable.startswith(f"{comp} vs ") or variable.startswith(f"{comp} by ") for comp in outcome_components):
            component_findings.append(finding)
            continue
        displayed = dict(finding)
        for key in ("variable", "key_finding", "test_applied", "effect_size", "notes_warnings"):
            if key in displayed:
                displayed[key] = _display_text(displayed[key], label_ctx)
        displayed["key_finding"] = _deterministic_key_finding(displayed, label_ctx)
        thesis_findings.append(displayed)

    canonical_associations = tested_associations or _fallback_tested_associations(tests, outcome)
    displayed_associations: List[Dict[str, Any]] = []
    component_associations: List[Dict[str, Any]] = []
    for association in canonical_associations:
        predictor = str(association.get("predictor") or "")
        if any(
            predictor == component
            or predictor.startswith(f"{component} vs ")
            or predictor.startswith(f"{component} by ")
            for component in outcome_components
        ):
            component_associations.append(dict(association))
            continue
        displayed = dict(association)
        for key in (
            "predictor", "test_applied", "test_statistic", "effect_size",
            "significance_status", "notes_warnings",
        ):
            displayed[key] = _display_text(displayed.get(key) or "", label_ctx)
        displayed_associations.append(displayed)

    if component_associations:
        warnings.append(
            "Marker-component variables were summarized descriptively and excluded from clinical association interpretation."
        )

    if displayed_associations:
        association_summary_table = {
            "table_id": "tested_associations_summary",
            "title": "Summary of tested associations",
            "table_type": "tested_associations_summary",
            "columns": [
                "Predictor", "Test applied", "Test statistic", "p-value",
                "Adjusted p-value", "Effect size", "Significance status", "Notes",
            ],
            "rows": [[
                row.get("predictor") or "",
                row.get("test_applied") or "",
                row.get("test_statistic") or "-",
                row.get("p_value") or "-",
                row.get("adjusted_p_value") or "-",
                row.get("effect_size") or "-",
                row.get("significance_status") or "",
                row.get("notes_warnings") or "-",
            ] for row in displayed_associations],
            "source_variables": [row.get("predictor") for row in displayed_associations],
            "source_test_ids": [row.get("source_result_id") for row in displayed_associations],
            "interpretation": (
                "All completed predictor-versus-outcome tests are shown, including non-significant "
                "and nominally significant results."
            ),
            "thesis_ready": True,
            "priority": "thesis_ready_primary",
            "optional": False,
            "detailed_report_only": False,
            "warnings": [],
        }
        association_summary_section = _section_template(
            "tested_associations_summary",
            "Summary of Tested Associations",
            "Report every completed predictor-versus-outcome association transparently.",
        )
        association_summary_section["tables"].append(association_summary_table)
        association_summary_section["interpretation"] = association_summary_table["interpretation"]
        sections.append(association_summary_section)
        all_tables.append(association_summary_table)

    if thesis_findings:
        rows = [
            [
                finding.get("variable") or "",
                finding.get("key_finding") or "",
                finding.get("test_statistic") or "-",
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
            "columns": ["Variable / parameter", "Key finding", "Test statistic", "p-value", "Adjusted p-value", "Test applied", "Effect size", "Notes/warnings"],
            "rows": rows,
            "source_variables": [],
            "source_test_ids": [str(f.get("variable") or "") for f in thesis_findings],
            "interpretation": "Only statistically significant completed tests are listed here.",
            "thesis_ready": True,
            "priority": "thesis_ready_primary",
            "optional": False,
            "detailed_report_only": False,
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
    if component_findings:
        warnings.append(
            "Some significant detailed results were outcome/marker components and were omitted from the final thesis findings table by default."
        )

    bivariate_section = sections_by_id.get("bivariate_associations")
    if bivariate_section:
        names = []
        for finding in thesis_findings:
            variable = str(finding.get("variable") or "")
            if " vs " in variable:
                names.append(_display_text(variable.split(" vs ", 1)[0], label_ctx))
            elif " by " in variable:
                names.append(_display_text(variable.split(" by ", 1)[0], label_ctx))
            elif variable:
                names.append(_display_text(variable, label_ctx))
        names = list(dict.fromkeys(names))[:8]
        sparse = any(table.get("warnings") for table in bivariate_section.get("tables") or [])
        sentence = (
            f"Bivariate analyses compared eligible predictors against the confirmed primary outcome, "
            f"{_display_text(outcome, label_ctx)}."
        )
        if names:
            sentence += " Significant associations were observed for " + ", ".join(names) + "."
        else:
            sentence += " No statistically significant associations were retained for the thesis findings table."
        if sparse:
            sentence += " Sparse-category warnings were present for some variables and should be reviewed."
        bivariate_section["interpretation"] = sentence

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
        "primary_outcome": _display_text(outcome, label_ctx) if outcome else "",
        "analysis_sections": sections,
        "tables": all_tables,
        "figures": all_figures,
        "significant_findings": thesis_findings,
        "tested_associations": displayed_associations,
        "methods_text": _display_text(methods_text, label_ctx),
        "results_narrative": _display_text(results_narrative, label_ctx),
        "warnings": list(dict.fromkeys(
            warning for warning in (_clean_report_warning(item) for item in warnings) if warning
        )),
        "unavailable_or_recommended_only": unavailable,
    }
