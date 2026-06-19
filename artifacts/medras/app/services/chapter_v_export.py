"""Render thesis Chapter V from Sigma's thesis_analysis_blueprint.

This module deliberately consumes the blueprint contract instead of the raw
statistical result text.  Detailed statistical subtables remain available to
other exports, but the main thesis chapter stays doctor-readable.
"""

from __future__ import annotations

import base64
import io
from typing import Any, Dict, List, Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
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


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, (list, tuple)):
        return "; ".join(_text(item) for item in value if _text(item))
    if isinstance(value, dict):
        return "; ".join(f"{_label(k)}: {_text(v)}" for k, v in value.items() if _text(v))
    return str(value).strip()


def _label(value: Any) -> str:
    text = _text(value).replace("_", " ").strip()
    if not text:
        return ""
    acronyms = {"id": "ID", "roc": "ROC", "auc": "AUC", "pdf": "PDF", "docx": "DOCX"}
    words = [acronyms.get(part.lower(), part.capitalize()) for part in text.split()]
    return " ".join(words)


def _outcome_label_context(blueprint: Dict[str, Any]) -> Dict[str, Any]:
    display = _text(blueprint.get("primary_outcome"))
    raw_values = set()
    for section in blueprint.get("analysis_sections") or []:
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
    return {"display": display, "raw_values": sorted(raw_values, key=len, reverse=True)}


def _display_value(value: Any, label_ctx: Optional[Dict[str, Any]]) -> str:
    text = _text(value)
    if not label_ctx:
        return text
    display = _text(label_ctx.get("display"))
    if not display:
        return text
    for raw in label_ctx.get("raw_values") or []:
        text = text.replace(raw, display)
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
    if figure.get("detailed_report_only"):
        return False
    if str(figure.get("priority") or "").lower() == "detailed_report_only":
        return False
    if figure.get("optional") and not include_optional:
        return False
    return bool(figure.get("thesis_ready") or str(figure.get("priority") or "").lower() == "thesis_ready_primary")


