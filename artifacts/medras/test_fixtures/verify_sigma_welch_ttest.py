"""Smoke verification for Sigma Welch t-test reporting.

Run from artifacts/medras:
    python test_fixtures/verify_sigma_welch_ttest.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import results  # noqa: E402


def verify_welch_ttest_reporting() -> None:
    group_a = np.array([8, 9, 10, 11, 12, 13, 14, 15], dtype=float)
    group_b = np.array([4, 7, 11, 18, 26, 35, 47, 60, 74], dtype=float)
    df = pd.DataFrame({
        "value": np.concatenate([group_a, group_b]),
        "group": ["A"] * len(group_a) + ["B"] * len(group_b),
    })

    result = results._ttest_independent(df, "value", "group")
    scipy_t, scipy_p = stats.ttest_ind(group_a, group_b, equal_var=False)

    var_a = float(np.var(group_a, ddof=1))
    var_b = float(np.var(group_b, ddof=1))
    n_a, n_b = len(group_a), len(group_b)
    se_a, se_b = var_a / n_a, var_b / n_b
    expected_df = ((se_a + se_b) ** 2) / ((se_a ** 2) / (n_a - 1) + (se_b ** 2) / (n_b - 1))
    diff = float(np.mean(group_a) - np.mean(group_b))
    se = math.sqrt(se_a + se_b)
    t_crit = float(stats.t.ppf(0.975, df=expected_df))
    expected_ci = (diff - t_crit * se, diff + t_crit * se)
    fixed_196_ci = (diff - 1.96 * se, diff + 1.96 * se)

    assert "df" in result
    assert math.isclose(result["df"], expected_df, rel_tol=1e-12)
    assert math.isclose(result["ci_lo"], expected_ci[0], rel_tol=1e-12)
    assert math.isclose(result["ci_hi"], expected_ci[1], rel_tol=1e-12)
    assert not math.isclose(result["ci_lo"], fixed_196_ci[0], rel_tol=1e-6)
    assert not math.isclose(result["ci_hi"], fixed_196_ci[1], rel_tol=1e-6)
    assert math.isclose(result["p_value"], float(scipy_p), rel_tol=1e-12)

    t_row = next(row for row in result["rows"] if row["label"] == "t statistic")
    df_row = next(row for row in result["rows"] if row["label"] == "Welch df")
    assert math.isclose(float(t_row["value"]), float(scipy_t), abs_tol=0.01)
    assert float(df_row["value"]) > 0


if __name__ == "__main__":
    verify_welch_ttest_reporting()
    print("Sigma Welch t-test verification passed.")
