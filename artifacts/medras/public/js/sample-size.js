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
  };

  // -----------------------------------------------------------------------
  // Boot
  // -----------------------------------------------------------------------

  document.addEventListener("DOMContentLoaded", function () {
    bindStep1();
    bindStep2();
    bindStep3();
  });

  function bindStep1() {
    document.getElementById("analyze-btn").addEventListener("click", onAnalyze);
    document.getElementById("manual-btn").addEventListener("click", function () {
      state.lastAnalysis = null;
      goToStep(2, "two_means");
    });
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
    document.getElementById("back-to-step-1").addEventListener("click", function () {
      goToStep(1);
    });
  }

  function bindStep3() {
    document.getElementById("back-to-step-2").addEventListener("click", function () {
      goToStep(2, state.selectedFormula);
    });
    document.getElementById("restart-btn").addEventListener("click", function () {
      resetCalculator();
      goToStep(1);
    });
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
      alert("Please write at least one full sentence describing your objective.");
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
        alert(err.message || "Could not analyse the objective.");
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

    // Update the calculate button label to match the mode.
    var calcBtn = document.getElementById("calculate-btn");
    if (calcBtn && !calcBtn.disabled) {
      calcBtn.textContent = state.reverseMode
        ? "Calculate detectable effect"
        : "Calculate sample size";
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

    var url = isReverse
      ? "/api/sample-size/reverse"
      : "/api/sample-size/calculate";
    var body = { formula: state.selectedFormula, parameters: params };
    if (!isReverse) {
      var expectedRaw = document.getElementById("expected").value.trim();
      var expected =
        expectedRaw === ""
          ? null
          : Math.max(1, Math.floor(Number(expectedRaw)));
      if (expected !== null && !Number.isNaN(expected)) {
        body.expected_sample_size = expected;
      }
    }
    var restoreLabel = isReverse
      ? "Calculate detectable effect"
      : "Calculate sample size";

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
          renderReverseResult(data);
        } else {
          renderResult(data);
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
    // Forward-mode layout: hide reverse panel, show the standard headline.
    var reversePanel = document.getElementById("result-reverse");
    if (reversePanel) reversePanel.hidden = true;
    var fwdHeadline = document.getElementById("result-forward-headline");
    if (fwdHeadline) fwdHeadline.style.display = "";
    var heading = document.getElementById("result-heading");
    if (heading) heading.textContent = "3. Required sample size";

    state.lastResult = data;
    renderRecommendedPanel(data, false);

    setText("text-result-formula", data.formula_label + " · " + data.formula_expression);
    setText("text-n-per-group", formatN(data.n_per_group, data.number_of_groups));
    setText("text-total-n", String(data.total_n));
    setText("text-adjusted-n", String(data.adjusted_n));
    setText("text-formula-expression", data.formula_expression);

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
  }

  function formatN(nPerGroup, numGroups) {
    if (numGroups <= 1) return String(nPerGroup);
    return nPerGroup + "  (×" + numGroups + " groups)";
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

    // Hide forward-only sections, show the reverse panel.
    document.getElementById("result-forward-headline").style.display = "none";
    document.getElementById("result-comparison").hidden = true;
    document.getElementById("result-reverse").hidden = false;

    setText("text-formula-expression", data.formula_expression);

    // Render headline cards from the API response.
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
    [1, 2, 3].forEach(function (n) {
      var section = document.querySelector('[data-step="' + n + '"]');
      if (section) section.hidden = n !== step;
      var indicator = document.querySelector('[data-step-indicator="' + n + '"]');
      if (indicator) {
        indicator.classList.toggle("is-active", n === step);
        indicator.classList.toggle("is-complete", n < step);
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
