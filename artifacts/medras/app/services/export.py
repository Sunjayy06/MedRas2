"""Phase C — publication-ready Word/PDF/Excel export for MedRAS (Step 8).

Produces a 10-section Word report (cover, data summary, Table 1, normality,
primary, secondary, figures, results-narrative, methods, limitations) using
python-docx, plus parallel structures for PDF (reportlab) and Excel (openpyxl).
"""

from __future__ import annotations

import base64
import datetime
import io
import math
import os
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from openpyxl import Workbook

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from reportlab.lib import colors
from reportlab.lib.units import inch

from .results import clean_display_name


# ---------------------------------------------------------------------------
# Test-type sets (must match the test_type strings produced by run_plan)
# ---------------------------------------------------------------------------

_PRIMARY_TYPES = {
    "t_test_independent", "welch_ttest", "t_test_paired",
    "mann_whitney", "wilcoxon",
    "anova_oneway", "kruskal_wallis", "rm_anova", "friedman",
    "chi_square", "fisher_exact", "mcnemar",
}
_SECONDARY_TYPES = {
    "pearson", "spearman",
    "logistic_regression", "linear_regression",
    "kaplan_meier", "log_rank", "cox_regression",
    "diagnostic_accuracy", "kappa", "icc",
    "ordinal_logistic", "count_regression",
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def fmt_p(p) -> str:
    if p is None:
        return "—"
    try:
        if isinstance(p, str):
            return p
        if math.isnan(p):
            return "—"
        if p < 0.001:
            return "< 0.001"
        return f"{p:.3f}"
    except Exception:
        return "—"


def _strip_data_uri(data_uri: str) -> bytes:
    if not data_uri:
        return b""
    if "," in data_uri:
        return base64.b64decode(data_uri.split(",", 1)[1])
    return base64.b64decode(data_uri)


def _safe_float(v):
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _sanitize_text(text: str, variables: Dict[str, Dict[str, Any]]) -> str:
    """Replace raw column names in narrative text with their display names."""
    if not text or not variables:
        return text or ""
    # Replace longest names first so 'hhs_post' isn't shadowed by 'hhs'.
    for raw in sorted(variables.keys(), key=len, reverse=True):
        dname = (variables.get(raw) or {}).get("display_name") or raw
        if not dname or dname == raw:
            continue
        text = text.replace(raw, dname)
    return text


def _first_present(d: Dict[str, Any], *keys):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _fmt(v, places=3) -> str:
    f = _safe_float(v)
    if f is None:
        return "—"
    return f"{f:.{places}f}"


# ---------------------------------------------------------------------------
# Word table styling
# ---------------------------------------------------------------------------


def _ensure_child(parent, tag_name):
    """Find or create a child element by tag (replaces get_or_add_*)."""
    elem = parent.find(qn(tag_name))
    if elem is None:
        elem = OxmlElement(tag_name)
        parent.insert(0, elem)
    return elem


def format_table(table) -> None:
    """Horizontal-only borders + alternating shading + bold header."""
    tbl = table._tbl
    tblPr = _ensure_child(tbl, "w:tblPr")
    tblBorders = OxmlElement("w:tblBorders")
    # Kill verticals
    for edge in ("left", "right", "insideV"):
        tag = OxmlElement(f"w:{edge}")
        tag.set(qn("w:val"), "nil")
        tblBorders.append(tag)
    # Add horizontals
    for edge in ("top", "bottom", "insideH"):
        tag = OxmlElement(f"w:{edge}")
        tag.set(qn("w:val"), "single")
        tag.set(qn("w:sz"), "6")
        tag.set(qn("w:color"), "000000")
        tblBorders.append(tag)
    tblPr.append(tblBorders)

    for i, row in enumerate(table.rows):
        for cell in row.cells:
            tc = cell._tc
            tcPr = _ensure_child(tc, "w:tcPr")
            tcBorders = OxmlElement("w:tcBorders")
            for side in ("left", "right", "insideV"):
                b = OxmlElement(f"w:{side}")
                b.set(qn("w:val"), "nil")
                tcBorders.append(b)
            tcPr.append(tcBorders)
            if i > 0 and i % 2 == 0:
                shd = OxmlElement("w:shd")
                shd.set(qn("w:fill"), "F2F2F2")
                shd.set(qn("w:val"), "clear")
                tcPr.append(shd)
        if i == 0:
            for cell in row.cells:
                for para in cell.paragraphs:
                    for run in para.runs:
                        run.bold = True

    for row in table.rows:
        for cell in row.cells:
            for para in cell.paragraphs:
                for run in para.runs:
                    run.font.size = Pt(10)


def add_caption(doc, text: str) -> None:
    p = doc.add_paragraph(text)
    if p.runs:
        p.runs[0].bold = True
        p.runs[0].font.size = Pt(10)


def add_footnote(doc, text: str) -> None:
    p = doc.add_paragraph(text)
    if p.runs:
        p.runs[0].italic = True
        p.runs[0].font.size = Pt(9)


def _set_header_text(cell, text: str) -> None:
    cell.text = text
    for para in cell.paragraphs:
        for run in para.runs:
            run.bold = True


# ---------------------------------------------------------------------------
# Session adapter — turn (entry, results, assignment) into the spec's session
# ---------------------------------------------------------------------------


def _build_session(entry, results: Dict[str, Any], assignment: Dict[str, Any]) -> Dict[str, Any]:
    df = entry.df
    meta = entry.meta or {}
    intake = meta.get("intake") or {}
    classifications = meta.get("classifications") or []
    normality = meta.get("normality") or {}

    # Variables map keyed by raw column name
    variables: Dict[str, Dict[str, Any]] = {}
    for c in classifications:
        col = c.get("column")
        if not col:
            continue
        miss_n = int(df[col].isna().sum()) if col in df.columns else 0
        n = int(df.shape[0]) or 1
        variables[str(col)] = {
            "display_name": clean_display_name(col),
            "type": _pretty_type(c.get("detected_type")),
            "missing_n": miss_n,
            "missing_pct": round(100.0 * miss_n / n, 1),
        }
    # Catch any df columns missing from classifications
    for col in df.columns:
        if str(col) not in variables:
            miss_n = int(df[col].isna().sum())
            n = int(df.shape[0]) or 1
            variables[str(col)] = {
                "display_name": clean_display_name(col),
                "type": "",
                "missing_n": miss_n,
                "missing_pct": round(100.0 * miss_n / n, 1),
            }

    # Normality results: convert {'columns':[{...}]} → {col: {test, stat, p, decision, normal}}
    norm_map: Dict[str, Dict[str, Any]] = {}
    for row in (normality.get("columns") or []) if isinstance(normality, dict) else []:
        col = row.get("column")
        if not col:
            continue
        decision = row.get("decision") or ""
        is_normal = decision == "normal"
        norm_map[col] = {
            "test": row.get("test") or "",
            "stat": _safe_float(row.get("statistic")),
            "p": _safe_float(row.get("p_value")),
            "skew": _safe_float(row.get("skewness")),
            "decision": "Normal" if is_normal else (
                "Non-normal" if decision in ("non_normal", "not_normal") else
                decision.replace("_", " ").capitalize()),
            "normal": is_normal,
        }

    # Graph paths: dump png data-URIs to temp files
    tmpdir = tempfile.mkdtemp(prefix="medras_export_")
    graph_paths: List[Tuple[str, str]] = []
    for i, g in enumerate(results.get("graphs") or []):
        png = _strip_data_uri(g.get("png_data_uri") or "")
        if not png:
            continue
        path = os.path.join(tmpdir, f"graph_{i}.png")
        with open(path, "wb") as f:
            f.write(png)
        caption = _sanitize_text(g.get("title") or f"Figure {i+1}", variables)
        graph_paths.append((path, caption))
    # Forest plot is only embedded when the results dict explicitly carries one
    # (i.e. logistic / Cox regression was run).  For correlation and standard
    # observational studies forest_plot is None and this block is skipped.
    if results.get("forest_plot"):
        png = _strip_data_uri(results["forest_plot"])
        if png:
            path = os.path.join(tmpdir, "forest.png")
            with open(path, "wb") as f:
                f.write(png)
            graph_paths.append((path, "Forest plot — odds / hazard ratios (95% CI)"))

    objective = ""
    if isinstance(intake, dict):
        objective = (intake.get("objective") or intake.get("objective_text")
                     or intake.get("text") or "")

    cleaning_actions: List[str] = []
    for c in classifications:
        if c.get("auto_strip_count"):
            cleaning_actions.append(
                f"Stripped non-numeric prefixes from "
                f"{clean_display_name(c.get('column',''))} "
                f"({c['auto_strip_count']} cells cleaned).")
    if meta.get("merged_sheets"):
        cleaning_actions.append(
            f"Merged sheets: {', '.join(meta['merged_sheets'])}.")

    return {
        "objective": str(objective) or "Not specified",
        "filename": meta.get("filename") or "Unknown",
        "n_rows": int(df.shape[0]),
        "n_cols": int(df.shape[1]),
        "analysis_date": datetime.date.today().strftime("%d %B %Y"),
        "variables": variables,
        "normality_results": norm_map,
        "outcome_variable": (assignment or {}).get("outcome"),
        "grouping_variable": (assignment or {}).get("group"),
        "covariates": list((assignment or {}).get("covariates") or []),
        "graph_paths": graph_paths,
        "cleaning_actions": cleaning_actions,
        "correction_info": results.get("correction_info"),
        "results": results.get("tests") or [],
        "table_one": results.get("table_one") or {},
        "is_practice": bool(meta.get("is_dummy") or meta.get("is_practice_wizard")),
    }


def _pretty_type(detected_type: Optional[str]) -> str:
    return {
        "scale": "Scale (continuous)",
        "ordinal": "Ordinal",
        "nominal": "Nominal",
        "id": "Identifier",
        "datetime": "Date/Time",
    }.get(detected_type or "", detected_type or "")


# ---------------------------------------------------------------------------
# Word — Section builders
# ---------------------------------------------------------------------------


def build_table1(doc, table1_data: Dict[str, Any], session: Dict[str, Any]) -> None:
    headers = list(table1_data.get("headers") or [])
    rows = list(table1_data.get("rows") or [])
    if not headers or not rows:
        doc.add_paragraph(
            "Table 1 is not available — no descriptive summary was generated.")
        return

    table = doc.add_table(rows=1, cols=len(headers))
    for i, h in enumerate(headers):
        _set_header_text(table.rows[0].cells[i], str(h))

    variables = session.get("variables", {})
    for item in rows:
        cells = table.add_row().cells
        # Resolve display name for the variable column
        var_raw = item.get("variable", "")
        dname = variables.get(var_raw, {}).get("display_name") or clean_display_name(var_raw)
        cells[0].text = dname
        # Column 2: 'type' from results.py describes the summary kind
        cells[1].text = str(item.get("type", ""))
        # Subsequent columns: per-group cells
        per_group = list(item.get("cells") or [])
        for j, val in enumerate(per_group, start=2):
            if j < len(cells):
                cells[j].text = str(val)
        # If a p-value column exists at the end, populate it
        if "p" in item and len(cells) >= len(headers):
            p_val = _safe_float(item.get("p"))
            if p_val is not None:
                cells[-1].text = fmt_p(p_val)
                if p_val < 0.05:
                    for run in cells[-1].paragraphs[0].runs:
                        run.bold = True

    format_table(table)
    add_caption(doc, "Table 1. Baseline characteristics.")
    add_footnote(
        doc,
        "Values expressed as mean ± SD, median (IQR), or n (%) as appropriate. "
        "Independent t-test, Mann-Whitney U, chi-square, or Fisher exact used "
        "for group comparisons as appropriate. p < 0.05 considered significant.",
    )


def _detect_regression_rows(rows: List[Dict[str, Any]]) -> bool:
    if not rows:
        return False
    keys = set(rows[0].keys()) if isinstance(rows[0], dict) else set()
    return ("variable" in keys) and bool(keys & {"OR", "HR", "coef", "beta"})


def _detect_diagnostic(result: Dict[str, Any]) -> bool:
    return all(k in result for k in ("TP", "TN", "FP", "FN"))


def build_result_table(doc, result: Dict[str, Any],
                       session: Dict[str, Any], table_num: int) -> None:
    test_name = result.get("plan_name") or result.get("title") or result.get("test", "Test")

    # Warning / reason banner
    if result.get("warning"):
        p = doc.add_paragraph(f"⚠ {result['warning']}")
        if p.runs:
            p.runs[0].font.color.rgb = RGBColor(0x85, 0x4F, 0x0B)
    if result.get("plan_reason"):
        p = doc.add_paragraph(f"Why this test: {result['plan_reason']}")
        if p.runs:
            p.runs[0].italic = True
            p.runs[0].font.size = Pt(9)

    test_type = result.get("test_type") or ""
    rows = result.get("rows") or []

    # Branch 1: diagnostic accuracy
    if test_type == "diagnostic_accuracy" or _detect_diagnostic(result):
        _render_diagnostic_table(doc, result)

    # Branch 2: regression (logistic / cox / linear with row-per-variable)
    elif test_type in ("logistic_regression", "cox_regression", "linear_regression",
                        "ordinal_logistic", "count_regression") or _detect_regression_rows(rows):
        _render_regression_table(doc, result)

    # Branch 3: ICC / kappa / Bland-Altman — render specific fields
    elif test_type in ("icc", "kappa"):
        _render_agreement_table(doc, result)

    # Branch 4: survival (KM)
    elif test_type in ("kaplan_meier", "log_rank"):
        _render_survival_table(doc, result)

    # Branch 5: standard inferential — header + p + effect
    elif test_type in _PRIMARY_TYPES:
        _render_inferential_table(doc, result)

    # Fallback: 2-col label/value table from rows
    else:
        _render_generic_rows(doc, result)

    add_caption(doc, f"Table {table_num}. {test_name} — results.")
    note_bits = ["CI confidence interval"]
    if test_type in ("logistic_regression", "cox_regression"):
        note_bits.append("OR odds ratio; HR hazard ratio")
    if test_type == "diagnostic_accuracy":
        note_bits.append("AUC area under the ROC curve")
    note_bits.append("Bold p-values indicate p < 0.05")
    add_footnote(doc, "; ".join(note_bits) + ".")
    if result.get("narrative"):
        doc.add_paragraph(_sanitize_text(result["narrative"], session.get("variables", {})))


def _render_inferential_table(doc, result: Dict[str, Any]) -> None:
    headers = ["Test", "Statistic", "df", "p-value", "Effect size"]
    table = doc.add_table(rows=2, cols=len(headers))
    for i, h in enumerate(headers):
        _set_header_text(table.rows[0].cells[i], h)
    cells = table.rows[1].cells
    cells[0].text = result.get("plan_name") or result.get("title", "")

    stat = _first_present(result, "statistic", "t", "U", "F", "z", "chi2", "W")
    cells[1].text = _fmt(stat)

    df_val = _first_present(result, "df", "df1", "df_between")
    cells[2].text = (str(df_val) if df_val is not None else "—")

    p_val = _safe_float(result.get("p") or result.get("p_value"))
    cells[3].text = fmt_p(p_val)
    if p_val is not None and p_val < 0.05:
        for run in cells[3].paragraphs[0].runs:
            run.bold = True

    eff = _first_present(result, "effect_size", "cohens_d", "eta_squared", "omega_squared",
                         "rank_biserial", "cramers_v", "phi", "r")
    eff_label = result.get("effect_label") or _guess_effect_label(result)
    cells[4].text = (f"{eff_label} = {_fmt(eff)}" if eff is not None else "—")
    format_table(table)


def _guess_effect_label(result: Dict[str, Any]) -> str:
    for k, lbl in (("cohens_d", "Cohen's d"), ("eta_squared", "η²"),
                   ("omega_squared", "ω²"), ("rank_biserial", "Rank-biserial r"),
                   ("cramers_v", "Cramér's V"), ("phi", "φ"), ("r", "r")):
        if k in result and result[k] is not None:
            return lbl
    return "Effect"


def _render_regression_table(doc, result: Dict[str, Any]) -> None:
    rows = result.get("rows") or []
    is_or = any("OR" in r for r in rows if isinstance(r, dict))
    is_hr = any("HR" in r for r in rows if isinstance(r, dict))
    metric_label = "OR" if is_or else ("HR" if is_hr else "Estimate")
    headers = ["Variable", metric_label, "95% CI", "p-value"]
    table = doc.add_table(rows=1, cols=len(headers))
    for i, h in enumerate(headers):
        _set_header_text(table.rows[0].cells[i], h)
    for item in rows:
        if not isinstance(item, dict):
            continue
        c = table.add_row().cells
        c[0].text = str(item.get("variable") or item.get("label") or "")
        metric = _first_present(item, "OR", "HR", "coef", "beta", "estimate", "value")
        c[1].text = _fmt(metric)
        ci_lo = _safe_float(_first_present(item, "CI_lo", "ci_lo", "lower"))
        ci_hi = _safe_float(_first_present(item, "CI_hi", "ci_hi", "upper"))
        c[2].text = (f"{ci_lo:.3f} – {ci_hi:.3f}" if ci_lo is not None and ci_hi is not None else "—")
        p_val = _safe_float(item.get("p") or item.get("p_value"))
        c[3].text = fmt_p(p_val)
        if p_val is not None and p_val < 0.05:
            for run in c[3].paragraphs[0].runs:
                run.bold = True
    format_table(table)


def _render_diagnostic_table(doc, result: Dict[str, Any]) -> None:
    TP = int(result.get("TP", 0)); TN = int(result.get("TN", 0))
    FP = int(result.get("FP", 0)); FN = int(result.get("FN", 0))
    n = TP + TN + FP + FN
    auc = _safe_float(result.get("auc"))

    def wci(k: int, total: int) -> str:
        if total <= 0:
            return "—"
        try:
            from statsmodels.stats.proportion import proportion_confint
            lo, hi = proportion_confint(k, total, method="wilson")
            return f"{lo:.3f} – {hi:.3f}"
        except Exception:
            return "—"

    measures = [
        ("Sensitivity", TP / (TP + FN) if (TP + FN) else 0.0, wci(TP, TP + FN)),
        ("Specificity", TN / (TN + FP) if (TN + FP) else 0.0, wci(TN, TN + FP)),
        ("PPV",         TP / (TP + FP) if (TP + FP) else 0.0, wci(TP, TP + FP)),
        ("NPV",         TN / (TN + FN) if (TN + FN) else 0.0, wci(TN, TN + FN)),
        ("Accuracy",    (TP + TN) / n if n else 0.0, wci(TP + TN, n)),
        ("AUC",         auc if auc is not None else 0.0, "—"),
    ]
    table = doc.add_table(rows=1, cols=3)
    for i, h in enumerate(("Measure", "Value", "95% CI")):
        _set_header_text(table.rows[0].cells[i], h)
    for name, val, ci in measures:
        c = table.add_row().cells
        c[0].text = name
        c[1].text = _fmt(val)
        c[2].text = ci
    format_table(table)


def _render_agreement_table(doc, result: Dict[str, Any]) -> None:
    rows: List[Tuple[str, str]] = []
    if result.get("test_type") == "icc":
        icc = _safe_float(result.get("icc"))
        ci = result.get("icc_ci")
        rows.append(("ICC", _fmt(icc)))
        if ci and len(ci) == 2:
            rows.append(("95% CI", f"{ci[0]:.3f} – {ci[1]:.3f}"))
        rows.append(("Interpretation", str(result.get("icc_interpretation", "—"))))
        if "icc_p" in result:
            rows.append(("p-value", fmt_p(result.get("icc_p"))))
        ba = result.get("bland_altman") or {}
        if ba:
            rows.append(("Bland-Altman bias", _fmt(ba.get("mean_bias"))))
            loa = ba.get("limits_of_agreement")
            if loa:
                rows.append(("95% limits of agreement", f"{loa[0]:.3f} – {loa[1]:.3f}"))
    else:  # kappa
        rows.append(("Kappa", _fmt(result.get("kappa"))))
        ci = result.get("kappa_ci")
        if ci and len(ci) == 2:
            rows.append(("95% CI", f"{ci[0]:.3f} – {ci[1]:.3f}"))
        rows.append(("Interpretation", str(result.get("kappa_interpretation", "—"))))
        if "p" in result:
            rows.append(("p-value", fmt_p(result.get("p"))))

    table = doc.add_table(rows=1, cols=2)
    _set_header_text(table.rows[0].cells[0], "Measure")
    _set_header_text(table.rows[0].cells[1], "Value")
    for label, value in rows:
        c = table.add_row().cells
        c[0].text = label
        c[1].text = str(value)
    format_table(table)


def _render_survival_table(doc, result: Dict[str, Any]) -> None:
    rows: List[Tuple[str, str]] = []
    p_lr = _safe_float(result.get("logrank_p") or result.get("p"))
    rows.append(("Log-rank p-value", fmt_p(p_lr)))
    rows.append(("Log-rank χ²", _fmt(result.get("logrank_stat") or result.get("statistic"))))
    medians = result.get("median_survival") or {}
    for grp, med in medians.items():
        rows.append((f"Median survival ({grp})", _fmt(med, 1)))
    if not medians:
        for r in (result.get("rows") or []):
            if isinstance(r, dict):
                rows.append((str(r.get("label", "")), str(r.get("value", ""))))
    table = doc.add_table(rows=1, cols=2)
    _set_header_text(table.rows[0].cells[0], "Statistic")
    _set_header_text(table.rows[0].cells[1], "Value")
    for label, value in rows:
        c = table.add_row().cells
        c[0].text = label
        c[1].text = str(value)
        if "p-value" in label and p_lr is not None and p_lr < 0.05:
            for run in c[1].paragraphs[0].runs:
                run.bold = True
    format_table(table)


def _render_generic_rows(doc, result: Dict[str, Any]) -> None:
    rows = result.get("rows") or []
    if not rows:
        doc.add_paragraph(
            result.get("narrative") or "No tabular results available for this test.")
        return
    table = doc.add_table(rows=1, cols=2)
    _set_header_text(table.rows[0].cells[0], "Statistic")
    _set_header_text(table.rows[0].cells[1], "Value")
    for r in rows:
        if not isinstance(r, dict):
            continue
        c = table.add_row().cells
        c[0].text = str(r.get("label", ""))
        c[1].text = str(r.get("value", ""))
    format_table(table)


# ---------------------------------------------------------------------------
# Narrative builders
# ---------------------------------------------------------------------------


def build_results_narrative(session: Dict[str, Any], results: List[Dict[str, Any]]) -> str:
    n = session.get("n_rows", 0)
    variables = session.get("variables", {})
    outcome = session.get("outcome_variable") or ""
    grouping = session.get("grouping_variable") or ""
    out_name = variables.get(outcome, {}).get("display_name") or clean_display_name(outcome) or "the outcome"
    grp_name = variables.get(grouping, {}).get("display_name") or clean_display_name(grouping) or ""

    text = f"A total of {n} participants were included in the analysis. "

    norm = session.get("normality_results", {})
    non_normal = [variables.get(v, {}).get("display_name") or clean_display_name(v)
                  for v, r in norm.items() if not r.get("normal", True)]
    if non_normal:
        text += (f'{", ".join(non_normal)} '
                 f'{"was" if len(non_normal) == 1 else "were"} not normally distributed; '
                 f'non-parametric tests were used where appropriate. ')

    primary = next((r for r in results
                    if r.get("test_type") in _PRIMARY_TYPES and "error" not in r), None)
    if primary:
        test_name = primary.get("plan_name") or primary.get("title", "the primary test")
        stat = _first_present(primary, "statistic", "t", "U", "F", "z", "chi2", "W")
        p = _safe_float(primary.get("p") or primary.get("p_value"))
        eff = _first_present(primary, "effect_size", "cohens_d", "eta_squared",
                             "rank_biserial", "cramers_v", "phi")
        eff_label = primary.get("effect_label") or _guess_effect_label(primary)
        sig = "significantly" if (p is not None and p < 0.05) else "not significantly"
        if grp_name:
            text += f"{out_name} differed {sig} between {grp_name} groups ({test_name}: "
        else:
            text += f"{out_name} showed a {sig} change ({test_name}: "
        if stat is not None:
            text += f"statistic = {_fmt(stat)}, "
        text += f"p = {fmt_p(p)}"
        if eff is not None:
            text += f", {eff_label} = {_fmt(eff)}"
        text += ") (Table 3). "

    reg = next((r for r in results if r.get("test_type") in
                ("logistic_regression", "linear_regression", "cox_regression")
                and "error" not in r), None)
    if reg:
        for item in (reg.get("rows") or []):
            if not isinstance(item, dict):
                continue
            p = _safe_float(item.get("p") or item.get("p_value"))
            if p is None or p >= 0.05:
                continue
            metric_key = "OR" if "OR" in item else ("HR" if "HR" in item else "estimate")
            metric = _safe_float(item.get(metric_key) or item.get("coef"))
            ci_lo = _safe_float(_first_present(item, "CI_lo", "ci_lo"))
            ci_hi = _safe_float(_first_present(item, "CI_hi", "ci_hi"))
            text += (f"On regression analysis, {item.get('variable','')} was an "
                     f"independent predictor of {out_name} "
                     f"(adjusted {metric_key} = {_fmt(metric)}")
            if ci_lo is not None and ci_hi is not None:
                text += f", 95% CI: {ci_lo:.3f}–{ci_hi:.3f}"
            text += f", p = {fmt_p(p)}). "
            break

    surv = next((r for r in results if r.get("test_type") in ("kaplan_meier", "log_rank")
                 and "error" not in r), None)
    if surv:
        p_lr = _safe_float(surv.get("logrank_p") or surv.get("p"))
        sig = "significant" if (p_lr is not None and p_lr < 0.05) else "no significant"
        text += f"Log-rank test showed {sig} difference in survival between groups (p = {fmt_p(p_lr)}). "

    return text


def build_methods_paragraph(session: Dict[str, Any], results: List[Dict[str, Any]]) -> str:
    versions = []
    for mod_name, label in (("scipy", "scipy"), ("statsmodels", "statsmodels"),
                            ("pingouin", "pingouin"), ("lifelines", "lifelines")):
        try:
            mod = __import__(mod_name)
            versions.append(f"{label} (v{getattr(mod, '__version__', '?')})")
        except Exception:
            pass

    norm = session.get("normality_results", {})
    tests_used = sorted({r.get("plan_name") or r.get("title", "")
                         for r in results if (r.get("plan_name") or r.get("title"))})
    normal_vars = [v for v, r in norm.items() if r.get("normal", True)]
    non_normal_vars = [v for v, r in norm.items() if not r.get("normal", True)]
    norm_test = "Shapiro-Wilk" if session.get("n_rows", 0) < 50 else "Kolmogorov-Smirnov"
    correction = session.get("correction_info")

    text = ("All statistical analyses were performed using Python with the "
            f"{', '.join(versions)} libraries. " if versions else
            "All statistical analyses were performed using Python. ")
    text += ("A two-tailed p-value < 0.05 was considered statistically significant. ")

    if normal_vars:
        text += (f"Continuous variables were assessed for normality using the "
                 f"{norm_test} test. Normally distributed variables were expressed "
                 f"as mean ± standard deviation. ")
    if non_normal_vars:
        text += ("Non-normally distributed variables were expressed as median with "
                 "interquartile range. ")
    text += "Categorical variables were expressed as frequencies and percentages. "

    if tests_used:
        text += f"Statistical tests used included: {', '.join(tests_used)}. "

    if correction:
        text += (f"Correction for multiple comparisons was applied using the "
                 f"{correction.get('method','')} method "
                 f"({correction.get('n_tests','')} tests). "
                 f"Both uncorrected and corrected p-values are reported. ")

    return text


def collect_limitations(session: Dict[str, Any], results: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    n = session.get("n_rows", 0)
    if n and n < 30:
        out.append(f"Small sample size (n={n}). Results should be interpreted "
                   f"with caution and confirmed in larger studies.")

    for r in results:
        if r.get("ph_note"):
            out.append(f"Cox regression: {r['ph_note']}")
        vifs = r.get("high_vif_warning") or {}
        for var, vif in vifs.items():
            out.append(f"Multicollinearity: {var} (VIF={_fmt(vif,1)}) was removed "
                       f"from the regression model.")
        if r.get("heteroscedasticity_warning"):
            out.append("Heteroscedasticity detected in linear regression residuals.")
        if r.get("warning"):
            out.append(str(r["warning"]))
        if r.get("error"):
            out.append(f"{r.get('plan_name') or r.get('title','Test')} could not "
                       f"complete: {r['error']}")

    pcts = [v.get("missing_pct", 0) for v in (session.get("variables", {}) or {}).values()]
    if pcts:
        max_pct = max(pcts)
        if max_pct > 20:
            out.append(f"High missing data rate detected (up to {max_pct:.0f}%). "
                       f"Results may be affected by missing data.")

    if not session.get("correction_info"):
        n_tests = sum(1 for r in results if "error" not in r)
        if n_tests >= 3:
            out.append(f"{n_tests} statistical tests were performed without "
                       f"automatic correction; multiple comparisons increase the "
                       f"risk of type I error.")
    return out


# ---------------------------------------------------------------------------
# Main Word generator
# ---------------------------------------------------------------------------


def generate_report(session: Dict[str, Any], df: pd.DataFrame) -> Document:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    graph_paths = session.get("graph_paths", [])
    results = session.get("results", [])

    # Red disclaimer banner at the very top when this report was built from
    # generated practice data — keeps reports from being mistaken for real
    # patient analyses.
    if session.get("is_practice"):
        warn = doc.add_paragraph()
        warn.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = warn.add_run(
            "⚠ NOT REAL PATIENT DATA — DO NOT PUBLISH. "
            "This report was generated from a MedRAS practice dataset "
            "for learning purposes only."
        )
        run.bold = True
        run.font.color.rgb = RGBColor(0xC0, 0x39, 0x2B)
        run.font.size = Pt(12)

    # ── 1. COVER ───────────────────────────────────────────────
    doc.add_heading("Statistical Analysis Report", 0)
    cover_info = [
        ("Study", session.get("objective", "Not specified")),
        ("Date", session.get("analysis_date", datetime.date.today().strftime("%d %B %Y"))),
        ("Dataset", session.get("filename", "Unknown")),
        ("Patients", str(session.get("n_rows", 0))),
        ("Variables", str(session.get("n_cols", 0))),
        ("Generated by", "MedRAS — Medical Research Acceleration System"),
    ]
    for label, value in cover_info:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(f"{label}: "); run.bold = True
        p.add_run(str(value))
    doc.add_page_break()

    # ── 2. DATA SUMMARY ────────────────────────────────────────
    doc.add_heading("Data Summary", 1)
    variables = session.get("variables", {})
    if variables:
        table = doc.add_table(rows=1, cols=4)
        for i, h in enumerate(("Variable", "Type", "Missing n", "Missing %")):
            _set_header_text(table.rows[0].cells[i], h)
        for col, info in variables.items():
            c = table.add_row().cells
            c[0].text = info.get("display_name", col)
            c[1].text = info.get("type", "")
            c[2].text = str(info.get("missing_n", 0))
            c[3].text = f'{info.get("missing_pct", 0):.1f}%'
        format_table(table)
        add_caption(doc, "Table 1a. Variable summary.")

    cleaning = session.get("cleaning_actions", [])
    if cleaning:
        doc.add_heading("Data Cleaning", 2)
        for action in cleaning:
            doc.add_paragraph(action, style="List Bullet")
    doc.add_page_break()

    # ── 3. TABLE 1 ─────────────────────────────────────────────
    doc.add_heading("Table 1. Baseline Characteristics", 1)
    build_table1(doc, session.get("table_one") or {}, session)
    doc.add_page_break()

    # ── 4. NORMALITY ───────────────────────────────────────────
    doc.add_heading("Normality Assessment", 1)
    norm_results = session.get("normality_results", {})
    if norm_results:
        table = doc.add_table(rows=1, cols=5)
        for i, h in enumerate(("Variable", "Test", "Statistic", "p-value", "Decision")):
            _set_header_text(table.rows[0].cells[i], h)
        for var, r in norm_results.items():
            row = table.add_row().cells
            row[0].text = variables.get(var, {}).get("display_name") or clean_display_name(var)
            row[1].text = r.get("test", "")
            row[2].text = _fmt(r.get("stat"))
            row[3].text = fmt_p(r.get("p"))
            decision = r.get("decision", "")
            row[4].text = decision
            if decision.startswith("Non-normal"):
                for cell in row:
                    for para in cell.paragraphs:
                        for run in para.runs:
                            run.font.color.rgb = RGBColor(0xA3, 0x2D, 0x2D)
        format_table(table)
        add_caption(doc, "Table 2. Normality assessment results.")
        add_footnote(doc,
                     "SW Shapiro-Wilk; KS Kolmogorov-Smirnov. "
                     "p < 0.05 indicates non-normal distribution.")
    else:
        doc.add_paragraph("No continuous variables required normality assessment.")
    doc.add_page_break()

    # ── 5. PRIMARY ─────────────────────────────────────────────
    doc.add_heading("Primary Analysis", 1)
    primary = next((r for r in results
                    if r.get("test_type") in _PRIMARY_TYPES and "error" not in r), None)
    if primary:
        build_result_table(doc, primary, session, table_num=3)
    else:
        doc.add_paragraph("No primary inferential comparison ran successfully.")
    doc.add_page_break()

    # ── 6. SECONDARY ───────────────────────────────────────────
    secondary = [r for r in results
                 if r.get("test_type") in _SECONDARY_TYPES and "error" not in r]
    if secondary:
        doc.add_heading("Secondary Analyses", 1)
        table_num = 4
        for r in secondary:
            doc.add_heading(r.get("plan_name") or r.get("title") or r.get("test_type",""), 2)
            build_result_table(doc, r, session, table_num=table_num)
            table_num += 1
            doc.add_paragraph()
        doc.add_page_break()

    # ── 7. FIGURES ─────────────────────────────────────────────
    if graph_paths:
        doc.add_heading("Figures", 1)
        for i, (path, caption) in enumerate(graph_paths, 1):
            if not os.path.exists(path):
                continue
            doc.add_picture(path, width=Inches(5.5))
            p = doc.add_paragraph(f"Figure {i}. {caption}")
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            if p.runs:
                p.runs[0].italic = True
            doc.add_paragraph()
        doc.add_page_break()

    # ── 8. RESULTS NARRATIVE ───────────────────────────────────
    doc.add_heading("Results Section", 1)
    p = doc.add_paragraph(
        "Copy the text below directly into your paper's Results section.")
    if p.runs:
        p.runs[0].italic = True
    doc.add_paragraph(build_results_narrative(session, results))
    doc.add_page_break()

    # ── 9. METHODS ─────────────────────────────────────────────
    doc.add_heading("Statistical Analysis", 1)
    p = doc.add_paragraph(
        "Copy the text below directly into your paper's Methods section.")
    if p.runs:
        p.runs[0].italic = True
    doc.add_paragraph(build_methods_paragraph(session, results))
    doc.add_page_break()

    # ── 10. LIMITATIONS ────────────────────────────────────────
    doc.add_heading("Limitations and Notes", 1)
    limitations = collect_limitations(session, results)
    if limitations:
        for lim in limitations:
            doc.add_paragraph(lim, style="List Bullet")
    else:
        doc.add_paragraph("No major assumption violations or warnings detected.")

    return doc


# ---------------------------------------------------------------------------
# Top-level format dispatchers (called from /export endpoint)
# ---------------------------------------------------------------------------


def to_docx(entry, results: Dict[str, Any], assignment: Dict[str, Any]) -> bytes:
    session = _build_session(entry, results, assignment)
    doc = generate_report(session, entry.df)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def to_pdf(entry, results: Dict[str, Any], assignment: Dict[str, Any]) -> bytes:
    """Mirror the 10-section Word report in PDF (best effort, reportlab)."""
    session = _build_session(entry, results, assignment)
    out = io.BytesIO()
    pdf = SimpleDocTemplate(out, pagesize=A4, leftMargin=36, rightMargin=36,
                            topMargin=48, bottomMargin=48)
    styles = getSampleStyleSheet()
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], spaceBefore=10)
    body = styles["BodyText"]
    italic = ParagraphStyle("italic", parent=body, fontName="Helvetica-Oblique")
    flow: List[Any] = []

    # 1. Cover
    flow.append(Paragraph("Statistical Analysis Report", styles["Title"]))
    flow.append(Spacer(1, 12))
    cover = [
        ("Study", session.get("objective", "Not specified")),
        ("Date", session.get("analysis_date", "")),
        ("Dataset", session.get("filename", "")),
        ("Patients", str(session.get("n_rows", 0))),
        ("Variables", str(session.get("n_cols", 0))),
        ("Generated by", "MedRAS"),
    ]
    for k, v in cover:
        flow.append(Paragraph(f"<b>{k}:</b> {v}", body))
    flow.append(PageBreak())

    # 2. Data summary
    flow.append(Paragraph("Data Summary", h2))
    variables = session.get("variables", {})
    if variables:
        data = [["Variable", "Type", "Missing n", "Missing %"]]
        for col, info in variables.items():
            data.append([info.get("display_name", col), info.get("type", ""),
                         str(info.get("missing_n", 0)),
                         f'{info.get("missing_pct", 0):.1f}%'])
        flow.append(_pdf_table(data))
    if session.get("cleaning_actions"):
        flow.append(Paragraph("Data Cleaning", h2))
        for a in session["cleaning_actions"]:
            flow.append(Paragraph(f"• {a}", body))
    flow.append(PageBreak())

    # 3. Table 1
    flow.append(Paragraph("Table 1. Baseline Characteristics", h2))
    t1 = session.get("table_one") or {}
    if t1.get("headers") and t1.get("rows"):
        data = [list(t1["headers"])]
        for row in t1["rows"]:
            cells = [variables.get(row.get("variable",""), {}).get("display_name")
                     or clean_display_name(row.get("variable","")),
                     str(row.get("type", ""))] + [str(c) for c in (row.get("cells") or [])]
            data.append(cells)
        flow.append(_pdf_table(data))
    flow.append(PageBreak())

    # 4. Normality
    flow.append(Paragraph("Normality Assessment", h2))
    if session.get("normality_results"):
        data = [["Variable", "Test", "Statistic", "p-value", "Decision"]]
        for v, r in session["normality_results"].items():
            data.append([variables.get(v, {}).get("display_name") or clean_display_name(v),
                         r.get("test", ""), _fmt(r.get("stat")),
                         fmt_p(r.get("p")), r.get("decision", "")])
        flow.append(_pdf_table(data))
    flow.append(PageBreak())

    # 5. Primary
    flow.append(Paragraph("Primary Analysis", h2))
    primary = next((r for r in session["results"]
                    if r.get("test_type") in _PRIMARY_TYPES and "error" not in r), None)
    if primary:
        _pdf_render_test(flow, primary, h2, body, session)
    else:
        flow.append(Paragraph("No primary inferential test ran successfully.", body))
    flow.append(PageBreak())

    # 6. Secondary
    secondary = [r for r in session["results"]
                 if r.get("test_type") in _SECONDARY_TYPES and "error" not in r]
    if secondary:
        flow.append(Paragraph("Secondary Analyses", h2))
        for r in secondary:
            flow.append(Paragraph(r.get("plan_name") or r.get("title", ""), h2))
            _pdf_render_test(flow, r, h2, body, session)
        flow.append(PageBreak())

    # 7. Figures
    if session.get("graph_paths"):
        flow.append(Paragraph("Figures", h2))
        for i, (path, caption) in enumerate(session["graph_paths"], 1):
            if not os.path.exists(path):
                continue
            try:
                flow.append(Image(path, width=5.5*inch, height=3.5*inch))
            except Exception:
                continue
            flow.append(Paragraph(f"<i>Figure {i}. {caption}</i>", body))
            flow.append(Spacer(1, 8))
        flow.append(PageBreak())

    # 8. Results narrative
    flow.append(Paragraph("Results Section", h2))
    flow.append(Paragraph("Copy the text below directly into your paper's Results section.", italic))
    flow.append(Paragraph(build_results_narrative(session, session["results"]), body))
    flow.append(PageBreak())

    # 9. Methods
    flow.append(Paragraph("Statistical Analysis", h2))
    flow.append(Paragraph("Copy the text below directly into your paper's Methods section.", italic))
    flow.append(Paragraph(build_methods_paragraph(session, session["results"]), body))
    flow.append(PageBreak())

    # 10. Limitations
    flow.append(Paragraph("Limitations and Notes", h2))
    lims = collect_limitations(session, session["results"])
    if lims:
        for l in lims:
            flow.append(Paragraph(f"• {l}", body))
    else:
        flow.append(Paragraph("No major assumption violations or warnings detected.", body))

    pdf.build(flow)
    return out.getvalue()


