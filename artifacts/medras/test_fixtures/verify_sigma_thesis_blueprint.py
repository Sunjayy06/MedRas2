"""Verify Sigma's general thesis-analysis blueprint payload.

Run:
    python -m test_fixtures.verify_sigma_thesis_blueprint
"""

from __future__ import annotations

import pandas as pd

from app.services import plan, results
from app.services.thesis_blueprint import build_thesis_analysis_blueprint


def _classes(df: pd.DataFrame, overrides: dict | None = None) -> list[dict]:
    overrides = overrides or {}
    out = []
    for col in df.columns:
        detected = overrides.get(col)
        if not detected:
            detected = "scale" if pd.api.types.is_numeric_dtype(df[col]) else "nominal"
        out.append({"column": col, "detected_type": detected})
    return out


def _normality(*cols: str) -> dict:
    return {"columns": [{"column": col, "is_normal": True, "decision": "normal"} for col in cols]}


def _section_ids(blueprint: dict) -> set[str]:
    return {section["section_id"] for section in blueprint["analysis_sections"]}


def _table_types(blueprint: dict) -> set[str]:
    return {table["table_type"] for table in blueprint["tables"]}


def _figure_types(blueprint: dict) -> set[str]:
    return {figure["graph_type"] for figure in blueprint["figures"]}


def verify_p27_association_blueprint() -> None:
    df = pd.DataFrame({
        "Age": [42, 51, 63, 55, 48, 61, 46, 59],
        "Laterality": ["Left", "Right", "Left", "Right", "Left", "Right", "Left", "Right"],
        "pT": ["T1c", "T2", "T3", "T4b", "T1c", "T2", "T3", "T4b"],
        "Nodal status": ["N0", "N1a", "N2a", "N3a", "N0", "N1a", "N2a", "N3a"],
        "ER": ["Positive", "Negative", "Positive", "Negative", "Positive", "Negative", "Positive", "Negative"],
        "PR": ["Positive", "Negative", "Positive", "Negative", "Positive", "Negative", "Positive", "Negative"],
        "Molecular subtype": ["Luminal A", "Luminal B", "HER2neu", "Triple negative", "Luminal A", "Luminal B", "HER2neu", "Triple negative"],
        "Interpretation-site": ["Nuclear", "Cytoplasmic", "Nuclear", "Cytoplasmic", "Nuclear", "Cytoplasmic", "Nuclear", "Cytoplasmic"],
        "Staining Result": ["Strong", "Weak", "Strong", "Weak", "Strong", "Weak", "Strong", "Weak"],
        "Positive/ Negative": ["Yes", "No", "Yes", "No", "Yes", "No", "Yes", "No"],
        "positive_nodes": [0, 1, 2, 3, 0, 1, 2, 3],
    })
    classes = _classes(df, {
        "Age": "scale",
        "pT": "ordinal",
        "Nodal status": "ordinal",
        "positive_nodes": "exclude",
    })
    assignment = {"outcome": "Positive/ Negative"}
    session = {
        "study_type": "association",
        "domain_profile": "breast_pathology",
        "main_marker": "p27",
        "main_outcome_concept": "p27 expression status",
        "analysis_predictors": ["Age", "Laterality", "pT", "Nodal status", "ER", "PR", "Molecular subtype"],
        "analysis_excluded_columns": ["positive_nodes"],
    }
    sigma_plan = plan.generate_plan(df, classes, assignment, _normality("Age"), session=session)
    output = results.run_plan(df, classes, assignment, sigma_plan, session=session)
    blueprint = output["thesis_analysis_blueprint"]
    assert blueprint["primary_outcome"] == "p27 expression status"
    assert blueprint["study_summary"]["domain_profile"] == "breast_pathology"
    assert {"baseline_characteristics", "primary_outcome_distribution", "bivariate_associations", "significant_findings_summary"}.issubset(_section_ids(blueprint))
    assert "clinical_study_characteristics" in _section_ids(blueprint)
    assert "immunophenotype_characteristics" in _section_ids(blueprint)
    assert "categorical_association_thesis_table" in _table_types(blueprint)
    table_text = str(blueprint["tables"])
    assert "p27 expression status" in table_text
    assert "Positive:" in table_text or "Positive n (%)" in table_text
    assert "Negative:" in table_text or "Negative n (%)" in table_text
    assert "Yes:" not in table_text
    assert "No:" not in table_text
    forbidden_titles = {"observed counts", "expected counts", "row percentages", "column percentages", "test summary"}
    assert not any(str(table["title"]).strip().lower() in forbidden_titles for table in blueprint["tables"])
    assert all(
        len([t for t in blueprint["tables"] if test_id in (t.get("source_test_ids") or [])]) == 1
        for test_id in {test["id"] for test in output["tests"]}
    )
    assert "positive_nodes" not in str({
        "sections": blueprint["analysis_sections"],
        "tables": blueprint["tables"],
        "figures": blueprint["figures"],
    })
    assert "marker_outcome_components" in _section_ids(blueprint)
    biv = next(section for section in blueprint["analysis_sections"] if section["section_id"] == "bivariate_associations")
    assert len(biv["interpretation"]) < 500
    assert all("priority" in table and "detailed_report_only" in table for table in blueprint["tables"])
    assert all("optional" in figure and "detailed_report_only" in figure for figure in blueprint["figures"])
    assert "— =" not in output["results_md"]
    assert "Chi-square test: Chi-square test" not in output["results_md"]
    assert any("Excluded variables" in warning for warning in blueprint["warnings"])


