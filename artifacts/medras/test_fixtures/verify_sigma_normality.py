"""Smoke verification for Sigma normality decisions.

Run from artifacts/medras:
    python test_fixtures/verify_sigma_normality.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import normality  # noqa: E402


def _normal_quantiles(n: int) -> pd.Series:
    probs = np.linspace(0.01, 0.99, n)
    return pd.Series(stats.norm.ppf(probs))


def verify_small_sample_uses_shapiro() -> None:
    result = normality.normality_test(_normal_quantiles(30), include_qq=False)
    assert result["n"] == 30
    assert result["test"] == "Shapiro-Wilk"
    assert result["decision"] == "normal"


def verify_medium_sample_avoids_plain_ks() -> None:
    result = normality.normality_test(_normal_quantiles(200), include_qq=False)
    assert result["n"] == 200
    assert result["test"] in {"Lilliefors", "Shapiro-Wilk"}
    assert result["test"] != "Kolmogorov-Smirnov"
    assert result["decision"] in {"normal", "non_normal"}


def verify_large_sample_is_not_auto_normal() -> None:
    result = normality.normality_test(_normal_quantiles(2501), include_qq=False)
    assert result["n"] == 2501
    assert result["test"] == "Skipped (n > 2000)"
    assert result["p_value"] is None
    assert result["decision"] == "skipped"
    assert "not confirmed" in result["note"]


def verify_large_skewed_sample_is_non_normal() -> None:
    result = normality.normality_test(pd.Series(np.exp(np.linspace(0, 8, 2501))), include_qq=False)
    assert result["n"] == 2501
    assert result["test"] == "Skipped (n > 2000)"
    assert result["decision"] == "non_normal"


if __name__ == "__main__":
    verify_small_sample_uses_shapiro()
    verify_medium_sample_avoids_plain_ks()
    verify_large_sample_is_not_auto_normal()
    verify_large_skewed_sample_is_non_normal()
    print("Sigma normality verification passed.")
