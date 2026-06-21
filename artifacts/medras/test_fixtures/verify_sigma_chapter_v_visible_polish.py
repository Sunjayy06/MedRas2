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


def test_main_export_does_not_append_unmatched_optional_figures() -> None:
    source = _read("app/services/chapter_v_export.py")
    docx_renderer = source[source.index("def _render_section_docx"):source.index("def _blueprint")]
    pdf_renderer = source[source.index("def _render_section_pdf"):source.index("def generate_pdf")]
    assert "if include_optional_figures:" in docx_renderer
    assert "if include_optional_figures:" in pdf_renderer
    assert "for figure in figures[:4]:" not in docx_renderer.replace("if include_optional_figures:\n        for figure in figures[:4]:", "")
    assert "for figure in figures[:4]:" not in pdf_renderer.replace("if include_optional_figures:\n        for figure in figures[:4]:", "")


def test_chapter_v_export_splits_mixed_descriptive_tables() -> None:
    source = _read("app/services/chapter_v_export.py")
    assert "def _expand_export_tables" in source
    assert "if continuous_rows and categorical_counts:" in source
    assert '"Mean \\u00b1 SD"' in source or '"Mean ± SD"' in source
    assert '"Missing n (%)"' in source
    assert '["Parameter", "Category", "n", "%"]' in source


def test_chapter_v_export_normalizes_association_display_categories() -> None:
    source = _read("app/services/chapter_v_export.py")
    assert "def _clinical_category_label" in source
    assert "def _association_table_for_export" in source
    assert "grouped[category][idx]" in source
    assert "Grade {match.group(1)}" in source
    assert "HER2-enriched" in source
    assert "Present" in source and "Absent" in source
    assert '"abse"' in source


def test_chapter_v_renders_core_association_figures_before_tables() -> None:
    source = _read("app/services/chapter_v_export.py")
    assert "def _association_figure_sort_key" in source
    docx_renderer = source[source.index("def _render_section_docx"):source.index("def _blueprint")]
    pdf_renderer = source[source.index("def _render_section_pdf"):source.index("def generate_pdf")]
    assert 'if section_id == "bivariate_associations":' in docx_renderer
    assert 'if section_id == "bivariate_associations":' in pdf_renderer
    assert "_association_figure_sort_key" in docx_renderer
    assert "_association_figure_sort_key" in pdf_renderer


def test_results_graph_generation_uses_outcome_display_mapping() -> None:
    source = _read("app/services/results.py")
    assert "def _apply_thesis_display_labels_to_graph_df" in source
    assert "def _needs_clinical_category_display" in source
    assert "def _clinical_display_category" in source
    assert "_needs_clinical_category_display(col)" in source
    assert "graph_outcome = args.get(\"outcome\") or args.get(\"col2\") or args.get(\"col1\")" in source
    assert "outcome_label = str((session or {}).get(\"main_outcome_concept\")" in source
    assert "outcome_label=outcome_label" in source
    assert '"title": f"{outcome_label or args.get(\'col2\')} by {clinical_display_name(args.get(\'col1\'))}"' in source


def test_significant_findings_keep_raw_and_adjusted_p_values_separate() -> None:
    source = _read("app/services/results.py")
    assert "raw_p = _result_raw_p_value(test)" in source
    assert "adjusted_p = _result_adjusted_p_value(test)" in source
    assert '"p_value": _fmt_p(raw_p) if raw_p is not None else _fmt_p(significance_p)' in source
    assert '"adjusted_p_value": _fmt_p(adjusted_p) if adjusted_p is not None else "-"' in source

    excel = _read("app/services/export.py")
    assert "_excel_display_value(row.get(\"p_value\", \"\"), label_ctx)" in excel
    assert "_excel_display_value(row.get(\"adjusted_p_value\", \"\"), label_ctx)" in excel


def test_pdf_primary_outcome_applies_expand_tables() -> None:
    source = _read("app/services/chapter_v_export.py")
    pdf_section = source[source.index("def generate_pdf"):]
    assert "display_tables = _expand_export_tables(outcome_tables" in pdf_section, \
        "PDF path must apply _expand_export_tables to outcome_tables before _pdf_table"


def test_thesis_interpretation_language_is_not_raw_outcome_phrase() -> None:
    blueprint = _read("app/services/thesis_blueprint.py")
    assert "was significantly associated with the outcome" not in blueprint
    assert "did not show a statistically significant association with" in blueprint

    export = _read("app/services/chapter_v_export.py")
    assert "This finding should be interpreted cautiously because some expected cell counts were below 5." in export
    assert "Localization and staining score are presented descriptively" in export
    assert "Minimum expected count" not in export


def test_thesis_significant_findings_use_deterministic_summaries() -> None:
    blueprint = _read("app/services/thesis_blueprint.py")
    assert "def _deterministic_key_finding" in blueprint
    assert "Grade 3 cases were proportionately higher in the p27-negative group." in blueprint
    assert "Triple-negative phenotype was proportionately enriched among p27-negative cases" in blueprint


def test_blueprint_keeps_core_significant_figures_in_main_report() -> None:
    blueprint = _read("app/services/thesis_blueprint.py")
    assert "core_figure_vars = set()" in blueprint
    assert "fig_vars.intersection(core_figure_vars)" in blueprint
    assert "and not is_core" in blueprint


def main() -> None:
    test_chapter_v_export_uses_thesis_display_figures()
    test_main_export_does_not_append_unmatched_optional_figures()
    test_chapter_v_export_splits_mixed_descriptive_tables()
    test_chapter_v_export_normalizes_association_display_categories()
    test_chapter_v_renders_core_association_figures_before_tables()
    test_pdf_primary_outcome_applies_expand_tables()
    test_results_graph_generation_uses_outcome_display_mapping()
    test_significant_findings_keep_raw_and_adjusted_p_values_separate()
    test_thesis_interpretation_language_is_not_raw_outcome_phrase()
    test_thesis_significant_findings_use_deterministic_summaries()
    test_blueprint_keeps_core_significant_figures_in_main_report()
    print("sigma chapter v visible polish checks passed")


if __name__ == "__main__":
    main()
