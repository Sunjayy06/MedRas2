from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "app" / "services" / "export.py"
STATS = ROOT / "app" / "api" / "stats.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_excel_export_uses_processed_display_dataset() -> None:
    source = _read(EXPORT)
    assert "cleaned_processed_dataset" in source
    assert "_excel_display_dataframe(df, label_ctx, category_merge_rows)" in source
    assert "Postive" in source and "Positive" in source
    assert '">=14%"' in source
    assert '"Yes": "Positive"' in source
    assert '"No": "Negative"' in source


def test_excel_export_has_structured_audit_sheets() -> None:
    source = _read(EXPORT)
    assert 'wb.create_sheet("category_merges")' in source
    assert '"Original category"' in source
    assert '"Cleaned category"' in source
    assert '"Count affected"' in source
    assert '"Decision type"' in source
    assert '"Applied to dataset"' in source
    assert 'wb.create_sheet("missing_data_decisions")' in source
    assert '"Missing count"' in source
    assert '"Missing percent"' in source
    assert '"Impact on analysis"' in source
    assert 'wb.create_sheet("excluded_variables")' in source
    assert '"Still present in cleaned dataset"' in source
    assert '"Downstream impact"' in source
    assert '"primary_outcome"' in source
    assert '"excluded_variable"' in source
    assert '"marker_or_outcome_component"' in source


def test_apply_routes_persist_structured_export_metadata() -> None:
    source = _read(STATS)
    assert 'entry.meta["category_merge_actions"]' in source
    assert '"original_category"' in source
    assert '"cleaned_category"' in source
    assert '"count_affected"' in source
    assert 'entry.meta["missing_decisions_log"]' in source
    assert '"missing_count"' in source
    assert '"missing_percent"' in source
    assert '"impact_on_analysis"' in source
    assert 'entry.meta["analysis_exclusion_log"]' in source


if __name__ == "__main__":
    test_excel_export_uses_processed_display_dataset()
    test_excel_export_has_structured_audit_sheets()
    test_apply_routes_persist_structured_export_metadata()
    print("Sigma Excel export fidelity checks passed.")
