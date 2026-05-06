"""Phase-C statistical tests — extends the engine with the bulk of the
catalogue described in `Stat_Engine_Tests.docx` (sections 9.1-9.22).

Every runner here is library-backed (scipy / statsmodels / scikit-learn /
pingouin / lifelines / scikit-posthocs / factor_analyzer / dcor /
linearmodels). No hand-rolled inferential statistics except where the
algorithm is published in a peer-reviewed paper and explicitly noted in
the docstring (currently only DeLong's test, after Sun & Xu 2014, IEEE SPL).

Every function returns the same normalised dict shape consumed by
`results.run_plan`:
    {
      'test', 'test_type', 'n',
      'p' (optional), 'interpretation' / 'result_text',
      'rows' (optional list of per-row dicts),
      'effect_size'/'effect_label'/'ci_lo'/'ci_hi' (optional),
    }
On failure they return {'error': '...'} or {'warning': '...', 'partial_result': True}.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import stats as _ss

# Imported helpers from results.py — kept lazy to avoid import cycles.
def _h():
    from app.services import results as _r
    return _r


# ===========================================================================
# §9.1 Descriptive statistics — extended summary
# ===========================================================================

def run_descriptive_extended(col: str, session: Dict, df: pd.DataFrame, group: Optional[str] = None) -> Dict:
    """Mean, SD, Variance, IQR, Q1/Q3, percentiles, 95% CI of mean, CV,
    skewness and kurtosis. Library: scipy.stats + numpy + pandas."""
    s = pd.to_numeric(df[col], errors='coerce').dropna()
    n = len(s)
    if n == 0:
        return {'error': f'{col} has no numeric values.'}

    mean = float(s.mean())
    sd = float(s.std(ddof=1)) if n > 1 else float('nan')
    var = float(s.var(ddof=1)) if n > 1 else float('nan')
    median = float(s.median())
    q1 = float(s.quantile(0.25))
    q3 = float(s.quantile(0.75))
    iqr = q3 - q1
    pcts = {p: float(s.quantile(p / 100)) for p in (5, 25, 50, 75, 95)}
    cv = (sd / mean * 100) if mean and not math.isnan(sd) else None
    skew = float(_ss.skew(s, bias=False)) if n >= 3 else None
    kurt = float(_ss.kurtosis(s, fisher=True, bias=False)) if n >= 4 else None
    se = sd / math.sqrt(n) if n > 1 else float('nan')
    ci_lo = mean - 1.96 * se
    ci_hi = mean + 1.96 * se

    return {
        'test': 'Descriptive statistics (extended)',
        'test_type': 'descriptive_extended',
        'n': n,
        'mean': round(mean, 4),
        'sd': round(sd, 4) if not math.isnan(sd) else None,
        'variance': round(var, 4) if not math.isnan(var) else None,
        'median': round(median, 4),
        'q1': round(q1, 4),
        'q3': round(q3, 4),
        'iqr': round(iqr, 4),
        'min': float(s.min()),
        'max': float(s.max()),
        'range': float(s.max() - s.min()),
        'percentiles': {f'P{p}': round(v, 4) for p, v in pcts.items()},
        'cv_percent': round(cv, 2) if cv is not None else None,
        'skewness': round(skew, 3) if skew is not None else None,
        'kurtosis': round(kurt, 3) if kurt is not None else None,
        'mean_95ci': (round(ci_lo, 4), round(ci_hi, 4)),
        'interpretation': (
            f'{col} (n={n}): mean = {mean:.3f} ± {sd:.3f} '
            f'(95% CI {ci_lo:.3f}–{ci_hi:.3f}). Median = {median:.3f} '
            f'(IQR {q1:.3f}–{q3:.3f}). Skew = {skew:.2f}, Kurt = {kurt:.2f}.'
            if (skew is not None and kurt is not None) else
            f'{col} (n={n}): mean = {mean:.3f}, median = {median:.3f}.'),
    }


def run_crosstab(col1: str, col2: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Crosstabulation with observed counts, expected counts, row %, col %."""
    data = df[[col1, col2]].dropna()
    n = len(data)
    if n == 0:
        return {'error': 'No valid observations.'}
    obs = pd.crosstab(data[col1], data[col2])
    chi2, p, dof, expected = _ss.chi2_contingency(obs, correction=False)
    row_pct = (obs.div(obs.sum(axis=1), axis=0) * 100).round(2)
    col_pct = (obs.div(obs.sum(axis=0), axis=1) * 100).round(2)
    return {
        'test': 'Crosstabulation',
        'test_type': 'crosstab',
        'n': n,
        'observed': obs.values.tolist(),
        'expected': expected.tolist(),
        'row_percent': row_pct.values.tolist(),
        'col_percent': col_pct.values.tolist(),
        'row_labels': obs.index.astype(str).tolist(),
        'col_labels': obs.columns.astype(str).tolist(),
        'chi2': round(float(chi2), 3),
        'p': float(p),
        'dof': int(dof),
        'interpretation': (
            f'Crosstab of {col1} × {col2} (n={n}). '
            f'χ² = {chi2:.3f} (df={dof}), p = {_h().fmt_p(float(p))}.'),
    }


# ===========================================================================
# §9.2 Compare means — extras
# ===========================================================================

def run_one_sample_t(col: str, session: Dict, df: pd.DataFrame, mu0: float = 0.0) -> Dict:
    """One-sample t-test against a reference value mu0. Library: scipy."""
    s = pd.to_numeric(df[col], errors='coerce').dropna()
    n = len(s)
    if n < 5:
        return {'error': f'Sample too small (n={n}).'}
    t, p = _ss.ttest_1samp(s, popmean=mu0, alternative='two-sided')
    mean = float(s.mean())
    sd = float(s.std(ddof=1))
    se = sd / math.sqrt(n)
    t_crit = _ss.t.ppf(0.975, df=n - 1)
    ci = (mean - t_crit * se, mean + t_crit * se)
    d = (mean - mu0) / sd if sd > 0 else 0.0
    eff = 'small' if abs(d) < 0.5 else 'medium' if abs(d) < 0.8 else 'large'
    return {
        'test': 'One-sample t-test',
        'test_type': 't_test_one_sample',
        'n': n,
        't': round(float(t), 3),
        'df': n - 1,
        'p': float(p),
        'mean': round(mean, 3),
        'mu0': mu0,
        'mean_diff': round(mean - mu0, 3),
        'ci': (round(ci[0], 3), round(ci[1], 3)),
        'cohens_d': round(d, 3),
        'effect_interpretation': eff,
        'interpretation': (
            f'One-sample t-test for {col} vs μ₀={mu0} (n={n}): '
            f'mean = {mean:.3f} (95% CI {ci[0]:.3f}–{ci[1]:.3f}), '
            f't({n-1}) = {float(t):.3f}, p = {_h().fmt_p(float(p))}, '
            f"Cohen's d = {d:.3f} ({eff})."),
    }


