"""Normality testing — drives the parametric vs non-parametric routing.

Per spec (Step 5):

* n < 50              → use Shapiro-Wilk
* 50 ≤ n ≤ 2000       → use Lilliefors when available; otherwise Shapiro-Wilk.
* n > 2000            → SKIP the formal test; do not auto-mark normal.
* |skew| > 2 OR |kurt| > 7  → flag as non-normal regardless of p-value.
* If non-normal AND values are strictly positive AND a log transform
  fixes the shape rules, recommend the log-transform.

The function returns one structured dict per scale variable, plus a
QQ-plot PNG (base64) so the UI can render thumbnails inline.
"""

from __future__ import annotations

import base64
import io
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


# Spec thumb-rule cut-offs.
_SKEW_LIMIT = 2.0
_KURT_LIMIT = 7.0
_SHAPIRO_MAX = 50
_KS_MAX = 2000


def _qq_png(values: np.ndarray) -> Optional[str]:
    """Return a base64-encoded PNG of a QQ plot, or None on error."""
    try:
        fig, ax = plt.subplots(figsize=(2.4, 2.4), dpi=80)
        stats.probplot(values, dist="norm", plot=ax)
        ax.set_title("")
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.tick_params(labelsize=7)
        for line in ax.get_lines():
            line.set_markersize(3)
        fig.tight_layout(pad=0.2)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        plt.close("all")
        return None


def _decision(p_value: Optional[float], skew: Optional[float],
              kurt: Optional[float], n: int, alpha: float = 0.05) -> str:
    """Return one of: 'normal', 'non_normal', 'skipped', 'insufficient'."""
    if n < 3:
        return "insufficient"
    if skew is not None and abs(skew) > _SKEW_LIMIT:
        return "non_normal"
    if kurt is not None and abs(kurt) > _KURT_LIMIT:
        return "non_normal"
    if p_value is None:
        # Formal test was skipped; do not treat this as confirmed normality.
        return "skipped"
    return "normal" if p_value > alpha else "non_normal"


def _run_test(clean: np.ndarray) -> Dict[str, Any]:
    """Pick the right test for the sample size and return its output."""
    n = int(len(clean))
    if n < 3:
        return {"test": None, "statistic": None, "p_value": None, "skipped": False}
    if n > _KS_MAX:
        # Per spec: skip the formal test for very large n — Shapiro/KS
        # both reject for trivially small departures at this size.
        return {"test": "Skipped (n > 2000)", "statistic": None, "p_value": None, "skipped": True}
    try:
        if n < _SHAPIRO_MAX:
            stat, p = stats.shapiro(clean)
            test_name = "Shapiro-Wilk"
        else:
            try:
                from statsmodels.stats.diagnostic import lilliefors

                stat, p = lilliefors(clean, dist="norm")
                test_name = "Lilliefors"
            except Exception:
                stat, p = stats.shapiro(clean)
                test_name = "Shapiro-Wilk"
        return {
            "test": test_name,
            "statistic": float(stat),
            "p_value": float(p),
            "skipped": False,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "test": None, "statistic": None, "p_value": None,
            "skipped": False, "error": str(exc),
        }


def normality_test(values: pd.Series, alpha: float = 0.05,
                   include_qq: bool = True) -> Dict[str, Any]:
    """Single-column normality test with skew/kurt + log fallback.

    Returns the structured dict expected by ``screen-5`` on the
    frontend. ``values`` is a numeric Series — non-numeric / NaN
    entries are dropped before testing.
    """
    clean = pd.to_numeric(values, errors="coerce").dropna().to_numpy()
    n = int(len(clean))
    if n < 3:
        return {
            "applicable": False, "n": n, "decision": "insufficient",
            "test": None, "statistic": None, "p_value": None,
            "skewness": None, "kurtosis": None,
            "log_transform_helps": False, "qq_png": None,
            "note": "Need at least 3 numeric values for a normality test.",
        }

    skew_v = float(stats.skew(clean, bias=False)) if n >= 3 else None
    # Excess kurtosis (so 0 == normal, > 7 == very heavy tails per spec).
    kurt_v = float(stats.kurtosis(clean, fisher=True, bias=False)) if n >= 4 else None

    base = _run_test(clean)
    decision = _decision(base.get("p_value"), skew_v, kurt_v, n, alpha)

    # Log-transform fallback: only meaningful for strictly-positive data
    # because log requires x > 0. We try it when the raw column failed
    # the shape rules and report whether it would have passed.
    log_helps = False
    log_decision = None
    log_skew = None
    log_kurt = None
    log_p = None
    if decision == "non_normal" and bool(np.all(clean > 0)):
        try:
            logged = np.log(clean)
            log_skew = float(stats.skew(logged, bias=False))
            log_kurt = float(stats.kurtosis(logged, fisher=True, bias=False))
            log_run = _run_test(logged)
            log_p = log_run.get("p_value")
            log_decision = _decision(log_p, log_skew, log_kurt, n, alpha)
            log_helps = log_decision == "normal"
        except Exception:
            log_helps = False
            log_decision = None

    # Build a researcher-readable note that summarises the verdict.
    if decision == "skipped":
        note = (
            f"n = {n} > 2000 - formal normality testing was skipped because "
            "large-sample tests can over-reject trivial departures. Skewness "
            "and kurtosis are acceptable, but normality was not confirmed."
        )
    elif decision == "normal":
        note = "Distribution is approximately normal — parametric tests are appropriate."
    elif decision == "non_normal":
        if log_helps:
            note = (
                "Distribution is non-normal as-is, but a log-transform fixes "
                "it. Either use the log-transformed values for parametric "
                "tests, or fall back to non-parametric tests on the raw "
                "values."
            )
        else:
            note = "Distribution is non-normal — non-parametric tests will be used."
    else:
        note = base.get("error") or "Could not assess normality."

    return {
        "applicable": True,
        "n": n,
        "decision": decision,                # normal | non_normal | skipped | insufficient
        "test": base.get("test"),
        "statistic": base.get("statistic"),
        "p_value": base.get("p_value"),
        "skewness": skew_v,
        "kurtosis": kurt_v,
        "log_transform_helps": bool(log_helps),
        "log_p_value": log_p,
        "log_skewness": log_skew,
        "log_kurtosis": log_kurt,
        "qq_png": _qq_png(clean) if include_qq else None,
        "note": note,
    }


def normality_for_dataset(df: pd.DataFrame, classifications: List[Dict[str, Any]],
                          include_qq: bool = True) -> Dict[str, Any]:
    """Run normality tests on every scale column in the dataset.

    Returns ``{"columns": [{column, ...test result...}, ...]}`` ordered
    to match the ``classifications`` argument so the UI can render them
    in the same order they appear on Step 3.
    """
    out: List[Dict[str, Any]] = []
    for c in classifications:
        if c.get("detected_type") != "scale":
            continue
        col = c.get("column")
        if not col or col not in df.columns:
            continue
        result = normality_test(df[col], include_qq=include_qq)
        result["column"] = col
        result["scale_subtype"] = c.get("scale_subtype")
        out.append(result)
    return {"columns": out}
