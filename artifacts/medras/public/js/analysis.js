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
  intakeStep: 0,       // current question index in intake wizard (0..3)
  sheetMode: null,     // null | "single" | "merge" — set once the user picks a radio
  previewReady: false, // true when Zone 4 should render an actual table (single-sheet
                       // confirmed or merge complete). Stays false on a fresh multi-sheet
                       // upload until the user picks an arrangement.
  blankSheets: new Set(), // sheet names we've discovered are blank, so we can pre-uncheck
                          // and grey them out on the next render of the merge list.

  // --- Step 3 (Variables) additions ---
  issues: [],            // [{column, type, severity, message}]
  autoCoding: [],        // [{column, kind, mapping, note, columns?}]
  assistantThread: [],   // [{role: "system"|"user"|"action"|"clarify", text}]
  recodingChoices: {},   // { age?: {bins:[...]}, bmi?: {...}, hb?: {...} }
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
        const choiceRadio = $(`input[name='intake-have'][value='${state.intake.what_you_have}']`);
        if (choiceRadio) choiceRadio.checked = true;
        if ($("#intake-objective")) $("#intake-objective").value = state.intake.objective || "";
        if ($("#intake-sample-size")) $("#intake-sample-size").value = state.intake.sample_size || "";
        if ($("#intake-outcomes")) $("#intake-outcomes").value = state.intake.outcomes || "";
        if ($("#intake-independents")) $("#intake-independents").value = state.intake.independents || "";
        if ($("#intake-instructions")) $("#intake-instructions").value = state.intake.instructions || "";
      } else {
        // Fresh session: clear any prior selection so Next stays disabled until user picks.
        $$("input[name='intake-have']").forEach((r) => { r.checked = false; });
      }
      // Reset the wizard to question 1 every time we enter the intake screen.
      if (typeof bindIntake._reset === "function") bindIntake._reset();
      showScreen("intake");
    });
  });
}

/* ------------------------------------------------------------------ */
/*  Screen INTAKE — quick questions                                    */
/* ------------------------------------------------------------------ */

function bindIntake() {
  const stage = $("#intake-stage");
  const progress = $("#intake-progress");
  const prevBtn = $('[data-action="intake-prev"]');
  const nextBtn = $('[data-action="intake-next"]');

  // Dynamic step plan. Q1 (have) is always present; Q2 is branched by the
  // user's Q1 choice; Q3 = outcomes; Q4 = independents; Q5 = instructions.
  function planSteps() {
    const choice = state.intake && state.intake.what_you_have;
    const middle = choice === "objective" ? "objective"
                 : choice === "proposal" ? "proposal"
                 : null;
    return middle
      ? ["have", middle, "outcomes", "independents", "instructions"]
      : ["have"];
  }

  function renderProgress(plan, idx) {
    progress.innerHTML = "";
    plan.forEach((_, i) => {
      const dot = document.createElement("span");
      dot.className = "se-intake-dot";
      if (i === idx) dot.classList.add("is-active");
      else if (i < idx) dot.classList.add("is-done");
      progress.appendChild(dot);
    });
  }

  function showStepByName(name) {
    $$(".se-intake-step", stage).forEach((el) => {
      el.classList.toggle("is-active", el.dataset.step === name);
    });
  }

  function refresh() {
    const plan = planSteps();
    const idx = Math.max(0, Math.min(state.intakeStep, plan.length - 1));
    state.intakeStep = idx;
    const stepName = plan[idx];
    showStepByName(stepName);
    renderProgress(plan, idx);
    // Button labels.
    prevBtn.textContent = idx === 0 ? "← Back" : "← Previous";
    nextBtn.textContent = idx === plan.length - 1 ? "Continue →" : "Next →";
    // Q1 requires a choice before Next is enabled. The proposal step needs
    // a successful upload (otherwise we'd advance with no proposal_id and
    // silently submit incomplete intake). Other steps always allow Next.
    if (stepName === "have") {
      const picked = !!$("input[name='intake-have']:checked");
      nextBtn.disabled = !picked;
    } else if (stepName === "proposal") {
      const haveProposal = !!(state.intake && state.intake.proposal_id);
      nextBtn.disabled = !haveProposal;
    } else {
      nextBtn.disabled = false;
    }
  }
  // Expose so the upload handler can re-evaluate Next after upload succeeds.
  bindIntake._refresh = refresh;

  function goNext() {
    const plan = planSteps();
    if (state.intakeStep < plan.length - 1) {
      state.intakeStep += 1;
      refresh();
      return;
    }
    // Final step → commit and continue.
    commitIntake();
    setStatus($("#intake-status"), "");
    if (state.entryChoice === "upload") {
      showScreen("2a");
    } else {
      showScreen("2c");
      renderPracticeTemplates();
    }
  }

  function goPrev() {
    if (state.intakeStep > 0) {
      state.intakeStep -= 1;
      refresh();
    } else {
      showScreen("1");
    }
  }

  function commitIntake() {
    const choice = (state.intake && state.intake.what_you_have) || "proposal";
    const out = {
      what_you_have: choice,
      proposal_id: null,
      proposal_filename: null,
      proposal_size_bytes: null,
      objective: "",
      sample_size: null,
      outcomes: ($("#intake-outcomes").value || "").trim(),
      independents: ($("#intake-independents").value || "").trim(),
      instructions: ($("#intake-instructions").value || "").trim(),
    };
    if (choice === "proposal") {
      out.proposal_id = (state.intake && state.intake.proposal_id) || null;
      out.proposal_filename = (state.intake && state.intake.proposal_filename) || null;
      out.proposal_size_bytes = (state.intake && state.intake.proposal_size_bytes) || null;
    } else if (choice === "objective") {
      out.objective = ($("#intake-objective").value || "").trim();
      const n = parseInt($("#intake-sample-size").value, 10);
      out.sample_size = Number.isFinite(n) && n > 0 ? n : null;
    }
    state.intake = out;
  }

  // Q1 — choice radios drive the branching. Update state.intake.what_you_have
  // immediately so planSteps() picks the right middle step on Next.
  $$("input[name='intake-have']", stage).forEach((r) => {
    r.addEventListener("change", () => {
      state.intake = state.intake || {};
      state.intake.what_you_have = r.value;
      refresh();
    });
  });

  // ---- Debounced navigation: prevents accidental double-tap from skipping
  //      multiple questions in one click on small/touch viewports. ----
  let busyUntil = 0;
  function debouncedClick(fn) {
    return () => {
      const now = performance.now();
      if (now < busyUntil) return;
      busyUntil = now + 250;
      fn();
    };
  }
  nextBtn.addEventListener("click", debouncedClick(goNext));
  prevBtn.addEventListener("click", debouncedClick(goPrev));

  // Keyboard: Enter on textareas/inputs would normally insert newline; only
  // Ctrl/Cmd+Enter advances. Plain Enter inside a number input also advances.
  stage.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const tag = (e.target.tagName || "").toLowerCase();
    const type = (e.target.type || "").toLowerCase();
    if (tag === "input" && type === "number") {
      e.preventDefault();
      goNext();
    } else if (tag === "textarea" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      goNext();
    }
  });

  // ---- Proposal file upload wiring ----
  bindProposalUpload();

  // Reset to first question whenever the screen is freshly shown.
  bindIntake._reset = () => {
    state.intakeStep = 0;
    refresh();
  };
  refresh();
}

