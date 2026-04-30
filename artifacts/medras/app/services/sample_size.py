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


# ---------------------------------------------------------------------------
# 7. Repeated measures (longitudinal — two groups, m timepoints)
# ---------------------------------------------------------------------------


def repeated_measures(
    mean1: float,
    mean2: float,
    sigma: float,
    rho: float,
    m_timepoints: int,
    alpha: float = 0.05,
    power: float = 0.80,
    dropout: float = 0.0,
) -> SampleSizeResult:
    """Two-group comparison with m repeated measurements per subject.

    n_per_group = 2·σ²·(Zα/2 + Zβ)²·(1 + (m−1)·ρ) / (m·Δ²)

    Reference: Diggle, Heagerty, Liang & Zeger (2002), *Analysis of
    Longitudinal Data*. With m=1 this reduces to the standard two-means
    formula. As within-subject correlation ρ → 1 the variance factor
    approaches 1 (no benefit from repeats); as ρ → 0 it approaches 1/m
    (full benefit).
    """
    _check_alpha(alpha)
    _check_power(power)
    if sigma <= 0:
        raise ValueError("σ must be positive.")
    if mean1 == mean2:
        raise ValueError("Means must differ — there is no effect to detect.")
    if not 0 <= rho < 1:
        raise ValueError("Within-subject correlation ρ must be in [0, 1).")
    if isinstance(m_timepoints, bool) or not isinstance(m_timepoints, (int, float)):
        raise ValueError("m_timepoints must be a number.")
    if isinstance(m_timepoints, float) and not m_timepoints.is_integer():
        raise ValueError("m_timepoints must be a whole number.")
    m = int(m_timepoints)
    if m < 2:
        raise ValueError(
            "m_timepoints must be ≥ 2. For a single timepoint use 'two_means'."
        )

    z_a = z_two_tailed(alpha)
    z_b = z_power(power)
    delta = mean1 - mean2
    var_factor = (1 + (m - 1) * rho) / m
    n_each = _ceil(2 * (sigma ** 2) * ((z_a + z_b) ** 2) * var_factor / (delta ** 2))
    total = n_each * 2
    return SampleSizeResult(
        formula="repeated_measures",
        formula_label=f"Two-group longitudinal study ({m} timepoints)",
        formula_expression=(
            "n/group = 2·σ²·(Z(α/2) + Z(β))²·(1 + (m−1)·ρ) / (m·Δ²)"
        ),
        n_per_group=n_each,
        number_of_groups=2,
        total_n=total,
        adjusted_n=_apply_dropout(total, dropout),
        inputs={
            "mean1": mean1,
            "mean2": mean2,
            "standard_deviation": sigma,
            "within_subject_correlation": rho,
            "number_of_timepoints": m,
            "alpha": alpha,
            "power": power,
            "dropout_rate": dropout,
        },
        constants=_round_constants(
            {
                "Z_alpha_over_2": z_a,
                "Z_beta": z_b,
                "effect_size_diff": abs(delta),
                "variance_factor": var_factor,
                "cohens_d": abs(delta) / sigma,
            }
        ),
        notes=[
            "Use this for longitudinal designs where each participant is "
            "measured at multiple timepoints and you compare two groups.",
            f"With ρ={rho} and m={m}, the variance factor is "
            f"{var_factor:.3f}× the single-timepoint variance.",
            "Dropout in longitudinal studies is typically larger — consider "
            "raising your dropout rate above the standard 10–20%.",
        ],
    )


# ---------------------------------------------------------------------------
# 8. Linear regression (testing R² with p predictors)
# ---------------------------------------------------------------------------


def linear_regression(
    r_squared: float,
    predictors: int,
    alpha: float = 0.05,
    power: float = 0.80,
    dropout: float = 0.0,
) -> SampleSizeResult:
    """Sample size for testing R² > 0 in a multiple regression.

    n = (Z(α/2) + Z(β))² · (1−R²) / R²  +  p + 1

    Where p is the number of predictors. The +p+1 absorbs the degrees of
    freedom lost to estimation. This is Cohen's (1988) z-approximation; for
    a precise noncentral-F result, use G*Power.
    """
    _check_alpha(alpha)
    _check_power(power)
    if not 0 < r_squared < 1:
        raise ValueError("r_squared must be in (0, 1).")
    if isinstance(predictors, bool) or not isinstance(predictors, (int, float)):
        raise ValueError("predictors must be a number.")
    if isinstance(predictors, float) and not predictors.is_integer():
        raise ValueError("predictors must be a whole number.")
    p = int(predictors)
    if p < 1:
        raise ValueError("predictors must be ≥ 1.")

    z_a = z_two_tailed(alpha)
    z_b = z_power(power)
    f_squared = r_squared / (1 - r_squared)
    n_total = _ceil(((z_a + z_b) ** 2) * (1 - r_squared) / r_squared + p + 1)
    return SampleSizeResult(
        formula="linear_regression",
        formula_label=f"Multiple linear regression ({p} predictor{'s' if p != 1 else ''})",
        formula_expression="n = (Z(α/2) + Z(β))²·(1−R²)/R² + p + 1",
        n_per_group=n_total,
        number_of_groups=1,
        total_n=n_total,
        adjusted_n=_apply_dropout(n_total, dropout),
        inputs={
            "expected_r_squared": r_squared,
            "number_of_predictors": p,
            "alpha": alpha,
            "power": power,
            "dropout_rate": dropout,
        },
        constants=_round_constants(
            {
                "Z_alpha_over_2": z_a,
                "Z_beta": z_b,
                "cohens_f_squared": f_squared,
            }
        ),
        notes=[
            "Use this when the objective is to test whether a multiple "
            "linear regression model explains a non-zero proportion of "
            "variance (R² > 0).",
            "Cohen's f² conventions: small = 0.02, medium = 0.15, large = 0.35.",
            "Z-approximation; for exact noncentral-F use G*Power.",
        ],
    )


# ---------------------------------------------------------------------------
# 9. Prediction model (events-per-variable rule)
# ---------------------------------------------------------------------------


