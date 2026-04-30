"""Normality testing — drives the parametric vs non-parametric routing.

Rule (matches the spec in Phase 4 of the original prompt):

* n < 50              → use Shapiro-Wilk
* 50 ≤ n ≤ 5000       → use Shapiro-Wilk (still well-powered)
* n > 5000            → use Kolmogorov-Smirnov (Shapiro is unreliable at very
  large n and almost always rejects normality, even for trivial deviations).

Decision threshold is α = 0.05. We expose both the p-value and a string
verdict so the UI can colour the row.
"""

from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd
from scipy import stats


def normality_test(values: pd.Series, alpha: float = 0.05) -> Dict[str, Any]:
    """Return a dict with the test name, statistic, p-value and verdict.

    ``values`` is expected to be a numeric Series (NaNs are dropped here).
    Returns ``{"applicable": False, ...}`` for series with < 3 valid points.
    """
    clean = pd.to_numeric(values, errors="coerce").dropna()
    n = int(len(clean))
    if n < 3:
        return {
            "applicable": False,
            "n": n,
            "test": None,
            "statistic": None,
            "p_value": None,
            "is_normal": None,
            "note": "Need at least 3 numeric values for a normality test.",
        }

    try:
        if n > 5000:
            # KS against a fitted normal — standardise first.
            mu, sd = float(clean.mean()), float(clean.std(ddof=1)) or 1.0
            stat, p = stats.kstest((clean - mu) / sd, "norm")
            test_name = "Kolmogorov-Smirnov"
        else:
            stat, p = stats.shapiro(clean)
            test_name = "Shapiro-Wilk"
    except Exception as exc:  # noqa: BLE001
        return {
            "applicable": False,
            "n": n,
            "test": None,
            "statistic": None,
            "p_value": None,
            "is_normal": None,
            "note": f"Normality test failed: {exc}",
        }

    is_normal = bool(p > alpha)
    return {
        "applicable": True,
        "n": n,
        "test": test_name,
        "statistic": float(stat),
        "p_value": float(p),
        "is_normal": is_normal,
        "note": (
            "p > 0.05 → distribution does not significantly differ from normal."
            if is_normal
            else "p ≤ 0.05 → distribution significantly differs from normal — "
            "non-parametric tests will be used."
        ),
    }