def run_two_way_anova(outcome: str, factor1: str, factor2: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Two-way ANOVA with interaction. Library: statsmodels OLS + anova_lm."""
    import statsmodels.formula.api as smf
    from statsmodels.stats.anova import anova_lm
    data = df[[outcome, factor1, factor2]].dropna()
    n = len(data)
    if n < 12:
        return {'error': f'Sample too small (n={n}). Two-way ANOVA needs ≥12.'}
    formula = f'Q("{outcome}") ~ C(Q("{factor1}")) * C(Q("{factor2}"))'
    try:
        model = smf.ols(formula, data=data).fit()
        table = anova_lm(model, typ=2)
    except Exception as e:
        return {'error': f'Two-way ANOVA failed: {e}'}
    rows = []
    for term in table.index:
        if term == 'Residual':
            continue
        ss = float(table.loc[term, 'sum_sq'])
        f = float(table.loc[term, 'F']) if not pd.isna(table.loc[term, 'F']) else None
        p = float(table.loc[term, 'PR(>F)']) if not pd.isna(table.loc[term, 'PR(>F)']) else None
        ss_total = float(table['sum_sq'].sum())
        eta2 = ss / ss_total if ss_total > 0 else 0.0
        rows.append({
            'term': str(term),
            'F': round(f, 3) if f is not None else None,
            'df': int(table.loc[term, 'df']),
            'p': p,
            'p_display': _h().fmt_p(p),
            'partial_eta2': round(eta2, 3),
        })
    main_p = next((r['p'] for r in rows if r['p'] is not None), None)
    return {
        'test': 'Two-way ANOVA',
        'test_type': 'two_way_anova',
        'n': n,
        'rows': rows,
        'r_squared': round(float(model.rsquared), 3),
        'p': main_p,
        'interpretation': (
            f'Two-way ANOVA on {outcome} by {factor1} × {factor2} (n={n}). '
            f'R² = {model.rsquared:.3f}. See term table for F and p.'),
    }


def run_factorial_anova(outcome: str, factors: Sequence[str], session: Dict, df: pd.DataFrame) -> Dict:
    """Three-way / factorial ANOVA — k factors with full interactions.
    Library: statsmodels OLS + anova_lm (Type II)."""
    import statsmodels.formula.api as smf
    from statsmodels.stats.anova import anova_lm
    factors = list(factors)
    if len(factors) < 2:
        return {'error': 'Factorial ANOVA needs ≥2 factors.'}
    data = df[[outcome] + factors].dropna()
    n = len(data)
    if n < 4 * len(factors):
        return {'error': f'Sample too small (n={n}) for {len(factors)}-way ANOVA.'}
    rhs = ' * '.join([f'C(Q("{f}"))' for f in factors])
    formula = f'Q("{outcome}") ~ {rhs}'
    try:
        model = smf.ols(formula, data=data).fit()
        table = anova_lm(model, typ=2)
    except Exception as e:
        return {'error': f'Factorial ANOVA failed: {e}'}
    rows = []
    ss_total = float(table['sum_sq'].sum())
    for term in table.index:
        if term == 'Residual':
            continue
        ss = float(table.loc[term, 'sum_sq'])
        f = table.loc[term, 'F']
        p = table.loc[term, 'PR(>F)']
        rows.append({
            'term': str(term),
            'df': int(table.loc[term, 'df']),
            'F': round(float(f), 3) if not pd.isna(f) else None,
            'p': float(p) if not pd.isna(p) else None,
            'p_display': _h().fmt_p(float(p)) if not pd.isna(p) else '-',
            'partial_eta2': round(ss / ss_total, 3) if ss_total > 0 else 0.0,
        })
    main_p = next((r['p'] for r in rows if r['p'] is not None), None)
    return {
        'test': f'{len(factors)}-way factorial ANOVA',
        'test_type': 'factorial_anova',
        'n': n,
        'rows': rows,
        'r_squared': round(float(model.rsquared), 3),
        'p': main_p,
        'interpretation': (
            f'{len(factors)}-way factorial ANOVA on {outcome} '
            f'(factors: {", ".join(factors)}, n={n}). '
            f'R² = {model.rsquared:.3f}.'),
    }


def run_ancova(outcome: str, group: str, covariates: Sequence[str], session: Dict, df: pd.DataFrame) -> Dict:
    """ANCOVA: outcome ~ group + covariate(s). Library: statsmodels."""
    import statsmodels.formula.api as smf
    from statsmodels.stats.anova import anova_lm
    covariates = list(covariates)
    cols = [outcome, group] + covariates
    data = df[cols].dropna()
    n = len(data)
    if n < 15:
        return {'error': f'Sample too small (n={n}).'}
    cov_terms = ' + '.join([f'Q("{c}")' for c in covariates])
    formula = f'Q("{outcome}") ~ C(Q("{group}")) + {cov_terms}'
    try:
        model = smf.ols(formula, data=data).fit()
        table = anova_lm(model, typ=2)
    except Exception as e:
        return {'error': f'ANCOVA failed: {e}'}
    rows = []
    ss_total = float(table['sum_sq'].sum())
    for term in table.index:
        if term == 'Residual':
            continue
        ss = float(table.loc[term, 'sum_sq'])
        f = table.loc[term, 'F']
        p = table.loc[term, 'PR(>F)']
        rows.append({
            'term': str(term),
            'df': int(table.loc[term, 'df']),
            'F': round(float(f), 3) if not pd.isna(f) else None,
            'p': float(p) if not pd.isna(p) else None,
            'p_display': _h().fmt_p(float(p)) if not pd.isna(p) else '-',
            'partial_eta2': round(ss / ss_total, 3) if ss_total > 0 else 0.0,
        })
    group_p = next((r['p'] for r in rows if r['term'].startswith('C(') and r['p'] is not None), None)
    return {
        'test': 'ANCOVA',
        'test_type': 'ancova',
        'n': n,
        'rows': rows,
        'r_squared': round(float(model.rsquared), 3),
        'p': group_p,
        'interpretation': (
            f'ANCOVA: {outcome} ~ {group} adjusting for '
            f'{", ".join(covariates)} (n={n}). R² = {model.rsquared:.3f}, '
            f'group p = {_h().fmt_p(group_p) if group_p else "-"}.'),
    }


def run_mixed_anova(dv: str, between: str, within: str, subject: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Mixed (split-plot) ANOVA — one between-groups factor and one
    within-subjects factor. Library: pingouin.mixed_anova."""
    import pingouin as pg
    data = df[[dv, between, within, subject]].dropna()
    n = len(data)
    if n < 10:
        return {'error': f'Sample too small (n={n}).'}
    try:
        res = pg.mixed_anova(data=data, dv=dv, within=within,
                             between=between, subject=subject)
    except Exception as e:
        return {'error': f'Mixed ANOVA failed: {e}'}
    rows = []
    for _, r in res.iterrows():
        rows.append({
            'source': str(r['Source']),
            'F': round(float(r['F']), 3) if pd.notna(r.get('F')) else None,
            'df1': float(r['DF1']) if pd.notna(r.get('DF1')) else None,
            'df2': float(r['DF2']) if pd.notna(r.get('DF2')) else None,
            'p': float(r['p-unc']) if pd.notna(r.get('p-unc')) else None,
            'p_display': _h().fmt_p(float(r['p-unc'])) if pd.notna(r.get('p-unc')) else '-',
            'np2': round(float(r['np2']), 3) if pd.notna(r.get('np2')) else None,
        })
    p_int = next((r['p'] for r in rows if r['source'].lower() == 'interaction'), None)
    return {
        'test': 'Mixed (split-plot) ANOVA',
        'test_type': 'mixed_anova',
        'n': n,
        'rows': rows,
        'p': p_int,
        'interpretation': (
            f'Mixed ANOVA: {dv} ~ {between} (between) × {within} (within) '
            f'with subject = {subject}, n = {n}.'),
    }


def run_manova(outcomes: Sequence[str], group: str, session: Dict, df: pd.DataFrame) -> Dict:
    """MANOVA — multiple continuous DVs vs a categorical IV.
    Library: statsmodels.multivariate.manova.MANOVA."""
    from statsmodels.multivariate.manova import MANOVA
    outcomes = list(outcomes)
    cols = outcomes + [group]
    data = df[cols].dropna()
    n = len(data)
    if n < max(20, 3 * len(outcomes)):
        return {'error': f'Sample too small (n={n}).'}
    formula = ' + '.join([f'Q("{o}")' for o in outcomes]) + f' ~ C(Q("{group}"))'
    try:
        m = MANOVA.from_formula(formula, data=data)
        res = m.mv_test()
    except Exception as e:
        return {'error': f'MANOVA failed: {e}'}
    # Pull Wilks' lambda for the group effect.
    rows = []
    p_main = None
    for term, payload in res.results.items():
        if term == 'Intercept':
            continue
        try:
            stat_df = payload['stat']
            for stat_name in ("Wilks' lambda", "Pillai's trace",
                              "Hotelling-Lawley trace", "Roy's greatest root"):
                if stat_name in stat_df.index:
                    val = float(stat_df.loc[stat_name, 'Value'])
                    f = float(stat_df.loc[stat_name, 'F Value'])
                    p = float(stat_df.loc[stat_name, 'Pr > F'])
                    if stat_name == "Wilks' lambda" and p_main is None:
                        p_main = p
                    rows.append({
                        'term': str(term),
                        'statistic_name': stat_name,
                        'value': round(val, 4),
                        'F': round(f, 3),
                        'p': p,
                        'p_display': _h().fmt_p(p),
                    })
        except Exception:
            continue
    return {
        'test': 'MANOVA',
        'test_type': 'manova',
        'n': n,
        'rows': rows,
        'p': p_main,
        'interpretation': (
            f'MANOVA: {len(outcomes)} outcomes ({", ".join(outcomes)}) by '
            f'{group}, n = {n}. Wilks p = '
            f'{_h().fmt_p(p_main) if p_main else "-"}.'),
    }


# ===========================================================================
# §9.3 GLM — Generalised Linear Models
# ===========================================================================

def _fit_glm(outcome: str, predictors: Sequence[str], df: pd.DataFrame, family) -> Tuple[Any, pd.DataFrame, int]:
    import statsmodels.formula.api as smf
    cols = [outcome] + list(predictors)
    data = df[cols].dropna()
    n = len(data)
    formula = f'Q("{outcome}") ~ ' + ' + '.join([f'Q("{p}")' for p in predictors])
    res = smf.glm(formula, data=data, family=family).fit()
    return res, data, n


def run_glm(outcome: str, predictors: Sequence[str], session: Dict, df: pd.DataFrame, family: str = 'binomial') -> Dict:
    """Generalised Linear Model — family ∈ {binomial, poisson, gamma,
    inverse_gaussian, gaussian, negative_binomial}. Library: statsmodels."""
    import statsmodels.api as sm
    fam_map = {
        'binomial': sm.families.Binomial(),
        'poisson': sm.families.Poisson(),
        'gamma': sm.families.Gamma(),
        'inverse_gaussian': sm.families.InverseGaussian(),
        'gaussian': sm.families.Gaussian(),
        'negative_binomial': sm.families.NegativeBinomial(),
    }
    if family not in fam_map:
        return {'error': f'Unknown GLM family {family}.'}
    if not predictors:
        return {'error': 'At least one predictor required.'}
    try:
        res, data, n = _fit_glm(outcome, predictors, df, fam_map[family])
    except Exception as e:
        return {'error': f'GLM ({family}) failed: {e}'}
    rows = []
    for p in predictors:
        if p in res.params.index:
            coef = float(res.params[p])
            se = float(res.bse[p])
            pv = float(res.pvalues[p])
            ci_lo = coef - 1.96 * se
            ci_hi = coef + 1.96 * se
            row = {
                'variable': p,
                'coef': round(coef, 4),
                'se': round(se, 4),
                'p': pv,
                'p_display': _h().fmt_p(pv),
                'ci': (round(ci_lo, 4), round(ci_hi, 4)),
            }
            if family == 'binomial':
                row['OR'] = round(math.exp(coef), 3)
                row['OR_ci'] = (round(math.exp(ci_lo), 3), round(math.exp(ci_hi), 3))
            elif family in ('poisson', 'negative_binomial'):
                row['IRR'] = round(math.exp(coef), 3)
                row['IRR_ci'] = (round(math.exp(ci_lo), 3), round(math.exp(ci_hi), 3))
            rows.append(row)
    return {
        'test': f'GLM — {family}',
        'test_type': f'glm_{family}',
        'n': n,
        'rows': rows,
        'aic': round(float(res.aic), 2),
        'bic': round(float(res.bic), 2) if hasattr(res, 'bic') else None,
        'deviance': round(float(res.deviance), 2),
        'interpretation': (
            f'GLM ({family}): {outcome} ~ {", ".join(predictors)} (n={n}). '
            f'AIC = {res.aic:.2f}, deviance = {res.deviance:.2f}.'),
    }


def run_gee(outcome: str, predictors: Sequence[str], cluster: str, session: Dict, df: pd.DataFrame, family: str = 'gaussian') -> Dict:
    """Generalised Estimating Equations for clustered/correlated data.
    Library: statsmodels.GEE."""
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    fam_map = {
        'gaussian': sm.families.Gaussian(),
        'binomial': sm.families.Binomial(),
        'poisson': sm.families.Poisson(),
    }
    if family not in fam_map:
        return {'error': f'Unsupported GEE family {family}.'}
    cols = [outcome, cluster] + list(predictors)
    data = df[cols].dropna()
    n = len(data)
    if n < 20:
        return {'error': f'Sample too small (n={n}).'}
    formula = f'Q("{outcome}") ~ ' + ' + '.join([f'Q("{p}")' for p in predictors])
    try:
        model = smf.gee(formula, groups=cluster, data=data,
                        family=fam_map[family],
                        cov_struct=sm.cov_struct.Exchangeable())
        res = model.fit()
    except Exception as e:
        return {'error': f'GEE failed: {e}'}
    rows = []
    for p in predictors:
        if p in res.params.index:
            coef = float(res.params[p])
            se = float(res.bse[p])
            pv = float(res.pvalues[p])
            rows.append({
                'variable': p,
                'coef': round(coef, 4),
                'robust_se': round(se, 4),
                'p': pv,
                'p_display': _h().fmt_p(pv),
                'ci': (round(coef - 1.96 * se, 4), round(coef + 1.96 * se, 4)),
            })
    return {
        'test': f'GEE ({family}, exchangeable)',
        'test_type': 'gee',
        'n': n,
        'n_clusters': int(data[cluster].nunique()),
        'rows': rows,
        'interpretation': (
            f'GEE ({family}): {outcome} clustered by {cluster}, '
            f'n = {n} obs in {data[cluster].nunique()} clusters.'),
    }


# ===========================================================================
# §9.4 Mixed (multi-level) models
# ===========================================================================

def run_linear_mixed(outcome: str, fixed: Sequence[str], group: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Linear mixed-effects model — random intercept by `group`.
    Library: statsmodels.MixedLM."""
    import statsmodels.formula.api as smf
    cols = [outcome, group] + list(fixed)
    data = df[cols].dropna()
    n = len(data)
    if n < 30 or data[group].nunique() < 3:
        return {'error': f'Need n≥30 and ≥3 groups (got n={n}, groups={data[group].nunique()}).'}
    formula = f'Q("{outcome}") ~ ' + ' + '.join([f'Q("{p}")' for p in fixed])
    try:
        res = smf.mixedlm(formula, data=data, groups=data[group]).fit(reml=True)
    except Exception as e:
        return {'error': f'Linear mixed model failed: {e}'}
    rows = []
    for p in fixed:
        if p in res.params.index:
            coef = float(res.params[p])
            se = float(res.bse[p])
            pv = float(res.pvalues[p])
            rows.append({
                'variable': p, 'coef': round(coef, 4),
                'se': round(se, 4), 'p': pv,
                'p_display': _h().fmt_p(pv),
                'ci': (round(coef - 1.96 * se, 4), round(coef + 1.96 * se, 4)),
            })
    re_var = float(res.cov_re.iloc[0, 0]) if hasattr(res, 'cov_re') else None
    return {
        'test': 'Linear mixed-effects model',
        'test_type': 'linear_mixed',
        'n': n,
        'n_groups': int(data[group].nunique()),
        'rows': rows,
        'random_intercept_variance': round(re_var, 4) if re_var is not None else None,
        'aic': round(float(res.aic), 2) if not math.isnan(res.aic) else None,
        'interpretation': (
            f'Linear mixed model: {outcome} ~ {", ".join(fixed)} '
            f'with random intercept by {group} '
            f'(n = {n}, groups = {data[group].nunique()}).'),
    }


# ===========================================================================
# §9.5 Correlations — extras
# ===========================================================================

def run_pearson(col1: str, col2: str, session: Dict, df: pd.DataFrame) -> Dict:
    data = df[[col1, col2]].apply(pd.to_numeric, errors='coerce').dropna()
    n = len(data)
    if n < 5:
        return {'error': f'Need ≥5 paired values (n={n}).'}
    r, p = _ss.pearsonr(data[col1], data[col2])
    z = math.atanh(r) if abs(r) < 0.999 else math.copysign(5.0, r)
    se = 1 / math.sqrt(n - 3) if n > 3 else float('nan')
    ci = (math.tanh(z - 1.96 * se), math.tanh(z + 1.96 * se))
    strength = ('negligible' if abs(r) < 0.2 else
                'weak' if abs(r) < 0.4 else
                'moderate' if abs(r) < 0.6 else
                'strong' if abs(r) < 0.8 else 'very strong')
    return {
        'test': 'Pearson correlation',
        'test_type': 'pearson',
        'n': n,
        'r': round(float(r), 3),
        'p': float(p),
        'p_display': _h().fmt_p(float(p)),
        'ci': (round(ci[0], 3), round(ci[1], 3)),
        'strength': strength,
        'interpretation': (
            f'Pearson r({n-2}) = {r:.3f} (95% CI {ci[0]:.3f}–{ci[1]:.3f}), '
            f'p = {_h().fmt_p(float(p))}, {strength} relationship.'),
    }


def run_spearman(col1: str, col2: str, session: Dict, df: pd.DataFrame) -> Dict:
    data = df[[col1, col2]].dropna()
    n = len(data)
    if n < 5:
        return {'error': f'Need ≥5 paired values (n={n}).'}
    rho, p = _ss.spearmanr(data[col1], data[col2])
    return {
        'test': 'Spearman rank correlation',
        'test_type': 'spearman',
        'n': n,
        'rho': round(float(rho), 3),
        'p': float(p),
        'p_display': _h().fmt_p(float(p)),
        'interpretation': (
            f'Spearman ρ = {rho:.3f}, p = {_h().fmt_p(float(p))} (n={n}).'),
    }


def run_kendall_tau(col1: str, col2: str, session: Dict, df: pd.DataFrame) -> Dict:
    data = df[[col1, col2]].dropna()
    n = len(data)
    if n < 5:
        return {'error': f'Need ≥5 paired values (n={n}).'}
    tau, p = _ss.kendalltau(data[col1], data[col2])
    return {
        'test': "Kendall's tau-b",
        'test_type': 'kendall_tau',
        'n': n,
        'tau': round(float(tau), 3),
        'p': float(p),
        'p_display': _h().fmt_p(float(p)),
        'interpretation': (
            f'Kendall τ-b = {tau:.3f}, p = {_h().fmt_p(float(p))} (n={n}).'),
    }


def run_partial_correlation(x: str, y: str, covariates: Sequence[str], session: Dict, df: pd.DataFrame) -> Dict:
    """Partial correlation controlling for covariates. Library: pingouin."""
    import pingouin as pg
    cols = [x, y] + list(covariates)
    data = df[cols].dropna()
    n = len(data)
    if n < 10:
        return {'error': f'Need ≥10 obs (n={n}).'}
    try:
        res = pg.partial_corr(data=data, x=x, y=y, covar=list(covariates))
    except Exception as e:
        return {'error': f'Partial correlation failed: {e}'}
    r = float(res['r'].iloc[0])
    p = float(res['p-val'].iloc[0])
    ci = res['CI95%'].iloc[0]
    return {
        'test': 'Partial correlation',
        'test_type': 'partial_correlation',
        'n': n,
        'r': round(r, 3),
        'ci': (round(float(ci[0]), 3), round(float(ci[1]), 3)),
        'p': p,
        'p_display': _h().fmt_p(p),
        'covariates': list(covariates),
        'interpretation': (
            f'Partial r({x}, {y} | {", ".join(covariates)}) = {r:.3f} '
            f'(95% CI {ci[0]:.3f}–{ci[1]:.3f}), p = {_h().fmt_p(p)} (n={n}).'),
    }


def run_point_biserial(continuous: str, binary: str, session: Dict, df: pd.DataFrame) -> Dict:
    data = df[[continuous, binary]].dropna()
    n = len(data)
    if n < 5:
        return {'error': f'Need ≥5 paired values (n={n}).'}
    try:
        b = pd.factorize(data[binary])[0]
    except Exception as e:
        return {'error': f'Cannot encode binary variable: {e}'}
    if len(set(b)) != 2:
        return {'error': 'Binary variable must have exactly 2 categories.'}
    r, p = _ss.pointbiserialr(b, data[continuous])
    return {
        'test': 'Point-biserial correlation',
        'test_type': 'point_biserial',
        'n': n,
        'r_pb': round(float(r), 3),
        'p': float(p),
        'p_display': _h().fmt_p(float(p)),
        'interpretation': (
            f'Point-biserial r = {r:.3f}, p = {_h().fmt_p(float(p))} (n={n}).'),
    }


def run_correlation_matrix(cols: Sequence[str], session: Dict, df: pd.DataFrame, method: str = 'pearson') -> Dict:
    """Pairwise correlation matrix with p-values. Library: scipy + pandas."""
    cols = [c for c in cols if c in df.columns]
    if len(cols) < 2:
        return {'error': 'Need ≥2 variables.'}
    data = df[cols].apply(pd.to_numeric, errors='coerce').dropna()
    n = len(data)
    if n < 5:
        return {'error': f'Need ≥5 obs (n={n}).'}
    fn = _ss.pearsonr if method == 'pearson' else _ss.spearmanr
    coefs = np.eye(len(cols))
    pvals = np.zeros((len(cols), len(cols)))
    for i, a in enumerate(cols):
        for j, b in enumerate(cols):
            if i == j:
                continue
            r, p = fn(data[a], data[b])
            coefs[i, j] = float(r)
            pvals[i, j] = float(p)
    return {
        'test': f'Correlation matrix ({method})',
        'test_type': 'correlation_matrix',
        'n': n,
        'variables': cols,
        'r_matrix': coefs.round(3).tolist(),
        'p_matrix': pvals.round(4).tolist(),
        'interpretation': (
            f'{method.capitalize()} correlation matrix for {len(cols)} '
            f'variables (n={n}). See r/p matrices.'),
    }


def run_distance_correlation(col1: str, col2: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Distance correlation — detects any (incl. non-linear) association.
    Library: dcor."""
    import dcor
    data = df[[col1, col2]].apply(pd.to_numeric, errors='coerce').dropna()
    n = len(data)
    if n < 10:
        return {'error': f'Need ≥10 obs (n={n}).'}
    try:
        d_corr = float(dcor.distance_correlation(data[col1].values, data[col2].values))
        # Permutation test for p-value (n_resamples 200 to keep latency low).
        test = dcor.independence.distance_covariance_test(
            data[col1].values, data[col2].values, num_resamples=200)
        p = float(test.pvalue)
    except Exception as e:
        return {'error': f'Distance correlation failed: {e}'}
    return {
        'test': 'Distance correlation',
        'test_type': 'distance_correlation',
        'n': n,
        'd_corr': round(d_corr, 3),
        'p': p,
        'p_display': _h().fmt_p(p),
        'interpretation': (
            f'Distance correlation = {d_corr:.3f}, '
            f'permutation p = {_h().fmt_p(p)} (n={n}, 200 resamples). '
            f'0 ⇒ independent; >0 ⇒ some association (linear or non-linear).'),
    }


# ===========================================================================
# §9.6 Regression — extras
# ===========================================================================

def run_linear_regression(outcome: str, predictors: Sequence[str], session: Dict, df: pd.DataFrame) -> Dict:
    """Simple or multiple linear regression. Library: statsmodels OLS."""
    import statsmodels.formula.api as smf
    cols = [outcome] + list(predictors)
    data = df[cols].dropna()
    n = len(data)
    if n < max(10, 3 * len(predictors)):
        return {'error': f'Sample too small (n={n}).'}
    formula = f'Q("{outcome}") ~ ' + ' + '.join([f'Q("{p}")' for p in predictors])
    try:
        res = smf.ols(formula, data=data).fit()
    except Exception as e:
        return {'error': f'OLS failed: {e}'}
    rows = []
    for p in predictors:
        if p in res.params.index:
            coef = float(res.params[p])
            se = float(res.bse[p])
            pv = float(res.pvalues[p])
            ci = res.conf_int().loc[p]
            rows.append({
                'variable': p,
                'B': round(coef, 4),
                'SE': round(se, 4),
                'beta_std': round(coef * (data[p].std() / data[outcome].std()), 3) if data[outcome].std() else None,
                't': round(float(res.tvalues[p]), 3),
                'p': pv,
                'p_display': _h().fmt_p(pv),
                'ci': (round(float(ci[0]), 4), round(float(ci[1]), 4)),
            })
    f2 = res.rsquared / (1 - res.rsquared) if res.rsquared < 1 else None
    return {
        'test': 'Linear regression' if len(predictors) == 1 else 'Multiple linear regression',
        'test_type': 'linear_regression',
        'n': n,
        'rows': rows,
        'r_squared': round(float(res.rsquared), 3),
        'adj_r_squared': round(float(res.rsquared_adj), 3),
        'f_statistic': round(float(res.fvalue), 3),
        'p': float(res.f_pvalue),
        'cohens_f2': round(f2, 3) if f2 is not None else None,
        'interpretation': (
            f'Linear regression: {outcome} ~ {", ".join(predictors)} (n={n}). '
            f'R² = {res.rsquared:.3f}, adj R² = {res.rsquared_adj:.3f}, '
            f'F = {res.fvalue:.2f}, p = {_h().fmt_p(float(res.f_pvalue))}.'),
    }


def run_binary_logistic(outcome: str, predictors: Sequence[str], session: Dict, df: pd.DataFrame) -> Dict:
    """Binary logistic regression with OR, 95% CI, Hosmer-Lemeshow, Nagelkerke R².
    Library: statsmodels Logit."""
    import statsmodels.formula.api as smf
    cols = [outcome] + list(predictors)
    data = df[cols].dropna().copy()
    n = len(data)
    if n < max(20, 10 * len(predictors)):
        return {'error': f'Sample too small (n={n}).'}
    if data[outcome].nunique() != 2:
        return {'error': 'Binary logistic needs a 2-level outcome.'}
    # Map outcome to 0/1.
    levels = sorted(data[outcome].dropna().unique().tolist())
    data['_y'] = (data[outcome] == levels[1]).astype(int)
    formula = '_y ~ ' + ' + '.join([f'Q("{p}")' for p in predictors])
    try:
        res = smf.logit(formula, data=data).fit(disp=False, maxiter=200)
    except Exception as e:
        return {'error': f'Logistic regression failed: {e}'}
    rows = []
    for p in predictors:
        if p in res.params.index:
            coef = float(res.params[p])
            se = float(res.bse[p])
            pv = float(res.pvalues[p])
            ci_lo = coef - 1.96 * se
            ci_hi = coef + 1.96 * se
            rows.append({
                'variable': p,
                'B': round(coef, 4),
                'SE': round(se, 4),
                'OR': round(math.exp(coef), 3),
                'OR_ci': (round(math.exp(ci_lo), 3), round(math.exp(ci_hi), 3)),
                'p': pv, 'p_display': _h().fmt_p(pv),
            })
    # Hosmer-Lemeshow + Nagelkerke from results.py.
    try:
        y_pred = res.predict(data)
        hl_stat, hl_df, hl_p = _h().hosmer_lemeshow(data['_y'], y_pred)
    except Exception:
        hl_stat = hl_df = hl_p = None
    try:
        nagelkerke = _h().nagelkerke_r2(res, n)
    except Exception:
        nagelkerke = None
    return {
        'test': 'Binary logistic regression',
        'test_type': 'logistic_regression',
        'n': n,
        'reference_class': levels[0],
        'positive_class': levels[1],
        'rows': rows,
        'aic': round(float(res.aic), 2),
        'nagelkerke_r2': nagelkerke,
        'hosmer_lemeshow': {'chi2': hl_stat, 'df': hl_df, 'p': hl_p,
                            'p_display': _h().fmt_p(hl_p) if hl_p is not None else '-'},
        'interpretation': (
            f'Binary logistic: {outcome} (1={levels[1]} vs 0={levels[0]}) '
            f'~ {", ".join(predictors)} (n={n}). '
            f"Nagelkerke R² = {nagelkerke}, "
            f"Hosmer-Lemeshow p = "
            f"{_h().fmt_p(hl_p) if hl_p is not None else '-'}."),
    }


def run_multinomial_logistic(outcome: str, predictors: Sequence[str], session: Dict, df: pd.DataFrame) -> Dict:
    """Multinomial logistic regression. Library: statsmodels MNLogit."""
    import statsmodels.formula.api as smf
    cols = [outcome] + list(predictors)
    data = df[cols].dropna()
    n = len(data)
    k = data[outcome].nunique()
    if k < 3:
        return {'error': f'Multinomial needs ≥3 outcome categories (got {k}).'}
    if n < max(30, 10 * len(predictors) * (k - 1)):
        return {'error': f'Sample too small (n={n}) for {k}-way multinomial.'}
    formula = f'Q("{outcome}") ~ ' + ' + '.join([f'Q("{p}")' for p in predictors])
    try:
        res = smf.mnlogit(formula, data=data).fit(disp=False, maxiter=200)
    except Exception as e:
        return {'error': f'Multinomial logistic failed: {e}'}
    rows = []
    params = res.params
    for col_idx in range(params.shape[1]):
        outcome_label = str(params.columns[col_idx])
        for p in predictors:
            if p in params.index:
                coef = float(params.iloc[:, col_idx][p])
                se = float(res.bse.iloc[:, col_idx][p])
                pv = float(res.pvalues.iloc[:, col_idx][p])
                rows.append({
                    'outcome_vs_ref': outcome_label,
                    'variable': p,
                    'OR': round(math.exp(coef), 3),
                    'OR_ci': (round(math.exp(coef - 1.96 * se), 3),
                              round(math.exp(coef + 1.96 * se), 3)),
                    'p': pv, 'p_display': _h().fmt_p(pv),
                })
    return {
        'test': 'Multinomial logistic regression',
        'test_type': 'multinomial_logistic',
        'n': n,
        'k_categories': int(k),
        'rows': rows,
        'aic': round(float(res.aic), 2),
        'interpretation': (
            f'Multinomial logistic: {outcome} ({k} categories) '
            f'~ {", ".join(predictors)} (n={n}).'),
    }


def run_probit(outcome: str, predictors: Sequence[str], session: Dict, df: pd.DataFrame) -> Dict:
    """Probit regression (binary outcome, probit link). Library: statsmodels."""
    import statsmodels.formula.api as smf
    cols = [outcome] + list(predictors)
    data = df[cols].dropna().copy()
    n = len(data)
    if data[outcome].nunique() != 2:
        return {'error': 'Probit needs a 2-level outcome.'}
    levels = sorted(data[outcome].dropna().unique().tolist())
    data['_y'] = (data[outcome] == levels[1]).astype(int)
    formula = '_y ~ ' + ' + '.join([f'Q("{p}")' for p in predictors])
    try:
        res = smf.probit(formula, data=data).fit(disp=False, maxiter=200)
    except Exception as e:
        return {'error': f'Probit failed: {e}'}
    rows = []
    for p in predictors:
        if p in res.params.index:
            coef = float(res.params[p])
            se = float(res.bse[p])
            pv = float(res.pvalues[p])
            rows.append({
                'variable': p,
                'coef': round(coef, 4),
                'se': round(se, 4),
                'z': round(float(res.tvalues[p]), 3),
                'p': pv, 'p_display': _h().fmt_p(pv),
                'ci': (round(coef - 1.96 * se, 4), round(coef + 1.96 * se, 4)),
            })
    return {
        'test': 'Probit regression',
        'test_type': 'probit',
        'n': n,
        'rows': rows,
        'aic': round(float(res.aic), 2),
        'interpretation': (
            f'Probit: {outcome} ~ {", ".join(predictors)} (n={n}).'),
    }


def run_quantile_regression(outcome: str, predictors: Sequence[str], session: Dict, df: pd.DataFrame, q: float = 0.5) -> Dict:
    """Quantile regression. Library: statsmodels QuantReg."""
    import statsmodels.formula.api as smf
    if not (0 < q < 1):
        return {'error': 'q must be in (0,1).'}
    data = df[[outcome] + list(predictors)].dropna()
    n = len(data)
    if n < 20:
        return {'error': f'Sample too small (n={n}).'}
    formula = f'Q("{outcome}") ~ ' + ' + '.join([f'Q("{p}")' for p in predictors])
    try:
        res = smf.quantreg(formula, data=data).fit(q=q)
    except Exception as e:
        return {'error': f'Quantile regression failed: {e}'}
    rows = []
    for p in predictors:
        if p in res.params.index:
            coef = float(res.params[p])
            se = float(res.bse[p])
            pv = float(res.pvalues[p])
            rows.append({
                'variable': p, 'coef': round(coef, 4),
                'se': round(se, 4), 'p': pv,
                'p_display': _h().fmt_p(pv),
                'ci': (round(coef - 1.96 * se, 4), round(coef + 1.96 * se, 4)),
            })
    return {
        'test': f'Quantile regression (q={q})',
        'test_type': 'quantile_regression',
        'n': n,
        'q': q,
        'rows': rows,
        'pseudo_r2': round(float(res.prsquared), 3),
        'interpretation': (
            f'Quantile regression at q = {q}: {outcome} ~ '
            f'{", ".join(predictors)} (n={n}). Pseudo R² = {res.prsquared:.3f}.'),
    }


def run_robust_regression(outcome: str, predictors: Sequence[str], session: Dict, df: pd.DataFrame) -> Dict:
    """Robust (M-estimation) regression. Library: statsmodels RLM (Huber)."""
    import statsmodels.formula.api as smf
    import statsmodels.api as sm
    data = df[[outcome] + list(predictors)].dropna()
    n = len(data)
    if n < 20:
        return {'error': f'Sample too small (n={n}).'}
    formula = f'Q("{outcome}") ~ ' + ' + '.join([f'Q("{p}")' for p in predictors])
    try:
        res = smf.rlm(formula, data=data, M=sm.robust.norms.HuberT()).fit()
    except Exception as e:
        return {'error': f'Robust regression failed: {e}'}
    rows = []
    for p in predictors:
        if p in res.params.index:
            coef = float(res.params[p])
            se = float(res.bse[p])
            pv = float(res.pvalues[p])
            rows.append({
                'variable': p, 'B': round(coef, 4),
                'robust_SE': round(se, 4), 'p': pv,
                'p_display': _h().fmt_p(pv),
                'ci': (round(coef - 1.96 * se, 4), round(coef + 1.96 * se, 4)),
            })
    return {
        'test': 'Robust regression (Huber M-estimation)',
        'test_type': 'robust_regression',
        'n': n, 'rows': rows,
        'interpretation': (
            f'Robust regression (Huber): {outcome} ~ '
            f'{", ".join(predictors)} (n={n}). Resistant to outliers.'),
    }


def run_wls(outcome: str, predictors: Sequence[str], weight_col: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Weighted least squares. Library: statsmodels WLS."""
    import statsmodels.formula.api as smf
    cols = [outcome, weight_col] + list(predictors)
    data = df[cols].dropna()
    n = len(data)
    if n < 20:
        return {'error': f'Sample too small (n={n}).'}
    formula = f'Q("{outcome}") ~ ' + ' + '.join([f'Q("{p}")' for p in predictors])
    try:
        res = smf.wls(formula, data=data, weights=data[weight_col]).fit()
    except Exception as e:
        return {'error': f'WLS failed: {e}'}
    rows = []
    for p in predictors:
        if p in res.params.index:
            coef = float(res.params[p])
            se = float(res.bse[p])
            pv = float(res.pvalues[p])
            rows.append({
                'variable': p, 'B': round(coef, 4),
                'SE': round(se, 4), 'p': pv,
                'p_display': _h().fmt_p(pv),
            })
    return {
        'test': 'Weighted least squares',
        'test_type': 'wls',
        'n': n, 'rows': rows,
        'r_squared': round(float(res.rsquared), 3),
        'interpretation': (
            f'WLS: {outcome} ~ {", ".join(predictors)} weighted by '
            f'{weight_col} (n={n}). R² = {res.rsquared:.3f}.'),
    }


def run_ridge(outcome: str, predictors: Sequence[str], session: Dict, df: pd.DataFrame, alpha: float = 1.0) -> Dict:
    """Ridge (L2) regression. Library: scikit-learn."""
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    data = df[[outcome] + list(predictors)].dropna()
    n = len(data)
    if n < 20:
        return {'error': f'Sample too small (n={n}).'}
    X = StandardScaler().fit_transform(data[list(predictors)].values)
    y = data[outcome].values
    try:
        m = Ridge(alpha=alpha).fit(X, y)
    except Exception as e:
        return {'error': f'Ridge failed: {e}'}
    r2 = float(m.score(X, y))
    rows = [{'variable': p, 'standardised_coef': round(float(c), 4)}
            for p, c in zip(predictors, m.coef_)]
    return {
        'test': f'Ridge regression (α={alpha})',
        'test_type': 'ridge',
        'n': n, 'alpha': alpha,
        'rows': rows,
        'r_squared': round(r2, 3),
        'intercept': round(float(m.intercept_), 4),
        'interpretation': (
            f'Ridge (α={alpha}): {outcome} ~ {", ".join(predictors)} (n={n}). '
            f'R² = {r2:.3f}. Coefficients are on standardised predictors.'),
    }


def run_lasso(outcome: str, predictors: Sequence[str], session: Dict, df: pd.DataFrame, alpha: float = 0.1) -> Dict:
    """LASSO (L1) regression — variable selection + shrinkage. Library: sklearn."""
    from sklearn.linear_model import Lasso
    from sklearn.preprocessing import StandardScaler
    data = df[[outcome] + list(predictors)].dropna()
    n = len(data)
    if n < 20:
        return {'error': f'Sample too small (n={n}).'}
    X = StandardScaler().fit_transform(data[list(predictors)].values)
    y = data[outcome].values
    try:
        m = Lasso(alpha=alpha, max_iter=5000).fit(X, y)
    except Exception as e:
        return {'error': f'LASSO failed: {e}'}
    r2 = float(m.score(X, y))
    rows = [{'variable': p, 'standardised_coef': round(float(c), 4),
             'selected': bool(c != 0)}
            for p, c in zip(predictors, m.coef_)]
    n_selected = int(sum(1 for r in rows if r['selected']))
    return {
        'test': f'LASSO (α={alpha})',
        'test_type': 'lasso',
        'n': n, 'alpha': alpha,
        'rows': rows, 'r_squared': round(r2, 3),
        'n_selected': n_selected,
        'interpretation': (
            f'LASSO (α={alpha}): {n_selected}/{len(predictors)} predictors '
            f'kept non-zero (n={n}). R² = {r2:.3f}.'),
    }


def run_elastic_net(outcome: str, predictors: Sequence[str], session: Dict, df: pd.DataFrame, alpha: float = 0.1, l1_ratio: float = 0.5) -> Dict:
    """Elastic net — combined L1 + L2. Library: sklearn."""
    from sklearn.linear_model import ElasticNet
    from sklearn.preprocessing import StandardScaler
    data = df[[outcome] + list(predictors)].dropna()
    n = len(data)
    if n < 20:
        return {'error': f'Sample too small (n={n}).'}
    X = StandardScaler().fit_transform(data[list(predictors)].values)
    y = data[outcome].values
    try:
        m = ElasticNet(alpha=alpha, l1_ratio=l1_ratio, max_iter=5000).fit(X, y)
    except Exception as e:
        return {'error': f'Elastic net failed: {e}'}
    r2 = float(m.score(X, y))
    rows = [{'variable': p, 'standardised_coef': round(float(c), 4),
             'selected': bool(c != 0)}
            for p, c in zip(predictors, m.coef_)]
    return {
        'test': f'Elastic net (α={alpha}, L1 ratio={l1_ratio})',
        'test_type': 'elastic_net',
        'n': n, 'alpha': alpha, 'l1_ratio': l1_ratio,
        'rows': rows, 'r_squared': round(r2, 3),
        'interpretation': (
            f'Elastic net (α={alpha}, L1 ratio={l1_ratio}, n={n}). '
            f'R² = {r2:.3f}.'),
    }


def run_iv2sls(outcome: str, endog: str, instruments: Sequence[str], exog: Sequence[str], session: Dict, df: pd.DataFrame) -> Dict:
    """Two-stage least squares — instrumental variable regression.
    Library: linearmodels.IV2SLS."""
    from linearmodels.iv import IV2SLS
    cols = [outcome, endog] + list(instruments) + list(exog)
    data = df[cols].dropna()
    n = len(data)
    if n < 30:
        return {'error': f'Sample too small (n={n}).'}
    try:
        exog_df = pd.DataFrame({'const': 1.0}, index=data.index)
        for c in exog:
            exog_df[c] = data[c]
        res = IV2SLS(dependent=data[outcome],
                     exog=exog_df,
                     endog=data[[endog]],
                     instruments=data[list(instruments)]).fit()
    except Exception as e:
        return {'error': f'IV2SLS failed: {e}'}
    rows = []
    for v in [endog] + list(exog):
        if v in res.params.index:
            rows.append({
                'variable': v,
                'coef': round(float(res.params[v]), 4),
                'robust_SE': round(float(res.std_errors[v]), 4),
                'p': float(res.pvalues[v]),
                'p_display': _h().fmt_p(float(res.pvalues[v])),
            })
    return {
        'test': '2-Stage Least Squares (IV)',
        'test_type': 'iv2sls',
        'n': n, 'rows': rows,
        'r_squared': round(float(res.rsquared), 3),
        'interpretation': (
            f'2SLS: {outcome} with endogenous {endog} instrumented by '
            f'{", ".join(instruments)} (n={n}). R² = {res.rsquared:.3f}.'),
    }


def run_nonlinear(outcome: str, predictor: str, model: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Non-linear regression. Library: scipy.optimize.curve_fit.
    Supported `model` values: 'exponential' (a*exp(b*x)),
    'power' (a*x**b), 'logistic' (L/(1+exp(-k*(x-x0))))."""
    from scipy.optimize import curve_fit
    data = df[[outcome, predictor]].apply(pd.to_numeric, errors='coerce').dropna()
    n = len(data)
    if n < 8:
        return {'error': f'Sample too small (n={n}).'}
    x = data[predictor].values
    y = data[outcome].values
    funcs = {
        'exponential': (lambda x, a, b: a * np.exp(b * x), [1.0, 0.01]),
        'power': (lambda x, a, b: a * np.power(np.maximum(x, 1e-9), b), [1.0, 1.0]),
        'logistic': (lambda x, L, k, x0: L / (1 + np.exp(-k * (x - x0))),
                     [float(np.max(y)), 1.0, float(np.median(x))]),
    }
    if model not in funcs:
        return {'error': f'Unknown nonlinear model {model}.'}
    fn, p0 = funcs[model]
    try:
        popt, pcov = curve_fit(fn, x, y, p0=p0, maxfev=5000)
        y_hat = fn(x, *popt)
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else None
    except Exception as e:
        return {'error': f'Non-linear fit failed: {e}'}
    return {
        'test': f'Non-linear regression — {model}',
        'test_type': 'nonlinear_regression',
        'n': n, 'model': model,
        'parameters': [round(float(p), 4) for p in popt],
        'r_squared': round(r2, 3) if r2 is not None else None,
        'interpretation': (
            f'Non-linear ({model}) fit of {outcome} ~ {predictor} (n={n}). '
            f'R² = {r2:.3f}.' if r2 is not None else
            f'Non-linear ({model}) fit of {outcome} ~ {predictor} (n={n}).'),
    }


def run_mediation(x: str, m: str, y: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Mediation analysis (Baron-Kenny / bootstrap indirect effect).
    Library: statsmodels.stats.mediation.Mediation."""
    import statsmodels.formula.api as smf
    from statsmodels.stats.mediation import Mediation
    data = df[[x, m, y]].dropna()
    n = len(data)
    if n < 30:
        return {'error': f'Sample too small (n={n}).'}
    try:
        outcome_model = smf.ols(f'Q("{y}") ~ Q("{x}") + Q("{m}")', data=data).fit()
        mediator_model = smf.ols(f'Q("{m}") ~ Q("{x}")', data=data).fit()
        med = Mediation(outcome_model, mediator_model,
                        exposure=f'Q("{x}")', mediator=f'Q("{m}")').fit(n_rep=500)
        s = med.summary()
    except Exception as e:
        return {'error': f'Mediation failed: {e}'}
    indirect = float(s.loc['ACME (average)', 'Estimate'])
    direct = float(s.loc['ADE (average)', 'Estimate'])
    total = float(s.loc['Total effect', 'Estimate'])
    p_indirect = float(s.loc['ACME (average)', 'P-value'])
    return {
        'test': 'Mediation analysis',
        'test_type': 'mediation',
        'n': n,
        'indirect_effect': round(indirect, 4),
        'direct_effect': round(direct, 4),
        'total_effect': round(total, 4),
        'p_indirect': p_indirect,
        'p_display': _h().fmt_p(p_indirect),
        'interpretation': (
            f'Mediation {x} → {m} → {y} (n={n}, 500 bootstrap reps): '
            f'indirect = {indirect:.4f} (p = {_h().fmt_p(p_indirect)}), '
            f'direct = {direct:.4f}, total = {total:.4f}.'),
    }


def run_moderation(y: str, x: str, w: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Moderation analysis — interaction term in OLS. Library: statsmodels."""
    import statsmodels.formula.api as smf
    data = df[[y, x, w]].dropna()
    n = len(data)
    if n < 30:
        return {'error': f'Sample too small (n={n}).'}
    formula = f'Q("{y}") ~ Q("{x}") * Q("{w}")'
    try:
        res = smf.ols(formula, data=data).fit()
    except Exception as e:
        return {'error': f'Moderation failed: {e}'}
    interaction_term = next((k for k in res.params.index if ':' in k), None)
    if not interaction_term:
        return {'error': 'No interaction term found.'}
    coef = float(res.params[interaction_term])
    p = float(res.pvalues[interaction_term])
    return {
        'test': 'Moderation (interaction)',
        'test_type': 'moderation',
        'n': n,
        'interaction_coef': round(coef, 4),
        'p': p, 'p_display': _h().fmt_p(p),
        'r_squared': round(float(res.rsquared), 3),
        'interpretation': (
            f'Moderation: {y} ~ {x} × {w} (n={n}). '
            f'Interaction B = {coef:.4f}, p = {_h().fmt_p(p)}. '
            f'R² = {res.rsquared:.3f}.'),
    }


# ===========================================================================
# §9.7 Loglinear models (statsmodels Poisson with formula interactions)
# ===========================================================================

def run_loglinear(count_col: str, factors: Sequence[str], session: Dict, df: pd.DataFrame, hierarchical: bool = False) -> Dict:
    """Loglinear model for multi-way contingency tables.
    Library: statsmodels Poisson GLM on aggregated counts."""
    import statsmodels.formula.api as smf
    factors = list(factors)
    cols = [count_col] + factors
    data = df[cols].dropna()
    n = len(data)
    if n < 10:
        return {'error': f'Sample too small (n={n}).'}
    rhs = ' * '.join([f'C(Q("{f}"))' for f in factors]) if not hierarchical else \
          ' + '.join([f'C(Q("{f}"))' for f in factors])
    formula = f'Q("{count_col}") ~ {rhs}'
    try:
        import statsmodels.api as sm
        res = smf.glm(formula, data=data, family=sm.families.Poisson()).fit()
    except Exception as e:
        return {'error': f'Loglinear model failed: {e}'}
    return {
        'test': ('Hierarchical loglinear' if hierarchical else 'General loglinear'),
        'test_type': 'loglinear',
        'n': n,
        'aic': round(float(res.aic), 2),
        'deviance': round(float(res.deviance), 2),
        'df_resid': int(res.df_resid),
        'interpretation': (
            f'{("Hierarchical" if hierarchical else "General")} loglinear model '
            f'on {count_col} with factors {", ".join(factors)} (n={n}). '
            f'AIC = {res.aic:.2f}, deviance = {res.deviance:.2f}.'),
    }


# ===========================================================================
# §9.8/§9.9 Classification
# ===========================================================================

def _classify_cv(model_cls, X, y, **kwargs):
    from sklearn.model_selection import cross_val_score
    return cross_val_score(model_cls(**kwargs), X, y, cv=5,
                           scoring='accuracy').mean()


def run_lda(outcome: str, predictors: Sequence[str], session: Dict, df: pd.DataFrame) -> Dict:
    """Linear discriminant analysis. Library: sklearn."""
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
    data = df[[outcome] + list(predictors)].dropna()
    n = len(data)
    if n < 30:
        return {'error': f'Sample too small (n={n}).'}
    X = data[list(predictors)].values
    y = data[outcome].astype(str).values
    m = LinearDiscriminantAnalysis().fit(X, y)
    train_acc = float(m.score(X, y))
    cv_acc = float(_classify_cv(LinearDiscriminantAnalysis, X, y))
    return {
        'test': 'Linear Discriminant Analysis',
        'test_type': 'lda',
        'n': n, 'k_classes': int(len(m.classes_)),
        'train_accuracy': round(train_acc, 3),
        'cv5_accuracy': round(cv_acc, 3),
        'interpretation': (
            f'LDA on {outcome} ~ {len(predictors)} predictors (n={n}). '
            f'Training accuracy = {train_acc:.3f}, 5-fold CV = {cv_acc:.3f}.'),
    }


def run_qda(outcome: str, predictors: Sequence[str], session: Dict, df: pd.DataFrame) -> Dict:
    from sklearn.discriminant_analysis import QuadraticDiscriminantAnalysis
    data = df[[outcome] + list(predictors)].dropna()
    n = len(data)
    if n < 30:
        return {'error': f'Sample too small (n={n}).'}
    X = data[list(predictors)].values
    y = data[outcome].astype(str).values
    m = QuadraticDiscriminantAnalysis().fit(X, y)
    train_acc = float(m.score(X, y))
    cv_acc = float(_classify_cv(QuadraticDiscriminantAnalysis, X, y))
    return {
        'test': 'Quadratic Discriminant Analysis',
        'test_type': 'qda',
        'n': n, 'k_classes': int(len(m.classes_)),
        'train_accuracy': round(train_acc, 3),
        'cv5_accuracy': round(cv_acc, 3),
        'interpretation': (
            f'QDA on {outcome} ~ {len(predictors)} predictors (n={n}). '
            f'Training accuracy = {train_acc:.3f}, 5-fold CV = {cv_acc:.3f}.'),
    }


def run_kmeans(features: Sequence[str], session: Dict, df: pd.DataFrame, k: int = 3) -> Dict:
    """K-means clustering. Library: sklearn."""
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import silhouette_score
    data = df[list(features)].apply(pd.to_numeric, errors='coerce').dropna()
    n = len(data)
    if n < max(20, 5 * k):
        return {'error': f'Sample too small (n={n}) for k={k}.'}
    X = StandardScaler().fit_transform(data.values)
    m = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)
    sil = float(silhouette_score(X, m.labels_)) if k >= 2 else None
    return {
        'test': f'K-means clustering (k={k})',
        'test_type': 'kmeans',
        'n': n, 'k': k,
        'inertia': round(float(m.inertia_), 3),
        'silhouette': round(sil, 3) if sil is not None else None,
        'cluster_sizes': pd.Series(m.labels_).value_counts().sort_index().to_dict(),
        'interpretation': (
            f'K-means (k={k}) on {len(features)} standardised features '
            f'(n={n}). Silhouette = {sil:.3f}, inertia = {m.inertia_:.1f}.'),
    }


def run_hierarchical_cluster(features: Sequence[str], session: Dict, df: pd.DataFrame, k: int = 3, method: str = 'ward') -> Dict:
    """Agglomerative hierarchical clustering. Library: scipy.cluster.hierarchy."""
    from scipy.cluster.hierarchy import linkage, fcluster
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import silhouette_score
    data = df[list(features)].apply(pd.to_numeric, errors='coerce').dropna()
    n = len(data)
    if n < max(10, 3 * k):
        return {'error': f'Sample too small (n={n}).'}
    X = StandardScaler().fit_transform(data.values)
    Z = linkage(X, method=method)
    labels = fcluster(Z, t=k, criterion='maxclust')
    sil = float(silhouette_score(X, labels)) if k >= 2 else None
    return {
        'test': f'Hierarchical clustering (k={k}, {method})',
        'test_type': 'hierarchical_cluster',
        'n': n, 'k': k, 'method': method,
        'silhouette': round(sil, 3) if sil is not None else None,
        'cluster_sizes': pd.Series(labels).value_counts().sort_index().to_dict(),
        'interpretation': (
            f'Hierarchical clustering (k={k}, {method} linkage) on '
            f'{len(features)} features (n={n}). Silhouette = {sil:.3f}.'),
    }


def run_knn(outcome: str, predictors: Sequence[str], session: Dict, df: pd.DataFrame, k: int = 5) -> Dict:
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.preprocessing import StandardScaler
    data = df[[outcome] + list(predictors)].dropna()
    n = len(data)
    if n < max(30, 5 * k):
        return {'error': f'Sample too small (n={n}).'}
    X = StandardScaler().fit_transform(data[list(predictors)].values)
    y = data[outcome].astype(str).values
    m = KNeighborsClassifier(n_neighbors=k).fit(X, y)
    train_acc = float(m.score(X, y))
    cv_acc = float(_classify_cv(KNeighborsClassifier, X, y, n_neighbors=k))
    return {
        'test': f'K-Nearest Neighbours (k={k})',
        'test_type': 'knn',
        'n': n, 'k': k,
        'train_accuracy': round(train_acc, 3),
        'cv5_accuracy': round(cv_acc, 3),
        'interpretation': (
            f'KNN (k={k}) on {outcome} ~ {len(predictors)} predictors '
            f'(n={n}). Training acc = {train_acc:.3f}, CV = {cv_acc:.3f}.'),
    }


def run_mlp(outcome: str, predictors: Sequence[str], session: Dict, df: pd.DataFrame) -> Dict:
    """Multilayer perceptron. Library: sklearn."""
    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler
    data = df[[outcome] + list(predictors)].dropna()
    n = len(data)
    if n < 100:
        return {'warning': f'MLP recommended n≥500; got n={n}. Results may be unstable.',
                'partial_result': True, 'test_type': 'mlp', 'n': n}
    X = StandardScaler().fit_transform(data[list(predictors)].values)
    y = data[outcome].astype(str).values
    m = MLPClassifier(hidden_layer_sizes=(32, 16), max_iter=500,
                      random_state=42).fit(X, y)
    train_acc = float(m.score(X, y))
    return {
        'test': 'Multilayer Perceptron',
        'test_type': 'mlp',
        'n': n,
        'train_accuracy': round(train_acc, 3),
        'hidden_layer_sizes': (32, 16),
        'interpretation': (
            f'MLP on {outcome} ~ {len(predictors)} predictors (n={n}). '
            f'Training accuracy = {train_acc:.3f}. '
            f'Note: MLP results are sensitive to architecture/seed.'),
    }


# ===========================================================================
# §9.10 Dimension reduction
# ===========================================================================

def run_pca(features: Sequence[str], session: Dict, df: pd.DataFrame, n_components: Optional[int] = None) -> Dict:
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler
    data = df[list(features)].apply(pd.to_numeric, errors='coerce').dropna()
    n = len(data)
    if n < 20:
        return {'error': f'Sample too small (n={n}).'}
    n_components = n_components or min(len(features), n - 1)
    X = StandardScaler().fit_transform(data.values)
    m = PCA(n_components=n_components).fit(X)
    rows = []
    for i, (ev, evr) in enumerate(zip(m.explained_variance_, m.explained_variance_ratio_)):
        rows.append({
            'component': f'PC{i+1}',
            'eigenvalue': round(float(ev), 3),
            'variance_pct': round(float(evr) * 100, 2),
            'cumulative_pct': round(float(m.explained_variance_ratio_[:i+1].sum()) * 100, 2),
        })
    return {
        'test': f'PCA ({n_components} components)',
        'test_type': 'pca',
        'n': n, 'k': n_components,
        'rows': rows,
        'loadings': m.components_.round(3).tolist(),
        'features': list(features),
        'interpretation': (
            f'PCA on {len(features)} features (n={n}). '
            f'First {n_components} components explain '
            f'{m.explained_variance_ratio_.sum()*100:.1f}% of variance.'),
    }


def run_efa(features: Sequence[str], session: Dict, df: pd.DataFrame, n_factors: int = 2, rotation: str = 'varimax') -> Dict:
    """Exploratory factor analysis with rotation. Library: factor_analyzer."""
    from factor_analyzer import FactorAnalyzer
    data = df[list(features)].apply(pd.to_numeric, errors='coerce').dropna()
    n = len(data)
    if n < max(50, 5 * n_factors * len(features)):
        return {'warning': f'EFA recommends n ≥ 5·k·p (got n={n}). Interpret with caution.',
                'partial_result': True, 'test_type': 'efa', 'n': n}
    try:
        fa = FactorAnalyzer(n_factors=n_factors, rotation=rotation)
        fa.fit(data.values)
    except Exception as e:
        return {'error': f'EFA failed: {e}'}
    ev, _ = fa.get_eigenvalues()
    var = fa.get_factor_variance()
    return {
        'test': f'Exploratory factor analysis ({n_factors} factors, {rotation})',
        'test_type': 'efa',
        'n': n, 'n_factors': n_factors, 'rotation': rotation,
        'loadings': fa.loadings_.round(3).tolist(),
        'communalities': fa.get_communalities().round(3).tolist(),
        'eigenvalues': [round(float(e), 3) for e in ev],
        'variance_explained': [round(float(v), 3) for v in var[1]],
        'features': list(features),
        'interpretation': (
            f'EFA: {n_factors} factors with {rotation} rotation, '
            f'{len(features)} variables (n={n}).'),
    }


def run_parallel_analysis(features: Sequence[str], session: Dict, df: pd.DataFrame, n_iter: int = 100) -> Dict:
    """Horn's parallel analysis to suggest number of factors. Library: factor_analyzer."""
    from factor_analyzer import FactorAnalyzer
    data = df[list(features)].apply(pd.to_numeric, errors='coerce').dropna()
    n = len(data)
    p = len(features)
    if n < 30 or p < 3:
        return {'error': f'Need n≥30 and ≥3 variables (n={n}, p={p}).'}
    fa = FactorAnalyzer(rotation=None, n_factors=p)
    fa.fit(data.values)
    real_ev, _ = fa.get_eigenvalues()
    rng = np.random.default_rng(42)
    sim_evs = []
    for _ in range(n_iter):
        sim = rng.normal(size=(n, p))
        fa_s = FactorAnalyzer(rotation=None, n_factors=p)
        fa_s.fit(sim)
        ev_s, _ = fa_s.get_eigenvalues()
        sim_evs.append(ev_s)
    sim_95 = np.percentile(np.vstack(sim_evs), 95, axis=0)
    suggested = int(np.sum(real_ev > sim_95))
    return {
        'test': "Horn's parallel analysis",
        'test_type': 'parallel_analysis',
        'n': n, 'p': p, 'n_iter': n_iter,
        'real_eigenvalues': [round(float(e), 3) for e in real_ev],
        'simulated_95th': [round(float(e), 3) for e in sim_95],
        'suggested_n_factors': suggested,
        'interpretation': (
            f'Horn parallel analysis suggests {suggested} factors '
            f'(p={p} variables, n={n}, {n_iter} simulations).'),
    }


def run_mds(features: Sequence[str], session: Dict, df: pd.DataFrame, n_components: int = 2) -> Dict:
    from sklearn.manifold import MDS
    from sklearn.preprocessing import StandardScaler
    data = df[list(features)].apply(pd.to_numeric, errors='coerce').dropna()
    n = len(data)
    if n < 10 or n > 1000:
        return {'error': f'MDS works best for 10 ≤ n ≤ 1000 (got n={n}).'}
    X = StandardScaler().fit_transform(data.values)
    m = MDS(n_components=n_components, random_state=42,
            normalized_stress='auto').fit(X)
    return {
        'test': f'Multidimensional scaling ({n_components}D)',
        'test_type': 'mds',
        'n': n, 'k': n_components,
        'stress': round(float(m.stress_), 3),
        'interpretation': (
            f'MDS to {n_components} dimensions on {len(features)} features '
            f'(n={n}). Stress = {m.stress_:.3f}.'),
    }


# ===========================================================================
# §9.11 Reliability — extras
# ===========================================================================

def run_cronbach_alpha(items: Sequence[str], session: Dict, df: pd.DataFrame) -> Dict:
    """Cronbach's alpha for internal consistency. Library: pingouin."""
    import pingouin as pg
    data = df[list(items)].apply(pd.to_numeric, errors='coerce').dropna()
    n = len(data)
    if n < 10 or len(items) < 2:
        return {'error': f'Need n≥10 and ≥2 items (n={n}, k={len(items)}).'}
    try:
        alpha, ci = pg.cronbach_alpha(data=data)
    except Exception as e:
        return {'error': f'Cronbach alpha failed: {e}'}
    interp = ('unacceptable' if alpha < 0.5 else
              'poor' if alpha < 0.6 else
              'questionable' if alpha < 0.7 else
              'acceptable' if alpha < 0.8 else
              'good' if alpha < 0.9 else 'excellent')
    return {
        'test': "Cronbach's alpha",
        'test_type': 'cronbach_alpha',
        'n': n, 'k_items': len(items),
        'alpha': round(float(alpha), 3),
        'ci': (round(float(ci[0]), 3), round(float(ci[1]), 3)),
        'interpretation_tier': interp,
        'interpretation': (
            f"Cronbach's α = {alpha:.3f} (95% CI {ci[0]:.3f}–{ci[1]:.3f}) "
            f'over {len(items)} items, n = {n} ({interp}).'),
    }


def run_split_half(items: Sequence[str], session: Dict, df: pd.DataFrame) -> Dict:
    """Split-half reliability with Spearman-Brown correction.
    Library: scipy.stats.pearsonr."""
    items = list(items)
    if len(items) < 4:
        return {'error': 'Need ≥4 items for split-half.'}
    data = df[items].apply(pd.to_numeric, errors='coerce').dropna()
    n = len(data)
    if n < 10:
        return {'error': f'Sample too small (n={n}).'}
    half_a = data[items[::2]].sum(axis=1)
    half_b = data[items[1::2]].sum(axis=1)
    r, p = _ss.pearsonr(half_a, half_b)
    sb = (2 * r) / (1 + r) if (1 + r) != 0 else None
    return {
        'test': 'Split-half reliability (Spearman-Brown)',
        'test_type': 'split_half',
        'n': n,
        'half_correlation': round(float(r), 3),
        'spearman_brown': round(float(sb), 3) if sb is not None else None,
        'p': float(p), 'p_display': _h().fmt_p(float(p)),
        'interpretation': (
            f'Split-half: r = {r:.3f}, Spearman-Brown corrected = '
            f'{sb:.3f} (n={n}, k={len(items)}).'),
    }


def run_sem_mdc(col1: str, col2: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Standard Error of Measurement and Minimum Detectable Change.
    SEM = SD × sqrt(1 - ICC). MDC = 1.96 × SEM × sqrt(2). Library: pingouin."""
    import pingouin as pg
    data = df[[col1, col2]].apply(pd.to_numeric, errors='coerce').dropna()
    n = len(data)
    if n < 10:
        return {'error': f'Sample too small (n={n}).'}
    long_df = pd.melt(data.reset_index(), id_vars='index',
                      value_vars=[col1, col2],
                      var_name='session', value_name='score')
    icc = pg.intraclass_corr(data=long_df, targets='index',
                             raters='session', ratings='score')
    icc_row = icc[icc['Type'] == 'ICC(C,1)']
    if icc_row.empty:
        icc_row = icc[icc['Type'] == 'ICC(A,1)']
    if icc_row.empty:
        return {'error': 'Could not compute ICC for SEM/MDC.'}
    icc_val = float(icc_row['ICC'].values[0])
    sd = float(pd.concat([data[col1], data[col2]]).std(ddof=1))
    sem = sd * math.sqrt(max(0.0, 1 - icc_val))
    mdc = 1.96 * sem * math.sqrt(2)
    return {
        'test': 'SEM and MDC (test-retest)',
        'test_type': 'sem_mdc',
        'n': n,
        'icc': round(icc_val, 3),
        'sd': round(sd, 3),
        'sem': round(sem, 3),
        'mdc_95': round(mdc, 3),
        'interpretation': (
            f'Test-retest reliability for {col1} ↔ {col2}, n = {n}. '
            f'ICC = {icc_val:.3f}, SEM = {sem:.3f}, MDC₉₅ = {mdc:.3f}.'),
    }


# ===========================================================================
# §9.12 Nonparametric — extras
# ===========================================================================

def run_cochran_q(cols: Sequence[str], session: Dict, df: pd.DataFrame) -> Dict:
    """Cochran's Q for ≥3 matched binary outcomes. Library: statsmodels."""
    from statsmodels.stats.contingency_tables import cochrans_q
    cols = list(cols)
    data = df[cols].dropna()
    if len(cols) < 3:
        return {'error': "Cochran's Q needs ≥3 conditions."}
    n = len(data)
    if n < 10:
        return {'error': f'Sample too small (n={n}).'}
    arr = data.values.astype(int)
    if not set(np.unique(arr)).issubset({0, 1}):
        return {'error': 'All columns must be 0/1 binary.'}
    try:
        res = cochrans_q(arr)
    except Exception as e:
        return {'error': f"Cochran's Q failed: {e}"}
    return {
        'test': "Cochran's Q",
        'test_type': 'cochrans_q',
        'n': n, 'k': len(cols),
        'Q': round(float(res.statistic), 3),
        'df': len(cols) - 1,
        'p': float(res.pvalue),
        'p_display': _h().fmt_p(float(res.pvalue)),
        'interpretation': (
            f"Cochran's Q across {len(cols)} matched binary conditions "
            f'(n={n}): Q = {res.statistic:.3f}, df = {len(cols)-1}, '
            f'p = {_h().fmt_p(float(res.pvalue))}.'),
    }


def run_sign_test(col1: str, col2: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Sign test for paired comparison. Library: scipy.stats.binomtest."""
    data = df[[col1, col2]].apply(pd.to_numeric, errors='coerce').dropna()
    n = len(data)
    if n < 5:
        return {'error': f'Sample too small (n={n}).'}
    diff = data[col1] - data[col2]
    pos = int((diff > 0).sum())
    neg = int((diff < 0).sum())
    ties = int((diff == 0).sum())
    n_eff = pos + neg
    if n_eff == 0:
        return {'error': 'All paired differences are zero.'}
    res = _ss.binomtest(min(pos, neg), n_eff, 0.5, alternative='two-sided')
    return {
        'test': 'Sign test',
        'test_type': 'sign_test',
        'n': n, 'positive': pos, 'negative': neg, 'ties': ties,
        'p': float(res.pvalue),
        'p_display': _h().fmt_p(float(res.pvalue)),
        'interpretation': (
            f'Sign test ({col1} vs {col2}, n={n}, +{pos}/-{neg}, ties={ties}): '
            f'p = {_h().fmt_p(float(res.pvalue))}.'),
    }


def run_runs_test(col: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Wald-Wolfowitz runs test for randomness. Library: statsmodels."""
    from statsmodels.sandbox.stats.runs import runstest_1samp
    s = pd.to_numeric(df[col], errors='coerce').dropna()
    n = len(s)
    if n < 10:
        return {'error': f'Sample too small (n={n}).'}
    try:
        z, p = runstest_1samp(s.values, cutoff='median')
    except Exception as e:
        return {'error': f'Runs test failed: {e}'}
    return {
        'test': 'Runs test (randomness)',
        'test_type': 'runs_test',
        'n': n,
        'z': round(float(z), 3),
        'p': float(p),
        'p_display': _h().fmt_p(float(p)),
        'interpretation': (
            f'Runs test on {col} (n={n}): z = {z:.3f}, '
            f'p = {_h().fmt_p(float(p))}. Low p ⇒ data not random around median.'),
    }


def run_ks_2sample(col: str, group: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Kolmogorov-Smirnov two-sample test. Library: scipy."""
    data = df[[col, group]].dropna()
    levels = data[group].unique()
    if len(levels) != 2:
        return {'error': f'Need exactly 2 groups (got {len(levels)}).'}
    a = pd.to_numeric(data[data[group] == levels[0]][col], errors='coerce').dropna()
    b = pd.to_numeric(data[data[group] == levels[1]][col], errors='coerce').dropna()
    if len(a) < 5 or len(b) < 5:
        return {'error': f'Each group needs ≥5 obs (got {len(a)}/{len(b)}).'}
    d, p = _ss.ks_2samp(a, b)
    return {
        'test': 'Kolmogorov-Smirnov 2-sample test',
        'test_type': 'ks_2sample',
        'n': int(len(a) + len(b)),
        'D': round(float(d), 3),
        'p': float(p),
        'p_display': _h().fmt_p(float(p)),
        'interpretation': (
            f'KS 2-sample on {col} by {group} '
            f'(n={len(a)} vs {len(b)}): D = {d:.3f}, '
            f'p = {_h().fmt_p(float(p))}.'),
    }


def run_mood_median(col: str, group: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Mood's median test. Library: scipy."""
    data = df[[col, group]].dropna()
    groups = [pd.to_numeric(data[data[group] == lvl][col], errors='coerce').dropna().values
              for lvl in data[group].unique()]
    groups = [g for g in groups if len(g) >= 5]
    if len(groups) < 2:
        return {'error': 'Need ≥2 groups with ≥5 obs each.'}
    try:
        chi2, p, _, _ = _ss.median_test(*groups)
    except Exception as e:
        return {'error': f"Mood's median failed: {e}"}
    return {
        'test': "Mood's median test",
        'test_type': 'mood_median',
        'n': int(sum(len(g) for g in groups)),
        'k_groups': len(groups),
        'chi2': round(float(chi2), 3),
        'p': float(p),
        'p_display': _h().fmt_p(float(p)),
        'interpretation': (
            f"Mood's median test on {col} by {group} ({len(groups)} groups): "
            f'χ² = {chi2:.3f}, p = {_h().fmt_p(float(p))}.'),
    }


def run_binomial_test(successes: int, n: int, session: Dict, df: pd.DataFrame, p0: float = 0.5) -> Dict:
    """Binomial test for proportion against reference. Library: scipy."""
    if n < 1 or successes < 0 or successes > n:
        return {'error': 'Invalid counts.'}
    res = _ss.binomtest(int(successes), int(n), p0, alternative='two-sided')
    ci = res.proportion_ci(confidence_level=0.95)
    return {
        'test': 'Binomial test',
        'test_type': 'binomial_test',
        'n': int(n), 'successes': int(successes),
        'proportion': round(successes / n, 4),
        'p_null': p0,
        'ci': (round(ci.low, 4), round(ci.high, 4)),
        'p': float(res.pvalue),
        'p_display': _h().fmt_p(float(res.pvalue)),
        'interpretation': (
            f'Binomial test: {successes}/{n} = {successes/n:.3f} vs {p0}. '
            f'p = {_h().fmt_p(float(res.pvalue))}.'),
    }


def run_chi_goodness_of_fit(col: str, session: Dict, df: pd.DataFrame, expected: Optional[Sequence[float]] = None) -> Dict:
    """Chi-square goodness of fit test. Library: scipy."""
    counts = df[col].dropna().astype(str).value_counts().sort_index()
    if len(counts) < 2:
        return {'error': 'Need ≥2 categories.'}
    obs = counts.values
    exp = np.array(expected) if expected else np.full_like(obs, obs.sum() / len(obs), dtype=float)
    try:
        chi2, p = _ss.chisquare(obs, f_exp=exp)
    except Exception as e:
        return {'error': f'Chi-square GOF failed: {e}'}
    return {
        'test': 'Chi-square goodness of fit',
        'test_type': 'chi_goodness_of_fit',
        'n': int(obs.sum()),
        'k_categories': len(counts),
        'chi2': round(float(chi2), 3),
        'df': len(counts) - 1,
        'p': float(p),
        'p_display': _h().fmt_p(float(p)),
        'observed': counts.to_dict(),
        'expected': dict(zip(counts.index, exp.round(2).tolist())),
        'interpretation': (
            f'Chi-square GOF on {col} ({len(counts)} categories, n={obs.sum()}): '
            f'χ²({len(counts)-1}) = {chi2:.3f}, p = {_h().fmt_p(float(p))}.'),
    }


def run_mcnemar_bowker(col1: str, col2: str, session: Dict, df: pd.DataFrame) -> Dict:
    """McNemar-Bowker test of symmetry for square contingency tables.
    Library: statsmodels.stats.contingency_tables.SquareTable."""
    from statsmodels.stats.contingency_tables import SquareTable
    data = df[[col1, col2]].dropna()
    n = len(data)
    if n < 10:
        return {'error': f'Sample too small (n={n}).'}
    table = pd.crosstab(data[col1], data[col2])
    if table.shape[0] != table.shape[1]:
        return {'error': 'Bowker requires a square table.'}
    try:
        st = SquareTable(table)
        res = st.symmetry()
    except Exception as e:
        return {'error': f'Bowker test failed: {e}'}
    return {
        'test': 'McNemar-Bowker test of symmetry',
        'test_type': 'mcnemar_bowker',
        'n': n, 'k': table.shape[0],
        'chi2': round(float(res.statistic), 3),
        'df': int(res.df),
        'p': float(res.pvalue),
        'p_display': _h().fmt_p(float(res.pvalue)),
        'interpretation': (
            f'McNemar-Bowker (k={table.shape[0]}, n={n}): '
            f'χ²({res.df}) = {res.statistic:.3f}, '
            f'p = {_h().fmt_p(float(res.pvalue))}.'),
    }


def run_dunns_post_hoc(outcome: str, group: str, session: Dict, df: pd.DataFrame, p_adjust: str = 'bonferroni') -> Dict:
    """Dunn's post-hoc after Kruskal-Wallis. Library: scikit-posthocs."""
    import scikit_posthocs as sp
    data = df[[outcome, group]].dropna()
    n = len(data)
    if data[group].nunique() < 3:
        return {'error': "Dunn's post-hoc requires ≥3 groups."}
    try:
        pmat = sp.posthoc_dunn(data, val_col=outcome, group_col=group,
                               p_adjust=p_adjust)
    except Exception as e:
        return {'error': f"Dunn's failed: {e}"}
    rows = []
    levels = pmat.index.tolist()
    for i, a in enumerate(levels):
        for b in levels[i+1:]:
            p = float(pmat.loc[a, b])
            rows.append({
                'pair': f'{a} vs {b}',
                'p_adj': p,
                'p_display': _h().fmt_p(p),
                'significant': p < 0.05,
            })
    return {
        'test': f"Dunn's post-hoc ({p_adjust})",
        'test_type': 'dunns_post_hoc',
        'n': n, 'k_groups': data[group].nunique(),
        'rows': rows,
        'adjustment': p_adjust,
        'interpretation': (
            f"Dunn's post-hoc on {outcome} by {group} "
            f'(n={n}, {p_adjust} adjustment).'),
    }


def run_nemenyi(outcome: str, group: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Nemenyi post-hoc (Friedman). Library: scikit-posthocs."""
    import scikit_posthocs as sp
    data = df[[outcome, group]].dropna()
    n = len(data)
    if data[group].nunique() < 3:
        return {'error': 'Need ≥3 groups.'}
    try:
        pmat = sp.posthoc_nemenyi(data, val_col=outcome, group_col=group)
    except Exception as e:
        return {'error': f'Nemenyi failed: {e}'}
    rows = []
    levels = pmat.index.tolist()
    for i, a in enumerate(levels):
        for b in levels[i+1:]:
            p = float(pmat.loc[a, b])
            rows.append({'pair': f'{a} vs {b}', 'p_adj': p,
                         'p_display': _h().fmt_p(p), 'significant': p < 0.05})
    return {
        'test': 'Nemenyi post-hoc',
        'test_type': 'nemenyi',
        'n': n, 'rows': rows,
        'interpretation': f'Nemenyi post-hoc on {outcome} by {group} (n={n}).',
    }


# ===========================================================================
# §9.13 Time series
# ===========================================================================

def run_acf_pacf(col: str, session: Dict, df: pd.DataFrame, lags: int = 20) -> Dict:
    """ACF and PACF. Library: statsmodels.tsa.stattools."""
    from statsmodels.tsa.stattools import acf, pacf
    s = pd.to_numeric(df[col], errors='coerce').dropna()
    n = len(s)
    if n < 30:
        return {'error': f'Time series too short (n={n}).'}
    lags = min(lags, n // 4)
    try:
        a = acf(s, nlags=lags, fft=True)
        p = pacf(s, nlags=lags, method='ywm')
    except Exception as e:
        return {'error': f'ACF/PACF failed: {e}'}
    return {
        'test': 'ACF and PACF',
        'test_type': 'acf_pacf',
        'n': n, 'lags': lags,
        'acf': [round(float(v), 3) for v in a],
        'pacf': [round(float(v), 3) for v in p],
        'interpretation': (
            f'ACF/PACF on {col} (n={n}, {lags} lags). '
            f'95% confidence bounds ≈ ±{1.96/math.sqrt(n):.3f}.'),
    }


def run_arima(col: str, session: Dict, df: pd.DataFrame, order: Tuple[int, int, int] = (1, 1, 1)) -> Dict:
    """ARIMA model. Library: statsmodels.tsa.arima.model.ARIMA."""
    from statsmodels.tsa.arima.model import ARIMA
    s = pd.to_numeric(df[col], errors='coerce').dropna()
    n = len(s)
    if n < 30:
        return {'error': f'Time series too short (n={n}).'}
    try:
        res = ARIMA(s, order=order).fit()
    except Exception as e:
        return {'error': f'ARIMA failed: {e}'}
    return {
        'test': f'ARIMA{order}',
        'test_type': 'arima',
        'n': n, 'order': list(order),
        'aic': round(float(res.aic), 2),
        'bic': round(float(res.bic), 2),
        'log_likelihood': round(float(res.llf), 2),
        'interpretation': (
            f'ARIMA{order} on {col} (n={n}). '
            f'AIC = {res.aic:.2f}, BIC = {res.bic:.2f}.'),
    }


def run_seasonal_decompose(col: str, session: Dict, df: pd.DataFrame, period: int = 12) -> Dict:
    """Seasonal decomposition. Library: statsmodels.tsa.seasonal."""
    from statsmodels.tsa.seasonal import seasonal_decompose
    s = pd.to_numeric(df[col], errors='coerce').dropna()
    n = len(s)
    if n < 2 * period:
        return {'error': f'Need n ≥ 2·period (n={n}, period={period}).'}
    try:
        res = seasonal_decompose(s, model='additive', period=period,
                                 extrapolate_trend='freq')
    except Exception as e:
        return {'error': f'Decomposition failed: {e}'}
    return {
        'test': f'Seasonal decomposition (period={period})',
        'test_type': 'seasonal_decompose',
        'n': n, 'period': period,
        'trend_strength': round(float(1 - res.resid.var() / (res.trend + res.resid).var()), 3) if (res.trend + res.resid).var() > 0 else None,
        'seasonal_strength': round(float(1 - res.resid.var() / (res.seasonal + res.resid).var()), 3) if (res.seasonal + res.resid).var() > 0 else None,
        'interpretation': (
            f'Additive seasonal decomposition on {col} '
            f'(n={n}, period={period}).'),
    }


def run_holt_winters(col: str, session: Dict, df: pd.DataFrame, period: int = 12, forecast: int = 12) -> Dict:
    """Holt-Winters exponential smoothing. Library: statsmodels."""
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    s = pd.to_numeric(df[col], errors='coerce').dropna()
    n = len(s)
    if n < 2 * period:
        return {'error': f'Need n ≥ 2·period (n={n}).'}
    try:
        res = ExponentialSmoothing(s, seasonal_periods=period,
                                   trend='add', seasonal='add').fit()
        fcst = res.forecast(forecast)
    except Exception as e:
        return {'error': f'Holt-Winters failed: {e}'}
    return {
        'test': f'Holt-Winters (period={period})',
        'test_type': 'holt_winters',
        'n': n, 'period': period,
        'aic': round(float(res.aic), 2) if hasattr(res, 'aic') else None,
        'forecast': [round(float(v), 3) for v in fcst.values],
        'interpretation': (
            f'Holt-Winters additive (period={period}) on {col} (n={n}); '
            f'{forecast}-step forecast generated.'),
    }


def run_spectral(col: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Periodogram (spectral analysis). Library: scipy.signal."""
    from scipy.signal import periodogram
    s = pd.to_numeric(df[col], errors='coerce').dropna()
    n = len(s)
    if n < 30:
        return {'error': f'Series too short (n={n}).'}
    f, Pxx = periodogram(s.values - s.mean())
    top_idx = int(np.argmax(Pxx[1:])) + 1
    return {
        'test': 'Spectral analysis (periodogram)',
        'test_type': 'spectral',
        'n': n,
        'dominant_frequency': round(float(f[top_idx]), 4),
        'dominant_period': round(float(1 / f[top_idx]), 2) if f[top_idx] > 0 else None,
        'interpretation': (
            f'Periodogram on {col} (n={n}). Dominant frequency '
            f'≈ {f[top_idx]:.4f} (period ≈ {1/f[top_idx]:.1f}).'
            if f[top_idx] > 0 else f'Periodogram on {col} (n={n}).'),
    }


def run_segmented_regression(outcome: str, time_col: str, breakpoint: float, session: Dict, df: pd.DataFrame) -> Dict:
    """Segmented (interrupted time series) regression with one breakpoint.
    Library: statsmodels OLS."""
    import statsmodels.formula.api as smf
    data = df[[outcome, time_col]].apply(pd.to_numeric, errors='coerce').dropna().copy()
    n = len(data)
    if n < 20:
        return {'error': f'Sample too small (n={n}).'}
    data['_post'] = (data[time_col] > breakpoint).astype(int)
    data['_post_time'] = (data[time_col] - breakpoint).clip(lower=0)
    formula = f'Q("{outcome}") ~ Q("{time_col}") + _post + _post_time'
    try:
        res = smf.ols(formula, data=data).fit()
    except Exception as e:
        return {'error': f'Segmented regression failed: {e}'}
    rows = []
    label_map = {'Intercept': 'Intercept',
                 f'Q("{time_col}")': 'Pre-slope',
                 '_post': 'Level change at breakpoint',
                 '_post_time': 'Slope change after breakpoint'}
    for term in res.params.index:
        rows.append({
            'term': label_map.get(term, term),
            'B': round(float(res.params[term]), 4),
            'SE': round(float(res.bse[term]), 4),
            'p': float(res.pvalues[term]),
            'p_display': _h().fmt_p(float(res.pvalues[term])),
        })
    return {
        'test': f'Segmented (ITS) regression at t={breakpoint}',
        'test_type': 'segmented_regression',
        'n': n, 'breakpoint': breakpoint,
        'rows': rows,
        'r_squared': round(float(res.rsquared), 3),
        'interpretation': (
            f'Segmented regression with breakpoint at t = {breakpoint} '
            f'(n={n}). R² = {res.rsquared:.3f}.'),
    }


# ===========================================================================
# §9.14 Survival — extras
# ===========================================================================

def run_stratified_cox(time_col: str, event_col: str, predictors: Sequence[str], strata: Sequence[str], session: Dict, df: pd.DataFrame) -> Dict:
    """Cox PH stratified by `strata`. Library: lifelines.CoxPHFitter."""
    from lifelines import CoxPHFitter
    cols = [time_col, event_col] + list(predictors) + list(strata)
    data = df[cols].dropna()
    n = len(data)
    if n < 30:
        return {'error': f'Sample too small (n={n}).'}
    try:
        cph = CoxPHFitter()
        cph.fit(data, duration_col=time_col, event_col=event_col,
                strata=list(strata))
    except Exception as e:
        return {'error': f'Stratified Cox failed: {e}'}
    s = cph.summary
    rows = []
    for p in predictors:
        if p in s.index:
            rows.append({
                'variable': p,
                'HR': round(float(s.loc[p, 'exp(coef)']), 3),
                'HR_ci': (round(float(s.loc[p, 'exp(coef) lower 95%']), 3),
                          round(float(s.loc[p, 'exp(coef) upper 95%']), 3)),
                'p': float(s.loc[p, 'p']),
                'p_display': _h().fmt_p(float(s.loc[p, 'p'])),
            })
    return {
        'test': 'Stratified Cox regression',
        'test_type': 'stratified_cox',
        'n': n, 'strata': list(strata), 'rows': rows,
        'interpretation': (
            f'Stratified Cox stratified by {", ".join(strata)} '
            f'(n={n}, events={int(data[event_col].sum())}).'),
    }


def run_time_varying_cox(id_col: str, start_col: str, stop_col: str, event_col: str, predictors: Sequence[str], session: Dict, df: pd.DataFrame) -> Dict:
    """Cox model with time-varying covariates. Library: lifelines.CoxTimeVaryingFitter."""
    from lifelines import CoxTimeVaryingFitter
    cols = [id_col, start_col, stop_col, event_col] + list(predictors)
    data = df[cols].dropna()
    n_rows = len(data)
    if n_rows < 30:
        return {'error': f'Sample too small (n_rows={n_rows}).'}
    try:
        ctv = CoxTimeVaryingFitter()
        ctv.fit(data, id_col=id_col, event_col=event_col,
                start_col=start_col, stop_col=stop_col)
    except Exception as e:
        return {'error': f'Time-varying Cox failed: {e}'}
    s = ctv.summary
    rows = []
    for p in predictors:
        if p in s.index:
            rows.append({
                'variable': p,
                'HR': round(float(s.loc[p, 'exp(coef)']), 3),
                'HR_ci': (round(float(s.loc[p, 'exp(coef) lower 95%']), 3),
                          round(float(s.loc[p, 'exp(coef) upper 95%']), 3)),
                'p': float(s.loc[p, 'p']),
                'p_display': _h().fmt_p(float(s.loc[p, 'p'])),
            })
    return {
        'test': 'Time-varying Cox regression',
        'test_type': 'time_varying_cox',
        'n_rows': n_rows, 'n_subjects': int(data[id_col].nunique()),
        'rows': rows,
        'interpretation': (
            f'Time-varying Cox: {n_rows} obs, {data[id_col].nunique()} subjects.'),
    }


def run_parametric_aft(time_col: str, event_col: str, predictors: Sequence[str], session: Dict, df: pd.DataFrame, family: str = 'weibull') -> Dict:
    """Parametric AFT survival model. Library: lifelines."""
    from lifelines import (WeibullAFTFitter, LogNormalAFTFitter,
                           LogLogisticAFTFitter)
    fitters = {
        'weibull': WeibullAFTFitter,
        'lognormal': LogNormalAFTFitter,
        'loglogistic': LogLogisticAFTFitter,
    }
    if family not in fitters:
        return {'error': f'Unknown AFT family {family}.'}
    cols = [time_col, event_col] + list(predictors)
    data = df[cols].dropna()
    n = len(data)
    if n < 30:
        return {'error': f'Sample too small (n={n}).'}
    try:
        f = fitters[family]()
        f.fit(data, duration_col=time_col, event_col=event_col)
    except Exception as e:
        return {'error': f'AFT ({family}) failed: {e}'}
    s = f.summary
    rows = []
    for p in predictors:
        # AFT param tables index by (parameter, covariate); we want the
        # 'lambda_' / 'mu_' rows, depending on family.
        for idx in s.index:
            label = idx[1] if isinstance(idx, tuple) else idx
            if label == p:
                rows.append({
                    'variable': p,
                    'time_ratio': round(float(math.exp(s.loc[idx, 'coef'])), 3),
                    'TR_ci': (round(float(math.exp(s.loc[idx, 'coef lower 95%'])), 3),
                              round(float(math.exp(s.loc[idx, 'coef upper 95%'])), 3)),
                    'p': float(s.loc[idx, 'p']),
                    'p_display': _h().fmt_p(float(s.loc[idx, 'p'])),
                })
                break
    return {
        'test': f'Parametric AFT — {family}',
        'test_type': f'aft_{family}',
        'n': n, 'rows': rows,
        'aic': round(float(f.AIC_), 2) if hasattr(f, 'AIC_') else None,
        'interpretation': (
            f'{family.capitalize()} AFT model (n={n}). '
            f'Time ratio > 1 ⇒ longer survival.'),
    }


def run_rmst(time_col: str, event_col: str, group_col: Optional[str], session: Dict, df: pd.DataFrame, t_horizon: Optional[float] = None) -> Dict:
    """Restricted Mean Survival Time (RMST). Library: lifelines."""
    from lifelines.utils import restricted_mean_survival_time
    from lifelines import KaplanMeierFitter
    cols = [time_col, event_col] + ([group_col] if group_col else [])
    data = df[cols].dropna()
    n = len(data)
    if n < 20:
        return {'error': f'Sample too small (n={n}).'}
    horizon = t_horizon or float(data[time_col].quantile(0.9))
    if group_col is None:
        kmf = KaplanMeierFitter().fit(data[time_col], data[event_col])
        rmst = float(restricted_mean_survival_time(kmf, t=horizon))
        return {
            'test': f'RMST at t={horizon}',
            'test_type': 'rmst',
            'n': n, 't_horizon': horizon,
            'rmst': round(rmst, 3),
            'interpretation': (
                f'RMST up to t={horizon}: {rmst:.3f} (n={n}).'),
        }
    rows = []
    for lvl in data[group_col].unique():
        sub = data[data[group_col] == lvl]
        if len(sub) < 5:
            continue
        kmf = KaplanMeierFitter().fit(sub[time_col], sub[event_col])
        rmst = float(restricted_mean_survival_time(kmf, t=horizon))
        rows.append({'group': str(lvl), 'n': len(sub), 'rmst': round(rmst, 3)})
    diff = (rows[0]['rmst'] - rows[1]['rmst']) if len(rows) >= 2 else None
    return {
        'test': f'RMST by {group_col} at t={horizon}',
        'test_type': 'rmst',
        'n': n, 't_horizon': horizon,
        'rows': rows,
        'rmst_difference': round(diff, 3) if diff is not None else None,
        'interpretation': (
            f'RMST up to t={horizon} by {group_col} '
            f'(n={n}, {len(rows)} groups).'),
    }


def run_cif(time_col: str, event_col: str, session: Dict, df: pd.DataFrame, event_of_interest: int = 1) -> Dict:
    """Cumulative Incidence Function via Aalen-Johansen.
    `event_col` should code: 0 = censored, 1 = event of interest,
    2+ = competing events. Library: lifelines.AalenJohansenFitter."""
    from lifelines import AalenJohansenFitter
    data = df[[time_col, event_col]].dropna()
    n = len(data)
    if n < 20:
        return {'error': f'Sample too small (n={n}).'}
    if data[event_col].nunique() < 3:
        return {'warning': ('Competing-risks CIF expects ≥3 distinct event '
                            'codes (0=censored, 1=event-of-interest, ≥2=competing). '
                            'Use Kaplan-Meier when only 0/1 are present.'),
                'partial_result': True, 'test_type': 'cif', 'n': n}
    try:
        ajf = AalenJohansenFitter()
        ajf.fit(durations=data[time_col],
                event_observed=data[event_col],
                event_of_interest=event_of_interest)
    except Exception as e:
        return {'error': f'Aalen-Johansen CIF failed: {e}'}
    cif = ajf.cumulative_density_
    final = float(cif.iloc[-1, 0])
    return {
        'test': 'Cumulative Incidence Function (Aalen-Johansen)',
        'test_type': 'cif',
        'n': n,
        'event_of_interest': event_of_interest,
        'final_cif': round(final, 3),
        'time_grid': [round(float(t), 3) for t in cif.index.tolist()[:50]],
        'cif_curve': [round(float(v), 3) for v in cif.iloc[:50, 0].tolist()],
        'interpretation': (
            f'Aalen-Johansen CIF for event = {event_of_interest} (n={n}). '
            f'Final CIF = {final:.3f}.'),
    }


def run_cause_specific_cox(time_col: str, event_col: str, predictors: Sequence[str], session: Dict, df: pd.DataFrame, event_of_interest: int = 1) -> Dict:
    """Cause-specific Cox PH — competing events treated as censoring.
    Library: lifelines.CoxPHFitter."""
    from lifelines import CoxPHFitter
    cols = [time_col, event_col] + list(predictors)
    data = df[cols].dropna().copy()
    n = len(data)
    if n < 30:
        return {'error': f'Sample too small (n={n}).'}
    data['_event'] = (data[event_col] == event_of_interest).astype(int)
    fit_data = data[[time_col, '_event'] + list(predictors)]
    try:
        cph = CoxPHFitter()
        cph.fit(fit_data, duration_col=time_col, event_col='_event')
    except Exception as e:
        return {'error': f'Cause-specific Cox failed: {e}'}
    s = cph.summary
    rows = []
    for p in predictors:
        if p in s.index:
            rows.append({
                'variable': p,
                'cause_specific_HR': round(float(s.loc[p, 'exp(coef)']), 3),
                'HR_ci': (round(float(s.loc[p, 'exp(coef) lower 95%']), 3),
                          round(float(s.loc[p, 'exp(coef) upper 95%']), 3)),
                'p': float(s.loc[p, 'p']),
                'p_display': _h().fmt_p(float(s.loc[p, 'p'])),
            })
    return {
        'test': 'Cause-specific Cox regression',
        'test_type': 'cause_specific_cox',
        'n': n,
        'event_of_interest': event_of_interest,
        'n_events_of_interest': int(data['_event'].sum()),
        'rows': rows,
        'interpretation': (
            f'Cause-specific Cox for event = {event_of_interest} '
            f'(n={n}, events = {int(data["_event"].sum())}). '
            f'Competing events treated as censored.'),
    }


# ===========================================================================
# §9.16 Imputation
# ===========================================================================

def run_mice_imputation(features: Sequence[str], session: Dict, df: pd.DataFrame, n_imputations: int = 5) -> Dict:
    """Multiple Imputation via Chained Equations (point-imputation summary).
    Library: sklearn.IterativeImputer."""
    from sklearn.experimental import enable_iterative_imputer  # noqa: F401
    from sklearn.impute import IterativeImputer
    data = df[list(features)].copy()
    n = len(data)
    n_missing = int(data.isna().sum().sum())
    if n_missing == 0:
        return {'warning': 'No missing values to impute.',
                'partial_result': True, 'test_type': 'mice', 'n': n}
    rng = np.random.default_rng(42)
    sums = np.zeros((n, len(features)))
    for i in range(n_imputations):
        imp = IterativeImputer(random_state=int(rng.integers(0, 1_000_000)))
        sums += imp.fit_transform(data.values)
    mean_imp = sums / n_imputations
    return {
        'test': f'MICE imputation ({n_imputations} draws, mean of imputations)',
        'test_type': 'mice',
        'n': n, 'n_missing': n_missing,
        'features': list(features),
        'mean_imputation_preview': mean_imp[:5].round(3).tolist(),
        'interpretation': (
            f'MICE: {n_missing} missing values imputed across {n_imputations} '
            f'iterations on {len(features)} features (n={n}). '
            f'Use the imputed dataset for downstream tests.'),
    }


# ===========================================================================
# §9.19 ROC + Diagnostic — DeLong test
# ===========================================================================

def _delong_fast(ground_truth: np.ndarray, predictions: np.ndarray) -> Tuple[float, np.ndarray]:
    """Compute AUC and the variance-covariance structures used by DeLong's
    test. Implementation of the Sun & Xu (2014) fast O(n log n) algorithm,
    IEEE Signal Processing Letters 21(11):1389-1393. This is a port of the
    published algorithm — not a hand-rolled statistic."""
    order = np.argsort(-predictions)
    label_1_count = int(ground_truth.sum())
    n = len(ground_truth)
    label_0_count = n - label_1_count
    # Compute mid-rank within each class.
    def _midrank(x):
        J = np.argsort(x, kind='mergesort')
        Z = x[J]
        N = len(x)
        T = np.zeros(N, dtype=float)
        i = 0
        while i < N:
            j = i
            while j < N and Z[j] == Z[i]:
                j += 1
            T[i:j] = 0.5 * (i + j - 1) + 1
            i = j
        T2 = np.empty(N, dtype=float)
        T2[J] = T
        return T2
    ordered_truth = ground_truth[order]
    ordered_pred = predictions[order]
    pos_pred = ordered_pred[ordered_truth == 1]
    neg_pred = ordered_pred[ordered_truth == 0]
    tx = _midrank(pos_pred)
    ty = _midrank(neg_pred)
    tz = _midrank(ordered_pred)
    auc = (tz[ordered_truth == 1].sum() / label_1_count - (label_1_count + 1) / 2) / label_0_count
    v01 = (tz[ordered_truth == 1] - tx) / label_0_count
    v10 = 1 - (tz[ordered_truth == 0] - ty) / label_1_count
    sx = np.cov(v01, ddof=1) if v01.size > 1 else 0.0
    sy = np.cov(v10, ddof=1) if v10.size > 1 else 0.0
    var_auc = sx / label_1_count + sy / label_0_count
    return float(auc), np.array([[var_auc]])


def run_delong(disease_col: str, test1_col: str, test2_col: str, session: Dict, df: pd.DataFrame, positive_class: int = 1) -> Dict:
    """DeLong's test for comparing two correlated AUCs.
    Algorithm: Sun & Xu (2014), IEEE SPL — port of the published
    O(n log n) vectorised algorithm (no hand-derived statistics).
    Library: scipy.stats.norm + sklearn (for AUC sanity check)."""
    from sklearn.metrics import roc_auc_score
    data = df[[disease_col, test1_col, test2_col]].dropna()
    n = len(data)
    if n < 30:
        return {'error': f'Sample too small (n={n}).'}
    y = (data[disease_col] == positive_class).astype(int).values
    if y.sum() == 0 or y.sum() == n:
        return {'error': 'Disease column must contain both positive and negative cases.'}

    # Compute AUCs and per-test variance using fast DeLong.
    auc1, var1 = _delong_fast(y, data[test1_col].values.astype(float))
    auc2, var2 = _delong_fast(y, data[test2_col].values.astype(float))

    # Cross-covariance via the joint computation.
    # Stack the two predictors and run the Sun & Xu joint algorithm.
    preds = np.vstack([data[test1_col].values.astype(float),
                       data[test2_col].values.astype(float)])
    aucs = np.array([auc1, auc2])
    # Joint covariance of the two AUCs.
    def _joint_cov(y, preds):
        m = int(y.sum())
        n_neg = len(y) - m
        pos_idx = np.where(y == 1)[0]
        neg_idx = np.where(y == 0)[0]
        v01_mat = np.zeros((preds.shape[0], m))
        v10_mat = np.zeros((preds.shape[0], n_neg))
        for k in range(preds.shape[0]):
            pk = preds[k]
            pos_p = pk[pos_idx]
            neg_p = pk[neg_idx]
            # v01[i] = (1/n_neg) * sum_j (I(neg_p[j] < pos_p[i]) + 0.5 * I(neg_p[j] == pos_p[i]))
            v01 = np.array([
                (np.sum(neg_p < pos_p[i]) + 0.5 * np.sum(neg_p == pos_p[i])) / n_neg
                for i in range(m)
            ])
            v10 = np.array([
                (np.sum(pos_p > neg_p[j]) + 0.5 * np.sum(pos_p == neg_p[j])) / m
                for j in range(n_neg)
            ])
            v01_mat[k] = v01
            v10_mat[k] = v10
        s01 = np.cov(v01_mat, ddof=1) if m > 1 else np.zeros((preds.shape[0], preds.shape[0]))
        s10 = np.cov(v10_mat, ddof=1) if n_neg > 1 else np.zeros((preds.shape[0], preds.shape[0]))
        return s01 / m + s10 / n_neg
    cov = _joint_cov(y, preds)
    diff = auc1 - auc2
    var_diff = float(cov[0, 0] + cov[1, 1] - 2 * cov[0, 1])
    if var_diff <= 0:
        return {'warning': 'DeLong variance non-positive — AUCs may be identical.',
                'partial_result': True, 'auc_diff': round(diff, 4),
                'test_type': 'delong', 'n': n}
    z = diff / math.sqrt(var_diff)
    p = 2 * (1 - _ss.norm.cdf(abs(z)))
    ci_lo = diff - 1.96 * math.sqrt(var_diff)
    ci_hi = diff + 1.96 * math.sqrt(var_diff)
    # Sanity-check AUCs against sklearn.
    auc1_sk = float(roc_auc_score(y, data[test1_col]))
    auc2_sk = float(roc_auc_score(y, data[test2_col]))
    return {
        'test': "DeLong's test for two correlated AUCs",
        'test_type': 'delong',
        'n': n,
        'auc1': round(auc1, 3), 'auc1_sklearn_check': round(auc1_sk, 3),
        'auc2': round(auc2, 3), 'auc2_sklearn_check': round(auc2_sk, 3),
        'auc_difference': round(diff, 4),
        'ci': (round(ci_lo, 4), round(ci_hi, 4)),
        'z': round(z, 3),
        'p': float(p),
        'p_display': _h().fmt_p(float(p)),
        'algorithm_reference': 'Sun & Xu (2014), IEEE Signal Processing Letters',
        'interpretation': (
            f"DeLong's test (n={n}): AUC₁ = {auc1:.3f} vs AUC₂ = {auc2:.3f}, "
            f'difference = {diff:.4f} (95% CI {ci_lo:.4f}–{ci_hi:.4f}), '
            f'z = {z:.3f}, p = {_h().fmt_p(float(p))}.'),
    }


# ===========================================================================
# §9.20 Bayesian (limited)
# ===========================================================================

def run_bayesian_t(col: str, group: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Bayesian t-test reporting Bayes Factor BF₁₀. Library: pingouin."""
    import pingouin as pg
    data = df[[col, group]].dropna()
    levels = data[group].unique()
    if len(levels) != 2:
        return {'error': 'Bayesian t-test needs exactly 2 groups.'}
    a = pd.to_numeric(data[data[group] == levels[0]][col], errors='coerce').dropna()
    b = pd.to_numeric(data[data[group] == levels[1]][col], errors='coerce').dropna()
    n = len(a) + len(b)
    if min(len(a), len(b)) < 5:
        return {'error': f'Each group needs ≥5 obs.'}
    try:
        res = pg.ttest(a, b, paired=False)
    except Exception as e:
        return {'error': f'Bayesian t-test failed: {e}'}
    bf10_raw = res.get('BF10', None)
    bf10 = None
    if bf10_raw is not None and len(bf10_raw) > 0:
        try:
            bf10 = float(bf10_raw.iloc[0])
        except Exception:
            try:
                bf10 = float(str(bf10_raw.iloc[0]))
            except Exception:
                bf10 = None
    interp = 'inconclusive'
    if bf10 is not None:
        if bf10 > 30:
            interp = 'very strong evidence for difference'
        elif bf10 > 10:
            interp = 'strong evidence for difference'
        elif bf10 > 3:
            interp = 'moderate evidence for difference'
        elif bf10 > 1:
            interp = 'anecdotal evidence for difference'
        elif bf10 > 1/3:
            interp = 'inconclusive'
        else:
            interp = 'evidence for null'
    return {
        'test': 'Bayesian t-test (BF₁₀)',
        'test_type': 'bayesian_t',
        'n': n, 'BF10': round(bf10, 3) if bf10 is not None else None,
        'interpretation_tier': interp,
        'p': float(res['p-val'].iloc[0]),
        'p_display': _h().fmt_p(float(res['p-val'].iloc[0])),
        'interpretation': (
            f'Bayesian t-test on {col} by {group} (n={n}): '
            f'BF₁₀ = {bf10:.3f} ({interp}).' if bf10 is not None else
            f'Bayesian t-test on {col} by {group} (n={n}): BF₁₀ unavailable.'),
    }


# ===========================================================================
# §9.22 Post-hocs and corrections
# ===========================================================================

def run_tukey_hsd(outcome: str, group: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Tukey HSD post-hoc. Library: statsmodels.pairwise_tukeyhsd."""
    from statsmodels.stats.multicomp import pairwise_tukeyhsd
    data = df[[outcome, group]].dropna()
    n = len(data)
    if data[group].nunique() < 3:
        return {'error': 'Tukey HSD needs ≥3 groups.'}
    try:
        res = pairwise_tukeyhsd(data[outcome], data[group])
    except Exception as e:
        return {'error': f'Tukey HSD failed: {e}'}
    rows = []
    for r in res.summary().data[1:]:
        rows.append({
            'pair': f'{r[0]} vs {r[1]}',
            'mean_diff': round(float(r[2]), 3),
            'p_adj': float(r[3]),
            'p_display': _h().fmt_p(float(r[3])),
            'ci': (round(float(r[4]), 3), round(float(r[5]), 3)),
            'significant': bool(r[6]),
        })
    return {
        'test': 'Tukey HSD post-hoc',
        'test_type': 'tukey_hsd',
        'n': n, 'rows': rows,
        'interpretation': (
            f'Tukey HSD on {outcome} by {group} '
            f'(n={n}, {data[group].nunique()} groups).'),
    }


def run_games_howell(outcome: str, group: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Games-Howell post-hoc (unequal variances). Library: pingouin."""
    import pingouin as pg
    data = df[[outcome, group]].dropna()
    if data[group].nunique() < 3:
        return {'error': 'Games-Howell needs ≥3 groups.'}
    try:
        res = pg.pairwise_gameshowell(data=data, dv=outcome, between=group)
    except Exception as e:
        return {'error': f'Games-Howell failed: {e}'}
    rows = []
    for _, r in res.iterrows():
        p = float(r['pval'])
        rows.append({
            'pair': f'{r["A"]} vs {r["B"]}',
            'mean_diff': round(float(r['diff']), 3),
            'se': round(float(r['se']), 3),
            't': round(float(r['T']), 3),
            'p_adj': p,
            'p_display': _h().fmt_p(p),
            'significant': p < 0.05,
        })
    return {
        'test': 'Games-Howell post-hoc',
        'test_type': 'games_howell',
        'n': len(data), 'rows': rows,
        'interpretation': (
            f'Games-Howell on {outcome} by {group} '
            f'(n={len(data)}). Robust to unequal variances.'),
    }


def run_dunnett(outcome: str, group: str, control: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Dunnett's test — all groups vs one control. Library: scipy ≥1.12."""
    data = df[[outcome, group]].dropna()
    if control not in data[group].astype(str).unique():
        return {'error': f'Control level "{control}" not found.'}
    control_vals = pd.to_numeric(data[data[group].astype(str) == control][outcome],
                                 errors='coerce').dropna().values
    others = [(str(lvl),
               pd.to_numeric(data[data[group].astype(str) == str(lvl)][outcome],
                             errors='coerce').dropna().values)
              for lvl in data[group].astype(str).unique() if str(lvl) != control]
    if not others:
        return {'error': 'No non-control groups.'}
    try:
        res = _ss.dunnett(*[g for _, g in others], control=control_vals)
    except Exception as e:
        return {'error': f"Dunnett's failed: {e}"}
    rows = []
    for (lvl, _), stat, p in zip(others, res.statistic, res.pvalue):
        p = float(p)
        rows.append({
            'pair': f'{lvl} vs {control}',
            'statistic': round(float(stat), 3),
            'p_adj': p,
            'p_display': _h().fmt_p(p),
            'significant': p < 0.05,
        })
    return {
        'test': "Dunnett's test (vs control)",
        'test_type': 'dunnett',
        'n': len(data), 'control': control, 'rows': rows,
        'interpretation': (
            f"Dunnett's test on {outcome}: "
            f'{len(others)} groups vs control "{control}" (n={len(data)}).'),
    }


def run_multiple_comparison_correction(p_values: Sequence[float], method: str = 'holm') -> Dict:
    """Apply a multiple-testing correction.
    method ∈ {bonferroni, sidak, holm, holm-sidak, simes-hochberg,
              hommel, fdr_bh, fdr_by, fdr_tsbh, fdr_tsbky}.
    Library: statsmodels.stats.multitest.multipletests."""
    from statsmodels.stats.multitest import multipletests
    p_values = list(p_values)
    if not p_values:
        return {'error': 'No p-values supplied.'}
    try:
        reject, p_adj, _, _ = multipletests(p_values, alpha=0.05, method=method)
    except Exception as e:
        return {'error': f'Correction failed: {e}'}
    return {
        'test': f'Multiple-testing correction — {method}',
        'test_type': 'multiple_correction',
        'n_tests': len(p_values),
        'method': method,
        'rows': [
            {'index': i, 'p_raw': float(p_values[i]),
             'p_adj': float(p_adj[i]),
             'p_display': _h().fmt_p(float(p_adj[i])),
             'significant': bool(reject[i])}
            for i in range(len(p_values))
        ],
        'interpretation': (
            f'{method} correction over {len(p_values)} tests: '
            f'{int(sum(reject))} survive at α=0.05.'),
    }


# ===========================================================================
# §9.21 Effect-size helpers (cross-cutting)
# ===========================================================================

def run_omega_squared(outcome: str, group: str, session: Dict, df: pd.DataFrame) -> Dict:
    """Omega-squared effect size for one-way ANOVA. Library: scipy."""
    data = df[[outcome, group]].dropna()
    groups = [pd.to_numeric(data[data[group] == lvl][outcome], errors='coerce').dropna().values
              for lvl in data[group].unique()]
    groups = [g for g in groups if len(g) >= 2]
    if len(groups) < 2:
        return {'error': 'Need ≥2 groups with ≥2 obs.'}
    f, p = _ss.f_oneway(*groups)
    n = sum(len(g) for g in groups)
    k = len(groups)
    df_b = k - 1
    df_w = n - k
    ms_w = sum(np.var(g, ddof=1) * (len(g) - 1) for g in groups) / df_w
    ss_b = float(f * df_b * ms_w)
    omega2 = (ss_b - df_b * ms_w) / (sum((np.array(g) ** 2).sum() for g in groups) -
                                     (sum(g.sum() for g in groups)) ** 2 / n + ms_w)
    return {
        'test': 'Omega-squared (ω²) effect size',
        'test_type': 'omega_squared',
        'n': n,
        'F': round(float(f), 3), 'p': float(p),
        'omega_squared': round(float(omega2), 3),
        'interpretation': (
            f'ω² = {omega2:.3f} for {outcome} by {group} (n={n}). '
            f'Small=0.01, Medium=0.06, Large=0.14.'),
    }