def prediction_model(
    predictors: int,
    event_rate: float,
    epv_target: float = 10.0,
    dropout: float = 0.0,
) -> SampleSizeResult:
    """Total n required to fit a prediction model with a given EPV target.

    n_total = ceil(epv_target × predictors / event_rate)

    The Peduzzi et al. (1996) rule of thumb requires roughly 10 events per
    candidate predictor (EPV ≥ 10) for a stable logistic-regression model;
    Riley et al. (2020) refined this with formulas tailored to particular
    performance targets. Use ``epv_target`` to switch between conservatism
    levels (e.g. 5, 10, 20).

    Note: this formula does not use α or β — it is a degrees-of-freedom
    rule, not a power calculation. Use it for sample-size planning of
    diagnostic / prognostic prediction models.
    """
    if isinstance(predictors, bool) or not isinstance(predictors, (int, float)):
        raise ValueError("predictors must be a number.")
    if isinstance(predictors, float) and not predictors.is_integer():
        raise ValueError("predictors must be a whole number.")
    p = int(predictors)
    if p < 1:
        raise ValueError("predictors must be ≥ 1.")
    if not 0 < event_rate < 1:
        raise ValueError("event_rate must be in (0, 1).")
    if epv_target <= 0:
        raise ValueError("epv_target must be positive.")

    n_events = epv_target * p
    n_total = _ceil(n_events / event_rate)
    return SampleSizeResult(
        formula="prediction_model",
        formula_label=f"Prediction model ({p} candidate predictor{'s' if p != 1 else ''})",
        formula_expression="n = ceil(EPV × predictors / event_rate)",
        n_per_group=n_total,
        number_of_groups=1,
        total_n=n_total,
        adjusted_n=_apply_dropout(n_total, dropout),
        inputs={
            "number_of_predictors": p,
            "event_rate": event_rate,
            "epv_target": epv_target,
            "dropout_rate": dropout,
        },
        constants=_round_constants(
            {
                "required_events": n_events,
                "events_per_variable": epv_target,
            }
        ),
        notes=[
            f"Rule of thumb: at least {epv_target:g} event{'s' if epv_target != 1 else ''} "
            f"per candidate predictor (Peduzzi et al., 1996).",
            f"Total events needed: {int(math.ceil(n_events))}; "
            f"with an event rate of {event_rate * 100:.1f}%, this requires "
            f"{n_total} total participants.",
            "For a more precise calculation accounting for expected model "
            "performance, see Riley et al. (2020).",
        ],
    )


# ---------------------------------------------------------------------------
# 10. Cohen's kappa (inter-rater agreement)
# ---------------------------------------------------------------------------


def kappa_agreement(
    expected_kappa: float,
    precision: float,
    alpha: float = 0.05,
    dropout: float = 0.0,
) -> SampleSizeResult:
    """Sample size for estimating Cohen's κ within a chosen precision.

    n = Z(α/2)² · κ(1−κ) / d²

    Simplified precision-based formula (Cantor, 1996; Bujang & Baharum,
    2017). Assumes balanced marginal proportions (~50/50 positive/negative
    ratings); for highly skewed marginals, the actual variance can be
    larger. Subjects rated by two raters with a binary outcome.
    """
    _check_alpha(alpha)
    if not 0 < expected_kappa < 1:
        raise ValueError("expected_kappa must be in (0, 1).")
    if not 0 < precision < 1:
        raise ValueError("precision (CI half-width) must be in (0, 1).")

    z_a = z_two_tailed(alpha)
    n_total = _ceil((z_a ** 2) * expected_kappa * (1 - expected_kappa) / (precision ** 2))
    return SampleSizeResult(
        formula="kappa_agreement",
        formula_label="Cohen's κ (inter-rater agreement, binary outcome)",
        formula_expression="n = Z(α/2)² · κ(1−κ) / d²",
        n_per_group=n_total,
        number_of_groups=1,
        total_n=n_total,
        adjusted_n=_apply_dropout(n_total, dropout),
        inputs={
            "expected_kappa": expected_kappa,
            "absolute_precision": precision,
            "alpha": alpha,
            "dropout_rate": dropout,
        },
        constants=_round_constants(
            {
                "Z_alpha_over_2": z_a,
                "kappa_variance_factor": expected_kappa * (1 - expected_kappa),
            }
        ),
        notes=[
            "Sample size for estimating κ within ±d at the chosen confidence.",
            "Assumes balanced marginal proportions (~50/50). For skewed "
            "marginals, the variance can be larger — confirm with a "
            "study-specific calculation.",
            "κ interpretation (Landis & Koch, 1977): 0.0–0.2 slight, "
            "0.21–0.4 fair, 0.41–0.6 moderate, 0.61–0.8 substantial, "
            "0.81–1.0 almost perfect.",
        ],
    )


# ---------------------------------------------------------------------------
# 11. ROC / AUC (single-test diagnostic accuracy)
# ---------------------------------------------------------------------------


def _hanley_mcneil_q(auc: float) -> tuple:
    """Hanley & McNeil (1982) Q1 and Q2 — distribution-free variance terms."""
    q1 = auc / (2 - auc)
    q2 = 2 * (auc ** 2) / (1 + auc)
    return q1, q2