/* Proposal upload (intake → POST /upload-proposal) */
function bindProposalUpload() {
  const dz = $("#proposal-dropzone");
  const input = $("#proposal-file");
  const status = $("#proposal-status");
  if (!dz || !input || !status) return;

  function setStatusText(text, kind) {
    status.textContent = text;
    dz.classList.remove("is-loaded", "is-error", "is-dragover");
    if (kind === "ok") dz.classList.add("is-loaded");
    else if (kind === "err") dz.classList.add("is-error");
  }

  function fmtBytes(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
    return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  }

  function clearStoredProposal() {
    state.intake = state.intake || {};
    state.intake.proposal_id = null;
    state.intake.proposal_filename = null;
    state.intake.proposal_size_bytes = null;
  }

  async function uploadFile(file) {
    if (!file) return;
    // Always invalidate any prior proposal first — if this new upload fails,
    // we must NOT silently submit the previous file.
    clearStoredProposal();
    if (typeof bindIntake._refresh === "function") bindIntake._refresh();
    setStatusText(`Uploading ${file.name}…`, null);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch(`${API_BASE}/upload-proposal`, { method: "POST", body: fd });
      if (!res.ok) {
        const text = await res.text();
        let msg = text;
        try { msg = JSON.parse(text).detail || text; } catch (_) { /* keep raw */ }
        throw new Error(msg);
      }
      const data = await res.json();
      state.intake = state.intake || {};
      state.intake.what_you_have = "proposal";
      state.intake.proposal_id = data.proposal_id;
      state.intake.proposal_filename = data.filename;
      state.intake.proposal_size_bytes = data.size_bytes;
      setStatusText(`✔ ${data.filename} — ${fmtBytes(data.size_bytes)} received`, "ok");
    } catch (err) {
      // Make sure we leave state cleared so Next stays disabled.
      clearStoredProposal();
      setStatusText(`Upload failed: ${err.message}`, "err");
    } finally {
      if (typeof bindIntake._refresh === "function") bindIntake._refresh();
    }
  }

  // Click anywhere in the dropzone opens the file picker (label wraps the
  // hidden input, so the browser already does this — we just guard against
  // duplicate dialogs).
  input.addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    if (file) uploadFile(file);
  });

  // Drag & drop.
  ["dragenter", "dragover"].forEach((ev) => {
    dz.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dz.classList.add("is-dragover");
    });
  });
  ["dragleave", "drop"].forEach((ev) => {
    dz.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dz.classList.remove("is-dragover");
    });
  });
  dz.addEventListener("drop", (e) => {
    const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) uploadFile(file);
  });
}

/* ------------------------------------------------------------------ */
/*  Screen 2A — upload                                                  */
/* ------------------------------------------------------------------ */

function bindScreen2A() {
  const drop = $("#drop-zone");
  const input = $("#file-input");

  // The drop-zone is a <label> wrapping the hidden input, so a plain click
  // already opens the OS file picker — no JS click handler needed (and adding
  // one would double-fire). We only handle drag-and-drop visuals + drop here.
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
  // A brand-new dataset (different job_id) means the user uploaded again or
  // generated fresh practice data — wipe the explicit sheet-mode choice so the
  // intake hint can pre-select the merge radio on the next render. Also reset
  // the previewReady flag and forget any blank-sheet discoveries.
  if (data.job_id !== state.jobId) {
    state.sheetMode = null;
    state.previewReady = false;
    state.blankSheets = new Set();
    // New dataset → clear any Step 3 work from a previous run.
    state.issues = [];
    state.autoCoding = [];
    state.assistantThread = [];
    state.recodingChoices = {};
  }
  state.jobId = data.job_id;
  state.summary = data.summary;
  state.columns = data.columns;
  state.classifications = data.classifications || [];
  state.preview = data.preview || [];
  state.repeated = data.repeated_ids || { any_repeats: false, columns: [] };
  state.quality = null;
  state.qualityActions = [];
  state.followUp = null;
  // Any sheets the backend told us were blank during the latest /combine-sheets
  // get folded into our local set so we keep them unchecked next render.
  const skipped = (data.summary && data.summary.skipped_blank_sheets) || [];
  skipped.forEach((s) => state.blankSheets.add(s));
  // Sync canonical intake from server, so any later round-trip (e.g. /dataset/{id})
  // hydrates the form with what the backend actually stored.
  if (data.intake) state.intake = data.intake;
}

/* ------------------------------------------------------------------ */
/*  File-preview screen                                                 */
/* ------------------------------------------------------------------ */

// Words in the "anything else" instructions that suggest the researcher
// already wants their sheets stacked together. Picked deliberately broad —
// false-positives just pre-select the merge radio, which the user can flip.
const MERGE_HINT_RE = /\b(merge|merging|combin(e|ing)|stack(ed)?|concatenat(e|ing)|join(ed)?|append|different\s+sheets|two\s+sheets|each\s+sheet)\b/i;

function intakeWantsMerge(intake) {
  if (!intake || typeof intake.instructions !== "string") return false;
  return MERGE_HINT_RE.test(intake.instructions);
}

/* ------------------------------------------------------------------ */
/*  Zone 2 · "How is your data arranged?" choice cards                  */
/* ------------------------------------------------------------------ */