def _pdf_table(data: List[List[str]]) -> Table:
    tbl = Table(data, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, colors.black),
        ("LINEABOVE", (0, 0), (-1, 0), 1.0, colors.black),
        ("LINEBELOW", (0, -1), (-1, -1), 1.0, colors.black),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
    ]))
    return tbl


def _pdf_render_test(flow, result, h2, body, session=None) -> None:
    variables = (session or {}).get("variables", {}) if session else {}
    if result.get("plan_reason"):
        flow.append(Paragraph(f"<i>Why this test: {result['plan_reason']}</i>", body))
    rows = result.get("rows") or []
    test_type = result.get("test_type", "")

    if test_type == "diagnostic_accuracy" or _detect_diagnostic(result):
        TP, TN = int(result.get("TP", 0)), int(result.get("TN", 0))
        FP, FN = int(result.get("FP", 0)), int(result.get("FN", 0))
        n = TP + TN + FP + FN
        sens = TP/(TP+FN) if (TP+FN) else 0
        spec = TN/(TN+FP) if (TN+FP) else 0
        ppv = TP/(TP+FP) if (TP+FP) else 0
        npv = TN/(TN+FN) if (TN+FN) else 0
        acc = (TP+TN)/n if n else 0
        auc = _safe_float(result.get("auc")) or 0
        data = [["Measure", "Value"],
                ["Sensitivity", _fmt(sens)], ["Specificity", _fmt(spec)],
                ["PPV", _fmt(ppv)], ["NPV", _fmt(npv)],
                ["Accuracy", _fmt(acc)], ["AUC", _fmt(auc)]]
        flow.append(_pdf_table(data))
    elif test_type in ("logistic_regression", "cox_regression", "linear_regression",
                       "ordinal_logistic", "count_regression") or _detect_regression_rows(rows):
        is_or = any("OR" in r for r in rows if isinstance(r, dict))
        is_hr = any("HR" in r for r in rows if isinstance(r, dict))
        metric_label = "OR" if is_or else ("HR" if is_hr else "Estimate")
        data = [["Variable", metric_label, "95% CI", "p-value"]]
        for item in rows:
            if not isinstance(item, dict):
                continue
            metric = _first_present(item, "OR", "HR", "coef", "beta", "estimate")
            ci_lo = _safe_float(_first_present(item, "CI_lo", "ci_lo", "lower"))
            ci_hi = _safe_float(_first_present(item, "CI_hi", "ci_hi", "upper"))
            ci_str = f"{ci_lo:.3f} – {ci_hi:.3f}" if ci_lo is not None and ci_hi is not None else "—"
            data.append([str(item.get("variable", "")), _fmt(metric), ci_str,
                         fmt_p(item.get("p") or item.get("p_value"))])
        flow.append(_pdf_table(data))
    elif test_type in _PRIMARY_TYPES:
        stat = _first_present(result, "statistic", "t", "U", "F", "z", "chi2", "W")
        df_v = _first_present(result, "df", "df1")
        p = _safe_float(result.get("p") or result.get("p_value"))
        eff = _first_present(result, "effect_size", "cohens_d", "eta_squared",
                             "rank_biserial", "cramers_v", "phi", "r")
        eff_lbl = result.get("effect_label") or _guess_effect_label(result)
        data = [["Test", "Statistic", "df", "p-value", "Effect size"],
                [result.get("plan_name") or result.get("title", ""),
                 _fmt(stat), str(df_v) if df_v is not None else "—",
                 fmt_p(p), f"{eff_lbl} = {_fmt(eff)}" if eff is not None else "—"]]
        flow.append(_pdf_table(data))
    else:
        if rows:
            data = [["Statistic", "Value"]]
            for r in rows:
                if isinstance(r, dict):
                    data.append([str(r.get("label", "")), str(r.get("value", ""))])
            flow.append(_pdf_table(data))
    if result.get("narrative"):
        flow.append(Spacer(1, 4))
        flow.append(Paragraph(_sanitize_text(result["narrative"], variables), body))
    flow.append(Spacer(1, 8))


