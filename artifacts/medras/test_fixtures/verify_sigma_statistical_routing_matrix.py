"""Verify Sigma statistical routing support matrix and major thesis scenarios."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.services.plan import generate_plan
from app.services.results import run_plan


def _classes(**types):
    return [{"column": column, "detected_type": detected} for column, detected in types.items()]


def _normality(*normal_columns):
    return {"columns": [{"column": column, "decision": "normal"} for column in normal_columns]}


def _functions(plan):
    return {
        test.get("_phase_b", {}).get("function")
        for test in plan["tests"]
        if test.get("_phase_b")
    }


def _test_types(plan):
    return {
        test.get("_phase_b", {}).get("test_type")
        for test in plan["tests"]
        if test.get("_phase_b")
    }


def verify_support_matrix() -> None:
    matrix_path = Path(__file__).with_name("sigma_statistical_routing_matrix.json")
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    expected = {
        "Correlation", "Regression", "Survival analysis", "Time series",
        "T-test", "Mann-Whitney U", "Kruskal-Wallis", "Pairwise comparisons",
        "Repeated-measures ANOVA", "Interrater agreement / Kappa",
        "Bland-Altman", "Forest plot", "Boxplot",
    }
    observed = {row["analysis_type"] for row in matrix}
    assert expected.issubset(observed)
    required_keys = {
        "analysis_type", "supported_now", "required_variables", "planner_behavior",
        "result_table", "graph", "interpretation_safety",
    }
    assert all(required_keys.issubset(row) for row in matrix)
    assert all(row["supported_now"] in {"yes", "partial", "no"} for row in matrix)


def verify_correlation_routing_and_graph_metadata() -> None:
    df = pd.DataFrame({
        "Score": list(range(1, 61)),
        "Age": list(range(31, 91)),
        "Group": ["A", "B", "C"] * 20,
    })
    classes = _classes(Score="scale", Age="scale", Group="nominal")
    pearson = generate_plan(
        df, classes, {"outcome": "Score"}, _normality("Score", "Age"),
        {"study_type": "correlation", "study_type_confirmed": True, "analysis_predictors": ["Age", "Group"]},
    )
    assert _test_types(pearson) == {"pearson"}
    assert all("Group" not in test["columns"] for test in pearson["tests"])
    assert any(graph["graph_type"] == "scatter" for graph in pearson["graphs"])
    assert all("graph_id" in graph and "source_result_id" in graph for graph in pearson["graphs"])

    spearman = generate_plan(
        df, classes, {"outcome": "Score"}, _normality("Score"),
        {"study_type": "correlation", "study_type_confirmed": True, "analysis_predictors": ["Age"]},
    )
    assert _test_types(spearman) == {"spearman"}


def verify_group_comparison_routing() -> None:
    binary = pd.DataFrame({
        "Outcome": ["No", "Yes"] * 30,
        "NormalScore": [10 + (i % 2) * 3 + i * 0.1 for i in range(60)],
        "SkewedScore": [1, 1, 2, 2, 2, 3] * 10,
        "Group3": ["A", "B", "C"] * 20,
    })
    classes = _classes(Outcome="nominal", NormalScore="scale", SkewedScore="scale", Group3="nominal")

    normal_two_group = generate_plan(
        binary, classes, {"outcome": "Outcome"}, _normality("NormalScore"),
        {"study_type": "association", "study_type_confirmed": True, "analysis_predictors": ["NormalScore"]},
    )
    assert "run_pairwise_welch" in _functions(normal_two_group)
    assert any(graph["graph_type"] == "boxplot" for graph in normal_two_group["graphs"])

    nonnormal_two_group = generate_plan(
        binary, classes, {"outcome": "Outcome"}, _normality(),
        {"study_type": "association", "study_type_confirmed": True, "analysis_predictors": ["SkewedScore"]},
    )
    assert "run_pairwise_mann_whitney" in _functions(nonnormal_two_group)

    scale_by_three = generate_plan(
        binary, classes, {"outcome": "SkewedScore", "group": "Group3"}, _normality(),
        {"study_type": "comparison", "study_type_confirmed": True},
    )
    assert any(test["id"] == "kruskal_wallis" for test in scale_by_three["tests"])
    assert any(graph["graph_type"] == "boxplot" for graph in scale_by_three["graphs"])

    anova = generate_plan(
        binary, classes, {"outcome": "NormalScore", "group": "Group3"}, _normality("NormalScore"),
        {"study_type": "comparison", "study_type_confirmed": True},
    )
    assert any(test["id"] == "anova_oneway" for test in anova["tests"])
    assert any(test["id"] == "pc_tukey_hsd" for test in anova["tests"])


def verify_regression_and_forest_rules() -> None:
    df = pd.DataFrame({
        "BinaryOutcome": ["No", "Yes"] * 60,
        "ScaleOutcome": [i * 1.3 for i in range(120)],
        "X1": list(range(120)),
        "X2": [i / 2 for i in range(120)],
    })
    classes = _classes(BinaryOutcome="nominal", ScaleOutcome="scale", X1="scale", X2="scale")
    logistic = generate_plan(
        df, classes, {"outcome": "BinaryOutcome"}, _normality(),
        {"study_type": "regression", "study_type_confirmed": True, "analysis_predictors": ["X1", "X2"]},
    )
    assert any(test["id"] == "pc_binary_logistic" for test in logistic["tests"])
    assert any(graph["graph_type"] == "forest_plot" for graph in logistic["graphs"])

    association = generate_plan(
        df, classes, {"outcome": "BinaryOutcome"}, _normality("X1"),
        {"study_type": "association", "study_type_confirmed": True, "analysis_predictors": ["X1"]},
    )
    assert not any(graph["graph_type"] == "forest_plot" for graph in association["graphs"])

    linear = generate_plan(
        df, classes, {"outcome": "ScaleOutcome"}, _normality(),
        {"study_type": "regression", "study_type_confirmed": True, "analysis_predictors": ["X1", "X2"]},
    )
    assert any(test["id"] == "pc_linear_regression" for test in linear["tests"])


def verify_unavailable_objectives_are_not_faked() -> None:
    df = pd.DataFrame({
        "Outcome": ["Yes", "No"] * 20,
        "Age": list(range(40)),
        "VisitDate": pd.date_range("2020-01-01", periods=40, freq="D"),
    })
    classes = _classes(Outcome="nominal", Age="scale", VisitDate="date")

    prognostic_association = generate_plan(
        df, classes, {"outcome": "Outcome"}, _normality("Age"),
        {
            "study_type": "association",
            "study_type_confirmed": True,
            "objective": "prognostic significance of a marker with clinicopathological association",
            "analysis_predictors": ["Age"],
        },
    )
    assert prognostic_association["study_design"] == "cohort_prognostic"
    assert not any(item["id"] == "survival_inputs_unavailable" for item in prognostic_association["unavailable_tests"])
    assert not any((test.get("_phase_b") or {}).get("test_type") in {"log_rank", "cox_regression"} for test in prognostic_association["tests"])

    survival_missing = generate_plan(
        df, classes, {"outcome": "Outcome"}, _normality(),
        {"study_type": "survival", "study_type_confirmed": True, "objective": "overall survival by group"},
    )
    assert any(item["id"] == "survival_inputs_unavailable" for item in survival_missing["unavailable_tests"])
    assert not any((test.get("_phase_b") or {}).get("test_type") in {"log_rank", "cox_regression"} for test in survival_missing["tests"])

    time_series = generate_plan(
        df, classes, {"outcome": "Age"}, _normality("Age"),
        {"study_type": "time_series", "study_type_confirmed": True, "objective": "forecast trend over time"},
    )
    assert time_series["study_design"] == "time_series"
    assert any(item["id"] == "time_series_unavailable" for item in time_series["unavailable_tests"])
    assert not time_series["tests"] or all("arima" not in str(test).lower() for test in time_series["tests"])


def verify_reliability_kappa_icc_and_bland_altman() -> None:
    df = pd.DataFrame({
        "Rater1": ["A", "B", "A", "C"] * 10,
        "Rater2": ["A", "B", "C", "C"] * 10,
        "OrdinalRater1": ["Mild", "Moderate", "Severe", "Moderate"] * 10,
        "OrdinalRater2": ["Mild", "Moderate", "Moderate", "Severe"] * 10,
        "Method1": [float(i) for i in range(40)],
        "Method2": [float(i) + (0.5 if i % 2 else -0.2) for i in range(40)],
    })
    classes = _classes(
        Rater1="nominal", Rater2="nominal",
        OrdinalRater1="ordinal", OrdinalRater2="ordinal",
        Method1="scale", Method2="scale",
    )
    nominal = generate_plan(
        df, classes, {"outcome": "Rater1"}, _normality(),
        {"study_type": "reliability", "study_type_confirmed": True, "rater_cols": ["Rater1", "Rater2"], "outcome_type": "nominal"},
    )
    assert any((test.get("_phase_b") or {}).get("test_type") == "kappa" for test in nominal["tests"])
    assert next(test for test in nominal["tests"] if test["id"] == "pb_kappa")["_phase_b"]["args"]["weighted"] is False

    ordinal = generate_plan(
        df, classes, {"outcome": "OrdinalRater1"}, _normality(),
        {"study_type": "reliability", "study_type_confirmed": True, "rater_cols": ["OrdinalRater1", "OrdinalRater2"], "outcome_type": "ordinal"},
    )
    assert next(test for test in ordinal["tests"] if test["id"] == "pb_kappa")["_phase_b"]["args"]["weighted"] is True

    continuous = generate_plan(
        df, classes, {"outcome": "Method1"}, _normality("Method1", "Method2"),
        {
            "study_type": "reliability",
            "study_type_confirmed": True,
            "objective": "Bland-Altman method comparison agreement",
            "rater_cols": ["Method1", "Method2"],
            "outcome_type": "scale",
        },
    )
    assert any(test["id"] == "pb_icc_ba" for test in continuous["tests"])
    result = run_plan(df, classes, {"outcome": "Method1"}, continuous, session={"variables": {}})
    icc = next(test for test in result["tests"] if test["id"] == "pb_icc_ba")
    table_titles = {table["title"] for table in icc["tables"]}
    assert "Bland-Altman Agreement" in table_titles
    assert any(fig["title"] == "Bland-Altman plot" for fig in icc["figures"])

    missing_df = pd.DataFrame({"Score": list(range(40)), "Group": ["A", "B"] * 20})
    missing = generate_plan(
        missing_df, _classes(Score="scale", Group="nominal"), {"outcome": "Score"}, _normality("Score"),
        {"study_type": "reliability", "study_type_confirmed": True, "objective": "interrater agreement"},
    )
    assert any(item["id"] == "reliability_inputs_unavailable" for item in missing["unavailable_tests"])


def verify_repeated_measures_guard() -> None:
    df = pd.DataFrame({
        "Subject": list(range(30)),
        "T1": list(range(30)),
        "T2": [i + 1 for i in range(30)],
        "T3": [i + 2 for i in range(30)],
    })
    classes = _classes(Subject="id", T1="scale", T2="scale", T3="scale")
    incomplete = generate_plan(
        df, classes, {"outcome": "T1"}, _normality("T1"),
        {"study_type": "repeated_measures", "study_type_confirmed": True, "design": "repeated_measures"},
    )
    assert any(item["id"] == "repeated_measures_unavailable" for item in incomplete["unavailable_tests"])

    friedman = generate_plan(
        df, classes, {"outcome": "T1"}, _normality(),
        {"study_type": "repeated_measures", "study_type_confirmed": True, "design": "repeated_measures", "timepoints": ["T1", "T2", "T3"]},
    )
    assert any((test.get("_phase_b") or {}).get("test_type") == "friedman" for test in friedman["tests"])


def verify_p27_outcome_guard() -> None:
    df = pd.DataFrame({
        "Positive/ Negative": ["Positive", "Negative"] * 30,
        "PR": ["Positive", "Positive", "Negative"] * 20,
        "Age": list(range(60)),
    })
    classes = _classes(**{"Positive/ Negative": "nominal", "PR": "nominal", "Age": "scale"})
    sigma_plan = generate_plan(
        df, classes, {"outcome": "Positive/ Negative"}, _normality("Age"),
        {"study_type": "association", "study_type_confirmed": True, "analysis_predictors": ["PR", "Age"], "domain_profile": "breast_pathology"},
    )
    titles = " ".join(test["title"] for test in sigma_plan["tests"])
    assert "PR vs Positive/ Negative" in titles
    assert "Age by Positive/ Negative" in titles
    assert "Age by PR" not in titles
    assert all(graph.get("outcome") == "Positive/ Negative" for graph in sigma_plan["graphs"])


def main() -> None:
    verify_support_matrix()
    verify_correlation_routing_and_graph_metadata()
    verify_group_comparison_routing()
    verify_regression_and_forest_rules()
    verify_unavailable_objectives_are_not_faked()
    verify_reliability_kappa_icc_and_bland_altman()
    verify_repeated_measures_guard()
    verify_p27_outcome_guard()
    print("Sigma statistical routing matrix verification passed.")


if __name__ == "__main__":
    main()