function renderArrangeCards(summary) {
  const card = $("#sheet-picker");
  const sheets = (summary && summary.sheet_names) || [];
  if (sheets.length < 2) {
    // Single-sheet file → Zone 2 is irrelevant; treat as "single chosen".
    card.classList.add("is-hidden");
    state.sheetMode = "single";
    state.previewReady = true;
    return;
  }
  card.classList.remove("is-hidden");

  const isMerged = Array.isArray(summary.merged_sheets) && summary.merged_sheets.length >= 2;
  const hint = intakeWantsMerge(state.intake);

  // First-render default: if we're already on a merged dataset, lock to "merge".
  // Else honour any explicit user click. Else use the intake hint.
  if (state.sheetMode == null) {
    if (isMerged) state.sheetMode = "merge";
    else if (hint) state.sheetMode = "merge";
  }

  // Hint copy under the section label
  const hintEl = $("#sheet-card-hint");
  const skipped = Array.isArray(summary.skipped_blank_sheets) ? summary.skipped_blank_sheets : [];
  const skippedNote = skipped.length
    ? ` We skipped ${skipped.length === 1 ? "blank sheet" : "blank sheets"} <strong>${escapeHtml(skipped.join(", "))}</strong>.`
    : "";
  if (isMerged) {
    hintEl.innerHTML = `Currently merged: <strong>${escapeHtml(summary.merged_sheets.join(" + "))}</strong>${summary.merge_group_column ? ` (with a <strong>${escapeHtml(summary.merge_group_column)}</strong> column added)` : ""}.${skippedNote}`;
  } else if (state.sheetMode === "merge" && hint) {
    hintEl.innerHTML = "Your earlier notes mention combining sheets, so we've pre-selected <strong>Combine sheets</strong>. Switch to <strong>One sheet only</strong> if that's not right.";
  } else {
    hintEl.textContent = "Pick one of the two options below to continue.";
  }

  // Wire the two arrangement cards. Selecting one toggles state.sheetMode and
  // re-renders so Zone 3/4 visibility updates.
  $$('.se-arrange-card').forEach((btn) => {
    const choice = btn.dataset.arrange;
    const isActive = state.sheetMode === choice;
    btn.classList.toggle("is-selected", isActive);
    btn.setAttribute("aria-pressed", isActive ? "true" : "false");
    btn.setAttribute("role", "radio");
    btn.setAttribute("aria-checked", isActive ? "true" : "false");
    // Keep the hidden helper radio in sync so any external test that pokes
    // `radio-sheet-single`/`radio-sheet-merge` still reflects state.
    const helperRadio = btn.querySelector('input[type="radio"]');
    if (helperRadio) helperRadio.checked = isActive;
    btn.onclick = async () => {
      state.sheetMode = choice;
      const status = $("#sheet-merge-status");
      const previewStatus = $("#preview-status");
      setStatus(status, "");
      $("#merge-empty-warning").classList.add("is-hidden");
      if (choice === "single") {
        if (isMerged) {
          // We're currently looking at a merged dataset on the server. Switching
          // to "One sheet only" must revert the server-side dataset, otherwise
          // Confirm would persist the merged view. Round-trip via /select-sheet
          // for the first of the merged sheets — note that summary.selected_sheet
          // after a merge is the joined label ("A + B"), which is NOT a real
          // workbook sheet, so we deliberately ignore it here.
          const merged = Array.isArray(summary.merged_sheets) ? summary.merged_sheets : [];
          const target = merged[0] || sheets[0];
          state.previewReady = false;
          renderPreview();
          setStatus(previewStatus, `Loading sheet "${target}"…`, "loading");
          try {
            const data = await api("/select-sheet", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ job_id: state.jobId, sheet_name: target }),
            });
            ingestDataset(data);
            state.sheetMode = "single";
            state.previewReady = true;
            setStatus(previewStatus, "");
            renderPreview();
          } catch (err) {
            setStatus(previewStatus, `Could not switch back to a single sheet: ${err.message}`, "error");
            // Roll back the visual choice so the UI matches the server state.
            state.sheetMode = "merge";
            state.previewReady = true;
            renderPreview();
          }
          return;
        }
        // Plain single-sheet case: the currently-loaded sheet is what we'll
        // preview. No backend round-trip needed unless the user explicitly
        // switches sheets via the secondary dropdown.
        state.previewReady = true;
      } else {
        // Merge path: hide preview until the user actually clicks Merge.
        // (Unless we're already viewing a successfully-merged dataset.)
        if (!isMerged) state.previewReady = false;
      }
      renderPreview();
    };
  });

  // Secondary "switch which sheet" dropdown — only shown when single is picked
  // AND the file has multiple sheets (so the user has a real choice to make).
  const singlePick = $("#single-pick");
  if (state.sheetMode === "single") {
    singlePick.classList.remove("is-hidden");
    const sel = $("#sheet-select");
    const currentSingle = isMerged ? sheets[0] : (summary.selected_sheet || sheets[0]);
    sel.innerHTML = sheets.map((n) =>
      `<option value="${escapeHtml(n)}"${n === currentSingle ? " selected" : ""}>${escapeHtml(n)}</option>`
    ).join("");
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
        // After a successful single-sheet swap we're definitely "single ready".
        state.sheetMode = "single";
        state.previewReady = true;
        setStatus(status, "");
        renderPreview();
      } catch (err) {
        // The backend may return our friendly per-sheet message
        // ("Sheet 'X' looks blank — pick a different sheet"). Show it inline
        // and revert the dropdown to the previously-loaded sheet.
        setStatus(status, err.message, "error");
        const previous = isMerged ? sheets[0] : (summary.selected_sheet || sheets[0]);
        sel.value = previous;
      }
    };
  } else {
    singlePick.classList.add("is-hidden");
  }
}

/* ------------------------------------------------------------------ */
/*  Zone 3 · Merge configuration                                        */
/* ------------------------------------------------------------------ */

function renderMergeConfig(summary) {
  const zone = $("#merge-config");
  if (state.sheetMode !== "merge") {
    zone.classList.add("is-hidden");
    return;
  }
  zone.classList.remove("is-hidden");

  const sheets = (summary && summary.sheet_names) || [];
  const isMerged = Array.isArray(summary.merged_sheets) && summary.merged_sheets.length >= 2;

  // Pre-tick: previously-merged sheets if we're on a merged dataset, else all
  // non-blank sheets.
  const preTicked = new Set();
  if (isMerged) {
    summary.merged_sheets.forEach((n) => preTicked.add(n));
  } else {
    sheets.forEach((n) => { if (!state.blankSheets.has(n)) preTicked.add(n); });
  }

  const list = $("#sheet-merge-list");
  list.innerHTML = sheets.map((n, i) => {
    const blank = state.blankSheets.has(n);
    const checked = preTicked.has(n) && !blank;
    const meta = blank ? "blank — skipped" : "ready to merge";
    return `
      <label class="${blank ? "is-blank" : ""}">
        <input type="checkbox" value="${escapeHtml(n)}" data-testid="check-merge-sheet-${i}"${checked ? " checked" : ""}${blank ? " disabled" : ""} />
        <span class="se-merge-sheet-name">${escapeHtml(n)}</span>
        <span class="se-merge-sheet-meta">${escapeHtml(meta)}</span>
      </label>
    `;
  }).join("");

  // Render the amber warning if we know about any blank sheets.
  const warn = $("#merge-empty-warning");
  if (state.blankSheets.size > 0) {
    const names = Array.from(state.blankSheets).map((n) => `<strong>${escapeHtml(n)}</strong>`).join(", ");
    warn.innerHTML = `Sheet ${names} appears to be empty or contains only blank rows. ${state.blankSheets.size === 1 ? "It has been" : "They have been"} unchecked automatically. If your data is on ${state.blankSheets.size === 1 ? "this sheet" : "one of these sheets"}, check that row 1 contains column headers and at least one data row exists.`;
    warn.classList.remove("is-hidden");
  } else {
    warn.classList.add("is-hidden");
  }

  const addGroup = $("#sheet-merge-add-group");
  addGroup.checked = isMerged ? Boolean(summary.merge_group_column) : true;

  // Wire the merge button (replace any prior handler).
  const btn = $('[data-action="run-merge"]');
  btn.onclick = async () => {
    const checked = Array.from(list.querySelectorAll('input[type="checkbox"]:checked')).map((cb) => cb.value);
    const status = $("#sheet-merge-status");
    if (checked.length < 2) {
      setStatus(status, "Tick at least two sheets to merge.", "error");
      return;
    }
    setStatus(status, `Merging ${checked.length} sheets…`, "loading");
    try {
      const data = await api("/combine-sheets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: state.jobId,
          sheet_names: checked,
          add_group_column: addGroup.checked,
        }),
      });
      ingestDataset(data);
      state.sheetMode = "merge";
      state.previewReady = true;
      setStatus(status, "");
      renderPreview();
    } catch (err) {
      // Try to extract the offending sheet name(s) from the friendly backend
      // error so we can pre-uncheck them and keep the user moving.
      const msg = err.message || "";
      // Pattern A: "Sheet 'X' looks blank …" or "Sheet 'X' has fewer than 2 columns …"
      const single = msg.match(/Sheet '([^']+)'/);
      // Pattern B: "Only 'X' has data — the other sheet was blank …"
      const onlyOne = msg.match(/Only '([^']+)' has data/);
      // Pattern C: "All of the sheets you picked are blank …" — every checked
      // sheet is blank.
      const allBlank = /All of the sheets you picked are blank/i.test(msg);
      if (allBlank) {
        checked.forEach((n) => state.blankSheets.add(n));
      } else if (onlyOne) {
        // Every other ticked sheet is blank → flag them all.
        checked.filter((n) => n !== onlyOne[1]).forEach((n) => state.blankSheets.add(n));
      } else if (single) {
        state.blankSheets.add(single[1]);
      }
      setStatus(status, err.message, "error");
      // Re-render so the amber warning + auto-uncheck takes effect.
      renderMergeConfig(summary);
    }
  };
}