def to_xlsx(entry, results: Dict[str, Any], assignment: Dict[str, Any]) -> bytes:
    session = _build_session(entry, results, assignment)
    wb = Workbook()
    s = wb.active; s.title = "Cover"
    for k, v in (("Study", session["objective"]), ("Date", session["analysis_date"]),
                 ("Dataset", session["filename"]), ("Patients", session["n_rows"]),
                 ("Variables", session["n_cols"])):
        s.append([k, v])

    # Variable summary
    ws = wb.create_sheet("Variables")
    ws.append(["Variable", "Type", "Missing n", "Missing %"])
    for col, info in session["variables"].items():
        ws.append([info.get("display_name", col), info.get("type", ""),
                   info.get("missing_n", 0), f'{info.get("missing_pct", 0):.1f}%'])

    # Table 1
    ws = wb.create_sheet("Table 1")
    t1 = session.get("table_one") or {}
    if t1.get("headers"):
        ws.append(list(t1["headers"]))
        for row in t1.get("rows") or []:
            dname = session["variables"].get(row.get("variable", ""), {}).get(
                "display_name") or clean_display_name(row.get("variable", ""))
            ws.append([dname, row.get("type", "")] + list(row.get("cells") or []))

    # Normality
    if session["normality_results"]:
        ws = wb.create_sheet("Normality")
        ws.append(["Variable", "Test", "Statistic", "p-value", "Decision"])
        for v, r in session["normality_results"].items():
            dname = session["variables"].get(v, {}).get("display_name") or clean_display_name(v)
            ws.append([dname, r.get("test", ""), r.get("stat"), r.get("p"), r.get("decision", "")])

    # Each test on its own sheet
    for t in session["results"]:
        title = (t.get("plan_name") or t.get("title") or "Test")[:30]
        ws = wb.create_sheet(title)
        ws.append(["Statistic", "Value"])
        for r in t.get("rows") or []:
            if isinstance(r, dict):
                ws.append([r.get("label", ""), r.get("value", "")])
        ws.append([])
        ws.append(["Narrative"]); ws.append([t.get("narrative", "")])

    # Narrative & methods sheet
    ws = wb.create_sheet("Narrative")
    ws.append(["Results section"]); ws.append([build_results_narrative(session, session["results"])])
    ws.append([]); ws.append(["Methods section"])
    ws.append([build_methods_paragraph(session, session["results"])])
    ws.append([]); ws.append(["Limitations"])
    for l in collect_limitations(session, session["results"]):
        ws.append([l])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


