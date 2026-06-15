"""Verify Sigma objective-aware planning without adding new statistics."""

from __future__ import annotations

import pandas as pd

from app.services.plan import generate_plan, generate_correlation_plan
from app.services.results import run_plan


def _classes(**types):
    return [{"column": column, "detected_type": detected} for column, detected in types.items()]


def _normality(*normal_columns):
    return {
        "columns": [
            {"column": column, "decision": "normal"}
            for column in normal_columns
        ]
    }


def _functions(plan):
    return {
        test.get("_phase_b", {}).get("function")
        for test in plan["tests"]
        if test.get("_phase_b")
    }


def verify_binary_association_routes_by_predictor_type():
    df = pd.DataFrame({
        "PR": ["Positive", "Negative"] * 40,
        "ER": ["Positive", "Positive", "Negative", "Negative"] * 20,
        "Age": list(range(40, 120)),
        "node_ratio": [value / 100 for value in range(80)],
    })
    classes = _classes(PR="nominal", ER="nominal", Age="scale", node_ratio="scale")
    session = {
        "study_type": "association",
        "study_type_confirmed": True,
        "analysis_predictors": ["ER", "Age", "node_ratio"],
    }
    plan = generate_plan(df, classes, {"outcome": "PR"}, _normality("Age"), session)
    functions = _functions(plan)
    assert "run_chi_or_fisher" in functions
    assert "run_pairwise_welch" in functions
    assert "run_pairwise_mann_whitney" in functions
    assert not any(test["id"] == "pc_binary_logistic" for test in plan["tests"])
    assert any(item["id"] == "suggest_binary_logistic" for item in plan["suggestions"])
    assert any(item["id"] == "suggest_correlation_matrix" for item in plan["suggestions"])

    results = run_plan(
        df, classes, {"outcome": "PR"}, plan,
        confirmed_graph_ids=[], session=session,
    )
    assert len(results["tests"]) == len(plan["tests"])
    assert any(test["test_type"] == "welch_ttest" for test in results["tests"])
    assert all(test.get("analysis_family") == "bivariate" for test in results["tests"])


def verify_scale_outcome_and_correlation_objective():
    df = pd.DataFrame({
        "Score": list(range(1, 61)),
        "Age": list(range(31, 91)),
        "Group": ["A", "B", "C"] * 20,
    })
    classes = _classes(Score="scale", Age="scale", Group="nominal")
    association = generate_plan(
        df, classes, {"outcome": "Score"}, _normality("Score"),
        {
            "study_type": "association",
            "study_type_confirmed": True,
            "analysis_predictors": ["Age", "Group"],
        },
    )
    assert "run_pairwise_anova" in _functions(association)
    assert not any(test.get("analysis_family") == "correlation" for test in association["tests"])

    correlation = generate_plan(
        df, classes, {"outcome": "Score"}, _normality("Score", "Age"),
        {
            "study_type": "correlation",
            "study_type_confirmed": True,
            "analysis_predictors": ["Age", "Group"],
        },
    )
    assert len(correlation["tests"]) == 1
    assert correlation["tests"][0]["_phase_b"]["function"] == "pc_pearson"
    assert correlation["tests"][0]["analysis_family"] == "correlation"

    legacy_correlation = generate_correlation_plan(df, classes, "Score")
    assert any(pair["predictor"] == "Age" and pair["test_id"] == "corr_spearman"
               for pair in legacy_correlation["pairs"])
    assert any(item["column"] == "Group" and "excluded" in item["reason"]
               for item in legacy_correlation["excluded"])


def verify_regression_requires_objective_and_checks_events():
    df = pd.DataFrame({
        "Outcome": ["No", "Yes"] * 50,
        "X1": list(range(100)),
        "X2": [value / 2 for value in range(100)],
        "ScaleOutcome": [value * 1.5 for value in range(100)],
    })
    classes = _classes(Outcome="nominal", X1="scale", X2="scale", ScaleOutcome="scale")
    session = {
        "study_type": "regression",
        "study_type_confirmed": True,
        "analysis_predictors": ["X1", "X2"],
    }
    logistic = generate_plan(df, classes, {"outcome": "Outcome"}, _normality(), session)
    assert any(test["id"] == "pc_binary_logistic" for test in logistic["tests"])
    assert any(test.get("analysis_family") == "regression" for test in logistic["tests"])

    linear = generate_plan(df, classes, {"outcome": "ScaleOutcome"}, _normality(), session)
    assert any(test["id"] == "pc_linear_regression" for test in linear["tests"])

    sparse = df.copy()
    sparse["Outcome"] = ["Yes"] * 12 + ["No"] * 88
    sparse_plan = generate_plan(sparse, classes, {"outcome": "Outcome"}, _normality(), session)
    assert not any(test["id"] == "pc_binary_logistic" for test in sparse_plan["tests"])
    assert any(item["id"] == "binary_logistic_sparse_warning" for item in sparse_plan["suggestions"])