/* ------------------------------------------------------------------ */
/*  Zone 4 · Preview table                                              */
/* ------------------------------------------------------------------ */

function renderPreviewZone(summary) {
  const placeholder = $("#preview-placeholder");
  const body = $("#preview-body");
  const confirmBtn = $('[data-action="confirm-preview"]');

  // Disable Confirm whenever there's no preview to confirm.
  confirmBtn.disabled = !state.previewReady;

  if (!state.previewReady) {
    body.classList.add("is-hidden");
    placeholder.classList.remove("is-hidden");
    // Helpful per-mode placeholder text.
    if (state.sheetMode === "single") {
      placeholder.innerHTML = `Loading preview…`;
    } else if (state.sheetMode === "merge") {
      placeholder.innerHTML = `Tick the sheets above and click <strong>Merge selected sheets</strong> to see the combined dataset.`;
    } else {
      placeholder.innerHTML = `Pick an option above to see your data.`;
    }
    return;
  }

  placeholder.classList.add("is-hidden");
  body.classList.remove("is-hidden");

  // Header line above the table
  const isMerged = Array.isArray(summary.merged_sheets) && summary.merged_sheets.length >= 2;
  const summaryLine = isMerged
    ? `${escapeHtml(summary.merged_sheets.join(" + "))} combined · ${summary.rows} patients · ${summary.cols} columns`
    : `${escapeHtml(summary.selected_sheet || summary.filename || "Dataset")} · ${summary.rows} patients · ${summary.cols} columns`;
  $("#preview-summary-line").innerHTML = summaryLine;

  // Optional banners (header looks numeric, repeated IDs)
  $("#header-warning").classList.toggle("is-hidden", !summary.header_looks_numeric);
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

  // The actual table. If a Group column was added during merge, render its cell
  // as a coloured chip whose colour is mapped by the source sheet name.
  const groupCol = summary.merge_group_column || null;
  const sourceSheets = isMerged ? summary.merged_sheets : [];
  const chipIndex = (sheetName) => {
    const i = sourceSheets.indexOf(sheetName);
    return i >= 0 ? (i % 6) : 0;
  };
  const renderCell = (col, val) => {
    const text = val == null ? "" : String(val);
    if (col === groupCol && text) {
      return `<td><span class="se-group-chip" data-chip="${chipIndex(text)}">${escapeHtml(text)}</span></td>`;
    }
    return `<td>${escapeHtml(text)}</td>`;
  };
  const cols = state.columns;
  const table = $("#preview-table");
  table.querySelector("thead").innerHTML = `<tr>${cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr>`;
  table.querySelector("tbody").innerHTML = state.preview.map((row) =>
    `<tr>${cols.map((c) => renderCell(c, row[c])).join("")}</tr>`
  ).join("");

  // Green ready banner under the table
  const sub = isMerged
    ? `${summary.rows} patients · ${summary.cols} variables · ${summary.merged_sheets.join(", ")} merged${summary.merge_group_column ? ` · Group column added` : ""}`
    : `${summary.rows} patients · ${summary.cols} variables · sheet "${summary.selected_sheet || ""}"`;
  $("#ready-banner-sub").textContent = sub;
}

/* ------------------------------------------------------------------ */
/*  Top-level renderer for the preview screen (4 zones)                 */
/* ------------------------------------------------------------------ */

