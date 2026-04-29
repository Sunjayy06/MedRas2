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
  };

  // -----------------------------------------------------------------------
  // App state
  // -----------------------------------------------------------------------

  var state = {
    objective: "",
    selectedFormula: null,
    lastAnalysis: null,
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
      var formula = state.lastAnalysis ? state.lastAnalysis.suggested_formula : "two_means";
      goToStep(2, formula);
    });
    document.getElementById("override-btn").addEventListener("click", function () {
      goToStep(2, state.lastAnalysis ? state.lastAnalysis.suggested_formula : "two_means");
    });
  }

  function bindStep2() {
    document.getElementById("formula-select").addEventListener("change", function (event) {
      renderFormulaFields(event.target.value);
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
  }

  // Wipe every researcher-entered value so the next study starts clean.
  // Per-formula fields are rebuilt fresh by renderFormulaFields(); we only
  // need to reset the static (always-present) inputs here.
  function resetCalculator() {
    state.objective = "";
    state.selectedFormula = null;
    state.lastAnalysis = null;
    var ids = ["objective", "expected"];
    ids.forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.value = "";
    });
    document.getElementById("alpha").value = "0.05";
    document.getElementById("power").value = "0.80";
    document.getElementById("dropout").value = "0";
    var panel = document.getElementById("analysis-panel");
    if (panel) panel.hidden = true;
    var err = document.getElementById("parameters-error");
    if (err) err.hidden = true;
    var formulaFields = document.getElementById("formula-fields");
    if (formulaFields) formulaFields.innerHTML = "";
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

    fetch("/api/sample-size/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ objective: objective }),
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
    setText("text-detected-groups", String(data.detected_groups));
    setText("text-outcome-type", titleCase(data.outcome_type));
    setText("text-study-design", titleCase(data.study_design));
    setText("text-suggested-formula", FORMULAS[data.suggested_formula].label);
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
  }

  function sourceLabel(source) {
    if (source === "llm") return "AI assistant";
    if (source === "llm+heuristic_fallback") return "Rule-based (AI unavailable)";
    return "Rule-based";
  }

  // -----------------------------------------------------------------------
  // Step 2 — parameters
  // -----------------------------------------------------------------------

  function renderFormulaFields(formulaKey) {
    state.selectedFormula = formulaKey;
    var spec = FORMULAS[formulaKey];
    document.getElementById("formula-select").value = formulaKey;
    document.getElementById("formula-summary").textContent = spec.expression;

    var container = document.getElementById("formula-fields");
    container.innerHTML = "";
    var row = document.createElement("div");
    row.className = "field-row";
    spec.fields.forEach(function (field) {
      row.appendChild(buildFieldEl(field));
    });
    container.appendChild(row);

    // Power field is irrelevant for descriptive (single-sample) formulas.
    var powerField = document.querySelector("[data-power-field]");
    if (powerField) {
      powerField.style.display = spec.usesPower ? "" : "none";
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

  function onCalculate() {
    var spec = FORMULAS[state.selectedFormula];
    var params = {};
    var missing = [];
    spec.fields.forEach(function (field) {
      var raw = document.getElementById("param-" + field.key).value;
      if (raw === "" || raw === null) {
        missing.push(field.label);
        return;
      }
      var num = Number(raw);
      if (Number.isNaN(num)) {
        missing.push(field.label);
        return;
      }
      params[field.key] = num;
    });

    var alpha = Number(document.getElementById("alpha").value);
    var dropout = Number(document.getElementById("dropout").value);
    params.alpha = alpha;
    params.dropout = dropout;
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

    var expectedRaw = document.getElementById("expected").value.trim();
    var expected = expectedRaw === "" ? null : Math.max(1, Math.floor(Number(expectedRaw)));

    var btn = document.getElementById("calculate-btn");
    btn.disabled = true;
    btn.textContent = "Calculating…";

    var body = {
      formula: state.selectedFormula,
      parameters: params,
    };
    if (expected !== null && !Number.isNaN(expected)) {
      body.expected_sample_size = expected;
    }

    fetch("/api/sample-size/calculate", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          if (!resp.ok) throw new Error(data.detail || "Calculation failed.");
          return data;
        });
      })
      .then(function (data) {
        renderResult(data);
        goToStep(3);
      })
      .catch(function (err) {
        errEl.hidden = false;
        errEl.textContent = err.message || "Calculation failed.";
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = "Calculate sample size";
      });
  }

  // -----------------------------------------------------------------------
  // Step 3 — result
  // -----------------------------------------------------------------------

  function renderResult(data) {
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
  };

  var CONSTANT_LABELS = {
    Z_alpha_over_2: "Z(α/2)",
    Z_beta: "Z(β)  (from desired power)",
    p_bar: "Pooled proportion p̄",
    p_q: "p × (1 − p)",
    effect_size_diff: "Effect size (absolute difference)",
    cohens_d: "Cohen's d",
    effect_size_dz: "Cohen's d_z (paired)",
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
    }
    window.scrollTo({ top: document.querySelector(".calc-shell").offsetTop - 24, behavior: "smooth" });
  }
})();
