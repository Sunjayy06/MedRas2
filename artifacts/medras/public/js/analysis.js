/* MedRAS — Statistical Analysis Engine (Pass 1)
 *
 * 12-screen wizard. Pass 1 ships screens 1, 2A, 2C, file-preview, 3, 4.
 * Screens 5-12 land in subsequent passes.
 */
"use strict";

document.documentElement.dataset.jsLoaded = "yes";
window.__medras_loaded = Date.now();

const API_BASE = "/api/stats";

/* ------------------------------------------------------------------ */
/*  State                                                              */
/* ------------------------------------------------------------------ */

const state = {
  jobId: null,
  summary: null,
  columns: [],
  classifications: [],
  preview: [],
  repeated: { any_repeats: false, columns: [] },
  quality: null,
  qualityActions: [],   // {row, variable, action, bound_low, bound_high}
  currentScreen: 1,
  followUp: null,
  practiceTemplate: "anaemia",
  entryChoice: null,   // "upload" | "practice"
  intake: null,        // {what_you_have, outcomes, independents, instructions}
};

/* ------------------------------------------------------------------ */
/*  Generic helpers                                                    */
/* ------------------------------------------------------------------ */

function $(sel, root = document) { return root.querySelector(sel); }
function $$(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }

function setStatus(el, message, level = "loading") {
  if (!el) return;
  el.textContent = message || "";
  if (message) {
    el.dataset.state = level;
  } else {
    delete el.dataset.state;
  }
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function fmtNum(v) {
  if (v == null) return "—";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "—";
    if (Number.isInteger(v)) return v.toString();
    return v.toFixed(2);
  }
  return String(v);
}

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body && body.detail) detail = body.detail;
    } catch (_e) { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

/* ------------------------------------------------------------------ */
/*  Screen routing                                                     */
/* ------------------------------------------------------------------ */

const SCREENS = ["1", "intake", "2a", "2c", "preview", "3", "4", "soon"];
// Map a logical screen id to which step number is "active" in the tracker.
const SCREEN_TO_STEP = {
  "1": 1, "intake": 1, "2a": 2, "2c": 2, "preview": 2, "3": 3, "4": 4, "soon": 5,
};

function showScreen(id) {
  state.currentScreen = id;
  SCREENS.forEach((s) => {
    const el = document.getElementById(`screen-${s}`);
    if (el) el.classList.toggle("is-hidden", s !== id);
  });
  const activeStep = SCREEN_TO_STEP[id] || 1;
  $$(".se-step").forEach((node) => {
    const n = Number(node.dataset.step);
    node.classList.toggle("is-active", n === activeStep);
    if (n < activeStep && !node.classList.contains("is-todo")) {
      node.classList.add("is-done");
    }
    if (n >= activeStep) {
      node.classList.remove("is-done");
    }
  });
  const target = document.getElementById(`screen-${id}`);
  if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ------------------------------------------------------------------ */
/*  Screen 1 — entry chooser                                           */
/* ------------------------------------------------------------------ */

function bindScreen1() {
  $$(".se-entry-card.is-clickable").forEach((card) => {
    card.addEventListener("click", () => {
      const entry = card.dataset.entry;
      if (entry !== "upload" && entry !== "practice") return;
      state.entryChoice = entry;
      // Pre-fill intake fields from any prior session in this tab.
      if (state.intake) {
        $("#intake-have").value = state.intake.what_you_have || "proposal";
        $("#intake-outcomes").value = state.intake.outcomes || "";
        $("#intake-independents").value = state.intake.independents || "";
        $("#intake-instructions").value = state.intake.instructions || "";
      }
      showScreen("intake");
    });
  });
}

/* ------------------------------------------------------------------ */
/*  Screen INTAKE — quick questions                                    */
/* ------------------------------------------------------------------ */

function bindIntake() {
  $('[data-action="continue-intake"]').addEventListener("click", () => {
    state.intake = {
      what_you_have: $("#intake-have").value,
      outcomes: $("#intake-outcomes").value.trim(),
      independents: $("#intake-independents").value.trim(),
      instructions: $("#intake-instructions").value.trim(),
    };
    setStatus($("#intake-status"), "");
    if (state.entryChoice === "upload") {
      showScreen("2a");
    } else {
      showScreen("2c");
      renderPracticeTemplates();
    }
  });
}

/* ------------------------------------------------------------------ */
/*  Screen 2A — upload                                                  */
/* ------------------------------------------------------------------ */

function bindScreen2A() {
  const drop = $("#drop-zone");
  const input = $("#file-input");

  drop.addEventListener("click", (ev) => {
    if (ev.target.closest("button") || ev.target.closest("a")) return;
    input.click();
  });
  $('[data-action="open-file"]').addEventListener("click", (ev) => {
    ev.stopPropagation();
    input.click();
  });

  ["dragover", "dragenter"].forEach((evt) =>
    drop.addEventListener(evt, (e) => {
      e.preventDefault();
      drop.classList.add("is-dragover");
    })
  );
  ["dragleave", "drop"].forEach((evt) =>
    drop.addEventListener(evt, (e) => {
      e.preventDefault();
      drop.classList.remove("is-dragover");
    })
  );
  drop.addEventListener("drop", (e) => {
    const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) handleUpload(file);
  });
  input.addEventListener("change", (ev) => {
    const file = ev.target.files && ev.target.files[0];
    if (file) handleUpload(file);
  });
}

async function handleUpload(file) {
  const status = $("#upload-status");
  setStatus(status, `Uploading ${file.name}…`, "loading");
  const form = new FormData();
  form.append("file", file);
  try {
    const data = await api("/upload", { method: "POST", body: form });
    ingestDataset(data);
    setStatus(status, `Loaded ${data.summary.rows} rows × ${data.summary.cols} columns.`, "success");
    showScreen("preview");
    renderPreview();
  } catch (err) {
    setStatus(status, `Upload failed: ${err.message}`, "error");
  }
}

/* ------------------------------------------------------------------ */
/*  Screen 2C — practice dataset                                        */
/* ------------------------------------------------------------------ */

let _templatesCache = null;

async function loadTemplates() {
  if (_templatesCache) return _templatesCache;
  const data = await api("/templates");
  _templatesCache = data.templates || [];
  return _templatesCache;
}

async function renderPracticeTemplates() {
  const wrap = $("#practice-templates");
  const templates = await loadTemplates();
  wrap.innerHTML = templates.map((t, i) => `
    <label class="se-radio-card${i === 0 ? " is-selected" : ""}" data-tpl="${escapeHtml(t.id)}">
      <input type="radio" name="practice-template" value="${escapeHtml(t.id)}"${i === 0 ? " checked" : ""} data-testid="radio-template-${escapeHtml(t.id)}" />
      <div>
        <strong>${escapeHtml(t.label)}</strong>
        <small>${escapeHtml(t.description)}</small>
      </div>
    </label>
  `).join("");
  state.practiceTemplate = templates[0]?.id || "anaemia";
  $$(".se-radio-card", wrap).forEach((card) => {
    card.addEventListener("click", () => {
      $$(".se-radio-card", wrap).forEach((c) => c.classList.remove("is-selected"));
      card.classList.add("is-selected");
      const radio = card.querySelector("input[type=radio]");
      if (radio) radio.checked = true;
      state.practiceTemplate = card.dataset.tpl;
    });
  });
}

function bindScreen2C() {
  const slider = $("#practice-n");
  slider.addEventListener("input", () => {
    $('[data-testid="text-n-value"]').textContent = slider.value;
  });
  $('[data-action="generate"]').addEventListener("click", handleGenerate);
}

async function handleGenerate() {
  const status = $("#practice-status");
  const n = Number($("#practice-n").value);
  const groups = Number($("#practice-groups").value);
  const missing = Number($("#practice-missing").value);
  setStatus(status, "Generating dataset…", "loading");
  try {
    const data = await api("/generate-dummy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        template: state.practiceTemplate,
        n_patients: n,
        n_groups: groups,
        missing_pct: missing,
        intake: state.intake || null,
      }),
    });
    ingestDataset(data);
    setStatus(status, `Generated ${data.summary.rows} patients × ${data.summary.cols} variables.`, "success");
    showScreen("preview");
    renderPreview();
  } catch (err) {
    setStatus(status, `Could not generate: ${err.message}`, "error");
  }
}

