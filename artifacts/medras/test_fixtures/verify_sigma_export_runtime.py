"""Directly verify every Sigma export endpoint against normalized Step 7 state."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pandas as pd
from docx import Document
from fastapi import HTTPException
from openpyxl import load_workbook

from app.api import stats


PNG_1X1 = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


class FakeEntry:
    def __init__(self):
        self.df = pd.DataFrame({
            "PR": ["Positive", "Negative"] * 10,
            "ER": ["Positive", "Positive", "Negative", "Negative"] * 5,
        })
        self.meta = {
            "filename": "export-runtime.csv",
            "assignment": {"outcome": "PR", "group": None, "covariates": []},
            "classifications": [
                {"column": "PR", "detected_type": "nominal"},
                {"column": "ER", "detected_type": "nominal"},
            ],
            "cleanup_notes": {"PR": "Whitespace normalized."},
            "quality_log": {"reviewed": 1},
        }


def _results():
    return {
        "table_one": {
            "headers": ["Variable", "Type", "Overall"],
            "rows": [{"variable": "PR", "type": "n (%)", "cells": ["20 (100.0%)"]}],
        },
        "tests": [{
            "id": "association_0",
            "title": "ER vs PR: Chi-square test",
            "plan_name": "ER vs PR: Chi-square / Fisher's exact",
            "test_type": "chi_square",
            "analysis_family": "bivariate",
            "actual_test_used": "Chi-square test",
            "p": 0.04,
            "warning": "Sparse cells should be interpreted cautiously.",
            "tables": [{
                "title": "Test summary",
                "headers": ["Test used", "p-value", "Effect size"],
                "rows": [["Chi-square test", "p = 0.040", "Cramer's V = 0.30"]],
            }],
            "figures": [{"title": "ER by PR (%)", "png_data_uri": PNG_1X1}],
            "narrative": "ER was associated with PR.",
        }],
        "graphs": [],
        "methods_md": "Categorical associations used chi-square or Fisher as appropriate.",
        "results_md": "ER was associated with PR.",
    }


def _docx_text(blob: bytes) -> str:
    doc = Document(io.BytesIO(blob))
    text = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            text.extend(cell.text for cell in row.cells)
    return "\n".join(text)


async def _verify_endpoints():
    entry = FakeEntry()
    original_get = stats.dataset_store.get
    stats.dataset_store.get = lambda job_id: entry
    try:
        published = stats._publish_results(entry, "runtime-job", _results())
        result_id = published["export_metadata"]["result_id"]

        for missing_or_stale_id in (None, "stale-result-id"):
            try:
                await stats.export("runtime-job", "pdf", result_id=missing_or_stale_id)
                raise AssertionError("Missing/stale result_id should block export.")
            except HTTPException as exc:
                assert exc.status_code == 409
                detail = str(exc.detail).lower()
                if missing_or_stale_id is None:
                    assert "result_id" in detail
                else:
                    assert "stale" in detail

        cases = [
            ("word", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ("pdf", "application/pdf"),
            ("excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ]
        responses = {}
        for fmt, media_type in cases:
            response = await stats.export("runtime-job", fmt, result_id=result_id)
            assert response.media_type == media_type
            assert response.body
            assert "attachment;" in response.headers["content-disposition"]
            responses[fmt] = response.body

        chapter_word = await stats.export_chapter_v_word("runtime-job", result_id=result_id)
        chapter_pdf = await stats.export_chapter_v_pdf("runtime-job", result_id=result_id)
        assert chapter_word.body and chapter_word.media_type.endswith("wordprocessingml.document")
        assert chapter_pdf.body.startswith(b"%PDF")

        for blob in (responses["word"], chapter_word.body):
            text = _docx_text(blob)
            assert "Baseline Characteristics" in text
            assert "Test summary" in text
            assert "Chi-square test" in text
            assert "ER by PR (%)" in text
            assert "Data Cleaning Log" in text
            assert "No primary inferential test ran successfully" not in text

        assert responses["pdf"].startswith(b"%PDF")
        assert len(responses["pdf"]) > 1000
        assert len(chapter_pdf.body) > 1000
        assert b"No primary inferential test ran successfully" not in responses["pdf"]
        assert b"No primary inferential test ran successfully" not in chapter_pdf.body

        wb = load_workbook(io.BytesIO(responses["excel"]))
        assert {"Table 1", "Data Cleaning Log", "Narrative"} <= set(wb.sheetnames)
        result_sheets = [
            name for name in wb.sheetnames
            if name not in {"Cover", "Variables", "Data Cleaning Log", "Table 1", "Narrative"}
        ]
        assert result_sheets
        assert all(":" not in name and "/" not in name for name in result_sheets)
        values = [
            value
            for row in wb[result_sheets[0]].iter_rows(values_only=True)
            for value in row if value is not None
        ]
        assert "Test summary" in values
        assert "ER by PR (%)" in values
    finally:
        stats.dataset_store.get = original_get


def main():
    asyncio.run(_verify_endpoints())
    root = Path(__file__).resolve().parents[1]
    js = (root / "public/js/analysis.js").read_text(encoding="utf-8")
    html = (root / "public/analysis.html").read_text(encoding="utf-8")
    for fmt in ("word", "pdf", "excel"):
        assert f'data-action="download" data-format="{fmt}"' in html
    assert 'data-action="download-chapter-v" data-format="word"' in html
    assert 'data-action="download-chapter-v" data-format="pdf"' in html
    assert "exportErrorMessage(res)" in js
    assert "downloadBlob(blob" in js
    print("Sigma export runtime/completeness verification passed.")


if __name__ == "__main__":
    main()
