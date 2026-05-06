# Tests with no Python library (explicitly not implemented)

This file documents items from `Stat_Engine_Tests.docx` (sections 9.1-9.22) that
the engine **does not implement** because there is no maintained, first-class
Python library that performs them. Each entry lists what was checked and why
the engine refuses to fabricate a result.

The engine's policy: never hand-roll inferential statistics, never use an LLM
for numerics, never silently approximate a test the user asked for. If a user
selects one of these in the wizard, the engine returns a clear "not implemented"
message with a pointer to this file.

## Confirmed gaps (no Python library)

| Section | Test | Why no library |
|---|---|---|
| §9.6 | **Tobit (left-censored regression)** | `lifelines` only handles right-censoring well; no maintained Tobit library. |
| §9.6 | **SEM, CFA, Path analysis** | `semopy` exists but is fragile and dependency-heavy; not added to MedRAS. |
| §9.5 | **Tetrachoric, Polychoric correlation** | `statsmodels` does not expose these; available estimators in `semopy`/`prince` are unreliable. |
| §9.8 | **RBF neural network classifier** | `sklearn` has `RBFSampler` for kernels but no native RBF NN classifier; no other maintained library. |
| §9.9 | **Two-step cluster** | No maintained Python equivalent of SPSS's two-step procedure. (BIRCH is conceptually different.) |
| §9.10 | **Correspondence analysis, MCA** | `prince` is the only option but is not actively maintained. |
| §9.11 | **McDonald's omega (ω)** | Requires a fitted CFA model; depends on a SEM library not in deps. |
| §9.12 | **Fisher-Freeman-Halton (large r×c tables)** | `scipy.stats.fisher_exact` is 2×2 only; no Python implementation for the general r×c exact test. |
| §9.12 | **Jonckheere-Terpstra trend test** | No maintained Python library; would need a hand-rolled implementation. |
| §9.12 | **Page's L trend test** | Same — no library; algorithm available but explicitly excluded by policy. |
| §9.13 | **Joinpoint regression** | Standard tool is the NCI's R/standalone Joinpoint program; no Python equivalent. |
| §9.14 | **Fine-Gray subdistribution hazard model** | Not in `lifelines`, `scikit-survival`, or `statsmodels`. R's `cmprsk` is the canonical implementation; calling it would need `rpy2`. |
| §9.14 | **Interval-censored survival regression** | `lifelines` interval-censored support is limited to point estimation; no formal regression. |
| §9.15 | **Multiple response analysis** | This is a data-tabulation feature, not a statistical test — `pandas` reproduces it directly without a dedicated library. |
| §9.16 | **Little's MCAR test** | No maintained Python library; the only candidates (`impyute`) are unreliable. |
| §9.17 | **Complex samples (svy logistic / svy Cox / etc.)** | `samplics` exists but is heavy and rarely updated; not added to MedRAS. |
| §9.18 | **Quality-control charts as inferential tests** | X-bar/R, I-MR, P, C, CUSUM are charts, not tests; the engine does not surface them as "tests" — visualisation only. |
| §9.20 | **Bayesian ANOVA / regression / model comparison** | Would require `pymc` + `bambi` (large C-compiled stack); explicitly excluded to keep MedRAS lean. Bayesian t-test (BF₁₀) **is** implemented via `pingouin`. |
| §9.21 | **Profile analysis, Multivariate GLM standalone** | `statsmodels` has MANOVA but not a fully-featured Multivariate GLM that matches SPSS GLM-Multivariate. |

## Borderline cases — implemented with a published-algorithm port

These have no first-tier Python library, but have a peer-reviewed published
algorithm that we ported verbatim with the citation in the runner's docstring.
Authorised by the user.

| Test | Algorithm reference | Runner |
|---|---|---|
| **DeLong's test for two correlated AUCs** | Sun & Xu (2014), *IEEE Signal Processing Letters* 21(11):1389-1393 | `pc_delong` in `tests_phase_c.py` |

## Implemented despite no R-style direct library

These are implemented by composing primitives from libraries already in
`requirements.txt`. They are mathematically equivalent to the named test, not
approximations.

| Test | Composition |
|---|---|
| **Cause-specific Cox** | `lifelines.CoxPHFitter` with competing events recoded as censored. This *is* the formal cause-specific approach. |
| **Cumulative Incidence Function (CIF)** | `lifelines.AalenJohansenFitter` — the standard estimator. |
| **General / Hierarchical loglinear** | `statsmodels` Poisson GLM with formulaic factor interactions on aggregated counts — equivalent parameterisation. |
| **Segmented (interrupted) time-series regression** | `statsmodels` OLS with intervention + post-time slope dummies. |
| **Sign test** | `scipy.stats.binomtest` on the count of positive differences (the formal definition). |
| **Split-half reliability** | `scipy.stats.pearsonr` between odd/even item totals + Spearman-Brown correction (the formal definition). |