/* ------------------------------------------------------------------ */
/*  Common ingest                                                       */
/* ------------------------------------------------------------------ */

function ingestDataset(data) {
  state.jobId = data.job_id;
  state.summary = data.summary;
  state.columns = data.columns;
  state.classifications = data.classifications || [];
  state.preview = data.preview || [];
  state.repeated = data.repeated_ids || { any_repeats: false, columns: [] };
  state.quality = null;
  state.qualityActions = [];
  state.followUp = null;
  // Sync canonical intake from server, so any later round-trip (e.g. /dataset/{id})
  // hydrates the form with what the backend actually stored.
  if (data.intake) state.intake = data.intake;
}

/* ------------------------------------------------------------------ */
/*  File-preview screen                                                 */
/* ------------------------------------------------------------------ */

function renderPreview() {
  const meta = $("#preview-meta");
  const s = state.summary || {};
  meta.innerHTML = `
    <div><dt>File</dt><dd data-testid="meta-file">${escapeHtml(s.filename || "—")}</dd></div>
    <div><dt>Rows (patients)</dt><dd data-testid="meta-rows">${s.rows ?? "—"}</dd></div>
    <div><dt>Columns (variables)</dt><dd data-testid="meta-cols">${s.cols ?? "—"}</dd></div>
    ${s.selected_sheet ? `<div><dt>Sheet</dt><dd data-testid="meta-sheet">${escapeHtml(s.selected_sheet)}</dd></div>` : ""}
  `;

  // Sheet picker
  const picker = $("#sheet-picker");
  if (s.sheet_names && s.sheet_names.length > 1) {
    picker.classList.remove("is-hidden");
    const sel = $("#sheet-select");
    sel.innerHTML = s.sheet_names.map((n) => `<option value="${escapeHtml(n)}"${n === s.selected_sheet ? " selected" : ""}>${escapeHtml(n)}</option>`).join("");
    sel.onchange = async () => {
      const status = $("#preview-status");
      setStatus(status, "Reading sheet…", "loading");
      try {
        const data = await api("/select-sheet", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_id: state.jobId, sheet_name: sel.value }),
        });
        ingestDataset(data);
        setStatus(status, "");
        renderPreview();
      } catch (err) {
        setStatus(status, `Could not switch sheet: ${err.message}`, "error");
      }
    };
  } else {
    picker.classList.add("is-hidden");
  }

  // Header warning
  $("#header-warning").classList.toggle("is-hidden", !s.header_looks_numeric);

  // Repeat-id banner
  const repBanner = $("#repeat-id-banner");
  if (state.repeated.any_repeats) {
    const sumText = state.repeated.columns
      .filter((c) => c.repeated_ids > 0)
      .map((c) => `${c.repeated_ids} ID${c.repeated_ids === 1 ? "" : "s"} appear more than once in <strong>${escapeHtml(c.column)}</strong>`)
      .join("; ");
    $("#repeat-id-text").innerHTML = `${sumText}. Is this follow-up data?`;
    repBanner.classList.remove("is-hidden");
    $$('#repeat-id-banner [data-action="set-followup"]').forEach((b) => {
      b.onclick = () => {
        state.followUp = b.dataset.yn === "yes";
        b.parentElement.querySelectorAll(".btn").forEach((x) => x.classList.remove("is-selected"));
        b.classList.add("is-selected");
      };
    });
  } else {
    repBanner.classList.add("is-hidden");
  }

  // Preview table
  const table = $("#preview-table");
  const cols = state.columns;
  table.querySelector("thead").innerHTML = `<tr>${cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr>`;
  table.querySelector("tbody").innerHTML = state.preview.map((row) => `
    <tr>${cols.map((c) => `<td>${escapeHtml(row[c] == null ? "" : row[c])}</td>`).join("")}</tr>
  `).join("");
}