def verify_two_group_blueprint() -> None:
    df = pd.DataFrame({
        "Score": [10, 12, 11, 13, 20, 22, 21, 23],
        "Treatment": ["A", "A", "A", "A", "B", "B", "B", "B"],
    })
    classes = _classes(df, {"Score": "scale", "Treatment": "nominal"})
    assignment = {"outcome": "Score", "group": "Treatment"}
    sigma_plan = plan.generate_plan(df, classes, assignment, _normality("Score"), session={"study_type": "two-group comparison"})
    output = results.run_plan(df, classes, assignment, sigma_plan, session={"study_type": "two-group comparison"})
    blueprint = output["thesis_analysis_blueprint"]
    assert "bivariate_associations" in _section_ids(blueprint)
    assert "continuous_or_group_comparison_thesis_table" in _table_types(blueprint)
    assert "boxplot" in _figure_types(blueprint) or any("box" in fig["graph_type"] for fig in blueprint["figures"])


def verify_correlation_blueprint() -> None:
    df = pd.DataFrame({"Marker A": [1, 2, 3, 4, 5], "Marker B": [2, 4, 6, 8, 10]})
    classes = _classes(df, {"Marker A": "scale", "Marker B": "scale"})
    assignment = {"outcome": "Marker A"}
    session = {"study_type": "correlation", "analysis_predictors": ["Marker B"]}
    sigma_plan = plan.generate_plan(df, classes, assignment, _normality("Marker A", "Marker B"), session=session)
    output = results.run_plan(df, classes, assignment, sigma_plan, session=session)
    blueprint = output["thesis_analysis_blueprint"]
    assert "correlation_analysis" in _section_ids(blueprint)
    assert "correlation_table" in _table_types(blueprint)


def verify_direct_family_blueprints() -> None:
    base = {
        "df_shape": (20, 3),
        "classifications": [
            {"column": "Disease", "detected_type": "nominal"},
            {"column": "Score", "detected_type": "scale"},
            {"column": "Rater 1", "detected_type": "ordinal"},
        ],
        "assignment": {"outcome": "Disease"},
        "table_one": {"headers": ["Variable", "Summary"], "rows": []},
        "methods_text": "Deterministic methods text.",
        "results_narrative": "Deterministic results text.",
        "session": {"study_type": "diagnostic accuracy"},
    }
    diagnostic = build_thesis_analysis_blueprint(
        **base,
        tests=[{
            "id": "diagnostic_accuracy",
            "title": "Score diagnostic accuracy",
            "test_type": "diagnostic_accuracy",
            "tables": [{"title": "Diagnostic Metrics", "headers": ["Metric", "Value"], "rows": [["AUC", "0.92"]]}],
            "figures": [{"title": "ROC curve", "png_data_uri": "data:image/png;base64,abc"}],
            "narrative": "AUC was high.",
        }],
        graphs=[],
        significant_findings=[],
        plan={"tests": [{"id": "diagnostic_accuracy"}]},
    )
    assert "diagnostic_accuracy" in _section_ids(diagnostic)
    assert "diagnostic_accuracy_table" in _table_types(diagnostic)
    assert "roc_curve" in _figure_types(diagnostic)

    reliability = build_thesis_analysis_blueprint(
        **{**base, "session": {"study_type": "reliability"}},
        tests=[{
            "id": "weighted_kappa",
            "title": "Rater agreement",
            "test_type": "weighted_kappa",
            "tables": [{"title": "Kappa Reliability", "headers": ["Measure", "Value"], "rows": [["Kappa", "0.70"]]}],
        }],
        graphs=[],
        significant_findings=[],
        plan={"tests": [{"id": "weighted_kappa"}]},
    )
    assert "reliability_agreement" in _section_ids(reliability)
    assert "agreement_table" in _table_types(reliability)

    repeated = build_thesis_analysis_blueprint(
        **{**base, "session": {"study_type": "repeated measures"}},
        tests=[],
        graphs=[],
        significant_findings=[],
        plan={"tests": [{"id": "repeated_measures_recommended"}]},
    )
    assert repeated["study_design"] == "repeated_measures"

    survival = build_thesis_analysis_blueprint(
        **{**base, "session": {"study_type": "prognostic association"}},
        tests=[],
        graphs=[],
        significant_findings=[],
        plan={"tests": [{"id": "survival_recommended"}]},
    )
    assert survival["study_design"] == "cohort_prognostic_association"
    assert "survival_analysis" not in _section_ids(survival)