function renderPreview() {
  const s = state.summary || {};
  const sheets = s.sheet_names || [];

  // ZONE 1 — file-summary metric cards
  $('[data-testid="meta-rows"]').textContent = s.rows ?? "—";
  $('[data-testid="meta-cols"]').textContent = s.cols ?? "—";
  $('[data-testid="meta-file"]').textContent = s.filename || "—";
  $("#metric-sheet-count").textContent = sheets.length || "—";
  $("#metric-sheet-list").textContent = sheets.length ? sheets.join(", ") : (s.selected_sheet || "—");

  // ZONE 2 — arrangement choice cards (also handles single-sheet auto-confirm)
  renderArrangeCards(s);

  // ZONE 3 — merge config (only when "Combine sheets" picked)
  renderMergeConfig(s);

  // ZONE 4 — preview table (only when previewReady)
  renderPreviewZone(s);
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
      await loadVariablesData();
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

/* ------------------------------------------------------------------ */
/*  Step 3 · 5-zone layout (A summary / B table / C recoding /         */
/*  D auto-coding plan / E variable assistant)                         */
/* ------------------------------------------------------------------ */

// A preset is described by its "interior" cutoffs (the boundaries between
// adjacent groups), an optional `floor` (the lower bound of the first
// group — null = open / "≤cut"), `isInteger` (controls whether bin labels
// look like "31–45" vs "18.5–25"), and an optional `defaultNames` array
// used when the cutoffs are unchanged from the preset's defaults.
const RECODE_PRESETS = {
  age:  { match: /^age$/i, label: "Age",
          isInteger: true, floor: 18, defaultCutoffs: [30, 45, 60] },
  bmi:  { match: /^bmi$/i, label: "BMI",
          isInteger: false, floor: null, defaultCutoffs: [18.5, 25, 30],
          defaultNames: ["Underweight", "Normal", "Overweight", "Obese"] },
  hb:   { match: /^(haemoglobin|hemoglobin|hb)$/i, label: "Haemoglobin",
          isInteger: false, floor: null, defaultCutoffs: [7, 10, 12],
          defaultNames: ["Severe", "Moderate", "Mild", "Normal"] },
};

// Build the internal bins[] array from a list of comma-separated cutoffs.
// `opts.lower` overrides the first bin's lower bound (defaults to
// `preset.floor`; pass `null` to force open "≤cut1"). `opts.upper`
// overrides the last bin's upper bound (defaults to open ">cutN" /
// "≥cutN"; pass a finite number to cap it).
// Returns null if cutoffs are invalid (non-numeric, empty, unsorted) or
// if lower/upper are inconsistent with the cutoffs.
function cutoffsToBins(cutoffs, preset, opts = {}) {
  const c = (cutoffs || []).filter((x) => Number.isFinite(x));
  if (c.length === 0) return null;
  for (let i = 1; i < c.length; i++) if (c[i] <= c[i - 1]) return null;

  const lower = ("lower" in opts)
    ? (Number.isFinite(opts.lower) ? opts.lower : null)
    : preset.floor;
  const upper = Number.isFinite(opts.upper) ? opts.upper : null;

  // Validate: lower must sit strictly below the first cut; upper must
  // sit at-or-above the last bin's lower edge (after the integer step).
  if (lower != null && lower >= c[0]) return null;
  const step = preset.isInteger ? 1 : 0;
  const lastCut = c[c.length - 1];
  const lastLo = lastCut + step;
  if (upper != null && upper < lastLo) return null;

  // Use preset names ("Underweight" / "Severe" / …) only when cutoffs
  // AND lower/upper are at their preset defaults — once the user moves
  // any boundary, fall back to numeric labels.
  const useNames =
    preset.defaultNames
    && c.length === preset.defaultCutoffs.length
    && preset.defaultCutoffs.every((v, i) => v === c[i])
    && lower === preset.floor
    && upper == null;

  const fmt = (n) => String(n);
  const bins = [];

  // First bin
  const firstHi = c[0];
  bins.push({
    lo: lower,
    hi: firstHi,
    name: useNames ? preset.defaultNames[0]
      : (lower == null ? `≤${fmt(firstHi)}` : `${fmt(lower)}–${fmt(firstHi)}`),
  });
  // Middle bins
  for (let i = 1; i < c.length; i++) {
    const lo = c[i - 1] + step;
    const hi = c[i];
    bins.push({
      lo, hi,
      name: useNames ? preset.defaultNames[i] : `${fmt(lo)}–${fmt(hi)}`,
    });
  }
  // Last bin
  bins.push({
    lo: lastLo,
    hi: upper,
    name: useNames ? preset.defaultNames[c.length]
      : (upper == null
          ? (preset.isInteger ? `>${fmt(lastCut)}` : `≥${fmt(lastCut)}`)
          : `${fmt(lastLo)}–${fmt(upper)}`),
  });
  return bins;
}

// Inverse of cutoffsToBins — derives the "interior" cutoffs from a
// bins[] array (for first-render where the user hasn't typed yet).
function binsToCutoffs(bins) {
  const cuts = [];
  for (let i = 0; i < bins.length - 1; i++) {
    if (bins[i].hi != null) cuts.push(bins[i].hi);
  }
  return cuts;
}

// Read the lower/upper overrides currently encoded in a bins[] array.
function binsLower(bins) { return bins && bins.length ? bins[0].lo : null; }
function binsUpper(bins) {
  return bins && bins.length ? bins[bins.length - 1].hi : null;
}

// Render a bins[] array back into a natural-language groups string the
// user can type directly into the single-input editor.
//   [{lo:18,hi:30}, {lo:31,hi:45}, {lo:46,hi:60}, {lo:61,hi:null}]
//     → "18–30, 31–45, 46–60, >60"
//   [{lo:null,hi:18.5}, {lo:18.5,hi:25}, ..., {lo:30,hi:null}]
//     → "<18.5, 18.5–25, 25–30, >30"
function binsToGroupsString(bins, preset) {
  if (!bins || !bins.length) return "";
  const fmt = (n) => String(n);
  const step = preset.isInteger ? 1 : 0;
  return bins.map((b) => {
    if (b.lo == null && b.hi != null) {
      // Open-low. If the user previously typed an explicit "<N" / "≤N"
      // the bin name preserves it; otherwise default to "<hi+step" for
      // integers ("<18" matches lo=null, hi=17) and "<hi" for floats.
      if (b.name && /^[<≤]/.test(b.name)) return b.name;
      return preset.isInteger ? `<${fmt(b.hi + step)}` : `<${fmt(b.hi)}`;
    }
    if (b.hi == null && b.lo != null) {
      if (b.name && /^[>≥]/.test(b.name)) return b.name;
      return preset.isInteger ? `>${fmt(b.lo - step)}` : `>${fmt(b.lo)}`;
    }
    if (b.lo != null && b.hi != null) {
      return `${fmt(b.lo)}–${fmt(b.hi)}`;
    }
    return b.name || "";
  }).join(", ");
}

// Parse a flexible groups string like "<18, 18–20, 21–30, >30" into a
// bins[] array. Supports `<N`, `≤N`, `>N`, `≥N`, and `N–M` (en-dash,
// em-dash, hyphen, or "N to M") chunks. Returns null on any unparseable
// chunk, on overlapping ranges, or on misplaced open bins.
function parseGroupsString(text, preset) {
  if (!text || !text.trim()) return null;
  const chunks = text.split(",").map((s) => s.trim()).filter(Boolean);
  if (!chunks.length) return null;

  const step = preset.isInteger ? 1 : 0;
  const NUM = "(\\d+(?:\\.\\d+)?)";
  const reLT = new RegExp(`^<${NUM}$`);
  const reLE = new RegExp(`^≤${NUM}$`);
  const reGT = new RegExp(`^>${NUM}$`);
  const reGE = new RegExp(`^≥${NUM}$`);
  const reRange = new RegExp(`^${NUM}-${NUM}$`);

  const bins = [];
  for (const raw of chunks) {
    // Normalise dashes / "to" / whitespace so the regexes only need to
    // care about a canonical form ("18-30").
    const cleaned = raw
      .replace(/[—–]/g, "-")            // em / en dash → hyphen
      .replace(/\s+to\s+/i, "-")        // "18 to 30"
      .replace(/\s+/g, "");
    let m;
    if ((m = reLT.exec(cleaned))) {
      const v = Number(m[1]);
      if (!Number.isFinite(v)) return null;
      // "<N" means strictly less than N. For integer presets this is
      // the closed bin (-∞, N-1]; for floats we keep hi=N.
      bins.push({
        lo: null,
        hi: preset.isInteger ? v - step : v,
        name: `<${m[1]}`,
      });
    } else if ((m = reLE.exec(cleaned))) {
      bins.push({ lo: null, hi: Number(m[1]), name: `≤${m[1]}` });
    } else if ((m = reGT.exec(cleaned))) {
      const v = Number(m[1]);
      if (!Number.isFinite(v)) return null;
      bins.push({
        lo: preset.isInteger ? v + step : v,
        hi: null,
        name: `>${m[1]}`,
      });
    } else if ((m = reGE.exec(cleaned))) {
      bins.push({ lo: Number(m[1]), hi: null, name: `≥${m[1]}` });
    } else if ((m = reRange.exec(cleaned))) {
      const lo = Number(m[1]);
      const hi = Number(m[2]);
      if (!Number.isFinite(lo) || !Number.isFinite(hi) || lo > hi) return null;
      bins.push({ lo, hi, name: `${m[1]}–${m[2]}` });
    } else {
      return null;
    }
  }

  // At most one open-low bin (must be first); at most one open-high bin
  // (must be last); closed bins must not overlap (touching is fine, e.g.
  // "20–30, 30–40" is a common left-closed/right-open style).
  for (let i = 0; i < bins.length; i++) {
    const b = bins[i];
    if (b.lo == null && i !== 0) return null;
    if (b.hi == null && i !== bins.length - 1) return null;
  }
  for (let i = 1; i < bins.length; i++) {
    const prevHi = bins[i - 1].hi;
    const curLo = bins[i].lo;
    if (prevHi == null || curLo == null) continue;
    if (curLo < prevHi) return null;
  }

  return maybeApplyPresetNames(bins, preset);
}

// If the parsed bins exactly match the preset's default cutoff scheme,
// restore the clinical labels (Underweight / Normal / Severe / …) so
// users still benefit from the preset semantics when typing the default
// ranges back in.
function maybeApplyPresetNames(bins, preset) {
  if (!preset.defaultNames) return bins;
  if (bins.length !== preset.defaultNames.length) return bins;
  const cuts = preset.defaultCutoffs;
  if (bins[0].lo !== null) return bins;
  if (bins[0].hi !== (preset.isInteger ? cuts[0] - 1 : cuts[0])) return bins;
  const last = bins[bins.length - 1];
  if (last.hi !== null) return bins;
  if (last.lo !== (preset.isInteger ? cuts[cuts.length - 1] + 1 : cuts[cuts.length - 1])) return bins;
  for (let i = 1; i < bins.length - 1; i++) {
    if (bins[i].lo !== cuts[i - 1]) return bins;
    if (bins[i].hi !== cuts[i]) return bins;
  }
  return bins.map((b, i) => ({ ...b, name: preset.defaultNames[i] }));
}

// Build a placeholder/example string per preset by serializing the
// seeded default bins. Going through cutoffsToBins ensures the example
// honours `preset.floor` (so Age becomes "18–30, 31–45, 46–60, >60",
// not "<30, 30–45, …") and matches the integer-step semantics used
// elsewhere in the editor.
function groupsExample(preset) {
  const seeded = cutoffsToBins(preset.defaultCutoffs, preset);
  return binsToGroupsString(seeded, preset);
}

const CHIP_SUGGESTIONS = [
  { label: "What should I do?", text: "What's your suggestion?",
    isStatic: true },
  { label: "I want both mean and frequency for this column",
    template: "I want both mean and frequency for {col}" },
  { label: "Strip the prefix from this column",
    template: "Strip the prefix from {col}" },
  { label: "Treat this as discrete instead",
    template: "Treat {col} as discrete" },
  { label: "Exclude this column",
    template: "Exclude {col} from analysis" },
];

async function loadVariablesData() {
  // Re-fetch classifications + issues + auto-coding plan from /classify
  // with no overrides. Used on initial entry to Step 3 and after each
  // assistant action.
  const status = $("#classify-status");
  setStatus(status, "Analysing variables…", "loading");
  try {
    const data = await api("/classify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: state.jobId, overrides: [] }),
    });
    state.classifications = data.classifications || [];
    state.issues = data.issues || [];
    state.autoCoding = data.auto_coding_plan || [];
    setStatus(status, "");
    renderClassify();
  } catch (err) {
    setStatus(status, `Could not load variables: ${err.message}`, "error");
  }
}

