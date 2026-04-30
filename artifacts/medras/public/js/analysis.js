/* MedRAS — Statistical Analysis Engine (frontend state machine)
 *
 * Single-page wizard. Talks to /api/stats/* endpoints. Keeps minimal state
 * in `state` and re-renders panels on every transition.
 */
"use strict";

const API_BASE = "/api/stats";

const state = {
  jobId: null,
  summary: null,
  columns: [],
  classifications: [],
  preview: [],
  result: null,
  currentStep: 1,
};

/* ------------------------------------------------------------------ */
/*  Generic helpers                                                    */
/* ------------------------------------------------------------------ */

function $(sel, root = document) {
  return root.querySelector(sel);
}
function $$(sel, root = document) {
  return Array.from(root.querySelectorAll(sel));
}

function setStatus(el, message, level = "loading") {
  el.textContent = message;
  el.dataset.state = level;
}

function showPanel(step) {
  state.currentStep = step;
  ["1", "2", "4", "6"].forEach((s) => {
    const panel = document.getElementById(`panel-${s}`);
    if (panel) panel.classList.toggle("is-hidden", s !== String(step));
  });
  $$(".ana-step").forEach((node) => {
    const n = Number(node.dataset.step);
    node.classList.toggle("is-active", n === step);
    node.classList.toggle("is-done", n < step && !node.classList.contains("is-todo"));
  });
  // Scroll to top of the new panel for clarity.
  const target = document.getElementById(`panel-${step}`);
  if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body && body.detail) detail = body.detail;
    } catch (_e) {
      /* ignore parse errors */
    }
    throw new Error(detail);
  }
  return res.json();
}

const TYPE_LABELS = {
  scale: "Scale",
  ordinal: "Ordinal",
  nominal: "Nominal",
  date: "Date",
  id: "ID",
  exclude: "Exclude",
};

function typeBadge(t) {
  const safe = TYPE_LABELS[t] ? t : "exclude";
  return `<span class="ana-type-badge t-${safe}">${TYPE_LABELS[safe]}</span>`;
}

/* ------------------------------------------------------------------ */
/*  Step 1 — data source                                               */
/* ------------------------------------------------------------------ */

