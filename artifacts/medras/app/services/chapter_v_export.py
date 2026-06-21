"""Render thesis Chapter V from Sigma's thesis_analysis_blueprint.

This module deliberately consumes the blueprint contract instead of the raw
statistical result text.  Detailed statistical subtables remain available to
other exports, but the main thesis chapter stays doctor-readable.
"""

from __future__ import annotations

import base64
import html
import io
import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Set, Tuple

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


FORBIDDEN_MAIN_TABLE_TITLES = {
    "observed counts",
    "expected counts",
    "row percentages",
    "column percentages",
    "test summary",
}


_BINARY_MARKER_VARS = {"er", "pr", "ar", "her2", "her2neu", "egfr"}
_PRESENCE_MARKER_VARS = {"lvi", "ene", "necrosis", "dcis"}


def _clean_variable_label(value: Any) -> str:
    text = _text(value)
    replacements = {
        "Her2Neu": "HER2",
        "HER2neu": "HER2",
        "Her2neu": "HER2",
        "Ki67": "Ki-67",
        "pT": "Pathological T stage",
        "pt": "Pathological T stage",
    }
    for raw, clean in replacements.items():
        text = re.sub(rf"\b{re.escape(raw)}\b", clean, text)
    text = re.sub(r"\bTumou?r site(?:/quadrant)?\b", "Tumour quadrant", text, flags=re.IGNORECASE)
    return text


def _variable_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _text(value).lower())


def _clinical_category_label(variable: Any, category: Any, label_ctx: Optional[Dict[str, Any]] = None) -> str:
    var_key = _variable_key(variable)
    text = _display_value(category, label_ctx) if label_ctx else _text(category)
    low = text.strip().lower()
    low_compact = re.sub(r"\s+", "", low)
    if "histologicaltype" in var_key or var_key in {"grade", "histologicalgrade"}:
        match = re.search(r"(?:type|grade)?\s*([123])(?:\.0)?\b", low, flags=re.IGNORECASE)
        if match:
            return f"Grade {match.group(1)}"
    if "ki67" in var_key or "ki67" in _text(variable).lower() or "ki-67" in _text(variable).lower():
        if low_compact in {">=14", ">=14%", "=>14", "=>14%"}:
            return ">=14%"
        if low_compact in {"<14", "<14%", "<=14", "<=14%"}:
            return "<14%"
    if "molecular" in var_key and "subtype" in var_key:
        if low_compact in {"her2neu", "her2", "her2enriched", "her2-enriched"}:
            return "HER2-enriched"
    if "nodal" in var_key and low_compact in {"no", "n0"}:
        return "N0"
    if "her2" in var_key:
        if low_compact in {"negative", "neg", "no", "0", "1", "1+", "low"}:
            return "Negative/low"
        if low_compact in {"2", "2+", "equivocal"}:
            return "Equivocal (2+)"
        if low_compact in {"3", "3+", "positive", "postive", "yes", "present"}:
            return "Positive (3+)"
    if "egfr" in var_key:
        if low in {"positive", "postive", "yes", "present", "patchy positive"}:
            return "Positive"
        if low in {"negative", "no", "absent"}:
            return "Negative"
    if var_key == "dcis":
        if low in {"positive", "postive", "yes", "present", "high grade", "low grade", "intermediate grade"}:
            return "Present"
        if low in {"negative", "no", "absent"}:
            return "Absent"
    if var_key in _PRESENCE_MARKER_VARS:
        if low in {"positive", "postive", "yes", "present"}:
            return "Present"
        if low in {"negative", "no", "absent", "abse"}:
            return "Absent"
    if var_key in _BINARY_MARKER_VARS or any(marker in var_key for marker in _BINARY_MARKER_VARS):
        if low in {"positive", "postive", "yes", "present"}:
            return "Positive"
        if low in {"negative", "no", "absent"}:
            return "Negative"
    return _clean_variable_label(text)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, (list, tuple)):
        return "; ".join(_text(item) for item in value if _text(item))
    if isinstance(value, dict):
        return "; ".join(f"{_label(k)}: {_text(v)}" for k, v in value.items() if _text(v))
    text = html.unescape(str(value)).strip()
    replacements = {
        "Â±": "±",
        "ą": "±",
        "â‰¤": "≤",
        "â‰¥": "≥",
        "â€”": "—",
        "â€“": "–",
        "â€¢": "•",
        "Cramer's V": "Cramér's V",
        "Cramer’s V": "Cramér's V",
    }
    for raw, clean in replacements.items():
        text = text.replace(raw, clean)
    text = text.replace("Postive", "Positive")
    text = re.sub(r">=\s*14%?", ">=14%", text)
    return text


def _label(value: Any) -> str:
    text = _text(value).replace("_", " ").strip()
    if not text:
        return ""
    acronyms = {"id": "ID", "roc": "ROC", "auc": "AUC", "pdf": "PDF", "docx": "DOCX"}
    words = [acronyms.get(part.lower(), part.capitalize()) for part in text.split()]
    return " ".join(words)


def _readable_study_design(value: Any) -> str:
    text = _text(value).replace("_", " ").strip().lower()
    mapping = {
        "cross sectional association": "Cross-sectional association study",
        "cohort prognostic association": "Cohort/prognostic association study",
        "two group comparison": "Two-group comparison study",
        "descriptive prevalence": "Descriptive/prevalence study",
        "diagnostic accuracy": "Diagnostic accuracy study",
        "reliability agreement": "Reliability/agreement study",
        "regression prediction": "Regression/prediction study",
        "repeated measures": "Repeated-measures study",
        "survival": "Survival/time-to-event study",
        "correlation": "Correlation study",
    }
    return mapping.get(text, _label(text))


def _outcome_label_context(blueprint: Dict[str, Any]) -> Dict[str, Any]:
    display = _text(blueprint.get("primary_outcome"))
    raw_values = set()
    core_figure_variables = set()
    outcome_values = {"yes", "no", "positive", "negative"}
    for finding in blueprint.get("significant_findings") or []:
        variable = _text(finding.get("variable") if isinstance(finding, dict) else "")
        for sep in (" vs ", " by "):
            if sep in variable:
                core_figure_variables.add(variable.split(sep, 1)[0].strip())
                break
    for section in blueprint.get("analysis_sections") or []:
        for table in section.get("tables") or []:
            if str(table.get("table_type") or "").startswith("continuous_or_group"):
                for variable in _source_variables(table):
                    if variable and variable != display and variable.lower() not in outcome_values:
                        core_figure_variables.add(variable)
        if not isinstance(section, dict) or section.get("section_id") != "primary_outcome_distribution":
            continue
        for figure in section.get("figures") or []:
            for variable in figure.get("source_variables") or []:
                if _text(variable) and _text(variable) != display:
                    raw_values.add(_text(variable))
        for table in section.get("tables") or []:
            for variable in table.get("source_variables") or []:
                if _text(variable) and _text(variable) != display:
                    raw_values.add(_text(variable))
    return {
        "display": display,
        "raw_values": sorted(raw_values, key=len, reverse=True),
        "core_figure_variables": sorted(core_figure_variables),
        "status_like": any(token in display.lower() for token in ("expression", "status", "marker", "positive", "negative")),
    }


def _display_value(value: Any, label_ctx: Optional[Dict[str, Any]]) -> str:
    text = _text(value)
    if not label_ctx:
        return _clean_variable_label(text)
    display = _text(label_ctx.get("display"))
    if not display:
        return _clean_variable_label(text)
    for raw in label_ctx.get("raw_values") or []:
        text = text.replace(raw, display)
    if label_ctx.get("status_like"):
        text = re.sub(r"\bYes\b", "Positive", text)
        text = re.sub(r"\bNo\b", "Negative", text)
    return _clean_variable_label(text)


def _clean_finding_text(value: Any) -> str:
    text = _text(value)
    text = text.replace("Chi-square test: Chi-square test", "Chi-square test")
    for token in ("; p =", "; adjusted p", "; Cram", "; Cohen", " p =", " adjusted p"):
        if token in text:
            text = text.split(token, 1)[0].strip()
    return text