function renderClassify() {
  renderVariableMetrics();
  renderClassifyTable();
  renderRecodingPanel();
  renderAutocodeSummary();
  renderAssistantPanel();
  validateConfirm();
}

function renderVariableMetrics() {
  const detected = state.classifications.length;
  // Count *distinct columns* with issues, not raw issue rows — a single
  // column can have several issue types (e.g. text_in_numeric + high_missing)
  // and the metric card is meant to show "how many variables need attention".
  const issuesCount = new Set(
    (state.issues || []).map((i) => i.column).filter(Boolean)
  ).size;
  const autoCount = state.autoCoding.filter((a) => a.kind !== "excluded").length;

  const setText = (sel, val) => { const el = $(sel); if (el) el.textContent = val; };
  setText('[data-testid="metric-detected-value"]', detected);
  setText('[data-testid="metric-issues-value"]', issuesCount);
  setText('[data-testid="metric-autocoded-value"]', autoCount);

  const issuesCard = $("#metric-issues-card");
  if (issuesCard) issuesCard.dataset.positive = issuesCount > 0 ? "true" : "false";
}

function issuesForColumn(col) {
  return state.issues.filter((i) => i.column === col);
}

function renderClassifyTable() {
  const tbody = $("#classify-table tbody");
  tbody.innerHTML = state.classifications.map((c, idx) => {
    const samplesArr = (c.sample_values || []).slice(0, 3).map(escapeHtml);
    const samples = samplesArr.length
      ? `<span class="se-vars-sample">${samplesArr.join(", ")}</span>`
      + (((c.sample_values || []).length > 3) ? ' <span class="se-vars-sample-more">…</span>' : "")
      : "—";
    const opts = TYPE_OPTIONS.map(
      (t) => `<option value="${t}"${t === c.detected_type ? " selected" : ""}>${TYPE_LABELS[t]}</option>`,
    ).join("");
    const isAmber = (c.missing_pct || 0) > 30;
    const missing = c.missing > 0
      ? `<span class="se-missing${isAmber ? " is-amber" : ""}" title="${c.missing} of ${c.missing + (c.unique_count || 0)} (${c.missing_pct}%)">
           <span class="se-missing-dot"></span>${c.missing} (${c.missing_pct}%)
         </span>`
      : `<span class="se-missing"><span class="se-missing-dot"></span>0</span>`;

    const colIssues = issuesForColumn(c.column);
    const issueHtml = colIssues.map((i) => {
      const cls = i.severity === "blocking" ? " is-blocking" : "";
      return `<div class="se-issue-sub${cls}" data-testid="issue-${escapeHtml(c.column)}-${i.type}">${escapeHtml(i.message)}</div>`;
    }).join("");

    return `<tr data-row="${idx}" data-testid="classify-row-${escapeHtml(c.column)}">
      <td>
        <div class="se-vars-col-name">${escapeHtml(c.column)}</div>
        ${issueHtml}
      </td>
      <td>${typeBadge(c.detected_type)}</td>
      <td>${samples}</td>
      <td>${missing}</td>
      <td class="se-vars-table-action">
        <select class="se-type-select" data-col="${escapeHtml(c.column)}" data-testid="select-type-${escapeHtml(c.column)}">${opts}</select>
      </td>
    </tr>`;
  }).join("");

  $$("select.se-type-select", tbody).forEach((sel) => {
    sel.addEventListener("change", () => {
      const col = sel.dataset.col;
      const c = state.classifications.find((x) => x.column === col);
      if (!c) return;
      c.detected_type = sel.value;
      c.reason = `Manually set to ${sel.value}.`;
      const row = sel.closest("tr");
      if (row) {
        const badge = row.querySelector(".se-type-badge");
        if (badge) badge.outerHTML = typeBadge(sel.value);
      }
      validateConfirm();
    });
  });
}

