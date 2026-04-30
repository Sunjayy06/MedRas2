# MedRAS — Medical Research Acceleration System

## Overview

MedRAS is a structured Research Operating System for medical, biomedical, and academic researchers. It guides users from research objective to submission-ready manuscript through six core modules:

1. **Study Builder** — translates a research objective into a structured methodology
2. **Sample Size Calculator** — formula-driven sample size estimation
3. **Statistical Analysis Engine** — Excel data ingestion and parametric/non-parametric testing
4. **Proposal Generator** — ICMR / institutional / university proposal drafting
5. **Thesis & Article Writer** — structured manuscript and dissertation chapter compilation
6. **Plagiarism & Compliance** — originality scoring and citation verification

## Architecture

- **Backend:** Python 3.11 + FastAPI, served by Uvicorn on port 8000.
- **Frontend:** Plain HTML / CSS / JavaScript served as static files by FastAPI itself. No React, Vite, or other framework — kept intentionally simple per the product brief.
- **Routing:** `/api/*` paths are handled by FastAPI route handlers; everything else is served from `artifacts/medras/public/`.
- **Statistics:** All numerical computation is done by validated Python libraries (`scipy.stats`, `statsmodels`, `lifelines` planned). LLMs are used for planning and writing only — never for numerical results.

## Project Structure

```
artifacts/medras/
├── .replit-artifact/artifact.toml   # service config (do not edit directly)
├── main.py                          # FastAPI entry point
├── requirements.txt                 # Python deps
├── app/
│   ├── api/                         # API routers, one file per module
│   │   ├── __init__.py              # aggregate router
│   │   └── health.py                # /healthz, /readyz
│   └── core/
│       ├── config.py                # env-backed settings
│       ├── limiter.py               # slowapi rate limiter
│       └── logging.py               # structured logging setup
└── public/
    ├── index.html                   # landing page
    ├── css/style.css
    └── js/app.js
```

Each new module gets its own router file under `app/api/<module>.py` and is mounted in `app/api/__init__.py`. Each new module's UI gets its own HTML file under `public/<module>.html`.

## Modules Implemented