function bindPreview() {
  $('[data-action="confirm-preview"]').addEventListener("click", async () => {
    const status = $("#preview-status");
    setStatus(status, "Saving…", "loading");
    try {
      const data = await api("/confirm-preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: state.jobId,
          follow_up_data: state.followUp,
          intake: state.intake || null,
        }),
      });
      ingestDataset(data);
      setStatus(status, "");
      showScreen("3");
      renderClassify();
    } catch (err) {
      setStatus(status, `Could not confirm: ${err.message}`, "error");
    }
  });
  $('[data-action="restart"]', $("#screen-preview")).addEventListener("click", restart);
  $$('[data-action="back-to-1"]').forEach((b) => b.addEventListener("click", () => showScreen("1")));
}

/* ------------------------------------------------------------------ */
/*  Screen 3 — classification                                           */
/* ------------------------------------------------------------------ */

const TYPE_LABELS = {
  scale:    "Scale",
  ordinal:  "Ordinal",
  nominal:  "Nominal",
  discrete: "Discrete",
  date:     "Date",
  id:       "ID",
  exclude:  "Exclude",
};
const TYPE_OPTIONS = ["scale", "ordinal", "nominal", "discrete", "date", "id", "exclude"];

function typeBadge(t) {
  const safe = TYPE_LABELS[t] ? t : "exclude";
  return `<span class="se-type-badge t-${safe}">${TYPE_LABELS[safe]}</span>`;
}

