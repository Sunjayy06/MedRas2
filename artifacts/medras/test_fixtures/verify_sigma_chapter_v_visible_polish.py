"""Static regression checks for Sigma Chapter V visible export polish.

These checks intentionally avoid importing the full app stack so they can run
even when optional analysis dependencies are not installed locally.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_chapter_v_export_uses_thesis_display_figures() -> None:
    source = _read("app/services/chapter_v_export.py")
    assert "def _normalise_figure_metadata" in source
    assert 'clone["title"] = f"{display} by {predictor}"' in source
    assert "def _primary_outcome_figure" in source

    docx_primary = source.index("generated = _primary_outcome_figure")
    docx_existing = source.index("for fig in _section_figures(section, include_optional_figures)[:1]")
    assert docx_primary < docx_existing

    pdf_primary = source.rindex("generated = _primary_outcome_figure")
    pdf_existing = source.rindex("for fig in _section_figures(section, include_optional_figures)[:1]")
    assert pdf_primary < pdf_existing


def test_chapter_v_export_splits_mixed_descriptive_tables() -> None:
    source = _read("app/services/chapter_v_export.py")
    assert "def _expand_export_tables" in source
    assert "if continuous_rows and categorical_counts:" in source
    assert '"Mean \\u00b1 SD"' in source or '"Mean ± SD"' in source
    assert '"Missing n (%)"' in source
    assert '["Parameter", "Category", "n", "%"]' in source


def test_results_graph_generation_uses_outcome_display_mapping() -> None:
    source = _read("app/services/results.py")
    assert "def _apply_thesis_display_labels_to_graph_df" in source
    assert "graph_outcome = args.get(\"outcome\") or args.get(\"col2\") or args.get(\"col1\")" in source
    assert "outcome_label = str((session or {}).get(\"main_outcome_concept\")" in source
    assert "outcome_label=outcome_label" in source
    assert '"title": f"{outcome_label or args.get(\'col2\')} by {clean_display_name(args.get(\'col1\'))}"' in source


def test_significant_findings_keep_raw_and_adjusted_p_values_separate() -> None:
    source = _read("app/services/results.py")
    assert "raw_p = _result_raw_p_value(test)" in source
    assert "adjusted_p = _result_adjusted_p_value(test)" in source
    assert '"p_value": _fmt_p(raw_p) if raw_p is not None else _fmt_p(significance_p)' in source
    assert '"adjusted_p_value": _fmt_p(adjusted_p) if adjusted_p is not None else "-"' in source

    excel = _read("app/services/export.py")
    assert "_excel_display_value(row.get(\"p_value\", \"\"), label_ctx)" in excel
    assert "_excel_display_value(row.get(\"adjusted_p_value\", \"\"), label_ctx)" in excel


def test_thesis_interpretation_language_is_not_raw_outcome_phrase() -> None:
    blueprint = _read("app/services/thesis_blueprint.py")
    assert "was significantly associated with the outcome" not in blueprint
    assert "did not show a statistically significant association with" in blueprint

    export = _read("app/services/chapter_v_export.py")
    assert "This finding should be interpreted cautiously because some expected cell counts were below 5." in export
    assert "Localization and staining score are presented descriptively" in export


def main() -> None:
    test_chapter_v_export_uses_thesis_display_figures()
    test_chapter_v_export_splits_mixed_descriptive_tables()
    test_results_graph_generation_uses_outcome_display_mapping()
    test_significant_findings_keep_raw_and_adjusted_p_values_separate()
    test_thesis_interpretation_language_is_not_raw_outcome_phrase()
    print("sigma chapter v visible polish checks passed")


if __name__ == "__main__":
    main()
