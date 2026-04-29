"""Sample-size calculation engine.

All computation is done in pure Python with explicit, well-known formulas so
that every number on screen can be traced back to its inputs. Each public
function returns a structured ``SampleSizeResult`` containing:

* ``formula``       — short identifier (e.g. ``"two_proportions"``)
* ``formula_label`` — human-readable name shown in the UI
* ``formula_expression`` — the actual symbolic expression used
* ``n_per_group``   — minimum n per arm (integer, rounded up)
* ``total_n``       — minimum total participants (integer, rounded up)
* ``adjusted_n``    — total n after dropout / non-response adjustment
* ``inputs``        — exactly the values the researcher supplied
* ``constants``     — derived values (Z-alpha, Z-beta, p_bar, ...)
* ``notes``         — short interpretation lines for the researcher

LLMs are never used for these numbers. The Sample Size module is the
"statistical-rigour" module — values must be reproducible from the formula.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .normal import z_power, z_two_tailed


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class SampleSizeResult:
    formula: str
    formula_label: str
    formula_expression: str
    n_per_group: int
    number_of_groups: int
    total_n: int
    adjusted_n: int
    inputs: Dict[str, Any]
    constants: Dict[str, float]
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ceil(x: float) -> int:
    if not math.isfinite(x) or x <= 0:
        raise ValueError("Calculated n is non-positive or infinite — check inputs.")
    return int(math.ceil(x))


def _apply_dropout(total: int, dropout: float) -> int:
    """Inflate ``total`` to absorb the expected dropout / non-response rate."""
    if dropout < 0 or dropout >= 1:
        raise ValueError("dropout must be in [0, 1).")
    if dropout == 0:
        return total
    return _ceil(total / (1 - dropout))


def _check_alpha(alpha: float) -> None:
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1).")


def _check_power(power: float) -> None:
    if not 0 < power < 1:
        raise ValueError("power must be in (0, 1).")


def _round_constants(d: Dict[str, float]) -> Dict[str, float]:
    return {k: round(v, 4) for k, v in d.items()}


# ---------------------------------------------------------------------------
# 1. Single proportion (descriptive prevalence study)
# ---------------------------------------------------------------------------


def single_proportion(
    p: float,
    precision: float,
    alpha: float = 0.05,
    dropout: float = 0.0,
) -> SampleSizeResult:
    """n = Z²α/2 · p(1-p) / d²  (Cochran, single sample, finite precision)."""
    _check_alpha(alpha)
    if not 0 < p < 1:
        raise ValueError("Expected proportion p must be in (0, 1).")
    if not 0 < precision < 1:
        raise ValueError("Absolute precision d must be in (0, 1).")
    z_a = z_two_tailed(alpha)
    n = (z_a ** 2) * p * (1 - p) / (precision ** 2)
    n_total = _ceil(n)
    return SampleSizeResult(
        formula="single_proportion",
        formula_label="Single proportion (one-sample prevalence)",
        formula_expression="n = Z²(α/2) × p × (1 − p) / d²",
        n_per_group=n_total,
        number_of_groups=1,
        total_n=n_total,
        adjusted_n=_apply_dropout(n_total, dropout),
        inputs={
            "expected_proportion": p,
            "absolute_precision": precision,
            "alpha": alpha,
            "dropout_rate": dropout,
        },
        constants=_round_constants({"Z_alpha_over_2": z_a, "p_q": p * (1 - p)}),
        notes=[
            "Use this when the objective is to estimate a single prevalence or "
            "proportion with a chosen margin of error.",
        ],
    )


# ---------------------------------------------------------------------------
# 2. Single mean
# ---------------------------------------------------------------------------


def single_mean(
    sigma: float,
    precision: float,
    alpha: float = 0.05,
    dropout: float = 0.0,
) -> SampleSizeResult:
    """n = (Zα/2 · σ / d)²"""
    _check_alpha(alpha)
    if sigma <= 0:
        raise ValueError("Standard deviation σ must be positive.")
    if precision <= 0:
        raise ValueError("Precision d must be positive.")
    z_a = z_two_tailed(alpha)
    n = (z_a * sigma / precision) ** 2
    n_total = _ceil(n)
    return SampleSizeResult(
        formula="single_mean",
        formula_label="Single mean (one-sample, continuous outcome)",
        formula_expression="n = (Z(α/2) × σ / d)²",
        n_per_group=n_total,
        number_of_groups=1,
        total_n=n_total,
        adjusted_n=_apply_dropout(n_total, dropout),
        inputs={
            "standard_deviation": sigma,
            "absolute_precision": precision,
            "alpha": alpha,
            "dropout_rate": dropout,
        },
        constants=_round_constants({"Z_alpha_over_2": z_a}),
        notes=[
            "Use this to estimate a single mean (e.g., mean BMI in a "
            "population) within a chosen precision.",
        ],
    )


# ---------------------------------------------------------------------------
# 3. Two independent proportions
# ---------------------------------------------------------------------------


def two_proportions(
    p1: float,
    p2: float,
    alpha: float = 0.05,
    power: float = 0.80,
    dropout: float = 0.0,
) -> SampleSizeResult:
    """Pooled-variance formula for comparing two independent proportions.

    n_per_group = [Zα/2·√(2·p̄·q̄) + Zβ·√(p1·q1 + p2·q2)]² / (p1 − p2)²
    """
    _check_alpha(alpha)
    _check_power(power)
    for value, name in ((p1, "p1"), (p2, "p2")):
        if not 0 < value < 1:
            raise ValueError(f"{name} must be in (0, 1).")
    if p1 == p2:
        raise ValueError("p1 and p2 must differ — there is no effect to detect.")
    z_a = z_two_tailed(alpha)
    z_b = z_power(power)
    p_bar = (p1 + p2) / 2
    q_bar = 1 - p_bar
    q1, q2 = 1 - p1, 1 - p2
    numerator = (
        z_a * math.sqrt(2 * p_bar * q_bar) + z_b * math.sqrt(p1 * q1 + p2 * q2)
    ) ** 2
    n_each = _ceil(numerator / (p1 - p2) ** 2)
    total = n_each * 2
    return SampleSizeResult(
        formula="two_proportions",
        formula_label="Two independent proportions (group comparison)",
        formula_expression=(
            "n/group = [Z(α/2)·√(2·p̄·q̄) + Z(β)·√(p1·q1 + p2·q2)]² / (p1 − p2)²"
        ),
        n_per_group=n_each,
        number_of_groups=2,
        total_n=total,
        adjusted_n=_apply_dropout(total, dropout),
        inputs={
            "p1": p1,
            "p2": p2,
            "alpha": alpha,
            "power": power,
            "dropout_rate": dropout,
        },
        constants=_round_constants(
            {
                "Z_alpha_over_2": z_a,
                "Z_beta": z_b,
                "p_bar": p_bar,
                "effect_size_diff": abs(p1 - p2),
            }
        ),
        notes=[
            "Use this for case-control or two-arm interventional studies with "
            "a binary outcome (e.g., cure vs. no cure).",
        ],
    )


# ---------------------------------------------------------------------------
# 4. Two independent means
# ---------------------------------------------------------------------------


def two_means(
    mean1: float,
    mean2: float,
    sigma: float,
    alpha: float = 0.05,
    power: float = 0.80,
    dropout: float = 0.0,
) -> SampleSizeResult:
    """n_per_group = 2·σ²·(Zα/2 + Zβ)² / (μ1 − μ2)²  (equal SDs assumed)."""
    _check_alpha(alpha)
    _check_power(power)
    if sigma <= 0:
        raise ValueError("σ must be positive.")
    if mean1 == mean2:
        raise ValueError("Means must differ — there is no effect to detect.")
    z_a = z_two_tailed(alpha)
    z_b = z_power(power)
    delta = mean1 - mean2
    n_each = _ceil(2 * (sigma ** 2) * ((z_a + z_b) ** 2) / (delta ** 2))
    total = n_each * 2
    return SampleSizeResult(
        formula="two_means",
        formula_label="Two independent means (group comparison)",
        formula_expression="n/group = 2·σ²·(Z(α/2) + Z(β))² / (μ1 − μ2)²",
        n_per_group=n_each,
        number_of_groups=2,
        total_n=total,
        adjusted_n=_apply_dropout(total, dropout),
        inputs={
            "mean1": mean1,
            "mean2": mean2,
            "standard_deviation": sigma,
            "alpha": alpha,
            "power": power,
            "dropout_rate": dropout,
        },
        constants=_round_constants(
            {
                "Z_alpha_over_2": z_a,
                "Z_beta": z_b,
                "effect_size_diff": abs(delta),
                "cohens_d": abs(delta) / sigma,
            }
        ),
        notes=[
            "Use this for two-arm trials with a continuous outcome (e.g., "
            "mean blood pressure between treatment vs control).",
            "Assumes equal standard deviations in both groups.",
        ],
    )


# ---------------------------------------------------------------------------
# 5. Paired means (matched / before-after)
# ---------------------------------------------------------------------------


def paired_means(
    mean_diff: float,
    sigma_diff: float,
    alpha: float = 0.05,
    power: float = 0.80,
    dropout: float = 0.0,
) -> SampleSizeResult:
    """n = (Zα/2 + Zβ)² · σ_d² / Δ²"""
    _check_alpha(alpha)
    _check_power(power)
    if sigma_diff <= 0:
        raise ValueError("σ of differences must be positive.")
    if mean_diff == 0:
        raise ValueError("Expected mean difference must be non-zero.")
    z_a = z_two_tailed(alpha)
    z_b = z_power(power)
    n = ((z_a + z_b) ** 2) * (sigma_diff ** 2) / (mean_diff ** 2)
    n_total = _ceil(n)
    return SampleSizeResult(
        formula="paired_means",
        formula_label="Paired means (before–after / matched pairs)",
        formula_expression="n = (Z(α/2) + Z(β))² · σ_d² / Δ²",
        n_per_group=n_total,
        number_of_groups=1,
        total_n=n_total,
        adjusted_n=_apply_dropout(n_total, dropout),
        inputs={
            "expected_mean_difference": mean_diff,
            "sd_of_differences": sigma_diff,
            "alpha": alpha,
            "power": power,
            "dropout_rate": dropout,
        },
        constants=_round_constants(
            {
                "Z_alpha_over_2": z_a,
                "Z_beta": z_b,
                "effect_size_dz": abs(mean_diff) / sigma_diff,
            }
        ),
        notes=[
            "Use this for pre-post designs or matched pairs (e.g., same "
            "patient measured before and after treatment).",
        ],
    )


# ---------------------------------------------------------------------------
# 6. ANOVA — three or more groups (approximation)
# ---------------------------------------------------------------------------


def anova_means(
    k: int,
    effect_size_f: float,
    alpha: float = 0.05,
    power: float = 0.80,
    dropout: float = 0.0,
) -> SampleSizeResult:
    """Per-group n for k-group one-way ANOVA, using a normal-approximation:

        n_per_group ≈ (Z(α/2) + Z(β))² / (k · f²) + 1

    The +1 absorbs a small bias vs. the noncentral-F exact value. For more
    precise calculation we will integrate ``statsmodels`` later.

    f is Cohen's effect size: small=0.10, medium=0.25, large=0.40.
    """
    _check_alpha(alpha)
    _check_power(power)
    # Coerce to int and reject fractional k (e.g. 3.7) early so the response
    # model never sees a float in an integer-only field.
    if isinstance(k, bool) or not isinstance(k, (int, float)):
        raise ValueError("k must be a number.")
    if isinstance(k, float) and not k.is_integer():
        raise ValueError("k must be a whole number of groups.")
    k = int(k)
    if k < 3:
        raise ValueError("ANOVA requires k ≥ 3 groups.")
    if effect_size_f <= 0:
        raise ValueError("Cohen's f must be positive.")
    z_a = z_two_tailed(alpha)
    z_b = z_power(power)
    n_each = _ceil(((z_a + z_b) ** 2) / (k * effect_size_f ** 2) + 1)
    total = n_each * k
    return SampleSizeResult(
        formula="anova_means",
        formula_label=f"One-way ANOVA ({k} groups)",
        formula_expression="n/group ≈ (Z(α/2) + Z(β))² / (k·f²) + 1",
        n_per_group=n_each,
        number_of_groups=k,
        total_n=total,
        adjusted_n=_apply_dropout(total, dropout),
        inputs={
            "number_of_groups": k,
            "cohens_f": effect_size_f,
            "alpha": alpha,
            "power": power,
            "dropout_rate": dropout,
        },
        constants=_round_constants({"Z_alpha_over_2": z_a, "Z_beta": z_b}),
        notes=[
            "ANOVA estimate uses a normal-approximation. Cohen's f "
            "conventions: small = 0.10, medium = 0.25, large = 0.40.",
            "For final, exact n use a noncentral-F calculation (will be "
            "added when the Statistical Analysis Engine ships).",
        ],
    )


# ===========================================================================
# REVERSE MODE — back-calculate the smallest effect detectable from a fixed n.
# ---------------------------------------------------------------------------
# Every reverse_* function returns the same dict shape so the API/frontend
# can render any of them through one generic component:
#
#   {
#       "formula": str,
#       "mode": "reverse",
#       "formula_label": str,
#       "formula_expression": str,   # the symbolic form that was inverted
#       "inputs": dict,              # what the researcher supplied
#       "constants": dict,           # derived Z-values, etc.
#       "headline": [                # 1-3 stats to feature at top of result
#           {"label": str, "value": str, "sublabel": str | None}
#       ],
#       "detectable": dict,          # raw, machine-readable solved values
#       "notes": [str, ...],
#       "warnings": [str, ...],
#   }
#
# Reverse mode is uniformly available for all 6 formulas. Where multiple
# unknowns exist (two_proportions has both p2 < p1 and p2 > p1 solutions),
# the function returns each one separately and warns if a direction is
# undetectable.
# ===========================================================================


def _coerce_n(n: Any, name: str = "n", minimum: int = 4) -> int:
    """Validate and coerce a sample-size argument used by reverse functions."""
    if isinstance(n, bool) or not isinstance(n, (int, float)):
        raise ValueError(f"{name} must be a number.")
    if isinstance(n, float) and not n.is_integer():
        raise ValueError(f"{name} must be a whole number.")
    n_int = int(n)
    if n_int < minimum:
        raise ValueError(
            f"{name} must be at least {minimum} to be analytically meaningful."
        )
    return n_int


def _analyzable(n: int, dropout: float) -> int:
    """Apply dropout to the available recruited n, floor to whole people."""
    if dropout < 0 or dropout >= 1:
        raise ValueError("dropout must be in [0, 1).")
    n_keep = int(math.floor(n * (1 - dropout)))
    if n_keep < 4:
        raise ValueError(
            "After applying the dropout rate, fewer than 4 analysable "
            "participants remain. Recruit more or lower dropout."
        )
    return n_keep


def _dropout_note(n_recruited: int, n_kept: int, dropout: float) -> Optional[str]:
    if dropout <= 0:
        return None
    return (
        f"Dropout deflated your recruited n ({n_recruited}) to "
        f"{n_kept} analysable before back-calculation."
    )


def _format_pct(v: float) -> str:
    return f"{v * 100:.2f}%  ({v:.4f})"


# ---------------------------------------------------------------------------
# Reverse 1 — single proportion: solve d (precision) given n
# ---------------------------------------------------------------------------


def reverse_single_proportion(
    p: float,
    n: int,
    alpha: float = 0.05,
    dropout: float = 0.0,
) -> Dict[str, Any]:
    """Solve  n = Z²·p(1−p)/d²  for d:   d = Z·√(p(1−p)/n).

    Reports the tightest absolute precision (margin of error) the study can
    achieve for an estimated proportion p with the analysable sample size.
    """
    _check_alpha(alpha)
    if not 0 < p < 1:
        raise ValueError("Expected proportion p must be in (0, 1).")
    n_recruited = _coerce_n(n, "n")
    n_keep = _analyzable(n_recruited, dropout)
    z_a = z_two_tailed(alpha)
    d = z_a * math.sqrt(p * (1 - p) / n_keep)

    notes = [
        "We solved the single-proportion formula for d (the half-width "
        "of the confidence interval) given your fixed sample size.",
        f"Your study can estimate p={p} with a margin of error no smaller "
        f"than ±{d * 100:.2f} percentage points at the chosen α.",
    ]
    drop = _dropout_note(n_recruited, n_keep, dropout)
    if drop:
        notes.append(drop)

    return {
        "formula": "single_proportion",
        "mode": "reverse",
        "formula_label": "Single proportion — back-calculated precision",
        "formula_expression": "solve for d:  d = Z(α/2) · √(p·(1−p) / n)",
        "inputs": {
            "expected_proportion": p,
            "n_recruited": n_recruited,
            "n_analyzable": n_keep,
            "alpha": alpha,
            "dropout_rate": dropout,
        },
        "constants": _round_constants(
            {"Z_alpha_over_2": z_a, "p_q": p * (1 - p)}
        ),
        "headline": [
            {
                "label": "Minimum detectable precision (±d)",
                "value": f"±{d * 100:.2f} percentage points",
                "sublabel": f"absolute width {d:.4f}",
            },
            {
                "label": "Resulting CI for p",
                "value": f"[{max(0, p - d):.3f}, {min(1, p + d):.3f}]",
                "sublabel": None,
            },
        ],
        "detectable": {"min_detectable_precision": round(d, 6)},
        "notes": notes,
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# Reverse 2 — single mean: solve d given n
# ---------------------------------------------------------------------------


def reverse_single_mean(
    sigma: float,
    n: int,
    alpha: float = 0.05,
    dropout: float = 0.0,
) -> Dict[str, Any]:
    """Solve  n = (Z·σ/d)²  for d:   d = Z·σ/√n."""
    _check_alpha(alpha)
    if sigma <= 0:
        raise ValueError("Standard deviation σ must be positive.")
    n_recruited = _coerce_n(n, "n")
    n_keep = _analyzable(n_recruited, dropout)
    z_a = z_two_tailed(alpha)
    d = z_a * sigma / math.sqrt(n_keep)

    notes = [
        "We solved the single-mean formula for d (the half-width of the "
        "confidence interval) given your fixed sample size.",
        f"Your study can estimate the mean to within ±{d:.4g} units "
        "(in the same units as σ) at the chosen α.",
    ]
    drop = _dropout_note(n_recruited, n_keep, dropout)
    if drop:
        notes.append(drop)

    return {
        "formula": "single_mean",
        "mode": "reverse",
        "formula_label": "Single mean — back-calculated precision",
        "formula_expression": "solve for d:  d = Z(α/2) · σ / √n",
        "inputs": {
            "standard_deviation": sigma,
            "n_recruited": n_recruited,
            "n_analyzable": n_keep,
            "alpha": alpha,
            "dropout_rate": dropout,
        },
        "constants": _round_constants({"Z_alpha_over_2": z_a}),
        "headline": [
            {
                "label": "Minimum detectable precision (±d)",
                "value": f"±{d:.4g} (same units as σ)",
                "sublabel": None,
            }
        ],
        "detectable": {"min_detectable_precision": round(d, 6)},
        "notes": notes,
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# Reverse 3 — two independent proportions (uses bisection)
# ---------------------------------------------------------------------------


def _two_prop_required_n_continuous(
    p1: float, p2: float, z_a: float, z_b: float
) -> float:
    """Continuous (non-ceiling) required n/group for two-proportion test.

    Used by the bisection solver below — we need a smooth function so that
    f(p2) = required_n(p2) - n_target has well-defined roots.
    """
    if p1 == p2:
        return float("inf")
    p_bar = (p1 + p2) / 2
    q_bar = 1 - p_bar
    q1, q2 = 1 - p1, 1 - p2
    numerator = (
        z_a * math.sqrt(2 * p_bar * q_bar) + z_b * math.sqrt(p1 * q1 + p2 * q2)
    ) ** 2
    return numerator / (p1 - p2) ** 2


def _bisect_p2(
    n_target: float,
    p1: float,
    z_a: float,
    z_b: float,
    low: float,
    high: float,
    tol: float = 1e-7,
    max_iter: int = 100,
) -> Optional[float]:
    """Find p2 in (low, high) such that required_n(p1, p2) == n_target.

    Returns None if the interval doesn't bracket a root — i.e. even maximum
    separation in this direction can't be detected with the given n_target.
    """
    f_low = _two_prop_required_n_continuous(p1, low, z_a, z_b) - n_target
    f_high = _two_prop_required_n_continuous(p1, high, z_a, z_b) - n_target
    if f_low * f_high > 0:
        return None
    for _ in range(max_iter):
        mid = (low + high) / 2
        f_mid = _two_prop_required_n_continuous(p1, mid, z_a, z_b) - n_target
        if abs(f_mid) < 1e-9 or (high - low) < tol:
            return mid
        if f_low * f_mid <= 0:
            high = mid
            f_high = f_mid
        else:
            low = mid
            f_low = f_mid
    return (low + high) / 2


def reverse_two_proportions(
    p1: float,
    n_per_group: int,
    alpha: float = 0.05,
    power: float = 0.80,
    dropout: float = 0.0,
) -> Dict[str, Any]:
    """Back-calculate the minimum detectable second proportion.

    Given a known baseline ``p1`` and a fixed available ``n_per_group``, find
    the two values of p2 (one below, one above p1) that the study could just
    detect at the chosen alpha and power. The detectable difference equals
    |p1 − p2| in each direction.
    """
    _check_alpha(alpha)
    _check_power(power)
    if not 0 < p1 < 1:
        raise ValueError("p1 must be in (0, 1).")
    n_recruited = _coerce_n(n_per_group, "n_per_group")
    n_keep = _analyzable(n_recruited, dropout)

    z_a = z_two_tailed(alpha)
    z_b = z_power(power)
    eps = 1e-4
    p2_lower = _bisect_p2(n_keep, p1, z_a, z_b, eps, p1 - eps)
    p2_higher = _bisect_p2(n_keep, p1, z_a, z_b, p1 + eps, 1 - eps)

    notes = [
        "We solved the two-proportion sample-size formula for p₂ given your "
        "fixed sample size — Z(α/2)·√(2·p̄·q̄) + Z(β)·√(p₁·q₁ + p₂·q₂) "
        "remains the variance term.",
        "Two answers are reported because the test is two-sided: one if the "
        "intervention raises the outcome rate, one if it lowers it.",
    ]
    drop = _dropout_note(n_recruited, n_keep, dropout)
    if drop:
        notes.append(drop)
    warnings: List[str] = []
    if p2_lower is None:
        warnings.append(
            "Even the largest possible decrease (p₂ → 0) cannot be detected "
            "with this sample size at the chosen α and power."
        )
    if p2_higher is None:
        warnings.append(
            "Even the largest possible increase (p₂ → 1) cannot be detected "
            "with this sample size at the chosen α and power."
        )

    headline = []
    if p2_lower is not None:
        headline.append({
            "label": "Detectable p₂ if outcome decreases",
            "value": _format_pct(p2_lower),
            "sublabel": f"Δ = {(p1 - p2_lower) * 100:.2f} percentage points",
        })
    else:
        headline.append({
            "label": "Detectable p₂ if outcome decreases",
            "value": "Not detectable",
            "sublabel": None,
        })
    if p2_higher is not None:
        headline.append({
            "label": "Detectable p₂ if outcome increases",
            "value": _format_pct(p2_higher),
            "sublabel": f"Δ = {(p2_higher - p1) * 100:.2f} percentage points",
        })
    else:
        headline.append({
            "label": "Detectable p₂ if outcome increases",
            "value": "Not detectable",
            "sublabel": None,
        })

    return {
        "formula": "two_proportions",
        "mode": "reverse",
        "formula_label": "Two independent proportions — back-calculated p₂",
        "formula_expression": (
            "solve for p₂:  n/group = [Z(α/2)·√(2·p̄·q̄) + Z(β)·√(p₁·q₁ + p₂·q₂)]² / (p₁ − p₂)²"
        ),
        "inputs": {
            "p1": p1,
            "n_per_group_recruited": n_recruited,
            "n_per_group_analyzable": n_keep,
            "alpha": alpha,
            "power": power,
            "dropout_rate": dropout,
        },
        "constants": _round_constants({"Z_alpha_over_2": z_a, "Z_beta": z_b}),
        "headline": headline,
        "detectable": {
            "p2_lower": round(p2_lower, 4) if p2_lower is not None else None,
            "p2_higher": round(p2_higher, 4) if p2_higher is not None else None,
            "min_detectable_decrease": (
                round(p1 - p2_lower, 4) if p2_lower is not None else None
            ),
            "min_detectable_increase": (
                round(p2_higher - p1, 4) if p2_higher is not None else None
            ),
        },
        "notes": notes,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Reverse 4 — two independent means: solve Δ given σ and n/group
# ---------------------------------------------------------------------------


def reverse_two_means(
    sigma: float,
    n_per_group: int,
    alpha: float = 0.05,
    power: float = 0.80,
    dropout: float = 0.0,
) -> Dict[str, Any]:
    """Solve  n/group = 2·σ²·(Zα/2 + Zβ)² / Δ²  for Δ:

        Δ = (Zα/2 + Zβ) · σ · √(2 / n)

    Because the variance does not depend on the mean, the detectable
    difference is symmetric: μ₁ ± Δ.
    """
    _check_alpha(alpha)
    _check_power(power)
    if sigma <= 0:
        raise ValueError("σ must be positive.")
    n_recruited = _coerce_n(n_per_group, "n_per_group")
    n_keep = _analyzable(n_recruited, dropout)
    z_a = z_two_tailed(alpha)
    z_b = z_power(power)
    delta = (z_a + z_b) * sigma * math.sqrt(2 / n_keep)
    cohens_d = delta / sigma

    notes = [
        "We solved the two-means formula for Δ given your fixed sample size. "
        "Equal SDs in both groups are still assumed.",
        "Δ is symmetric: any group difference larger than this — in either "
        "direction — would be detectable at the chosen α and power.",
    ]
    drop = _dropout_note(n_recruited, n_keep, dropout)
    if drop:
        notes.append(drop)

    return {
        "formula": "two_means",
        "mode": "reverse",
        "formula_label": "Two independent means — back-calculated Δ",
        "formula_expression": "solve for Δ:  Δ = (Z(α/2) + Z(β)) · σ · √(2 / n)",
        "inputs": {
            "standard_deviation": sigma,
            "n_per_group_recruited": n_recruited,
            "n_per_group_analyzable": n_keep,
            "alpha": alpha,
            "power": power,
            "dropout_rate": dropout,
        },
        "constants": _round_constants({"Z_alpha_over_2": z_a, "Z_beta": z_b}),
        "headline": [
            {
                "label": "Minimum detectable difference (|μ₁ − μ₂|)",
                "value": f"{delta:.4g} (same units as σ)",
                "sublabel": None,
            },
            {
                "label": "Equivalent Cohen's d at this Δ",
                "value": f"{cohens_d:.3f}",
                "sublabel": _cohens_d_label(cohens_d),
            },
        ],
        "detectable": {
            "min_detectable_difference": round(delta, 6),
            "cohens_d": round(cohens_d, 4),
        },
        "notes": notes,
        "warnings": [],
    }


def _cohens_d_label(d: float) -> str:
    a = abs(d)
    if a < 0.2:
        return "below conventional small effect (d < 0.2)"
    if a < 0.5:
        return "small effect (Cohen)"
    if a < 0.8:
        return "medium effect (Cohen)"
    return "large effect (Cohen)"


# ---------------------------------------------------------------------------
# Reverse 5 — paired means: solve Δ given σ_d and n
# ---------------------------------------------------------------------------


def reverse_paired_means(
    sigma_diff: float,
    n: int,
    alpha: float = 0.05,
    power: float = 0.80,
    dropout: float = 0.0,
) -> Dict[str, Any]:
    """Solve  n = (Zα/2 + Zβ)² · σ_d² / Δ²  for Δ:

        Δ = (Zα/2 + Zβ) · σ_d / √n
    """
    _check_alpha(alpha)
    _check_power(power)
    if sigma_diff <= 0:
        raise ValueError("σ of differences must be positive.")
    n_recruited = _coerce_n(n, "n")
    n_keep = _analyzable(n_recruited, dropout)
    z_a = z_two_tailed(alpha)
    z_b = z_power(power)
    delta = (z_a + z_b) * sigma_diff / math.sqrt(n_keep)
    dz = delta / sigma_diff

    notes = [
        "We solved the paired-means formula for Δ given your fixed sample size.",
        "This is the smallest mean within-pair change (e.g. before vs after) "
        "your study could detect at the chosen α and power.",
    ]
    drop = _dropout_note(n_recruited, n_keep, dropout)
    if drop:
        notes.append(drop)

    return {
        "formula": "paired_means",
        "mode": "reverse",
        "formula_label": "Paired means — back-calculated Δ",
        "formula_expression": "solve for Δ:  Δ = (Z(α/2) + Z(β)) · σ_d / √n",
        "inputs": {
            "sd_of_differences": sigma_diff,
            "n_recruited": n_recruited,
            "n_analyzable": n_keep,
            "alpha": alpha,
            "power": power,
            "dropout_rate": dropout,
        },
        "constants": _round_constants({"Z_alpha_over_2": z_a, "Z_beta": z_b}),
        "headline": [
            {
                "label": "Minimum detectable mean difference (|Δ|)",
                "value": f"{delta:.4g} (same units as σ_d)",
                "sublabel": None,
            },
            {
                "label": "Equivalent effect size dz",
                "value": f"{dz:.3f}",
                "sublabel": _cohens_d_label(dz),
            },
        ],
        "detectable": {
            "min_detectable_difference": round(delta, 6),
            "effect_size_dz": round(dz, 4),
        },
        "notes": notes,
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# Reverse 6 — one-way ANOVA: solve Cohen's f given k and n/group
# ---------------------------------------------------------------------------


def reverse_anova_means(
    k: int,
    n_per_group: int,
    alpha: float = 0.05,
    power: float = 0.80,
    dropout: float = 0.0,
) -> Dict[str, Any]:
    """Invert  n/group ≈ (Zα/2 + Zβ)² / (k·f²) + 1  for Cohen's f:

        f = (Zα/2 + Zβ) / √(k · (n − 1))

    Same normal-approximation caveat as the forward calculator.
    """
    _check_alpha(alpha)
    _check_power(power)
    if isinstance(k, bool) or not isinstance(k, (int, float)):
        raise ValueError("k must be a number.")
    if isinstance(k, float) and not k.is_integer():
        raise ValueError("k must be a whole number of groups.")
    k = int(k)
    if k < 3:
        raise ValueError("ANOVA requires k ≥ 3 groups.")
    n_recruited = _coerce_n(n_per_group, "n_per_group", minimum=5)
    n_keep = _analyzable(n_recruited, dropout)
    if n_keep < 5:
        raise ValueError(
            "Need at least 5 analysable participants per group to back-"
            "calculate Cohen's f reliably."
        )
    z_a = z_two_tailed(alpha)
    z_b = z_power(power)
    f_val = (z_a + z_b) / math.sqrt(k * (n_keep - 1))

    notes = [
        "We solved the ANOVA approximation for Cohen's f given k and your "
        "per-group sample size.",
        "ANOVA estimate uses a normal-approximation. Cohen's conventions: "
        "small = 0.10, medium = 0.25, large = 0.40.",
        "For final, exact f use a noncentral-F calculation (will be added "
        "when the Statistical Analysis Engine ships).",
    ]
    drop = _dropout_note(n_recruited, n_keep, dropout)
    if drop:
        notes.append(drop)

    return {
        "formula": "anova_means",
        "mode": "reverse",
        "formula_label": f"One-way ANOVA ({k} groups) — back-calculated f",
        "formula_expression": "solve for f:  f = (Z(α/2) + Z(β)) / √(k · (n − 1))",
        "inputs": {
            "number_of_groups": k,
            "n_per_group_recruited": n_recruited,
            "n_per_group_analyzable": n_keep,
            "alpha": alpha,
            "power": power,
            "dropout_rate": dropout,
        },
        "constants": _round_constants({"Z_alpha_over_2": z_a, "Z_beta": z_b}),
        "headline": [
            {
                "label": "Minimum detectable Cohen's f",
                "value": f"{f_val:.3f}",
                "sublabel": _cohens_f_label(f_val),
            }
        ],
        "detectable": {
            "min_detectable_cohens_f": round(f_val, 4),
            "qualitative_label": _cohens_f_label(f_val),
        },
        "notes": notes,
        "warnings": [],
    }


def _cohens_f_label(f_val: float) -> str:
    if f_val < 0.10:
        return "below conventional small effect (f < 0.10)"
    if f_val < 0.25:
        return "small effect (Cohen)"
    if f_val < 0.40:
        return "medium effect (Cohen)"
    return "large effect (Cohen)"


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


FORMULAS = {
    "single_proportion": single_proportion,
    "single_mean": single_mean,
    "two_proportions": two_proportions,
    "two_means": two_means,
    "paired_means": paired_means,
    "anova_means": anova_means,
}


REVERSE_FORMULAS = {
    "single_proportion": reverse_single_proportion,
    "single_mean": reverse_single_mean,
    "two_proportions": reverse_two_proportions,
    "two_means": reverse_two_means,
    "paired_means": reverse_paired_means,
    "anova_means": reverse_anova_means,
}


def calculate(formula: str, params: Dict[str, Any]) -> SampleSizeResult:
    """Look up a formula by id and run it with the supplied parameters."""
    if formula not in FORMULAS:
        raise ValueError(f"Unknown formula: {formula}")
    fn = FORMULAS[formula]
    return fn(**params)


def reverse_calculate(formula: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Run the reverse-mode (back-calculation) form of the given formula."""
    if formula not in REVERSE_FORMULAS:
        raise ValueError(f"Reverse mode not available for formula: {formula}")
    fn = REVERSE_FORMULAS[formula]
    return fn(**params)