EXPORTERS = {
    "word":  (to_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "pdf":   (to_pdf,  "application/pdf", "pdf"),
    "excel": (to_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
}


# ===========================================================================
# Correlation Study — Thesis Chapter Word Doc (T007)
# ===========================================================================


def _add_table_from_data(
    doc: Document,
    headers: List[str],
    rows: List[List[str]],
    bold_last: bool = False,
) -> None:
    """Add a formatted table to doc from headers + rows lists."""
    if not headers:
        return
    n_cols = len(headers)
    table = doc.add_table(rows=1, cols=n_cols)
    table.style = "Table Grid"
    hdr_cells = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr_cells[i].text = str(h)
        for run in hdr_cells[i].paragraphs[0].runs:
            run.bold = True
        hdr_cells[i].paragraphs[0].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Shade header row navy
    for cell in hdr_cells:
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), "17375E")
        tcPr.append(shd)
        for run in cell.paragraphs[0].runs:
            run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    for r_idx, row_data in enumerate(rows):
        is_total = (row_data[0] if row_data else "").strip().lower() == "total"
        r = table.add_row().cells
        for i, val in enumerate(row_data[:n_cols]):
            r[i].text = str(val)
            if is_total or (bold_last and r_idx == len(rows) - 1):
                for run in r[i].paragraphs[0].runs:
                    run.bold = True
        # Alternate shading
        if r_idx % 2 == 0 and not is_total:
            for cell in r:
                tc = cell._tc
                tcPr = tc.get_or_add_tcPr()
                shd = OxmlElement("w:shd")
                shd.set(qn("w:val"), "clear")
                shd.set(qn("w:color"), "auto")
                shd.set(qn("w:fill"), "DCE6F1")
                tcPr.append(shd)


