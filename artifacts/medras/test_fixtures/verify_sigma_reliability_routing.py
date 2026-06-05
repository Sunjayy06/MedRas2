"""Smoke verification for Sigma reliability routing.

Run from artifacts/medras:
    python test_fixtures/verify_sigma_reliability_routing.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import plan  # noqa: E402


def _df() -> pd.DataFrame:
    return pd.DataFrame({
        "rating": [1, 2, 3, 2, 1, 3, 4, 2, 3, 4, 1, 2],
        "rater1": [1, 2, 3, 2, 1, 3, 4, 2, 3, 4, 1, 2],
        "rater2": [1, 2, 2, 2, 1, 3, 4, 3, 3, 4, 1, 2],
        "score": [10.1, 11.2, 12.4, 13.1, 13.8, 15.2, 16.0, 16.7, 18.1, 19.4, 20.2, 21.3],
        "reader1": [10.0, 11.1, 12.5, 13.0, 13.7, 15.4, 15.9, 16.8, 18.0, 19.3, 20.4, 21.2],
        "reader2": [10.2, 11.0, 12.6, 13.2, 13.6, 15.1, 16.1, 16.5, 18.2, 19.5, 20.1, 21.4],
    })


def verify_ordinal_routes_to_weighted_kappa() -> None:
    df = _df()
    classifications = [
        {"column": "rating", "detected_type": "ordinal"},
        {"column": "rater1", "detected_type": "ordinal"},
        {"column": "rater2", "detected_type": "ordinal"},
    ]
    sigma_plan = plan.generate_plan(
        df,
        classifications,
        {"outcome": "rating", "group": None, "covariates": []},
        {"columns": []},
        session={"rater_cols": ["rater1", "rater2"], "outcome_type": "ordinal"},
    )
    reliability_tests = [t for t in sigma_plan["tests"] if t["id"] in ("pb_kappa", "pb_icc_ba")]
    assert len(reliability_tests) == 1
    test = reliability_tests[0]
    assert test["id"] == "pb_kappa"
    assert test["title"] == "Weighted Kappa"
    assert test["_phase_b"]["function"] == "run_kappa"
    assert test["_phase_b"]["args"]["weighted"] is True


def verify_scale_routes_to_icc() -> None:
    df = _df()
    classifications = [
        {"column": "score", "detected_type": "scale"},
        {"column": "reader1", "detected_type": "scale"},
        {"column": "reader2", "detected_type": "scale"},
    ]
    sigma_plan = plan.generate_plan(
        df,
        classifications,
        {"outcome": "score", "group": None, "covariates": []},
        {"columns": [{"column": "score", "decision": "normal"}]},
        session={"rater_cols": ["reader1", "reader2"], "outcome_type": "scale"},
    )
    reliability_tests = [t for t in sigma_plan["tests"] if t["id"] in ("pb_kappa", "pb_icc_ba")]
    assert len(reliability_tests) == 1
    test = reliability_tests[0]
    assert test["id"] == "pb_icc_ba"
    assert test["_phase_b"]["function"] == "run_icc_bland_altman"


if __name__ == "__main__":
    verify_ordinal_routes_to_weighted_kappa()
    verify_scale_routes_to_icc()
    print("Sigma reliability routing verification passed.")
