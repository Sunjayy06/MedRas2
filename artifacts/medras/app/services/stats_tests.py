"""Primary statistical test dispatcher.

Given an outcome variable, optional grouping variable, and the variable-type
classifications, this module:

1. Chooses the right test (t-test, Mann-Whitney, ANOVA, Kruskal-Wallis,
   chi-square / Fisher's exact, Pearson / Spearman correlation).
2. Runs it.
3. Returns: descriptives, normality results (where relevant), the test
   statistic + p-value, an effect size, achieved power, and a plain-English
   interpretation paragraph the front-end can render verbatim.

Keeping all the test maths in one module makes it easy for the front-end to
stay dumb (just renders dicts) and for code review to verify the formulas.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats import power as smpower

from .normality import normality_test


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _round(x: Optional[float], nd: int = 3) -> Optional[float]:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), nd)


def _fmt_p(p: Optional[float]) -> str:
    if p is None:
        return "n/a"
    if p < 0.001:
        return "p < 0.001"
    return f"p = {p:.3f}"


def _verdict(p: Optional[float], alpha: float = 0.05) -> str:
    if p is None:
        return "inconclusive"
    return "statistically significant" if p < alpha else "not statistically significant"


def _descriptives_scale(values: pd.Series) -> Dict[str, Any]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return {"n": 0}
    return {
        "n": int(len(clean)),
        "mean": _round(clean.mean(), 2),
        "sd": _round(clean.std(ddof=1), 2),
        "median": _round(clean.median(), 2),
        "q1": _round(clean.quantile(0.25), 2),
        "q3": _round(clean.quantile(0.75), 2),
        "min": _round(clean.min(), 2),
        "max": _round(clean.max(), 2),
    }


def _descriptives_nominal(values: pd.Series) -> Dict[str, Any]:
    clean = values.dropna().astype(str)
    if clean.empty:
        return {"n": 0, "counts": {}}
    counts = clean.value_counts().to_dict()
    pct = (clean.value_counts(normalize=True) * 100).round(1).to_dict()
    return {
        "n": int(len(clean)),
        "counts": {k: int(v) for k, v in counts.items()},
        "percentages": {k: float(v) for k, v in pct.items()},
    }


# ---------------------------------------------------------------------------
# Effect sizes
# ---------------------------------------------------------------------------


def _cohens_d(a: pd.Series, b: pd.Series) -> Optional[float]:
    a, b = pd.to_numeric(a, errors="coerce").dropna(), pd.to_numeric(b, errors="coerce").dropna()
    if len(a) < 2 or len(b) < 2:
        return None
    pooled = np.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(a) + len(b) - 2))
    if pooled == 0:
        return None
    return float((a.mean() - b.mean()) / pooled)


def _cohens_f_from_anova(groups: List[pd.Series]) -> Optional[float]:
    """Cohen's f for one-way ANOVA = sqrt(η² / (1 - η²))."""
    flat = pd.concat([pd.to_numeric(g, errors="coerce").dropna() for g in groups])
    if flat.empty:
        return None
    grand = flat.mean()
    ss_between = sum(len(pd.to_numeric(g, errors="coerce").dropna()) *
                     (pd.to_numeric(g, errors="coerce").dropna().mean() - grand) ** 2 for g in groups)
    ss_total = ((flat - grand) ** 2).sum()
    if ss_total == 0:
        return None
    eta2 = ss_between / ss_total
    if eta2 >= 1:
        return None
    return float(np.sqrt(eta2 / (1 - eta2)))


def _cramers_v(table: np.ndarray, chi2: float) -> Optional[float]:
    n = float(table.sum())
    if n == 0:
        return None
    r, k = table.shape
    denom = min(r - 1, k - 1)
    if denom <= 0:
        return None
    return float(np.sqrt(chi2 / (n * denom)))


# ---------------------------------------------------------------------------
# Achieved power
# ---------------------------------------------------------------------------


def _power_two_sample_t(d: Optional[float], n1: int, n2: int, alpha: float = 0.05) -> Optional[float]:
    if d is None or n1 < 2 or n2 < 2:
        return None
    try:
        ratio = n2 / n1 if n1 else 1.0
        return float(
            smpower.TTestIndPower().solve_power(
                effect_size=abs(d), nobs1=n1, alpha=alpha, ratio=ratio
            )
        )
    except Exception:
        return None