function renderClassify() {
  const tbody = $("#classify-table tbody");
  tbody.innerHTML = state.classifications.map((c, idx) => {
    const samples = (c.sample_values || []).slice(0, 3).map(escapeHtml).join(", ");
    const opts = TYPE_OPTIONS.map((t) => `<option value="${t}"${t === c.detected_type ? " selected" : ""}>${TYPE_LABELS[t]}</option>`).join("");
    const missing = c.missing > 0
      ? `<span title="${c.missing_pct}% missing">${c.missing} (${c.missing_pct}%)</span>`
      : "—";
    return `<tr data-row="${idx}" data-testid="classify-row-${escapeHtml(c.column)}">
      <td><strong>${escapeHtml(c.column)}</strong></td>
      <td>${typeBadge(c.detected_type)}</td>
      <td><small>${samples || "—"}</small></td>
      <td>${c.unique_count}</td>
      <td>${missing}</td>
      <td>
        <select class="se-type-select" data-col="${escapeHtml(c.column)}" data-testid="select-type-${escapeHtml(c.column)}">${opts}</select>
      </td>
    </tr>`;
  }).join("");

  $$("select.se-type-select", tbody).forEach((sel) => {
    sel.addEventListener("change", () => {
      const col = sel.dataset.col;
      const c = state.classifications.find((x) => x.column === col);
      if (c) {
        c.detected_type = sel.value;
        c.reason = `Manually set to ${sel.value}.`;
        const row = sel.closest("tr");
        if (row) row.querySelector(".se-type-badge").outerHTML = typeBadge(sel.value);
      }
    });
  });

  // Auto-coding summary
  renderAutocodeSummary();
}

function renderAutocodeSummary() {
  const out = $("#autocode-summary");
  const messages = [];
  const cols = state.preview;
  const sexCol = state.classifications.find((c) => /^(sex|gender)$/i.test(c.column));
  if (sexCol && cols.length) {
    const sample = (sexCol.sample_values || []).join(", ").toLowerCase();
    if (/male|female/.test(sample)) {
      messages.push("Sex / Gender will be coded <strong>Male = 1</strong>, <strong>Female = 2</strong>.");
    }
  }
  const yesNoCol = state.classifications.find((c) => {
    const sample = (c.sample_values || []).map((v) => String(v).toLowerCase());
    return c.detected_type === "nominal" && sample.some((v) => v === "yes" || v === "no");
  });
  if (yesNoCol) {
    messages.push(`<strong>${escapeHtml(yesNoCol.column)}</strong> will be coded <strong>Yes = 1</strong>, <strong>No = 0</strong>.`);
  }
  const exclude = state.classifications.filter((c) => c.detected_type === "exclude" || c.detected_type === "id");
  if (exclude.length) {
    messages.push(`Excluded from analysis: ${exclude.map((c) => `<em>${escapeHtml(c.column)}</em>`).join(", ")}.`);
  }
  if (!messages.length) {
    out.innerHTML = "";
  } else {
    out.innerHTML = `<strong>Auto-coding plan</strong>${messages.map((m) => `<div>• ${m}</div>`).join("")}`;
  }
}

function bindScreen3() {
  $('[data-action="back-to-preview"]').addEventListener("click", () => showScreen("preview"));
  $('[data-action="confirm-classify"]').addEventListener("click", async () => {
    const status = $("#classify-status");
    setStatus(status, "Saving classifications…", "loading");
    const overrides = state.classifications
      .filter((c) => /^Manually set/.test(c.reason || ""))
      .map((c) => ({ column: c.column, detected_type: c.detected_type }));
    try {
      await api("/classify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: state.jobId, overrides }),
      });
      setStatus(status, "");
      showScreen("4");
      await loadQualityReport();
    } catch (err) {
      setStatus(status, `Could not save classifications: ${err.message}`, "error");
    }
  });
}