function bindStep1() {
  $('[data-action="open-file"]').addEventListener("click", () => {
    $("#file-input").click();
  });

  $("#file-input").addEventListener("change", async (ev) => {
    const file = ev.target.files && ev.target.files[0];
    if (!file) return;
    const status = $("#upload-status");
    setStatus(status, `Uploading ${file.name}…`, "loading");
    const form = new FormData();
    form.append("file", file);
    try {
      const data = await api("/upload", { method: "POST", body: form });
      ingestDataset(data);
      setStatus(status, `Loaded ${data.summary.rows} rows × ${data.summary.cols} columns.`, "success");
    } catch (err) {
      setStatus(status, err.message, "error");
    } finally {
      ev.target.value = ""; // allow re-uploading same file
    }
  });

  $('[data-action="generate-dummy"]').addEventListener("click", async () => {
    const status = $("#upload-status");
    const payload = {
      template: $("#dummy-template").value,
      n_patients: Number($("#dummy-n").value) || 150,
      n_groups: Number($("#dummy-groups").value) || 2,
      missing_pct: 5,
    };
    setStatus(status, `Generating ${payload.template} dataset…`, "loading");
    try {
      const data = await api("/generate-dummy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      ingestDataset(data);
      setStatus(status, `Generated ${data.summary.rows} rows × ${data.summary.cols} columns.`, "success");
    } catch (err) {
      setStatus(status, err.message, "error");
    }
  });
}

function ingestDataset(data) {
  state.jobId = data.job_id;
  state.summary = data.summary;
  state.columns = data.columns;
  state.classifications = data.classifications;
  state.preview = data.preview;
  renderClassifyTable();
  renderPreviewTable();
  renderDatasetMeta();
  showPanel(2);
}

/* ------------------------------------------------------------------ */
/*  Step 2 — classify                                                  */
/* ------------------------------------------------------------------ */

function renderDatasetMeta() {
  const meta = state.summary || {};
  // All values originate from user-supplied uploads — escape before insertion.
  const filename = escapeHtml(meta.filename || "Dataset");
  const rows = Number(meta.rows) || 0;
  const cols = Number(meta.cols) || 0;
  const sheet = meta.selected_sheet
    ? `<span>Sheet: <strong>${escapeHtml(meta.selected_sheet)}</strong></span>`
    : "";
  $("#dataset-meta").innerHTML = `
    <span><strong>${filename}</strong></span>
    <span>${rows} rows · ${cols} columns</span>
    ${sheet}
  `;
}

function renderClassifyTable() {
  const tbody = $("#classify-table tbody");
  const types = ["scale", "ordinal", "nominal", "date", "id", "exclude"];
  tbody.innerHTML = state.classifications
    .map((c, i) => {
      const opts = types
        .map((t) => `<option value="${t}" ${c.detected_type === t ? "selected" : ""}>${TYPE_LABELS[t]}</option>`)
        .join("");
      const samples = (c.sample_values || []).slice(0, 3).map((v) => `<code>${escapeHtml(String(v))}</code>`).join(", ");
      return `
        <tr data-testid="row-classify-${i}">
          <td><strong>${escapeHtml(c.column)}</strong></td>
          <td>
            <select class="var-type" data-col="${escapeHtml(c.column)}" data-testid="select-type-${i}">${opts}</select>
          </td>
          <td>${c.unique_count}</td>
          <td>${c.missing} <small>(${c.missing_pct}%)</small></td>
          <td>${samples || '<span style="color:var(--color-text-muted)">—</span>'}</td>
          <td><small>${escapeHtml(c.reason)}</small></td>
        </tr>
      `;
    })
    .join("");

  $$("#classify-table .var-type").forEach((sel) => {
    sel.addEventListener("change", (e) => {
      const col = e.target.dataset.col;
      const t = e.target.value;
      const rec = state.classifications.find((x) => x.column === col);
      if (rec) {
        rec.detected_type = t;
        rec.reason = `Manually set to ${TYPE_LABELS[t]}.`;
      }
    });
  });
}

function renderPreviewTable() {
  const head = $("#preview-table thead");
  const body = $("#preview-table tbody");
  head.innerHTML = `<tr>${state.columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr>`;
  body.innerHTML = state.preview
    .map(
      (row) =>
        `<tr>${state.columns
          .map((c) => `<td>${row[c] == null ? '<span style="color:var(--color-text-muted)">—</span>' : escapeHtml(String(row[c]))}</td>`)
          .join("")}</tr>`,
    )
    .join("");
}

function bindStep2() {
  $('[data-action="confirm-classify"]').addEventListener("click", async () => {
    try {
      await api("/classify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: state.jobId,
          overrides: state.classifications.map((c) => ({ column: c.column, detected_type: c.detected_type })),
        }),
      });
      buildAnalysisForm();
      showPanel(4);
    } catch (err) {
      alert(`Could not save classifications: ${err.message}`);
    }
  });

  $$('[data-action="restart"]').forEach((btn) => btn.addEventListener("click", restart));
}

/* ------------------------------------------------------------------ */
/*  Step 4 — analysis                                                  */
/* ------------------------------------------------------------------ */

function buildAnalysisForm() {
  const outcome = $("#select-outcome");
  const group = $("#select-group");
  const eligibleOutcomes = state.classifications.filter((c) =>
    ["scale", "ordinal", "nominal"].includes(c.detected_type),
  );
  const eligibleGroups = state.classifications.filter((c) =>
    ["scale", "ordinal", "nominal"].includes(c.detected_type),
  );

  outcome.innerHTML = eligibleOutcomes
    .map((c) => `<option value="${escapeHtml(c.column)}">${escapeHtml(c.column)} — ${TYPE_LABELS[c.detected_type]}</option>`)
    .join("");
  group.innerHTML =
    `<option value="">— none (descriptives only) —</option>` +
    eligibleGroups
      .map((c) => `<option value="${escapeHtml(c.column)}">${escapeHtml(c.column)} — ${TYPE_LABELS[c.detected_type]}</option>`)
      .join("");

  // Smart default: pick first scale outcome and first nominal group if available.
  const firstScale = eligibleOutcomes.find((c) => c.detected_type === "scale");
  if (firstScale) outcome.value = firstScale.column;
  const firstNominal = eligibleGroups.find((c) => c.detected_type === "nominal" && c.column !== outcome.value);
  if (firstNominal) group.value = firstNominal.column;

  updateRecommendation();
  // Listeners are bound once in DOMContentLoaded — no rebinding here.
}