def _is_main_table(table: Dict[str, Any]) -> bool:
    if not isinstance(table, dict):
        return False
    if table.get("detailed_report_only"):
        return False
    if table.get("thesis_ready") is False:
        return False
    if str(table.get("priority") or "").lower() == "detailed_report_only":
        return False
    placement = str(table.get("placement") or "main_thesis").lower()
    if placement and placement not in {"main_thesis", "thesis_preview", "chapter_v"}:
        return False
    title = _text(table.get("title")).lower()
    return title not in FORBIDDEN_MAIN_TABLE_TITLES


def _is_main_figure(figure: Dict[str, Any], include_optional: bool = False) -> bool:
    if not isinstance(figure, dict):
        return False
    if not figure.get("png_data_uri"):
        return False
    if figure.get("detailed_report_only"):
        return False
    if str(figure.get("priority") or "").lower() == "detailed_report_only":
        return False
    return bool(figure.get("thesis_ready") or str(figure.get("priority") or "").lower() == "thesis_ready_primary")


def _is_core_figure(figure: Dict[str, Any], label_ctx: Dict[str, Any], section_id: str = "") -> bool:
    if section_id == "primary_outcome_distribution":
        return True
    core = {str(item) for item in label_ctx.get("core_figure_variables") or []}
    if not core:
        return False
    fig_vars = {str(item) for item in figure.get("source_variables") or [] if item}
    title = _text(figure.get("title") or figure.get("caption"))
    display = _text(label_ctx.get("display"))
    non_outcome_vars = {var for var in fig_vars if var and var != display and var not in set(label_ctx.get("raw_values") or [])}
    return bool(non_outcome_vars.intersection(core) or any(variable and variable in title for variable in core))


def _association_figure_sort_key(figure: Dict[str, Any], label_ctx: Dict[str, Any]) -> Tuple[int, str]:
    title = _text(figure.get("title") or figure.get("caption")).lower()
    variables = " ".join(_text(item) for item in figure.get("source_variables") or []).lower()
    haystack = f"{title} {variables}"
    order = [
        ("age", 0),
        ("histological", 1),
        ("grade", 1),
        ("er", 2),
        ("pr", 3),
        ("molecular", 4),
        ("ar", 5),
    ]
    for token, rank in order:
        if re.search(rf"(^|[^a-z0-9]){re.escape(token)}([^a-z0-9]|$)", haystack):
            return rank, title
    core = {str(item).lower() for item in label_ctx.get("core_figure_variables") or []}
    if any(item and item in haystack for item in core):
        return 20, title
    return 100, title


def _normalise_figure_metadata(figure: Dict[str, Any], label_ctx: Dict[str, Any]) -> Dict[str, Any]:
    clone = deepcopy(figure)
    display = _text(label_ctx.get("display"))
    source_vars = [_display_value(item, label_ctx) for item in clone.get("source_variables") or []]
    predictor = next((item for item in source_vars if item and item != display), "")
    for key in ("title", "caption", "interpretation"):
        if clone.get(key):
            clone[key] = _display_value(clone[key], label_ctx)
    if display and predictor and (" by " in _text(clone.get("title")).lower() or " vs " in _text(clone.get("title")).lower()):
        clone["title"] = f"{display} by {predictor}"
        clone["caption"] = f"{display} by {predictor}."
    return clone


