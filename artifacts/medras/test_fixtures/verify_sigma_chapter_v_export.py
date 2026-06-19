"""Verify Sigma Chapter V export is driven by thesis_analysis_blueprint.

Run:
    python -m test_fixtures.verify_sigma_chapter_v_export
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pandas as pd
from docx import Document

from app.api import stats
from app.services import chapter_v_export, export
from app.services.thesis_blueprint import build_thesis_analysis_blueprint


class FakeEntry:
    def __init__(self):
        self.df = pd.DataFrame({
            "Positive/ Negative": ["Yes", "No"] * 6,
            "Age": [42, 44, 51, 53, 55, 56, 60, 61, 63, 65, 67, 69],
            "ER": ["Positive", "Negative"] * 6,
            "PR": ["Positive", "Negative"] * 6,
            "Interpretation-site": ["Nuclear", "Cytoplasmic"] * 6,
            "Staining Result": ["Strong", "Weak"] * 6,
        })
        self.meta = {
            "filename": "chapter-v-fixture.xlsx",
            "domain_profile": "breast_pathology",
            "assignment": {"outcome": "Positive/ Negative"},
            "classifications": [
                {"column": "Positive/ Negative", "detected_type": "nominal"},
                {"column": "Age", "detected_type": "scale"},
                {"column": "ER", "detected_type": "nominal"},
                {"column": "PR", "detected_type": "nominal"},
                {"column": "Interpretation-site", "detected_type": "nominal"},
                {"column": "Staining Result", "detected_type": "ordinal"},
            ],
            "data_version": 0,
        }


def _docx_text(blob: bytes) -> str:
    doc = Document(io.BytesIO(blob))
    paragraphs = [p.text for p in doc.paragraphs]
    cells = [cell.text for table in doc.tables for row in table.rows for cell in row.cells]
    return "\n".join(paragraphs + cells)


def _representative_results() -> dict:
    classifications = [
        {"column": "Positive/ Negative", "detected_type": "nominal"},
        {"column": "Age", "detected_type": "scale"},
        {"column": "ER", "detected_type": "nominal"},
        {"column": "PR", "detected_type": "nominal"},
        {"column": "Interpretation-site", "detected_type": "nominal"},
        {"column": "Staining Result", "detected_type": "ordinal"},
    ]
    table_one = {
        "headers": ["Variable", "Type", "Overall"],
        "rows": [
            {"variable": "Positive/ Negative", "type": "n (%)", "cells": ["Yes: 9 (75.0%); No: 3 (25.0%)"]},
            {"variable": "Age", "type": "mean ± SD", "cells": ["57.2 ± 8.6"]},
            {"variable": "ER", "type": "n (%)", "cells": ["Positive: 6 (50.0%); Negative: 6 (50.0%)"]},
            {"variable": "PR", "type": "n (%)", "cells": ["Positive: 6 (50.0%); Negative: 6 (50.0%)"]},
            {"variable": "Interpretation-site", "type": "n (%)", "cells": ["Nuclear: 6 (50.0%); Cytoplasmic: 6 (50.0%)"]},
            {"variable": "Staining Result", "type": "n (%)", "cells": ["Strong: 6 (50.0%); Weak: 6 (50.0%)"]},
        ],
    }
    tests = [
        {
            "id": "age_by_outcome",
            "title": "Age by p27 expression status: Welch's t-test",
            "test_type": "welch_ttest",
            "analysis_family": "bivariate",
            "tables": [{
                "title": "Comparison of Age by p27 expression status",
                "headers": ["Group", "n", "Mean ± SD", "Test statistic", "p-value", "Adjusted p-value", "Test applied", "Effect size", "Warnings"],
                "rows": [["Positive", "9", "56.1 ± 8.0", "t = 1.20", "p = 0.240", "p = 0.300", "Welch's t-test", "Cohen's d = 0.42", "-"]],
            }],
            "figures": [],
        },
        {
            "id": "er_by_outcome",
            "title": "ER vs p27 expression status: Chi-square test",
            "test_type": "chi_square",
            "analysis_family": "bivariate",
            "tables": [{
                "title": "Association of p27 expression status with ER",
                "headers": ["Predictor category", "Positive n (%)", "Negative n (%)", "p-value", "Adjusted p-value", "Test applied", "Effect size", "Warnings"],
                "rows": [["Positive", "6 (66.7%)", "0 (0.0%)", "p = 0.005", "p = 0.018", "Chi-square test", "Cramer's V = 0.46", "-"]],
            }],
            "figures": [],
        },
    ]
    significant_findings = [
        {
            "variable": "ER vs Positive/ Negative",
            "key_finding": "ER status was associated with the primary outcome.",
            "test_statistic": "chi-square = 8.00",
            "p_value": "p = 0.005",
            "adjusted_p_value": "p = 0.018",
            "test_applied": "Chi-square test",
            "effect_size": "Cramer's V = 0.46",
            "notes_warnings": "-",
        },
        {
            "variable": "PR vs Positive/ Negative",
            "key_finding": "PR status was associated with the primary outcome.",
            "test_statistic": "chi-square = 9.30",
            "p_value": "p = 0.002",
            "adjusted_p_value": "p = 0.012",
            "test_applied": "Chi-square test",
            "effect_size": "Cramer's V = 0.50",
            "notes_warnings": "-",
        },
        {
            "variable": "Interpretation-site vs Positive/ Negative",
            "key_finding": "Marker component association.",
            "test_statistic": "chi-square = 7.00",
            "p_value": "p = 0.008",
            "adjusted_p_value": "p = 0.020",
            "test_applied": "Chi-square test",
            "effect_size": "Cramer's V = 0.44",
            "notes_warnings": "-",
        },
        {
            "variable": "Staining Result vs Positive/ Negative",
            "key_finding": "Marker component association.",
            "test_statistic": "chi-square = 7.10",
            "p_value": "p = 0.007",
            "adjusted_p_value": "p = 0.020",
            "test_applied": "Chi-square test",
            "effect_size": "Cramer's V = 0.45",
            "notes_warnings": "-",
        },
    ]
    blueprint = build_thesis_analysis_blueprint(
        df_shape=(12, 6),
        classifications=classifications,
        assignment={"outcome": "Positive/ Negative"},
        table_one=table_one,
        tests=tests,
        graphs=[],
        significant_findings=significant_findings,
        methods_text=(
            "Descriptive statistics were used for baseline variables. Welch's t-test "
            "and chi-square tests were used for completed bivariate analyses. "
            "A p-value threshold of 0.05 was used."
        ),
        results_narrative="ER and PR were significantly associated with p27 expression status.",
        session={
            "study_type": "association",
            "domain_profile": "breast_pathology",
            "main_marker": "p27",
            "main_outcome_concept": "p27 expression status",
            "analysis_excluded_columns": ["positive_nodes"],
        },
        plan={"debug": {"eligible_predictor_count": 4, "bivariate_test_count": 2}},
    )
    blueprint["tables"].append({
        "table_id": "internal_observed",
        "title": "Observed counts",
        "table_type": "internal_detail",
        "columns": ["A", "B"],
        "rows": [["x", "y"]],
        "thesis_ready": True,
        "priority": "detailed_report_only",
        "detailed_report_only": True,
        "warnings": [],
    })
    blueprint["figures"].append({
        "figure_id": "internal_detail_figure",
        "title": "Internal detailed figure",
        "graph_type": "bar_chart",
        "caption": "Internal detailed figure.",
        "thesis_ready": True,
        "priority": "detailed_report_only",
        "optional": True,
        "detailed_report_only": True,
        "warnings": [],
    })
    return {
        "table_one": table_one,
        "tests": tests,
        "significant_findings": significant_findings,
        "thesis_analysis_blueprint": blueprint,
        "export_metadata": {
            "dataset_id": "chapter-v-job",
            "result_id": "chapter-v-result",
            "analysis_version": 1,
            "generated_at": "2026-06-20T00:00:00+00:00",
            "domain_profile": "breast_pathology",
        },
    }


def verify_service_docx() -> None:
    results = _representative_results()
    blob = chapter_v_export.generate_docx(results)
    assert blob and len(blob) > 1000
    text = _docx_text(blob)
    assert "CHAPTER V" in text
    assert "OBSERVATION AND RESULTS" in text
    assert "5.1 Study Summary" in text
    assert "5.2 Statistical Methods" in text
    assert "5.3 Baseline and Study Characteristics" in text
    assert "5.5 Inferential Analysis / Bivariate Associations" in text
    assert "5.6 Significant Findings Summary" in text
    assert "p27 expression status" in text
    assert "Positive: 9 (75.0%)" in text
    assert "No:" not in text and "Yes:" not in text
    assert "Variable / parameter" in text
    assert "p-value" in text and "Adjusted p-value" in text
    assert "ER vs p27 expression status" in text
    assert "PR vs p27 expression status" in text
    final_section = text.split("5.6 Significant Findings Summary", 1)[1].split("5.7 Warnings", 1)[0]
    assert "Interpretation-site" not in final_section
    assert "Staining Result" not in final_section
    assert "Observed counts" not in text
    assert "Expected counts" not in text
    assert "Row percentages" not in text
    assert "Column percentages" not in text
    assert "section_id" not in text and "source_result_id" not in text
    assert "cross_sectional_association" not in text
    assert "Internal detailed figure" not in text

    regular_word = export.to_docx(FakeEntry(), results, {"outcome": "Positive/ Negative"})
    regular_text = _docx_text(regular_word)
    assert "CHAPTER V" in regular_text
    assert "Observed counts" not in regular_text


def verify_generic_docx() -> None:
    blueprint = build_thesis_analysis_blueprint(
        df_shape=(20, 2),
        classifications=[
            {"column": "Score", "detected_type": "scale"},
            {"column": "Treatment", "detected_type": "nominal"},
        ],
        assignment={"outcome": "Score", "group": "Treatment"},
        table_one={
            "headers": ["Variable", "Type", "Overall"],
            "rows": [{"variable": "Score", "type": "mean ± SD", "cells": ["12.4 ± 3.1"]}],
        },
        tests=[],
        graphs=[],
        significant_findings=[],
        methods_text="Welch's t-test was used for the two-group comparison.",
        results_narrative="No significant finding was detected.",
        session={"study_type": "two-group comparison", "domain_profile": "generic"},
    )
    blob = chapter_v_export.generate_docx({"thesis_analysis_blueprint": blueprint, "export_metadata": {"result_id": "generic-result"}})
    text = _docx_text(blob)
    assert "CHAPTER V" in text
    assert "Two Group Comparison" in text or "two-group comparison" in text.lower()
    assert "p27" not in text


async def verify_post_endpoint() -> None:
    entry = FakeEntry()
    original_get = stats.dataset_store.get
    stats.dataset_store.get = lambda job_id: entry
    try:
        published = stats._publish_results(entry, "chapter-v-job", _representative_results())
        result_id = published["export_metadata"]["result_id"]
        response = await stats.export_chapter_v(stats.ChapterVExportRequest(
            job_id="chapter-v-job",
            result_id=result_id,
            format="docx",
        ))
        assert response.media_type.endswith("wordprocessingml.document")
        text = _docx_text(response.body)
        assert "CHAPTER V" in text
        assert "p27 expression status" in text
    finally:
        stats.dataset_store.get = original_get


def verify_frontend_wiring() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "public/analysis.html").read_text(encoding="utf-8")
    js = (root / "public/js/analysis.js").read_text(encoding="utf-8")
    assert "Download Word Report" in html
    assert "Download PDF Report" in html
    assert "Download Cleaned Excel" in html
    assert '<div class="se-export-feature is-hidden" hidden>' in html
    assert "/export/chapter-v" in js
    assert 'data-testid="button-chapter-v-word">Download Chapter V DOCX' in html
    assert "include_detailed_appendix: false" in js
    assert "include_optional_figures: false" in js


def main() -> None:
    verify_service_docx()
    verify_generic_docx()
    asyncio.run(verify_post_endpoint())
    verify_frontend_wiring()
    print("Sigma Chapter V export verification passed.")


if __name__ == "__main__":
    main()