/* ------------------------------------------------------------------ */
/*  Screen 4 — data quality                                             */
/* ------------------------------------------------------------------ */

async function loadQualityReport() {
  const status = $("#quality-status");
  setStatus(status, "Running quality checks…", "loading");
  try {
    const rep = await api(`/quality-check/${state.jobId}`);
    state.quality = rep;
    state.qualityActions = (rep.impossible_values || []).map((f) => ({
      row: f.row,
      variable: f.variable,
      action: f.recommended_action || "review",
      bound_low: f.bound_low,
      bound_high: f.bound_high,
    }));
    renderQuality();
    setStatus(status, "");
  } catch (err) {
    setStatus(status, `Could not run quality checks: ${err.message}`, "error");
  }
}

function renderQuality() {
  const q = state.quality || {};
  const s = q.summary || {};
  $("#quality-summary").innerHTML = `
    <div class="se-q-card"><div class="se-q-label">Total records</div><div class="se-q-value" data-testid="q-total-records">${s.total_records ?? 0}</div></div>
    <div class="se-q-card"><div class="se-q-label">Variables checked</div><div class="se-q-value" data-testid="q-vars-checked">${s.variables_checked ?? 0}</div></div>
    <div class="se-q-card"><div class="se-q-label">Issues found</div><div class="se-q-value" data-testid="q-issues">${s.issues_found ?? 0}</div></div>
    <div class="se-q-card"><div class="se-q-label">Duplicates</div><div class="se-q-value" data-testid="q-duplicates">${s.exact_duplicate_rows ?? 0}</div></div>
    <div class="se-q-card is-score"><div class="se-q-label">Quality score</div><div class="se-q-value" data-testid="q-score">${s.quality_score ?? 100}/100</div></div>
  `;

  // Section A — impossible values
  const impossible = q.impossible_values || [];
  $('[data-testid="count-impossible"]').textContent = impossible.length;
  const tA = $("#dq-impossible-table tbody");
  tA.innerHTML = impossible.map((f, i) => `
    <tr data-testid="impossible-row-${i}">
      <td>${f.row + 1}</td>
      <td>${escapeHtml(f.variable)}</td>
      <td>${fmtNum(f.value)} ${escapeHtml(f.unit || "")}</td>
      <td>${escapeHtml(f.issue)}</td>
      <td>${actionPicker(i, f.recommended_action || "review")}</td>
    </tr>
  `).join("");
  $$("select.se-impossible-action").forEach((sel) => {
    sel.addEventListener("change", () => {
      const i = Number(sel.dataset.i);
      if (state.qualityActions[i]) state.qualityActions[i].action = sel.value;
    });
  });
  if (!impossible.length) {
    tA.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:18px; color:var(--color-text-muted)">No impossible values found.</td></tr>`;
  }

  // Section B — duplicates
  const dups = q.duplicates || { exact_duplicate_rows: [], duplicate_id_groups: [] };
  const dupCount = (dups.exact_duplicate_rows || []).length + (dups.duplicate_id_groups || []).length;
  $('[data-testid="count-duplicates"]').textContent = dupCount;
  const dupBody = $("#dq-dup-body");
  let dupHtml = "";
  if ((dups.exact_duplicate_rows || []).length) {
    dupHtml += `<p data-testid="dq-exact-summary"><strong>${dups.exact_duplicate_rows.length}</strong> exact duplicate rows. They will be removed automatically when you continue.</p>`;
  }
  if ((dups.duplicate_id_groups || []).length) {
    dupHtml += `<p>Repeated IDs in <strong>${escapeHtml(dups.duplicate_id_groups[0].id_column)}</strong>: ${dups.duplicate_id_groups.length} ID${dups.duplicate_id_groups.length === 1 ? "" : "s"} appear more than once.</p>`;
  }
  if (!dupHtml) dupHtml = `<p class="se-hint">No duplicates detected.</p>`;
  dupBody.innerHTML = dupHtml;

  // Section C — logical errors
  const logical = q.logical_errors || [];
  $('[data-testid="count-logical"]').textContent = logical.length;
  const tC = $("#dq-logical-table tbody");
  tC.innerHTML = logical.length
    ? logical.map((f, i) => `
      <tr data-testid="logical-row-${i}">
        <td>${f.row + 1}</td>
        <td>${escapeHtml(f.variable)}</td>
        <td>${escapeHtml(f.value)}</td>
        <td>${escapeHtml(f.issue)}</td>
        <td><em>Flagged for review</em></td>
      </tr>
    `).join("")
    : `<tr><td colspan="5" style="text-align:center; padding:18px; color:var(--color-text-muted)">No consistency errors found.</td></tr>`;
}

