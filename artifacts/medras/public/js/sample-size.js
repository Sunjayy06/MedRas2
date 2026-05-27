/**
 * MedRAS — Sample Size Calculator (frontend flow).
 *
 * Three-step flow:
 *   1. Researcher enters an objective; we POST it to /api/sample-size/analyze
 *      to detect group count and suggest a formula. The researcher can accept
 *      or override.
 *   2. We render the parameter form for the selected formula, plus the
 *      shared statistical assumptions (alpha, power, dropout) and an optional
 *      "expected sample size" target.
 *   3. We POST to /api/sample-size/calculate and render the breakdown.
 */
(function () {
  "use strict";

  // -----------------------------------------------------------------------
  // Formula schema — what each formula needs from the researcher.
  // -----------------------------------------------------------------------

  // -----------------------------------------------------------------------
  // Per-formula dropout-display rule (CHANGE 6).
  //   "show"   → render the existing dropout select normally
  //   "hide"   → never show the dropout select (single-timepoint or
  //              estimation-only formulas)
  //   "rename:experimental_failure" → show but relabel to "Expected
  //              experimental failure rate (%)" (in-vitro)
  //   "rename:animal_loss" → relabel to "Expected animal loss (%)" (in-vivo)
  // Defaults to "show" if not set.
  // -----------------------------------------------------------------------
  var DROPOUT_RULES = {
    single_proportion: "show",
    single_mean: "show",
    two_proportions: "show",
    two_means: "show",
    paired_means: "show",
    anova_means: "show",
    repeated_measures: "show",
    repeated_measures_anova: "show",
    linear_regression: "show",
    prediction_model: "show",
    correlation: "hide",
    survival_logrank: "show",
    kappa_agreement: "hide",
    roc_auc: "hide",
    diagnostic_accuracy: "hide",
    icc: "hide",
    bayesian_credible: "show",
    non_inferiority: "show",
    equivalence: "show",
  };

  var FORMULAS = {
    single_proportion: {
      label: "Single proportion (one-sample prevalence)",
      expression: "n = Z²(α/2) × p × (1 − p) / d²",
      usesPower: false,
      fields: [
        {
          key: "p",
          label: "Expected proportion (p)",
          help: "Anticipated prevalence or rate, e.g., 0.30 for 30%.",
          type: "number", min: 0.001, max: 0.999, step: 0.01, placeholder: "e.g., 0.30",
        },
        {
          key: "precision",
          label: "Absolute precision / margin of error (d)",
          help: "Acceptable distance from the true proportion, e.g., 0.05 for ±5%.",
          type: "number", min: 0.001, max: 0.499, step: 0.01, placeholder: "e.g., 0.05",
        },
      ],
    },
    single_mean: {
      label: "Single mean (one-sample, continuous)",
      expression: "n = (Z(α/2) × σ / d)²",
      usesPower: false,
      fields: [
        {
          key: "sigma",
          label: "Standard deviation (σ)",
          help: "Estimated SD of the outcome in the population.",
          type: "number", min: 0.0001, step: 0.1, placeholder: "e.g., 12",
        },
        {
          key: "precision",
          label: "Absolute precision (d)",
          help: "Acceptable margin around the mean.",
          type: "number", min: 0.0001, step: 0.1, placeholder: "e.g., 2",
        },
      ],
    },
    two_proportions: {
      label: "Two independent proportions",
      expression: "n/group = [Z(α/2)·√(2·p̄·q̄) + Z(β)·√(p1·q1 + p2·q2)]² / (p1 − p2)²",
      usesPower: true,
      fields: [
        {
          key: "p1",
          label: "Proportion in group 1 (p₁)",
          help: "E.g., cure rate in the treatment arm, as a decimal.",
          type: "number", min: 0.001, max: 0.999, step: 0.01, placeholder: "e.g., 0.70",
        },
        {
          key: "p2",
          label: "Proportion in group 2 (p₂)",
          help: "E.g., cure rate in the control arm, as a decimal.",
          type: "number", min: 0.001, max: 0.999, step: 0.01, placeholder: "e.g., 0.55",
        },
      ],
    },
    two_means: {
      label: "Two independent means",
      expression: "n/group = 2·σ²·(Z(α/2) + Z(β))² / (μ1 − μ2)²",
      usesPower: true,
      fields: [
        {
          key: "mean1",
          label: "Mean in group 1 (μ₁)",
          type: "number", step: 0.1, placeholder: "e.g., 130",
        },
        {
          key: "mean2",
          label: "Mean in group 2 (μ₂)",
          type: "number", step: 0.1, placeholder: "e.g., 122",
        },
        {
          key: "sigma",
          label: "Common standard deviation (σ)",
          help: "Assumed equal across both groups.",
          type: "number", min: 0.0001, step: 0.1, placeholder: "e.g., 15",
        },
      ],
    },
    paired_means: {
      label: "Paired means (before–after / matched)",
      expression: "n = (Z(α/2) + Z(β))² · σ_d² / Δ²",
      usesPower: true,
      fields: [
        {
          key: "mean_diff",
          label: "Expected mean difference (Δ)",
          help: "Mean change before vs after, or between matched pairs.",
          type: "number", step: 0.1, placeholder: "e.g., 5",
        },
        {
          key: "sigma_diff",
          label: "SD of differences (σ_d)",
          type: "number", min: 0.0001, step: 0.1, placeholder: "e.g., 12",
        },
      ],
    },
    anova_means: {
      label: "One-way ANOVA (≥3 groups)",
      expression: "n/group ≈ (Z(α/2) + Z(β))² / (k·f²) + 1",
      usesPower: true,
      fields: [
        {
          key: "k",
          label: "Number of groups (k)",
          type: "number", min: 3, max: 20, step: 1, placeholder: "e.g., 3",
        },
        {
          key: "effect_size_f",
          label: "Cohen's f (effect size)",
          help: "Conventions: small = 0.10, medium = 0.25, large = 0.40.",
          type: "number", min: 0.01, max: 2, step: 0.01, placeholder: "e.g., 0.25",
        },
      ],
    },
    repeated_measures: {
      label: "Two-group longitudinal (repeated measures)",
      expression: "n/group = 2·σ²·(Z(α/2) + Z(β))²·(1 + (m−1)·ρ) / (m·Δ²)",
      usesPower: true,
      fields: [
        {
          key: "mean1",
          label: "Mean in group 1 (μ₁)",
          help: "Expected mean across the m timepoints in group 1.",
          type: "number", step: 0.1, placeholder: "e.g., 130",
        },
        {
          key: "mean2",
          label: "Mean in group 2 (μ₂)",
          help: "Expected mean across the m timepoints in group 2.",
          type: "number", step: 0.1, placeholder: "e.g., 122",
        },
        {
          key: "sigma",
          label: "Standard deviation (σ)",
          help: "Outcome SD at any single timepoint (assumed equal across timepoints and groups).",
          type: "number", min: 0.0001, step: 0.1, placeholder: "e.g., 15",
        },
        {
          key: "rho",
          label: "Within-subject correlation (ρ)",
          help: "Correlation between repeated measurements on the same subject (0 = independent, 1 = perfect).",
          type: "number", min: 0, max: 0.999, step: 0.05, placeholder: "e.g., 0.50",
        },
        {
          key: "m_timepoints",
          label: "Number of timepoints (m)",
          help: "How many times each subject is measured. Must be ≥ 2.",
          type: "number", min: 2, max: 50, step: 1, placeholder: "e.g., 4",
        },
      ],
    },
    linear_regression: {
      label: "Multiple linear regression (R²)",
      expression: "n = (Z(α/2) + Z(β))²·(1−R²)/R² + p + 1",
      usesPower: true,
      fields: [
        {
          key: "r_squared",
          label: "Expected R² (proportion of variance explained)",
          help: "Cohen's f² conventions: small = 0.02 (R²≈0.02), medium = 0.15 (R²≈0.13), large = 0.35 (R²≈0.26).",
          type: "number", min: 0.001, max: 0.999, step: 0.01, placeholder: "e.g., 0.13",
        },
        {
          key: "predictors",
          label: "Number of predictors (p)",
          help: "Number of independent variables in the model.",
          type: "number", min: 1, max: 100, step: 1, placeholder: "e.g., 4",
        },
      ],
    },
    prediction_model: {
      label: "Clinical prediction model (events per variable)",
      expression: "n = ceil(EPV × predictors / event_rate)",
      usesPower: false,
      usesAlpha: false,
      fields: [
        {
          key: "predictors",
          label: "Number of candidate predictors",
          help: "How many variables you intend to consider for the model.",
          type: "number", min: 1, max: 100, step: 1, placeholder: "e.g., 8",
        },
        {
          key: "event_rate",
          label: "Expected event rate",
          help: "Proportion of participants expected to have the outcome (e.g., 0.20 for 20%).",
          type: "number", min: 0.001, max: 0.999, step: 0.01, placeholder: "e.g., 0.20",
        },
        {
          key: "epv_target",
          label: "Events per variable (EPV target)",
          help: "Conservatism: 5 = liberal, 10 = standard (Peduzzi et al. 1996), 20 = strict.",
          type: "number", min: 1, max: 100, step: 1, placeholder: "e.g., 10",
        },
      ],
    },
    kappa_agreement: {
      label: "Cohen's κ (inter-rater agreement)",
      expression: "n = Z(α/2)² · κ(1−κ) / d²",
      usesPower: false,
      fields: [
        {
          key: "expected_kappa",
          label: "Expected κ",
          help: "Anticipated agreement level (0–1). Landis & Koch: 0.41–0.6 moderate, 0.61–0.8 substantial.",
          type: "number", min: 0.001, max: 0.999, step: 0.01, placeholder: "e.g., 0.70",
        },
        {
          key: "precision",
          label: "Absolute precision / CI half-width (d)",
          help: "Acceptable distance from the true κ, e.g., 0.10 for ±0.10.",
          type: "number", min: 0.001, max: 0.499, step: 0.01, placeholder: "e.g., 0.10",
        },
      ],
    },
    roc_auc: {
      label: "Diagnostic test ROC / AUC",
      expression: "n_cases solves d² = Z(α/2)²·Var(AUC) [Hanley & McNeil 1982]",
      usesPower: false,
      fields: [
        {
          key: "auc",
          label: "Expected AUC",
          help: "Anticipated area under the ROC curve (between 0.5 and 1).",
          type: "number", min: 0.51, max: 0.999, step: 0.01, placeholder: "e.g., 0.80",
        },
        {
          key: "case_ratio",
          label: "Controls per case (k)",
          help: "How many non-diseased subjects per diseased subject (1 = balanced).",
          type: "number", min: 0.1, max: 20, step: 0.1, placeholder: "e.g., 1",
        },
        {
          key: "precision",
          label: "Absolute precision / CI half-width for AUC (d)",
          help: "How tight a confidence interval you want around the AUC, e.g., 0.05 for ±0.05.",
          type: "number", min: 0.005, max: 0.499, step: 0.005, placeholder: "e.g., 0.05",
        },
      ],
    },
    correlation: {
      label: "Pearson correlation (Fisher's z)",
      expression: "n = ((Z(α/2) + Z(β)) / arctanh(r))² + 3",
      usesPower: true,
      fields: [
        {
          key: "expected_r",
          label: "Expected correlation (r)",
          help: "Cohen 1988: small ≈ 0.10, medium ≈ 0.30, large ≈ 0.50. Sign is ignored.",
          type: "number", min: -0.99, max: 0.99, step: 0.05, placeholder: "e.g., 0.30",
        },
      ],
    },
    repeated_measures_anova: {
      label: "Repeated-measures ANOVA (k groups × m timepoints)",
      expression: "n/group = (Z(α/2) + Z(β))² · (1 − ρ) / (m · f²) + 1",
      usesPower: true,
      fields: [
        {
          key: "k_groups",
          label: "Number of groups (k)",
          help: "How many independent treatment arms.",
          type: "number", min: 2, max: 20, step: 1, placeholder: "e.g., 2",
        },
        {
          key: "m_timepoints",
          label: "Number of timepoints (m)",
          help: "How many times each subject is measured (≥ 2).",
          type: "number", min: 2, max: 50, step: 1, placeholder: "e.g., 3",
        },
        {
          key: "rho",
          label: "Within-subject correlation (ρ)",
          help: "Correlation across repeated measurements (0 = independent, 1 = perfect). Typical: 0.5.",
          type: "number", min: 0, max: 0.999, step: 0.05, placeholder: "e.g., 0.50",
        },
        {
          key: "effect_size_f",
          label: "Cohen's f (between-group effect)",
          help: "Conventions: small = 0.10, medium = 0.25, large = 0.40.",
          type: "number", min: 0.01, max: 2, step: 0.01, placeholder: "e.g., 0.25",
        },
      ],
    },
    survival_logrank: {
      label: "Survival — two-group log-rank (Schoenfeld 1983)",
      expression:
        "events = (Z(α/2)+Z(β))² / (p_a·p_b·(ln HR)²);  n = events / event_rate",
      usesPower: true,
      fields: [
        {
          key: "hazard_ratio",
          label: "Expected hazard ratio (HR)",
          help: "HR < 1 = treatment protective; HR > 1 = harmful. Must be ≠ 1.",
          type: "number", min: 0.05, max: 20, step: 0.05, placeholder: "e.g., 0.70",
        },
        {
          key: "overall_event_rate",
          label: "Expected overall event rate",
          help: "Proportion of all enrolled subjects expected to have the event during follow-up.",
          type: "number", min: 0.01, max: 1, step: 0.05, placeholder: "e.g., 0.40",
        },
        {
          key: "allocation_ratio",
          label: "Allocation ratio (k = n_b / n_a)",
          help: "1 = balanced randomisation; 2 = twice as many in arm B.",
          type: "number", min: 0.1, max: 10, step: 0.1, placeholder: "e.g., 1",
        },
      ],
    },
    // ---------------------------------------------------------------------
    // CHANGE 7 — Five new formulas computed entirely on the client.
    // These do NOT call the backend; clientCompute(...) returns a response
    // shaped like the API response so the existing renderResult pipeline
    // works unchanged.
    // ---------------------------------------------------------------------
    non_inferiority: {
      label: "Non-inferiority trial (continuous outcome)",
      expression: "n/group = 2·σ²·(Z(α) + Z(β))² / (δ + M)²",
      usesPower: true,
      clientCompute: true,
      fields: [
        { key: "ni_margin", label: "Non-inferiority margin (M)", help: "Largest acceptable inferiority of new vs standard, in original units. Use one-sided α (typically 0.025).", type: "number", min: 0.0001, step: 0.1, placeholder: "e.g., 5" },
        { key: "true_diff", label: "Expected true difference (δ)", help: "Anticipated difference favouring the new treatment (often 0). Must be > −M.", type: "number", step: 0.1, placeholder: "e.g., 0" },
        { key: "sigma", label: "Common standard deviation (σ)", type: "number", min: 0.0001, step: 0.1, placeholder: "e.g., 15" },
      ],
    },
    equivalence: {
      label: "Equivalence trial (TOST)",
      expression: "n/group = 2·σ²·(Z(α) + Z(β/2))² / (M − |δ|)²",
      usesPower: true,
      clientCompute: true,
      fields: [
        { key: "eq_margin", label: "Equivalence margin (M)", help: "Symmetric margin; both arms differ by less than ±M to declare equivalence.", type: "number", min: 0.0001, step: 0.1, placeholder: "e.g., 5" },
        { key: "true_diff", label: "Expected true difference (δ)", help: "Anticipated absolute difference between treatments. Must be < M.", type: "number", step: 0.1, placeholder: "e.g., 0" },
        { key: "sigma", label: "Common standard deviation (σ)", type: "number", min: 0.0001, step: 0.1, placeholder: "e.g., 15" },
      ],
    },
    diagnostic_accuracy: {
      label: "Diagnostic accuracy (sensitivity/specificity)",
      expression: "n_cases = Z(α/2)² · Se(1−Se) / d²;  n_controls = Z(α/2)² · Sp(1−Sp) / d²",
      usesPower: false,
      clientCompute: true,
      fields: [
        { key: "sensitivity", label: "Expected sensitivity (Se)", type: "number", min: 0.01, max: 0.999, step: 0.01, placeholder: "e.g., 0.90" },
        { key: "specificity", label: "Expected specificity (Sp)", type: "number", min: 0.01, max: 0.999, step: 0.01, placeholder: "e.g., 0.85" },
        { key: "precision", label: "Margin of error (d, ±)", type: "number", min: 0.005, max: 0.2, step: 0.005, placeholder: "e.g., 0.05" },
        { key: "prevalence", label: "Disease prevalence", help: "Used to scale total n: n_total = max(n_cases / prev, n_controls / (1 − prev)).", type: "number", min: 0.001, max: 0.999, step: 0.01, placeholder: "e.g., 0.20" },
      ],
    },
    icc: {
      label: "Intraclass Correlation Coefficient (ICC)",
      expression: "n = 1 + 2·(Z(α/2)+Z(β))²·(1−ρ₀)²·(1+(k−1)ρ₁)² / (k(k−1)·(ρ₁ − ρ₀)²)  [Bonett 2002]",
      usesPower: true,
      clientCompute: true,
      fields: [
        { key: "rho0", label: "Null ICC (ρ₀)", help: "Lowest acceptable agreement.", type: "number", min: 0, max: 0.99, step: 0.05, placeholder: "e.g., 0.40" },
        { key: "rho1", label: "Alternative ICC (ρ₁)", help: "Anticipated true agreement (must be > ρ₀).", type: "number", min: 0.01, max: 0.999, step: 0.05, placeholder: "e.g., 0.70" },
        { key: "raters", label: "Number of raters / repeated measurements (k)", type: "number", min: 2, max: 20, step: 1, placeholder: "e.g., 3" },
      ],
    },
    bayesian_credible: {
      label: "Bayesian sample size (credible-interval width)",
      expression: "n = (Z(α/2) · σ_post / w)²  with normal–normal conjugate prior",
      usesPower: false,
      clientCompute: true,
      fields: [
        { key: "sigma", label: "Likelihood standard deviation (σ)", type: "number", min: 0.0001, step: 0.1, placeholder: "e.g., 15" },
        { key: "prior_sigma", label: "Prior standard deviation (σ₀)", help: "Larger σ₀ = weaker prior. Use 1e6 for an essentially flat prior.", type: "number", min: 0.0001, step: 0.1, placeholder: "e.g., 30" },
        { key: "ci_halfwidth", label: "Desired credible-interval half-width (w)", type: "number", min: 0.0001, step: 0.1, placeholder: "e.g., 2" },
      ],
    },
  };

  // -----------------------------------------------------------------------
  // DEFAULTS — sensible reference values used to:
  //   (1) auto-fill blank inputs in FORWARD mode on submit
  //   (2) silently fill non-structural reference params in REVERSE n-only mode
  // Keys must match the FORMULAS[*].fields[*].key.
  // -----------------------------------------------------------------------

  var DEFAULTS = {
    single_proportion: { p: 0.5, precision: 0.05 },
    single_mean: { sigma: 1, precision: 0.1 },
    two_proportions: { p1: 0.5, p2: 0.65 },
    two_means: { mean1: 0, mean2: 0.5, sigma: 1 },
    paired_means: { mean_diff: 0.5, sigma_diff: 1 },
    anova_means: { k: 3, effect_size_f: 0.25 },
    repeated_measures: { mean1: 0, mean2: 0.5, sigma: 1, rho: 0.5, m_timepoints: 3 },
    linear_regression: { r_squared: 0.13, predictors: 4 },
    prediction_model: { predictors: 8, event_rate: 0.20, epv_target: 10 },
    kappa_agreement: { expected_kappa: 0.7, precision: 0.1 },
    roc_auc: { auc: 0.75, case_ratio: 1, precision: 0.05 },
    correlation: { expected_r: 0.3 },
    repeated_measures_anova: {
      k_groups: 2, m_timepoints: 3, rho: 0.5, effect_size_f: 0.25,
    },
    survival_logrank: {
      hazard_ratio: 0.7, overall_event_rate: 0.4, allocation_ratio: 1,
    },
    non_inferiority: { ni_margin: 5, true_diff: 0, sigma: 15 },
    equivalence: { eq_margin: 5, true_diff: 0, sigma: 15 },
    diagnostic_accuracy: {
      sensitivity: 0.9, specificity: 0.85, precision: 0.05, prevalence: 0.2,
    },
    icc: { rho0: 0.4, rho1: 0.7, raters: 3 },
    bayesian_credible: { sigma: 15, prior_sigma: 30, ci_halfwidth: 2 },
  };

  // -----------------------------------------------------------------------
  // WHY_DEFAULTS — short justification for each auto-fillable parameter
  // (CHANGE 3 "Auto-filled defaults" table). Keyed by field key OR by
  // "<formula>.<field>" if a formula needs an override.
  // -----------------------------------------------------------------------
  var WHY_DEFAULTS = {
    alpha: "Standard type I error rate (95% confidence)",
    power: "Minimum acceptable power",
    dropout: "Typical outpatient study attrition",
    p: "Worst-case proportion (maximises required n)",
    p1: "Conservative starting estimate",
    p2: "Conservative starting estimate",
    sigma: "Conservative SD pending pilot data",
    sigma_diff: "Conservative SD of paired differences",
    mean1: "Reference baseline",
    mean2: "Reference baseline",
    mean_diff: "Small-to-medium effect size",
    rho: "Typical within-subject correlation",
    expected_r: "Cohen 1988 medium effect",
    expected_kappa: "Substantial agreement (Landis & Koch)",
    auc: "Conventionally good test (AUC 0.75)",
    case_ratio: "Balanced case-control design",
    r_squared: "Cohen f² medium effect",
    event_rate: "Common-event scenario",
    epv_target: "Peduzzi 1996 standard",
    overall_event_rate: "Moderate-event scenario",
    hazard_ratio: "Clinically relevant treatment effect",
    allocation_ratio: "Balanced randomisation",
    effect_size_f: "Cohen 1988 medium effect",
    precision: "Conventional ±5% precision",
    predictors: "Typical multivariable model size",
    k: "Smallest k that requires ANOVA",
    m_timepoints: "Common longitudinal design",
    k_groups: "Two-arm trial",
    ni_margin: "Common non-inferiority margin",
    eq_margin: "Common equivalence margin",
    true_diff: "Null assumption (no true difference)",
    sensitivity: "High-performing test target",
    specificity: "High-performing test target",
    prevalence: "Moderate-prevalence condition",
    rho0: "Lowest acceptable agreement",
    rho1: "Substantial agreement target",
    raters: "Typical 3-rater study",
    prior_sigma: "Weakly informative prior",
    ci_halfwidth: "Conventional precision",
  };

  // Human-readable labels for reference params shown in the "defaults used"
  // panel during n-only reverse mode.
  var DEFAULT_LABELS = {
    p: "Expected proportion (p)",
    p1: "Proportion in group 1 (p₁)",
    p2: "Proportion in group 2 (p₂)",
    sigma: "Standard deviation (σ)",
    sigma_diff: "SD of differences (σ_d)",
    mean1: "Mean in group 1 (μ₁)",
    mean2: "Mean in group 2 (μ₂)",
    mean_diff: "Expected mean difference (Δ)",
    rho: "Within-subject correlation (ρ)",
    expected_r: "Expected correlation (r)",
    expected_kappa: "Expected κ",
    auc: "Expected AUC",
    case_ratio: "Controls per case (k)",
    r_squared: "Expected R²",
    event_rate: "Expected event rate",
    epv_target: "Events per variable (EPV)",
    overall_event_rate: "Expected overall event rate",
    hazard_ratio: "Hazard ratio (HR)",
    allocation_ratio: "Allocation ratio",
    effect_size_f: "Cohen's f",
    precision: "Precision (d)",
  };

  // -----------------------------------------------------------------------
  // App state
  // -----------------------------------------------------------------------

  var state = {
    objective: "",
    selectedFormula: null,
    lastAnalysis: null,
    reverseMode: false, // only meaningful when selectedFormula === 'two_proportions'
    lastResult: null,   // most recent /calculate or /reverse response (for the
                        // downloadable report)
  };

  // -----------------------------------------------------------------------
  // IDEAL_FOR — plain-language description of when each formula is the
  // statistically appropriate choice. Used by the "Recommended statistical
  // formula" callout on Step 3 so the researcher always sees, in their own
  // words, why this formula fits their study.
  // -----------------------------------------------------------------------
  var IDEAL_FOR = {
    single_proportion:
      "Estimating a single prevalence or rate in one population " +
      "(e.g., the proportion of adults with hypertension) to a desired " +
      "absolute precision.",
    single_mean:
      "Estimating a single population mean of a continuous outcome " +
      "(e.g., mean systolic blood pressure) to a desired precision.",
    two_proportions:
      "Comparing the prevalence/cure/event rate between TWO independent " +
      "groups (e.g., treatment vs control) where the outcome is binary.",
    two_means:
      "Comparing the mean of a continuous outcome between TWO independent " +
      "groups, when both groups are measured once and assumed to share a " +
      "common SD.",
    paired_means:
      "Detecting a within-subject change on a continuous outcome — " +
      "before/after, matched pairs, or crossover designs.",
    anova_means:
      "Comparing the means of a continuous outcome across THREE or more " +
      "independent groups in a one-way design.",
    repeated_measures:
      "Two-arm longitudinal study where the same subjects are measured " +
      "at multiple timepoints; uses the within-subject correlation to " +
      "reduce the required n.",
    repeated_measures_anova:
      "Mixed (between × within) design with k groups measured across m " +
      "timepoints — tests for a time × group interaction.",
    correlation:
      "Estimating or detecting a Pearson correlation between two " +
      "continuous variables in one sample.",
    survival_logrank:
      "Two-arm time-to-event study (e.g., overall survival, " +
      "progression-free survival) compared with the log-rank test under " +
      "proportional hazards.",
    linear_regression:
      "Multiple linear regression where you want enough power to detect " +
      "the model's overall R² with the planned number of predictors.",
    prediction_model:
      "Building a clinical prediction model — sizes the dataset using the " +
      "events-per-variable rule (Peduzzi 1996) instead of α/β.",
    kappa_agreement:
      "Estimating Cohen's κ for inter-rater agreement on a categorical " +
      "outcome with a desired CI half-width around κ.",
    roc_auc:
      "Diagnostic accuracy study — estimating the AUC of a single test " +
      "with a desired CI half-width (Hanley & McNeil 1982).",
    non_inferiority:
      "Non-inferiority trial — proving a new treatment is not unacceptably " +
      "worse than the standard by more than a pre-specified margin M.",
    equivalence:
      "Equivalence (TOST) trial — proving two treatments differ by less " +
      "than ±M (typical for bioequivalence and biosimilar studies).",
    diagnostic_accuracy:
      "Estimating the sensitivity and specificity of a binary diagnostic " +
      "test with a desired absolute precision; total n is scaled by " +
      "disease prevalence.",
    icc:
      "Estimating an Intraclass Correlation Coefficient against a null " +
      "value — used for inter-rater or test-retest reliability with " +
      "k raters/measurements per subject.",
    bayesian_credible:
      "Bayesian sample size by precision — sizes n so the posterior 95% " +
      "credible interval has a desired half-width, given a normal-normal " +
      "conjugate prior.",
  };

  // -----------------------------------------------------------------------
  // Boot
  // -----------------------------------------------------------------------

  document.addEventListener("DOMContentLoaded", function () {
    bindStep0();
    bindCardA();
    bindCardC();
    bindStep1();
    bindStep2();
    bindStep3();
  });

  // -----------------------------------------------------------------------
  // CHANGE 2 — client-side objective parser. Pure regex; no API call.
  // Returns: { flags: {...}, formula: <key|null>, chips: [...] }
  // -----------------------------------------------------------------------

  function objectiveParser(text) {
    var t = String(text || "").toLowerCase();
    var flags = {
      groups: 1,
      compare: false,
      outcome: null,           // "binary" | "continuous" | "time-to-event" | "agreement" | "diagnostic" | null
      longitudinal: false,
      genetic: false,
      complexity: "simple",    // "simple" | "complex"
      design: null,            // "non_inferiority" | "equivalence" | null
      survey: false,
      paired: false,
    };

    // Comparison keywords
    var twoCompare = /\b(compare|vs\.?|versus|between|control vs|treatment vs|cases vs)\b/;
    var threePlus  = /\b(three|four|five|multiple)\b.*\b(groups?|arms?)\b|\b(anova|three-?arm|three arms|four arms)\b/;
    if (twoCompare.test(t)) { flags.compare = true; flags.groups = 2; }
    if (threePlus.test(t))  { flags.compare = true; flags.groups = 3; }
    var nGroupsMatch = t.match(/\b([2-9])\s*(?:arms?|groups?)\b/);
    if (nGroupsMatch) { flags.compare = true; flags.groups = Math.max(flags.groups, parseInt(nGroupsMatch[1], 10)); }

    // Paired / before-after / crossover
    if (/\b(before[- ]?after|pre[- ]?post|paired|matched|crossover|change from baseline|within[- ]subject)\b/.test(t)) {
      flags.paired = true;
    }

    // Outcome type
    if (/\b(prevalence|proportion|incidence|cure rate|response rate|positive|infection rate|mortality rate|seropositive|seroprevalence)\b/.test(t)) {
      flags.outcome = "binary";
    }
    if (/\b(mean|average|level|score|hba1c|blood pressure|systolic|diastolic|cholesterol|continuous|change in)\b/.test(t)) {
      flags.outcome = flags.outcome || "continuous";
    }
    if (/\b(survival|time[- ]to[- ]event|progression[- ]free|hazard|kaplan[- ]?meier|log[- ]?rank|overall survival|pfs)\b/.test(t)) {
      flags.outcome = "time-to-event";
    }
    if (/\b(agreement|kappa|inter[- ]?rater|intra[- ]?rater|reliability|icc)\b/.test(t)) {
      flags.outcome = "agreement";
    }
    if (/\b(sensitivity|specificity|diagnostic accuracy|roc|auc|positive predictive value|ppv|npv)\b/.test(t)) {
      flags.outcome = "diagnostic";
    }

    // Longitudinal / repeated measures
    if (/\b(longitudinal|repeated measures|over time|follow[- ]?up|months?|weeks?|timepoints?|6 months|12 months|baseline and|cohort)\b/.test(t)) {
      flags.longitudinal = true;
    }

    // Genetic
    if (/\b(snp|gwas|genom(e|ic)|genotype|allele|polymorphism|gene |genetic|hla|haplotype|pharmacogenom|carrier|linkage)\b/.test(t)) {
      flags.genetic = true;
    }

    // Survey / cross-sectional / prevalence-only
    if (/\b(survey|cross[- ]?sectional|kap study|knowledge attitude|questionnaire|prevalence study|seroprevalence)\b/.test(t)) {
      flags.survey = true;
    }

    // Trial design
    if (/\b(non[- ]?inferiority|noninferiority)\b/.test(t)) flags.design = "non_inferiority";
    if (/\b(equivalence|bioequivalence|biosimilar)\b/.test(t)) flags.design = "equivalence";

    // Complexity heuristic
    var complexHits = 0;
    if (/\b(multicent(re|er)|multi[- ]?site|multi[- ]?arm)\b/.test(t)) complexHits++;
    if (/\b(adaptive|interim|group sequential)\b/.test(t)) complexHits++;
    if (/\b(composite (primary )?outcome|primary outcomes?)\b/.test(t) && /\b(and|,)\b/.test(t)) complexHits++;
    if (flags.longitudinal && flags.compare) complexHits++;
    if (complexHits >= 2) flags.complexity = "complex";

    // Routing priority table
    var formula = null;
    if (flags.genetic) {
      formula = null; // routed via genetic engine
    } else if (flags.design === "non_inferiority") {
      formula = "non_inferiority";
    } else if (flags.design === "equivalence") {
      formula = "equivalence";
    } else if (flags.outcome === "time-to-event") {
      formula = "survival_logrank";
    } else if (flags.outcome === "diagnostic") {
      formula = "diagnostic_accuracy";
    } else if (flags.outcome === "agreement") {
      // ICC for continuous, kappa for categorical
      formula = /\bcontinuous|measur(e|ement)\b/.test(t) ? "icc" : "kappa_agreement";
    } else if (flags.longitudinal && flags.compare && flags.groups >= 3) {
      formula = "repeated_measures_anova";
    } else if (flags.longitudinal && flags.compare) {
      formula = "repeated_measures";
    } else if (flags.compare && flags.groups >= 3) {
      formula = "anova_means";
    } else if (flags.compare && flags.outcome === "binary") {
      formula = "two_proportions";
    } else if (flags.compare && (flags.outcome === "continuous" || flags.outcome === null)) {
      formula = flags.paired ? "paired_means" : "two_means";
    } else if (flags.outcome === "binary") {
      formula = "single_proportion";
    } else if (flags.outcome === "continuous") {
      formula = "single_mean";
    } else if (flags.survey) {
      formula = "single_proportion";
    } else if (/\bcorrelat/.test(t)) {
      formula = "correlation";
    }

    // Build human-readable chips
    var chips = [];
    if (flags.compare) chips.push((flags.groups || 2) + " groups");
    else chips.push("single group");
    if (flags.outcome) chips.push(flags.outcome + " outcome");
    if (flags.longitudinal) chips.push("longitudinal");
    if (flags.paired) chips.push("paired/within-subject");
    if (flags.genetic) chips.push("genetic study");
    if (flags.design) chips.push(flags.design.replace("_", "-"));
    if (flags.complexity === "complex") chips.push("complex design");
    if (flags.survey) chips.push("survey/cross-sectional");

    return { flags: flags, formula: formula, chips: chips };
  }

  // -----------------------------------------------------------------------
  // CHANGE 7 — client-side compute helpers (pure JS, no backend).
  // Each returns a response object compatible with the existing
  // renderResult() pipeline.
  // -----------------------------------------------------------------------

  function zFromAlpha(alpha, oneSided) {
    // Two-sided unless oneSided===true
    var p = oneSided ? 1 - alpha : 1 - alpha / 2;
    return inverseNormalCdf(p);
  }
  function zFromPower(power) { return inverseNormalCdf(power); }

  // Beasley-Springer-Moro inverse-normal CDF (good to ~7 decimals).
  function inverseNormalCdf(p) {
    if (p <= 0 || p >= 1) {
      if (p === 0) return -Infinity;
      if (p === 1) return Infinity;
      return NaN;
    }
    var a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00];
    var b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01];
    var c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00];
    var d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00];
    var pLow = 0.02425, pHigh = 1 - pLow, q, r;
    if (p < pLow) {
      q = Math.sqrt(-2 * Math.log(p));
      return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
        ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
    }
    if (p <= pHigh) {
      q = p - 0.5; r = q * q;
      return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
        (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
    }
    q = Math.sqrt(-2 * Math.log(1 - p));
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }

  function _ceil(x) { return Math.ceil(x); }

  function clientComputeForward(formula, params) {
    var alpha = params.alpha != null ? params.alpha : 0.05;
    var power = params.power != null ? params.power : 0.8;
    var dropout = params.dropout != null ? params.dropout : 0;
    var spec = FORMULAS[formula];
    var nPerGroup = 0, totalN = 0, numGroups = 1;
    var notes = [], constants = {};

    if (formula === "non_inferiority") {
      // One-sided α (regulatory standard)
      var Za = zFromAlpha(alpha, true);
      var Zb = zFromPower(power);
      var sigma = params.sigma;
      var M = params.ni_margin;
      var delta = params.true_diff;
      var denom = (delta + M);
      if (denom <= 0) {
        throw new Error("Non-inferiority requires δ + M > 0 (true effect must be better than the negative margin).");
      }
      nPerGroup = _ceil(2 * sigma * sigma * Math.pow(Za + Zb, 2) / (denom * denom));
      numGroups = 2;
      totalN = nPerGroup * 2;
      constants = { Z_alpha_one_sided: round(Za, 4), Z_beta: round(Zb, 4), effect_minus_margin: round(denom, 4) };
      notes.push("Non-inferiority uses one-sided α = " + alpha + " (regulatory convention).");
      notes.push("Margin (M) = " + M + ";  expected true difference (δ) = " + delta + ".");
    } else if (formula === "equivalence") {
      var Za2 = zFromAlpha(alpha, true);              // TOST: one-sided α each side
      var Zb2 = zFromAlpha(1 - power, true);          // Z(β/2) → use β/2 for two one-sided tests
      Zb2 = zFromPower(1 - (1 - power) / 2);
      var sg = params.sigma;
      var Mq = params.eq_margin;
      var dq = Math.abs(params.true_diff);
      var diff = Mq - dq;
      if (diff <= 0) {
        throw new Error("Equivalence requires |δ| < M (the expected difference must be smaller than the margin).");
      }
      nPerGroup = _ceil(2 * sg * sg * Math.pow(Za2 + Zb2, 2) / (diff * diff));
      numGroups = 2;
      totalN = nPerGroup * 2;
      constants = { Z_alpha_one_sided: round(Za2, 4), Z_beta_over_2: round(Zb2, 4), margin_minus_abs_diff: round(diff, 4) };
      notes.push("TOST uses one-sided α = " + alpha + " on EACH side of the symmetric ±M margin.");
    } else if (formula === "diagnostic_accuracy") {
      var Z = zFromAlpha(alpha, false);
      var Se = params.sensitivity, Sp = params.specificity, d = params.precision, prev = params.prevalence;
      var nCases    = _ceil(Z * Z * Se * (1 - Se) / (d * d));
      var nControls = _ceil(Z * Z * Sp * (1 - Sp) / (d * d));
      // Total n constrained by prevalence: need enough total so that
      //   prev * total ≥ nCases  AND  (1-prev)*total ≥ nControls
      var tFromCases    = Math.ceil(nCases / prev);
      var tFromControls = Math.ceil(nControls / (1 - prev));
      totalN = Math.max(tFromCases, tFromControls);
      numGroups = 1;
      nPerGroup = totalN;
      constants = {
        Z_alpha_over_2: round(Z, 4),
        n_cases_required: nCases,
        n_controls_required: nControls,
        scaled_by_prevalence: prev,
      };
      notes.push("n_cases needed for sensitivity CI ±" + d + " = " + nCases + ".");
      notes.push("n_controls needed for specificity CI ±" + d + " = " + nControls + ".");
      notes.push("Total n scaled to prevalence " + prev + " so both case and control counts are met.");
    } else if (formula === "icc") {
      var Zi = zFromAlpha(alpha, false);
      var Zib = zFromPower(power);
      var rho0 = params.rho0, rho1 = params.rho1, k = params.raters;
      if (rho1 <= rho0) throw new Error("ICC requires ρ₁ > ρ₀ (alternative agreement must exceed null).");
      // Walter, Eliasziw & Donner (1998) approximation
      var theta0 = rho0 / (1 - rho0 + 1e-12);
      var theta1 = rho1 / (1 - rho1 + 1e-12);
      // Use Bonett (2002) closed-form approximation:
      //   n = 1 + 2·k·(Z(α/2)+Z(β))²·(1-ρ₀)²·(1+(k-1)ρ₁)² / (k(k-1)·(ρ₁-ρ₀)²)
      var num = 2 * Math.pow(Zi + Zib, 2) * Math.pow(1 - rho0, 2) * Math.pow(1 + (k - 1) * rho1, 2);
      var denomI = k * (k - 1) * Math.pow(rho1 - rho0, 2);
      nPerGroup = _ceil(1 + num / denomI);
      numGroups = 1;
      totalN = nPerGroup;
      constants = { Z_alpha_over_2: round(Zi, 4), Z_beta: round(Zib, 4), raters: k, theta0: round(theta0, 4), theta1: round(theta1, 4) };
      notes.push("Subjects each rated by " + k + " raters; total ratings = " + (nPerGroup * k) + ".");
      notes.push("Approximation: Bonett 2002 (Statistics in Medicine 21:1331-1335).");
    } else if (formula === "bayesian_credible") {
      // Normal-normal conjugate.  Posterior precision = 1/σ₀² + n/σ²
      // Posterior SD = √(1/(1/σ₀² + n/σ²)).  Solve for n given desired
      // half-width w at credibility level (1−α).
      var Zc = zFromAlpha(alpha, false);
      var sigma2 = Math.pow(params.sigma, 2);
      var prior2 = Math.pow(params.prior_sigma, 2);
      var w = params.ci_halfwidth;
      // Want Z·√(1/(1/σ₀² + n/σ²)) ≤ w
      //   → 1/σ₀² + n/σ² ≥ Z²/w²
      //   → n ≥ σ² (Z²/w² − 1/σ₀²)
      var rhs = (Zc * Zc) / (w * w) - 1 / prior2;
      if (rhs <= 0) {
        nPerGroup = 1;
        notes.push("Prior alone already meets the desired half-width — n=1 suffices.");
      } else {
        nPerGroup = _ceil(sigma2 * rhs);
      }
      numGroups = 1;
      totalN = nPerGroup;
      constants = {
        Z_credibility: round(Zc, 4),
        prior_precision: round(1 / prior2, 6),
        likelihood_variance: round(sigma2, 4),
      };
      notes.push("Normal-normal conjugate; posterior 95% credible interval target half-width = " + w + ".");
    } else {
      throw new Error("Unknown client-side formula: " + formula);
    }

    var adjustedN = dropout > 0 && dropout < 1
      ? Math.ceil(totalN / (1 - dropout))
      : totalN;

    // Build response shape compatible with renderResult().
    var inputs = Object.assign({ alpha: alpha, dropout_rate: dropout }, params);
    if (spec.usesPower) inputs.power = power;
    delete inputs.dropout;

    return {
      formula: formula,
      formula_label: spec.label,
      formula_expression: spec.expression,
      n_per_group: nPerGroup,
      number_of_groups: numGroups,
      total_n: totalN,
      adjusted_n: adjustedN,
      inputs: inputs,
      constants: constants,
      notes: notes,
    };
  }

  function round(v, dp) {
    var f = Math.pow(10, dp || 4);
    return Math.round(v * f) / f;
  }

  // -----------------------------------------------------------------------
  // CHANGE 4 — Complex-trial layered pipeline.
  // Takes a baseline result (n_per_group/total_n) and applies, in order:
  //   1. composite-outcome Bonferroni (multiple primary outcomes, with ρ)
  //   2. repeated-measures variance reduction
  //   3. multicentre design-effect inflation (DEFF = 1 + (m-1)·ICC)
  //   4. adaptive-design α-spending penalty
  // Returns { result, layers } where layers is a list of {name, multiplier,
  // n_per_group, total_n} suitable for the layered breakdown table.
  // -----------------------------------------------------------------------
  function applyComplexLayers(baseResult, cx) {
    var layers = [{
      name: "Baseline (statistical formula)",
      adj: "—",
      n_per_group: baseResult.n_per_group,
      total_n: baseResult.total_n,
      multiplier: 1,
    }];
    var nPerGroup = baseResult.n_per_group;
    var totalN = baseResult.total_n;
    // Use the actual study α (not a hardcoded 0.05) so adjustments scale
    // correctly for stricter levels (e.g. 0.01 or GWAS 5e-8).
    var studyAlpha = (baseResult.inputs && baseResult.inputs.alpha != null)
      ? baseResult.inputs.alpha
      : 0.05;

    // 1. Composite outcomes — TRUE Šidák correction with ρ-adjusted m_eff.
    if (cx.outcomes > 1) {
      var k = cx.outcomes;
      var rho = cx.rho_outcomes != null ? cx.rho_outcomes : 0.4;
      // Effective independent tests under correlation ρ (Conneely & Boehnke 2007 approx)
      var effTests = 1 + (k - 1) * (1 - rho);
      // True Šidák: α_per = 1 − (1 − α)^(1/m_eff)
      var alphaPer = 1 - Math.pow(1 - studyAlpha, 1 / effTests);
      var Zbase = zFromAlpha(studyAlpha, false);
      var Zadj  = zFromAlpha(alphaPer,   false);
      var mult = Math.pow(Zadj / Zbase, 2);
      nPerGroup = Math.ceil(nPerGroup * mult);
      totalN    = Math.ceil(totalN * mult);
      layers.push({
        name: "Composite outcomes (k=" + k + ", ρ=" + rho + ", true Šidák)",
        adj: "× " + mult.toFixed(3) +
             "  (m_eff=" + effTests.toFixed(2) +
             ", α_per=" + alphaPer.toExponential(2) + ")",
        n_per_group: nPerGroup, total_n: totalN, multiplier: mult,
      });
    }

    // 2. Repeated measures variance reduction
    if (cx.timepoints > 1) {
      var m = cx.timepoints;
      var rT = cx.rho_time != null ? cx.rho_time : 0.5;
      // Variance-reduction multiplier for paired/RM analysis
      var rmMult = (1 + (m - 1) * rT) / m;
      // RM REDUCES required n
      nPerGroup = Math.max(2, Math.ceil(nPerGroup * rmMult));
      totalN    = Math.max(2, Math.ceil(totalN * rmMult));
      layers.push({
        name: "Repeated measures (m=" + m + ", ρ=" + rT + ")",
        adj: "× " + rmMult.toFixed(3) + "  (efficiency gain)",
        n_per_group: nPerGroup, total_n: totalN, multiplier: rmMult,
      });
    }

    // 3. Multicentre design-effect inflation
    if (cx.multicentre === "yes") {
      var sites = cx.sites || 10;
      var icc = cx.icc != null ? cx.icc : 0.05;
      var avgClusterSize = totalN / sites;
      var DEFF = 1 + (avgClusterSize - 1) * icc;
      if (DEFF < 1) DEFF = 1;
      nPerGroup = Math.ceil(nPerGroup * DEFF);
      totalN    = Math.ceil(totalN * DEFF);
      layers.push({
        name: "Multicentre DEFF (sites=" + sites + ", ICC=" + icc + ")",
        adj: "× " + DEFF.toFixed(3),
        n_per_group: nPerGroup, total_n: totalN, multiplier: DEFF,
      });
    }

    // 4. Adaptive-design α-spending penalty
    if (cx.adaptive === "yes") {
      var interims = cx.interims || 1;
      var penalty = interims === 1 ? 1.05 : interims === 2 ? 1.07 : 1.10;
      nPerGroup = Math.ceil(nPerGroup * penalty);
      totalN    = Math.ceil(totalN * penalty);
      layers.push({
        name: "Adaptive design (" + interims + " interims)",
        adj: "× " + penalty.toFixed(2) + "  (α-spending penalty)",
        n_per_group: nPerGroup, total_n: totalN, multiplier: penalty,
      });
    }

    var dropout = baseResult.inputs && (baseResult.inputs.dropout_rate || 0);
    var adjusted = dropout > 0 && dropout < 1 ? Math.ceil(totalN / (1 - dropout)) : totalN;

    var newResult = Object.assign({}, baseResult, {
      n_per_group: nPerGroup,
      total_n: totalN,
      adjusted_n: adjusted,
    });
    return { result: newResult, layers: layers };
  }

  // -----------------------------------------------------------------------
  // CHANGE 5 — Genetic engine wrapper. Maps a sub-type onto an existing
  // formula with the appropriate α + parameters, then returns the result
  // with a "genetic" tag so renderResult can show the genetic checklist.
  // -----------------------------------------------------------------------
  function geneticEngineSelect(subtype) {
    // Returns { formula, defaultAlpha, lockedAlpha (boolean), notes[] }
    switch (subtype) {
      case "candidate_gene":
        return { formula: "two_proportions", defaultAlpha: 0.05, lockedAlpha: false,
          notes: ["Candidate-gene case-control: standard α = 0.05 with Bonferroni for the number of SNPs tested."] };
      case "gwas":
        return { formula: "two_proportions", defaultAlpha: 5e-8, lockedAlpha: true,
          notes: ["GWAS uses genome-wide significance α = 5×10⁻⁸ to control FWER across ~10⁶ independent SNPs."] };
      case "pharmacogenomic":
        return { formula: "anova_means", defaultAlpha: 0.05, lockedAlpha: false,
          notes: ["Pharmacogenomic study: comparing drug response across genotype groups (AA / Aa / aa)."] };
      case "carrier":
        return { formula: "single_proportion", defaultAlpha: 0.05, lockedAlpha: false,
          notes: ["Carrier study: estimating allele frequency in the population."] };
      case "linkage":
        return { formula: null, defaultAlpha: null, lockedAlpha: true,
          notes: ["Linkage analysis is family-based; sample size depends on family structure and disease model.",
                  "Use SIMLINK or GENEHUNTER software. LOD ≥ 3.0 = genome-wide significance."] };
      default:
        return { formula: "two_proportions", defaultAlpha: 0.05, lockedAlpha: false, notes: [] };
    }
  }

  // -----------------------------------------------------------------------
  // CHANGE 1 — Step 0 / Card A / Card C wiring
  // -----------------------------------------------------------------------

  function bindStep0() {
    document.querySelectorAll(".entry-card").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var entry = btn.getAttribute("data-entry");
        state.entryPath = entry; // remember where the user came from
        if (entry === "A") goToStep("A");
        else if (entry === "B") goToStep(1);
        else if (entry === "C") { wizardReset(); goToStep("C"); }
      });
    });
  }

  // Smart back: from Step 2, return to whichever entry the user came from
  // so they can edit their previous answers without losing them.
  function backToEntry() {
    var p = state.entryPath;
    if (p === "A") goToStep("A");
    else if (p === "C") goToStep("C");
    else goToStep(1); // default: Card B / direct entry
  }

  function bindCardA() {
    var back = document.getElementById("cardA-back");
    if (back) back.addEventListener("click", function () { goToStep(0); });
    var go = document.getElementById("cardA-go");
    if (go) go.addEventListener("click", onCardAGo);
  }

  function onCardAGo() {
    var errEl = document.getElementById("cardA-error");
    errEl.hidden = true; errEl.textContent = "";
    var nRaw = document.getElementById("cardA-n").value.trim();
    var n = parseInt(nRaw, 10);
    if (!nRaw || Number.isNaN(n) || n < 2) {
      errEl.hidden = false;
      errEl.textContent = "Please enter your available sample size (whole number ≥ 2).";
      return;
    }
    var objective = document.getElementById("cardA-objective").value.trim();
    state.objective = objective;
    var parsed = objectiveParser(objective);
    state.lastParsed = parsed;
    state.lastAnalysis = null;

    // Pick formula. Default to two_proportions if parser couldn't decide.
    var formula = parsed.formula || "two_proportions";

    // Card A invariant: n is given → must run REVERSE mode. If the parser
    // chose a formula that has no reverse spec (e.g. non_inferiority,
    // diagnostic_accuracy, icc, bayesian_credible), substitute the closest
    // reverse-capable formula based on parser flags so the user's n is
    // actually consumed. Surface the substitution as a chip + note.
    if (!REVERSE_SPECS[formula]) {
      var fallback;
      var f = parsed.flags || {};
      if (f.groups === 1 && f.outcome === "binary")        fallback = "single_proportion";
      else if (f.groups === 1 && f.outcome !== "binary")    fallback = "single_mean";
      else if (f.outcome === "binary")                      fallback = "two_proportions";
      else                                                  fallback = "two_means";
      parsed.chips = (parsed.chips || []).concat([
        "auto-switched to " + (FORMULAS[fallback] && FORMULAS[fallback].label || fallback) +
        " (so we can solve for what your n=" + n + " can detect)",
      ]);
      formula = fallback;
    }
    state.reverseMode = true;
    state.selectedFormula = formula;

    // Pre-fill the parameter form with defaults + n, then jump straight
    // to results by calling onCalculate via renderFormulaFields.
    goToStep(2, formula);
    // Set the n input
    var revSpec = REVERSE_SPECS[formula];
    if (revSpec) {
      var nInput = document.getElementById("param-" + revSpec.nField.key);
      if (nInput) nInput.value = String(n);
    }
    // Auto-trigger calculate
    setTimeout(function () { document.getElementById("calculate-btn").click(); }, 50);
  }

  // ---------- Card C wizard ----------
  var WIZ = { q: 1, answers: {} };
  function wizardReset() {
    WIZ = { q: 1, answers: {} };
    document.querySelectorAll(".wizard-step").forEach(function (s) { s.hidden = s.getAttribute("data-q") !== "1"; });
    document.querySelectorAll(".wizard-dot").forEach(function (d, i) { d.classList.toggle("is-active", i === 0); d.classList.remove("is-complete"); });
    var ids = ["wiz-objective", "wiz-n"];
    ids.forEach(function (id) { var el = document.getElementById(id); if (el) el.value = ""; });
    document.querySelectorAll('input[name="wiz-compare"], input[name="wiz-groups"], input[name="wiz-haven"]').forEach(function (r) { r.checked = false; });
  }
  function showWizQ(q) {
    WIZ.q = q;
    document.querySelectorAll(".wizard-step").forEach(function (s) { s.hidden = String(q) !== s.getAttribute("data-q"); });
    document.querySelectorAll(".wizard-dot").forEach(function (d, i) {
      d.classList.toggle("is-active", i + 1 === q);
      d.classList.toggle("is-complete", i + 1 < q);
    });
    if (q === 5) {
      var haven = WIZ.answers.haven;
      document.getElementById("wiz-q5-haven-yes").hidden = haven !== "yes";
      document.getElementById("wiz-q5-haven-no").hidden  = haven !== "no";
    }
    var nextBtn = document.getElementById("wiz-next");
    if (nextBtn) nextBtn.textContent = q === 5 ? "Calculate →" : "Next →";
  }
  function bindCardC() {
    var nextBtn = document.getElementById("wiz-next");
    var backBtn = document.getElementById("wiz-back");
    if (!nextBtn || !backBtn) return;
    nextBtn.addEventListener("click", function () {
      // Capture answer for current q
      if (WIZ.q === 1) {
        WIZ.answers.objective = document.getElementById("wiz-objective").value.trim();
      } else if (WIZ.q === 2) {
        var c = document.querySelector('input[name="wiz-compare"]:checked');
        if (!c) { window.medrasAlert("Please pick one.", 'warn'); return; }
        WIZ.answers.compare = c.value;
      } else if (WIZ.q === 3) {
        var g = document.querySelector('input[name="wiz-groups"]:checked');
        if (!g) { window.medrasAlert("Please pick one.", 'warn'); return; }
        WIZ.answers.groups = parseInt(g.value, 10);
      } else if (WIZ.q === 4) {
        var h = document.querySelector('input[name="wiz-haven"]:checked');
        if (!h) { window.medrasAlert("Please pick one.", 'warn'); return; }
        WIZ.answers.haven = h.value;
      } else if (WIZ.q === 5) {
        if (WIZ.answers.haven === "yes") {
          var nv = parseInt(document.getElementById("wiz-n").value, 10);
          if (!nv || nv < 2) { window.medrasAlert("Enter a sample size ≥ 2.", 'warn'); return; }
          WIZ.answers.n = nv;
        } else {
          WIZ.answers.alpha = parseFloat(document.getElementById("wiz-alpha").value);
        }
        return wizardFinish();
      }
      // Skip Q3 if Q2 said "no compare"
      var nextQ = WIZ.q + 1;
      if (nextQ === 3 && WIZ.answers.compare === "no") nextQ = 4;
      showWizQ(nextQ);
    });
    backBtn.addEventListener("click", function () {
      if (WIZ.q === 1) return goToStep(0);
      var prev = WIZ.q - 1;
      if (prev === 3 && WIZ.answers.compare === "no") prev = 2;
      showWizQ(prev);
    });
    var restartBtn = document.getElementById("wiz-restart");
    if (restartBtn) restartBtn.addEventListener("click", function () {
      wizardReset();
      goToStep(0);
    });
  }
  function wizardFinish() {
    var a = WIZ.answers;
    state.objective = a.objective || "";
    var parsed = objectiveParser(state.objective);
    state.lastParsed = parsed;
    state.lastAnalysis = null;

    // Override parser with explicit wizard answers
    if (a.compare === "no") {
      parsed.formula = parsed.formula && /single|correlation|kappa|roc|icc|diagnostic|bayesian/.test(parsed.formula)
        ? parsed.formula
        : (parsed.flags.outcome === "binary" ? "single_proportion" : "single_mean");
    } else if (a.groups >= 3) {
      parsed.formula = parsed.flags.longitudinal ? "repeated_measures_anova" : "anova_means";
    } else if (a.groups === 2) {
      if (parsed.flags.outcome === "binary") parsed.formula = "two_proportions";
      else if (parsed.flags.outcome === "time-to-event") parsed.formula = "survival_logrank";
      else if (parsed.flags.longitudinal) parsed.formula = "repeated_measures";
      else parsed.formula = parsed.flags.paired ? "paired_means" : "two_means";
    }
    var formula = parsed.formula || "two_means";
    state.selectedFormula = formula;
    state.reverseMode = a.haven === "yes" && !!REVERSE_SPECS[formula];

    goToStep(2, formula);
    if (a.alpha != null) {
      var alphaSel = document.getElementById("alpha");
      if (alphaSel) alphaSel.value = String(a.alpha);
    }
    if (state.reverseMode) {
      var revSpec = REVERSE_SPECS[formula];
      var nInput = document.getElementById("param-" + revSpec.nField.key);
      if (nInput) nInput.value = String(a.n);
    } else if (a.n) {
      // user has expected n in mind but in forward mode → put in expected field
      var expected = document.getElementById("expected");
      if (expected) expected.value = String(a.n);
    }
    setTimeout(function () { document.getElementById("calculate-btn").click(); }, 50);
  }

  function bindStep1() {
    document.getElementById("analyze-btn").addEventListener("click", onAnalyze);
    document.getElementById("manual-btn").addEventListener("click", function () {
      state.lastAnalysis = null;
      goToStep(2, "two_means");
    });
    var home1 = document.getElementById("home-from-step-1");
    if (home1) home1.addEventListener("click", function () { goToStep(0); });
    document.getElementById("accept-btn").addEventListener("click", function () {
      // If the analyzer routed to a non-formulaic study type (qualitative,
      // FGD, pilot, …) we have no formula to open. The recommendation panel
      // already shows the recommended n in-page; the accept button is hidden
      // in that case (see renderAnalysis), so this guard is belt-and-braces.
      if (state.lastAnalysis && !state.lastAnalysis.suggested_formula) return;
      var formula = state.lastAnalysis
        ? state.lastAnalysis.suggested_formula
        : "two_means";
      goToStep(2, formula);
    });
    document.getElementById("override-btn").addEventListener("click", function () {
      var fallback =
        state.lastAnalysis &&
        state.lastAnalysis.study_type_recommendation &&
        state.lastAnalysis.study_type_recommendation.fallback_formula;
      var formula =
        (state.lastAnalysis && state.lastAnalysis.suggested_formula) ||
        fallback ||
        "two_means";
      goToStep(2, formula);
    });
  }

  function bindStep2() {
    bindComplexityControls();
    document.getElementById("formula-select").addEventListener("change", function (event) {
      // Switching formulas keeps the chosen mode (forward / reverse) so that
      // a researcher who picked "I only have a sample size" doesn't have to
      // re-select it after browsing the formula list.
      renderFormulaFields(event.target.value);
    });
    document.getElementById("mode-select").addEventListener("change", function (event) {
      state.reverseMode = event.target.value === "reverse";
      renderFormulaFields(state.selectedFormula);
    });
    document.getElementById("calculate-btn").addEventListener("click", onCalculate);
    document.getElementById("back-to-step-1").addEventListener("click", backToEntry);
    var home2 = document.getElementById("home-from-step-2");
    if (home2) home2.addEventListener("click", function () { goToStep(0); });
  }

  function bindStep3() {
    document.getElementById("back-to-step-2").addEventListener("click", function () {
      goToStep(2, state.selectedFormula);
    });
    document.getElementById("restart-btn").addEventListener("click", function () {
      resetCalculator();
      goToStep(0);
    });
    var home3 = document.getElementById("home-from-step-3");
    if (home3) home3.addEventListener("click", function () { goToStep(0); });
    var dl = document.getElementById("download-report-btn");
    if (dl) {
      dl.addEventListener("click", function () {
        if (!state.lastResult) return;
        downloadReport(state.lastResult, state.reverseMode);
      });
    }
  }

  // Wipe every researcher-entered value so the next study starts clean.
  // Per-formula fields are rebuilt fresh by renderFormulaFields(); we only
  // need to reset the static (always-present) inputs here.
  function resetCalculator() {
    state.objective = "";
    state.selectedFormula = null;
    state.lastAnalysis = null;
    state.reverseMode = false;
    state.lastResult = null;
    var ids = ["objective", "expected"];
    ids.forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.value = "";
    });
    document.getElementById("alpha").value = "0.05";
    document.getElementById("power").value = "0.80";
    document.getElementById("dropout").value = "0";
    var modeSel = document.getElementById("mode-select");
    if (modeSel) modeSel.value = "forward";
    var studyType = document.getElementById("study-type");
    if (studyType) studyType.value = "auto";
    var panel = document.getElementById("analysis-panel");
    if (panel) panel.hidden = true;
    var recPanel = document.getElementById("study-type-recommendation");
    if (recPanel) recPanel.hidden = true;
    var err = document.getElementById("parameters-error");
    if (err) err.hidden = true;
    var formulaFields = document.getElementById("formula-fields");
    if (formulaFields) formulaFields.innerHTML = "";
  }

  // Snap an arbitrary suggested dropout fraction (0–0.20) to the nearest
  // value present in the dropout <select> so the option actually exists.
  function snapDropoutToOption(fraction) {
    var allowed = [0, 0.05, 0.10, 0.15, 0.20];
    var best = allowed[0];
    var bestDist = Math.abs(fraction - best);
    allowed.forEach(function (v) {
      var d = Math.abs(fraction - v);
      if (d < bestDist) {
        best = v;
        bestDist = d;
      }
    });
    return best === 0 ? "0" : String(best);
  }

  // -----------------------------------------------------------------------
  // Step 1 — analyze
  // -----------------------------------------------------------------------

  function onAnalyze() {
    var objective = document.getElementById("objective").value.trim();
    if (objective.length < 10) {
      window.medrasAlert("Please write at least one full sentence describing your objective.", 'warn');
      return;
    }
    state.objective = objective;
    var btn = document.getElementById("analyze-btn");
    btn.disabled = true;
    btn.textContent = "Analysing…";

    // Honour an explicit Study Type pick from Step 1 — the API will route
    // straight to the recommendation table for non-formulaic types.
    var studyTypeEl = document.getElementById("study-type");
    var studyTypeOverride =
      studyTypeEl && studyTypeEl.value && studyTypeEl.value !== "auto"
        ? studyTypeEl.value
        : null;
    var body = { objective: objective };
    if (studyTypeOverride) body.study_type = studyTypeOverride;

    fetch("/api/sample-size/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (resp) {
        return resp.json().then(function (body) {
          if (!resp.ok) throw new Error(body.detail || "Analysis failed.");
          return body;
        });
      })
      .then(function (data) {
        state.lastAnalysis = data;
        renderAnalysis(data);
      })
      .catch(function (err) {
        window.medrasAlert(err.message || "Could not analyse the objective.", 'error');
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = "Analyse objective";
      });
  }

  function renderAnalysis(data) {
    var panel = document.getElementById("analysis-panel");
    panel.hidden = false;
    setText("text-study-type", titleCase(data.study_type || "quantitative"));
    setText("text-detected-groups", String(data.detected_groups));
    setText("text-outcome-type", titleCase(data.outcome_type));
    setText("text-study-design", titleCase(data.study_design));
    var formulaLabel =
      data.suggested_formula && FORMULAS[data.suggested_formula]
        ? FORMULAS[data.suggested_formula].label
        : "—  (no formula needed for this study type)";
    setText("text-suggested-formula", formulaLabel);
    setText(
      "text-suggested-dropout",
      data.suggested_dropout && data.suggested_dropout > 0
        ? Math.round(data.suggested_dropout * 100) + "%"
        : "0% (none expected)"
    );
    setText("text-confidence", titleCase(data.confidence));
    setText("text-source", sourceLabel(data.source));
    setText("text-rationale", data.rationale || "");

    var warningsEl = document.querySelector('[data-testid="list-warnings"]');
    warningsEl.innerHTML = "";
    (data.warnings || []).forEach(function (w) {
      var li = document.createElement("li");
      li.textContent = w;
      warningsEl.appendChild(li);
    });

    renderStudyTypeRecommendation(data);

    // When the analyzer routes to a non-formulaic type the "Use this formula"
    // CTA is meaningless; hide it (keep "override" so users can drop into the
    // calculator manually). Otherwise show both buttons normally.
    var hasFormula = !!(data.suggested_formula && FORMULAS[data.suggested_formula]);
    var acceptBtn = document.getElementById("accept-btn");
    if (acceptBtn) acceptBtn.style.display = hasFormula ? "" : "none";
    var overrideBtn = document.getElementById("override-btn");
    if (overrideBtn) {
      overrideBtn.textContent = hasFormula
        ? "Choose a different formula"
        : "Open the calculator manually";
    }
  }

  function renderStudyTypeRecommendation(data) {
    var recPanel = document.getElementById("study-type-recommendation");
    if (!recPanel) return;
    var rec = data.study_type_recommendation;
    if (!rec) {
      recPanel.hidden = true;
      return;
    }
    recPanel.hidden = false;
    setText("text-rec-label", rec.label || titleCase(data.study_type));
    // For non-formulaic types with a fixed n (qualitative=12, FGD=24,
    // pilot=25, questionnaire=384) show the integer; for in-vitro/in-vivo
    // there is no single number (it depends on the design) so show the
    // recommended range only.
    var hasNumber =
      typeof rec.recommended_n === "number" && isFinite(rec.recommended_n);
    var recommendedLine = hasNumber
      ? "Recommended sample size: " +
        rec.recommended_n +
        (rec.range ? "  (" + rec.range + ")" : "")
      : "Recommended sample size: " + (rec.range || "see guidance below");
    setText("text-rec-recommended-n", recommendedLine);
    setText("text-rec-range", "");
    setText("text-rec-rationale", rec.rationale || "");
    var ul = document.querySelector('[data-testid="list-rec-guidance"]');
    if (ul) {
      ul.innerHTML = "";
      (rec.guidance || []).forEach(function (g) {
        var li = document.createElement("li");
        li.textContent = g;
        ul.appendChild(li);
      });
    }
    var fb = document.getElementById("rec-fallback-hint");
    if (fb) {
      if (rec.fallback_formula) {
        fb.hidden = false;
        fb.textContent =
          "If you need a power calculation instead, the closest matching " +
          'formula is "' +
          (FORMULAS[rec.fallback_formula]
            ? FORMULAS[rec.fallback_formula].label
            : rec.fallback_formula) +
          '" — click "Open the calculator manually" below.';
      } else {
        fb.hidden = true;
      }
    }
  }

  function sourceLabel(source) {
    if (source === "llm") return "AI assistant";
    if (source === "llm+heuristic_fallback") return "Rule-based (AI unavailable)";
    return "Rule-based";
  }

  // -----------------------------------------------------------------------
  // Step 2 — parameters
  // -----------------------------------------------------------------------

  // -----------------------------------------------------------------------
  // Reverse-mode specs — what each formula's back-calculation needs.
  //
  // Each entry says:
  //   removeFields  — keys to drop from the standard form when reverse mode
  //                   is active (the "unknown" inputs the researcher would
  //                   normally need to specify, e.g. p2 or Cohen's f)
  //   nField        — the sample-size field that gets added in their place
  //   solvesFor     — short label shown next to the formula expression
  //   detail        — human description for the toggle text
  // -----------------------------------------------------------------------

  // For each formula in reverse mode:
  //   removeFields  — keys the back-calculation SOLVES FOR (omitted entirely)
  //   keepFields    — design-structural keys we still ASK the user (e.g.
  //                   k = #groups, m = #timepoints, p = #predictors). All
  //                   other reference parameters are silently filled from
  //                   DEFAULTS so that "n-only reverse" really means n-only
  //                   from the researcher's perspective.
  //   nField        — the available-n input to render.
  var REVERSE_SPECS = {
    single_proportion: {
      removeFields: ["precision"],
      keepFields: [],
      nField: nField("n", "Available sample size", "How many participants you can recruit."),
      solvesFor: "the smallest precision (margin of error) it can achieve",
      detail: "Back-calculate the tightest confidence interval my available sample size can support.",
    },
    single_mean: {
      removeFields: ["precision"],
      keepFields: [],
      nField: nField("n", "Available sample size", "How many participants you can recruit."),
      solvesFor: "the smallest precision (margin of error) it can achieve",
      detail: "Back-calculate the tightest confidence interval my available sample size can support.",
    },
    two_proportions: {
      removeFields: ["p2"],
      keepFields: [],
      nField: nField("n_per_group", "Available sample size per group", "How many participants in each arm."),
      solvesFor: "the smallest detectable second proportion (p₂)",
      detail: "Back-calculate the smallest p₂ — both above and below p₁ — my sample can detect.",
    },
    two_means: {
      removeFields: ["mean1", "mean2"],
      keepFields: [],
      nField: nField("n_per_group", "Available sample size per group", "How many participants in each arm."),
      solvesFor: "the smallest detectable standardised mean difference (Cohen's d)",
      detail: "Back-calculate the smallest standardised difference (Cohen's d) my sample can detect.",
    },
    paired_means: {
      removeFields: ["mean_diff"],
      keepFields: [],
      nField: nField("n", "Available sample size (number of pairs)", "How many matched pairs / before-after subjects."),
      solvesFor: "the smallest detectable within-pair change (Cohen's d_z)",
      detail: "Back-calculate the smallest before-vs-after standardised change my paired sample can detect.",
    },
    anova_means: {
      removeFields: ["effect_size_f"],
      keepFields: ["k"],
      nField: nField("n_per_group", "Available sample size per group", "How many participants in each of the k groups.", 5),
      solvesFor: "the smallest detectable Cohen's f",
      detail: "Back-calculate the smallest between-group spread my sample can detect.",
    },
    repeated_measures: {
      removeFields: ["mean1", "mean2"],
      keepFields: ["m_timepoints"],
      nField: nField(
        "n_per_group",
        "Available sample size per group",
        "How many subjects in each of the two longitudinal arms."
      ),
      solvesFor: "the smallest detectable mean difference (Δ) across timepoints",
      detail: "Back-calculate the smallest Δ my longitudinal sample can detect.",
    },
    linear_regression: {
      removeFields: ["r_squared"],
      keepFields: ["predictors"],
      nField: nField(
        "n",
        "Available sample size",
        "How many participants you can recruit for the regression model."
      ),
      solvesFor: "the smallest detectable R² (and Cohen's f²)",
      detail: "Back-calculate the smallest R² my sample can detect with this number of predictors.",
    },
    prediction_model: {
      removeFields: ["predictors"],
      keepFields: [],
      nField: nField(
        "n_total",
        "Available total sample size",
        "Total number of participants for model development."
      ),
      solvesFor: "the maximum number of candidate predictors my sample can support",
      detail: "Back-calculate the maximum predictors the EPV rule allows for my sample.",
    },
    kappa_agreement: {
      removeFields: ["precision"],
      keepFields: [],
      nField: nField(
        "n",
        "Available number of subjects",
        "How many items / subjects two raters will independently rate.",
        10
      ),
      solvesFor: "the achievable precision (CI half-width) around κ",
      detail: "Back-calculate the tightest CI around κ my sample size can support.",
    },
    roc_auc: {
      removeFields: ["precision"],
      keepFields: [],
      nField: nField(
        "n_per_group",
        "Available number of cases (diseased)",
        "Controls will be added in proportion to the case-ratio default (1:1).",
        5
      ),
      solvesFor: "the achievable precision (CI half-width) around the AUC",
      detail: "Back-calculate the tightest CI around the AUC my case sample can support.",
    },
    correlation: {
      removeFields: ["expected_r"],
      keepFields: [],
      nField: nField(
        "n",
        "Available sample size",
        "How many subjects you can measure on both variables.",
        10
      ),
      solvesFor: "the smallest detectable |r|",
      detail: "Back-calculate the smallest correlation magnitude my sample can detect.",
    },
    repeated_measures_anova: {
      removeFields: ["effect_size_f"],
      keepFields: ["k_groups", "m_timepoints"],
      nField: nField(
        "n_per_group",
        "Available sample size per group",
        "How many subjects in each of the k groups.",
        4
      ),
      solvesFor: "the smallest detectable Cohen's f",
      detail: "Back-calculate the smallest between-group effect my sample can detect.",
    },
    survival_logrank: {
      removeFields: ["hazard_ratio"],
      keepFields: [],
      nField: nField(
        "n_total",
        "Available total sample size",
        "Both arms combined; allocation defaults to 1:1.",
        10
      ),
      solvesFor: "the smallest hazard ratio (above and below 1) the study can detect",
      detail: "Back-calculate the smallest detectable HR my study can separate from 1.",
    },
  };

  function nField(key, label, help, minN) {
    return {
      key: key,
      label: label,
      help: help,
      type: "number",
      min: minN || 4,
      max: 1000000,
      step: 1,
      placeholder: "e.g., 100",
    };
  }

  function renderFormulaFields(formulaKey) {
    state.selectedFormula = formulaKey;
    var spec = FORMULAS[formulaKey];
    var revSpec = REVERSE_SPECS[formulaKey];
    var defaults = DEFAULTS[formulaKey] || {};
    document.getElementById("formula-select").value = formulaKey;

    // Keep the mode dropdown in sync with state and visible for every formula.
    var modeWrap = document.getElementById("mode-select-wrap");
    if (modeWrap) modeWrap.hidden = false;
    var modeSelect = document.getElementById("mode-select");
    if (modeSelect) {
      modeSelect.value = state.reverseMode ? "reverse" : "forward";
    }

    // Update the dropdown's helper text so it accurately describes what
    // back-calculation means for THIS specific formula.
    var detail = document.getElementById("mode-select-detail");
    if (detail && revSpec) {
      detail.textContent =
        "If you choose the second option, this calculator will " +
        revSpec.detail.charAt(0).toLowerCase() +
        revSpec.detail.slice(1);
    }

    // Build the per-formula fields.
    //   FORWARD mode → render all spec.fields; placeholders show defaults so
    //                  the researcher can submit even with blanks (we'll
    //                  auto-fill on submit).
    //   REVERSE mode → render ONLY structural keepFields + the available-n
    //                  field. All other reference parameters are silently
    //                  filled from DEFAULTS so the researcher truly only
    //                  has to type their available sample size.
    var fieldsToRender;
    var hiddenDefaultedFields = []; // shown in the "defaults used" panel
    if (state.reverseMode && revSpec) {
      var keepSet = {};
      (revSpec.keepFields || []).forEach(function (k) { keepSet[k] = true; });
      var removeSet = {};
      (revSpec.removeFields || []).forEach(function (k) { removeSet[k] = true; });
      fieldsToRender = spec.fields
        .filter(function (f) { return keepSet[f.key]; })
        .concat([revSpec.nField]);
      hiddenDefaultedFields = spec.fields.filter(function (f) {
        return !keepSet[f.key] && !removeSet[f.key];
      });
    } else {
      fieldsToRender = spec.fields;
    }

    document.getElementById("formula-summary").textContent =
      state.reverseMode && revSpec
        ? "Solving for " + revSpec.solvesFor + ":  " + spec.expression
        : spec.expression;

    var container = document.getElementById("formula-fields");
    container.innerHTML = "";
    var row = document.createElement("div");
    row.className = "field-row";
    fieldsToRender.forEach(function (field) {
      // Pre-fill default into the placeholder so the user sees a hint.
      var fieldWithDefault = field;
      if (defaults.hasOwnProperty(field.key)) {
        fieldWithDefault = Object.assign({}, field, {
          placeholder:
            (field.placeholder ? field.placeholder + "  " : "") +
            "(default " + defaults[field.key] + ")",
        });
      }
      row.appendChild(buildFieldEl(fieldWithDefault));
    });
    container.appendChild(row);

    // Reverse-mode transparency disclosure — always shown so the researcher
    // knows what (if anything) the back-calculation auto-filled on their
    // behalf. When there are hidden defaults (most formulas), list them;
    // when there aren't (e.g. correlation), say so explicitly.
    if (state.reverseMode && revSpec) {
      var details = document.createElement("details");
      details.className = "reverse-defaults";
      details.open = false;
      var summary = document.createElement("summary");
      var ul = document.createElement("ul");
      ul.className = "reverse-defaults-list";
      var hint = document.createElement("p");
      hint.className = "reverse-defaults-hint";

      if (hiddenDefaultedFields.length) {
        summary.textContent =
          "Defaults used (" + hiddenDefaultedFields.length + " parameter" +
          (hiddenDefaultedFields.length === 1 ? "" : "s") +
          ") — click to view";
        hiddenDefaultedFields.forEach(function (f) {
          var v = defaults[f.key];
          if (v === undefined) return;
          var li = document.createElement("li");
          li.textContent = (DEFAULT_LABELS[f.key] || f.label) + " = " + v;
          ul.appendChild(li);
        });
        hint.textContent =
          "Switch to forward mode if you want to set these yourself.";
      } else {
        summary.textContent =
          "Defaults used — only the available sample size is needed";
        var li2 = document.createElement("li");
        li2.textContent =
          "No reference parameters were auto-filled — n is the only input " +
          "this back-calculation requires.";
        ul.appendChild(li2);
        hint.textContent = "";
      }

      details.appendChild(summary);
      details.appendChild(ul);
      if (hint.textContent) details.appendChild(hint);
      container.appendChild(details);
    }

    // Power field is irrelevant for descriptive (single-sample) formulas.
    var powerField = document.querySelector("[data-power-field]");
    if (powerField) {
      powerField.style.display = spec.usesPower ? "" : "none";
    }

    // A handful of formulas (prediction_model) don't use α at all because
    // they're rule-of-thumb based rather than hypothesis-test based.
    var usesAlpha = spec.usesAlpha !== false;
    var alphaField = document.querySelector("[data-alpha-field]");
    if (alphaField) {
      alphaField.style.display = usesAlpha ? "" : "none";
    }

    // The "expected sample size" target is meaningless in reverse mode —
    // the researcher's available n IS the input. Hide it to avoid confusion.
    var expectedFieldset = document.getElementById("expected").closest("fieldset");
    if (expectedFieldset) {
      expectedFieldset.style.display = state.reverseMode ? "none" : "";
    }

    // CHANGE 6 — apply per-formula dropout rule
    applyDropoutRule(formulaKey);

    // Update the calculate button label to match the mode.
    var calcBtn = document.getElementById("calculate-btn");
    if (calcBtn && !calcBtn.disabled) {
      calcBtn.textContent = state.reverseMode
        ? "Calculate detectable effect"
        : "Calculate sample size";
    }
  }

  // CHANGE 6 — show/hide/relabel the dropout select per formula.
  function applyDropoutRule(formulaKey) {
    var rule = DROPOUT_RULES[formulaKey] || "show";
    var field = document.getElementById("dropout-field");
    var label = document.getElementById("dropout-label");
    var sel = document.getElementById("dropout");
    if (!field || !sel) return;
    if (rule === "hide") {
      field.style.display = "none";
      sel.value = "0"; // ensure no dropout adjustment when hidden
    } else if (rule.indexOf("rename:") === 0) {
      field.style.display = "";
      var kind = rule.split(":")[1];
      label.textContent = kind === "experimental_failure"
        ? "Expected experimental failure rate (%)"
        : "Expected animal loss (%)";
    } else {
      field.style.display = "";
      label.textContent = "Anticipated dropout / non-response";
    }
  }

  // CHANGE 1 — bind complexity radios + genetic sub-type chooser
  function bindComplexityControls() {
    if (bindComplexityControls._bound) return;
    bindComplexityControls._bound = true;
    document.querySelectorAll('input[name="complexity"]').forEach(function (r) {
      r.addEventListener("change", function () { applyComplexityVisibility(); });
    });
    var gType = document.getElementById("genetic-type");
    if (gType) gType.addEventListener("change", applyGeneticSubtypeUI);
    // Sub-toggles inside the complex fieldset
    ["cx-outcomes", "cx-timepoints", "cx-multicentre", "cx-adaptive"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener("change", applyComplexSubRows);
    });
  }
  function getComplexity() {
    var el = document.querySelector('input[name="complexity"]:checked');
    return el ? el.value : "simple";
  }
  function applyComplexityVisibility() {
    var c = getComplexity();
    document.getElementById("complex-fieldset").hidden = c !== "complex";
    document.getElementById("genetic-group").hidden    = c !== "genetic";
    if (c === "complex") applyComplexSubRows();
    if (c === "genetic") applyGeneticSubtypeUI();
  }
  function applyComplexSubRows() {
    var k = parseInt(document.getElementById("cx-outcomes").value, 10) || 1;
    var m = parseInt(document.getElementById("cx-timepoints").value, 10) || 1;
    document.getElementById("cx-composite-row").hidden = !(k > 1);
    document.getElementById("cx-rm-row").hidden        = !(m > 1);
    document.getElementById("cx-multicentre-row").hidden = document.getElementById("cx-multicentre").value !== "yes";
    document.getElementById("cx-adaptive-row").hidden    = document.getElementById("cx-adaptive").value !== "yes";
  }
  function applyGeneticSubtypeUI() {
    var sub = document.getElementById("genetic-type").value;
    document.getElementById("genetic-gwas-warning").hidden    = sub !== "gwas";
    document.getElementById("genetic-linkage-info").hidden    = sub !== "linkage";
    var info = geneticEngineSelect(sub);
    var alphaSel = document.getElementById("alpha");
    if (info.lockedAlpha && info.defaultAlpha != null) {
      // Add the special α option if missing, then select it.
      if (info.defaultAlpha === 5e-8) {
        if (!Array.prototype.find.call(alphaSel.options, function (o) { return o.value === "5e-8"; })) {
          var opt = document.createElement("option");
          opt.value = "5e-8";
          opt.textContent = "5×10⁻⁸ (GWAS genome-wide significance)";
          alphaSel.appendChild(opt);
        }
        alphaSel.value = "5e-8";
      }
    }
    // Show the appropriate underlying formula
    if (info.formula) {
      var sel = document.getElementById("formula-select");
      if (sel) sel.value = info.formula;
      renderFormulaFields(info.formula);
    }
  }

  function buildFieldEl(field) {
    var wrap = document.createElement("div");
    wrap.className = "field";
    var label = document.createElement("label");
    label.className = "field-label";
    label.htmlFor = "param-" + field.key;
    label.textContent = field.label;
    wrap.appendChild(label);

    var input = document.createElement("input");
    input.className = "field-input";
    input.type = field.type || "number";
    input.id = "param-" + field.key;
    input.name = field.key;
    input.dataset.testid = "input-param-" + field.key;
    if (field.min !== undefined) input.min = String(field.min);
    if (field.max !== undefined) input.max = String(field.max);
    if (field.step !== undefined) input.step = String(field.step);
    if (field.placeholder) input.placeholder = field.placeholder;
    wrap.appendChild(input);

    if (field.help) {
      var help = document.createElement("p");
      help.className = "field-help";
      help.textContent = field.help;
      wrap.appendChild(help);
    }
    return wrap;
  }

  // Discrete-count keys must be whole numbers; API rejects fractions.
  var DISCRETE_KEYS = {
    n: 1, n_per_group: 1, n_total: 1,
    k: 1, k_groups: 1, predictors: 1, m_timepoints: 1, epv_target: 1,
  };

  function onCalculate() {
    var spec = FORMULAS[state.selectedFormula];
    var revSpec = REVERSE_SPECS[state.selectedFormula];
    var defaults = DEFAULTS[state.selectedFormula] || {};
    var isReverse = !!state.reverseMode && !!revSpec;

    // What the form actually rendered:
    //   reverse → keepFields + n
    //   forward → all spec.fields
    var visibleFields;
    var hiddenDefaultedFields = [];
    if (isReverse) {
      var keepSet = {};
      (revSpec.keepFields || []).forEach(function (k) { keepSet[k] = true; });
      var removeSet = {};
      (revSpec.removeFields || []).forEach(function (k) { removeSet[k] = true; });
      visibleFields = spec.fields
        .filter(function (f) { return keepSet[f.key]; })
        .concat([revSpec.nField]);
      hiddenDefaultedFields = spec.fields.filter(function (f) {
        return !keepSet[f.key] && !removeSet[f.key];
      });
    } else {
      visibleFields = spec.fields;
    }

    var params = {};
    var missing = [];

    // Read visible inputs. Blank cells fall back to DEFAULTS (forward mode)
    // or, for the n field specifically, are flagged as missing — n is the
    // ONE thing the researcher must always tell us in reverse mode.
    visibleFields.forEach(function (field) {
      var el = document.getElementById("param-" + field.key);
      var raw = el ? el.value : "";
      var num;
      if (raw === "" || raw === null) {
        if (defaults.hasOwnProperty(field.key)) {
          num = defaults[field.key];
        } else {
          // No default available — must ask. Most commonly this is the
          // available-n field in reverse mode, or a structural keepField.
          missing.push(field.label);
          return;
        }
      } else {
        num = Number(raw);
        if (Number.isNaN(num)) {
          missing.push(field.label);
          return;
        }
      }
      if (DISCRETE_KEYS[field.key]) {
        num = Math.floor(num);
      }
      params[field.key] = num;
    });

    // Inject hidden reference-parameter defaults (reverse mode only).
    hiddenDefaultedFields.forEach(function (f) {
      if (defaults.hasOwnProperty(f.key) && !params.hasOwnProperty(f.key)) {
        var v = defaults[f.key];
        params[f.key] = DISCRETE_KEYS[f.key] ? Math.floor(v) : v;
      }
    });

    var dropout = Number(document.getElementById("dropout").value);
    params.dropout = dropout;
    if (spec.usesAlpha !== false) {
      params.alpha = Number(document.getElementById("alpha").value);
    }
    if (spec.usesPower) {
      params.power = Number(document.getElementById("power").value);
    }

    var errEl = document.getElementById("parameters-error");
    if (missing.length) {
      errEl.hidden = false;
      errEl.textContent = "Please fill in: " + missing.join(", ") + ".";
      return;
    }
    errEl.hidden = true;

    var btn = document.getElementById("calculate-btn");
    btn.disabled = true;
    btn.textContent = "Calculating…";

    var expectedRaw = document.getElementById("expected").value.trim();
    var expected =
      expectedRaw === ""
        ? null
        : Math.max(1, Math.floor(Number(expectedRaw)));

    var restoreLabel = isReverse
      ? "Calculate detectable effect"
      : "Calculate sample size";

    // CHANGE 7 — Client-side compute path for the 5 new formulas.
    if (spec.clientCompute && !isReverse) {
      try {
        var data = clientComputeForward(state.selectedFormula, params);
        // Note which inputs were left blank so the autofilled defaults
        // table can flag them.
        data._autofilledKeys = collectAutofilledKeys(visibleFields, defaults);
        if (expected !== null) data.expected_sample_size = expected;
        var post = postProcess(data, expected);
        renderResult(post);
        goToStep(3);
      } catch (err) {
        errEl.hidden = false;
        errEl.textContent = err.message || "Calculation failed.";
      } finally {
        btn.disabled = false;
        btn.textContent = restoreLabel;
      }
      return;
    }

    var url = isReverse
      ? "/api/sample-size/reverse"
      : "/api/sample-size/calculate";
    var body = { formula: state.selectedFormula, parameters: params };
    if (!isReverse) {
      if (expected !== null && !Number.isNaN(expected)) {
        body.expected_sample_size = expected;
      }
    }

    var autofilledKeys = collectAutofilledKeys(visibleFields, defaults);

    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          if (!resp.ok) throw new Error(humanizeError(data.detail));
          return data;
        });
      })
      .then(function (data) {
        if (isReverse) {
          state.lastResult = data;
          renderReverseResult(data);
        } else {
          data._autofilledKeys = autofilledKeys;
          var post = postProcess(data, expected);
          renderResult(post);
        }
        goToStep(3);
      })
      .catch(function (err) {
        errEl.hidden = false;
        errEl.textContent = err.message || "Calculation failed.";
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = restoreLabel;
      });
  }

  // Track which fields were left blank by the user (so the autofilled
  // defaults table flags them).
  function collectAutofilledKeys(visibleFields, defaults) {
    var keys = [];
    visibleFields.forEach(function (f) {
      var el = document.getElementById("param-" + f.key);
      if (!el) return;
      if ((el.value === "" || el.value === null) && defaults.hasOwnProperty(f.key)) {
        keys.push(f.key);
      }
    });
    // Constants (alpha/power/dropout) are never blank in the UI but we still
    // disclose them as "auto-filled standards" if untouched by the wizard.
    var alphaSel = document.getElementById("alpha");
    var powerSel = document.getElementById("power");
    var dropSel  = document.getElementById("dropout");
    if (alphaSel && alphaSel.value === "0.05") keys.push("alpha");
    if (powerSel && powerSel.value === "0.80") keys.push("power");
    if (dropSel && dropSel.value === "0") keys.push("dropout");
    return keys;
  }

  // Apply complex-trial layering and attach verdict + chip metadata.
  function postProcess(data, expected) {
    state.lastLayers = null;
    var c = getComplexity();
    if (c === "complex") {
      var cx = readComplexInputs();
      var layered = applyComplexLayers(data, cx);
      data = layered.result;
      state.lastLayers = layered.layers;
      data.notes = (data.notes || []).concat([
        "Complex-trial pipeline applied: " + layered.layers.length + " layer" +
        (layered.layers.length === 1 ? "" : "s") + ".",
      ]);
    } else if (c === "genetic") {
      var sub = document.getElementById("genetic-type").value;
      var info = geneticEngineSelect(sub);
      data._genetic = { subtype: sub, info: info };
      data.notes = (data.notes || []).concat(info.notes || []);
    }
    if (expected != null && !Number.isNaN(expected)) {
      // Stamp the user-provided expected n onto the result so the new
      // hero card always reflects what the researcher entered, even when
      // the server response doesn't echo it back.
      data.expected_sample_size = expected;
      data._verdict = computeVerdict(expected, data.adjusted_n || data.total_n);
    } else {
      // Explicit null so the hero card can show the empty-state hint.
      data.expected_sample_size = null;
    }
    state.lastResult = data;
    return data;
  }
  function readComplexInputs() {
    return {
      outcomes:    parseInt(document.getElementById("cx-outcomes").value, 10) || 1,
      timepoints:  parseInt(document.getElementById("cx-timepoints").value, 10) || 1,
      multicentre: document.getElementById("cx-multicentre").value,
      adaptive:    document.getElementById("cx-adaptive").value,
      rho_outcomes: parseFloat(document.getElementById("cx-rho-outcomes").value) || 0.4,
      rho_time:     parseFloat(document.getElementById("cx-rho-time").value) || 0.5,
      sites:        parseInt(document.getElementById("cx-sites").value, 10) || 10,
      icc:          parseFloat(document.getElementById("cx-icc").value) || 0.05,
      interims:     parseInt(document.getElementById("cx-interims").value, 10) || 1,
    };
  }
  function computeVerdict(expected, required) {
    if (!required) return null;
    var ratio = expected / required;
    if (ratio >= 1) {
      return { color: "green", badge: "✅ ADEQUATELY POWERED",
        message: "Your sample of " + expected + " meets the requirement of " + required + " (" + Math.round(ratio * 100) + "%). Good to proceed." };
    }
    if (ratio >= 0.8) {
      return { color: "amber", badge: "⚠ MARGINALLY UNDERPOWERED",
        message: "Your sample of " + expected + " is " + Math.round(ratio * 100) + "% of the required " + required + ". Consider increasing recruitment or accept reduced power." };
    }
    return { color: "red", badge: "❌ UNDERPOWERED",
      message: "Your sample of " + expected + " is only " + Math.round(ratio * 100) + "% of the required " + required + ". Either increase recruitment, accept a smaller detectable effect, or simplify the study design." };
  }

  // FastAPI's 422 returns detail as an array of validation errors.
  function humanizeError(detail) {
    if (!detail) return "Calculation failed.";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map(function (d) {
          var loc = (d.loc || []).slice(-1)[0] || "value";
          return loc + ": " + (d.msg || "invalid");
        })
        .join("; ");
    }
    return "Calculation failed.";
  }

  // -----------------------------------------------------------------------
  // Step 3 — result
  // -----------------------------------------------------------------------

  function renderResult(data) {
    // Forward-mode layout: show forward hero, hide reverse panel + reverse hero + extras.
    var reversePanel = document.getElementById("result-reverse");
    if (reversePanel) reversePanel.hidden = true;
    var hero = document.getElementById("result-hero");
    if (hero) hero.hidden = false;
    var heroReverse = document.getElementById("result-hero-reverse");
    if (heroReverse) heroReverse.hidden = true;
    var heroExtras = document.getElementById("result-hero-extras");
    if (heroExtras) { heroExtras.hidden = true; heroExtras.innerHTML = ""; }
    var heading = document.getElementById("result-heading");
    if (heading) heading.textContent = "3. Required sample size";

    state.lastResult = data;
    renderRecommendedPanel(data, false);

    setText("text-result-formula", data.formula_label + " · " + data.formula_expression);
    setText("text-n-per-group", formatN(data.n_per_group, data.number_of_groups));
    setText("text-total-n", String(data.total_n));
    setText("text-adjusted-n", String(data.adjusted_n));
    setText("text-formula-expression", data.formula_expression);

    // NEW HERO — populate the "Expected sample size" card. When the
    // researcher didn't supply an expected n, render a friendly "Not
    // provided" plus a small hint instead of a bare em-dash, so the card
    // tells users what to do to get a comparison.
    var expectedEl = document.querySelector('[data-testid="text-expected-n"]');
    var expectedSubEl = document.querySelector('[data-testid="text-expected-sublabel"]');
    var expectedCard = expectedEl ? expectedEl.closest(".hero-stat-expected") : null;
    if (data.expected_sample_size != null) {
      if (expectedEl) expectedEl.textContent = String(data.expected_sample_size);
      if (expectedSubEl) expectedSubEl.textContent = "your target recruitment";
      if (expectedCard) expectedCard.classList.remove("hero-stat-empty");
    } else {
      if (expectedEl) expectedEl.textContent = "Not provided";
      if (expectedSubEl) {
        expectedSubEl.textContent = "Add an expected n in step 2 to see how it compares";
      }
      if (expectedCard) expectedCard.classList.add("hero-stat-empty");
    }

    fillTable("table-inputs", data.inputs, INPUT_LABELS);
    fillTable("table-constants", data.constants, CONSTANT_LABELS);

    var notesSection = document.getElementById("result-notes-section");
    var notesList = document.querySelector('[data-testid="list-result-notes"]');
    notesList.innerHTML = "";
    if (data.notes && data.notes.length) {
      notesSection.hidden = false;
      data.notes.forEach(function (note) {
        var li = document.createElement("li");
        li.textContent = note;
        notesList.appendChild(li);
      });
    } else {
      notesSection.hidden = true;
    }

    var compPanel = document.getElementById("result-comparison");
    if (data.expected_comparison) {
      var c = data.expected_comparison;
      compPanel.hidden = false;
      compPanel.classList.toggle("is-shortfall", !c.meets_requirement);
      setText("text-comparison-verdict", c.verdict);
      setText("text-comp-expected", String(c.expected_sample_size));
      setText("text-comp-required", String(c.statistically_required_total));
      setText("text-comp-adjusted", String(c.adjusted_required_total));
      setText("text-comp-shortfall", c.shortfall === 0 ? "None" : String(c.shortfall));
    } else {
      compPanel.hidden = true;
    }

    // CHANGE 3 — Verdict card (traffic light)
    renderVerdictCard(data);
    // CHANGE 3 — Auto-filled defaults table
    renderAutofilledTable(data);
    // CHANGE 2 — Detected chips (only when objective parser ran)
    renderDetectedChips();
    // CHANGE 4 — Layer-by-layer breakdown (only when complex layers applied)
    renderLayerBreakdown();
    // CHANGE 5 — Genetic checklist (only for genetic results)
    var gPanel = document.getElementById("genetic-checklist");
    if (gPanel) gPanel.hidden = !data._genetic;
  }

  function renderVerdictCard(data) {
    var card = document.getElementById("verdict-card");
    var nums = document.getElementById("verdict-numbers");
    var badge = document.getElementById("verdict-badge");
    var msg = document.getElementById("verdict-message");
    if (!card) return;
    card.classList.remove("verdict-green", "verdict-amber", "verdict-red", "verdict-blue");
    var v = data._verdict;
    if (!v) {
      card.classList.add("verdict-blue");
      nums.hidden = true;
      badge.textContent = "ℹ︎ For your information";
      msg.textContent = "You did not provide an expected sample size. The required total is " +
        (data.adjusted_n || data.total_n) + " (after dropout: " + (data.adjusted_n || data.total_n) + ").";
      return;
    }
    card.classList.add("verdict-" + v.color);
    nums.hidden = false;
    setText("text-verdict-yours", String(data.expected_sample_size != null ? data.expected_sample_size : data._verdict.yours || "—"));
    setText("text-verdict-required", String(data.adjusted_n || data.total_n));
    badge.textContent = v.badge;
    msg.textContent = v.message;
  }

  function renderAutofilledTable(data) {
    var section = document.getElementById("autofilled-section");
    if (!section) return;
    var keys = (data._autofilledKeys || []).filter(Boolean);
    if (!keys.length) { section.hidden = true; return; }
    section.hidden = false;
    var tbody = section.querySelector("tbody");
    tbody.innerHTML = "";
    var labels = Object.assign({}, INPUT_LABELS, DEFAULT_LABELS, {
      alpha: "Alpha (α)",
      power: "Power (1−β)",
      dropout: "Anticipated dropout",
    });
    var defaults = DEFAULTS[data.formula] || {};
    var statics = { alpha: 0.05, power: 0.80, dropout: 0 };
    keys.forEach(function (k) {
      var v = (defaults[k] != null) ? defaults[k] : statics[k];
      if (v == null) return;
      var tr = document.createElement("tr");
      var th = document.createElement("th"); th.textContent = labels[k] || k; tr.appendChild(th);
      var td = document.createElement("td"); td.textContent = formatValue(v); tr.appendChild(td);
      var td2 = document.createElement("td"); td2.textContent = WHY_DEFAULTS[k] || "Standard default"; tr.appendChild(td2);
      tbody.appendChild(tr);
    });
  }

  function renderDetectedChips() {
    var row = document.getElementById("detected-row");
    if (!row) return;
    var p = state.lastParsed;
    if (!p || !p.chips || !p.chips.length) { row.hidden = true; return; }
    row.hidden = false;
    var box = document.getElementById("detected-chips");
    box.innerHTML = "";
    p.chips.forEach(function (c) {
      var span = document.createElement("span");
      span.className = "chip";
      span.textContent = c;
      box.appendChild(span);
    });
    var pick = document.getElementById("detected-pick");
    var spec = FORMULAS[state.selectedFormula];
    pick.textContent = "We picked " + (spec ? spec.label : state.selectedFormula) +
      " because of these signals. Use the formula dropdown above to change it.";
  }

  function renderLayerBreakdown() {
    var section = document.getElementById("layer-breakdown-section");
    if (!section) return;
    var L = state.lastLayers;
    if (!L || L.length <= 1) { section.hidden = true; return; }
    section.hidden = false;
    var tbody = section.querySelector("tbody");
    tbody.innerHTML = "";
    L.forEach(function (layer) {
      var tr = document.createElement("tr");
      ["name", "adj", "n_per_group", "total_n"].forEach(function (k) {
        var td = document.createElement("td");
        td.textContent = String(layer[k]);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    // Sensitivity line: ±20% on each multiplier
    var base = L[0].total_n;
    var finalN = L[L.length - 1].total_n;
    var lo = Math.round(finalN * 0.8);
    var hi = Math.round(finalN * 1.2);
    setText("text-layer-sensitivity",
      "Sensitivity range (±20% on multipliers): " + lo + " — " + hi +
      " total. Baseline before adjustments was " + base + ".");
  }

  function formatN(nPerGroup, numGroups) {
    if (numGroups <= 1) return nPerGroup + " per group";
    return nPerGroup + " per group (× " + numGroups + " groups)";
  }

  // Pull the most relevant "user-entered sample size" from a reverse-mode
  // response's inputs object. Different formulas use different keys, so we
  // try the common ones in priority order: per-group totals first (because
  // most studies are reported that way), then total n.
  var REVERSE_N_KEYS = [
    "n_per_group_recruited",
    "n_per_group_analyzable",
    "n_per_group",
    "n_recruited",
    "n_analyzable",
    "total_n",
    "n_total",
    "sample_size",
    "n",
  ];
  function pickReverseSampleSize(inputs) {
    for (var i = 0; i < REVERSE_N_KEYS.length; i++) {
      var k = REVERSE_N_KEYS[i];
      if (inputs[k] != null && inputs[k] !== "") return inputs[k];
    }
    return null;
  }

  // -----------------------------------------------------------------------
  // Step 3 — reverse result (generic for all 6 formulas)
  //
  // The API returns a `headline` array of {label, value, sublabel?} stats
  // already formatted as strings; we render one card per entry. This way
  // the same UI works whether the back-calculated quantity is a precision
  // (single proportion/mean), a probability (two_proportions), a difference
  // in the original units (two_means/paired_means), or Cohen's f (ANOVA).
  // -----------------------------------------------------------------------

  function renderReverseResult(data) {
    var heading = document.getElementById("result-heading");
    if (heading) heading.textContent = "3. Minimum detectable effect";

    state.lastResult = data;
    renderRecommendedPanel(data, true);

    setText(
      "text-result-formula",
      data.formula_label + " · " + data.formula_expression
    );

    // Reverse-mode layout: hide the forward hero, show the dedicated
    // reverse hero pair + the (kept-but-hidden) reverse panel for warnings.
    var heroPanel = document.getElementById("result-hero");
    if (heroPanel) heroPanel.hidden = true;
    var heroRev = document.getElementById("result-hero-reverse");
    if (heroRev) heroRev.hidden = false;
    document.getElementById("result-comparison").hidden = true;
    document.getElementById("result-reverse").hidden = false;

    setText("text-formula-expression", data.formula_expression);

    // ---- NEW REVERSE HERO PAIR ----------------------------------------
    // Left card: the user's own sample size, pulled from the inputs they
    // typed (different formulas use different keys; pick the most relevant).
    var userN = pickReverseSampleSize(data.inputs || {});
    setText(
      "text-reverse-yours",
      userN != null ? String(userN) : "—"
    );
    var alpha = (data.inputs && data.inputs.alpha) || 0.05;
    var power = (data.inputs && data.inputs.power) || 0.80;
    var subText =
      "what you can recruit · α=" + alpha + ", power=" + power;
    setText("text-reverse-yours-sub", subText);

    // Right card: the primary detectable stat from the API response.
    var primary = (data.headline && data.headline[0]) || null;
    var extras  = (data.headline || []).slice(1);
    setText(
      "text-reverse-primary-label",
      primary ? primary.label : "Smallest detectable effect"
    );
    setText(
      "text-reverse-primary-value",
      primary ? primary.value : "—"
    );
    setText(
      "text-reverse-primary-sub",
      (primary && primary.sublabel) ||
        "the smallest effect this sample can detect"
    );

    // Extra detectable stats (e.g. detectable increase + decrease) render
    // as a slim chip row directly below the hero so users see them too.
    var extrasEl = document.getElementById("result-hero-extras");
    if (extrasEl) {
      extrasEl.innerHTML = "";
      if (extras.length === 0) {
        extrasEl.hidden = true;
      } else {
        extras.forEach(function (stat) {
          var row = document.createElement("div");
          row.className = "result-hero-extra";
          var l = document.createElement("span");
          l.className = "result-hero-extra-label";
          l.textContent = stat.label;
          var v = document.createElement("span");
          v.className = "result-hero-extra-value";
          v.textContent = stat.value;
          row.appendChild(l);
          row.appendChild(v);
          if (stat.sublabel) {
            var s = document.createElement("span");
            s.className = "result-hero-extra-sub";
            s.textContent = stat.sublabel;
            row.appendChild(s);
          }
          extrasEl.appendChild(row);
        });
        extrasEl.hidden = false;
      }
    }

    // Keep the legacy hidden #reverse-headline list populated for any
    // tests/external callers that still query it by data-testid.
    var headlineEl = document.getElementById("reverse-headline");
    headlineEl.innerHTML = "";
    (data.headline || []).forEach(function (stat) {
      var card = document.createElement("div");
      card.className = "result-stat";
      var label = document.createElement("span");
      label.className = "result-stat-label";
      label.textContent = stat.label;
      card.appendChild(label);
      var value = document.createElement("span");
      value.className = "result-stat-value";
      value.textContent = stat.value;
      card.appendChild(value);
      if (stat.sublabel) {
        var sub = document.createElement("span");
        sub.className = "result-stat-sublabel";
        sub.textContent = stat.sublabel;
        card.appendChild(sub);
      }
      headlineEl.appendChild(card);
    });

    fillTable("table-inputs", data.inputs, INPUT_LABELS);
    fillTable("table-constants", data.constants, CONSTANT_LABELS);

    // Notes
    var notesSection = document.getElementById("result-notes-section");
    var notesList = document.querySelector('[data-testid="list-result-notes"]');
    notesList.innerHTML = "";
    if (data.notes && data.notes.length) {
      notesSection.hidden = false;
      data.notes.forEach(function (note) {
        var li = document.createElement("li");
        li.textContent = note;
        notesList.appendChild(li);
      });
    } else {
      notesSection.hidden = true;
    }

    // Warnings (e.g. an effect direction that isn't detectable at all).
    var warnList = document.getElementById("reverse-warnings-list");
    warnList.innerHTML = "";
    (data.warnings || []).forEach(function (w) {
      var li = document.createElement("li");
      li.textContent = w;
      warnList.appendChild(li);
    });

    // CHANGE 3 — In reverse mode, render a blue "estimate" verdict card so
    // Card A users always get the top-of-result summary they expect.
    var card = document.getElementById("verdict-card");
    if (card) {
      card.classList.remove("verdict-green", "verdict-amber", "verdict-red");
      card.classList.add("verdict-blue");
      var nums = document.getElementById("verdict-numbers");
      if (nums) nums.hidden = true;
      var badge = document.getElementById("verdict-badge");
      var msg = document.getElementById("verdict-message");
      if (badge) badge.textContent = "ℹ︎ What your sample can detect";
      if (msg) {
        var headlineSummary = (data.headline && data.headline[0])
          ? data.headline[0].label + ": " + data.headline[0].value
          : "See detectable effect below.";
        msg.textContent = "You provided n. We solved the formula for the smallest effect detectable at α=" +
          (data.inputs && data.inputs.alpha ? data.inputs.alpha : "0.05") +
          " with power=" + (data.inputs && data.inputs.power ? data.inputs.power : "0.80") +
          ". " + headlineSummary;
      }
    }
    // CHANGE 2 — Detected chips also render in reverse mode (objective parser).
    renderDetectedChips();
    // Hide forward-only panels (autofilled, layer breakdown, genetic checklist)
    var af = document.getElementById("autofilled-section");
    if (af) af.hidden = true;
    var lb = document.getElementById("layer-breakdown-section");
    if (lb) lb.hidden = true;
    var gc = document.getElementById("genetic-checklist");
    if (gc) gc.hidden = true;
  }

  // -----------------------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------------------

  var INPUT_LABELS = {
    expected_proportion: "Expected proportion (p)",
    absolute_precision: "Absolute precision (d)",
    standard_deviation: "Standard deviation (σ)",
    p1: "Proportion in group 1 (p₁)",
    p2: "Proportion in group 2 (p₂)",
    mean1: "Mean in group 1 (μ₁)",
    mean2: "Mean in group 2 (μ₂)",
    expected_mean_difference: "Expected mean difference (Δ)",
    sd_of_differences: "SD of differences (σ_d)",
    number_of_groups: "Number of groups (k)",
    cohens_f: "Cohen's f (effect size)",
    alpha: "Alpha (α — Type I error)",
    power: "Power (1 − β)",
    dropout_rate: "Anticipated dropout rate",
    n_per_group_recruited: "Available n per group (recruited)",
    n_per_group_analyzable: "Analysable n per group (after dropout)",
    n_recruited: "Available n (recruited)",
    n_analyzable: "Analysable n (after dropout)",
    // Repeated measures
    within_subject_correlation: "Within-subject correlation (ρ)",
    number_of_timepoints: "Number of timepoints (m)",
    // Linear regression
    expected_r_squared: "Expected R² (variance explained)",
    number_of_predictors: "Number of predictors (p)",
    // Prediction model
    event_rate: "Expected event rate",
    epv_target: "Events per variable (EPV target)",
    // Kappa
    expected_kappa: "Expected κ",
    // ROC / AUC
    expected_auc: "Expected AUC",
    controls_per_case_ratio: "Controls per case (k)",
    n_cases_recruited: "Available cases (recruited)",
    n_cases_analyzable: "Analysable cases (after dropout)",
    n_controls_analyzable: "Analysable controls (after dropout)",
    // Correlation / RM-ANOVA / Survival
    expected_r: "Expected correlation (r)",
    k_groups: "Number of groups (k)",
    hazard_ratio: "Expected hazard ratio (HR)",
    overall_event_rate: "Expected overall event rate",
    allocation_ratio: "Allocation ratio (n_b / n_a)",
  };

  var CONSTANT_LABELS = {
    Z_alpha_over_2: "Z(α/2)",
    Z_beta: "Z(β)  (from desired power)",
    p_bar: "Pooled proportion p̄",
    p_q: "p × (1 − p)",
    effect_size_diff: "Effect size (absolute difference)",
    cohens_d: "Cohen's d",
    effect_size_dz: "Cohen's d_z (paired)",
    // Repeated measures
    variance_factor: "Variance factor (1 + (m−1)ρ) / m",
    // Linear regression
    cohens_f_squared: "Cohen's f²",
    // Prediction model
    events_available: "Expected events (n × event_rate)",
    events_per_variable: "Events per variable (target)",
    // Kappa
    kappa_variance_factor: "κ × (1 − κ)",
    // ROC / AUC
    Q1_hanley: "Q₁ (Hanley-McNeil)",
    Q2_hanley: "Q₂ (Hanley-McNeil)",
    auc_variance: "Var(AUC)",
    // Correlation / RM-ANOVA / Survival
    fisher_z_r: "Fisher's z(r) = arctanh(r)",
    variance_reduction: "Variance reduction factor (1 − ρ)",
    ln_hazard_ratio: "ln(HR)",
    required_events: "Required events",
    expected_events: "Expected events (n × event_rate)",
    n_group_a: "Allocated to group A",
    n_group_b: "Allocated to group B",
  };

  function fillTable(testid, obj, labels) {
    var tbody = document.querySelector('[data-testid="' + testid + '"] tbody');
    tbody.innerHTML = "";
    Object.keys(obj).forEach(function (key) {
      var tr = document.createElement("tr");
      var th = document.createElement("th");
      th.textContent = labels[key] || key;
      var td = document.createElement("td");
      td.textContent = formatValue(obj[key]);
      tr.appendChild(th);
      tr.appendChild(td);
      tbody.appendChild(tr);
    });
  }

  function formatValue(value) {
    if (typeof value === "number") {
      if (Number.isInteger(value)) return String(value);
      return value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
    }
    return String(value);
  }

  function setText(testid, text) {
    var el = document.querySelector('[data-testid="' + testid + '"]');
    if (el) el.textContent = text;
  }

  function titleCase(s) {
    if (!s) return "—";
    return s.replace(/(^|\s|_)([a-z])/g, function (_, sep, ch) {
      return (sep === "_" ? " " : sep) + ch.toUpperCase();
    });
  }

  function goToStep(step, formulaKey) {
    // Hide every step section
    [0, "A", "C", 1, 2, 3].forEach(function (n) {
      var section = document.querySelector('[data-step="' + n + '"]');
      if (section) section.hidden = String(n) !== String(step);
    });
    // Indicator (1/2/3): Step 0/A/C all map to indicator 1; otherwise normal
    var indicatorStep = (step === 2 || step === 3) ? step : 1;
    [1, 2, 3].forEach(function (n) {
      var indicator = document.querySelector('[data-step-indicator="' + n + '"]');
      if (indicator) {
        indicator.classList.toggle("is-active", n === indicatorStep);
        indicator.classList.toggle("is-complete", n < indicatorStep);
      }
    });
    if (step === 2) {
      renderFormulaFields(formulaKey || state.selectedFormula || "two_means");
      document.getElementById("parameters-error").hidden = true;
      // Pre-select the dropout dropdown to the analyzer's smart suggestion
      // (longitudinal/cohort → 10%, RCT → 15%, cross-sectional → 0%).
      // Only auto-apply on first entry; if the user has already changed it
      // (i.e. it's anything other than "0") we leave their pick alone.
      if (state.lastAnalysis && typeof state.lastAnalysis.suggested_dropout === "number") {
        var dropEl = document.getElementById("dropout");
        if (dropEl && dropEl.value === "0") {
          dropEl.value = snapDropoutToOption(state.lastAnalysis.suggested_dropout);
        }
      }
    }
    window.scrollTo({ top: document.querySelector(".calc-shell").offsetTop - 24, behavior: "smooth" });
  }

  // -----------------------------------------------------------------------
  // "Recommended statistical formula" callout — always visible at the top
  // of Step 3. Shows the formula name, what it's ideal for, the analyzer's
  // rationale (if the user came through the analyse flow), and the
  // statistical assumptions (α, power, dropout, mode).
  // -----------------------------------------------------------------------
  function renderRecommendedPanel(data, isReverse) {
    var key = data.formula;
    var spec = FORMULAS[key] || {};
    var label = data.formula_label || spec.label || key;

    setText("text-ideal-formula-name", label);
    setText(
      "text-ideal-formula-use",
      "Ideal for: " +
        (IDEAL_FOR[key] ||
          "the statistical question described in your objective.")
    );

    // Rationale only shown when it came from the analyzer (i.e. the user
    // went through "Analyse objective" rather than picking manually).
    var rationaleEl = document.getElementById("result-recommended-rationale");
    var rationale = state.lastAnalysis && state.lastAnalysis.rationale;
    var came = state.lastAnalysis && state.lastAnalysis.suggested_formula === key;
    if (rationaleEl) {
      if (came && rationale) {
        rationaleEl.hidden = false;
        rationaleEl.textContent = "Why this formula was selected: " + rationale;
      } else {
        rationaleEl.hidden = true;
        rationaleEl.textContent = "";
      }
    }

    var inputs = data.inputs || {};
    var bits = [];
    if (inputs.alpha != null) {
      bits.push("two-sided α = " + inputs.alpha);
    }
    if (inputs.power != null) {
      bits.push("power = " + Math.round(inputs.power * 100) + "%");
    }
    var dropoutVal =
      inputs.dropout_rate != null ? inputs.dropout_rate : inputs.dropout;
    if (dropoutVal != null) {
      bits.push(
        "dropout adjustment = " + Math.round(dropoutVal * 100) + "%"
      );
    }
    bits.push(isReverse ? "back-calculated effect mode" : "forward (n) mode");
    setText(
      "text-ideal-formula-assumptions",
      "Assumptions: " + bits.join(" · ")
    );
  }

  // -----------------------------------------------------------------------
  // Downloadable HTML report. Generates a self-contained .html file the
  // user can open in any browser, print to PDF from Chrome/Safari, or
  // attach to a proposal. We render HTML rather than PDF/DOCX to keep the
  // calculator a single static page (no extra backend dependencies).
  // -----------------------------------------------------------------------
  function downloadReport(data, isReverse) {
    var key = data.formula;
    var spec = FORMULAS[key] || {};
    var label = data.formula_label || spec.label || key;
    var ideal = IDEAL_FOR[key] || "";
    var rationale =
      state.lastAnalysis &&
      state.lastAnalysis.suggested_formula === key &&
      state.lastAnalysis.rationale;
    var objective = state.objective || "";

    var inputsRows = renderTableRowsForReport(
      data.inputs || {},
      INPUT_LABELS
    );
    var constantsRows = renderTableRowsForReport(
      data.constants || {},
      CONSTANT_LABELS
    );

    var headlineHtml;
    if (isReverse) {
      var cards = (data.headline || [])
        .map(function (s) {
          return (
            '<div class="card"><div class="card-label">' +
            escapeHtml(s.label) +
            '</div><div class="card-value">' +
            escapeHtml(s.value) +
            "</div>" +
            (s.sublabel
              ? '<div class="card-sub">' + escapeHtml(s.sublabel) + "</div>"
              : "") +
            "</div>"
          );
        })
        .join("");
      headlineHtml =
        '<h2>Minimum detectable effect</h2><div class="cards">' +
        cards +
        "</div>";
    } else {
      headlineHtml =
        '<h2>Required sample size</h2><div class="cards">' +
        '<div class="card"><div class="card-label">Per group</div><div class="card-value">' +
        escapeHtml(formatN(data.n_per_group, data.number_of_groups)) +
        "</div></div>" +
        '<div class="card"><div class="card-label">Total (statistically required)</div><div class="card-value">' +
        escapeHtml(String(data.total_n)) +
        "</div></div>" +
        '<div class="card"><div class="card-label">Adjusted for dropout</div><div class="card-value">' +
        escapeHtml(String(data.adjusted_n)) +
        "</div></div>" +
        "</div>";
    }

    var notes = (data.notes || [])
      .map(function (n) { return "<li>" + escapeHtml(n) + "</li>"; })
      .join("");
    var warnings = (data.warnings || [])
      .map(function (w) { return "<li>" + escapeHtml(w) + "</li>"; })
      .join("");

    var rationaleBlock = rationale
      ? '<p class="rationale"><strong>Why this formula was selected:</strong> ' +
        escapeHtml(rationale) +
        "</p>"
      : "";
    var objectiveBlock = objective
      ? '<section><h2>Research objective</h2><p>' +
        escapeHtml(objective) +
        "</p></section>"
      : "";

    var generated = new Date().toISOString().replace("T", " ").slice(0, 16) + " UTC";
    var html =
      '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
      "<title>MedRAS — Sample Size Report (" + escapeHtml(label) + ")</title>" +
      "<style>" +
      "body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#0f172a;max-width:780px;margin:32px auto;padding:0 24px;line-height:1.5;}" +
      "h1{font-size:24px;margin:0 0 4px;}h2{font-size:18px;margin:28px 0 8px;border-bottom:1px solid #e2e8f0;padding-bottom:4px;}h3{font-size:15px;margin:16px 0 6px;color:#334155;}" +
      ".meta{color:#64748b;font-size:13px;margin:0 0 24px;}" +
      ".callout{background:#eff6ff;border-left:4px solid #2563eb;padding:14px 18px;border-radius:6px;margin:16px 0;}" +
      ".callout strong{display:block;color:#1e3a8a;margin-bottom:4px;}" +
      ".cards{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0;}" +
      ".card{flex:1;min-width:160px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px 14px;}" +
      ".card-label{font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.04em;}" +
      ".card-value{font-size:22px;font-weight:600;color:#0f172a;margin-top:4px;}" +
      ".card-sub{font-size:12px;color:#64748b;margin-top:2px;}" +
      "code,.formula{background:#f1f5f9;padding:6px 10px;border-radius:4px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;display:inline-block;}" +
      "table{border-collapse:collapse;width:100%;margin-top:8px;}td,th{text-align:left;padding:6px 10px;border-bottom:1px solid #e2e8f0;font-size:14px;}" +
      "th{color:#475569;font-weight:600;background:#f8fafc;}" +
      ".rationale{background:#fef9c3;padding:10px 14px;border-radius:6px;color:#713f12;}" +
      "ul{margin:6px 0 12px 22px;}li{margin:4px 0;}" +
      "footer{margin-top:40px;color:#94a3b8;font-size:12px;border-top:1px solid #e2e8f0;padding-top:12px;}" +
      "@media print{body{margin:0;padding:18px;}.cards{break-inside:avoid;}}" +
      "</style></head><body>" +
      "<h1>MedRAS — Sample Size Report</h1>" +
      '<p class="meta">Generated ' + generated + " · Module 02 · Sample Size Calculator</p>" +
      objectiveBlock +
      '<section class="callout"><strong>Recommended statistical formula</strong>' +
      "<div><strong style=\"color:#0f172a;font-weight:600;\">" + escapeHtml(label) + "</strong></div>" +
      (ideal ? "<p style=\"margin:6px 0 0;\"><em>Ideal for:</em> " + escapeHtml(ideal) + "</p>" : "") +
      rationaleBlock +
      "</section>" +
      "<section>" + headlineHtml + "</section>" +
      "<section><h2>Formula</h2><div class=\"formula\">" +
      escapeHtml(data.formula_expression || "") +
      "</div></section>" +
      "<section><h2>Inputs you provided</h2><table><thead><tr><th>Parameter</th><th>Value</th></tr></thead><tbody>" +
      inputsRows +
      "</tbody></table></section>" +
      "<section><h2>Constants used in the calculation</h2><table><thead><tr><th>Constant</th><th>Value</th></tr></thead><tbody>" +
      constantsRows +
      "</tbody></table></section>" +
      (notes ? "<section><h2>Notes</h2><ul>" + notes + "</ul></section>" : "") +
      (warnings ? "<section><h2>Warnings</h2><ul>" + warnings + "</ul></section>" : "") +
      "<footer>MedRAS — Medical Research Acceleration System. " +
      "All statistics computed by validated formulas, not language models. " +
      "Cite this report's formula and constants in your protocol's sample-size justification." +
      "</footer></body></html>";

    var blob = new Blob([html], { type: "text/html;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var fname =
      "medras-sample-size-" +
      key +
      "-" +
      new Date().toISOString().slice(0, 10) +
      ".html";
    var a = document.createElement("a");
    a.href = url;
    a.download = fname;
    document.body.appendChild(a);
    a.click();
    setTimeout(function () {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 0);
  }

  function renderTableRowsForReport(obj, labelMap) {
    var keys = Object.keys(obj || {});
    if (!keys.length) {
      return '<tr><td colspan="2"><em>None</em></td></tr>';
    }
    return keys
      .map(function (k) {
        var v = obj[k];
        if (typeof v === "number") {
          v = Number.isInteger(v) ? String(v) : v.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
        }
        return (
          "<tr><td>" +
          escapeHtml(labelMap[k] || k) +
          "</td><td>" +
          escapeHtml(String(v)) +
          "</td></tr>"
        );
      })
      .join("");
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }
})();
