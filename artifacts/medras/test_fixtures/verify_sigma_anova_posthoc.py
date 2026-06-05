"""Smoke verification for Sigma ANOVA post-hoc routing.

Run from artifacts/medras:
    python test_fixtures/verify_sigma_anova_posthoc.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import plan, results  # noqa: E402


def _df() -> pd.DataFrame:
    group_a = [8, 9, 10, 11, 12, 13, 14, 15]
    group_b = [20, 21, 22, 23, 24, 25, 26, 27]
    group_c = [35, 36, 37, 38, 39, 40, 41, 42]
    return pd.DataFrame({
        "score": group_a + group_b + group_c,
        "arm": ["A"] * len(group_a) + ["B"] * len(group_b) + ["C"] * len(group_c),
    })


def verify_anova_posthoc_executes() -> None:
    df = _df()
    classifications = [
        {"column": "score", "detected_type": "scale"},
        {"column": "arm", "detected_type": "nominal"},
    ]
    normality = {"columns": [{"column": "score", "decision": "normal"}]}
    assignment = {"outcome": "score", "group": "arm", "covariates": []}

    sigma_plan = plan.generate_plan(df, classifications, assignment, normality)
    test_ids = [t["id"] for t in sigma_plan["tests"]]
    assert "anova_oneway" in test_ids
    assert "pc_tukey_hsd" in test_ids
    assert "tukey_hsd" not in test_ids

    tukey_plan = next(t for t in sigma_plan["tests"] if t["id"] == "pc_tukey_hsd")
    assert tukey_plan["_phase_b"]["function"] == "pc_tukey_hsd"
    assert tukey_plan["_phase_b"]["args"] == {"outcome": "score", "group": "arm"}

    sigma_results = results.run_plan(df, classifications, assignment, sigma_plan)
    result_ids = [t["id"] for t in sigma_results["tests"]]
    assert "anova_oneway" in result_ids
    assert "pc_tukey_hsd" in result_ids

    tukey_result = next(t for t in sigma_results["tests"] if t["id"] == "pc_tukey_hsd")
    assert tukey_result["test_type"] == "tukey_hsd"
    assert tukey_result["rows"]
    assert any(row["significant"] for row in tukey_result["rows"])


def verify_nonparametric_path_does_not_force_tukey() -> None:
    df = _df()
    classifications = [
        {"column": "score", "detected_type": "scale"},
        {"column": "arm", "detected_type": "nominal"},
    ]
    normality = {"columns": [{"column": "score", "decision": "non_normal"}]}
    assignment = {"outcome": "score", "group": "arm", "covariates": []}

    sigma_plan = plan.generate_plan(df, classifications, assignment, normality)
    test_ids = [t["id"] for t in sigma_plan["tests"]]
    assert "kruskal_wallis" in test_ids
    assert "pc_tukey_hsd" not in test_ids


if __name__ == "__main__":
    verify_anova_posthoc_executes()
    verify_nonparametric_path_does_not_force_tukey()
    print("Sigma ANOVA post-hoc verification passed.")