function actionPicker(idx, recommended) {
  const opts = ["keep", "remove", "cap", "review"];
  const labels = { keep: "Keep (default)", remove: "Remove row", cap: "Cap at boundary", review: "Mark for review" };
  return `<select class="se-type-select se-impossible-action" data-i="${idx}" data-testid="action-${idx}">
    ${opts.map((o) => `<option value="${o}"${o === recommended ? " selected" : ""}>${labels[o]}</option>`).join("")}
  </select>`;
}

function bindScreen4() {
  $('[data-action="back-to-classify"]').addEventListener("click", () => showScreen("3"));
  $$('[data-action="bulk-impossible"]').forEach((btn) => {
    btn.addEventListener("click", () => {
      const set = btn.dataset.set;
      state.qualityActions.forEach((a) => { a.action = set; });
      $$("select.se-impossible-action").forEach((sel) => { sel.value = set; });
    });
  });
  $('[data-action="apply-quality"]').addEventListener("click", async () => {
    const status = $("#quality-status");
    setStatus(status, "Applying actions…", "loading");
    try {
      const data = await api("/apply-quality", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: state.jobId,
          actions: state.qualityActions,
          remove_exact_duplicates: true,
        }),
      });
      ingestDataset(data);
      const log = data.log || {};
      setStatus(
        status,
        `Done. Removed ${log.removed_rows || 0} rows, capped ${log.capped_values || 0} values.`,
        "success"
      );
      // Pass 1 ends here — show the "coming soon" screen.
      showScreen("soon");
    } catch (err) {
      setStatus(status, `Could not apply: ${err.message}`, "error");
    }
  });
}

/* ------------------------------------------------------------------ */
/*  Soon screen + restart                                              */
/* ------------------------------------------------------------------ */

function bindSoon() {
  $('[data-action="restart"]', $("#screen-soon")).addEventListener("click", restart);
}

function restart() {
  state.jobId = null;
  state.summary = null;
  state.columns = [];
  state.classifications = [];
  state.preview = [];
  state.repeated = { any_repeats: false, columns: [] };
  state.quality = null;
  state.qualityActions = [];
  state.followUp = null;
  setStatus($("#upload-status"), "");
  setStatus($("#practice-status"), "");
  setStatus($("#quality-status"), "");
  showScreen("1");
}

/* ------------------------------------------------------------------ */
/*  Init                                                                */
/* ------------------------------------------------------------------ */

function initApp() {
  document.documentElement.dataset.medrasInit = "running";
  try {
    bindScreen1();
    bindIntake();
    bindScreen2A();
    bindScreen2C();
    bindPreview();
    bindScreen3();
    bindScreen4();
    bindSoon();
    showScreen("1");
    document.documentElement.dataset.medrasInit = "ok";
  } catch (err) {
    document.documentElement.dataset.medrasInit = "error: " + err.message;
    document.title = "INIT ERROR: " + err.message;
    const banner = document.createElement("div");
    banner.style.cssText = "position:fixed;top:0;left:0;right:0;background:#c43838;color:#fff;padding:14px;font:14px monospace;z-index:9999";
    banner.textContent = "INIT FAILED: " + err.message;
    document.body && document.body.appendChild(banner);
    return;
  }
  if (new URLSearchParams(window.location.search).get("autotest") === "1") {
    runSelfTest().catch((err) => {
      document.title = "SELFTEST FAIL: " + err.message;
      const banner = document.createElement("div");
      banner.id = "selftest-result";
      banner.style.cssText = "position:fixed;top:0;left:0;right:0;background:#c43838;color:#fff;padding:14px;font:14px monospace;z-index:9999";
      banner.textContent = `SELFTEST FAIL: ${err.message}`;
      document.body.appendChild(banner);
    });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initApp);
} else {
  initApp();
}