def _section_tables(section: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [table for table in section.get("tables") or [] if _is_main_table(table)]


def _section_figures(section: Dict[str, Any], include_optional: bool = False) -> List[Dict[str, Any]]:
    return [figure for figure in section.get("figures") or [] if _is_main_figure(figure, include_optional)]


def _expand_export_tables(tables: List[Dict[str, Any]], label_ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    expanded: List[Dict[str, Any]] = []
    for table in tables:
        payload = _descriptive_export_table(table, label_ctx)
        if isinstance(payload, list):
            expanded.extend(payload)
        else:
            expanded.append(payload)
    return expanded


BASELINE_TERMS = ("age", "sex", "gender", "laterality", "side", "group", "cohort")

DESCRIPTIVE_TABLE_TYPES = {
    "descriptive_table",
    "domain_profile_descriptive_table",
    "marker_component_descriptive_table",
    "primary_outcome_distribution_table",
}


def _row_variable(row: Any) -> str:
    if isinstance(row, dict):
        return _text(row.get("variable"))
    if isinstance(row, (list, tuple)) and row:
        return _text(row[0])
    return ""


def _source_variables(table: Dict[str, Any]) -> List[str]:
    variables = [_text(var) for var in table.get("source_variables") or [] if _text(var)]
    if variables:
        return variables
    return [_row_variable(row) for row in table.get("rows") or [] if _row_variable(row)]


def _clean_table_title(title: Any) -> str:
    text = _text(title)
    return re.sub(r"^Table\s+\d+[A-Z]?\.\s*", "", text, flags=re.IGNORECASE).strip()


def _clean_interpretation(value: Any, label_ctx: Optional[Dict[str, Any]] = None) -> str:
    text = _display_value(value, label_ctx) if label_ctx else _text(value)
    blocked = (
        "Domain-profile grouping is descriptive",
        "statistical tests remain generated from variable roles",
        "Use this figure to inspect outcome balance",
    )
    if any(item in text for item in blocked):
        return ""
    text = text.replace(
        "Marker or outcome-component variables are described here and omitted from final prognostic findings by default.",
        "Localization and staining score are presented descriptively as components of the immunohistochemical assessment.",
    )
    text = text.replace("Chi-square test with sparse-cell warning was", "was")
    text = text.replace("Chi-square test: Chi-square test", "Chi-square test")
    text = re.sub(
        r"^(.+?)\s+vs\s+(.+?):\s+was significantly associated with the outcome\.?$",
        r"\1 showed a statistically significant association with \2.",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(.+?)\s+vs\s+(.+?):\s+was not significantly associated with the outcome\.?$",
        r"\1 did not show a statistically significant association with \2.",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(.+?)\s+vs\s+(.+?)\s+was significantly associated with the outcome\.?$",
        r"\1 showed a statistically significant association with \2.",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(.+?)\s+vs\s+(.+?)\s+was not significantly associated with the outcome\.?$",
        r"\1 did not show a statistically significant association with \2.",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(.+?)\s+by\s+(.+?):\s+Welch's t-test was not significantly associated with the outcome\.?$",
        r"\1 was not significantly associated with \2.",
        text,
        flags=re.IGNORECASE,
    )
    text = text.replace(
        "Sparse categories were detected; interpret with caution.",
        "This finding should be interpreted cautiously because some expected cell counts were below 5.",
    )
    text = re.sub(
        r"This finding should be interpreted cautiously because some\.?",
        "This finding should be interpreted cautiously because some expected cell counts were below 5.",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s*Interpret with caution:\s*-\s*", " ", text, flags=re.IGNORECASE)
    text = re.sub(
        r"Chi-square test with sparse-cell Chi-square used:\s*some\.?",
        "This finding should be interpreted cautiously because some expected cell counts were below 5.",
        text,
        flags=re.IGNORECASE,
    )
    if re.search(r"(sparse|expected cell counts|expected counts below)", text, flags=re.IGNORECASE):
        text = re.sub(r"\s*Interpret with caution[:.]?\s*", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*Warning[:.]?\s*", " ", text, flags=re.IGNORECASE)
        text = re.sub(
            r"\b(?:minimum|min)\s+expected(?:\s+cell)?\s+count(?:\s+was|\s*=|\s*:)?\s*[0-9.]+\.?",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\bexpected(?:\s+cell)?\s+counts?\s+(?:were\s+)?(?:below|<)\s*5[^.]*\.",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"(?:This finding should be interpreted cautiously because some expected cell counts were below 5\.\s*)+",
            "This finding should be interpreted cautiously because some expected cell counts were below 5. ",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"(?:This finding should be interpreted cautiously because some expected cell counts were below 5\.\s*)",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        if "This finding should be interpreted cautiously because some expected cell counts were below 5." not in text:
            text = text.rstrip(". ") + ". This finding should be interpreted cautiously because some expected cell counts were below 5."
    text = re.sub(r"^(.+?):\s+was ", r"\1 was ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_category_summary(summary: Any, label_ctx: Optional[Dict[str, Any]] = None) -> List[Tuple[str, str, str]]:
    text = _display_value(summary, label_ctx) if label_ctx else _text(summary)
    rows: List[Tuple[str, str, str]] = []
    for label, count, pct in re.findall(r"([^:;]+):\s*([0-9]+(?:\.[0-9]+)?)\s*\(([0-9]+(?:\.[0-9]+)?)%\)", text):
        rows.append((_text(label).strip(), str(int(float(count))) if float(count).is_integer() else count, f"{pct}%"))
    return rows


def _parse_continuous_summary(summary: Any, label_ctx: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, str]]:
    text = _display_value(summary, label_ctx) if label_ctx else _text(summary)
    mean_sd = re.search(r"([0-9.+-]+)\s*(?:±|Â±|ą|\+/-)\s*([0-9.+-]+)", text)
    n_match = re.search(r"\(n\s*=\s*([0-9]+)\)", text, flags=re.IGNORECASE)
    missing = re.search(r"Missing:\s*([0-9]+)\s*\(([0-9.]+)%\)", text, flags=re.IGNORECASE)
    median = re.search(r"Median(?:\s*[:=])?\s*([0-9.+-]+)", text, flags=re.IGNORECASE)
    minimum = re.search(r"(?:Minimum|Min)(?:\s*[:=])?\s*([0-9.+-]+)", text, flags=re.IGNORECASE)
    maximum = re.search(r"(?:Maximum|Max)(?:\s*[:=])?\s*([0-9.+-]+)", text, flags=re.IGNORECASE)
    if not (mean_sd or n_match or median or minimum or maximum):
        return None
    mean_sd_text = f"{mean_sd.group(1)} ± {mean_sd.group(2)}" if mean_sd else "-"
    missing_text = f"{missing.group(1)} ({missing.group(2)}%)" if missing else "-"
    return {
        "n": n_match.group(1) if n_match else "-",
        "mean_sd": mean_sd_text,
        "median": median.group(1) if median else "-",
        "min": minimum.group(1) if minimum else "-",
        "max": maximum.group(1) if maximum else "-",
        "missing": missing_text,
    }


def _descriptive_export_table(table: Dict[str, Any], label_ctx: Dict[str, Any]) -> Any:
    if str(table.get("table_type") or "") not in DESCRIPTIVE_TABLE_TYPES:
        return table
    categorical_counts: Dict[Tuple[str, str], float] = {}
    categorical_order: List[Tuple[str, str]] = []
    continuous_rows: List[List[str]] = []
    for row in table.get("rows") or []:
        variable = _row_variable(row)
        if not variable:
            continue
        variable = _display_value(variable, label_ctx)
        cells = row.get("cells") if isinstance(row, dict) else None
        kind = _text(row.get("type") if isinstance(row, dict) else "")
        summary = cells[0] if isinstance(cells, list) and cells else ""
        continuous = _parse_continuous_summary(summary, label_ctx)
        if continuous and ("mean" in kind.lower() or "sd" in kind.lower() or not _parse_category_summary(summary, label_ctx)):
            continuous_rows.append([
                variable,
                continuous["n"],
                continuous["mean_sd"],
                continuous["median"],
                continuous["min"],
                continuous["max"],
                continuous["missing"],
            ])
            continue
        categories = _parse_category_summary(summary, label_ctx)
        if categories:
            for category, count, pct in categories:
                key = (variable, _clinical_category_label(variable, category, label_ctx))
                if key not in categorical_counts:
                    categorical_order.append(key)
                    categorical_counts[key] = 0.0
                categorical_counts[key] += float(count)
        elif summary:
            continuous_rows.append([variable, "-", _display_value(summary, label_ctx), "-", "-", "-", "-"])
    if not categorical_counts and not continuous_rows:
        return table
    polish = table.get("_polish_interpretation")
    clone = deepcopy(table)
    if continuous_rows and categorical_counts:
        continuous = deepcopy(table)
        continuous["columns"] = ["Parameter", "n", "Mean ± SD", "Median", "Minimum", "Maximum", "Missing n (%)"]
        continuous["rows"] = continuous_rows
        continuous["title"] = _clean_table_title(continuous.get("title") or "Continuous descriptive findings")
        continuous["interpretation"] = polish or _descriptive_table_interpretation(continuous)
        categorical = deepcopy(table)
        totals: Dict[str, float] = {}
        for variable, _category in categorical_order:
            totals[variable] = totals.get(variable, 0.0) + categorical_counts[(variable, _category)]
        rows = []
        for variable, category in categorical_order:
            count = categorical_counts[(variable, category)]
            total = totals.get(variable, 0.0)
            pct = (count / total * 100.0) if total else 0.0
            count_text = str(int(count)) if float(count).is_integer() else f"{count:g}"
            rows.append([variable, category, count_text, f"{pct:.1f}%"])
        categorical["columns"] = ["Parameter", "Category", "n", "%"]
        categorical["rows"] = rows
        categorical["title"] = _clean_table_title(categorical.get("title") or "Categorical descriptive findings")
        categorical["interpretation"] = polish or _descriptive_table_interpretation(categorical)
        for item in (continuous, categorical):
            item.pop("headers", None)
        return [continuous, categorical]
    if continuous_rows and not categorical_counts:
        clone["columns"] = ["Parameter", "n", "Mean ± SD", "Median", "Minimum", "Maximum", "Missing n (%)"]
        clone["rows"] = continuous_rows
    else:
        totals: Dict[str, float] = {}
        for variable, _category in categorical_order:
            totals[variable] = totals.get(variable, 0.0) + categorical_counts[(variable, _category)]
        rows = []
        for variable, category in categorical_order:
            count = categorical_counts[(variable, category)]
            total = totals.get(variable, 0.0)
            pct = (count / total * 100.0) if total else 0.0
            count_text = str(int(count)) if float(count).is_integer() else f"{count:g}"
            rows.append([variable, category, count_text, f"{pct:.1f}%"])
        clone["columns"] = ["Parameter", "Category", "n", "%"]
        clone["rows"] = rows
    clone.pop("headers", None)
    clone["title"] = _clean_table_title(clone.get("title") or "Descriptive findings")
    clone["interpretation"] = polish or _descriptive_table_interpretation(clone)
    return clone


def _descriptive_table_interpretation(table: Dict[str, Any]) -> str:
    rows = table.get("rows") or []
    if not rows:
        return ""
    first_param = _text(rows[0][0]) if isinstance(rows[0], list) and rows[0] else ""
    best: Optional[List[str]] = None
    for row in rows:
        if not isinstance(row, list) or len(row) < 4:
            continue
        try:
            current = float(str(row[2]).replace(",", ""))
        except ValueError:
            continue
        if best is None:
            best = row
            continue
        try:
            previous = float(str(best[2]).replace(",", ""))
        except ValueError:
            previous = -1.0
        if current > previous:
            best = row
    if best and len(best) >= 4 and best[1]:
        return f"The most frequent category for {best[0]} was {best[1]} ({best[2]}, {best[3]})."
    if first_param:
        return f"This table summarises {first_param} in the analysed sample."
    return "This table summarises the analysed sample."


def _filter_table_variables(table: Dict[str, Any], allowed: Set[str], seen: Set[str]) -> Optional[Dict[str, Any]]:
    clone = deepcopy(table)
    rows = []
    for row in clone.get("rows") or []:
        variable = _row_variable(row)
        if variable and variable in seen:
            continue
        if allowed and variable and variable not in allowed:
            continue
        rows.append(row)
        if variable:
            seen.add(variable)
    if not rows:
        return None
    clone["rows"] = rows
    clone["source_variables"] = [var for var in _source_variables(clone) if not allowed or var in allowed]
    return clone


def _dedupe_descriptive_sections(sections: List[Dict[str, Any]], label_ctx: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    domain_ids = {
        "clinical_study_characteristics",
        "immunophenotype_characteristics",
        "marker_outcome_components",
    }
    has_domain_sections = any(section.get("section_id") in domain_ids for section in sections)
    marker_vars: Set[str] = set()
    outcome_vars: Set[str] = set(label_ctx.get("raw_values") or []) if label_ctx else set()
    if label_ctx and _text(label_ctx.get("display")):
        outcome_vars.add(_text(label_ctx.get("display")))
    for section in sections:
        if section.get("section_id") != "marker_outcome_components":
            continue
        for table in section.get("tables") or []:
            marker_vars.update(_source_variables(table))
    seen: Set[str] = set()
    out: List[Dict[str, Any]] = []
    for section in sections:
        section_id = section.get("section_id")
        clone = deepcopy(section)
        allowed: Set[str] = set()
        if section_id == "baseline_characteristics" and has_domain_sections:
            for table in clone.get("tables") or []:
                for var in _source_variables(table):
                    if any(term in var.lower() for term in BASELINE_TERMS):
                        allowed.add(var)
        new_tables = []
        for table in clone.get("tables") or []:
            if section_id != "marker_outcome_components" and marker_vars:
                clone_table = deepcopy(table)
                clone_table["rows"] = [
                    row for row in clone_table.get("rows") or []
                    if _row_variable(row) not in marker_vars
                ]
                table = clone_table
            if section_id != "marker_outcome_components" and outcome_vars:
                clone_table = deepcopy(table)
                clone_table["rows"] = [
                    row for row in clone_table.get("rows") or []
                    if _row_variable(row) not in outcome_vars
                ]
                table = clone_table
            filtered = _filter_table_variables(table, allowed, seen)
            if filtered:
                new_tables.append(filtered)
        clone["tables"] = new_tables
        if new_tables or clone.get("figures") or _text(clone.get("interpretation")):
            out.append(clone)
    return out


def _primary_outcome_tables(blueprint: Dict[str, Any], label_ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    display = _text(label_ctx.get("display"))
    raw_values = set(label_ctx.get("raw_values") or [])
    candidates = raw_values | ({display} if display else set())
    if not candidates:
        return []
    for section in blueprint.get("analysis_sections") or []:
        for table in section.get("tables") or []:
            for row in table.get("rows") or []:
                variable = _row_variable(row)
                if variable not in candidates:
                    continue
                clone = deepcopy(table)
                clone["title"] = f"Primary outcome distribution: {display or variable}"
                clone["table_type"] = "primary_outcome_distribution_table"
                clone["rows"] = [row]
                clone["source_variables"] = [variable]
                clone["interpretation"] = f"This table reports the distribution of {display or variable}."
                clone["warnings"] = []
                return [clone]
    return []


def _parse_distribution_counts(table: Dict[str, Any], label_ctx: Dict[str, Any]) -> Tuple[List[str], List[float]]:
    labels: List[str] = []
    counts: List[float] = []
    _, rows = _table_rows(table)
    for row in rows:
        # Prefer columns after index 1 (skip variable name + type/summary label).
        # If that slice is empty or blank, fall back to scanning all cells so
        # tables using a "Summary" column (index 1) are also parsed correctly.
        cells_to_scan = row[2:] if len(row) > 2 else row
        if not any(_text(cell) for cell in cells_to_scan):
            cells_to_scan = row[1:] if len(row) > 1 else row
        for cell in cells_to_scan:
            text = _display_value(cell, label_ctx)
            for label, count in re.findall(r"([^:;]+):\s*([0-9]+(?:\.[0-9]+)?)", text):
                clean_label = _display_value(label.strip(), label_ctx)
                if clean_label and clean_label not in labels:
                    labels.append(clean_label)
                    counts.append(float(count))
    return labels, counts


def _bar_chart_data_uri(labels: List[str], counts: List[float], title: str) -> str:
    if not labels or not counts:
        return ""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return ""
    fig, ax = plt.subplots(figsize=(5.5, 3.4), dpi=160)
    colours = ["#4B78A8", "#F58518", "#54A24B", "#B279A2", "#E45756"]
    bars = ax.bar(labels, counts, color=colours[:len(labels)], edgecolor="white")
    ax.set_title(title)
    ax.set_ylabel("n")
    ax.spines[["top", "right"]].set_visible(False)
    for bar, value in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(counts) * 0.02, f"{value:g}", ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    out = io.BytesIO()
    fig.savefig(out, format="png", bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def _primary_outcome_figure(blueprint: Dict[str, Any], table: Dict[str, Any], label_ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    labels, counts = _parse_distribution_counts(table, label_ctx)
    display = _text(label_ctx.get("display") or blueprint.get("primary_outcome") or "primary outcome")
    png = _bar_chart_data_uri(labels, counts, f"Distribution of {display}")
    if not png:
        return None
    return {
        "figure_id": "primary_outcome_distribution_generated",
        "title": f"Distribution of {display}",
        "caption": f"Distribution of {display}.",
        "interpretation": f"The figure shows the distribution of {display} across the analysed sample.",
        "source_variables": [display],
        "png_data_uri": png,
        "thesis_ready": True,
        "detailed_report_only": False,
    }


def _compact_table_for_export(table: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    clone = deepcopy(table)
    headers = [_text(header) for header in (clone.get("columns") or clone.get("headers") or [])]
    warnings: List[str] = list(clone.get("warnings") or [])
    warning_indexes = [
        idx for idx, header in enumerate(headers)
        if header.strip().lower() in {"warning", "warnings", "notes/warnings"}
    ]
    if len(headers) > 7 and warning_indexes:
        remove = set(warning_indexes)
        clone["columns"] = [header for idx, header in enumerate(headers) if idx not in remove]
        new_rows = []
        for row in clone.get("rows") or []:
            if isinstance(row, dict):
                row_warning = row.get("warnings") or row.get("warning") or row.get("notes_warnings")
                if row_warning and _text(row_warning) not in {"-", "None"}:
                    warnings.append(_text(row_warning))
                new_rows.append(row)
            elif isinstance(row, (list, tuple)):
                values = list(row)
                for idx in warning_indexes:
                    if idx < len(values) and _text(values[idx]) not in {"", "-", "None"}:
                        warnings.append(_text(values[idx]))
                new_rows.append([cell for idx, cell in enumerate(values) if idx not in remove])
            else:
                new_rows.append(row)
        clone["rows"] = new_rows
    return clone, list(dict.fromkeys(warnings))


def _parse_count_cell(value: Any) -> Optional[float]:
    text = _text(value)
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _format_count_pct(count: float, total: float) -> str:
    count_text = str(int(count)) if float(count).is_integer() else f"{count:g}"
    pct = (count / total * 100.0) if total else 0.0
    return f"{count_text} ({pct:.1f}%)"


def _association_table_for_export(table: Dict[str, Any], label_ctx: Dict[str, Any]) -> Dict[str, Any]:
    table_type = str(table.get("table_type") or "").lower()
    if "association" not in table_type:
        return table
    headers, rows = _table_rows(table)
    if not rows or not headers:
        return table
    first_header = headers[0].strip().lower()
    if first_header not in {"predictor category", "category", "group"}:
        return table

    source_vars = _source_variables(table)
    display = _text(label_ctx.get("display"))
    predictor = next((var for var in source_vars if var and var != display and var not in set(label_ctx.get("raw_values") or [])), "")
    if not predictor:
        title = _text(table.get("title"))
        match = re.search(r"with\s+(.+)$", title, flags=re.IGNORECASE)
        predictor = match.group(1).strip() if match else ""

    count_indexes = [
        idx for idx, header in enumerate(headers)
        if idx > 0 and ("n (%)" in header.lower() or "count" in header.lower())
    ]
    if not count_indexes:
        return table

    grouped: Dict[str, List[Any]] = {}
    order: List[str] = []
    for row in rows:
        if not row:
            continue
        category = _clinical_category_label(predictor, row[0], label_ctx)
        if category not in grouped:
            order.append(category)
            grouped[category] = list(row)
            grouped[category][0] = category
            for idx in count_indexes:
                grouped[category][idx] = 0.0
        for idx in count_indexes:
            grouped[category][idx] = float(grouped[category][idx] or 0.0) + float(_parse_count_cell(row[idx]) or 0.0)

    if len(order) == len(rows) and all(_text(row[0]) == order[idx] for idx, row in enumerate(rows)):
        clone = deepcopy(table)
        clone["columns"] = [_display_value(header, label_ctx) for header in headers]
        clean_rows = []
        for row in rows:
            clean_row = [_display_value(cell, label_ctx) for cell in row]
            if clean_row:
                clean_row[0] = _clinical_category_label(predictor, row[0], label_ctx)
            clean_rows.append(clean_row)
        clone["rows"] = clean_rows
        return clone

    out_rows: List[List[str]] = []
    for category in order:
        row = grouped[category]
        total = sum(float(row[idx] or 0.0) for idx in count_indexes)
        normalized = [_display_value(cell, label_ctx) for cell in row]
        normalized[0] = category
        for idx in count_indexes:
            normalized[idx] = _format_count_pct(float(row[idx] or 0.0), total)
        out_rows.append(normalized)

    clone = deepcopy(table)
    clone["columns"] = [_display_value(header, label_ctx) for header in headers]
    clone["rows"] = out_rows
    return clone


def _normalise_table_for_export(table: Dict[str, Any], label_ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = label_ctx or {}
    payload = _association_table_for_export(table, ctx)
    if payload is table:
        payload = deepcopy(table)
        headers, rows = _table_rows(payload)
        payload["columns"] = [_display_value(header, ctx) for header in headers]
        payload["rows"] = [[_display_value(cell, ctx) for cell in row] for row in rows]
    return payload


def _table_rows(table: Dict[str, Any]) -> tuple[List[str], List[List[str]]]:
    headers = [_text(header) for header in (table.get("columns") or table.get("headers") or [])]
    rows: List[List[str]] = []
    for row in table.get("rows") or []:
        if isinstance(row, dict):
            if headers and isinstance(row.get("cells"), list):
                values: List[str] = []
                cell_values = [_text(cell) for cell in row.get("cells") or []]
                cell_idx = 0
                for header in headers:
                    normalized = header.strip().lower()
                    if normalized == "variable":
                        values.append(_text(row.get("variable")))
                    elif normalized == "type":
                        values.append(_text(row.get("type")))
                    elif normalized in {"p", "p-value", "p value"}:
                        values.append(_text(row.get("p") or row.get("p_value")))
                    else:
                        values.append(cell_values[cell_idx] if cell_idx < len(cell_values) else _text(row.get(header)))
                        cell_idx += 1
                rows.append(values)
            elif headers:
                rows.append([_text(row.get(header) or row.get(header.lower()) or row.get(header.replace(" ", "_").lower())) for header in headers])
            else:
                rows.extend([_text(k), _text(v)] for k, v in row.items())
        elif isinstance(row, (list, tuple)):
            rows.append([_text(cell) for cell in row])
        else:
            rows.append([_text(row)])
    if not headers and rows:
        headers = [f"Column {idx + 1}" for idx in range(max(len(row) for row in rows))]
    width = len(headers) or (max((len(row) for row in rows), default=1))
    normalized = [row + [""] * (width - len(row)) for row in rows]
    return headers or ["Value"], normalized


def _plain_docx_text(doc: Document, text: str, style: Optional[str] = None):
    para = doc.add_paragraph(style=style)
    para.add_run(_text(text))
    return para


def _set_docx_styles(doc: Document) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    for name in ("Heading 1", "Heading 2", "Heading 3"):
        style = doc.styles[name]
        style.font.name = "Times New Roman"
        style.font.bold = True


def _add_heading(doc: Document, text: str, level: int = 1) -> None:
    doc.add_heading(_text(text), level=level)


def _repeat_docx_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def _format_docx_table(table, font_size: int = 8) -> None:
    table.autofit = True
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(font_size)


def _add_table_docx(
    doc: Document,
    payload: Dict[str, Any],
    caption_no: int,
    label_ctx: Optional[Dict[str, Any]] = None,
    include_interpretation: bool = True,
) -> int:
    payload = _descriptive_export_table(payload, label_ctx or {})
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    payload = _normalise_table_for_export(payload, label_ctx or {})
    payload, warning_notes = _compact_table_for_export(payload)
    headers, rows = _table_rows(payload)
    if not rows:
        return caption_no
    caption = _display_value(_clean_table_title(payload.get("title") or f"Table {caption_no}"), label_ctx)
    _plain_docx_text(doc, f"Table {caption_no}. {caption}", style=None).runs[0].bold = True
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for idx, header in enumerate(headers):
        cell = table.rows[0].cells[idx]
        cell.text = _display_value(header, label_ctx)
        for run in cell.paragraphs[0].runs:
            run.bold = True
    _repeat_docx_header(table.rows[0])
    for row in rows:
        cells = table.add_row().cells
        for idx, value in enumerate(row[:len(headers)]):
            cells[idx].text = _display_value(value, label_ctx)
    _format_docx_table(table, font_size=8 if len(headers) > 5 else 9)
    for warning in warning_notes:
        _plain_docx_text(doc, f"Caution: {_display_value(warning, label_ctx)}")
    interpretation = _clean_interpretation(payload.get("interpretation"), label_ctx)
    if include_interpretation and interpretation:
        _plain_docx_text(doc, interpretation)
    doc.add_paragraph()
    return caption_no + 1


def _strip_data_uri(data_uri: str) -> bytes:
    if not data_uri:
        return b""
    if "," in data_uri:
        data_uri = data_uri.split(",", 1)[1]
    try:
        return base64.b64decode(data_uri)
    except Exception:
        return b""


def _add_figure_docx(doc: Document, figure: Dict[str, Any], figure_no: int, label_ctx: Optional[Dict[str, Any]] = None) -> int:
    title = _display_value(figure.get("title") or f"Figure {figure_no}", label_ctx)
    png = _strip_data_uri(_text(figure.get("png_data_uri")))
    if not png:
        return figure_no
    if png:
        try:
            doc.add_picture(io.BytesIO(png), width=Inches(5.7))
        except Exception:
            return figure_no
    caption = _display_value(figure.get("caption") or title, label_ctx)
    caption_para = doc.add_paragraph()
    caption_run = caption_para.add_run(f"Figure {figure_no}. {caption}")
    caption_run.italic = True
    interpretation = _clean_interpretation(figure.get("interpretation"), label_ctx)
    if interpretation:
        _plain_docx_text(doc, interpretation)
    doc.add_paragraph()
    return figure_no + 1


def _figure_matches_table(figure: Dict[str, Any], table: Dict[str, Any]) -> bool:
    table_ids = {str(item) for item in table.get("source_test_ids") or [] if item}
    fig_result = str(figure.get("source_result_id") or "")
    if table_ids and fig_result and fig_result in table_ids:
        return True
    table_vars = set(_source_variables(table))
    fig_vars = {str(item) for item in figure.get("source_variables") or [] if item}
    return bool(table_vars and fig_vars and table_vars.intersection(fig_vars))


def _render_section_docx(
    doc: Document,
    section: Dict[str, Any],
    table_no: int,
    figure_no: int,
    label_ctx: Dict[str, Any],
    include_optional_figures: bool = False,
) -> tuple[int, int]:
    section_id = str(section.get("section_id") or "")
    figures = [
        _normalise_figure_metadata(figure, label_ctx)
        for figure in _section_figures(section, include_optional_figures)
        if include_optional_figures or _is_core_figure(figure, label_ctx, section_id)
    ]
    used_figures: Set[str] = set()
    tables = _expand_export_tables(_section_tables(section), label_ctx)
    if section_id == "bivariate_associations":
        for figure in sorted(figures, key=lambda item: _association_figure_sort_key(item, label_ctx)):
            figure_id = _text(figure.get("figure_id") or figure.get("title"))
            if figure_id in used_figures:
                continue
            next_no = _add_figure_docx(doc, figure, figure_no, label_ctx)
            if next_no != figure_no:
                figure_no = next_no
                used_figures.add(figure_id)
    for table in tables:
        table_no = _add_table_docx(doc, table, table_no, label_ctx, include_interpretation=False)
        for figure in figures:
            figure_id = _text(figure.get("figure_id") or figure.get("title"))
            if figure_id in used_figures or not _figure_matches_table(figure, table):
                continue
            next_no = _add_figure_docx(doc, figure, figure_no, label_ctx)
            if next_no != figure_no:
                figure_no = next_no
                used_figures.add(figure_id)
        interpretation = _clean_interpretation(table.get("interpretation"), label_ctx)
        if interpretation:
            _plain_docx_text(doc, interpretation)
    if include_optional_figures:
        for figure in figures[:4]:
            figure_id = _text(figure.get("figure_id") or figure.get("title"))
            if figure_id in used_figures:
                continue
            next_no = _add_figure_docx(doc, figure, figure_no, label_ctx)
            if next_no != figure_no:
                figure_no = next_no
                used_figures.add(figure_id)
    return table_no, figure_no


def _blueprint(results: Dict[str, Any]) -> Dict[str, Any]:
    blueprint = results.get("thesis_analysis_blueprint")
    if not isinstance(blueprint, dict) or not blueprint:
        raise ValueError("Chapter V export requires thesis_analysis_blueprint. Run analysis again before exporting.")
    return blueprint


def _study_summary(blueprint: Dict[str, Any], results: Dict[str, Any]) -> List[tuple[str, str]]:
    summary = dict(blueprint.get("study_summary") or {})
    rows = [
        ("Study design", _readable_study_design(blueprint.get("study_design") or summary.get("study_design"))),
        ("Sample size", summary.get("sample_size") or summary.get("n") or ""),
        ("Primary outcome", blueprint.get("primary_outcome") or summary.get("primary_outcome") or ""),
    ]
    return [(label, _text(value)) for label, value in rows if _text(value)]


def _add_summary_docx(doc: Document, blueprint: Dict[str, Any], results: Dict[str, Any]) -> None:
    rows = _study_summary(blueprint, results)
    if not rows:
        _plain_docx_text(doc, "Study summary metadata was not available.")
        return
    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for label, value in rows:
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = value
        for run in cells[0].paragraphs[0].runs:
            run.bold = True


def _main_sections(blueprint: Dict[str, Any]) -> List[Dict[str, Any]]:
    skipped = {"significant_findings_summary"}
    return [
        section for section in blueprint.get("analysis_sections") or []
        if isinstance(section, dict)
        and section.get("section_id") not in skipped
        and (_section_tables(section) or _section_figures(section) or _text(section.get("interpretation")))
    ]


def _section_export_title(section_id: str, fallback: Any, label_ctx: Dict[str, Any]) -> str:
    marker = _text(label_ctx.get("display") or "Marker")
    titles = {
        "baseline_characteristics": "Section I - Baseline Characteristics",
        "clinical_study_characteristics": "Section II - Nodal and Prognostic Pathology",
        "immunophenotype_characteristics": "Section III - Immunophenotype",
        "marker_outcome_components": f"Section IV - {marker} / Marker Expression",
        "primary_outcome_distribution": f"Section IV - {marker} / Marker Expression",
        "bivariate_associations": "Section V - Statistical Associations",
        "correlation_analysis": "Section V - Correlation Analysis",
        "regression_adjusted_analysis": "Section V - Regression / Adjusted Analysis",
        "diagnostic_accuracy": "Section V - Diagnostic Accuracy",
        "reliability_agreement": "Section V - Reliability and Agreement",
        "survival_analysis": "Section V - Survival Analysis",
        "repeated_measures": "Section V - Repeated-Measures Analysis",
        "other_analyses": "Section V - Statistical Analyses",
    }
    return titles.get(section_id, _text(fallback) or "Results")


def _apply_polish_overrides(
    blueprint: Dict[str, Any],
    overrides: Dict[str, str],
) -> Dict[str, Any]:
    """Return a deep copy of blueprint with prose overrides injected into interpretation fields.

    Tables also get a ``_polish_interpretation`` key so the override survives
    through ``_descriptive_export_table``, which regenerates ``interpretation``.
    """
    if not overrides:
        return blueprint
    bp = deepcopy(blueprint)
    for section in bp.get("analysis_sections") or []:
        section_id = str(section.get("section_id") or "")
        s_key = f"section:{section_id}"
        if s_key in overrides:
            section["interpretation"] = overrides[s_key]
        for table in section.get("tables") or []:
            t_key = f"table:{table.get('table_id', '')}"
            if t_key in overrides:
                table["interpretation"] = overrides[t_key]
                table["_polish_interpretation"] = overrides[t_key]
        for fig in section.get("figures") or []:
            f_key = f"figure:{fig.get('figure_id', '')}"
            if f_key in overrides:
                fig["interpretation"] = overrides[f_key]
    return bp


def _section_intro(
    section: Dict[str, Any],
    label_ctx: Dict[str, Any],
    overrides: Optional[Dict[str, str]] = None,
) -> str:
    section_id = str(section.get("section_id") or "")
    if overrides:
        s_key = f"section:{section_id}"
        if s_key in overrides:
            return overrides[s_key]
    marker = _text(label_ctx.get("display") or "the primary outcome")
    intros = {
        "baseline_characteristics": "This section describes the baseline profile of the analysed sample.",
        "clinical_study_characteristics": "This section summarises clinically relevant pathology and prognostic variables.",
        "immunophenotype_characteristics": "This section summarises receptor, immunophenotypic, and molecular marker variables.",
        "marker_outcome_components": f"This section summarises {marker} and related marker-expression components.",
        "primary_outcome_distribution": f"This section reports the distribution of {marker}.",
        "bivariate_associations": f"This section presents statistical associations between eligible predictors and {marker}.",
    }
    return intros.get(section_id, _clean_interpretation(section.get("interpretation"), label_ctx))


def _add_warnings_docx(doc: Document, blueprint: Dict[str, Any]) -> None:
    warnings = list(blueprint.get("warnings") or [])
    unavailable = list(blueprint.get("unavailable_or_recommended_only") or [])
    if not warnings and not unavailable:
        _plain_docx_text(doc, "No major thesis-reporting cautions were recorded.")
        return
    for warning in warnings:
        _plain_docx_text(doc, _text(warning), style="List Bullet")
    for item in unavailable:
        if isinstance(item, dict):
            _plain_docx_text(doc, f"{_text(item.get('analysis')) or 'Analysis'}: {_text(item.get('reason'))}", style="List Bullet")
        else:
            _plain_docx_text(doc, _text(item), style="List Bullet")
    _plain_docx_text(
        doc,
        "Associations should not be interpreted as causal effects. Independent prognostic value should only be claimed when an adjusted model was actually performed.",
    )


def generate_docx(
    results: Dict[str, Any],
    *,
    include_optional_figures: bool = False,
    polish_overrides: Optional[Dict[str, str]] = None,
) -> bytes:
    blueprint = _blueprint(results)
    if polish_overrides:
        blueprint = _apply_polish_overrides(blueprint, polish_overrides)
    label_ctx = _outcome_label_context(blueprint)
    doc = Document()
    _set_docx_styles(doc)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("CHAPTER V\nOBSERVATION AND RESULTS")
    run.bold = True
    run.font.size = Pt(14)

    _add_heading(doc, "5.1 Study Summary", 1)
    _add_summary_docx(doc, blueprint, results)

    _add_heading(doc, "5.2 Statistical Methods", 1)
    methods = _text(blueprint.get("methods_text"))
    _plain_docx_text(doc, methods or "Statistical methods were generated from the executed Sigma analysis plan.")

    table_no = 1
    figure_no = 1
    main_sections = _main_sections(blueprint)

    baseline_sections = _dedupe_descriptive_sections([
        section for section in main_sections
        if section.get("section_id") in {
            "baseline_characteristics",
            "clinical_study_characteristics",
            "immunophenotype_characteristics",
            "marker_outcome_components",
            "descriptive_results",
        }
    ], label_ctx)
    if not baseline_sections:
        _plain_docx_text(doc, "Baseline and study characteristics were not available in the blueprint.")
    for section in [s for s in baseline_sections if s.get("section_id") not in {"marker_outcome_components"}]:
        _add_heading(doc, _section_export_title(str(section.get("section_id") or ""), section.get("title"), label_ctx), 1)
        intro = _section_intro(section, label_ctx, polish_overrides)
        if intro:
            _plain_docx_text(doc, intro)
        table_no, figure_no = _render_section_docx(
            doc, section, table_no, figure_no, label_ctx, include_optional_figures
        )

    _add_heading(doc, _section_export_title("primary_outcome_distribution", "Marker Expression", label_ctx), 1)
    outcome_sections = [section for section in main_sections if section.get("section_id") == "primary_outcome_distribution"]
    marker_sections = [section for section in baseline_sections if section.get("section_id") == "marker_outcome_components"]
    if outcome_sections:
        for section in outcome_sections:
            intro = _section_intro(section, label_ctx, polish_overrides)
            if intro:
                _plain_docx_text(doc, intro)
            outcome_tables = _section_tables(section) or _primary_outcome_tables(blueprint, label_ctx)
            for table in outcome_tables:
                table_no = _add_table_docx(doc, table, table_no, label_ctx, include_interpretation=False)
            rendered_outcome_figure = False
            if outcome_tables:
                generated = _primary_outcome_figure(blueprint, outcome_tables[0], label_ctx)
                if generated:
                    next_no = _add_figure_docx(doc, generated, figure_no, label_ctx)
                    rendered_outcome_figure = rendered_outcome_figure or next_no != figure_no
                    figure_no = next_no
            for fig in _section_figures(section, include_optional_figures)[:1]:
                if _text(fig.get("figure_id")) == "primary_outcome_distribution_generated":
                    continue
                next_no = _add_figure_docx(doc, _normalise_figure_metadata(fig, label_ctx), figure_no, label_ctx)
                rendered_outcome_figure = rendered_outcome_figure or next_no != figure_no
                figure_no = next_no
            for table in outcome_tables:
                interpretation = _clean_interpretation(table.get("interpretation"), label_ctx)
                if interpretation:
                    _plain_docx_text(doc, interpretation)
    else:
        _plain_docx_text(doc, "Primary outcome distribution was not available in the blueprint.")
    for section in marker_sections:
        table_no, figure_no = _render_section_docx(
            doc, section, table_no, figure_no, label_ctx, include_optional_figures
        )

    inferential_ids = {
        "bivariate_associations", "correlation_analysis", "regression_adjusted_analysis",
        "diagnostic_accuracy", "reliability_agreement", "survival_analysis",
        "repeated_measures", "other_analyses",
    }
    inferential_sections = [section for section in main_sections if section.get("section_id") in inferential_ids]
    if not inferential_sections:
        _add_heading(doc, "Section V - Statistical Associations", 1)
        _plain_docx_text(doc, "No thesis-ready inferential analysis tables were available.")
    for section in inferential_sections:
        _add_heading(doc, _section_export_title(str(section.get("section_id") or ""), section.get("title"), label_ctx), 1)
        intro = _section_intro(section, label_ctx, polish_overrides)
        if intro:
            _plain_docx_text(doc, intro)
        table_no, figure_no = _render_section_docx(
            doc, section, table_no, figure_no, label_ctx, include_optional_figures
        )

    _add_heading(doc, "Section VI - Significant Findings Summary", 1)
    findings = list(blueprint.get("significant_findings") or [])
    if findings:
        sig_table = {
            "title": "Final thesis significant findings",
            "columns": [
                "Variable / parameter", "Key finding", "Test statistic", "p-value",
                "Adjusted p-value", "Test applied", "Effect size", "Notes/warnings",
            ],
            "rows": [
                [
                    _display_value(row.get("variable") or "", label_ctx),
                    _clean_finding_text(row.get("key_finding") or ""),
                    row.get("test_statistic") or "",
                    row.get("p_value") or "",
                    row.get("adjusted_p_value") or "",
                    row.get("test_applied") or "",
                    row.get("effect_size") or "",
                    row.get("notes_warnings") or "",
                ]
                for row in findings if isinstance(row, dict)
            ],
            "interpretation": "These findings are filtered for thesis-facing reporting and exclude marker/outcome components by default.",
            "warnings": [],
        }
        table_no = _add_table_docx(doc, sig_table, table_no, label_ctx)
    else:
        _plain_docx_text(doc, "No final thesis significant findings were identified among the completed tests.")

    _add_heading(doc, "Warnings and Interpretation Notes", 1)
    _add_warnings_docx(doc, blueprint)

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _pdf_escape(value: Any) -> str:
    return _text(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _pdf_table(payload: Dict[str, Any], label_ctx: Optional[Dict[str, Any]] = None, width: float = 10.4 * inch) -> Tuple[Table, List[str]]:
    payload = _normalise_table_for_export(payload, label_ctx or {})
    payload, warning_notes = _compact_table_for_export(payload)
    headers, rows = _table_rows(payload)
    font_size = 6 if len(headers) > 6 else 7
    style = ParagraphStyle("Cell", fontName="Helvetica", fontSize=font_size, leading=font_size + 2)
    header_style = ParagraphStyle("CellHeader", parent=style, fontName="Helvetica-Bold")
    data = [[Paragraph(_pdf_escape(_display_value(h, label_ctx)), header_style) for h in headers]] + [
        [Paragraph(_pdf_escape(_display_value(cell, label_ctx)), style) for cell in row] for row in rows
    ]
    col_width = width / max(len(headers), 1)
    table = Table(data, colWidths=[col_width] * max(len(headers), 1), repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E9EEF7")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table, warning_notes


def _add_pdf_figure(flow: List[Any], figure: Dict[str, Any], figure_no: int, label_ctx: Dict[str, Any], body, small) -> int:
    png = _strip_data_uri(_text(figure.get("png_data_uri")))
    if not png:
        return figure_no
    try:
        flow.append(Image(io.BytesIO(png), width=5.5 * inch, height=3.4 * inch))
    except Exception:
        return figure_no
    flow.append(Paragraph(f"<i>Figure {figure_no}. {_pdf_escape(_display_value(figure.get('caption') or figure.get('title'), label_ctx))}</i>", small))
    interpretation = _clean_interpretation(figure.get("interpretation"), label_ctx)
    if interpretation:
        flow.append(Paragraph(_pdf_escape(interpretation), body))
    return figure_no + 1


def _render_section_pdf(
    flow: List[Any],
    section: Dict[str, Any],
    figure_no: int,
    label_ctx: Dict[str, Any],
    available_width: float,
    body,
    small,
    include_optional_figures: bool = False,
) -> int:
    section_id = str(section.get("section_id") or "")
    figures = [
        _normalise_figure_metadata(figure, label_ctx)
        for figure in _section_figures(section, include_optional_figures)
        if include_optional_figures or _is_core_figure(figure, label_ctx, section_id)
    ]
    used_figures: Set[str] = set()
    tables = _expand_export_tables(_section_tables(section), label_ctx)
    if section_id == "bivariate_associations":
        for figure in sorted(figures, key=lambda item: _association_figure_sort_key(item, label_ctx)):
            figure_id = _text(figure.get("figure_id") or figure.get("title"))
            if figure_id in used_figures:
                continue
            next_no = _add_pdf_figure(flow, figure, figure_no, label_ctx, body, small)
            if next_no != figure_no:
                figure_no = next_no
                used_figures.add(figure_id)
    for table in tables:
        flow.append(Paragraph(f"<b>{_pdf_escape(_display_value(_clean_table_title(table.get('title')), label_ctx))}</b>", small))
        pdf_table, warning_notes = _pdf_table(table, label_ctx, available_width)
        flow.append(pdf_table)
        for warning in warning_notes:
            flow.append(Paragraph(f"Caution: {_pdf_escape(_display_value(warning, label_ctx))}", small))
        for figure in figures:
            figure_id = _text(figure.get("figure_id") or figure.get("title"))
            if figure_id in used_figures or not _figure_matches_table(figure, table):
                continue
            next_no = _add_pdf_figure(flow, figure, figure_no, label_ctx, body, small)
            if next_no != figure_no:
                figure_no = next_no
                used_figures.add(figure_id)
        interpretation = _clean_interpretation(table.get("interpretation"), label_ctx)
        if interpretation:
            flow.append(Paragraph(_pdf_escape(interpretation), body))
        flow.append(Spacer(1, 6))
    if include_optional_figures:
        for figure in figures[:4]:
            figure_id = _text(figure.get("figure_id") or figure.get("title"))
            if figure_id in used_figures:
                continue
            next_no = _add_pdf_figure(flow, figure, figure_no, label_ctx, body, small)
            if next_no != figure_no:
                figure_no = next_no
                used_figures.add(figure_id)
    return figure_no


def generate_pdf(
    results: Dict[str, Any],
    *,
    include_optional_figures: bool = False,
    polish_overrides: Optional[Dict[str, str]] = None,
) -> bytes:
    blueprint = _blueprint(results)
    if polish_overrides:
        blueprint = _apply_polish_overrides(blueprint, polish_overrides)
    label_ctx = _outcome_label_context(blueprint)
    out = io.BytesIO()
    page_size = landscape(A4)
    available_width = page_size[0] - 72
    doc = SimpleDocTemplate(out, pagesize=page_size, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    body = styles["BodyText"]
    small = ParagraphStyle("Small", parent=body, fontSize=8, leading=10)
    flow: List[Any] = []
    figure_no = 1

    flow.append(Paragraph("CHAPTER V<br/>OBSERVATION AND RESULTS", styles["Title"]))
    flow.append(Spacer(1, 10))
    flow.append(Paragraph("5.1 Study Summary", h1))
    for label, value in _study_summary(blueprint, results):
        flow.append(Paragraph(f"<b>{_pdf_escape(label)}:</b> {_pdf_escape(value)}", body))
    flow.append(Paragraph("5.2 Statistical Methods", h1))
    flow.append(Paragraph(_pdf_escape(blueprint.get("methods_text") or "Statistical methods were generated from the executed Sigma analysis plan."), body))

    main_sections = _main_sections(blueprint)
    descriptive_sections = _dedupe_descriptive_sections([
        section for section in main_sections
        if section.get("section_id") in {"baseline_characteristics", "clinical_study_characteristics", "immunophenotype_characteristics", "marker_outcome_components", "descriptive_results"}
    ], label_ctx)
    for section in [s for s in descriptive_sections if s.get("section_id") != "marker_outcome_components"]:
        flow.append(Paragraph(_pdf_escape(_section_export_title(str(section.get("section_id") or ""), section.get("title"), label_ctx)), h1))
        intro = _section_intro(section, label_ctx, polish_overrides)
        if intro:
            flow.append(Paragraph(_pdf_escape(intro), body))
        figure_no = _render_section_pdf(
            flow, section, figure_no, label_ctx, available_width, body, small, include_optional_figures
        )

    flow.append(Paragraph(_pdf_escape(_section_export_title("primary_outcome_distribution", "Marker Expression", label_ctx)), h1))
    outcome_sections = [section for section in main_sections if section.get("section_id") == "primary_outcome_distribution"]
    for section in outcome_sections:
        intro = _section_intro(section, label_ctx, polish_overrides)
        if intro:
            flow.append(Paragraph(_pdf_escape(intro), body))
        outcome_tables = _primary_outcome_tables(blueprint, label_ctx) or _section_tables(section)
        display_tables = _expand_export_tables(outcome_tables, label_ctx)
        for table in display_tables:
            flow.append(Paragraph(f"<b>{_pdf_escape(_display_value(_clean_table_title(table.get('title')), label_ctx))}</b>", small))
            pdf_table, warning_notes = _pdf_table(table, label_ctx, available_width)
            flow.append(pdf_table)
            for warning in warning_notes:
                flow.append(Paragraph(f"Caution: {_pdf_escape(_display_value(warning, label_ctx))}", small))
        rendered_outcome_figure = False
        if outcome_tables:
            generated = _primary_outcome_figure(blueprint, outcome_tables[0], label_ctx)
            if generated:
                next_no = _add_pdf_figure(flow, generated, figure_no, label_ctx, body, small)
                rendered_outcome_figure = rendered_outcome_figure or next_no != figure_no
                figure_no = next_no
        for fig in _section_figures(section, include_optional_figures)[:1]:
            if _text(fig.get("figure_id")) == "primary_outcome_distribution_generated":
                continue
            next_no = _add_pdf_figure(flow, _normalise_figure_metadata(fig, label_ctx), figure_no, label_ctx, body, small)
            rendered_outcome_figure = rendered_outcome_figure or next_no != figure_no
            figure_no = next_no
        for table in display_tables:
            interpretation = _clean_interpretation(table.get("interpretation"), label_ctx)
            if interpretation:
                flow.append(Paragraph(_pdf_escape(interpretation), body))
    for section in [s for s in descriptive_sections if s.get("section_id") == "marker_outcome_components"]:
        figure_no = _render_section_pdf(
            flow, section, figure_no, label_ctx, available_width, body, small, include_optional_figures
        )

    inferential_ids = {"bivariate_associations", "correlation_analysis", "regression_adjusted_analysis", "diagnostic_accuracy", "reliability_agreement", "survival_analysis", "repeated_measures", "other_analyses"}
    for section in [section for section in main_sections if section.get("section_id") in inferential_ids]:
        flow.append(Paragraph(_pdf_escape(_section_export_title(str(section.get("section_id") or ""), section.get("title"), label_ctx)), h1))
        intro = _section_intro(section, label_ctx, polish_overrides)
        if intro:
            flow.append(Paragraph(_pdf_escape(intro), body))
        figure_no = _render_section_pdf(
            flow, section, figure_no, label_ctx, available_width, body, small, include_optional_figures
        )
    flow.append(Paragraph("Section VI - Significant Findings Summary", h1))
    if blueprint.get("significant_findings"):
        pdf_table, warning_notes = _pdf_table({
            "columns": [
                "Variable / parameter", "Key finding", "Test statistic", "p-value",
                "Adjusted p-value", "Test applied", "Effect size", "Notes/warnings",
            ],
            "rows": [
                [
                    _display_value(row.get("variable") or "", label_ctx),
                    _clean_finding_text(row.get("key_finding") or ""),
                    row.get("test_statistic") or "",
                    row.get("p_value") or "",
                    row.get("adjusted_p_value") or "",
                    row.get("test_applied") or "",
                    row.get("effect_size") or "",
                    row.get("notes_warnings") or "",
                ]
                for row in blueprint.get("significant_findings") or []
            ],
        }, label_ctx, available_width)
        flow.append(pdf_table)
        for warning in warning_notes:
            flow.append(Paragraph(f"Caution: {_pdf_escape(_display_value(warning, label_ctx))}", small))
    else:
        flow.append(Paragraph("No final thesis significant findings were identified among the completed tests.", body))
    flow.append(Paragraph("Warnings and Interpretation Notes", h1))
    warnings = list(blueprint.get("warnings") or [])
    unavailable = list(blueprint.get("unavailable_or_recommended_only") or [])
    if not warnings and not unavailable:
        flow.append(Paragraph("No major thesis-reporting cautions were recorded.", body))
    for warning in warnings:
        flow.append(Paragraph(f"• {_pdf_escape(warning)}", body))
    for item in unavailable:
        flow.append(Paragraph(f"• {_pdf_escape(item)}", body))
    flow.append(Paragraph("Associations should not be interpreted as causal effects. Independent prognostic value should only be claimed when an adjusted model was actually performed.", body))
    doc.build(flow)
    return out.getvalue()