- **Module 02 — Sample Size Calculator** (`/sample-size.html`)
  - Three-step UI: enter objective → choose/confirm formula and parameters → view result.
  - Backend endpoints: `POST /api/sample-size/analyze`, `POST /api/sample-size/calculate`, `POST /api/sample-size/reverse`.
  - **14 supported formulas** (forward + reverse for each):
      - Descriptive: `single_proportion`, `single_mean`
      - Comparative: `two_proportions`, `two_means`, `paired_means`,
        `anova_means` (one-way, ≥3 groups, normal-approx)
      - Longitudinal: `repeated_measures` (two groups across m timepoints,
        Diggle variance factor (1+(m−1)ρ)/m),
        `repeated_measures_anova` (k groups × m timepoints, between-within
        design, Cohen's f, with α Bonferroni-adjusted across the (k − 1)
        between-group contrasts so k_groups meaningfully affects n)
      - Correlation: `correlation` (Pearson r via Fisher's z transform)
      - Survival: `survival_logrank` (Schoenfeld events formula, then
        n_total = events / overall_event_rate, with allocation ratio)
      - Modelling: `linear_regression` (Cohen R²/f² formula),
        `prediction_model` (events-per-variable rule, Peduzzi 1996;
        does NOT use α or β)
      - Agreement / diagnostic: `kappa_agreement` (Cohen's κ precision),
        `roc_auc` (Hanley & McNeil 1982 AUC variance, solved as a
        quadratic in n_cases)
  - Objective analyzer uses OpenAI when `OPENAI_API_KEY` is set; otherwise a
    rule-based heuristic classifies group count, outcome type, and study
    design. Specialised regex hints route to longitudinal / regression /
    prediction / agreement / diagnostic / correlation / RM-ANOVA / survival
    before falling back to the generic descriptive vs comparative paths.
  - Analyzer also returns `study_type` (auto-detected from objective wording:
    quantitative, qualitative, focus_group, pilot, questionnaire, in_vitro,
    in_vivo) and `suggested_dropout` (heuristic — 0.10–0.15 for
    longitudinal/RCT/cohort, 0 for cross-sectional/in-vitro/lab work).
    The Step 1 form has a Study Type select that overrides auto-detection.
  - **Non-formulaic study types** route to `STUDY_TYPE_RECOMMENDATIONS` (a
    constant in `sample_size.py`) instead of a formula:
    qualitative=12-15, focus_group=24, pilot=25, questionnaire=384,
    in_vitro/in_vivo=evidence-based recommended ranges. The API returns
    these as `study_type_recommendation` on the `/analyze` response and the
    UI renders a dedicated recommendation panel (no "Use this formula"
    button — there is no formula to use).
  - Z-scores derived from Acklam's inverse-normal algorithm (no SciPy dependency).
  - Result panel always shows: per-group n, statistically-required total, dropout-
    adjusted total, full input list, all derived constants (Z(α/2), Z(β), p̄, …),
    and an optional comparison against the researcher's expected sample size.
  - **Step 3 "Recommended statistical formula" callout** appears at the top
    of every result (forward and reverse). Shows the formula label, a
    plain-language "Ideal for: …" description from the `IDEAL_FOR` map in
    `sample-size.js` (one entry per formula), an optional "Why this formula
    was selected" rationale (only when the user came via the analyze flow
    AND `state.lastAnalysis.suggested_formula` matches the active formula),
    and an "Assumptions:" line summarising α, power, dropout, and forward
    vs reverse mode.
  - **"Download full report" button** on Step 3 generates a self-contained
    HTML report client-side (no backend round-trip) via
    `Blob([html],{type:'text/html'})`, named
    `medras-sample-size-<formula_key>-<YYYY-MM-DD>.html`. The report
    contains the objective, the recommended-formula callout (label, ideal-
    for, rationale), the headline result cards (per-group / total /
    adjusted, or back-calculated effect cards in reverse mode), the formula
    expression, full input and constants tables, notes, warnings, and a
    MedRAS footer. Users can open it in any browser and print to PDF. All
    untrusted fields (formula label, ideal-for, rationale, objective,
    table keys/values, notes, warnings, headline cards, total_n,
    adjusted_n) are escaped via a local `escapeHtml` helper.
  - **Mode dropdown on step 2** ("What information do you have for this
    study?") replaces the older reverse-mode checkbox. Two options:
      - *forward* — the researcher has the statistical inputs (effect
        size, precision, α, β, …) and wants the required sample size.
        Every param input is rendered with a sensible default in its
        placeholder; any blank input is auto-filled from `DEFAULTS` on
        submit so the user can always get a quick estimate.
      - *reverse* — the researcher only has an expected sample size and
        wants the formula solved for the smallest detectable effect /
        precision / max-predictors / etc. **Reverse mode renders only the
        n input plus any structural design fields** (k_groups,
        m_timepoints, predictors). All other reference parameters are
        silently filled from `DEFAULTS` and disclosed in a "Defaults used"
        <details> panel for transparency.
    The dropdown's helper text is rewritten per-formula to describe what
    "back-calculate" means for that specific test.
  - **Reverse-mode targets** per formula:
      - single_proportion / single_mean → smallest precision (margin of error)
      - two_proportions → smallest detectable p₂ in each direction (bisection)
      - two_means → smallest detectable Δ (plus equivalent Cohen's d)
      - paired_means → smallest detectable within-pair Δ (plus dz)
      - anova_means → smallest detectable Cohen's f
      - repeated_measures → smallest detectable Δ across m timepoints
      - repeated_measures_anova → smallest detectable Cohen's f
      - correlation → smallest detectable |r|
      - survival_logrank → smallest detectable hazard ratio in each direction
      - linear_regression → smallest detectable R² (and Cohen's f²)
      - prediction_model → maximum candidate predictors at the EPV target
      - kappa_agreement → tightest achievable CI half-width around κ
      - roc_auc → tightest achievable CI half-width around the AUC
    All reverse responses share the same shape:
    `{formula, mode, formula_label, formula_expression, inputs, constants,
      headline[], detectable, notes, warnings}`.
  - JS spec flags `usesAlpha` and `usesPower` per formula gate which
    statistical-assumption fields are sent and shown — `prediction_model`
    sets both to `false` because the EPV rule is rule-of-thumb based.
  - **Master UX upgrade (April 2026)** — implements 7 changes from the
    final master prompt while preserving everything above:
      1. **Three-tier entry chooser (Step 0).** Card A "I just have a
         sample size" (lazy n-only path; auto-runs reverse mode and
         falls back to the closest reverse-capable formula if the
         parser-chosen one has no reverse spec). Card B "I know my
         study details" (drops into the existing Step 1 form). Card C
         "Guide me step by step" (5-question wizard: objective →
         compare? → groups? → have n? → α; Q3 is skipped when no
         comparison; the final calc uses `objectiveParser` plus the
         wizard answers).
      2. **Client-side objective parser (`objectiveParser`).** Regex-
         based flag detection (groups, outcome type, longitudinal,
         genetic, design=non_inferiority|equivalence) with a priority
         table that routes to a formula and emits "Detected: [chip]
         [chip]" labels rendered as `panel-detected` chips above the
         result. Visible on Card A and Card C results.
      3. **Traffic-light verdict card (Step 3, top).** Compares
         `expected_n` vs `adjusted_n`: GREEN ≥100 %, AMBER ≥80 %, RED
         <80 %; falls back to a BLUE "Estimate" card when no
         expected_n was given (Card A always lands here). New
         "Auto-filled defaults" table between constants and notes
         lists every input that was blanked-and-defaulted, with the
         `WHY_DEFAULTS` rationale.
      4. **Complex-trial layered pipeline (`applyComplexLayers`).**
         Activates only when the Step 2 complexity radio is set to
         "complex". Layered adjustments: composite outcomes (TRUE
         Šidák correction `α_per = 1−(1−α)^(1/m_eff)` using the study
         α, not a hardcoded 0.05), repeated measures (Diggle variance
         reduction `(1+(m−1)ρ)/m`), multicentre design effect
         `DEFF = 1+(c̄−1)·ICC`, adaptive α-spending penalty (5/7/10 %
         for 1/2/≥3 interims). Renders a layer-by-layer table plus a
         ±20 % sensitivity range.
      5. **Genetic study engine (`geneticEngineSelect`).** Triggered
         by the Step 2 "genetic" radio or the parser GENETIC flag.
         Five sub-types: candidate_gene, gwas (forces α=5e-8 and
         shows a warning panel), pharmacogenomic, carrier, linkage
         (info-only — LOD-score-based, not powered like a frequentist
         test). Maps each to an existing formula with the appropriate
         α + parameters and renders a blue genetic checklist on the
         result.
      6. **Conditional dropout (`DROPOUT_RULES` map).** The dropout
         field is hidden for kappa, roc_auc, correlation, icc,
         diagnostic_accuracy, in_vitro, in_vivo and surveys; renamed
         to "Experimental failure rate" for in-vitro work and
         "Animal loss rate" for in-vivo work where applicable.
      7. **Five new formulas (all client-side, no API call).**
         `non_inferiority` (one-sided α; `n/group = 2σ²(Z_α+Z_β)² /
         (δ+M)²`), `equivalence` (TOST: `n/group = 2σ²(Z_α+Z_{β/2})²
         / (M−|δ|)²`), `diagnostic_accuracy` (Hajian-Tilaki
         sensitivity/specificity CI; total n scaled by prevalence),
         `icc` (Bonett 2002 closed-form for ρ₀ vs ρ₁ with k raters),
         `bayesian_credible` (normal-normal conjugate; solves for n
         given desired credible-interval half-width). Forward-only;
         routed via `FORMULAS[*].clientCompute` flag in `onCalculate`.
- Other five modules: scaffolded on the landing page, not yet implemented.

## Environment Variables

Configured via Replit Secrets. The app starts even without these but the corresponding modules will be disabled.

- `OPENAI_API_KEY` — required for Modules 1, 4, 5 (LLM-driven planning and writing)
- `COPYLEAKS_EMAIL` and `COPYLEAKS_API_KEY` — required for Module 6 (plagiarism scoring)

## Running

The artifact runs automatically via the `MedRAS Web` workflow. It can be reached at the workspace preview root (`/`).

- Local API: `http://localhost:80/api/healthz`
- Local UI: `http://localhost:80/`

## Operational Rules

- **Never log document content.** Logging is restricted to operational metadata only (route, status, duration, sizes, error types).
- **Never expose API keys to the frontend.** `/api/readyz` returns booleans only.
- **Statistical computation is library-backed.** No statistics may be computed by LLMs.
- **Files are processed in memory.** No uploaded document is written to disk.