function predictTest(outcomeCol, groupCol) {
  const o = state.classifications.find((c) => c.column === outcomeCol);
  const g = groupCol ? state.classifications.find((c) => c.column === groupCol) : null;
  if (!o) return null;
  if (!g) {
    return o.detected_type === "nominal"
      ? "Frequency table only (no group provided)"
      : "Descriptive statistics only (no group provided)";
  }
  if (o.detected_type === "scale" || o.detected_type === "ordinal") {
    if (g.detected_type === "nominal" || g.detected_type === "ordinal") {
      // Group cardinality only known after data — compute live.
      const row = state.preview;
      const seen = new Set(row.map((r) => r[groupCol]).filter((x) => x != null));
      const k = seen.size; // approximate from preview only
      if (k <= 2) {
        return "Independent t-test or Mann-Whitney U (chosen by normality)";
      }
      return "One-way ANOVA or Kruskal-Wallis (chosen by normality)";
    }
    if (g.detected_type === "scale" || g.detected_type === "ordinal") {
      return "Pearson or Spearman correlation (chosen by normality)";
    }
  }
  if (o.detected_type === "nominal") {
    if (g.detected_type === "nominal" || g.detected_type === "ordinal") {
      return "Chi-square test (Fisher's exact if expected counts are small)";
    }
  }
  return "No appropriate test for this combination — try different variables";
}

function updateRecommendation() {
  const o = $("#select-outcome").value;
  const g = $("#select-group").value || null;
  const test = predictTest(o, g);
  const callout = $("#recommendation");
  if (!test) {
    callout.innerHTML = "";
    return;
  }
  callout.innerHTML = `<strong>Likely test:</strong> ${escapeHtml(test)}. Final choice depends on normality of the actual values.`;
}

