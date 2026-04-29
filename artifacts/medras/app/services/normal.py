"""Inverse-normal CDF using Acklam's algorithm.

Used to derive Z-scores for arbitrary alpha / beta values without pulling in
SciPy. Accuracy is ~1e-9 across the central range, which is more than enough
for sample-size calculations.

Reference: Peter J. Acklam, "An algorithm for computing the inverse normal
cumulative distribution function" (2003).
"""

from __future__ import annotations

import math


# Coefficients in rational approximations.
_A = [
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
]
_B = [
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
]
_C = [
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
]
_D = [
    7.784695709041462e-03,
    3.224671290700398e-01,
    2.445134137142996e00,
    3.754408661907416e00,
]

_P_LOW = 0.02425
_P_HIGH = 1 - _P_LOW


def normal_inv(p: float) -> float:
    """Return the value x such that Phi(x) = p, for 0 < p < 1."""
    if not 0 < p < 1:
        raise ValueError("p must be in (0, 1)")
    if p < _P_LOW:
        q = math.sqrt(-2 * math.log(p))
        return (
            ((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]
        ) / ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1)
    if p <= _P_HIGH:
        q = p - 0.5
        r = q * q
        return (
            (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5])
            * q
            / (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1)
        )
    q = math.sqrt(-2 * math.log(1 - p))
    return -(
        ((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]
    ) / ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1)


def z_two_tailed(alpha: float) -> float:
    """Critical Z value for a two-tailed test at significance level alpha."""
    return normal_inv(1 - alpha / 2)


def z_one_tailed(alpha: float) -> float:
    """Critical Z value for a one-tailed test at significance level alpha."""
    return normal_inv(1 - alpha)


def z_power(power: float) -> float:
    """Z value associated with the desired statistical power (1 - beta)."""
    return normal_inv(power)
