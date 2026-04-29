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
from typing import Any, Dict, List

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


def calculate(formula: str, params: Dict[str, Any]) -> SampleSizeResult:
    """Look up a formula by id and run it with the supplied parameters."""
    if formula not in FORMULAS:
        raise ValueError(f"Unknown formula: {formula}")
    fn = FORMULAS[formula]
    return fn(**params)
