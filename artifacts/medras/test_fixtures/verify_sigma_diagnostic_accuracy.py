"""Smoke verification for Sigma diagnostic accuracy fixes.

Run from artifacts/medras:
    python test_fixtures/verify_sigma_diagnostic_accuracy.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import results  # noqa: E402


def _scores() -> list[float]:
    negative = [0.05 + i * 0.01 for i in range(30)]
    positive = [0.65 + i * 0.01 for i in range(30)]
    return negative + positive


def _check_auc_result(result: dict, expected_positive) -> None:
    assert "error" not in result, result.get("error")
    assert result["positive_class"] == expected_positive
    assert result["auc"] > 0.95
    assert result["auc_ci_method"] == "bootstrap_percentile"
    assert result["auc_ci"][0] is not None
    assert result["auc_ci"][1] is not None

    wilson_like = results.wilson_ci(int(result["auc"] * result["n"]), result["n"])
    assert tuple(result["auc_ci"]) != tuple(wilson_like)

    for key in (
        "optimal_threshold", "sensitivity", "specificity", "ppv", "npv",
        "accuracy", "lr_positive", "lr_negative", "dor",
    ):
        assert key in result


def verify_numeric_labels() -> None:
    df = pd.DataFrame({
        "disease": [0] * 30 + [1] * 30,
        "score": _scores(),
    })
    result = results.run_diagnostic_accuracy("disease", "score", {}, df)
    _check_auc_result(result, 1)


def verify_string_labels() -> None:
    df = pd.DataFrame({
        "disease": ["Negative"] * 30 + ["Positive"] * 30,
        "score": _scores(),
    })
    result = results.run_diagnostic_accuracy("disease", "score", {}, df)
    _check_auc_result(result, "Positive")


if __name__ == "__main__":
    verify_numeric_labels()
    verify_string_labels()
    print("Sigma diagnostic accuracy verification passed.")