function renderRecodingPanel() {
  const zone = $("#recode-zone");
  if (!zone) return;
  // Show only for Scale variables that match a known preset.
  const matches = [];
  state.classifications.forEach((c) => {
    if (c.detected_type !== "scale") return;
    Object.entries(RECODE_PRESETS).forEach(([key, preset]) => {
      if (preset.match.test(c.column)) {
        matches.push({ key, column: c.column, preset });
      }
    });
  });
  if (!matches.length) {
    zone.innerHTML = "";
    return;
  }

  // Per-row state: ensure each match has bins seeded from defaultCutoffs so
  // the cutoff input can render and Step-4 has a usable bins[] array.
  matches.forEach(({ column, preset }) => {
    const choice = state.recodingChoices[column];
    if (!choice || !choice.bins) {
      const bins = cutoffsToBins(preset.defaultCutoffs, preset);
      state.recodingChoices[column] = {
        enabled: choice ? !!choice.enabled : false,
        bins,
      };
    }
  });

  const rowsHtml = matches.map(({ column, preset }) => {
    const choice = state.recodingChoices[column];
    const enabled = !!choice.enabled;
    const bins = choice.bins;
    const groupsStr = binsToGroupsString(bins, preset);
    const example = groupsExample(preset);
    const summary = bins.map((b) => b.name).join(" / ");
    const editorHtml = `
      <div class="se-recode-cutoffs" data-testid="recode-bins-${escapeHtml(column)}" hidden>
        <label class="se-recode-cutoffs-label" for="groups-${escapeHtml(column)}">
          Enter desired groups
        </label>
        <input type="text"
               id="groups-${escapeHtml(column)}"
               class="se-recode-cutoffs-input"
               data-recode-groups="${escapeHtml(column)}"
               data-testid="input-recode-groups-${escapeHtml(column)}"
               value="${escapeHtml(groupsStr)}"
               placeholder="${escapeHtml(example)}"
               autocomplete="off"
               spellcheck="false" />
        <div class="se-recode-cutoffs-helper">
          Define ranges in any format. MedRAS will detect and apply them automatically.
        </div>
        <div class="se-recode-cutoffs-preview"
             data-recode-preview="${escapeHtml(column)}"
             data-testid="preview-recode-${escapeHtml(column)}">
          → Will create groups: <strong>${escapeHtml(summary)}</strong>
        </div>
      </div>`;
    return `<div class="se-recode-row" data-testid="recode-row-${escapeHtml(column)}">
      <label>
        <input type="checkbox" data-recode-toggle="${escapeHtml(column)}"
               data-testid="check-recode-${escapeHtml(column)}" ${enabled ? "checked" : ""}/>
        Group <strong>${escapeHtml(column)}</strong> into
        <span class="se-recode-summary"
              data-recode-summary="${escapeHtml(column)}">${escapeHtml(summary)}</span>
      </label>
      <button type="button" class="se-recode-edit" data-recode-edit="${escapeHtml(column)}"
              data-testid="button-recode-edit-${escapeHtml(column)}">Edit groups</button>
      ${editorHtml}
    </div>`;
  }).join("");
  zone.innerHTML = `
    <div class="se-section-label">OPTIONAL RECODING</div>
    <div class="se-recode-zone">${rowsHtml}
      <p class="se-hint" style="margin:8px 0 0;font-size:12px;color:var(--color-text-muted)">
        Recoding adds a new column alongside the original. Applies in the next pass.
      </p>
    </div>`;

  $$("[data-recode-toggle]", zone).forEach((cb) => {
    cb.addEventListener("change", () => {
      const col = cb.dataset.recodeToggle;
      state.recodingChoices[col] = state.recodingChoices[col] || {};
      state.recodingChoices[col].enabled = cb.checked;
    });
  });
  $$("[data-recode-edit]", zone).forEach((btn) => {
    btn.addEventListener("click", () => {
      const col = btn.dataset.recodeEdit;
      const editor = zone.querySelector(`[data-testid="recode-bins-${CSS.escape(col)}"]`);
      if (editor) editor.hidden = !editor.hidden;
    });
  });
  // Single-input update routine: read the natural-language groups string
  // (e.g. "<18, 18–30, >30"), parse it into bins, and refresh preview +
  // summary or flag an error.
  const updateRow = (col) => {
    const preset = matches.find((m) => m.column === col).preset;
    const inp = zone.querySelector(
      `[data-recode-groups="${CSS.escape(col)}"]`);
    const previewEl = zone.querySelector(
      `[data-recode-preview="${CSS.escape(col)}"]`);
    const summaryEl = zone.querySelector(
      `[data-recode-summary="${CSS.escape(col)}"]`);

    const bins = parseGroupsString(inp ? inp.value : "", preset);
    if (bins) {
      state.recodingChoices[col] = state.recodingChoices[col] || { enabled: false };
      state.recodingChoices[col].bins = bins;
      const summary = bins.map((b) => b.name).join(" / ");
      if (previewEl) {
        previewEl.classList.remove("is-error");
        previewEl.innerHTML =
          `→ Will create groups: <strong>${escapeHtml(summary)}</strong>`;
      }
      if (summaryEl) summaryEl.textContent = summary;
      if (inp) inp.classList.remove("is-error");
    } else {
      if (previewEl) {
        previewEl.classList.add("is-error");
        previewEl.textContent =
          "Couldn't read those ranges. Try comma-separated entries like \"<18, 18–30, 31–45, >45\".";
      }
      if (inp) inp.classList.add("is-error");
    }
  };

  $$("[data-recode-groups]", zone).forEach((inp) => {
    const handler = () => updateRow(inp.dataset.recodeGroups);
    inp.addEventListener("input", handler);
    inp.addEventListener("change", handler);
  });
}

function renderAutocodeSummary() {
  const out = $("#autocode-summary");
  const label = $("#autocode-label");
  if (!out || !label) return;
  if (!state.autoCoding.length) {
    out.hidden = true;
    label.hidden = true;
    out.innerHTML = "";
    return;
  }
  out.hidden = false;
  label.hidden = false;
  out.innerHTML = state.autoCoding.map((entry) => {
    if (entry.kind === "excluded") {
      const list = (entry.columns || []).map((c) => `<em>${escapeHtml(c)}</em>`).join(", ");
      return `<div class="se-autocode-item" data-testid="autocode-excluded">
        <strong>Excluded from analysis:</strong> ${list}
      </div>`;
    }
    const map = (entry.mapping || []).map(
      (m) => `<code>${escapeHtml(m.from)} = ${escapeHtml(String(m.to))}</code>`
    ).join(", ");
    return `<div class="se-autocode-item" data-testid="autocode-${escapeHtml(entry.kind)}">
      <strong>${escapeHtml(entry.column || "")}</strong> — ${map}
      <small style="color:var(--color-text-muted)">· ${escapeHtml(entry.note || "")}</small>
    </div>`;
  }).join("");
}