def _inline_graph(doc: Document, graph_uri: Optional[str], caption: str) -> None:
    """Decode a base64 PNG data URI and insert it inline with a caption."""
    if not graph_uri:
        return
    try:
        if "," in graph_uri:
            _, b64 = graph_uri.split(",", 1)
        else:
            b64 = graph_uri
        img_bytes = base64.b64decode(b64)
        img_stream = io.BytesIO(img_bytes)
        doc.add_picture(img_stream, width=Inches(5.5))
        cap = doc.add_paragraph(caption)
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if cap.runs:
            cap.runs[0].italic = True
            cap.runs[0].font.size = Pt(9)
    except Exception:
        doc.add_paragraph(f"[Figure: {caption}]")


def generate_correlation_chapter_word(
    entry: Any,
    corr_results: Dict[str, Any],
) -> bytes:
    """Generate a thesis-chapter Word document for a correlation study.

    Structure:
      - Cover (title, dataset, date, n)
      - Statistical Methods section
      - For each predictor variable:
          * Bold heading: "Association of [Predictor] with [Outcome]"
          * Table (crosstab with row-% for categorical; descriptive for continuous)
          * Figure (stacked bar or box plot)
          * Interpretation paragraph
      - Summary table (all variables, sorted by p-value ascending; p<0.05 rows bold)
    """
    doc = Document()

    # Global style — Times New Roman 12
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    from docx.oxml.ns import qn as _qn
    from docx.oxml import OxmlElement as _OXE

    def _set_font(para):
        for run in para.runs:
            run.font.name = "Times New Roman"
            run.font.size = Pt(12)

    # ── Cover ──────────────────────────────────────────────────────────────
    outcome_col = corr_results.get("outcome_col", "Outcome")
    filename = getattr(entry, "filename", None) or (entry.meta.get("filename") if hasattr(entry, "meta") else "")
    n_rows = len(entry.df) if hasattr(entry, "df") else "?"
    today = datetime.date.today().strftime("%d %B %Y")

    title_p = doc.add_heading("Correlation Analysis", 0)
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for label, value in [
        ("Dataset", filename or "Unknown"),
        ("Outcome Variable", outcome_col),
        ("Patients", str(n_rows)),
        ("Date", today),
        ("Generated by", "MedRAS — Medical Research Acceleration System"),
    ]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(f"{label}: ")
        run.bold = True
        p.add_run(str(value))

    doc.add_page_break()

    # ── Statistical Methods ────────────────────────────────────────────────
    doc.add_heading("Statistical Methods", 1)
    methods_text = corr_results.get("methods_text", "")
    if methods_text:
        mp = doc.add_paragraph(methods_text)
        _set_font(mp)

    doc.add_page_break()

    # ── Per-variable sections ──────────────────────────────────────────────
    pair_results = corr_results.get("pairs") or []
    fig_num = 1
    table_num = 1

    for pr in pair_results:
        predictor = pr.get("predictor", "")
        pred_display = clean_display_name(predictor)
        outcome_display = clean_display_name(outcome_col)
        test_result = pr.get("test_result") or {}

        # Skip failed pairs silently
        if "error" in test_result:
            continue

        # Bold heading
        hdg = doc.add_heading(
            f"Association of {pred_display} with {outcome_display}", 2
        )
        for run in hdg.runs:
            run.bold = True

        # Table
        table_data = pr.get("table_data") or {"headers": [], "rows": []}
        headers = table_data.get("headers") or []
        rows = table_data.get("rows") or []

        pred_type = pr.get("predictor_type", "nominal")
        if pred_type == "scale":
            table_caption = (
                f"Table {table_num}. Descriptive statistics for {pred_display} "
                f"by {outcome_display} groups."
            )
        else:
            table_caption = (
                f"Table {table_num}. Distribution of {pred_display} "
                f"by {outcome_display} (n, row %)."
            )

        if headers and rows:
            _add_table_from_data(doc, headers, rows)
            cap_p = doc.add_paragraph(table_caption)
            cap_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            if cap_p.runs:
                cap_p.runs[0].italic = True
                cap_p.runs[0].font.size = Pt(9)
            table_num += 1

        doc.add_paragraph()  # spacer

        # Figure
        graph_uri = pr.get("graph_uri")
        if graph_uri:
            if pred_type == "scale":
                fig_caption = (
                    f"Figure {fig_num}. Box plot of {pred_display} "
                    f"by {outcome_display}."
                )
            else:
                fig_caption = (
                    f"Figure {fig_num}. Stacked bar chart showing distribution "
                    f"of {pred_display} by {outcome_display}."
                )
            _inline_graph(doc, graph_uri, fig_caption)
            fig_num += 1

        doc.add_paragraph()

        # Interpretation paragraph
        interpretation = pr.get("interpretation", "")
        if interpretation:
            interp_p = doc.add_paragraph(interpretation)
            _set_font(interp_p)

        doc.add_page_break()

    # ── Summary table ──────────────────────────────────────────────────────
    doc.add_heading("Summary of Associations", 1)
    summary_intro = doc.add_paragraph(
        f"The table below summarises the association of all predictor variables with {outcome_display}, "
        "sorted by p-value in ascending order. Variables with p < 0.05 are highlighted in bold."
    )
    _set_font(summary_intro)
    doc.add_paragraph()

    summary = corr_results.get("summary_table") or []
    if summary:
        n_cols = 4
        tbl = doc.add_table(rows=1, cols=n_cols)
        tbl.style = "Table Grid"
        hdrs = ["Variable", "Test Used", "Statistic", "p-value"]
        hdr_cells = tbl.rows[0].cells
        for i, h in enumerate(hdrs):
            hdr_cells[i].text = h
            for run in hdr_cells[i].paragraphs[0].runs:
                run.bold = True
            hdr_cells[i].paragraphs[0].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        # Shade header
        for cell in hdr_cells:
            tc = cell._tc
            tcPr = tc.get_or_add_tcPr()
            shd = OxmlElement("w:shd")
            shd.set(qn("w:val"), "clear")
            shd.set(qn("w:color"), "auto")
            shd.set(qn("w:fill"), "17375E")
            tcPr.append(shd)
            for run in cell.paragraphs[0].runs:
                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        for item in summary:
            r = tbl.add_row().cells
            r[0].text = clean_display_name(item.get("predictor", ""))
            r[1].text = item.get("test", "")
            r[2].text = item.get("stat", "—")
            r[3].text = item.get("p", "—")
            if item.get("significant"):
                for cell in r:
                    for run in cell.paragraphs[0].runs:
                        run.bold = True

    cap = doc.add_paragraph(
        f"Table {table_num}. Summary of associations with {outcome_display} sorted by p-value. "
        "Bold rows indicate p < 0.05."
    )
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if cap.runs:
        cap.runs[0].italic = True
        cap.runs[0].font.size = Pt(9)

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
