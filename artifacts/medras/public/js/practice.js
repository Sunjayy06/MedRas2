/* MedRAS — Practice Data Wizard
 *
 * 4-step wizard that calls /api/practice to generate a custom dataset,
 * downloads it as Excel, and (optionally) hands the dataset off to the
 * existing analysis pipeline by redirecting to /analysis.html with the
 * generated job_id.
 */

(function () {
  "use strict";

  const $  = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const ORDER = ["step-1", "step-2", "step-3", "step-4", "summary", "loading", "result"];
  const STEP_TO_RAIL = {
    "step-1": "1", "step-2": "2", "step-3": "3", "step-4": "4",
    "summary": "summary", "loading": "summary", "result": "summary",
  };

  const state = {
    objective: "",
    outcome: "",
    variables: [],   // [{name, type, min, max, percent, levels, is_outcome}]
    n: 60,
    expected_effect: "",
    instructions: "",
    job_id: null,
    download_url: null,
  };

  // ---------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------

  function show(screen) {
    $$(".pw-card").forEach((el) => el.classList.add("is-hidden"));
    const target = $(`[data-screen="${screen}"]`);
    if (target) target.classList.remove("is-hidden");
    const railKey = STEP_TO_RAIL[screen];
    $$("#pw-steps li").forEach((li) => {
      li.classList.remove("is-active");
      const ds = li.dataset.step;
      if (ds === railKey) li.classList.add("is-active");
      const idx = ORDER.indexOf(`step-${ds}`);
      const here = ORDER.indexOf(screen);
      if (idx >= 0 && here > idx) li.classList.add("is-done");
      else li.classList.remove("is-done");
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function setStatus(msg, kind) {
    const el = $("#pw-status");
    if (!el) return;
    el.textContent = msg || "";
    el.classList.toggle("is-error", kind === "error");
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  async function api(path, opts = {}) {
    const res = await fetch(`/api${path}`, {
      method: opts.method || "GET",
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      body: opts.body || undefined,
    });
    const text = await res.text();
    let json;
    try { json = text ? JSON.parse(text) : {}; } catch (_) { json = { detail: text }; }
    if (!res.ok) throw new Error(json.detail || `Request failed (${res.status})`);
    return json;
  }

  // ---------------------------------------------------------------------
  // Step 1 — objective + outcome
  // ---------------------------------------------------------------------

  function validateStep1() {
    state.objective = $("#pw-objective").value.trim();
    state.outcome   = $("#pw-outcome").value.trim();
    if (!state.objective) { window.medrasAlert("Please enter the study objective.", 'warn'); return false; }
    if (!state.outcome)   { window.medrasAlert("Please enter the primary outcome variable.", 'warn'); return false; }
    return true;
  }

  // ---------------------------------------------------------------------
  // Step 2 — variable list + auto-detected types
  // ---------------------------------------------------------------------

  async function detectTypes() {
    const text = $("#pw-vars").value || "";
    if (!text.trim()) { window.medrasAlert("Enter at least one variable.", 'warn'); return; }
    let detected;
    try {
      detected = await api("/practice/detect-types", {
        method: "POST",
        body: JSON.stringify({ text }),
      });
    } catch (err) {
      window.medrasAlert(`Could not detect types: ${err.message}`, 'error');
      return;
    }
    state.variables = detected.variables.map((v) => ({
      name: v.name, type: v.type, min: null, max: null,
      percent: null, levels: [], is_outcome: false,
    }));
    // Mark outcome row.
    const outcomeNorm = state.outcome.toLowerCase();
    state.variables.forEach((v) => {
      if (v.name.toLowerCase() === outcomeNorm) v.is_outcome = true;
    });
    renderVarsTable();
  }

  function renderVarsTable() {
    const wrap  = $("#pw-vars-table-wrap");
    const tbody = $("#pw-vars-tbody");
    if (!state.variables.length) { wrap.classList.add("is-hidden"); return; }
    wrap.classList.remove("is-hidden");
    tbody.innerHTML = state.variables.map((v, i) => `
      <tr>
        <td>${escapeHtml(v.name)}</td>
        <td>
          <select data-i="${i}" data-k="type">
            <option value="scale"${v.type === "scale" ? " selected" : ""}>Scale</option>
            <option value="binary"${v.type === "binary" ? " selected" : ""}>Binary</option>
            <option value="nominal"${v.type === "nominal" ? " selected" : ""}>Nominal</option>
          </select>
        </td>
        <td>
          <label><input type="checkbox" data-i="${i}" data-k="is_outcome"${v.is_outcome ? " checked" : ""}/> Outcome</label>
        </td>
      </tr>
    `).join("");
    tbody.addEventListener("change", onVarTableChange, { once: true });
  }

  function onVarTableChange(e) {
    const t = e.target;
    const i = Number(t.dataset.i);
    const k = t.dataset.k;
    if (Number.isNaN(i) || !k || !state.variables[i]) return;
    if (t.type === "checkbox") state.variables[i][k] = t.checked;
    else state.variables[i][k] = t.value;
    renderVarsTable();          // re-bind
  }

  function validateStep2() {
    if (!state.variables.length) {
      window.medrasAlert("Click 'Detect types' to extract variables first.", 'warn');
      return false;
    }
    return true;
  }

  // ---------------------------------------------------------------------
  // Step 3 — sample size + per-variable detail + expected effect
  // ---------------------------------------------------------------------

  function renderDetailTable() {
    const tbody = $("#pw-detail-tbody");
    tbody.innerHTML = state.variables.map((v, i) => {
      let inputs = "";
      if (v.type === "scale") {
        inputs = `
          <label>Min <input type="number" data-i="${i}" data-k="min" value="${v.min ?? ""}" placeholder="auto"></label>
          <label>Max <input type="number" data-i="${i}" data-k="max" value="${v.max ?? ""}" placeholder="auto"></label>
        `;
      } else if (v.type === "binary") {
        inputs = `
          <label>% positive <input type="number" data-i="${i}" data-k="percent" min="5" max="95" value="${v.percent ?? 50}"></label>
        `;
      } else {
        inputs = `
          <label>Levels (comma-sep) <input type="text" data-i="${i}" data-k="levels" value="${escapeHtml((v.levels || []).join(", "))}" placeholder="A, B, C"></label>
        `;
      }
      return `
        <tr class="pw-detail-row">
          <td>${escapeHtml(v.name)}</td>
          <td>${escapeHtml(v.type)}</td>
          <td>${inputs}</td>
        </tr>
      `;
    }).join("");
    tbody.addEventListener("input", onDetailChange);
  }

  function onDetailChange(e) {
    const t = e.target;
    const i = Number(t.dataset.i);
    const k = t.dataset.k;
    if (Number.isNaN(i) || !k || !state.variables[i]) return;
    if (k === "levels") {
      state.variables[i].levels = t.value.split(",").map((s) => s.trim()).filter(Boolean);
    } else if (k === "min" || k === "max" || k === "percent") {
      const v = t.value === "" ? null : Number(t.value);
      state.variables[i][k] = Number.isFinite(v) ? v : null;
    }
  }

  function bindRange() {
    const slider = $("#pw-n");
    const display = $("#pw-n-display");
    slider.addEventListener("input", () => {
      state.n = Number(slider.value);
      display.textContent = String(state.n);
    });
  }

  // ---------------------------------------------------------------------
  // Step 4 — instructions
  // ---------------------------------------------------------------------

  function captureStep4() {
    state.expected_effect = $("#pw-effect").value.trim();
    state.instructions    = $("#pw-instructions").value.trim();
  }

  // ---------------------------------------------------------------------
  // Summary
  // ---------------------------------------------------------------------

  function renderSummary() {
    const dl = $("#pw-summary");
    const varList = state.variables.map((v) => {
      let extra = "";
      if (v.type === "scale" && (v.min != null || v.max != null)) {
        extra = ` (${v.min ?? "auto"}–${v.max ?? "auto"})`;
      } else if (v.type === "binary" && v.percent != null) {
        extra = ` (${v.percent}% positive)`;
      } else if (v.type === "nominal" && (v.levels || []).length) {
        extra = ` [${v.levels.join(", ")}]`;
      }
      return `${escapeHtml(v.name)} — ${escapeHtml(v.type)}${escapeHtml(extra)}${v.is_outcome ? " ⭐" : ""}`;
    }).join("<br>");

    dl.innerHTML = `
      <dt>Study</dt><dd>${escapeHtml(state.objective)}</dd>
      <dt>Primary outcome</dt><dd>${escapeHtml(state.outcome)}</dd>
      <dt>Variables (${state.variables.length})</dt><dd>${varList || "—"}</dd>
      <dt>Sample size</dt><dd>${state.n} patients</dd>
      <dt>Expected effect</dt><dd>${escapeHtml(state.expected_effect) || "<em>(none specified)</em>"}</dd>
      <dt>Special instructions</dt><dd>${escapeHtml(state.instructions) || "<em>(none)</em>"}</dd>
    `;
  }

  // ---------------------------------------------------------------------
  // Generate
  // ---------------------------------------------------------------------

  const LOADING_MSGS = [
    "Creating variables…",
    "Applying medical ranges…",
    "Adding realistic variation…",
    "Adding 5% missing values…",
    "Preparing Excel file…",
  ];

  async function generate() {
    show("loading");
    let i = 0;
    const msg = $("#pw-loading-msg");
    const ticker = setInterval(() => {
      i = (i + 1) % LOADING_MSGS.length;
      msg.textContent = LOADING_MSGS[i];
    }, 600);

    try {
      const data = await api("/practice/generate", {
        method: "POST",
        body: JSON.stringify({
          objective: state.objective,
          outcome: state.outcome,
          variables: state.variables,
          n: state.n,
          expected_effect: state.expected_effect,
          instructions: state.instructions,
          missing_pct: 5.0,
        }),
      });
      state.job_id = data.job_id;
      state.download_url = data.download_url;
      clearInterval(ticker);
      renderResult(data);
      show("result");
    } catch (err) {
      clearInterval(ticker);
      setStatus(`Could not generate: ${err.message}`, "error");
      show("summary");
    }
  }

  function renderResult(data) {
    const list = $("#pw-result-list");
    list.innerHTML = `
      <li><strong>${data.rows}</strong> patients (rows)</li>
      <li><strong>${data.cols}</strong> variables (columns)</li>
      <li>Realistic medical ranges applied</li>
      <li>~${Math.round(data.missing_pct)}% missing values added (so cleaning is meaningful)</li>
    `;
    $("#pw-download").setAttribute("href", data.download_url);
    $("#pw-use").setAttribute(
      "href",
      `/analysis.html?practice=${encodeURIComponent(data.job_id)}`
    );
  }

  // ---------------------------------------------------------------------
  // Wiring
  // ---------------------------------------------------------------------

  function go(direction) {
    const current = $$(".pw-card").find((c) => !c.classList.contains("is-hidden"));
    const screen = current ? current.dataset.screen : "step-1";
    const idx = ORDER.indexOf(screen);

    if (direction === "next") {
      if (screen === "step-1" && !validateStep1()) return;
      if (screen === "step-2" && !validateStep2()) return;
      if (screen === "step-3") {
        // capture slider value (already mirrored to state via input handler)
      }
      if (screen === "step-4") captureStep4();

      const nextIdx = idx + 1;
      const next = ORDER[nextIdx];
      if (next === "summary") renderSummary();
      if (next === "step-3") renderDetailTable();
      show(next);
    } else {
      const prev = ORDER[Math.max(0, idx - 1)];
      show(prev);
    }
  }

  function init() {
    document.addEventListener("click", (e) => {
      const t = e.target;
      if (!(t instanceof HTMLElement)) return;
      if (t.matches("[data-next]")) go("next");
      else if (t.matches("[data-prev]")) go("prev");
      else if (t.matches("[data-edit]")) show("step-1");
    });

    $("#pw-detect").addEventListener("click", detectTypes);
    $("#pw-generate").addEventListener("click", generate);
    $("#pw-restart").addEventListener("click", () => location.reload());

    bindRange();
    show("step-1");
  }

  document.addEventListener("DOMContentLoaded", init);
})();