/* ----- Zone E · Variable Assistant ----- */

function renderAssistantPanel() {
  renderAssistantThread();
  renderAssistantChips();
}

function renderAssistantThread() {
  const out = $("#assistant-thread");
  if (!out) return;
  out.innerHTML = state.assistantThread.map((m, i) => {
    const cls = ({ system: "is-system", user: "is-user", action: "is-action", clarify: "is-clarify" })[m.role] || "is-system";
    return `<div class="se-chat-msg ${cls}" data-testid="chat-msg-${i}-${m.role}">${escapeHtml(m.text)}</div>`;
  }).join("");
  out.scrollTop = out.scrollHeight;
}

function renderAssistantChips() {
  const out = $("#assistant-chips");
  if (!out) return;
  // Pick the first text-in-numeric column as the primary suggestion target,
  // otherwise the first non-id/exclude column.
  const blocking = state.classifications.find((c) =>
    issuesForColumn(c.column).some((i) => i.type === "text_in_numeric"),
  );
  const target = blocking || state.classifications.find(
    (c) => c.detected_type !== "id" && c.detected_type !== "exclude",
  );
  const colName = target ? target.column : null;
  const chips = CHIP_SUGGESTIONS.flatMap((s) => {
    if (s.isStatic) {
      return [{ label: s.label, text: s.text }];
    }
    if (!colName) return [];
    return [{
      label: s.label.replace("this column", `“${colName}”`),
      text: s.template.replace("{col}", colName),
    }];
  });
  out.innerHTML = chips.map(
    (c, i) => `<button type="button" class="se-chip" data-chip="${i}" data-testid="chip-${i}">${escapeHtml(c.label)}</button>`
  ).join("");
  $$(".se-chip", out).forEach((btn, i) => {
    btn.addEventListener("click", () => sendAssistantMessage(chips[i].text));
  });
}

async function sendAssistantMessage(message) {
  const text = (message || "").trim();
  if (!text) return;
  state.assistantThread.push({ role: "user", text });
  renderAssistantThread();
  const input = $("#assistant-input");
  if (input) input.value = "";

  try {
    const res = await api("/variable-assistant", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: state.jobId, message: text }),
    });
    if (res.status === "applied") {
      state.assistantThread.push({ role: "action", text: res.confirmation_message || "Done." });
      state.classifications = res.classifications || [];
      state.issues = res.issues || [];
      state.autoCoding = res.auto_coding_plan || [];
      renderClassify();
    } else {
      state.assistantThread.push({ role: "clarify", text: res.confirmation_message || "Could you rephrase?" });
      renderAssistantThread();
    }
  } catch (err) {
    state.assistantThread.push({ role: "clarify", text: `Could not run: ${err.message}` });
    renderAssistantThread();
  }
}

/* ----- Confirm validation (Step 3 → Step 4) ----- */

function validateConfirm() {
  const btn = $('[data-action="confirm-classify"]');
  const banner = $("#confirm-validation");
  if (!btn || !banner) return;
  // Block on any blocking issue (text_in_numeric) where the column is still
  // typed as a numeric kind. If the user changed the type to nominal /
  // exclude, the issue is effectively resolved.
  const numericKinds = new Set(["scale", "ordinal", "discrete"]);
  const stillBlocking = state.issues.filter((i) => {
    if (i.severity !== "blocking") return false;
    const c = state.classifications.find((x) => x.column === i.column);
    if (!c) return false;
    return numericKinds.has(c.detected_type);
  });
  if (stillBlocking.length) {
    btn.disabled = true;
    banner.hidden = false;
    banner.innerHTML = `Cannot continue yet. Resolve these:
      <ul style="margin:6px 0 0 18px;padding:0;">
        ${stillBlocking.map((i) => `<li><strong>${escapeHtml(i.column)}</strong>: ${escapeHtml(i.message)}</li>`).join("")}
      </ul>
      <div style="margin-top:6px;font-size:12px;">
        Tip: ask the assistant to <em>strip the prefix</em>, or change the type to Nominal.
      </div>`;
  } else {
    btn.disabled = false;
    banner.hidden = true;
    banner.innerHTML = "";
  }
}

function bindScreen3() {
  $('[data-action="back-to-preview"]').addEventListener("click", () => showScreen("preview"));
  $('[data-action="confirm-classify"]').addEventListener("click", async () => {
    const status = $("#classify-status");
    setStatus(status, "Saving classifications…", "loading");
    const overrides = state.classifications
      .filter((c) => /^(Manually set|Set by assistant)/.test(c.reason || ""))
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

  // Variable Assistant form submission
  const form = $("#assistant-form");
  if (form) {
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const input = $("#assistant-input");
      if (input && input.value.trim()) sendAssistantMessage(input.value);
    });
  }
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
  const back = $('[data-action="back-to-quality"]', $("#screen-soon"));
  if (back) back.addEventListener("click", () => showScreen("4"));
}

function restart() {
  // Wipe everything — used only by the explicit "Start over" button. Back
  // navigation deliberately does NOT call this so the user's classification
  // overrides, assistant thread, and recoding choices survive a Back trip.
  state.jobId = null;
  state.summary = null;
  state.columns = [];
  state.classifications = [];
  state.preview = [];
  state.repeated = { any_repeats: false, columns: [] };
  state.quality = null;
  state.qualityActions = [];
  state.followUp = null;
  state.issues = [];
  state.autoCoding = [];
  state.assistantThread = [];
  state.recodingChoices = {};
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
  // Q1 — pick "objective + sample size" choice card.
  const choiceRadio = $('[data-testid="radio-have-objective"]');
  choiceRadio.checked = true;
  choiceRadio.dispatchEvent(new Event("change", { bubbles: true }));
  await wait(50);
  log(`intake step: ${state.intakeStep}, next disabled: ${$('[data-testid="button-intake-next"]').disabled}`);
  // Wait for debounce (250ms) before next click to avoid swallowed clicks.
  await wait(280);
  click('[data-testid="button-intake-next"]');
  await wait(280);
  // Q2 — paste objective + sample size.
  $("#intake-objective").value = "Compare mean haemoglobin at 12 weeks between iron sucrose and oral iron groups in adult women.";
  $("#intake-sample-size").value = "120";
  log(`intake step: ${state.intakeStep}`);
  click('[data-testid="button-intake-next"]');
  await wait(280);
  // Q3 — outcomes.
  $("#intake-outcomes").value = "haemoglobin at 12 weeks";
  log(`intake step: ${state.intakeStep}`);
  click('[data-testid="button-intake-next"]');
  await wait(280);
  // Q4 — independents.
  $("#intake-independents").value = "treatment arm; sex";
  log(`intake step: ${state.intakeStep}`);
  click('[data-testid="button-intake-next"]');
  await wait(280);
  // Q5 — instructions + final Continue.
  $("#intake-instructions").value = "use non-parametric tests if skewed";
  log(`intake step: ${state.intakeStep}, button label: ${$('[data-testid="button-intake-next"]').textContent.trim()}`);
  click('[data-testid="button-intake-next"]');
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
