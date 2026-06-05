"""Smoke verification for Sigma P0 statistical routing fixes.

Run from artifacts/medras:
    python test_fixtures/verify_sigma_p0_routing.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import plan, results  # noqa: E402


def _classifications() -> list[dict]:
    return [
        {"column": "age", "detected_type": "scale"},
        {"column": "marker", "detected_type": "scale"},
        {"column": "score", "detected_type": "scale"},
        {"column": "disease", "detected_type": "nominal"},
    ]


def _normality() -> dict:
    return {
        "columns": [
            {"column": "age", "decision": "normal"},
            {"column": "marker", "decision": "normal"},
            {"column": "score", "decision": "normal"},
        ]
    }


def _df() -> pd.DataFrame:
    age = list(range(21, 61))
    return pd.DataFrame(
        {
            "age": age,
            "marker": [v * 1.7 + (i % 5) for i, v in enumerate(age)],
            "score": [35 + v * 0.8 + (i % 4) for i, v in enumerate(age)],
            "disease": [1 if i % 3 == 0 or i % 7 == 0 else 0 for i in range(len(age))],
        }
    )


def verify_correlation_dispatch() -> None:
    df = _df()
    corr_plan = plan.generate_correlation_plan(df, _classifications(), "marker")
    age_pair = next(p for p in corr_plan["pairs"] if p["predictor"] == "age")
    assert age_pair["test_id"] == "corr_spearman"

    corr_results = results.run_correlation_plan(df, _classifications(), corr_plan)
    age_result = next(p for p in corr_results["pairs"] if p["predictor"] == "age")
    test_result = age_result["test_result"]

    assert test_result["test_name"] == "Spearman rank correlation"
    assert test_result["method"] == "spearman"
    assert test_result["stat"] > 0.9
    assert "Chi-square" not in test_result["test_name"]
    assert "Fisher" not in test_result["test_name"]


def verify_regression_ids_execute() -> None:
    df = _df()
    classes = _classifications()

    linear_plan = plan.generate_plan(
        df,
        classes,
        {"outcome": "score", "group": None, "covariates": ["age"]},
        _normality(),
    )
    linear_ids = [t["id"] for t in linear_plan["tests"]]
    assert "pc_linear_regression" in linear_ids
    assert "linear_regression" not in linear_ids
    linear_results = results.run_plan(
        df,
        classes,
        {"outcome": "score", "group": None, "covariates": ["age"]},
        linear_plan,
        session={"variables": {c: {"display_name": c} for c in df.columns}},
    )
    assert any(t["id"] == "pc_linear_regression" for t in linear_results["tests"])

    logistic_plan = plan.generate_plan(
        df,
        classes,
        {"outcome": "disease", "group": None, "covariates": ["age"]},
        _normality(),
    )
    logistic_ids = [t["id"] for t in logistic_plan["tests"]]
    assert "pc_binary_logistic" in logistic_ids
    assert "logistic_regression" not in logistic_ids
    logistic_results = results.run_plan(
        df,
        classes,
        {"outcome": "disease", "group": None, "covariates": ["age"]},
        logistic_plan,
        session={"variables": {c: {"display_name": c} for c in df.columns}},
    )
    assert any(t["id"] == "pc_binary_logistic" for t in logistic_results["tests"])


if __name__ == "__main__":
    verify_correlation_dispatch()
    verify_regression_ids_execute()
    print("Sigma P0 routing verification passed.")