async function runSelfTest() {
  const events = [];
  const log = (msg) => {
    events.push(msg);
    document.title = "TEST: " + msg.slice(0, 60);
    const node = document.getElementById("selftest-log");
    if (node) node.textContent = events.join("\n");
  };
  const banner = document.createElement("pre");
  banner.id = "selftest-log";
  banner.style.cssText = "position:fixed;top:0;left:0;right:0;background:#103a6e;color:#fff;padding:14px;font:12px monospace;z-index:9999;max-height:240px;overflow:auto;white-space:pre-wrap";
  banner.textContent = "SELFTEST starting…\n";
  document.body.appendChild(banner);

  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const click = (sel) => {
    const el = document.querySelector(sel);
    if (!el) throw new Error(`no element ${sel}`);
    el.click();
    log(`clicked ${sel}`);
  };

  // Screen 1 → intake
  click('[data-testid="card-entry-practice"]');
  await wait(200);
  log("waiting for screen-intake…");
  for (let i = 0; i < 30; i++) {
    if (!document.getElementById("screen-intake").classList.contains("is-hidden")) break;
    await wait(100);
  }
  log(`screen-intake visible: ${!document.getElementById("screen-intake").classList.contains("is-hidden")}`);
  // Fill intake fields and continue
  $("#intake-have").value = "objective";
  $("#intake-outcomes").value = "haemoglobin at 12 weeks";
  $("#intake-independents").value = "treatment arm; sex";
  $("#intake-instructions").value = "use non-parametric tests if skewed";
  click('[data-testid="button-continue-intake"]');
  await wait(300);
  // Screen 2C: pick rct, click generate
  await loadTemplates();
  await wait(200);
  // The radio cards may not be rendered yet — wait for them.
  for (let i = 0; i < 20; i++) {
    if (document.querySelector('[data-testid="radio-template-rct"]')) break;
    await wait(100);
  }
  click('[data-testid="radio-template-rct"]');
  click('[data-testid="button-generate"]');
  log("waiting for screen-preview…");
  for (let i = 0; i < 60; i++) {
    if (!document.getElementById("screen-preview").classList.contains("is-hidden")) break;
    await wait(100);
  }
  log(`screen-preview visible: ${!document.getElementById("screen-preview").classList.contains("is-hidden")}`);

  // Confirm preview
  click('[data-testid="button-confirm-preview"]');
  log("waiting for screen-3…");
  for (let i = 0; i < 60; i++) {
    if (!document.getElementById("screen-3").classList.contains("is-hidden")) break;
    await wait(100);
  }
  log(`screen-3 visible: ${!document.getElementById("screen-3").classList.contains("is-hidden")}`);
  // Check Hospital_visits classification
  const hvBadge = document.querySelector('[data-testid="classify-row-Hospital_visits"] .se-type-badge');
  log(`Hospital_visits badge: ${hvBadge ? hvBadge.textContent : "MISSING"}`);

  // Confirm classify → screen 4
  click('[data-testid="button-confirm-classify"]');
  log("waiting for screen-4…");
  for (let i = 0; i < 80; i++) {
    if (!document.getElementById("screen-4").classList.contains("is-hidden")) break;
    await wait(100);
  }
  const s4Visible = !document.getElementById("screen-4").classList.contains("is-hidden");
  log(`screen-4 visible: ${s4Visible}`);
  if (!s4Visible) throw new Error("screen-4 never became visible after confirm-classify");
  await wait(500);
  const records = document.querySelector('[data-testid="q-total-records"]');
  log(`q-total-records: ${records ? records.textContent : "MISSING"}`);

  // Apply quality → screen soon
  click('[data-testid="button-apply-quality"]');
  log("waiting for screen-soon…");
  for (let i = 0; i < 60; i++) {
    if (!document.getElementById("screen-soon").classList.contains("is-hidden")) break;
    await wait(100);
  }
  const soonVisible = !document.getElementById("screen-soon").classList.contains("is-hidden");
  log(`screen-soon visible: ${soonVisible}`);
  if (!soonVisible) throw new Error("screen-soon never became visible");

  log("\n✅ SELFTEST PASSED");
  banner.style.background = "#1f5d36";
}