def verify_marker_component_filtering() -> None:
    blueprint = build_thesis_analysis_blueprint(
        df_shape=(12, 4),
        classifications=[
            {"column": "Positive/ Negative", "detected_type": "nominal"},
            {"column": "Staining result", "detected_type": "ordinal"},
            {"column": "Age", "detected_type": "scale"},
        ],
        assignment={"outcome": "Positive/ Negative"},
        table_one={"headers": ["Variable", "Summary"], "rows": []},
        tests=[],
        graphs=[],
        significant_findings=[
            {
                "variable": "Staining result vs Positive/ Negative",
                "key_finding": "Component association.",
                "p_value": "p = 0.001",
                "adjusted_p_value": "p = 0.010",
                "test_applied": "Chi-square test",
                "effect_size": "Cramer's V = 0.80",
                "notes_warnings": "-",
            },
            {
                "variable": "Age by Positive/ Negative",
                "key_finding": "Age association.",
                "p_value": "p = 0.020",
                "adjusted_p_value": "p = 0.040",
                "test_applied": "Welch's t-test",
                "effect_size": "Cohen's d = 0.70",
                "notes_warnings": "-",
            },
        ],
        methods_text="Methods.",
        results_narrative="Results.",
        session={
            "study_type": "association",
            "main_marker": "p27",
            "main_outcome_concept": "p27 expression status",
        },
    )
    assert all("Staining result" not in str(row) for row in blueprint["significant_findings"])
    sig_table = next(table for table in blueprint["tables"] if table["table_id"] == "significant_findings")
    assert "Adjusted p-value" in sig_table["columns"]
    assert any("Age by Positive/ Negative" in str(row) for row in sig_table["rows"])


def main() -> None:
    verify_p27_association_blueprint()
    verify_two_group_blueprint()
    verify_correlation_blueprint()
    verify_direct_family_blueprints()
    verify_marker_component_filtering()
    matrix = [
        ("cross-sectional association", "bivariate_associations", "categorical_association_thesis_table", "grouped_or_stacked_bar", "supported"),
        ("two-group comparison", "bivariate_associations", "continuous_or_group_comparison_thesis_table", "boxplot", "supported"),
        ("correlation", "correlation_analysis", "correlation_table", "scatter_plot metadata when available", "supported"),
        ("diagnostic accuracy", "diagnostic_accuracy", "diagnostic_accuracy_table", "roc_curve", "supported when diagnostic result exists"),
        ("reliability/agreement", "reliability_agreement", "agreement_table", "agreement/Bland-Altman figure when available", "supported when result exists"),
        ("repeated measures", "repeated_measures", "repeated-measures table", "line chart", "recommended-only if incomplete"),
        ("survival", "survival_analysis", "survival table", "Kaplan-Meier curve", "only when time/event outputs exist"),
    ]
    print("Sigma thesis blueprint support matrix:")
    for row in matrix:
        print(" | ".join(row))
    print("Sigma thesis blueprint verification passed.")


if __name__ == "__main__":
    main()