def roc_auc(
    auc: float,
    case_ratio: float,
    precision: float,
    alpha: float = 0.05,
    dropout: float = 0.0,
) -> SampleSizeResult:
    """Cases needed to estimate AUC within ±d using Hanley & McNeil (1982).

    Solves for n_cases given the AUC, the controls-per-case ratio (k), and
    the desired half-width d of the (1−α) CI. With n_b = k · n_a:

        Var(AUC) = [AUC(1−AUC) + (n_a−1)(Q1−AUC²) + (n_b−1)(Q2−AUC²)]
                   / (n_a · n_b)
        d = Z(α/2) · √Var(AUC)

    Where Q1 = AUC/(2−AUC) and Q2 = 2·AUC²/(1+AUC). Approximating
    (n_a − 1) ≈ n_a gives a quadratic in n_a that we solve directly.
    """
    _check_alpha(alpha)
    if not 0.5 < auc < 1:
        raise ValueError("AUC must be in (0.5, 1) — values ≤ 0.5 indicate no diagnostic value.")
    if case_ratio <= 0:
        raise ValueError("case_ratio (controls per case) must be positive.")
    if not 0 < precision < 0.5:
        raise ValueError("precision must be in (0, 0.5).")

    z_a = z_two_tailed(alpha)
    q1, q2 = _hanley_mcneil_q(auc)
    auc_var = auc * (1 - auc)

    # Quadratic: a·n² + b·n + c = 0 in n_a (cases).
    a = (precision ** 2) * case_ratio
    b = -(z_a ** 2) * ((q1 - auc ** 2) + case_ratio * (q2 - auc ** 2))
    c = -(z_a ** 2) * auc_var
    discriminant = b ** 2 - 4 * a * c
    if discriminant < 0:
        raise ValueError(
            "Could not solve for n_cases — check inputs (AUC near 0.5 with "
            "very tight precision needs an enormous sample)."
        )
    n_cases = _ceil((-b + math.sqrt(discriminant)) / (2 * a))
    n_controls = _ceil(case_ratio * n_cases)
    total = n_cases + n_controls
    return SampleSizeResult(
        formula="roc_auc",
        formula_label="Single-test diagnostic AUC (ROC curve)",
        formula_expression=(
            "n_cases solves: d² = Z(α/2)² · "
            "[AUC(1−AUC) + (n_a−1)(Q1−AUC²) + (n_b−1)(Q2−AUC²)] / (n_a·n_b)"
        ),
        n_per_group=n_cases,
        number_of_groups=1,
        total_n=total,
        adjusted_n=_apply_dropout(total, dropout),
        inputs={
            "expected_auc": auc,
            "controls_per_case_ratio": case_ratio,
            "absolute_precision": precision,
            "alpha": alpha,
            "dropout_rate": dropout,
        },
        constants=_round_constants(
            {
                "Z_alpha_over_2": z_a,
                "Q1_hanley": q1,
                "Q2_hanley": q2,
                "auc_variance_term": auc_var,
            }
        ),
        notes=[
            f"Required: {n_cases} cases (diseased) plus {n_controls} controls "
            f"(non-diseased) at a {case_ratio}:1 controls-to-cases ratio.",
            "Variance from Hanley & McNeil (1982) — distribution-free, "
            "exponential-derived approximation.",
            "Interpretation of AUC: 0.5 = no discrimination; 0.7–0.8 = "
            "acceptable; 0.8–0.9 = excellent; >0.9 = outstanding.",
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


def _cohens_f2_label(f2: float) -> str:
    if f2 < 0.02:
        return "below conventional small effect (f² < 0.02)"
    if f2 < 0.15:
        return "small effect (Cohen)"
    if f2 < 0.35:
        return "medium effect (Cohen)"
    return "large effect (Cohen)"


def _kappa_label(k_val: float) -> str:
    """Landis & Koch (1977) descriptors for Cohen's κ."""
    if k_val < 0.0:
        return "no agreement"
    if k_val < 0.21:
        return "slight agreement"
    if k_val < 0.41:
        return "fair agreement"
    if k_val < 0.61:
        return "moderate agreement"
    if k_val < 0.81:
        return "substantial agreement"
    return "almost perfect agreement"


# ---------------------------------------------------------------------------
# 7r. Reverse — Repeated measures
# ---------------------------------------------------------------------------


def reverse_repeated_measures(
    sigma: float,
    rho: float,
    m_timepoints: int,
    n_per_group: int,
    alpha: float = 0.05,
    power: float = 0.80,
    dropout: float = 0.0,
) -> Dict[str, Any]:
    """Solve the longitudinal formula for the smallest detectable Δ:

        Δ = (Z(α/2) + Z(β)) · σ · √(2·(1 + (m−1)·ρ) / (m·n))
    """
    _check_alpha(alpha)
    _check_power(power)
    if sigma <= 0:
        raise ValueError("σ must be positive.")
    if not 0 <= rho < 1:
        raise ValueError("ρ must be in [0, 1).")
    if isinstance(m_timepoints, bool) or not isinstance(m_timepoints, (int, float)):
        raise ValueError("m_timepoints must be a number.")
    if isinstance(m_timepoints, float) and not m_timepoints.is_integer():
        raise ValueError("m_timepoints must be a whole number.")
    m = int(m_timepoints)
    if m < 2:
        raise ValueError("m_timepoints must be ≥ 2.")
    n_recruited = _coerce_n(n_per_group, "n_per_group", minimum=4)
    n_keep = _analyzable(n_recruited, dropout)
    if n_keep < 4:
        raise ValueError("Need ≥ 4 analysable participants per group after dropout.")

    z_a = z_two_tailed(alpha)
    z_b = z_power(power)
    var_factor = (1 + (m - 1) * rho) / m
    delta = (z_a + z_b) * sigma * math.sqrt(2 * var_factor / n_keep)
    cohens_d = delta / sigma

    notes = [
        "We inverted the longitudinal formula for the smallest mean "
        "difference (Δ) detectable with your per-group sample size.",
        f"Variance factor with ρ={rho} and m={m}: {var_factor:.3f}.",
    ]
    drop = _dropout_note(n_recruited, n_keep, dropout)
    if drop:
        notes.append(drop)

    return {
        "formula": "repeated_measures",
        "mode": "reverse",
        "formula_label": f"Two-group longitudinal study ({m} timepoints) — back-calculated Δ",
        "formula_expression": "solve for Δ:  Δ = (Z(α/2) + Z(β))·σ·√(2·(1+(m−1)ρ)/(m·n))",
        "inputs": {
            "standard_deviation": sigma,
            "within_subject_correlation": rho,
            "number_of_timepoints": m,
            "n_per_group_recruited": n_recruited,
            "n_per_group_analyzable": n_keep,
            "alpha": alpha,
            "power": power,
            "dropout_rate": dropout,
        },
        "constants": _round_constants(
            {"Z_alpha_over_2": z_a, "Z_beta": z_b, "variance_factor": var_factor}
        ),
        "headline": [
            {
                "label": "Minimum detectable mean difference (Δ)",
                "value": f"{delta:.3f}",
                "sublabel": f"Cohen's d ≈ {cohens_d:.3f}",
            }
        ],
        "detectable": {
            "min_detectable_delta": round(delta, 4),
            "cohens_d": round(cohens_d, 4),
        },
        "notes": notes,
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# 8r. Reverse — Linear regression
# ---------------------------------------------------------------------------


def reverse_linear_regression(
    predictors: int,
    n: int,
    alpha: float = 0.05,
    power: float = 0.80,
    dropout: float = 0.0,
) -> Dict[str, Any]:
    """Solve the regression formula for the smallest detectable R²:

        f² = (Z(α/2) + Z(β))² / (n − p − 1)
        R² = f² / (1 + f²)
    """
    _check_alpha(alpha)
    _check_power(power)
    if isinstance(predictors, bool) or not isinstance(predictors, (int, float)):
        raise ValueError("predictors must be a number.")
    if isinstance(predictors, float) and not predictors.is_integer():
        raise ValueError("predictors must be a whole number.")
    p = int(predictors)
    if p < 1:
        raise ValueError("predictors must be ≥ 1.")
    n_recruited = _coerce_n(n, "n", minimum=p + 5)
    n_keep = _analyzable(n_recruited, dropout)
    if n_keep < p + 5:
        raise ValueError(
            f"Need ≥ {p + 5} analysable participants after dropout to fit a "
            f"regression with {p} predictor{'s' if p != 1 else ''}."
        )

    z_a = z_two_tailed(alpha)
    z_b = z_power(power)
    f_squared = ((z_a + z_b) ** 2) / (n_keep - p - 1)
    r_squared = f_squared / (1 + f_squared)

    notes = [
        f"We inverted Cohen's z-approximation for R² given n={n_keep} and "
        f"{p} predictor{'s' if p != 1 else ''}.",
        "Cohen's f² conventions: small = 0.02, medium = 0.15, large = 0.35.",
    ]
    drop = _dropout_note(n_recruited, n_keep, dropout)
    if drop:
        notes.append(drop)

    return {
        "formula": "linear_regression",
        "mode": "reverse",
        "formula_label": f"Multiple linear regression ({p} predictor{'s' if p != 1 else ''}) — back-calculated R²",
        "formula_expression": "solve for R²:  f² = (Z(α/2) + Z(β))² / (n − p − 1);  R² = f²/(1+f²)",
        "inputs": {
            "number_of_predictors": p,
            "n_recruited": n_recruited,
            "n_analyzable": n_keep,
            "alpha": alpha,
            "power": power,
            "dropout_rate": dropout,
        },
        "constants": _round_constants(
            {"Z_alpha_over_2": z_a, "Z_beta": z_b, "cohens_f_squared": f_squared}
        ),
        "headline": [
            {
                "label": "Minimum detectable R²",
                "value": f"{r_squared:.4f}",
                "sublabel": f"Cohen's f² ≈ {f_squared:.4f} ({_cohens_f2_label(f_squared)})",
            }
        ],
        "detectable": {
            "min_detectable_r_squared": round(r_squared, 6),
            "cohens_f_squared": round(f_squared, 6),
        },
        "notes": notes,
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# 9r. Reverse — Prediction model (max supported predictors)
# ---------------------------------------------------------------------------


def reverse_prediction_model(
    event_rate: float,
    n_total: int,
    epv_target: float = 10.0,
    dropout: float = 0.0,
) -> Dict[str, Any]:
    """Solve the EPV rule for the maximum number of candidate predictors:

        n_events = floor(n × event_rate)
        max_predictors = floor(n_events / epv_target)
    """
    if not 0 < event_rate < 1:
        raise ValueError("event_rate must be in (0, 1).")
    if epv_target <= 0:
        raise ValueError("epv_target must be positive.")
    n_recruited = _coerce_n(n_total, "n_total", minimum=10)
    n_keep = _analyzable(n_recruited, dropout)
    if n_keep < 10:
        raise ValueError(
            "Need at least 10 analysable participants to fit any prediction "
            "model under the EPV rule."
        )

    n_events = math.floor(n_keep * event_rate)
    max_predictors = math.floor(n_events / epv_target)

    notes = [
        f"With n={n_keep} and an event rate of {event_rate * 100:.1f}% you "
        f"will have ~{n_events} events.",
        f"At the {epv_target:g}-events-per-variable rule, this supports "
        f"up to {max_predictors} candidate predictor"
        f"{'s' if max_predictors != 1 else ''}.",
    ]
    drop = _dropout_note(n_recruited, n_keep, dropout)
    if drop:
        notes.append(drop)
    warnings: List[str] = []
    if max_predictors < 1:
        warnings.append(
            "Your sample produces fewer than the events needed for even one "
            "predictor at this EPV target — increase n, raise the event "
            "rate, or relax EPV (use with caution)."
        )

    return {
        "formula": "prediction_model",
        "mode": "reverse",
        "formula_label": "Prediction model — back-calculated maximum predictors",
        "formula_expression": "max_predictors = floor((n × event_rate) / EPV)",
        "inputs": {
            "event_rate": event_rate,
            "epv_target": epv_target,
            "n_recruited": n_recruited,
            "n_analyzable": n_keep,
            "dropout_rate": dropout,
        },
        "constants": _round_constants(
            {"events_available": float(n_events), "events_per_variable": epv_target}
        ),
        "headline": [
            {
                "label": "Maximum candidate predictors",
                "value": str(max_predictors),
                "sublabel": f"based on ~{n_events} events at EPV = {epv_target:g}",
            }
        ],
        "detectable": {
            "max_predictors": int(max_predictors),
            "expected_events": int(n_events),
        },
        "notes": notes,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 10r. Reverse — Cohen's kappa
# ---------------------------------------------------------------------------


def reverse_kappa_agreement(
    expected_kappa: float,
    n: int,
    alpha: float = 0.05,
    dropout: float = 0.0,
) -> Dict[str, Any]:
    """Solve the κ-precision formula for the achievable CI half-width:

        d = Z(α/2) · √(κ(1−κ) / n)
    """
    _check_alpha(alpha)
    if not 0 < expected_kappa < 1:
        raise ValueError("expected_kappa must be in (0, 1).")
    n_recruited = _coerce_n(n, "n", minimum=10)
    n_keep = _analyzable(n_recruited, dropout)
    if n_keep < 10:
        raise ValueError("Need ≥ 10 analysable subjects to estimate κ.")

    z_a = z_two_tailed(alpha)
    d = z_a * math.sqrt(expected_kappa * (1 - expected_kappa) / n_keep)
    ci_low = max(0.0, expected_kappa - d)
    ci_high = min(1.0, expected_kappa + d)

    notes = [
        f"Inverted the κ-precision formula for d given n={n_keep} and "
        f"expected κ={expected_kappa}.",
        f"Approximate {(1 - alpha) * 100:.0f}% CI: [{ci_low:.3f}, {ci_high:.3f}] "
        f"around κ={expected_kappa}.",
        "Assumes balanced marginal proportions (~50/50). Skewed marginals "
        "produce wider intervals.",
    ]
    drop = _dropout_note(n_recruited, n_keep, dropout)
    if drop:
        notes.append(drop)

    return {
        "formula": "kappa_agreement",
        "mode": "reverse",
        "formula_label": "Cohen's κ — back-calculated precision",
        "formula_expression": "solve for d:  d = Z(α/2)·√(κ(1−κ)/n)",
        "inputs": {
            "expected_kappa": expected_kappa,
            "n_recruited": n_recruited,
            "n_analyzable": n_keep,
            "alpha": alpha,
            "dropout_rate": dropout,
        },
        "constants": _round_constants(
            {"Z_alpha_over_2": z_a, "kappa_variance_factor": expected_kappa * (1 - expected_kappa)}
        ),
        "headline": [
            {
                "label": "Achievable CI half-width (±d)",
                "value": f"±{d:.3f}",
                "sublabel": f"approx. {(1 - alpha) * 100:.0f}% CI: [{ci_low:.3f}, {ci_high:.3f}]",
            },
            {
                "label": "Interpretation at expected κ",
                "value": _kappa_label(expected_kappa),
                "sublabel": "Landis & Koch (1977)",
            },
        ],
        "detectable": {
            "achievable_precision": round(d, 4),
            "ci_low": round(ci_low, 4),
            "ci_high": round(ci_high, 4),
        },
        "notes": notes,
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# 11r. Reverse — ROC / AUC
# ---------------------------------------------------------------------------


def reverse_roc_auc(
    auc: float,
    case_ratio: float,
    n_per_group: int,
    alpha: float = 0.05,
    dropout: float = 0.0,
) -> Dict[str, Any]:
    """Plug the Hanley & McNeil variance into d = Z(α/2)·√Var(AUC).

    ``n_per_group`` is the number of cases (diseased subjects); the number
    of controls is case_ratio × n_cases.
    """
    _check_alpha(alpha)
    if not 0.5 < auc < 1:
        raise ValueError("AUC must be in (0.5, 1).")
    if case_ratio <= 0:
        raise ValueError("case_ratio must be positive.")
    n_cases_recruited = _coerce_n(n_per_group, "n_per_group (cases)", minimum=5)
    n_cases_keep = _analyzable(n_cases_recruited, dropout)
    if n_cases_keep < 5:
        raise ValueError("Need ≥ 5 analysable cases after dropout.")
    n_controls_keep = max(1, math.floor(case_ratio * n_cases_keep))

    z_a = z_two_tailed(alpha)
    q1, q2 = _hanley_mcneil_q(auc)
    var = (
        auc * (1 - auc)
        + (n_cases_keep - 1) * (q1 - auc ** 2)
        + (n_controls_keep - 1) * (q2 - auc ** 2)
    ) / (n_cases_keep * n_controls_keep)
    if var <= 0:
        raise ValueError(
            "Computed AUC variance is non-positive — check inputs (very high "
            "AUC with very large n can be numerically unstable)."
        )
    d = z_a * math.sqrt(var)
    ci_low = max(0.5, auc - d)
    ci_high = min(1.0, auc + d)

    notes = [
        f"Inverted Hanley & McNeil (1982) variance for d given n_cases="
        f"{n_cases_keep} and n_controls={n_controls_keep}.",
        f"Approximate {(1 - alpha) * 100:.0f}% CI for AUC: [{ci_low:.3f}, "
        f"{ci_high:.3f}].",
    ]
    drop = _dropout_note(n_cases_recruited, n_cases_keep, dropout)
    if drop:
        notes.append(drop)

    return {
        "formula": "roc_auc",
        "mode": "reverse",
        "formula_label": "Single-test diagnostic AUC — back-calculated precision",
        "formula_expression": "solve for d:  d = Z(α/2)·√Var(AUC)  [Hanley & McNeil 1982]",
        "inputs": {
            "expected_auc": auc,
            "controls_per_case_ratio": case_ratio,
            "n_cases_recruited": n_cases_recruited,
            "n_cases_analyzable": n_cases_keep,
            "n_controls_analyzable": n_controls_keep,
            "alpha": alpha,
            "dropout_rate": dropout,
        },
        "constants": _round_constants(
            {
                "Z_alpha_over_2": z_a,
                "Q1_hanley": q1,
                "Q2_hanley": q2,
                "auc_variance": var,
            }
        ),
        "headline": [
            {
                "label": "Achievable CI half-width (±d) for AUC",
                "value": f"±{d:.4f}",
                "sublabel": f"{(1 - alpha) * 100:.0f}% CI: [{ci_low:.3f}, {ci_high:.3f}]",
            }
        ],
        "detectable": {
            "achievable_precision": round(d, 4),
            "ci_low": round(ci_low, 4),
            "ci_high": round(ci_high, 4),
        },
        "notes": notes,
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# Correlation (Fisher's z)
# ---------------------------------------------------------------------------


def _fisher_z(r: float) -> float:
    return 0.5 * math.log((1 + r) / (1 - r))


def correlation(
    expected_r: float,
    alpha: float = 0.05,
    power: float = 0.80,
    dropout: float = 0.0,
) -> SampleSizeResult:
    """Fisher's z-transform sample size for a single Pearson correlation.

        n = ((Z(α/2) + Z(β)) / arctanh(r))² + 3
    """
    _check_alpha(alpha)
    _check_power(power)
    if not -1 < expected_r < 1 or expected_r == 0:
        raise ValueError("expected_r must be in (-1, 1) and non-zero.")

    z_a = z_two_tailed(alpha)
    z_b = z_power(power)
    zr = _fisher_z(abs(expected_r))
    n_total = _ceil(((z_a + z_b) / zr) ** 2 + 3)
    return SampleSizeResult(
        formula="correlation",
        formula_label="Pearson correlation (Fisher's z)",
        formula_expression="n = ((Z(α/2) + Z(β)) / arctanh(r))² + 3",
        n_per_group=n_total,
        number_of_groups=1,
        total_n=n_total,
        adjusted_n=_apply_dropout(n_total, dropout),
        inputs={
            "expected_r": expected_r,
            "alpha": alpha,
            "power": power,
            "dropout_rate": dropout,
        },
        constants=_round_constants(
            {"Z_alpha_over_2": z_a, "Z_beta": z_b, "fisher_z_r": zr}
        ),
        notes=[
            "Tests H₀: ρ = 0 vs H₁: ρ = expected_r using Fisher's z-transform.",
            "Add 3 because the variance of z is 1/(n-3).",
        ],
    )


def reverse_correlation(
    n: int,
    alpha: float = 0.05,
    power: float = 0.80,
    dropout: float = 0.0,
) -> Dict[str, Any]:
    """Solve Fisher's z for the smallest detectable |r|."""
    _check_alpha(alpha)
    _check_power(power)
    n_recruited = _coerce_n(n, "n", minimum=10)
    n_keep = _analyzable(n_recruited, dropout)
    if n_keep <= 3:
        raise ValueError("Need > 3 analysable subjects for Fisher's z.")

    z_a = z_two_tailed(alpha)
    z_b = z_power(power)
    zr = (z_a + z_b) / math.sqrt(n_keep - 3)
    r = math.tanh(zr)

    notes = [
        f"Inverted Fisher's z given n={n_keep}; the smallest |r| your sample "
        "can distinguish from zero at the chosen α and power.",
    ]
    drop = _dropout_note(n_recruited, n_keep, dropout)
    if drop:
        notes.append(drop)

    return {
        "formula": "correlation",
        "mode": "reverse",
        "formula_label": "Pearson correlation — back-calculated minimum |r|",
        "formula_expression": "solve for r:  r = tanh((Z(α/2) + Z(β)) / √(n−3))",
        "inputs": {
            "n_recruited": n_recruited,
            "n_analyzable": n_keep,
            "alpha": alpha,
            "power": power,
            "dropout_rate": dropout,
        },
        "constants": _round_constants(
            {"Z_alpha_over_2": z_a, "Z_beta": z_b, "fisher_z_r": zr}
        ),
        "headline": [
            {
                "label": "Minimum detectable |r|",
                "value": f"{r:.3f}",
                "sublabel": (
                    "small r ≈ 0.10  ·  medium ≈ 0.30  ·  large ≈ 0.50  (Cohen 1988)"
                ),
            }
        ],
        "detectable": {"min_detectable_r": round(r, 4)},
        "notes": notes,
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# Repeated-measures ANOVA (k groups × m within-subject timepoints)
# ---------------------------------------------------------------------------


def repeated_measures_anova(
    k_groups: int,
    m_timepoints: int,
    rho: float,
    effect_size_f: float,
    alpha: float = 0.05,
    power: float = 0.80,
    dropout: float = 0.0,
) -> SampleSizeResult:
    """Within-between repeated-measures ANOVA, time × group interaction.

    Simplified normal-approximation form (Cohen 1988) with a Bonferroni
    adjustment for the (k − 1) between-group contrasts of the F-test:

        α* = α / (k − 1)
        n_per_group ≈ (Z(α*/2) + Z(β))² · (1 − ρ) / (m · f²) + 1

    The (1 − ρ) factor reflects the variance reduction from repeated
    measurements on the same subject; m is the number of timepoints; f
    is Cohen's f for the between-group factor. The Bonferroni step makes
    k_groups influence the required n in a defensible, conservative way:
    for k = 2 the adjustment is a no-op (α* = α); for k > 2 it widens the
    required separation between groups, which inflates n.
    """
    _check_alpha(alpha)
    _check_power(power)
    if isinstance(k_groups, float) and not k_groups.is_integer():
        raise ValueError("k_groups must be a whole number.")
    k = int(k_groups)
    if k < 2:
        raise ValueError("k_groups must be ≥ 2.")
    if isinstance(m_timepoints, float) and not m_timepoints.is_integer():
        raise ValueError("m_timepoints must be a whole number.")
    m = int(m_timepoints)
    if m < 2:
        raise ValueError("m_timepoints must be ≥ 2 (use anova_means for m=1).")
    if not 0 <= rho < 1:
        raise ValueError("rho must be in [0, 1).")
    if effect_size_f <= 0:
        raise ValueError("effect_size_f must be positive.")

    alpha_adj = alpha / max(1, k - 1)
    z_a = z_two_tailed(alpha_adj)
    z_b = z_power(power)
    n_each = _ceil(((z_a + z_b) ** 2) * (1 - rho) / (m * effect_size_f ** 2) + 1)
    total = n_each * k
    return SampleSizeResult(
        formula="repeated_measures_anova",
        formula_label=(
            f"Repeated-measures ANOVA ({k} groups × {m} timepoints)"
        ),
        formula_expression=(
            "n/group = (Z(α*/2) + Z(β))² · (1 − ρ) / (m · f²) + 1"
            "   where α* = α / (k − 1)"
        ),
        n_per_group=n_each,
        number_of_groups=k,
        total_n=total,
        adjusted_n=_apply_dropout(total, dropout),
        inputs={
            "k_groups": k,
            "m_timepoints": m,
            "within_subject_correlation": rho,
            "effect_size_f": effect_size_f,
            "alpha": alpha,
            "power": power,
            "dropout_rate": dropout,
        },
        constants=_round_constants(
            {
                "alpha_bonferroni": alpha_adj,
                "Z_alpha_over_2": z_a,
                "Z_beta": z_b,
                "variance_reduction": 1 - rho,
            }
        ),
        notes=[
            "Cohen's f conventions: small = 0.10, medium = 0.25, large = 0.40.",
            "Higher within-subject correlation (ρ) reduces n needed.",
            (
                "α is Bonferroni-adjusted across (k − 1) between-group "
                "contrasts; for k = 2 this is a no-op."
            ),
        ],
    )


def reverse_repeated_measures_anova(
    k_groups: int,
    m_timepoints: int,
    rho: float,
    n_per_group: int,
    alpha: float = 0.05,
    power: float = 0.80,
    dropout: float = 0.0,
) -> Dict[str, Any]:
    """Solve RM-ANOVA for the smallest detectable Cohen's f."""
    _check_alpha(alpha)
    _check_power(power)
    if isinstance(k_groups, float) and not k_groups.is_integer():
        raise ValueError("k_groups must be a whole number.")
    k = int(k_groups)
    if k < 2:
        raise ValueError("k_groups must be ≥ 2.")
    if isinstance(m_timepoints, float) and not m_timepoints.is_integer():
        raise ValueError("m_timepoints must be a whole number.")
    m = int(m_timepoints)
    if m < 2:
        raise ValueError("m_timepoints must be ≥ 2.")
    if not 0 <= rho < 1:
        raise ValueError("rho must be in [0, 1).")
    n_recruited = _coerce_n(n_per_group, "n_per_group", minimum=4)
    n_keep = _analyzable(n_recruited, dropout)
    if n_keep < 4:
        raise ValueError("Need ≥ 4 analysable subjects per group.")

    alpha_adj = alpha / max(1, k - 1)
    z_a = z_two_tailed(alpha_adj)
    z_b = z_power(power)
    f_val = math.sqrt(((z_a + z_b) ** 2) * (1 - rho) / (m * (n_keep - 1)))

    notes = [
        f"Inverted RM-ANOVA for f given k={k}, m={m}, ρ={rho:g}, n={n_keep}/group.",
        (
            "α was Bonferroni-adjusted across (k − 1) between-group "
            "contrasts; for k = 2 this is a no-op."
        ),
    ]
    drop = _dropout_note(n_recruited, n_keep, dropout)
    if drop:
        notes.append(drop)

    return {
        "formula": "repeated_measures_anova",
        "mode": "reverse",
        "formula_label": (
            f"Repeated-measures ANOVA ({k}×{m}) — back-calculated f"
        ),
        "formula_expression": "solve for f:  f = √((Z(α/2) + Z(β))²·(1−ρ) / (m·(n−1)))",
        "inputs": {
            "k_groups": k,
            "m_timepoints": m,
            "within_subject_correlation": rho,
            "n_per_group_recruited": n_recruited,
            "n_per_group_analyzable": n_keep,
            "alpha": alpha,
            "power": power,
            "dropout_rate": dropout,
        },
        "constants": _round_constants(
            {"Z_alpha_over_2": z_a, "Z_beta": z_b, "variance_reduction": 1 - rho}
        ),
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


# ---------------------------------------------------------------------------
# Survival analysis (log-rank, Schoenfeld 1983)
# ---------------------------------------------------------------------------


def survival_logrank(
    hazard_ratio: float,
    overall_event_rate: float,
    allocation_ratio: float = 1.0,
    alpha: float = 0.05,
    power: float = 0.80,
    dropout: float = 0.0,
) -> SampleSizeResult:
    """Schoenfeld (1983) sample size for the two-group log-rank test.

        events = (Z(α/2) + Z(β))² / (p_a · p_b · (ln HR)²)
        n      = events / overall_event_rate

    ``allocation_ratio`` is k = n_b / n_a.
    """
    _check_alpha(alpha)
    _check_power(power)
    if hazard_ratio <= 0 or hazard_ratio == 1:
        raise ValueError("hazard_ratio must be positive and ≠ 1.")
    if not 0 < overall_event_rate <= 1:
        raise ValueError("overall_event_rate must be in (0, 1].")
    if allocation_ratio <= 0:
        raise ValueError("allocation_ratio must be positive.")

    z_a = z_two_tailed(alpha)
    z_b = z_power(power)
    p_a = 1 / (1 + allocation_ratio)
    p_b = allocation_ratio / (1 + allocation_ratio)
    ln_hr = math.log(hazard_ratio)
    n_events = _ceil(((z_a + z_b) ** 2) / (p_a * p_b * ln_hr ** 2))
    n_total = _ceil(n_events / overall_event_rate)
    n_a = _ceil(n_total * p_a)
    n_b = _ceil(n_total * p_b)
    return SampleSizeResult(
        formula="survival_logrank",
        formula_label="Survival analysis — two-group log-rank (Schoenfeld 1983)",
        formula_expression=(
            "events = (Z(α/2)+Z(β))² / (p_a·p_b·(ln HR)²);  n = events / event_rate"
        ),
        n_per_group=min(n_a, n_b),
        number_of_groups=2,
        total_n=n_a + n_b,
        adjusted_n=_apply_dropout(n_a + n_b, dropout),
        inputs={
            "hazard_ratio": hazard_ratio,
            "overall_event_rate": overall_event_rate,
            "allocation_ratio": allocation_ratio,
            "alpha": alpha,
            "power": power,
            "dropout_rate": dropout,
        },
        constants=_round_constants(
            {
                "Z_alpha_over_2": z_a,
                "Z_beta": z_b,
                "ln_hazard_ratio": ln_hr,
                "required_events": float(n_events),
                "n_group_a": float(n_a),
                "n_group_b": float(n_b),
            }
        ),
        notes=[
            f"Total events required: {n_events}.",
            f"Allocation: group A = {n_a}, group B = {n_b}.",
            "Censoring assumed non-informative; HR assumed proportional over time.",
        ],
    )


def reverse_survival_logrank(
    overall_event_rate: float,
    n_total: int,
    allocation_ratio: float = 1.0,
    alpha: float = 0.05,
    power: float = 0.80,
    dropout: float = 0.0,
) -> Dict[str, Any]:
    """Solve Schoenfeld for the smallest detectable HR away from 1."""
    _check_alpha(alpha)
    _check_power(power)
    if not 0 < overall_event_rate <= 1:
        raise ValueError("overall_event_rate must be in (0, 1].")
    if allocation_ratio <= 0:
        raise ValueError("allocation_ratio must be positive.")
    n_recruited = _coerce_n(n_total, "n_total", minimum=10)
    n_keep = _analyzable(n_recruited, dropout)
    n_events = max(1, math.floor(n_keep * overall_event_rate))

    z_a = z_two_tailed(alpha)
    z_b = z_power(power)
    p_a = 1 / (1 + allocation_ratio)
    p_b = allocation_ratio / (1 + allocation_ratio)
    if n_events < 4:
        raise ValueError(
            "Too few expected events (<4). Increase n or the event rate."
        )

    ln_hr_abs = math.sqrt(((z_a + z_b) ** 2) / (n_events * p_a * p_b))
    hr_low = math.exp(-ln_hr_abs)
    hr_high = math.exp(ln_hr_abs)

    notes = [
        f"With {n_keep} analysable subjects and an overall event rate of "
        f"{overall_event_rate:g}, you expect ≈ {n_events} events.",
        "These are the closest hazard ratios to 1 your study can separate "
        f"at α={alpha:g} and power={power:g}.",
    ]
    drop = _dropout_note(n_recruited, n_keep, dropout)
    if drop:
        notes.append(drop)

    return {
        "formula": "survival_logrank",
        "mode": "reverse",
        "formula_label": "Log-rank survival — back-calculated detectable HR",
        "formula_expression": "solve for HR:  |ln HR| = √((Z(α/2)+Z(β))² / (events·p_a·p_b))",
        "inputs": {
            "overall_event_rate": overall_event_rate,
            "allocation_ratio": allocation_ratio,
            "n_recruited": n_recruited,
            "n_analyzable": n_keep,
            "alpha": alpha,
            "power": power,
            "dropout_rate": dropout,
        },
        "constants": _round_constants(
            {
                "Z_alpha_over_2": z_a,
                "Z_beta": z_b,
                "expected_events": float(n_events),
            }
        ),
        "headline": [
            {
                "label": "Smallest detectable HR < 1 (protective)",
                "value": f"{hr_low:.3f}",
                "sublabel": f"HR ≤ {hr_low:.3f}  ⇒  detectable benefit",
            },
            {
                "label": "Smallest detectable HR > 1 (harmful)",
                "value": f"{hr_high:.3f}",
                "sublabel": f"HR ≥ {hr_high:.3f}  ⇒  detectable harm",
            },
        ],
        "detectable": {
            "min_detectable_hr_low": round(hr_low, 4),
            "min_detectable_hr_high": round(hr_high, 4),
            "expected_events": int(n_events),
        },
        "notes": notes,
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# Built-in recommendations for non-formulaic study types
# ---------------------------------------------------------------------------


STUDY_TYPE_RECOMMENDATIONS: Dict[str, Dict[str, Any]] = {
    "qualitative": {
        "label": "Qualitative interview study",
        "recommended_n": 12,
        "range": "12–15 in-depth interviews",
        "rationale": (
            "Information saturation in homogeneous samples is typically "
            "reached by 12 interviews (Guest, Bunce & Johnson 2006). Plan "
            "for 12 minimum and recruit until no new themes emerge."
        ),
        "guidance": [
            "Sample size in qualitative work is judged by saturation, not statistics.",
            "Stop recruiting when 2–3 consecutive interviews add no new codes.",
            "Heterogeneous samples (multiple sub-populations) may need 20+ interviews.",
        ],
    },
    "focus_group": {
        "label": "Focus-group discussion (FGD)",
        "recommended_n": 24,
        "range": "3–5 groups of 6–10 participants each (≈ 24 total)",
        "rationale": (
            "Krueger & Casey (2015): 3–5 groups per population strata "
            "are usually enough to reach thematic saturation."
        ),
        "guidance": [
            "Each group: 6–10 participants; 60–90 min duration.",
            "Plan ≥ 1 group per stratum (e.g., gender, age band).",
            "Recruit a 20% backup roster — no-shows are common.",
        ],
    },
    "pilot": {
        "label": "Pilot / feasibility study",
        "recommended_n": 25,
        "range": "20–30 participants total (≈ 25)",
        "rationale": (
            "Pilots target feasibility, recruitment rate, and SD estimation "
            "— not effect-size testing. ~25 is sufficient to estimate a "
            "continuous SD with a usable CI (Whitehead et al. 2016)."
        ),
        "guidance": [
            "Do not power a pilot to detect the main study's effect.",
            "Report CIs for recruitment rate and outcome SD, not p-values.",
            "Pre-specify go/no-go criteria before starting.",
        ],
    },
    "questionnaire": {
        "label": "Cross-sectional questionnaire / KAP survey",
        "recommended_n": 384,
        "range": "≈ 384 respondents (Cochran formula at p=0.5, d=0.05)",
        "rationale": (
            "Standard Cochran (1977) sample for a large/unknown population: "
            "n = Z²·p(1−p)/d² = 1.96²·0.25/0.05² ≈ 384, the worst-case n "
            "to estimate any prevalence to within ±5% at 95% confidence."
        ),
        "guidance": [
            "If you know an expected prevalence, single_proportion gives a smaller n.",
            "If your population is finite (<10 000), apply the finite-population correction.",
            "Inflate by your expected non-response rate (often 15–25%).",
        ],
    },
    "in_vitro": {
        "label": "In-vitro experiment",
        "recommended_n": None,  # routes to a normal formula
        "range": "Typically 3–6 biological replicates per condition",
        "rationale": (
            "In-vitro work follows the resource-equation approach (Mead 1988) "
            "or formal ANOVA when a hypothesis test is planned. For hypothesis "
            "testing, use anova_means / two_means with pilot SD estimates."
        ),
        "guidance": [
            "Distinguish biological replicates (independent samples) from technical replicates.",
            "Report replicate type and number explicitly.",
            "If formal hypothesis testing is the aim, switch to anova_means or two_means below.",
        ],
        "fallback_formula": "two_means",
    },
    "in_vivo": {
        "label": "In-vivo animal study",
        "recommended_n": None,  # routes to a normal formula
        "range": "Power-based n with the 3Rs principle (Reduction)",
        "rationale": (
            "ARRIVE 2.0 / NC3Rs guidance: justify each animal with a power "
            "calculation. Use anova_means / two_means with pilot or "
            "literature-derived SD; round UP to whole animals per cage."
        ),
        "guidance": [
            "Apply the 3Rs: replacement, reduction, refinement.",
            "Justify allocation method and blinding in your protocol.",
            "Account for expected attrition (mortality, surgical loss).",
        ],
        "fallback_formula": "two_means",
    },
}


def get_study_type_recommendation(study_type: str) -> Optional[Dict[str, Any]]:
    """Return the recommendation dict for a special study type, or None."""
    return STUDY_TYPE_RECOMMENDATIONS.get(study_type)


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
    "repeated_measures": repeated_measures,
    "linear_regression": linear_regression,
    "prediction_model": prediction_model,
    "kappa_agreement": kappa_agreement,
    "roc_auc": roc_auc,
    "correlation": correlation,
    "repeated_measures_anova": repeated_measures_anova,
    "survival_logrank": survival_logrank,
}


REVERSE_FORMULAS = {
    "single_proportion": reverse_single_proportion,
    "single_mean": reverse_single_mean,
    "two_proportions": reverse_two_proportions,
    "two_means": reverse_two_means,
    "paired_means": reverse_paired_means,
    "anova_means": reverse_anova_means,
    "repeated_measures": reverse_repeated_measures,
    "linear_regression": reverse_linear_regression,
    "prediction_model": reverse_prediction_model,
    "kappa_agreement": reverse_kappa_agreement,
    "roc_auc": reverse_roc_auc,
    "correlation": reverse_correlation,
    "repeated_measures_anova": reverse_repeated_measures_anova,
    "survival_logrank": reverse_survival_logrank,
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