function bindStep4() {
  // Bind once. The select elements are static in the HTML; only their
  // <option> children get rebuilt by buildAnalysisForm().
  $("#select-outcome").addEventListener("change", updateRecommendation);
  $("#select-group").addEventListener("change", updateRecommendation);
  $('[data-action="back-to-classify"]').addEventListener("click", () => showPanel(2));
  $('[data-action="run-analysis"]').addEventListener("click", async () => {
    const payload = {
      job_id: state.jobId,
      outcome: $("#select-outcome").value,
      group: $("#select-group").value || null,
      alpha: Number($("#select-alpha").value),
    };
    const callout = $("#recommendation");
    callout.innerHTML = `<strong>Running analysis…</strong>`;
    try {
      const result = await api("/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      state.result = result;
      renderResults(result);
      showPanel(6);
    } catch (err) {
      callout.innerHTML = `<strong style="color:var(--color-danger)">Error:</strong> ${escapeHtml(err.message)}`;
    }
  });
}

/* ------------------------------------------------------------------ */
/*  Step 6 — results                                                   */
/* ------------------------------------------------------------------ */

function renderResults(r) {
  const sig = r.p_value != null && r.p_value < (r.alpha || 0.05);
  const pDisplay = r.p_value == null ? "—" : (r.p_value < 0.001 ? "p < 0.001" : `p = ${r.p_value.toFixed(3)}`);
  const headline = `
    <div class="res-headline ${sig ? "sig" : "notsig"}" data-testid="res-headline">
      <div>
        <h3>${escapeHtml(r.test || "Result")}</h3>
        <p class="res-design">${escapeHtml(r.study_design || "")}</p>
      </div>
      <div class="res-pvalue" data-testid="res-pvalue">${escapeHtml(pDisplay)}</div>
    </div>
  `;

  const stats = renderStatGrid(r);
  const groups = renderGroupTable(r);
  const assumptions = renderAssumptions(r);
  const interpretation = `
    <div class="res-section">
      <h4>Interpretation</h4>
      <div class="res-interp" data-testid="res-interpretation">${escapeHtml(r.interpretation || "")}</div>
    </div>
  `;

  $("#results-body").innerHTML = headline + stats + groups + assumptions + interpretation;
}

function renderStatGrid(r) {
  const cards = [];
  if (r.statistic != null) cards.push(stat("Statistic", r.statistic));
  if (r.df != null) cards.push(stat("Degrees of freedom", r.df));
  if (r.effect_size && r.effect_size.value != null)
    cards.push(stat(r.effect_size.name, r.effect_size.value));
  if (r.achieved_power != null) cards.push(stat("Achieved power", `${Math.round(r.achieved_power * 100)}%`));
  if (cards.length === 0) return "";
  return `<div class="res-section"><h4>Test statistics</h4><div class="res-stat-grid">${cards.join("")}</div></div>`;
}
function stat(label, value) {
  return `<div class="res-stat"><div class="res-stat-label">${escapeHtml(label)}</div><div class="res-stat-value">${escapeHtml(String(value))}</div></div>`;
}

function renderGroupTable(r) {
  if (!Array.isArray(r.groups) || r.groups.length === 0) {
    if (r.table) return renderCrossTable(r.table);
    return "";
  }
  // Continuous summaries.
  if (r.groups[0].mean !== undefined) {
    return `<div class="res-section"><h4>Descriptive statistics</h4>
      <div class="ana-table-wrap"><table class="ana-table" data-testid="table-groups">
        <thead><tr><th>Group</th><th>n</th><th>Mean (SD)</th><th>Median (IQR)</th><th>Min – Max</th></tr></thead>
        <tbody>${r.groups
          .map(
            (g) => `<tr>
              <td><strong>${escapeHtml(g.name)}</strong></td>
              <td>${g.n}</td>
              <td>${fmtMean(g)}</td>
              <td>${fmtMedian(g)}</td>
              <td>${g.min ?? "—"} – ${g.max ?? "—"}</td>
            </tr>`,
          )
          .join("")}</tbody>
      </table></div></div>`;
  }
  // Categorical descriptives.
  if (r.groups[0].counts) {
    const g = r.groups[0];
    const items = Object.entries(g.counts).map(([k, v]) => `<tr><td>${escapeHtml(k)}</td><td>${v}</td><td>${(g.percentages?.[k] ?? 0).toFixed(1)}%</td></tr>`);
    return `<div class="res-section"><h4>Frequencies</h4>
      <div class="ana-table-wrap"><table class="ana-table">
        <thead><tr><th>Value</th><th>Count</th><th>%</th></tr></thead>
        <tbody>${items.join("")}</tbody>
      </table></div></div>`;
  }
  return "";
}
function fmtMean(g) {
  if (g.mean == null) return "—";
  return `${g.mean} (${g.sd ?? "—"})`;
}
function fmtMedian(g) {
  if (g.median == null) return "—";
  return `${g.median} (${g.q1 ?? "—"} – ${g.q3 ?? "—"})`;
}
function renderCrossTable(t) {
  const head = `<tr><th></th>${t.cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}<th>Total</th></tr>`;
  const rows = t.rows
    .map((r, i) => {
      const counts = t.counts[i];
      const total = counts.reduce((a, b) => a + b, 0);
      return `<tr><td><strong>${escapeHtml(r)}</strong></td>${counts.map((n) => `<td>${n}</td>`).join("")}<td>${total}</td></tr>`;
    })
    .join("");
  return `<div class="res-section"><h4>Crosstab</h4>
    <div class="ana-table-wrap"><table class="ana-table" data-testid="table-crosstab">
      <thead>${head}</thead><tbody>${rows}</tbody>
    </table></div></div>`;
}

function renderAssumptions(r) {
  if (!r.assumptions) return "";
  const a = r.assumptions;
  const blocks = [];
  if (a.normality) {
    Object.entries(a.normality).forEach(([k, v]) => {
      if (!v || !v.applicable) return;
      const pill = v.is_normal ? '<span class="res-pill ok">normal</span>' : '<span class="res-pill bad">not normal</span>';
      blocks.push(`<li><strong>${escapeHtml(k)}</strong>: ${escapeHtml(v.test)} W = ${v.statistic.toFixed(3)}, p = ${v.p_value.toFixed(4)} ${pill}</li>`);
    });
  }
  if (a.equal_variance) {
    const ev = a.equal_variance;
    if (ev.statistic != null) {
      const pill = ev.equal ? '<span class="res-pill ok">equal variance</span>' : '<span class="res-pill bad">unequal variance</span>';
      blocks.push(`<li><strong>Levene's test</strong>: F = ${ev.statistic}, p = ${ev.p_value} ${pill}</li>`);
    }
  }
  if (a.min_expected != null) {
    blocks.push(`<li><strong>Minimum expected count</strong>: ${a.min_expected}${a.fisher_used ? ' — Fisher\'s exact used' : ""}</li>`);
  }
  if (blocks.length === 0) return "";
  return `<div class="res-section"><h4>Assumptions checked</h4><ul style="margin:0;padding-left:18px;font-size:14px;line-height:1.7">${blocks.join("")}</ul></div>`;
}

function bindStep6() {
  $('[data-action="back-to-analysis"]').addEventListener("click", () => showPanel(4));
}

/* ------------------------------------------------------------------ */
/*  Restart                                                            */
/* ------------------------------------------------------------------ */

function restart() {
  state.jobId = null;
  state.summary = null;
  state.columns = [];
  state.classifications = [];
  state.preview = [];
  state.result = null;
  setStatus($("#upload-status"), "", "loading");
  showPanel(1);
}

/* ------------------------------------------------------------------ */
/*  Tiny utils                                                         */
/* ------------------------------------------------------------------ */

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

document.addEventListener("DOMContentLoaded", () => {
  bindStep1();
  bindStep2();
  bindStep4();
  bindStep6();
});