def _section_tables(section: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [table for table in section.get("tables") or [] if _is_main_table(table)]


def _section_figures(section: Dict[str, Any], include_optional: bool = False) -> List[Dict[str, Any]]:
    return [figure for figure in section.get("figures") or [] if _is_main_figure(figure, include_optional)]


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


def _add_table_docx(doc: Document, payload: Dict[str, Any], caption_no: int, label_ctx: Optional[Dict[str, Any]] = None) -> int:
    headers, rows = _table_rows(payload)
    if not rows:
        return caption_no
    caption = _display_value(payload.get("title") or f"Table {caption_no}", label_ctx)
    _plain_docx_text(doc, f"Table {caption_no}. {caption}", style=None).runs[0].bold = True
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for idx, header in enumerate(headers):
        cell = table.rows[0].cells[idx]
        cell.text = _display_value(header, label_ctx)
        for run in cell.paragraphs[0].runs:
            run.bold = True
    for row in rows:
        cells = table.add_row().cells
        for idx, value in enumerate(row[:len(headers)]):
            cells[idx].text = _display_value(value, label_ctx)
    interpretation = _display_value(payload.get("interpretation"), label_ctx)
    if interpretation:
        _plain_docx_text(doc, interpretation)
    for warning in payload.get("warnings") or []:
        _plain_docx_text(doc, f"Caution: {_display_value(warning, label_ctx)}")
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
    if png:
        try:
            doc.add_picture(io.BytesIO(png), width=Inches(5.7))
        except Exception:
            _plain_docx_text(doc, "Graph preview not generated yet.")
    else:
        _plain_docx_text(doc, "Graph preview not generated yet.")
    caption = _display_value(figure.get("caption") or title, label_ctx)
    caption_para = doc.add_paragraph()
    caption_run = caption_para.add_run(f"Figure {figure_no}. {caption}")
    caption_run.italic = True
    interpretation = _display_value(figure.get("interpretation"), label_ctx)
    if interpretation:
        _plain_docx_text(doc, interpretation)
    doc.add_paragraph()
    return figure_no + 1


def _blueprint(results: Dict[str, Any]) -> Dict[str, Any]:
    blueprint = results.get("thesis_analysis_blueprint")
    if not isinstance(blueprint, dict) or not blueprint:
        raise ValueError("Chapter V export requires thesis_analysis_blueprint. Run analysis again before exporting.")
    return blueprint


def _study_summary(blueprint: Dict[str, Any], results: Dict[str, Any]) -> List[tuple[str, str]]:
    summary = dict(blueprint.get("study_summary") or {})
    metadata = dict(results.get("export_metadata") or {})
    rows = [
        ("Study design", _label(blueprint.get("study_design") or summary.get("study_design"))),
        ("Sample size", summary.get("sample_size") or summary.get("n") or ""),
        ("Primary outcome", blueprint.get("primary_outcome") or summary.get("primary_outcome") or ""),
        ("Domain/profile", summary.get("domain_profile") or metadata.get("domain_profile") or ""),
        ("Dataset ID", metadata.get("dataset_id") or ""),
        ("Result ID", metadata.get("result_id") or ""),
        ("Generated at", metadata.get("generated_at") or ""),
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


def generate_docx(results: Dict[str, Any], *, include_optional_figures: bool = False) -> bytes:
    blueprint = _blueprint(results)
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

    _add_heading(doc, "5.3 Baseline and Study Characteristics", 1)
    baseline_sections = [
        section for section in _main_sections(blueprint)
        if section.get("section_id") in {
            "baseline_characteristics",
            "clinical_study_characteristics",
            "immunophenotype_characteristics",
            "marker_outcome_components",
            "descriptive_results",
        }
    ]
    if not baseline_sections:
        _plain_docx_text(doc, "Baseline and study characteristics were not available in the blueprint.")
    for section in baseline_sections:
        _add_heading(doc, section.get("title") or "Study Characteristics", 2)
        if _text(section.get("interpretation")):
            _plain_docx_text(doc, _display_value(section.get("interpretation"), label_ctx))
        for table in _section_tables(section):
            table_no = _add_table_docx(doc, table, table_no, label_ctx)

    _add_heading(doc, "5.4 Primary Outcome Distribution", 1)
    outcome_sections = [section for section in _main_sections(blueprint) if section.get("section_id") == "primary_outcome_distribution"]
    if outcome_sections:
        for section in outcome_sections:
            _plain_docx_text(doc, section.get("interpretation") or "")
            for table in _section_tables(section):
                table_no = _add_table_docx(doc, table, table_no, label_ctx)
            for fig in _section_figures(section, include_optional_figures)[:2]:
                figure_no = _add_figure_docx(doc, fig, figure_no, label_ctx)
    else:
        _plain_docx_text(doc, "Primary outcome distribution was not available in the blueprint.")

    _add_heading(doc, "5.5 Inferential Analysis / Bivariate Associations", 1)
    inferential_ids = {
        "bivariate_associations", "correlation_analysis", "regression_adjusted_analysis",
        "diagnostic_accuracy", "reliability_agreement", "survival_analysis",
        "repeated_measures", "other_analyses",
    }
    inferential_sections = [section for section in _main_sections(blueprint) if section.get("section_id") in inferential_ids]
    if not inferential_sections:
        _plain_docx_text(doc, "No thesis-ready inferential analysis tables were available.")
    for section in inferential_sections:
        _add_heading(doc, section.get("title") or "Inferential Analysis", 2)
        if _text(section.get("interpretation")):
            _plain_docx_text(doc, _display_value(section.get("interpretation"), label_ctx))
        for table in _section_tables(section):
            table_no = _add_table_docx(doc, table, table_no, label_ctx)
        for fig in _section_figures(section, include_optional_figures)[:4]:
            figure_no = _add_figure_docx(doc, fig, figure_no, label_ctx)

    _add_heading(doc, "5.6 Significant Findings Summary", 1)
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
                    row.get("key_finding") or "",
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

    _add_heading(doc, "5.7 Warnings and Interpretation Notes", 1)
    _add_warnings_docx(doc, blueprint)

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _pdf_escape(value: Any) -> str:
    return _text(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _pdf_table(payload: Dict[str, Any], label_ctx: Optional[Dict[str, Any]] = None) -> Table:
    headers, rows = _table_rows(payload)
    data = [[_pdf_escape(_display_value(h, label_ctx)) for h in headers]] + [
        [_pdf_escape(_display_value(cell, label_ctx)) for cell in row] for row in rows
    ]
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E9EEF7")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def generate_pdf(results: Dict[str, Any], *, include_optional_figures: bool = False) -> bytes:
    blueprint = _blueprint(results)
    label_ctx = _outcome_label_context(blueprint)
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=48, bottomMargin=48)
    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    body = styles["BodyText"]
    small = ParagraphStyle("Small", parent=body, fontSize=8, leading=10)
    flow: List[Any] = []

    flow.append(Paragraph("CHAPTER V<br/>OBSERVATION AND RESULTS", styles["Title"]))
    flow.append(Spacer(1, 10))
    flow.append(Paragraph("5.1 Study Summary", h1))
    for label, value in _study_summary(blueprint, results):
        flow.append(Paragraph(f"<b>{_pdf_escape(label)}:</b> {_pdf_escape(value)}", body))
    flow.append(Paragraph("5.2 Statistical Methods", h1))
    flow.append(Paragraph(_pdf_escape(blueprint.get("methods_text") or "Statistical methods were generated from the executed Sigma analysis plan."), body))

    section_map = [
        ("5.3 Baseline and Study Characteristics", {"baseline_characteristics", "clinical_study_characteristics", "immunophenotype_characteristics", "marker_outcome_components", "descriptive_results"}),
        ("5.4 Primary Outcome Distribution", {"primary_outcome_distribution"}),
        ("5.5 Inferential Analysis / Bivariate Associations", {"bivariate_associations", "correlation_analysis", "regression_adjusted_analysis", "diagnostic_accuracy", "reliability_agreement", "survival_analysis", "repeated_measures", "other_analyses"}),
    ]
    for heading, section_ids in section_map:
        flow.append(Paragraph(heading, h1))
        for section in _main_sections(blueprint):
            if section.get("section_id") not in section_ids:
                continue
            flow.append(Paragraph(_pdf_escape(section.get("title")), h2))
            if _text(section.get("interpretation")):
                flow.append(Paragraph(_pdf_escape(_display_value(section.get("interpretation"), label_ctx)), body))
            for table in _section_tables(section):
                flow.append(Paragraph(f"<b>{_pdf_escape(_display_value(table.get('title'), label_ctx))}</b>", small))
                flow.append(_pdf_table(table, label_ctx))
                flow.append(Spacer(1, 6))
            for fig in _section_figures(section, include_optional_figures)[:4]:
                png = _strip_data_uri(_text(fig.get("png_data_uri")))
                if png:
                    try:
                        flow.append(Image(io.BytesIO(png), width=5.5 * inch, height=3.4 * inch))
                    except Exception:
                        flow.append(Paragraph("Graph preview not generated yet.", body))
                else:
                    flow.append(Paragraph("Graph preview not generated yet.", body))
                flow.append(Paragraph(f"<i>{_pdf_escape(_display_value(fig.get('caption') or fig.get('title'), label_ctx))}</i>", small))
    flow.append(Paragraph("5.6 Significant Findings Summary", h1))
    if blueprint.get("significant_findings"):
        flow.append(_pdf_table({
            "columns": [
                "Variable / parameter", "Key finding", "Test statistic", "p-value",
                "Adjusted p-value", "Test applied", "Effect size", "Notes/warnings",
            ],
            "rows": [
                [
                    _display_value(row.get("variable") or "", label_ctx),
                    row.get("key_finding") or "",
                    row.get("test_statistic") or "",
                    row.get("p_value") or "",
                    row.get("adjusted_p_value") or "",
                    row.get("test_applied") or "",
                    row.get("effect_size") or "",
                    row.get("notes_warnings") or "",
                ]
                for row in blueprint.get("significant_findings") or []
            ],
        }, label_ctx))
    else:
        flow.append(Paragraph("No final thesis significant findings were identified among the completed tests.", body))
    flow.append(Paragraph("5.7 Warnings and Interpretation Notes", h1))
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
