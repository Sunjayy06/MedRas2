"""Export the run-analysis results to Word / PDF / Excel (Step 8)."""

from __future__ import annotations

import base64
import io
from typing import Any, Dict, List

import pandas as pd
from docx import Document
from docx.shared import Inches, Pt
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from reportlab.lib import colors


def _strip_data_uri(data_uri: str) -> bytes:
    if not data_uri:
        return b""
    if "," in data_uri:
        return base64.b64decode(data_uri.split(",", 1)[1])
    return base64.b64decode(data_uri)


# ---------------------------------------------------------------------------
# Word (.docx)
# ---------------------------------------------------------------------------


def to_docx(results: Dict[str, Any], assignment: Dict[str, Any]) -> bytes:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    doc.add_heading("MedRAS — Statistical Analysis Report", level=0)
    doc.add_paragraph(
        f"Outcome: {assignment.get('outcome', '—')}    "
        f"Group: {assignment.get('group') or 'none'}"
    )

    doc.add_heading("Methods", level=1)
    doc.add_paragraph(results.get("methods_md") or "")

    doc.add_heading("Table 1 — Baseline characteristics", level=1)
    t1 = results.get("table_one") or {}
    headers = t1.get("headers") or []
    rows = t1.get("rows") or []
    if headers:
        table = doc.add_table(rows=1 + len(rows), cols=len(headers))
        table.style = "Light Grid Accent 1"
        for i, h in enumerate(headers):
            table.rows[0].cells[i].text = str(h)
        for r_idx, row in enumerate(rows, start=1):
            cells = [row.get("variable", ""), row.get("type", "")] + (row.get("cells") or [])
            for c_idx in range(len(headers)):
                table.rows[r_idx].cells[c_idx].text = str(cells[c_idx]) if c_idx < len(cells) else ""

    doc.add_heading("Results", level=1)
    for t in results.get("tests") or []:
        doc.add_heading(t.get("title", "Test"), level=2)
        if t.get("rows"):
            tab = doc.add_table(rows=len(t["rows"]), cols=2)
            tab.style = "Light List Accent 1"
            for i, row in enumerate(t["rows"]):
                tab.rows[i].cells[0].text = str(row.get("label", ""))
                tab.rows[i].cells[1].text = str(row.get("value", ""))
        doc.add_paragraph(t.get("narrative", ""))

    doc.add_heading("Narrative", level=1)
    doc.add_paragraph(results.get("results_md") or "")

    # Embed graphs.
    for g in results.get("graphs") or []:
        doc.add_heading(g.get("title", ""), level=2)
        png_bytes = _strip_data_uri(g.get("png_data_uri") or "")
        if png_bytes:
            doc.add_picture(io.BytesIO(png_bytes), width=Inches(5.5))

    if results.get("forest_plot"):
        doc.add_heading("Forest plot", level=2)
        doc.add_picture(io.BytesIO(_strip_data_uri(results["forest_plot"])), width=Inches(6))

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def to_pdf(results: Dict[str, Any], assignment: Dict[str, Any]) -> bytes:
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=36, rightMargin=36,
                            topMargin=48, bottomMargin=48)
    styles = getSampleStyleSheet()
    flowables: List[Any] = []
    flowables.append(Paragraph("MedRAS — Statistical Analysis Report", styles["Title"]))
    flowables.append(Paragraph(
        f"<b>Outcome:</b> {assignment.get('outcome','—')} &nbsp; "
        f"<b>Group:</b> {assignment.get('group') or 'none'}",
        styles["Normal"]))
    flowables.append(Spacer(1, 12))

    flowables.append(Paragraph("<b>Methods</b>", styles["Heading2"]))
    flowables.append(Paragraph(results.get("methods_md") or "", styles["BodyText"]))
    flowables.append(Spacer(1, 8))

    t1 = results.get("table_one") or {}
    if (t1.get("headers") or []) and (t1.get("rows") or []):
        flowables.append(Paragraph("<b>Table 1 — Baseline characteristics</b>", styles["Heading2"]))
        data = [t1["headers"]]
        for row in t1["rows"]:
            data.append(
                [row.get("variable", ""), row.get("type", "")] + (row.get("cells") or [])
            )
        tbl = Table(data, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#103a6e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        flowables.append(tbl)
        flowables.append(Spacer(1, 12))

    flowables.append(Paragraph("<b>Results</b>", styles["Heading2"]))
    for t in results.get("tests") or []:
        flowables.append(Paragraph(f"<b>{t.get('title','')}</b>", styles["Heading3"]))
        if t.get("rows"):
            data = [["", ""]] + [[r.get("label",""), r.get("value","")] for r in t["rows"]]
            tbl = Table(data, colWidths=[160, 240])
            tbl.setStyle(TableStyle([("GRID", (0,0), (-1,-1), 0.25, colors.grey),
                                     ("FONTSIZE", (0,0), (-1,-1), 8)]))
            flowables.append(tbl)
            flowables.append(Spacer(1, 6))
        flowables.append(Paragraph(t.get("narrative",""), styles["BodyText"]))
        flowables.append(Spacer(1, 8))

    for g in results.get("graphs") or []:
        flowables.append(PageBreak())
        flowables.append(Paragraph(f"<b>{g.get('title','')}</b>", styles["Heading3"]))
        png_bytes = _strip_data_uri(g.get("png_data_uri") or "")
        if png_bytes:
            flowables.append(Image(io.BytesIO(png_bytes), width=420, height=300))

    if results.get("forest_plot"):
        flowables.append(PageBreak())
        flowables.append(Paragraph("<b>Forest plot</b>", styles["Heading3"]))
        flowables.append(Image(io.BytesIO(_strip_data_uri(results["forest_plot"])),
                               width=460, height=320))

    doc.build(flowables)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------


def to_xlsx(results: Dict[str, Any], assignment: Dict[str, Any]) -> bytes:
    wb = Workbook()
    s = wb.active
    s.title = "Summary"
    s.append(["MedRAS — Statistical Analysis"])
    s.append(["Outcome", assignment.get("outcome", "")])
    s.append(["Group", assignment.get("group") or "none"])
    s.append([])
    s.append(["Methods"])
    s.append([results.get("methods_md") or ""])

    t1 = results.get("table_one") or {}
    sheet = wb.create_sheet("Table 1")
    if t1.get("headers"):
        sheet.append(t1["headers"])
        for row in t1.get("rows") or []:
            sheet.append([row.get("variable", ""), row.get("type", "")] + (row.get("cells") or []))

    for t in results.get("tests") or []:
        title = (t.get("title") or "Test")[:30]
        ws = wb.create_sheet(title)
        ws.append(["Statistic", "Value"])
        for r in t.get("rows") or []:
            ws.append([r.get("label", ""), r.get("value", "")])
        ws.append([])
        ws.append(["Narrative"])
        ws.append([t.get("narrative", "")])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


EXPORTERS = {
    "word": (to_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "pdf":  (to_pdf,  "application/pdf", "pdf"),
    "excel": (to_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
}