def verify_layered_plan_and_confirmed_outcome():
    df = pd.DataFrame({
        "PR": ["Positive", "Negative"] * 20,
        "p27_status": ["Positive", "Negative", "Positive", "Positive"] * 10,
        "Age": list(range(40, 80)),
    })
    classes = _classes(PR="nominal", p27_status="nominal", Age="scale")

    no_outcome = generate_plan(
        df, classes, {}, _normality("Age"),
        {"study_type": "association", "analysis_predictors": ["PR", "Age"]},
    )
    assert no_outcome["analysis_layers"]["descriptive"]
    assert no_outcome["analysis_layers"]["bivariate"] == []
    assert no_outcome["analysis_layers"]["multivariate"] == []
    assert no_outcome["main_outcome"] is None
    assert no_outcome["requires_confirmation"] is True

    p27 = generate_plan(
        df, classes, {"outcome": "p27_status"}, _normality("Age"),
        {
            "study_type": "association",
            "study_type_confirmed": True,
            "analysis_predictors": ["PR", "Age"],
        },
    )
    assert p27["main_outcome"] == "p27_status"
    assert p27["main_outcome"] != "PR"
    assert p27["analysis_layers"]["descriptive"]
    assert p27["analysis_layers"]["bivariate"]


def verify_low_events_and_special_objectives():
    df = pd.DataFrame({
        "Outcome": ["Yes"] * 12 + ["No"] * 88,
        "Age": list(range(100)),
        "Score": [value / 10 for value in range(100)],
        "T1": list(range(100)),
        "T2": [value + 1 for value in range(100)],
        "T3": [value + 2 for value in range(100)],
    })
    classes = _classes(
        Outcome="nominal", Age="scale", Score="scale",
        T1="scale", T2="scale", T3="scale",
    )
    low_events = generate_plan(
        df, classes, {"outcome": "Outcome"}, _normality(),
        {
            "study_type": "regression",
            "study_type_confirmed": True,
            "analysis_predictors": ["Age", "Score", "T1"],
        },
    )
    assert any("smaller outcome class" in note.lower() for note in low_events["eligibility_notes"])
    assert any("limited to 1 predictor" in warning for warning in low_events["warnings"])
    assert any(
        item.get("execution_status") == "recommended_only"
        for item in low_events["analysis_layers"]["multivariate"]
    )
    recommendation = next(
        item for item in low_events["analysis_layers"]["multivariate"]
        if item.get("execution_status") == "recommended_only"
    )
    assert len(recommendation["columns"]) == 2  # outcome + one EPV-eligible predictor
    assert low_events["requires_confirmation"] is True

    diagnostic = generate_plan(
        df, classes, {"outcome": "Outcome"}, _normality(),
        {
            "study_type": "diagnostic",
            "study_type_confirmed": True,
            "disease_col": "Outcome",
            "test_result_col": "Score",
        },
    )
    assert any(
        (test.get("_phase_b") or {}).get("test_type") == "diagnostic_accuracy"
        for test in diagnostic["tests"]
    )

    repeated = generate_plan(
        df, classes, {"outcome": "T1"}, _normality(),
        {
            "study_type": "repeated_measures",
            "design": "repeated_measures",
            "timepoints": ["T1", "T2", "T3"],
        },
    )
    assert repeated["study_design"] == "repeated_measures"
    assert any(
        (test.get("_phase_b") or {}).get("test_type") == "friedman"
        for test in repeated["tests"]
    )

    repeated_incomplete = generate_plan(
        df[["Outcome", "Age", "Score"]],
        _classes(Outcome="nominal", Age="scale", Score="scale"),
        {"outcome": "Score"}, _normality(),
        {"study_type": "repeated_measures", "design": "repeated_measures"},
    )
    assert any(
        item["id"] == "repeated_measures_unavailable"
        for item in repeated_incomplete["unavailable_tests"]
    )


def main():
    verify_binary_association_routes_by_predictor_type()
    verify_scale_outcome_and_correlation_objective()
    verify_regression_requires_objective_and_checks_events()
    verify_layered_plan_and_confirmed_outcome()
    verify_low_events_and_special_objectives()
    print("Sigma objective-aware planner verification passed.")


if __name__ == "__main__":
    main()