def _power_anova(f: Optional[float], k: int, n_total: int, alpha: float = 0.05) -> Optional[float]:
    if f is None or k < 2 or n_total < k * 2:
        return None
    try:
        return float(
            smpower.FTestAnovaPower().solve_power(
                effect_size=abs(f), k_groups=k, nobs=n_total, alpha=alpha
            )
        )
    except Exception:
        return None


def _power_chi(w: Optional[float], n: int, dof: int, alpha: float = 0.05) -> Optional[float]:
    if w is None or n < 2 or dof < 1:
        return None
    try:
        return float(
            smpower.GofChisquarePower().solve_power(
                effect_size=abs(w), nobs=n, alpha=alpha, n_bins=dof + 1
            )
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _two_groups_scale(
    df: pd.DataFrame, outcome: str, group: str, alpha: float
) -> Dict[str, Any]:
    levels = df[group].dropna().astype(str).unique().tolist()
    a = pd.to_numeric(df.loc[df[group].astype(str) == levels[0], outcome], errors="coerce").dropna()
    b = pd.to_numeric(df.loc[df[group].astype(str) == levels[1], outcome], errors="coerce").dropna()

    norm_a = normality_test(a, alpha=alpha)
    norm_b = normality_test(b, alpha=alpha)
    parametric_ok = bool(norm_a.get("is_normal")) and bool(norm_b.get("is_normal"))

    # Levene's for homogeneity of variance — informs Welch's correction.
    try:
        levene_stat, levene_p = stats.levene(a, b, center="median")
        equal_var = bool(levene_p > alpha)
    except Exception:
        levene_stat, levene_p, equal_var = None, None, True

    if parametric_ok:
        stat, p = stats.ttest_ind(a, b, equal_var=equal_var)
        test_name = "Independent samples t-test" + ("" if equal_var else " (Welch's)")
        d = _cohens_d(a, b)
        achieved_power = _power_two_sample_t(d, len(a), len(b), alpha=alpha)
        effect_size = {"name": "Cohen's d", "value": _round(d, 3)}
        if equal_var:
            df_value: Optional[float] = float(len(a) + len(b) - 2)
        else:
            # Welch–Satterthwaite approximation.
            va = float(a.var(ddof=1)) if len(a) > 1 else 0.0
            vb = float(b.var(ddof=1)) if len(b) > 1 else 0.0
            num = (va / len(a) + vb / len(b)) ** 2
            denom = (
                (va / len(a)) ** 2 / (len(a) - 1) if len(a) > 1 else 0.0
            ) + (
                (vb / len(b)) ** 2 / (len(b) - 1) if len(b) > 1 else 0.0
            )
            df_value = (num / denom) if denom > 0 else None
    else:
        stat, p = stats.mannwhitneyu(a, b, alternative="two-sided")
        test_name = "Mann-Whitney U"
        # Rank-biserial r as effect size: 1 - (2U) / (n1*n2).
        u = float(stat)
        rb = 1 - (2 * u) / (len(a) * len(b)) if len(a) and len(b) else None
        effect_size = {"name": "Rank-biserial r", "value": _round(rb, 3)}
        achieved_power = None  # Power for non-parametric is approximated only.
        df_value = None

    return {
        "test": test_name,
        "statistic": _round(stat, 3),
        "p_value": _round(p, 4),
        "df": _round(df_value, 2) if df_value is not None else None,
        "effect_size": effect_size,
        "achieved_power": _round(achieved_power, 3) if achieved_power else None,
        "groups": [
            {"name": levels[0], **_descriptives_scale(a)},
            {"name": levels[1], **_descriptives_scale(b)},
        ],
        "assumptions": {
            "normality": {levels[0]: norm_a, levels[1]: norm_b},
            "equal_variance": {
                "test": "Levene",
                "statistic": _round(levene_stat, 3),
                "p_value": _round(levene_p, 4),
                "equal": equal_var,
            },
            "parametric_path": parametric_ok,
        },
        "interpretation": _interpret_two_groups(
            outcome, levels, _round(p, 4), test_name, effect_size, achieved_power, alpha
        ),
    }


def _multi_groups_scale(
    df: pd.DataFrame, outcome: str, group: str, alpha: float
) -> Dict[str, Any]:
    raw_levels = df[group].dropna().astype(str).unique().tolist()
    # Build (level, array) pairs together so we can filter both in lockstep.
    paired = [
        (lv, pd.to_numeric(df.loc[df[group].astype(str) == lv, outcome], errors="coerce").dropna())
        for lv in raw_levels
    ]
    paired = [(lv, arr) for lv, arr in paired if len(arr) >= 2]
    if len(paired) < 2:
        return {"error": "Not enough non-empty groups to compare."}
    levels = [lv for lv, _ in paired]
    arrays = [arr for _, arr in paired]

    norms = [normality_test(a, alpha=alpha) for a in arrays]
    parametric_ok = all(n.get("is_normal") for n in norms)

    if parametric_ok:
        stat, p = stats.f_oneway(*arrays)
        test_name = "One-way ANOVA"
        f_eff = _cohens_f_from_anova(arrays)
        n_total = sum(len(a) for a in arrays)
        achieved_power = _power_anova(f_eff, len(arrays), n_total, alpha=alpha)
        effect_size = {"name": "Cohen's f", "value": _round(f_eff, 3)}
    else:
        stat, p = stats.kruskal(*arrays)
        test_name = "Kruskal-Wallis H"
        # epsilon-squared as effect size for KW.
        n = sum(len(a) for a in arrays)
        eps2 = (float(stat) - len(arrays) + 1) / (n - len(arrays)) if n > len(arrays) else None
        effect_size = {"name": "Epsilon-squared", "value": _round(eps2, 3)}
        achieved_power = None

    descriptives = [{"name": lv, **_descriptives_scale(a)} for lv, a in zip(levels, arrays)]
    return {
        "test": test_name,
        "statistic": _round(stat, 3),
        "p_value": _round(p, 4),
        "df": len(arrays) - 1,
        "effect_size": effect_size,
        "achieved_power": _round(achieved_power, 3) if achieved_power else None,
        "groups": descriptives,
        "assumptions": {
            "normality": {lv: n for lv, n in zip(levels, norms)},
            "parametric_path": parametric_ok,
        },
        "interpretation": _interpret_multi_groups(
            outcome, levels, _round(p, 4), test_name, effect_size, achieved_power, alpha
        ),
    }


def _categorical_vs_categorical(
    df: pd.DataFrame, outcome: str, group: str, alpha: float
) -> Dict[str, Any]:
    # Drop rows missing either variable BEFORE casting to string — otherwise
    # NaN gets coerced to the literal string "nan" and biases the test.
    pair = df[[group, outcome]].dropna()
    if pair.empty:
        return {"error": "No complete pairs available for this comparison."}
    table = pd.crosstab(pair[group].astype(str), pair[outcome].astype(str))
    if table.shape[0] < 2 or table.shape[1] < 2:
        return {"error": "Crosstab needs at least two levels on each axis."}
    chi2, p, dof, expected = stats.chi2_contingency(table.values)
    use_fisher = bool(np.any(expected < 5)) and table.shape == (2, 2)
    if use_fisher:
        odds, p_fisher = stats.fisher_exact(table.values)
        test_name = "Fisher's exact test (small expected counts)"
        stat_value = _round(odds, 3)
        p_used = p_fisher
    else:
        test_name = "Chi-square test of independence"
        stat_value = _round(chi2, 3)
        p_used = p
    v = _cramers_v(table.values, float(chi2))
    achieved_power = _power_chi(v, int(table.values.sum()), dof, alpha=alpha)

    return {
        "test": test_name,
        "statistic": stat_value,
        "p_value": _round(p_used, 4),
        "df": dof,
        "effect_size": {"name": "Cramér's V", "value": _round(v, 3)},
        "achieved_power": _round(achieved_power, 3) if achieved_power else None,
        "table": {
            "rows": list(table.index.astype(str)),
            "cols": list(table.columns.astype(str)),
            "counts": table.values.astype(int).tolist(),
            "expected": np.round(expected, 2).tolist(),
        },
        "assumptions": {
            "min_expected": _round(float(np.min(expected)), 2),
            "fisher_used": use_fisher,
        },
        "interpretation": _interpret_categorical(
            outcome, group, _round(p_used, 4), test_name, v, achieved_power, alpha
        ),
    }


def _scale_vs_scale(
    df: pd.DataFrame, outcome: str, predictor: str, alpha: float
) -> Dict[str, Any]:
    a = pd.to_numeric(df[outcome], errors="coerce")
    b = pd.to_numeric(df[predictor], errors="coerce")
    pair = pd.concat([a, b], axis=1).dropna()
    if len(pair) < 5:
        return {"error": "Need at least 5 paired observations for correlation."}
    a, b = pair.iloc[:, 0], pair.iloc[:, 1]
    norm_a, norm_b = normality_test(a, alpha=alpha), normality_test(b, alpha=alpha)
    if bool(norm_a.get("is_normal")) and bool(norm_b.get("is_normal")):
        r, p = stats.pearsonr(a, b)
        test_name = "Pearson correlation"
        coef_name = "r"
    else:
        r, p = stats.spearmanr(a, b)
        test_name = "Spearman rank correlation"
        coef_name = "ρ"

    return {
        "test": test_name,
        "statistic": _round(r, 3),
        "p_value": _round(p, 4),
        "df": len(pair) - 2,
        "effect_size": {"name": coef_name, "value": _round(r, 3)},
        "achieved_power": None,
        "n": int(len(pair)),
        "assumptions": {
            "normality": {outcome: norm_a, predictor: norm_b},
        },
        "interpretation": _interpret_correlation(
            outcome, predictor, _round(r, 3), _round(p, 4), test_name, alpha
        ),
    }


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------


def run_primary_analysis(
    df: pd.DataFrame,
    *,
    outcome: str,
    group: Optional[str],
    classifications: List[Dict[str, Any]],
    alpha: float = 0.05,
) -> Dict[str, Any]:
    """Pick and run the right test based on variable types.

    Returns a dict shaped like::

        {
          "outcome": str,
          "group": str | None,
          "study_design": str,
          "test": ...,
          "statistic": ...,
          "p_value": ...,
          "interpretation": str,
          ...
        }
    """
    type_by_col = {c["column"]: c["detected_type"] for c in classifications}
    out_kind = type_by_col.get(outcome)
    grp_kind = type_by_col.get(group) if group else None

    if outcome not in df.columns:
        return {"error": f"Outcome column '{outcome}' not found in dataset."}
    if group and group not in df.columns:
        return {"error": f"Group/predictor column '{group}' not found in dataset."}

    # 1) Continuous outcome.
    if out_kind in ("scale", "ordinal"):
        if group is None:
            # Single-sample descriptives only — no inferential test without a comparator.
            return {
                "outcome": outcome,
                "group": None,
                "study_design": "Single-sample descriptives",
                "test": "Descriptive statistics only",
                "statistic": None,
                "p_value": None,
                "df": None,
                "effect_size": None,
                "achieved_power": None,
                "groups": [{"name": outcome, **_descriptives_scale(df[outcome])}],
                "interpretation": (
                    f"Descriptive statistics for {outcome}: "
                    f"mean = {_round(pd.to_numeric(df[outcome], errors='coerce').mean(), 2)}, "
                    f"SD = {_round(pd.to_numeric(df[outcome], errors='coerce').std(ddof=1), 2)}. "
                    "No grouping variable was provided, so no comparison test was run."
                ),
                "alpha": alpha,
            }
        if grp_kind in ("nominal", "ordinal"):
            n_groups = int(df[group].dropna().astype(str).nunique())
            if n_groups < 2:
                return {"error": "Group variable has fewer than two distinct values."}
            if n_groups == 2:
                result = _two_groups_scale(df, outcome, group, alpha)
                design = "Two independent groups, continuous outcome"
            else:
                result = _multi_groups_scale(df, outcome, group, alpha)
                design = f"{n_groups} independent groups, continuous outcome"
            result.update({"outcome": outcome, "group": group, "study_design": design, "alpha": alpha})
            return result
        if grp_kind in ("scale", "ordinal"):
            result = _scale_vs_scale(df, outcome, group, alpha)
            result.update({
                "outcome": outcome, "group": group,
                "study_design": "Continuous outcome vs continuous predictor (correlation)",
                "alpha": alpha,
            })
            return result

    # 2) Categorical outcome.
    if out_kind == "nominal":
        if group is None:
            return {
                "outcome": outcome,
                "group": None,
                "study_design": "Single-sample frequencies",
                "test": "Descriptive frequencies only",
                "statistic": None,
                "p_value": None,
                "df": None,
                "effect_size": None,
                "achieved_power": None,
                "groups": [{"name": outcome, **_descriptives_nominal(df[outcome])}],
                "interpretation": (
                    f"Frequency table for {outcome}. No grouping variable was "
                    "provided, so no comparison test was run."
                ),
                "alpha": alpha,
            }
        if grp_kind in ("nominal", "ordinal"):
            result = _categorical_vs_categorical(df, outcome, group, alpha)
            result.update({
                "outcome": outcome, "group": group,
                "study_design": "Categorical outcome vs categorical predictor",
                "alpha": alpha,
            })
            return result

    return {
        "error": (
            f"Cannot pick a test for outcome={outcome} ({out_kind}) "
            f"with predictor={group} ({grp_kind}). "
            "Please change the variable classifications."
        )
    }


# ---------------------------------------------------------------------------
# Auto-written interpretations
# ---------------------------------------------------------------------------


def _power_phrase(power: Optional[float]) -> str:
    if power is None:
        return ""
    pct = round(power * 100)
    if power >= 0.80:
        verdict = "adequate"
    elif power >= 0.60:
        verdict = "borderline"
    else:
        verdict = "underpowered"
    return f" Achieved statistical power was {pct}% ({verdict})."


def _interpret_two_groups(
    outcome: str, levels: List[str], p: Optional[float], test: str,
    effect: Dict[str, Any], power: Optional[float], alpha: float,
) -> str:
    direction = ""
    es = effect.get("value")
    if es is not None:
        if effect["name"] == "Cohen's d":
            mag = abs(es)
            if mag < 0.2: size = "negligible"
            elif mag < 0.5: size = "small"
            elif mag < 0.8: size = "medium"
            else: size = "large"
            direction = f" Effect size was {size} ({effect['name']} = {es})."
    sig = _verdict(p, alpha)
    return (
        f"{outcome} was compared between {levels[0]} and {levels[1]} "
        f"using a {test}. The difference was {sig} ({_fmt_p(p)})." + direction + _power_phrase(power)
    )


def _interpret_multi_groups(
    outcome: str, levels: List[str], p: Optional[float], test: str,
    effect: Dict[str, Any], power: Optional[float], alpha: float,
) -> str:
    sig = _verdict(p, alpha)
    es = effect.get("value")
    es_phrase = ""
    if es is not None:
        es_phrase = f" Effect size {effect['name']} = {es}."
    posthoc = ""
    if p is not None and p < alpha:
        posthoc = (
            " Because the omnibus test was significant, post-hoc pairwise "
            "comparisons (Tukey HSD or Dunn's test) should be reported."
        )
    return (
        f"{outcome} was compared across {len(levels)} groups "
        f"({', '.join(levels)}) using a {test}. The overall difference was "
        f"{sig} ({_fmt_p(p)})." + es_phrase + posthoc + _power_phrase(power)
    )


def _interpret_categorical(
    outcome: str, group: str, p: Optional[float], test: str,
    cramers_v: Optional[float], power: Optional[float], alpha: float,
) -> str:
    sig = _verdict(p, alpha)
    es = ""
    if cramers_v is not None:
        v = cramers_v
        if v < 0.1: strength = "negligible"
        elif v < 0.3: strength = "weak"
        elif v < 0.5: strength = "moderate"
        else: strength = "strong"
        es = f" The association strength was {strength} (Cramér's V = {round(v, 3)})."
    return (
        f"The association between {outcome} and {group} was evaluated using a "
        f"{test}. The association was {sig} ({_fmt_p(p)})." + es + _power_phrase(power)
    )


def _interpret_correlation(
    outcome: str, predictor: str, r: Optional[float], p: Optional[float],
    test: str, alpha: float,
) -> str:
    sig = _verdict(p, alpha)
    strength = ""
    if r is not None:
        a = abs(r)
        if a < 0.10: strength = "negligible"
        elif a < 0.30: strength = "weak"
        elif a < 0.50: strength = "moderate"
        elif a < 0.70: strength = "strong"
        else: strength = "very strong"
        sign = "positive" if r >= 0 else "negative"
        strength = f" The relationship was {sign} and {strength} (coefficient = {r})."
    return (
        f"The relationship between {outcome} and {predictor} was assessed "
        f"using a {test}. The correlation was {sig} ({_fmt_p(p)})." + strength
    )
