"""Final Sigma deterministic cleanup — regression checks.

Covers:
  1. Age baseline Minimum=30 / Maximum=88 populated in Word/PDF
  2. Primary outcome table uses Parameter | Category | n | % columns
  3. Primary outcome distribution figure exists before Age association figure
  4. pT / Nodal status / LVI absent from main Word/PDF by default
  5. Histological type, ER, PR, Molecular subtype, AR figures present
  6. category_merges sheet records Postive->Positive and Ki67 normalisation
  7. cleaned_processed_dataset contains no raw "Postive" values
  8. Significant-findings table has separate raw p-value / adjusted p-value columns
  9. Generic (non-p27) fixture still passes

Run from artifacts/medras:
    python -m test_fixtures.verify_sigma_final_polish
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
from docx import Document
from openpyxl import load_workbook

from app.services import chapter_v_export, export
from app.services.results import build_table_one
from app.services.thesis_blueprint import build_thesis_analysis_blueprint


PNG_1X1 = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def _docx_text(blob: bytes) -> str:
    doc = Document(io.BytesIO(blob))
    paragraphs = [p.text for p in doc.paragraphs]
    cells = [cell.text for table in doc.tables for row in table.rows for cell in row.cells]
    return "\n".join(paragraphs + cells)


def _assoc_test(name: str, *, p_value: str, adjusted: str, effect: str = "Cramér's V = 0.46") -> Dict[str, Any]:
    return {
        "id": f"{name.lower().replace(' ', '_')}_by_outcome",
        "title": f"{name} vs p27 expression status: Chi-square test",
        "test_type": "chi_square",
        "analysis_family": "bivariate",
        "tables": [{
            "title": f"Association of p27 expression status with {name}",
            "headers": [
                "Predictor category", "Positive n (%)", "Negative n (%)",
                "p-value", "Adjusted p-value", "Test applied", "Effect size", "Warnings",
            ],
            "rows": [["Positive", "6 (66.7%)", "0 (0.0%)", p_value, adjusted, "Chi-square test", effect, "-"]],
        }],
        "figures": [{
            "title": f"{name} by p27 expression status",
            "png_data_uri": PNG_1X1,
            "caption": f"Grouped percentage bar chart of {name} by p27 expression status.",
        }],
    }


def _build_fixture() -> tuple[Dict[str, Any], "pd.DataFrame", Dict[str, Any]]:
    """Build representative results, raw df, and FakeEntry-style meta."""
    # Age range deliberately spans 30–88 to verify min/max pipeline.
    ages = [30, 35, 42, 48, 55, 60, 62, 67, 72, 77, 81, 88]
    n = len(ages)

    df = pd.DataFrame({
        "Positive/ Negative": ["Yes"] * 8 + ["No"] * 4,
        "Age": ages,
        "ER": ["Postive"] * 2 + ["Positive"] * 4 + ["Negative"] * 6,     # 2 typos
        "PR": ["Postive"] * 1 + ["Positive"] * 5 + ["Negative"] * 6,     # 1 typo
        "AR": ["Postive"] * 1 + ["Positive"] * 5 + ["Negative"] * 6,     # 1 typo
        "Histological type": ["Type 1", "Type 2", "Type 3"] * 4,
        "Molecular subtype": ["Luminal A", "Luminal B", "HER2neu", "Triple negative"] * 3,
        "Ki67": [">=14"] * 5 + ["<14"] * 7,                               # unnormalised Ki67
        "pT": ["T1", "T2", "T3"] * 4,
        "Nodal status": ["N0", "N1", "N2"] * 4,
        "LVI": ["Present", "Absent"] * 6,
    })

    classifications = [
        {"column": "Positive/ Negative", "detected_type": "nominal"},
        {"column": "Age",                "detected_type": "scale"},
        {"column": "ER",                 "detected_type": "nominal"},
        {"column": "PR",                 "detected_type": "nominal"},
        {"column": "AR",                 "detected_type": "nominal"},
        {"column": "Histological type",  "detected_type": "nominal"},
        {"column": "Molecular subtype",  "detected_type": "nominal"},
        {"column": "Ki67",               "detected_type": "nominal"},
        {"column": "pT",                 "detected_type": "ordinal"},
        {"column": "Nodal status",       "detected_type": "ordinal"},
        {"column": "LVI",                "detected_type": "nominal"},
    ]

    table_one = build_table_one(df, classifications, group=None)

    tests: List[Dict[str, Any]] = [
        {
            "id": "age_by_outcome",
            "title": "Age by p27 expression status: Welch's t-test",
            "test_type": "welch_ttest",
            "analysis_family": "bivariate",
            "tables": [{
                "title": "Comparison of Age by p27 expression status",
                "headers": [
                    "Group", "n", "Mean ± SD", "Test statistic",
                    "p-value", "Adjusted p-value", "Test applied", "Effect size", "Warnings",
                ],
                "rows": [
                    ["p27 Positive", "8", "57.1 ± 18.9", "t = 1.20", "p = 0.240", "p = 0.300", "Welch's t-test", "Cohen's d = 0.42", "-"],
                    ["p27 Negative", "4", "61.8 ± 22.5", "t = 1.20", "p = 0.240", "p = 0.300", "Welch's t-test", "Cohen's d = 0.42", "-"],
                ],
            }],
            "figures": [{
                "title": "Age by p27 expression status",
                "png_data_uri": PNG_1X1,
                "caption": "Boxplot of Age by p27 expression status.",
            }],
        },
        # Significant predictors (real p-values per task spec)
        _assoc_test("Histological type", p_value="p = 0.004", adjusted="p = 0.013"),
        _assoc_test("ER",                p_value="p < 0.001",  adjusted="p = 0.005"),
        _assoc_test("PR",                p_value="p = 0.002",  adjusted="p = 0.009"),
        _assoc_test("Molecular subtype", p_value="p < 0.001",  adjusted="p < 0.001"),
        _assoc_test("AR",                p_value="p = 0.004",  adjusted="p = 0.013"),
        # Non-significant (should NOT appear in main Word/PDF figures)
        _assoc_test("pT",          p_value="p = 0.400", adjusted="p = 0.700"),
        _assoc_test("Nodal status", p_value="p = 0.420", adjusted="p = 0.710"),
        _assoc_test("LVI",         p_value="p = 0.500", adjusted="p = 0.750"),
    ]

    significant_findings: List[Dict[str, Any]] = [
        {
            "variable": "Histological type vs Positive/ Negative",
            "key_finding": "Histological type was associated with the primary outcome.",
            "test_statistic": "chi-square = 8.40",
            "p_value": "p = 0.004",
            "adjusted_p_value": "p = 0.013",
            "test_applied": "Chi-square test",
            "effect_size": "Cramér's V = 0.46",
            "notes_warnings": "-",
        },
        {
            "variable": "ER vs Positive/ Negative",
            "key_finding": "ER was associated with the primary outcome.",
            "test_statistic": "chi-square = 12.00",
            "p_value": "p < 0.001",
            "adjusted_p_value": "p = 0.005",
            "test_applied": "Chi-square test",
            "effect_size": "Cramér's V = 0.55",
            "notes_warnings": "-",
        },
        {
            "variable": "PR vs Positive/ Negative",
            "key_finding": "PR was associated with the primary outcome.",
            "test_statistic": "chi-square = 9.30",
            "p_value": "p = 0.002",
            "adjusted_p_value": "p = 0.009",
            "test_applied": "Chi-square test",
            "effect_size": "Cramér's V = 0.50",
            "notes_warnings": "-",
        },
        {
            "variable": "Molecular subtype vs Positive/ Negative",
            "key_finding": "Molecular subtype was associated with the primary outcome.",
            "test_statistic": "chi-square = 14.00",
            "p_value": "p < 0.001",
            "adjusted_p_value": "p < 0.001",
            "test_applied": "Chi-square test",
            "effect_size": "Cramér's V = 0.60",
            "notes_warnings": "-",
        },
        {
            "variable": "AR vs Positive/ Negative",
            "key_finding": "AR was associated with the primary outcome.",
            "test_statistic": "chi-square = 8.10",
            "p_value": "p = 0.004",
            "adjusted_p_value": "p = 0.013",
            "test_applied": "Chi-square test",
            "effect_size": "Cramér's V = 0.44",
            "notes_warnings": "-",
        },
    ]

    blueprint = build_thesis_analysis_blueprint(
        df_shape=(n, len(df.columns)),
        classifications=classifications,
        assignment={"outcome": "Positive/ Negative"},
        table_one=table_one,
        tests=tests,
        graphs=[],
        significant_findings=significant_findings,
        methods_text=(
            "Continuous variables are summarised as mean ± SD with range. "
            "Chi-square tests were used for categorical predictors. "
            "Welch's t-test was used for the continuous predictor Age. "
            "p < 0.05 was considered statistically significant."
        ),
        results_narrative="ER, PR, Molecular subtype, Histological type, and AR were significantly associated with p27 expression status.",
        session={
            "study_type": "association",
            "domain_profile": "breast_pathology",
            "main_marker": "p27",
            "main_outcome_concept": "p27 expression status",
            "analysis_excluded_columns": [],
        },
        plan={"debug": {"eligible_predictor_count": 8, "bivariate_test_count": 8}},
    )

    results = {
        "table_one": table_one,
        "tests": tests,
        "significant_findings": significant_findings,
        "thesis_analysis_blueprint": blueprint,
        "export_metadata": {
            "dataset_id": "final-polish-job",
            "result_id": "final-polish-result",
            "analysis_version": 1,
            "generated_at": "2026-06-20T00:00:00+00:00",
            "domain_profile": "breast_pathology",
        },
    }

    meta = {
        "filename": "final-polish-fixture.xlsx",
        "domain_profile": "breast_pathology",
        "assignment": {"outcome": "Positive/ Negative"},
        "classifications": classifications,
        "data_version": 0,
        "category_merge_actions": [],   # no user merges; system merges come from df scan
    }

    return results, df, meta


# ── 1. Age baseline min / max ─────────────────────────────────────────────────

def test_age_baseline_min_max() -> None:
    """Word export must show Minimum=30 and Maximum=88 for Age."""
    results, _, _ = _build_fixture()
    blob = chapter_v_export.generate_docx(results)
    doc = Document(io.BytesIO(blob))

    # Find the continuous descriptive table (Age row)
    age_row: list | None = None
    for table in doc.tables:
        headers = [cell.text for cell in table.rows[0].cells]
        if headers[:2] == ["Parameter", "n"] and "Minimum" in headers and "Maximum" in headers:
            min_idx = headers.index("Minimum")
            max_idx = headers.index("Maximum")
            for row in table.rows[1:]:
                cells = [cell.text for cell in row.cells]
                if cells[0] == "Age":
                    age_row = cells
                    break
        if age_row:
            break

    assert age_row is not None, "Age row not found in any continuous descriptive table"
    min_val = age_row[min_idx]
    max_val = age_row[max_idx]
    assert min_val == "30", f"Expected Minimum=30, got {min_val!r}"
    assert max_val == "88", f"Expected Maximum=88, got {max_val!r}"


# ── 2. Primary outcome table format ──────────────────────────────────────────

def test_primary_outcome_table_format() -> None:
    """Primary outcome table must use Parameter | Category | n | % columns."""
    results, _, _ = _build_fixture()
    blob = chapter_v_export.generate_docx(results)
    doc = Document(io.BytesIO(blob))
    text = _docx_text(blob)

    assert "Parameter\nCategory\nn\n%" in text, "Header row Parameter|Category|n|% not found"

    # p27 expression status must be the Parameter column entry
    found_p27_row = False
    for table in doc.tables:
        headers = [cell.text for cell in table.rows[0].cells]
        if headers == ["Parameter", "Category", "n", "%"]:
            row_params = {row.cells[0].text for row in table.rows[1:]}
            if "p27 expression status" in row_params:
                found_p27_row = True
                break
    assert found_p27_row, "p27 expression status not found as Parameter in a Parameter/Category/n/% table"

    # Verify Positive and Negative categories appear
    assert "Positive\n8\n66.7%" in text, "Expected Positive row in primary outcome table"
    assert "Negative\n4\n33.3%" in text, "Expected Negative row in primary outcome table"


# ── 3. Figure order: distribution before Age ─────────────────────────────────

def test_primary_outcome_figure_before_age_figure() -> None:
    """Figure 1 must be the distribution figure; Age figure must follow."""
    results, _, _ = _build_fixture()
    blob = chapter_v_export.generate_docx(results)
    text = _docx_text(blob)

    assert "Figure 1. Distribution of p27 expression status." in text, \
        "Distribution figure must be Figure 1"

    dist_pos = text.index("Figure 1. Distribution of p27 expression status.")
    age_pos = text.index("Figure 2.")  # Age is second because it's the next core figure
    assert dist_pos < age_pos, "Distribution figure must precede Age figure"


# ── 4. Non-significant figures absent from main report ───────────────────────

def test_nonsignificant_figures_absent() -> None:
    """pT, Nodal status, LVI figures must NOT appear in the main Word export."""
    results, _, _ = _build_fixture()
    blob = chapter_v_export.generate_docx(results)
    text = _docx_text(blob)

    # After _normalise_figure_metadata the format is "{outcome} by {predictor}".
    assert "p27 expression status by pT" not in text, \
        "pT figure must be absent from main report"
    assert "p27 expression status by Nodal status" not in text, \
        "Nodal status figure must be absent from main report"
    assert "p27 expression status by LVI" not in text, \
        "LVI figure must be absent from main report"


# ── 5. Significant association figures present ────────────────────────────────

def test_significant_association_figures_present() -> None:
    """Histological type, ER, PR, Molecular subtype, AR figures must be present."""
    results, _, _ = _build_fixture()
    blob = chapter_v_export.generate_docx(results)
    text = _docx_text(blob)

    # _normalise_figure_metadata rewrites captions to "{outcome} by {predictor}".
    for predictor in ("Histological type", "ER", "PR", "Molecular subtype", "AR"):
        assert f"p27 expression status by {predictor}" in text, \
            f"Figure for {predictor} must be present in main report"


# ── 6. category_merges audit sheet completeness ───────────────────────────────

class _FakeEntry:
    def __init__(self, df: pd.DataFrame, meta: dict) -> None:
        self.df = df
        self.meta = meta


def test_category_merges_records_system_display_typos() -> None:
    """category_merges sheet must record Postive->Positive and Ki67 normalisation."""
    results, df, meta = _build_fixture()
    entry = _FakeEntry(df, meta)
    blob = export.to_xlsx(entry, results, {"outcome": "Positive/ Negative"})

    wb = load_workbook(io.BytesIO(blob))
    assert "category_merges" in wb.sheetnames, "category_merges sheet must exist"

    ws = wb["category_merges"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))

    original_cols = [str(r[1]) for r in rows if r[1] is not None]
    cleaned_cols  = [str(r[2]) for r in rows if r[2] is not None]

    # Postive -> Positive entries must be present (ER=2, PR=1, AR=1)
    assert "Postive" in original_cols, "Postive must appear in Original category column"
    assert "Positive" in cleaned_cols, "Positive must appear in Cleaned category column"

    # Ki67 normalisation: >=14 -> >=14%
    assert ">=14" in original_cols, ">=14 must appear in Original category column"
    assert ">=14%" in cleaned_cols, ">=14% must appear in Cleaned category column"

    # ER column with count=2 must have an explicit row
    er_rows = [r for r in rows if str(r[0]) == "ER" and str(r[1]) == "Postive"]
    assert er_rows, "ER / Postive row must be present in category_merges"
    assert er_rows[0][3] == 2, f"ER Postive count_affected must be 2, got {er_rows[0][3]}"

    # PR with count=1
    pr_rows = [r for r in rows if str(r[0]) == "PR" and str(r[1]) == "Postive"]
    assert pr_rows, "PR / Postive row must be present in category_merges"
    assert pr_rows[0][3] == 1, f"PR Postive count_affected must be 1, got {pr_rows[0][3]}"

    # AR with count=1
    ar_rows = [r for r in rows if str(r[0]) == "AR" and str(r[1]) == "Postive"]
    assert ar_rows, "AR / Postive row must be present in category_merges"
    assert ar_rows[0][3] == 1, f"AR Postive count_affected must be 1, got {ar_rows[0][3]}"


# ── 7. cleaned_processed_dataset has no raw typos ────────────────────────────

def test_cleaned_dataset_no_postive() -> None:
    """cleaned_processed_dataset sheet must not contain the raw typo 'Postive'."""
    results, df, meta = _build_fixture()
    entry = _FakeEntry(df, meta)
    blob = export.to_xlsx(entry, results, {"outcome": "Positive/ Negative"})

    wb = load_workbook(io.BytesIO(blob))
    assert "cleaned_processed_dataset" in wb.sheetnames

    ws = wb["cleaned_processed_dataset"]
    # iter_rows(values_only=True) returns raw scalars, not Cell objects
    all_text = " ".join(
        str(v)
        for row in ws.iter_rows(min_row=2, values_only=True)
        for v in row
        if v is not None
    )
    assert "Postive" not in all_text, \
        "cleaned_processed_dataset must not contain the raw typo 'Postive'"


# ── 8. Significant findings p-values are separate and correct ─────────────────

def test_significant_findings_pvalues_separate() -> None:
    """Significant findings table must have separate raw and adjusted p-value columns."""
    results, _, _ = _build_fixture()
    blob = chapter_v_export.generate_docx(results)
    doc = Document(io.BytesIO(blob))

    # Last table in Chapter V is the significant findings summary
    sig_table = doc.tables[-1]
    headers = [cell.text for cell in sig_table.rows[0].cells]

    assert "p-value" in headers, "p-value column must exist in significant findings table"
    assert "Adjusted p-value" in headers, "Adjusted p-value column must exist"

    p_idx  = headers.index("p-value")
    ap_idx = headers.index("Adjusted p-value")

    rows = {row.cells[0].text: [cell.text for cell in row.cells]
            for row in sig_table.rows[1:] if row.cells[0].text}

    def _find(label: str) -> list[str]:
        for key, row in rows.items():
            if label in key:
                return row
        raise AssertionError(f"Finding '{label}' not in significant findings table. Keys: {list(rows)}")

    hist = _find("Histological type")
    assert hist[p_idx] == "p = 0.004",  f"Histological type raw p: {hist[p_idx]!r}"
    assert hist[ap_idx] == "p = 0.013", f"Histological type adjusted p: {hist[ap_idx]!r}"

    er = _find("ER vs")
    assert er[p_idx] == "p < 0.001",  f"ER raw p: {er[p_idx]!r}"
    assert er[ap_idx] == "p = 0.005", f"ER adjusted p: {er[ap_idx]!r}"

    pr = _find("PR vs")
    assert pr[p_idx] == "p = 0.002",  f"PR raw p: {pr[p_idx]!r}"
    assert pr[ap_idx] == "p = 0.009", f"PR adjusted p: {pr[ap_idx]!r}"

    mol = _find("Molecular subtype")
    assert mol[p_idx] == "p < 0.001",  f"Molecular subtype raw p: {mol[p_idx]!r}"
    assert mol[ap_idx] == "p < 0.001", f"Molecular subtype adjusted p: {mol[ap_idx]!r}"

    ar = _find("AR vs")
    assert ar[p_idx] == "p = 0.004",  f"AR raw p: {ar[p_idx]!r}"
    assert ar[ap_idx] == "p = 0.013", f"AR adjusted p: {ar[ap_idx]!r}"


# ── 9. Generic (non-p27) fixture still passes ────────────────────────────────

def test_generic_non_p27_fixture() -> None:
    """A generic two-group study must render without p27-specific content."""
    blueprint = build_thesis_analysis_blueprint(
        df_shape=(20, 2),
        classifications=[
            {"column": "Score",     "detected_type": "scale"},
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
    blob = chapter_v_export.generate_docx({
        "thesis_analysis_blueprint": blueprint,
        "export_metadata": {"result_id": "generic-final-polish"},
    })
    text = _docx_text(blob)
    assert "CHAPTER V" in text
    assert "p27" not in text


# ── runner ────────────────────────────────────────────────────────────────────

def main() -> None:
    test_age_baseline_min_max()
    print("  [ok] Age baseline min/max")

    test_primary_outcome_table_format()
    print("  [ok] Primary outcome table Parameter|Category|n|% format")

    test_primary_outcome_figure_before_age_figure()
    print("  [ok] Primary outcome distribution figure before Age figure")

    test_nonsignificant_figures_absent()
    print("  [ok] pT / Nodal status / LVI figures absent from main report")

    test_significant_association_figures_present()
    print("  [ok] Histological type / ER / PR / Molecular subtype / AR figures present")

    test_category_merges_records_system_display_typos()
    print("  [ok] category_merges records Postive->Positive and Ki67 normalisation")

    test_cleaned_dataset_no_postive()
    print("  [ok] cleaned_processed_dataset contains no raw typo 'Postive'")

    test_significant_findings_pvalues_separate()
    print("  [ok] Significant findings raw p-value and adjusted p-value are separate")

    test_generic_non_p27_fixture()
    print("  [ok] Generic non-p27 fixture passes")

    print("\nSigma final polish verification passed.")


if __name__ == "__main__":
    main()
