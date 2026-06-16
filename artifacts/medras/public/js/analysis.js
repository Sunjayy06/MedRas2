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
  domainProfile: "generic",
  jobId: null,
  summary: null,
  columns: [],
  classifications: [],
  preview: [],
  repeated: { any_repeats: false, columns: [] },
  quality: null,
  qualityActions: [],   // {row, variable, action, bound_low, bound_high}
  missingDecisions: {},
  currentScreen: 1,
  followUp: null,
  practiceTemplate: "anaemia",
  entryChoice: null,   // "upload" | "practice"
  intake: null,        // {what_you_have, outcomes, independents, instructions}
  proposalUnderstanding: null,
  intakeStep: 0,       // current question index in intake wizard (0..3)
  sheetMode: null,     // null | "single" | "merge" — set once the user picks a radio
  previewReady: false, // true when Zone 4 should render an actual table (single-sheet
                       // confirmed or merge complete). Stays false on a fresh multi-sheet
                       // upload until the user picks an arrangement.
  blankSheets: new Set(), // sheet names we've discovered are blank, so we can pre-uncheck
                          // and grey them out on the next render of the merge list.

  // --- Category duplicate detection ---
  categoryDupeResults: null,   // {columns: {<col>: {obvious:[], borderline:[], n_dirty}}}
  rejectedMergeSuggestions: new Set(),
  setupGroupCol: "",           // grouping variable selected on setup screen

  // --- Step 3 (Variables) additions ---
  issues: [],            // [{column, type, severity, message}]
  autoCoding: [],        // [{column, kind, mapping, note, columns?}]
  assistantThread: [],   // [{role: "system"|"user"|"action"|"clarify", text}]
  recodingChoices: {},   // { age?: {bins:[...]}, bmi?: {...}, hb?: {...} }

  // --- Steps 4-8 additions ---
  assignment: null,        // {outcome, group, covariates}
  normality: null,         // {columns: [...]}
  plan: null,              // {tests, graphs, outputs, summary}
  confirmedTests: null,    // Set<string>
  confirmedGraphs: null,   // Set<string>
  results: null,           // results-payload from /run-analysis
  resultId: null,
  analysisVersion: null,

  // --- Correlation study (new) ---
  aiStudy: null,           // result from /ai-bridge
  corrResults: null,       // result from /run-correlation

  // --- Task 2: Document correction versions ---
  correctionVersions: [],  // [{version, timestamp, instructions, applied, skipped}]

  // --- Chatboxes 2/3/4 (PART 5) ---
  chatThreads: { normality: [], plan: [], results: [] },
  chatOpened:  { normality: false, plan: false, results: false },

  // --- Inline Custom Practice Wizard (Step 2C → 4-question card) ---
  // Tracks the user's answers across the 4 question panels so "Regenerate
  // with changes" can re-open the wizard pre-filled. `dataSource` lets the
  // preview screen know whether to surface practice-only buttons.
  customWizard: {
    activeQ: 1,
    variables: [],   // [{name, type, min, max, percent, levels[]}]
    n: 60,
    effect: "",
    instructions: "",   // Q5 — free-form notes for the Excel sheet
  },
  dataSource: null,  // "upload" | "template" | "custom"
};

/* ------------------------------------------------------------------ */
/*  Generic helpers                                                    */
/* ------------------------------------------------------------------ */

function $(sel, root = document) { return root.querySelector(sel); }

function confirmAIStateChange(title, change) {
  const lines = [
    title,
    "",
    `Affected: ${change.affected || "analysis state"}`,
    `Before: ${change.before ?? "not set"}`,
    `After: ${change.after ?? "not set"}`,
  ];
  if (change.details) lines.push("", change.details);
  lines.push("", "Apply this AI-suggested change?");
  return window.confirm(lines.join("\n"));
}

function confirmAIStudyReplacement(suggested, title = "AI suggested a study setup change") {
  const current = state.aiStudy || {};
  const before = `${current.study_type || "not set"}; outcome: ${current.outcome_col || "not set"}`;
  const after = `${suggested.study_type || "not set"}; outcome: ${suggested.outcome_col || "not set"}`;
  const predictors = (suggested.predictors || suggested.all_predictors || []).join(", ");
  return confirmAIStateChange(title, {
    affected: "study type, outcome, predictors, and analysis approach",
    before,
    after,
    details: predictors ? `Suggested predictors: ${predictors}` : "No predictor changes listed.",
  });
}

const EXTERNAL_AI_PATHS = [
  "/variable-assistant", "/chat/", "/ai-chat", "/ai-bridge",
  "/adjust-analysis", "/setup-study", "/adjust-setup",
];

const ANALYSIS_INVALIDATING_PATHS = [
  "/classify", "/assign", "/apply-category-merge", "/apply-quality",
  "/cleanup-undo", "/trim-all-whitespace", "/apply-missing-decisions",
  "/standardize-yes-no", "/handle-missing", "/normality/override",
];

function invalidateClientAnalysisState() {
  state.normality = null;
  state.plan = null;
  state.confirmedTests = null;
  state.confirmedGraphs = null;
  state.results = null;
  state.resultId = null;
  state.analysisVersion = null;
  state.corrResults = null;
  updateExportAvailability();
}

function _externalAIConsentKey() {
  return `medras.sigma.external_ai_consent:${state.jobId || "pre-dataset"}`;
}

function ensureExternalAIConsent() {
  const key = _externalAIConsentKey();
  try {
    const saved = sessionStorage.getItem(key);
    if (saved === "granted") return true;
    if (saved === "denied") return false;
  } catch (_) {}
  const granted = window.confirm(
    "External AI disclosure\n\n"
    + "Sigma may send your proposal text, study description, column names, "
    + "statistical summaries, and questions to OpenRouter. "
    + "Do not include identifiable patient data.\n\n"
    + "Allow external AI for this dataset/session?\n"
    + "Choose Cancel to keep using local fallback only."
  );
  try { sessionStorage.setItem(key, granted ? "granted" : "denied"); } catch (_) {}
  return granted;
}

function externalAIHeaders(headers = {}) {
  const out = new Headers(headers);
  out.set("X-External-AI-Consent", ensureExternalAIConsent() ? "true" : "false");
  return out;
}

function showAIProviderStatus(data) {
  if (!data || !data.provider_message) return;
  let el = document.getElementById("sigma-ai-provider-status");
  if (!el) {
    el = document.createElement("div");
    el.id = "sigma-ai-provider-status";
    el.className = "se-ai-provider-status";
    el.setAttribute("role", "status");
    document.body.appendChild(el);
  }
  el.textContent = data.provider_message;
  el.dataset.provider = data.provider_status || "local_fallback";
  el.hidden = false;
}

window.SigmaExternalAI = {
  ensureConsent: ensureExternalAIConsent,
  headers: externalAIHeaders,
  showStatus: showAIProviderStatus,
};

function selectedDomainProfile() {
  const value = document.getElementById("s1-domain-profile")?.value || state.domainProfile;
  state.domainProfile = ["generic", "clinical_general", "breast_pathology"].includes(value)
    ? value
    : "generic";
  return state.domainProfile;
}

function proposalMetadataPayload() {
  return state.proposalUnderstanding || (state.intake && state.intake.proposal_understanding) || null;
}

function _mergeSuggestionKey(proposal) {
  const members = [...(proposal.members || [])].map(String).sort();
  return `${proposal.column || ""}::${proposal.canonical || ""}::${members.join("|")}`;
}

function _isProtectedBreastMerge(proposal) {
  if (selectedDomainProfile() !== "breast_pathology") return false;
  const labels = new Set([proposal.canonical, ...(proposal.members || [])].map((value) =>
    String(value || "").trim().toLowerCase().replace(/[^\w]+/g, " ")
  ));
  return labels.has("luminal a") && labels.has("luminal b");
}
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

const _API_JOB_LABELS = {
  '/upload':          'Processing dataset…',
  '/quality-check':   'Quality check…',
  '/apply-quality':   'Applying quality fixes…',
  '/generate-plan':   'Generating analysis plan…',
  '/run-analysis':    'Running analysis…',
  '/setup-study':     'AI study setup…',
  '/adjust-setup':    'Updating study setup…',
  '/normality':       'Checking normality…',
  '/run-correlation': 'Running correlation…',
  '/ai-chat':         'AI assistant thinking…',
  '/handle-missing':  'Handling missing data…',
  '/rerun-partial':   'Re-running selected tests…',
};

async function api(path, options = {}) {
  const jobEntry = Object.entries(_API_JOB_LABELS).find(([k]) => path.includes(k));
  const jobId    = jobEntry ? `sigma${path.replace(/[^a-z0-9]/gi, '')}` : null;
  if (jobId) window.MedrasJobs?.start(jobId, jobEntry[1]);
  try {
    if (EXTERNAL_AI_PATHS.some((aiPath) => path.includes(aiPath))) {
      options.headers = externalAIHeaders(options.headers || {});
    }
    const res = await fetch(`${API_BASE}${path}`, options);
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const body = await res.json();
        if (body && body.detail) detail = body.detail;
      } catch (_e) { /* ignore */ }
      throw new Error(detail);
    }
    const data = await res.json();
    if (ANALYSIS_INVALIDATING_PATHS.some((mutatingPath) => path.includes(mutatingPath))) {
      invalidateClientAnalysisState();
    }
    showAIProviderStatus(data);
    return data;
  } finally {
    if (jobId) window.MedrasJobs?.finish(jobId);
  }
}

/* ------------------------------------------------------------------ */
/*  Session persistence (localStorage)                                  */
/*                                                                      */
/*  We persist enough breadcrumbs to drop the user back where they      */
/*  were after a refresh — the dataset itself stays on the server,      */
/*  keyed by job_id, so the localStorage payload is metadata only.      */
/*  TTL: 24 hours, after which the saved session is silently forgotten. */
/* ------------------------------------------------------------------ */

const SESSION_KEY = "medras_analysis_session";
const SESSION_TTL_MS = 24 * 60 * 60 * 1000;
// We only persist sessions for screens past the entry chooser. Saving on
// screen 1 / intake would defeat the resume banner (there's nothing to
// resume to) and would also wipe the saved session every time the page
// reloads cold.
const RESUMABLE_SCREENS = new Set(["preview", "setup", "ai-confirm", "3", "4", "normality", "plan", "results", "export"]);

function saveSession() {
  if (!state.jobId) return;
  if (!RESUMABLE_SCREENS.has(state.currentScreen)) return;
  const payload = {
    screen: state.currentScreen,
    step: SCREEN_TO_STEP[state.currentScreen] || 1,
    dataset_id: state.jobId,
    filename: (state.summary && state.summary.filename) || null,
    n_rows: (state.summary && state.summary.rows) || null,
    n_cols: (state.summary && state.summary.cols) || null,
    variable_types: Object.fromEntries(
      (state.classifications || []).map((c) => [c.column, c.detected_type])
    ),
    quality_actions: state.qualityActions || [],
    // Persist AI study plan + description so screen-setup can rehydrate without
    // a network call on resume (fast path in resumeFromSavedSession).
    aiStudy: state.aiStudy || null,
    studyDescription: (() => {
      const el = document.getElementById("setup-study-description");
      return el ? el.value.trim() : "";
    })(),
    timestamp: new Date().toISOString(),
  };
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify(payload));
  } catch (_e) { /* quota or disabled — fail silently */ }
}

function loadSavedSession() {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const obj = JSON.parse(raw);
    const t = obj && obj.timestamp ? Date.parse(obj.timestamp) : NaN;
    if (!Number.isFinite(t) || Date.now() - t > SESSION_TTL_MS) {
      localStorage.removeItem(SESSION_KEY);
      return null;
    }
    if (!obj.dataset_id || !obj.screen) return null;
    return obj;
  } catch (_e) {
    return null;
  }
}

function clearSavedSession() {
  try { localStorage.removeItem(SESSION_KEY); } catch (_e) { /* ignore */ }
}

function _formatRelativeTime(iso) {
  const d = Date.parse(iso);
  if (!Number.isFinite(d)) return "earlier";
  const diff = Date.now() - d;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} minute${mins === 1 ? "" : "s"} ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} hour${hrs === 1 ? "" : "s"} ago`;
  const days = Math.floor(hrs / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

async function resumeFromSavedSession(saved) {
  // Pull the dataset back from the server and walk the user forward to
  // the screen they were on. /dataset returns the same payload that any
  // upload/generate step would, so ingestDataset rehydrates classifications
  // automatically. If the dataset is gone (server restarted, 24-hour cache
  // expired, etc.) we forget the session and stay on screen 1.
  try {
    const data = await api(`/dataset/${saved.dataset_id}`);
    ingestDataset(data);
    const target = saved.screen;
    // Map legacy screen ids ("soon", "assign") onto the current 8-step
    // model so a saved session from before the refactor still resumes
    // somewhere valid instead of silently hiding every screen.
    const LEGACY_REMAP = { soon: "normality", assign: "3" };
    const resolved = LEGACY_REMAP[target] || target;
    if (resolved === "4") {
      showScreen("4");
      await loadQualityReport();
    } else if (resolved === "3") {
      showScreen("3");
      await loadVariablesData();
    } else if (resolved === "setup") {
      // Restore the setup screen — rehydrate AI study plan from saved state,
      // or re-call /setup-study with the stored description if state is stale.
      const savedStudy = saved.aiStudy || state.aiStudy;
      const savedDesc  = saved.studyDescription || "";
      if (savedStudy && savedStudy.study_type) {
        // Fast path: AI plan survived in localStorage — just render it.
        state.aiStudy = savedStudy;
        renderSetupScreen(savedStudy);
        showScreen("setup");
      } else {
        // Slow path: re-run /setup-study with the previously typed description.
        showScreen("setup");
        const statusEl = document.getElementById("setup-describe-status");
        if (statusEl) setStatus(statusEl, "Restoring study plan…", "info");
        try {
          const plan = await api("/setup-study", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              job_id: state.jobId,
              description: savedDesc,
              outcome_hint: "",
              profile: selectedDomainProfile(),
              proposal_metadata: proposalMetadataPayload(),
            }),
          });
          state.aiStudy = plan;
          renderSetupScreen(plan);
          if (statusEl) setStatus(statusEl, "");
        } catch (_) {
          if (statusEl) setStatus(statusEl, "Could not restore study plan — please re-describe.", "error");
        }
      }
    } else if (resolved === "ai-confirm") {
      // Re-run the AI bridge so the confirmation screen has fresh results,
      // then show it. Falls back gracefully if the bridge is unavailable.
      _showAiBridgeOverlay(true);
      try {
        const description = (state.intake && (state.intake.objectives || "")) || "";
        const outcomeHint  = (state.intake && (state.intake.outcomes || "")) || "";
        const bridgeResult = await api("/ai-bridge", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            job_id: state.jobId,
            description,
            outcome_hint: outcomeHint,
            study_type_hint: (state.intake && state.intake.study_type) || null,
            profile: selectedDomainProfile(),
          }),
        });
        state.aiStudy = bridgeResult;
      } catch (_) {
        // Silent rule-based fallback — never show "AI service unavailable" to users
        const _cols2 = (state.classifications || []);
        const _nom2  = _cols2.filter((c) => c.detected_type === "nominal" || c.detected_type === "ordinal");
        const _sc2   = _cols2.filter((c) => c.detected_type === "scale");
        const _gType = _nom2.length && _sc2.length ? "comparison"
                     : _nom2.length >= 2            ? "association"
                     :                               "descriptive";
        state.aiStudy = {
          study_type:    _gType,
          outcome_col:   _sc2.length ? _sc2[0].column : (_nom2.length ? _nom2[0].column : null),
          confidence:    0,
          reasoning:     "",
          source:        "rule_based",
          all_predictors: state.columns.map((c) => c.column || c),
        };
      }
      _showAiBridgeOverlay(false);
      renderAiConfirmScreen();
      showScreen("ai-confirm");
    } else if (resolved === "preview") {
      showScreen("preview");
      // Without renderPreview() the zone label, conditional buttons, and
      // Step-3 reassurance note never get rebuilt for the resumed dataset.
      renderPreview();
    } else if (resolved === "normality") {
      showScreen("normality");
      loadNormality();
    } else if (resolved === "plan") {
      showScreen("plan");
      loadPlan();
    } else if (resolved === "results" || resolved === "export") {
      // Results/Export require a successful run; safer to drop the user
      // back on the plan screen so they can re-run or jump forward via
      // the (clickable) done step circles.
      showScreen("plan");
      loadPlan();
    } else {
      showScreen("1");
    }
  } catch (_err) {
    clearSavedSession();
    showScreen("1");
  }
}

function renderResumeBanner(saved) {
  const modal = document.getElementById("resume-modal");
  if (!modal) return;

  const when = _formatRelativeTime(saved.timestamp);
  const stepLabel = (() => {
    switch (saved.screen) {
      case "4":          return "Step 4 · Review data";
      case "3":          return "Step 3 · Variables";
      case "preview":    return "Step 2 · Data preview";
      case "setup":      return "Step 2.5 · Study setup";
      case "ai-confirm": return "Step 2.5 · Study setup";
      case "normality":  return "Step 5 · Normality";
      case "plan":       return "Step 6 · Plan and Run";
      case "results":    return "Step 7 · Results";
      case "export":     return "Step 8 · Export";
      case "soon":       return "Step 5 · Normality";
      case "assign":     return "Step 3 · Variables";
      default:           return `Step ${saved.step || 1}`;
    }
  })();

  const fname   = saved.filename ? escapeHtml(saved.filename) : "your dataset";
  const rows    = saved.n_rows   ? `${saved.n_rows} rows` : "";
  const cols    = saved.n_cols   ? `${saved.n_cols} columns` : "";
  const dims    = [rows, cols].filter(Boolean).join(" · ");

  modal.innerHTML = `
    <div class="se-resume-modal" data-testid="resume-modal" role="dialog" aria-modal="true" aria-labelledby="resume-modal-title">
      <div class="se-resume-modal-card">
        <div class="se-resume-modal-icon" aria-hidden="true">📊</div>
        <h2 id="resume-modal-title" class="se-resume-modal-title">Unfinished analysis found</h2>
        <p class="se-resume-modal-file"><strong>${fname}</strong>${dims ? `<br><span style="font-size:0.82rem;color:#6b7280">${dims}</span>` : ""}</p>
        <p class="se-resume-modal-meta">Paused <strong>${escapeHtml(when)}</strong> at <strong>${escapeHtml(stepLabel)}</strong></p>
        <div class="se-resume-modal-actions">
          <button type="button" class="btn btn-primary se-resume-modal-btn-continue" data-action="resume-continue" data-testid="button-resume-continue">
            ▶ Resume analysis
          </button>
          <button type="button" class="btn se-resume-modal-btn-delete" data-action="resume-fresh" data-testid="button-resume-fresh">
            🗑 Delete &amp; start fresh
          </button>
        </div>
      </div>
    </div>
  `;
  modal.style.display = "flex";

  modal.querySelector('[data-action="resume-continue"]').addEventListener("click", async () => {
    modal.style.display = "none";
    modal.innerHTML = "";
    await resumeFromSavedSession(saved);
  });
  modal.querySelector('[data-action="resume-fresh"]').addEventListener("click", () => {
    clearSavedSession();
    modal.style.display = "none";
    modal.innerHTML = "";
  });
}

/* ------------------------------------------------------------------ */
/*  Screen routing                                                     */
/* ------------------------------------------------------------------ */

const SCREENS = [
  "1", "intake", "2a", "2c", "2c-custom", "preview",
  "setup", "ai-confirm", "corr-results",
  "3", "4", "missing",
  "normality", "plan", "results", "export",
];
// Map a logical screen id to which step number is "active" in the tracker.
// 7-step model: 1 Setup, 2 Data, 3 Variables+Quality (merged), 4 Normality,
//               5 Plan, 6 Results, 7 Export.
const SCREEN_TO_STEP = {
  "1": 1, "intake": 1,
  "2a": 2, "2c": 2, "2c-custom": 2, "preview": 2, "setup": 2, "ai-confirm": 2,
  "3": 3, "4": 3, "missing": 3,
  "normality": 4, "plan": 5, "results": 6, "corr-results": 6, "export": 7,
};

function showScreen(id) {
  state.currentScreen = id;
  SCREENS.forEach((s) => {
    const el = document.getElementById(`screen-${s}`);
    if (el) el.classList.toggle("is-hidden", s !== id);
  });
  if (id === "export") updateExportAvailability();
  // The step navigator has three explicit states per circle:
  //   is-done    → completed, clickable to go back, green check
  //   is-active  → current, blue with halo
  //   is-future  → not yet reachable, dimmed, NOT clickable
  // We always reset every node before applying the right one so going
  // backwards correctly drops the higher steps back into the future bucket.
  const activeStep = SCREEN_TO_STEP[id] || 1;
  $$(".se-step").forEach((node) => {
    const n = Number(node.dataset.step);
    node.classList.remove("is-active", "is-done", "is-future");
    if (n < activeStep) {
      node.classList.add("is-done");
    } else if (n === activeStep) {
      node.classList.add("is-active");
    } else {
      node.classList.add("is-future");
    }
  });
  // Whenever we leave Step 4, force-hide the sticky controls so they don't
  // bleed into Step 3 or the soon screen. renderQuality() will re-show
  // them with the correct continue-button state when we re-enter Step 4.
  if (id !== "4") {
    const sticky = document.getElementById("dq-sticky-actions");
    if (sticky) sticky.classList.add("is-hidden");
  }
  const target = document.getElementById(`screen-${id}`);
  if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });

  // Update the Pass badge: Steps 1-4 = data preparation; Steps 5-8 = analysis
  const passBadge = document.querySelector('[data-testid="badge-pass"]');
  if (passBadge) {
    const helpBtn = passBadge.querySelector(".se-pass-help");
    const tip     = passBadge.querySelector(".se-pass-tip");
    const step    = SCREEN_TO_STEP[id] || 1;
    const isAnalysis = step >= 4;
    const labelText = isAnalysis
      ? "Pass 2 of 2 — statistical analysis"
      : "Pass 1 of 2 — data preparation";
    // Replace the text node (first child) without touching the button/tip
    const textNode = Array.from(passBadge.childNodes).find((n) => n.nodeType === 3);
    if (textNode) textNode.textContent = labelText;
    else if (helpBtn) passBadge.insertBefore(document.createTextNode(labelText), helpBtn);
    if (tip) tip.textContent = isAnalysis
      ? "You are now in Pass 2. MedRAS is running statistical tests and building your results."
      : "MedRAS runs two passes. Pass 1 prepares and cleans your data. Pass 2 runs the statistical analysis.";
  }

  // Persist the latest step + state to localStorage so a refresh can resume.
  saveSession();
}

// Click-navigation for completed step circles. Done steps are clickable
// (the cursor and colour both signal it) — wire each to its corresponding
// screen so users can jump back without burrowing through the wizard.
function bindStepNavBack() {
  const STEP_TO_SCREEN = {
    1: "1", 2: "preview", 3: "4",
    4: "normality", 5: "plan", 6: "results",
  };
  $$(".se-step").forEach((node) => {
    node.addEventListener("click", () => {
      if (!node.classList.contains("is-done")) return;
      const n = Number(node.dataset.step);
      const target = STEP_TO_SCREEN[n];
      if (target) showScreen(target);
    });
  });
}

/* ------------------------------------------------------------------ */
/*  Screen 1 — entry chooser                                           */
/* ------------------------------------------------------------------ */

function bindScreen1() {
  $$(".se-entry-card.is-clickable").forEach((card) => {
    card.addEventListener("click", () => {
      const entry = card.dataset.entry;
      if (entry === "practice") {
        state.entryChoice = "practice";
        if (state.intake) {
          const choiceRadio = $(`input[name='intake-have'][value='${state.intake.what_you_have}']`);
          if (choiceRadio) choiceRadio.checked = true;
        } else {
          $$("input[name='intake-have']").forEach((r) => { r.checked = false; });
        }
        if (typeof bindIntake._reset === "function") bindIntake._reset();
        showScreen("intake");
        return;
      }
      if (entry === "upload") {
        state.entryChoice = "upload";
        // Show the inline study-description phase instead of the 5-question wizard
        const phase = $("#s1-study-phase");
        const grid = document.querySelector("#screen-1 .se-entry-grid");
        const head  = document.querySelector("#screen-1 > .se-screen-head");
        if (phase) phase.classList.remove("is-hidden");
        if (grid)  grid.classList.add("is-hidden");
        if (head)  head.classList.add("is-hidden");
        // Restore prior session values if any
        if (state.studyDesc && $("#s1-study-desc")) $("#s1-study-desc").value = state.studyDesc;
        if (state.outcomeHint && $("#s1-outcome-hint")) {
          $("#s1-outcome-hint").value = state.outcomeHint;
          const btn = $("#s1-describe-continue-btn");
          if (btn) btn.disabled = false;
        }
      }
    });
  });

  // Back button — restore the entry grid
  document.addEventListener("click", (e) => {
    if (!e.target.closest('[data-action="s1-back"]')) return;
    const phase = $("#s1-study-phase");
    const grid  = document.querySelector("#screen-1 .se-entry-grid");
    const head  = document.querySelector("#screen-1 > .se-screen-head");
    if (phase) phase.classList.add("is-hidden");
    if (grid)  grid.classList.remove("is-hidden");
    if (head)  head.classList.remove("is-hidden");
  });

  // Show a soft hint when the outcome field is blank (no longer blocks the button)
  const outcomeInput = $("#s1-outcome-hint");
  const outcomeHintMsg = $("#s1-outcome-hint-msg");
  if (outcomeInput && outcomeHintMsg) {
    outcomeInput.addEventListener("input", () => {
      outcomeHintMsg.style.display = outcomeInput.value.trim() ? "none" : "block";
    });
  }

  // Describe-path continue — outcome hint is now optional
  document.addEventListener("click", (e) => {
    if (!e.target.closest('[data-action="s1-continue-describe"]')) return;
    const desc = ($("#s1-study-desc")?.value || "").trim();
    const hint = ($("#s1-outcome-hint")?.value || "").trim();
    state.studyDesc   = desc;
    state.outcomeHint = hint;
    // Mirror into state.intake so the AI bridge can consume it downstream
    state.intake = Object.assign({}, state.intake || {}, {
      objectives: desc,
      outcomes:   hint,
    });
    showScreen("2a");
  });

  // Proposal-path continue — outcome hint is now optional
  document.addEventListener("click", (e) => {
    if (!e.target.closest('[data-action="s1-continue-proposal"]')) return;
    const desc       = ($("#s1-prop-desc")?.value || "").trim();
    const hint       = ($("#s1-prop-outcome")?.value || "").trim();
    const studyType  = ($("#s1-prop-study-type")?.value || "").trim();
    const sampleSize = parseInt($("#s1-prop-sample-size")?.value || "", 10) || null;
    state.studyDesc   = desc;
    state.outcomeHint = hint;
    state.intake = Object.assign({}, state.intake || {}, {
      objectives:  desc,
      outcomes:    hint,
      study_type:  studyType  || state.intake?.study_type  || null,
      sample_size: sampleSize || state.intake?.sample_size || null,
      study_title: state.intake?.study_title || null,
      main_marker: state.intake?.main_marker || null,
      main_outcome_concept: state.intake?.main_outcome_concept || hint || null,
      proposal_understanding: proposalMetadataPayload(),
    });
    showScreen("2a");
  });

  _bindS1ProposalUpload();
}

function _bindS1ProposalUpload() {
  const dropzone  = $("#s1-proposal-dropzone");
  const fileInput = $("#s1-proposal-file");
  const status    = $("#s1-proposal-status");
  const fields    = $("#s1-proposal-fields");
  if (!dropzone || !fileInput) return;

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) return;
    if (status) status.textContent = `Parsing ${file.name}…`;
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await fetch(`${API_BASE}/parse-proposal`, {
        method: "POST",
        headers: externalAIHeaders(),
        body: fd,
      });
      if (!r.ok) {
        const errText = await r.text();
        let errMsg = errText;
        try { errMsg = JSON.parse(errText).detail || errText; } catch (_) { /* keep raw */ }
        throw new Error(errMsg);
      }
      const data = await r.json();
      showAIProviderStatus(data);

      const descField       = $("#s1-prop-desc");
      const outcomeField    = $("#s1-prop-outcome");
      const studyTypeField  = $("#s1-prop-study-type");
      const sampleSizeField = $("#s1-prop-sample-size");
      const aiBadge         = $("#s1-prop-ai-badge");

      const primaryObjective = data.objective || (data.objectives && data.objectives.primary) || "";
      if (descField)    descField.value = primaryObjective;
      if (outcomeField) outcomeField.value = data.main_outcome_concept || data.outcomes || "";
      if (studyTypeField && data.study_type) studyTypeField.value = data.study_type;
      if (sampleSizeField && data.sample_size) sampleSizeField.value = data.sample_size;
      if (data.domain_profile) {
        state.domainProfile = data.domain_profile;
        const profileSelect = document.getElementById("s1-domain-profile");
        if (profileSelect) profileSelect.value = data.domain_profile;
      }

      // Show AI badge if extraction was AI-powered.
      if (aiBadge) {
        if (["openrouter", "ai"].includes(data.source)) {
          aiBadge.style.display = "flex";
          aiBadge.classList.remove("is-hidden");
        } else {
          aiBadge.style.display = "none";
        }
      }

      // Cache extracted values in state for downstream use.
      state.intake = Object.assign({}, state.intake || {}, {
        study_type:  data.study_type  || null,
        sample_size: data.sample_size || null,
        study_title: data.study_title || null,
        main_marker: data.main_marker || null,
        main_outcome_concept: data.main_outcome_concept || null,
        proposal_understanding: data,
      });
      state.proposalUnderstanding = data;

      if (fields) fields.classList.remove("is-hidden");
      const sourceLabel = ["openrouter", "ai"].includes(data.source) ? "AI extracted" : "parsed";
      if (status) {
        const outcomeText = data.main_outcome_concept || data.outcomes || "main outcome";
        status.textContent = `✓ ${file.name} — ${sourceLabel}. Suggested outcome: ${outcomeText}. Please confirm or edit.`;
      }
    } catch (e) {
      if (fields) fields.classList.remove("is-hidden");
      if (status) status.textContent = `Could not parse file: ${e.message}. Please fill the fields manually.`;
    }
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
  form.append("profile", selectedDomainProfile());
  try {
    const data = await api("/upload", { method: "POST", body: form });
    state.dataSource = "upload";
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
  // The "Build your own practice dataset" card opens the inline 4-question
  // wizard right here in Step 2 — no page navigation, no separate route.
  const customCard = $('[data-action="open-custom-wizard"]');
  if (customCard) {
    const open = () => openCustomWizard(1);
    customCard.addEventListener("click", open);
    customCard.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
    });
  }
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
    state.dataSource = "template";
    ingestDataset(data);
    setStatus(status, `Generated ${data.summary.rows} patients × ${data.summary.cols} variables.`, "success");
    showScreen("preview");
    renderPreview();
  } catch (err) {
    setStatus(status, `Could not generate: ${err.message}`, "error");
  }
}

/* ------------------------------------------------------------------ */
/*  Screen 2C-CUSTOM — inline 4-question custom wizard                  */
/* ------------------------------------------------------------------ */

// The custom wizard hits a different router (`/api/practice`) than the rest
// of the analysis flow (`/api/stats`), so it goes through fetch() directly
// instead of the api() helper which bakes in API_BASE.
async function practiceApi(path, body) {
  const res = await fetch(`/api/practice${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { const b = await res.json(); if (b.detail) detail = b.detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function showCustomQ(n) {
  state.customWizard.activeQ = n;
  $$("#screen-2c-custom .se-cw-panel").forEach((p) => {
    p.classList.toggle("is-hidden", Number(p.dataset.q) !== n);
  });
  $$("#screen-2c-custom .se-cw-dot").forEach((d) => {
    const dn = Number(d.dataset.q);
    d.classList.toggle("is-active", dn === n);
    d.classList.toggle("is-done", dn < n);
  });
}

function openCustomWizard(q) {
  showScreen("2c-custom");
  showCustomQ(q || 1);
}

function renderCustomQ3Fields() {
  const wrap = $("#cw-q3-fields");
  if (!wrap) return;
  const vars = state.customWizard.variables;
  if (!vars.length) {
    wrap.innerHTML = `<p class="se-hint">No variables yet — go back and add some.</p>`;
    return;
  }
  // Type was auto-detected at Q1 (POST /detect-types) and is intentionally
  // NOT shown here — full variable classification happens later in Step 3,
  // so re-asking for it in the wizard would just repeat that work. We still
  // surface a small per-type hint chip so the user knows what they're
  // configuring (range vs %positive vs levels).
  const TYPE_HINT = {
    scale: "Number",
    binary: "Yes / No",
    nominal: "Category",
  };
  wrap.innerHTML = vars.map((v, i) => {
    let extra = "";
    if (v.type === "scale") {
      extra = `
        <label class="se-cw-mini">Min <input type="number" data-i="${i}" data-k="min" value="${v.min ?? ""}" placeholder="auto"></label>
        <label class="se-cw-mini">Max <input type="number" data-i="${i}" data-k="max" value="${v.max ?? ""}" placeholder="auto"></label>`;
    } else if (v.type === "binary") {
      extra = `<label class="se-cw-mini">% positive <input type="number" data-i="${i}" data-k="percent" min="5" max="95" value="${v.percent ?? 50}"></label>`;
    } else {
      extra = `<label class="se-cw-mini se-cw-mini-wide">Levels (comma-separated) <input type="text" data-i="${i}" data-k="levels" value="${escapeHtml((v.levels || []).join(", "))}" placeholder="e.g. Group A, Group B"></label>`;
    }
    const hint = TYPE_HINT[v.type] || "Number";
    return `
      <div class="se-cw-field-row">
        <div class="se-cw-field-name">
          <span>${escapeHtml(v.name)}</span>
          <span class="se-cw-field-hint" data-testid="hint-cw-type-${i}">${hint}</span>
        </div>
        <div class="se-cw-field-extra">${extra}</div>
      </div>`;
  }).join("");
  wrap.onchange = (e) => {
    const t = e.target;
    const i = Number(t.dataset.i);
    const k = t.dataset.k;
    if (Number.isNaN(i) || !k || !vars[i]) return;
    if (k === "levels") {
      vars[i].levels = String(t.value || "").split(",").map((s) => s.trim()).filter(Boolean);
    } else {
      vars[i][k] = t.value === "" ? null : Number(t.value);
    }
  };
}

async function customWizardNext(from) {
  if (from === 1) {
    const text = ($("#cw-q1-vars").value || "").trim();
    const status = $("#cw-q1-status");
    if (!text) { setStatus(status, "Add at least one variable name.", "error"); return; }
    setStatus(status, "Detecting types…", "loading");
    try {
      const detected = await practiceApi("/detect-types", { text });
      state.customWizard.variables = (detected.variables || []).map((v) => ({
        name: v.name,
        type: v.type || "scale",
        min: null, max: null, percent: null, levels: [],
      }));
      if (!state.customWizard.variables.length) {
        setStatus(status, "Could not extract any variables — please check your list.", "error");
        return;
      }
      setStatus(status, "");
      showCustomQ(2);
    } catch (err) {
      setStatus(status, `Could not detect types: ${err.message}`, "error");
    }
  } else if (from === 2) {
    const n = Number($("#cw-q2-n").value);
    if (!Number.isFinite(n) || n < 20 || n > 500) {
      window.medrasAlert("Pick a number between 20 and 500.", 'warn');
      return;
    }
    state.customWizard.n = n;
    renderCustomQ3Fields();
    showCustomQ(3);
  } else if (from === 3) {
    showCustomQ(4);
  } else if (from === 4) {
    // Stash Q4 before moving on — Q5 → Generate also reads it back, but
    // saving here means a Back-trip preserves what the user typed.
    state.customWizard.effect = ($("#cw-q4-effect").value || "").trim();
    showCustomQ(5);
  }
}

async function customWizardGenerate() {
  const status = $("#cw-status");
  const cw = state.customWizard;
  // Re-read Q4 in case the user edited it without clicking Next, plus Q5.
  cw.effect = ($("#cw-q4-effect").value || "").trim();
  cw.instructions = ($("#cw-q5-instructions").value || "").trim();
  if (!cw.variables.length) {
    setStatus(status, "No variables to generate — go back to question 1.", "error");
    return;
  }
  setStatus(status, "Generating dataset…", "loading");
  try {
    // Mirror practice.html: POST to /api/practice/generate to create the
    // dataset, then re-fetch via /api/stats/dataset/<job_id> to get the
    // full preview/classification payload the analysis flow expects.
    const created = await practiceApi("/generate", {
      objective: "",
      outcome: "",
      variables: cw.variables.map((v) => ({
        name: v.name,
        type: v.type,
        min: v.min,
        max: v.max,
        percent: v.percent,
        levels: v.levels && v.levels.length ? v.levels : null,
        is_outcome: false,
      })),
      n: cw.n,
      expected_effect: cw.effect,
      instructions: cw.instructions,
      missing_pct: 5.0,
    });
    const data = await api(`/dataset/${created.job_id}`);
    state.dataSource = "custom";
    state.entryChoice = "practice";
    ingestDataset(data);
    setStatus(status, "");
    showScreen("preview");
    renderPreview();
  } catch (err) {
    setStatus(status, `Could not generate: ${err.message}`, "error");
  }
}

function bindCustomWizard() {
  const root = $("#screen-2c-custom");
  if (!root) return;
  root.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-cw-action]");
    if (!btn) return;
    const action = btn.dataset.cwAction;
    if (action === "cancel") {
      showScreen("2c");
    } else if (action === "prev") {
      const from = Number(btn.dataset.from);
      showCustomQ(Math.max(1, from - 1));
    } else if (action === "next") {
      const from = Number(btn.dataset.from);
      customWizardNext(from);
    } else if (action === "generate") {
      customWizardGenerate();
    }
  });
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
    state.missingDecisions = {};
    state.categoryDupeResults = null;
    state.rejectedMergeSuggestions = new Set();
    // Also clear all Step 4–7 state so a new dataset starts clean.
    state.assignment = null;
    state.assignmentAutoMatched = false;
    state.assignmentConfirmed = false;
    state.normality = null;
    state.plan = null;
    state.confirmedTests = null;
    state.confirmedGraphs = null;
    state.results = null;
    state.resultId = null;
    state.analysisVersion = null;
    state.chatThreads = { normality: [], plan: [], results: [] };
    state.chatOpened  = { normality: false, plan: false, results: false };
    try { sessionStorage.removeItem('medras.nav.returnHint'); } catch (_) {}
  }
  state.jobId = data.job_id;
  if (data.domain_profile) {
    state.domainProfile = data.domain_profile;
    const profileSelect = document.getElementById("s1-domain-profile");
    if (profileSelect) profileSelect.value = data.domain_profile;
  }
  state.summary = data.summary;
  state.columns = data.columns;
  // Surface the practice banner whenever the backend marks the dataset
  // as dummy/wizard-generated. Toggle (not just show) so a real upload
  // after a prior practice run hides the leftover banner.
  try {
    const s = data.summary || {};
    const isPractice = !!(s.is_dummy || s.is_practice_wizard || data.is_dummy || data.is_practice_wizard);
    const banner = document.getElementById("practice-banner");
    if (banner) banner.classList.toggle("is-hidden", !isPractice);
  } catch (_) { /* banner is purely cosmetic */ }
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
  // Auto-match the wizard's outcome / grouping answers against actual column
  // names. Only run for fresh datasets (a back-trip from Step 3 calls
  // ingestDataset on the same job_id and we want to preserve any manual
  // override the user already confirmed on the assignment card).
  if (!state.assignment || !state.assignment.outcome) {
    autoAssignFromIntake();
  }
}

/* ------------------------------------------------------------------ */
/*  Auto-assignment from wizard answers (Q3 outcome, Q2 / Q4 group)    */
/* ------------------------------------------------------------------ */

function _normaliseToken(s) {
  return String(s || "").toLowerCase().replace(/[_\-/]+/g, " ").trim();
}

function _isUsableAsOutcome(c) {
  return c && !["id", "exclude", "date"].includes(c.detected_type);
}

function _isUsableAsGroup(c) {
  return c && ["nominal", "ordinal"].includes(c.detected_type);
}

function matchColumn(needle, columns) {
  // Returns the best column name match for `needle` against an array of
  // classification rows, or null when nothing scores high enough.
  if (!needle || !columns || !columns.length) return null;
  const n = _normaliseToken(needle);
  if (!n) return null;
  // 1. Exact (case-insensitive, ignoring connectors)
  let m = columns.find((c) => _normaliseToken(c.column) === n);
  if (m) return m.column;
  // 2. Substring either way
  m = columns.find((c) => {
    const col = _normaliseToken(c.column);
    return col.includes(n) || n.includes(col);
  });
  if (m) return m.column;
  // 3. Token-overlap score — pick the column with the most shared meaningful
  //    tokens (length > 2). Ties broken by shortest column name.
  const tokens = n.split(/\s+/).filter((t) => t.length > 2);
  if (!tokens.length) return null;
  let best = null;
  let bestScore = 0;
  columns.forEach((c) => {
    const colTokens = _normaliseToken(c.column).split(/\s+/).filter((t) => t.length > 2);
    const overlap = tokens.filter((t) =>
      colTokens.some((ct) => ct === t || ct.includes(t) || t.includes(ct))
    ).length;
    if (overlap > bestScore || (overlap === bestScore && best && c.column.length < best.length)) {
      best = c.column;
      bestScore = overlap;
    }
  });
  return bestScore >= 1 ? best : null;
}

function extractGroupHint(text) {
  // Scan free-text objective for comparison keywords and return whatever
  // word(s) follow, e.g. "compare HHS between treatment groups" → "treatment".
  if (!text) return null;
  const re = /\b(?:between|compare(?:d)?|across|by|among|in different|vs\.?|versus|grouped\s+by|groups?\s+of|groups?)\s+([a-zA-Z][a-zA-Z0-9 _\-]{1,40})/i;
  const m = String(text).match(re);
  if (!m) return null;
  // Strip trailing filler words like "groups", "patients", "the", etc.
  return m[1].replace(/\b(groups?|patients?|subjects?|the|a|an)\b/gi, "").trim() || null;
}

function autoAssignFromIntake() {
  const intake = state.intake || {};
  const cls = state.classifications || [];
  if (!cls.length) return;
  const outcomeCols = cls.filter(_isUsableAsOutcome);
  const groupCols = cls.filter(_isUsableAsGroup);

  // Outcome — Q3 free text (e.g. "Time to Union")
  let outcome = matchColumn(
    state.outcomeCol || (state.aiStudy && state.aiStudy.outcome_col) || intake.outcomes,
    outcomeCols
  );
  // Defensive: if matchColumn returns an ID-typed column for any reason,
  // discard it — Rule 5 (no ID as outcome).
  if (outcome) {
    const row = cls.find((c) => c.column === outcome);
    if (!row || !_isUsableAsOutcome(row)) outcome = null;
  }

  // Grouping — pull a hint from Q2 (objective) or Q4 (independents)
  const hint =
    extractGroupHint(intake.objective) ||
    extractGroupHint(intake.independents) ||
    (intake.independents || "").split(/[,;]/)[0] || "";
  let group = matchColumn(state.setupGroupCol || hint, groupCols);
  if (group) {
    const row = cls.find((c) => c.column === group);
    if (!row || !_isUsableAsGroup(row)) group = null;
  }

  state.assignment = {
    outcome: outcome || null,
    group: group || null,
    covariates: [],
  };
  state.assignmentAutoMatched = !!outcome;

  // Persist to the server so /generate-plan and /run-analysis pick it up.
  if (outcome && state.jobId) {
    api("/assign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: state.jobId,
        outcome,
        group: group || null,
        covariates: [],
      }),
    }).catch(() => { /* non-fatal — user can re-confirm on the card */ });
  }
}

/* ------------------------------------------------------------------ */
/*  Step 3 — Assignment confirmation card                              */
/* ------------------------------------------------------------------ */

function _typeLabel(c) {
  if (!c) return "—";
  const t = c.detected_type;
  if (t === "scale") {
    return c.scale_subtype ? `Scale (${c.scale_subtype})` : "Scale";
  }
  if (t === "nominal") {
    const n = (c.unique_values && c.unique_values.length) || c.n_levels;
    return n ? `Nominal · ${n} groups` : "Nominal";
  }
  return t ? (t.charAt(0).toUpperCase() + t.slice(1)) : "—";
}

function _sampleSnippet(c) {
  const vals = (c && (c.sample_values || c.unique_values)) || [];
  return vals.slice(0, 3).map((v) => String(v)).join(", ");
}

function renderAssignmentCard(opts) {
  // opts.formOpen forces the change form to be visible (used by the amber
  // warning state and by the "Let me change this" button).
  const host = document.getElementById("assignment-card-host");
  if (!host) return;
  const cls = state.classifications || [];
  if (!cls.length) { host.innerHTML = ""; return; }

  const a = state.assignment || {};
  const outcomeRow = cls.find((c) => c.column === a.outcome);
  const groupRow = cls.find((c) => c.column === a.group);
  const matched = !!outcomeRow && _isUsableAsOutcome(outcomeRow);
  const formOpen = (opts && opts.formOpen) || !matched;

  // Build dropdown options. ID, exclude and date columns are greyed out
  // and disabled — Rule 5 says they can never be selected as outcome/group.
  const outcomeOptions = cls.map((c) => {
    const usable = _isUsableAsOutcome(c);
    const tag = ["id", "exclude"].includes(c.detected_type)
      ? " (ID — excluded)"
      : c.detected_type === "date" ? " (Date — excluded)" : "";
    const sample = _sampleSnippet(c);
    const label = `${c.column}${tag}${sample ? `  ·  ${sample}` : ""}`;
    return `<option value="${escapeHtml(c.column)}"${usable ? "" : " disabled"}${a.outcome === c.column ? " selected" : ""}>${escapeHtml(label)}</option>`;
  }).join("");
  const groupOptions = `<option value=""${!a.group ? " selected" : ""}>— No grouping (descriptive only) —</option>` + cls.map((c) => {
    const usable = _isUsableAsGroup(c);
    const tag = ["id", "exclude"].includes(c.detected_type)
      ? " (ID — excluded)"
      : c.detected_type === "date" ? " (Date — excluded)"
      : c.detected_type === "scale" ? " (Scale — usually not a grouping variable)" : "";
    const sample = _sampleSnippet(c);
    const label = `${c.column}${tag}${sample ? `  ·  ${sample}` : ""}`;
    return `<option value="${escapeHtml(c.column)}"${usable ? "" : " disabled"}${a.group === c.column ? " selected" : ""}>${escapeHtml(label)}</option>`;
  }).join("");

  const warn = !matched ? `
    <div class="se-assign-warn" data-testid="assign-warn">
      We could not confidently identify your outcome variable from what you described.
      Please pick one below — ID and Date columns are greyed out.
    </div>` : "";

  const summaryRows = matched ? `
    <div class="se-assign-row" data-testid="assign-row-outcome">
      <span class="se-assign-row-label">Outcome variable:</span>
      <strong>${escapeHtml(a.outcome)}</strong>
      <span class="se-assign-row-type">— ${escapeHtml(_typeLabel(outcomeRow))}</span>
    </div>
    <div class="se-assign-row" data-testid="assign-row-group">
      <span class="se-assign-row-label">Grouping variable:</span>
      ${a.group
        ? `<strong>${escapeHtml(a.group)}</strong> <span class="se-assign-row-type">— ${escapeHtml(_typeLabel(groupRow))}</span>`
        : `<em>— None (descriptive only) —</em>`}
    </div>
    <p class="se-assign-q">Is this correct?</p>
    <div class="se-assign-buttons">
      <button type="button" class="btn btn-primary" data-action="assign-confirm" data-testid="button-assign-confirm">Yes, looks right →</button>
      <button type="button" class="btn btn-secondary" data-action="assign-change" data-testid="button-assign-change">Let me change this</button>
    </div>` : "";

  const form = formOpen ? `
    <div class="se-assign-form" data-testid="assign-form">
      <label class="se-assign-form-row">
        <span>Outcome variable</span>
        <select class="se-type-select" data-assign-field="outcome" data-testid="select-outcome">${outcomeOptions}</select>
      </label>
      <label class="se-assign-form-row">
        <span>Grouping variable (optional)</span>
        <select class="se-type-select" data-assign-field="group" data-testid="select-group">${groupOptions}</select>
      </label>
      <div class="se-assign-form-actions">
        <button type="button" class="btn btn-primary" data-action="assign-save" data-testid="button-assign-save">Update and confirm</button>
      </div>
      <div id="assign-form-status" class="se-status" role="status" aria-live="polite" data-testid="status-assign"></div>
    </div>` : "";

  host.innerHTML = `
    <section class="se-assign-card${matched ? "" : " is-amber"}${state.assignmentConfirmed ? " is-confirmed" : ""}" data-testid="assignment-card">
      <div class="se-assign-card-eyebrow">BASED ON YOUR OBJECTIVE</div>
      ${warn}
      ${summaryRows}
      ${form}
    </section>`;

  bindAssignmentCard();
}

function bindAssignmentCard() {
  const host = document.getElementById("assignment-card-host");
  if (!host) return;
  const yes = host.querySelector('[data-action="assign-confirm"]');
  if (yes) yes.addEventListener("click", () => {
    state.assignmentConfirmed = true;
    renderAssignmentCard();
  });
  const change = host.querySelector('[data-action="assign-change"]');
  if (change) change.addEventListener("click", () => renderAssignmentCard({ formOpen: true }));
  const save = host.querySelector('[data-action="assign-save"]');
  if (save) save.addEventListener("click", () => saveAssignmentFromCard());
}

async function saveAssignmentFromCard() {
  const host = document.getElementById("assignment-card-host");
  if (!host) return;
  const status = document.getElementById("assign-form-status");
  const outcome = (host.querySelector('[data-assign-field="outcome"]') || {}).value || null;
  const group = (host.querySelector('[data-assign-field="group"]') || {}).value || null;
  const cls = state.classifications || [];
  const outcomeRow = cls.find((c) => c.column === outcome);
  if (!outcome) {
    setStatus(status, "Please pick an outcome variable.", "error");
    return;
  }
  if (!_isUsableAsOutcome(outcomeRow)) {
    setStatus(status, `${outcome} is a patient identifier and cannot be used as an outcome variable. Please select a measurement column.`, "error");
    return;
  }
  const groupRow = cls.find((c) => c.column === group);
  if (group && !_isUsableAsGroup(groupRow)) {
    setStatus(status, `${group} cannot be used as a grouping variable.`, "error");
    return;
  }
  setStatus(status, "Saving…", "loading");
  try {
    await api("/assign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: state.jobId, outcome, group: group || null, covariates: [] }),
    });
    state.assignment = { outcome, group: group || null, covariates: [] };
    state.assignmentAutoMatched = true;
    state.assignmentConfirmed = true;
    renderAssignmentCard();
  } catch (err) {
    setStatus(status, `Could not save: ${err.message}`, "error");
  }
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

  // Practice-data extras: longer preview, Step 3 reassurance, optional
  // Excel download, optional "regenerate with changes" shortcut back into
  // the inline custom wizard. Real uploads hide all of this. The "custom"
  // condition derives from the backend flag so deep-link/resume paths work
  // even when state.dataSource was lost (e.g. fresh tab).
  const isPractice = !!(s.is_dummy || s.is_practice_wizard);
  const isCustom = !!s.is_practice_wizard || state.dataSource === "custom";
  const label = $("#preview-zone-label");
  // Backend always returns up to 10 preview rows now. Use the actual array
  // length so the label is honest if a tiny dataset returns fewer.
  if (label) {
    const n = Array.isArray(state.preview) ? state.preview.length : 0;
    label.textContent = `Preview — first ${n || (isPractice ? 10 : 5)} rows`;
  }
  const note = $("#preview-step3-note");
  if (note) note.classList.toggle("is-hidden", !isPractice);
  const dl = $("#btn-download-excel");
  if (dl) dl.classList.toggle("is-hidden", !isPractice);
  const regen = $("#btn-regenerate-custom");
  if (regen) regen.classList.toggle("is-hidden", !isCustom);
}

function _showAiBridgeOverlay(show) {
  const overlay = document.getElementById("ai-bridge-overlay");
  if (!overlay) return;
  overlay.style.display = show ? "flex" : "none";
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

      // Show a full-page loading overlay so users know analysis is in progress
      _showAiBridgeOverlay(true);

      // Call /setup-study (primary) to identify study type, objective, test pairs.
      // This never blocks navigation — errors fall back gracefully.
      const description =
        (state.intake && (state.intake.objectives || state.intake.instructions || "")) || "";
      const outcomeHint =
        (state.intake && (state.intake.outcomes || "")) || "";
      try {
        const setupResult = await api("/setup-study", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            job_id: state.jobId,
            description,
            outcome_hint: outcomeHint,
            profile: selectedDomainProfile(),
            proposal_metadata: proposalMetadataPayload(),
          }),
        });
        state.aiStudy = setupResult;
      } catch (_) {
        // /setup-study failure is non-fatal — fall back to rule-based plan silently.
        // Never surface "AI service unavailable" to the user.
        const cols = (state.classifications || []);
        const nominals  = cols.filter((c) => c.detected_type === "nominal"  || c.detected_type === "ordinal");
        const scales    = cols.filter((c) => c.detected_type === "scale");
        const guessType = nominals.length && scales.length ? "comparison"
                        : nominals.length >= 2              ? "association"
                        : scales.length                     ? "descriptive"
                        :                                     "descriptive";
        const guessOutcome = scales.length    ? scales[0].column
                           : nominals.length  ? nominals[0].column
                           : (cols[0] || {}).column || null;
        state.aiStudy = {
          study_type:  guessType,
          outcome_col: guessOutcome,
          objective:   state.intake
                         ? (state.intake.objectives || state.intake.instructions || "").slice(0, 200)
                         : "",
          sample_size: (state.summary && state.summary.rows) || null,
          test_pairs:  [],
          reasoning:   "",
          confidence:  0,
          source:      "rule_based",
        };
      }

      _showAiBridgeOverlay(false);
      renderSetupScreen(state.aiStudy);
      showScreen("setup");
    } catch (err) {
      _showAiBridgeOverlay(false);
      setStatus(status, `Could not confirm: ${err.message}`, "error");
    }
  });
  $('[data-action="restart"]', $("#screen-preview")).addEventListener("click", restart);
  $$('[data-action="back-to-1"]').forEach((b) => b.addEventListener("click", () => showScreen("1")));

  // Practice-only: Download Excel button hits the practice router directly
  // and lets the browser stream the file (no JSON round-trip).
  const dl = $("#btn-download-excel");
  if (dl) {
    dl.addEventListener("click", () => {
      if (!state.jobId) return;
      window.location.href = `/api/practice/${state.jobId}/excel`;
    });
  }
  // Custom-wizard only: jump back into the wizard at Q3 (smart per-variable
  // settings) so the user can tweak ranges/types and regenerate.
  const regen = $("#btn-regenerate-custom");
  if (regen) {
    regen.addEventListener("click", () => {
      // Keep prior answers in state.customWizard so the wizard re-opens
      // pre-filled. Q3 is where range/type tweaking happens.
      if (!state.customWizard.variables.length) {
        // Fallback if user landed on preview without going through wizard
        // (e.g. via ?practice=...). Send them to Q1 to start fresh.
        openCustomWizard(1);
        return;
      }
      renderCustomQ3Fields();
      openCustomWizard(3);
    });
  }
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

function typeBadge(t, scaleSubtype) {
  const safe = TYPE_LABELS[t] ? t : "exclude";
  // Per spec Rule 3: surface "Scale (continuous)" or "Scale (discrete)"
  // as an info-only suffix so users see how their numeric variable is
  // being summarised. Sub-type never affects which tests run.
  let label = TYPE_LABELS[safe];
  if (safe === "scale" && (scaleSubtype === "continuous" || scaleSubtype === "discrete")) {
    label = `Scale (${scaleSubtype})`;
  }
  return `<span class="se-type-badge t-${safe}">${escapeHtml(label)}</span>`;
}

// MedRAS Variable Intelligence Layer — display labels for the four
// theory-aware axes returned by the backend classifier alongside the
// legacy `detected_type`. See artifacts/medras/app/services/variable_classifier.py.
const INTERPRETATION_LABELS = {
  measurement:      "Measurement",
  count:            "Count",
  // validated_score is a legacy interpretation from a prior iteration of
  // the classifier; the current backend never emits it, but stored
  // sessions may still carry it so we keep the label mapping for
  // backwards compatibility.
  validated_score:  "Score",
  grading:          "Grading / stage",
  binary_indicator: "Binary indicator",
  category:         "Category",
  identifier:       "Identifier",
  date:             "Date / time",
  free_text:        "Free text",
  empty:            "Empty",
};
const FLEX_LABELS = {
  continuous:                "Continuous",
  ordinal:                   "Ordinal",
  categorical:               "Categorical",
  categorical_after_binning: "Banded",
  binary:                    "Binary",
  time_index:                "Time index",
  exclude:                   "—",
};
function renderIntelligence(c) {
  // Backwards-compat: older payloads (or manual edits via the dropdown)
  // may not carry the new fields. Render nothing in that case so the
  // legacy badge keeps standing on its own.
  const interp = c.interpretation;
  if (!interp || !INTERPRETATION_LABELS[interp]) return "";
  const flex = Array.isArray(c.analytical_flexibility) ? c.analytical_flexibility : [];
  const flexHtml = flex
    .filter((f) => FLEX_LABELS[f] && FLEX_LABELS[f] !== "—")
    .map((f) => `<span class="se-vars-flex-chip" data-flex="${escapeHtml(f)}">${escapeHtml(FLEX_LABELS[f])}</span>`)
    .join("");
  const reasoning = c.reasoning ? escapeHtml(c.reasoning) : "";
  const titleAttr = reasoning ? ` title="${reasoning}"` : "";
  return `
    <div class="se-vars-interp"${titleAttr} data-interpretation="${escapeHtml(interp)}">${escapeHtml(INTERPRETATION_LABELS[interp])}</div>
    ${flexHtml ? `<div class="se-vars-flex">${flexHtml}</div>` : ""}
  `;
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

async function refreshClassifications(overrides = [], { render = true, detectCategoryDupes = false } = {}) {
  const data = await api("/classify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      job_id: state.jobId,
      overrides,
      profile: selectedDomainProfile(),
    }),
  });
  state.classifications = data.classifications || [];
  state.issues = data.issues || [];
  state.autoCoding = data.auto_coding_plan || [];
  state.columns = state.classifications.map((c) => c.column);
  if (render) renderClassify();
  if (detectCategoryDupes) await _detectCategoryDupes();
  return data;
}

async function loadVariablesData() {
  // Re-fetch classifications + issues + auto-coding plan from /classify
  // with no overrides. Used on initial entry to Step 3 and after each
  // assistant action.
  const status = $("#classify-status");
  setStatus(status, "Analysing variables…", "loading");
  try {
    await refreshClassifications([], { render: true, detectCategoryDupes: true });
    // Setup may identify an outcome after the initial dataset ingest. Carry
    // that choice into assignment before plan generation.
    if (!state.assignment || !state.assignment.outcome) {
      autoAssignFromIntake();
      renderAssignmentCard();
    }
    setStatus(status, "");
  } catch (err) {
    setStatus(status, `Could not fully refresh variables: ${err.message}`, "error");
  }
}

// ---------------------------------------------------------------------------
// Category near-duplicate detection
// ---------------------------------------------------------------------------

async function _detectCategoryDupes() {
  if (!state.jobId) return;
  const result = await api("/detect-category-dupes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: state.jobId,
        profile: selectedDomainProfile(),
      }),
  });
  state.categoryDupeResults = result;
  _renderCategoryMergePanel(result);
  return result;
}

function _renderCategoryMergePanel(result) {
  const panel = document.getElementById("category-merge-panel");
  const listEl = document.getElementById("merge-proposals-list");
  const dirtyCount = document.getElementById("merge-dirty-count");
  if (!panel || !listEl) return;

  const columns = result && result.columns ? result.columns : {};
  const allObvious = [];
  const allBorderline = [];

  for (const [col, colResult] of Object.entries(columns)) {
    for (const p of (colResult.obvious || [])) {
      const proposal = { ...p, column: col };
      if (!_isProtectedBreastMerge(proposal)) allObvious.push(proposal);
    }
    for (const p of (colResult.borderline || [])) {
      const proposal = { ...p, column: col };
      if (
        !_isProtectedBreastMerge(proposal)
        && !state.rejectedMergeSuggestions.has(_mergeSuggestionKey(proposal))
      ) {
        allBorderline.push(proposal);
      }
    }
  }

  if (allObvious.length === 0 && allBorderline.length === 0) {
    panel.style.display = "none";
    return;
  }

  const totalDirty = Object.values(columns).reduce((s, r) => s + (r.n_dirty || 0), 0);
  if (dirtyCount) dirtyCount.textContent = `${totalDirty} dirty value${totalDirty !== 1 ? "s" : ""}`;

  const renderGroup = (proposals, badge) => proposals.map((p) => {
    const badgeClass = badge === "AUTO" ? "is-auto" : "is-review";
    const key = _mergeSuggestionKey(p);
    const memberTags = (p.members || []).map((m) => {
      const count = (p.counts || {})[m] || 0;
      const isCanon = m === p.canonical;
      return `<span class="se-merge-member ${isCanon ? "is-canonical" : ""}">
        ${isCanon ? "✓ " : ""}${escapeHtml(m)}<span class="se-merge-member-count"> n=${count}</span>
      </span>`;
    }).join(" ");
    return `<div class="se-merge-proposal">
      <span class="se-merge-badge ${badgeClass}">${badge}</span>
      <code class="se-merge-column">${escapeHtml(p.column)}</code>
      <span class="se-merge-arrow">→</span>
      <span class="se-merge-target">merge to <strong>${escapeHtml(p.canonical)}</strong></span>
      <div class="se-merge-members">${memberTags}</div>
      ${badge === "REVIEW" ? `<div class="se-merge-review-actions">
        <button type="button" class="btn btn-secondary se-btn-small" data-merge-accept="${escapeHtml(key)}">Accept</button>
        <button type="button" class="btn btn-ghost se-btn-small" data-merge-reject="${escapeHtml(key)}">Reject</button>
      </div>` : ""}
    </div>`;
  }).join("");

  listEl.innerHTML =
    renderGroup(allObvious, "AUTO") +
    renderGroup(allBorderline, "REVIEW");

  panel.style.display = "";
  _bindMergePanelButtons(allObvious, allBorderline);
}

function _buildMergePayload(proposals) {
  return proposals.map((p) => ({
    column: p.column,
    canonical: p.canonical,
    members: p.members || [],
  }));
}

function _bindMergePanelButtons(allObvious, allBorderline) {
  const mergeStatus = document.getElementById("merge-status");
  const reviewByKey = new Map(allBorderline.map((proposal) => [_mergeSuggestionKey(proposal), proposal]));

  const applyMerge = async (proposals, label) => {
    if (!proposals.length) return;
    let mergeApplied = false;
    setStatus(mergeStatus, `Applying ${label}…`, "loading");
    try {
      const res = await api("/apply-category-merge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: state.jobId,
          merges: _buildMergePayload(proposals),
          profile: selectedDomainProfile(),
        }),
      });
      mergeApplied = true;
      const n = res.n_merges || 0;
      setStatus(mergeStatus, `Applied ${n} merge${n !== 1 ? "s" : ""} — re-classifying…`, "success");
      // Re-run classification to pick up the cleaned data
      await refreshClassifications([], { render: true, detectCategoryDupes: true });
      state.normality = null;
      state.plan = null;
      state.confirmedTests = null;
      state.confirmedGraphs = null;
      state.results = null;
      state.resultId = null;
      state.analysisVersion = null;
      state.corrResults = null;
      if (state.currentScreen === "plan") await loadPlan();
    } catch (err) {
      setStatus(
        mergeStatus,
        `${mergeApplied ? "Merge applied, but refresh failed" : "Merge failed"}: ${err.message}`,
        "error"
      );
    }
  };

  document.getElementById("btn-apply-obvious-merges")?.addEventListener("click", () =>
    applyMerge(allObvious, "obvious merges"), { once: true });

  document.getElementById("btn-apply-all-merges")?.addEventListener("click", () =>
    applyMerge([...allObvious, ...allBorderline], "all suggestions"), { once: true });

  $$("[data-merge-accept]").forEach((button) => {
    button.addEventListener("click", () => {
      const proposal = reviewByKey.get(button.dataset.mergeAccept);
      if (proposal) applyMerge([proposal], `${proposal.column} label merge`);
    }, { once: true });
  });

  $$("[data-merge-reject]").forEach((button) => {
    button.addEventListener("click", () => {
      state.rejectedMergeSuggestions.add(button.dataset.mergeReject);
      button.closest(".se-merge-proposal")?.remove();
      setStatus(mergeStatus, "Suggestion rejected. No data were changed.", "success");
      if (!document.querySelector("#merge-proposals-list .se-merge-proposal")) {
        document.getElementById("category-merge-panel").style.display = "none";
      }
    }, { once: true });
  });

  document.getElementById("btn-dismiss-merge-panel")?.addEventListener("click", () => {
    document.getElementById("category-merge-panel").style.display = "none";
  }, { once: true });
}

function renderClassify() {
  renderAssignmentCard();
  renderVariableMetrics();
  renderClassifyTable();
  renderFixAllBar();
  renderRecodingPanel();
  renderAutocodeSummary();
  renderAssistantPanel();
  validateConfirm();
}

function renderFixAllBar() {
  const bar = document.getElementById("fix-all-bar");
  if (!bar) return;
  const dupCols = [...new Set(
    (state.issues || []).filter((i) => i.type === "duplicate_values").map((i) => i.column)
  )];
  if (!dupCols.length) {
    bar.style.display = "none";
    bar.innerHTML = "";
    return;
  }
  bar.style.display = "flex";
  const colList = dupCols.map((c) => `<strong>${escapeHtml(c)}</strong>`).join(" ");
  bar.innerHTML = `
    <button type="button" id="fix-all-btn" data-testid="btn-fix-all">
      ✦ Fix all whitespace issues
      <span class="fix-all-count">
        ${dupCols.length} column${dupCols.length === 1 ? "" : "s"}
      </span>
    </button>
    <div class="fix-all-cols">Trims: ${colList}</div>`;
  document.getElementById("fix-all-btn")?.addEventListener("click", () => trimAllWhitespace(dupCols));
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

function _isCategoricalClinicalMarkerName(column) {
  return /(^|[\W_])(her\s*2|her2|her2neu|her2\s*neu|erbb2|er|pr|ar|lvi|ene|necrosis|dcis)($|[\W_])/i
    .test(String(column || ""));
}

function _issueFixCommand(column, issueType) {
  switch (issueType) {
    case "text_in_numeric":
      return _isCategoricalClinicalMarkerName(column) ? null : `Strip the prefix from ${column}`;
    case "numeric_as_id":    return `Exclude ${column} from analysis`;
    case "low_unique_nominal": return `Exclude ${column} from analysis`;
    case "high_missing":     return `Exclude ${column} from analysis`;
    case "duplicate_values": return `Trim whitespace from ${column}`;
    default: return null;
  }
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
      const fixCmd = _issueFixCommand(c.column, i.type);
      const fixBtn = fixCmd
        ? `<button type="button" class="se-issue-fix-btn" data-fix-cmd="${escapeHtml(fixCmd)}" title="Send fix command to assistant">Fix →</button>`
        : "";
      return `<div class="se-issue-sub${cls}" data-testid="issue-${escapeHtml(c.column)}-${i.type}">${escapeHtml(i.message)}${fixBtn}</div>`;
    }).join("");

    // Per spec Rule 2: surface the auto-strip notice directly on the
    // affected row so users see exactly which column was rewritten and
    // can undo it without hunting through a dataset-level banner.
    const cleanupUndo = c.cleanup_undo_available
      ? `<button type="button" class="se-cleanup-undo"
                   data-cleanup-undo="${escapeHtml(c.column)}"
                   data-testid="button-cleanup-undo-${escapeHtml(c.column)}">Undo</button>`
      : "";
    const cleanupHtml = c.cleanup_note
      ? `<div class="se-cleanup-note" data-testid="cleanup-${escapeHtml(c.column)}">
           <span class="se-cleanup-icon">✓</span>
           <span class="se-cleanup-text">${escapeHtml(c.cleanup_note)}</span>
           ${cleanupUndo}
         </div>`
      : "";

    return `<tr data-row="${idx}" data-testid="classify-row-${escapeHtml(c.column)}">
      <td>
        <div class="se-vars-col-name">${escapeHtml(c.column)}</div>
        ${cleanupHtml}
        ${issueHtml}
      </td>
      <td>
        <div class="se-vars-type-stack">
          ${typeBadge(c.detected_type, c.scale_subtype)}
          ${renderIntelligence(c)}
        </div>
      </td>
      <td>${samples}</td>
      <td>${missing}</td>
      <td class="se-vars-table-action">
        <label class="se-type-override" data-testid="override-wrap-${escapeHtml(c.column)}">
          <input type="checkbox"
                 data-override-toggle="${escapeHtml(c.column)}"
                 data-testid="check-override-${escapeHtml(c.column)}"
                 aria-label="Correct the type for ${escapeHtml(c.column)}" />
          <span>Change</span>
        </label>
        <select class="se-type-select is-collapsed"
                data-col="${escapeHtml(c.column)}"
                data-testid="select-type-${escapeHtml(c.column)}"
                aria-label="Pick a different type for ${escapeHtml(c.column)}">${opts}</select>
      </td>
    </tr>`;
  }).join("");

  // Per spec Rule 2: wire the inline "Undo" button on each cleanup
  // notice. POSTs to /api/stats/cleanup-undo, then re-classifies so the
  // restored column shows up with its original text values + a fresh
  // type badge (usually Nominal once the strings are back).
  $$("[data-fix-cmd]", tbody).forEach((btn) => {
    btn.addEventListener("click", () => {
      sendAssistantMessage(btn.dataset.fixCmd);
      btn.closest(".se-assistant-panel, #screen-3") && setTimeout(() => {
        const thread = $("#assistant-thread");
        if (thread) thread.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }, 100);
    });
  });

  $$("[data-cleanup-undo]", tbody).forEach((btn) => {
    btn.addEventListener("click", async () => {
      const col = btn.dataset.cleanupUndo;
      btn.disabled = true;
      btn.textContent = "Undoing…";
      try {
        const res = await fetch("/api/stats/cleanup-undo", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_id: state.jobId, column: col }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        // Re-classify to refresh the row with the restored text values.
        await refreshClassifications([], { render: true, detectCategoryDupes: true });
        setStatus($("#classify-status"), `Restored original values for ${col}.`, "success");
      } catch (err) {
        btn.disabled = false;
        btn.textContent = "Undo";
        window.medrasAlert(`Couldn't undo: ${err.message}`, 'error');
      }
    });
  });

  // The dropdown is hidden behind a "Change" checkbox so the system's
  // auto-decision is the primary display. Users only see the dropdown
  // when they explicitly opt-in to override.
  $$("[data-override-toggle]", tbody).forEach((cb) => {
    cb.addEventListener("change", () => {
      const col = cb.dataset.overrideToggle;
      const sel = tbody.querySelector(
        `select.se-type-select[data-col="${CSS.escape(col)}"]`,
      );
      if (!sel) return;
      sel.classList.toggle("is-collapsed", !cb.checked);
      if (cb.checked) sel.focus();
    });
  });

  $$("select.se-type-select", tbody).forEach((sel) => {
    sel.addEventListener("change", () => {
      const col = sel.dataset.col;
      const c = state.classifications.find((x) => x.column === col);
      if (!c) return;
      c.detected_type = sel.value;
      c.reason = `Manually set to ${sel.value}.`;
      // Manual override invalidates the Variable Intelligence Layer
      // axes — they were derived from the auto-classified detected_type
      // and we don't have the raw series client-side to recompute them.
      // Clear them so the UI doesn't show contradictory information;
      // the next /classify round-trip will repopulate them via the
      // backend reenrich_after_override hook.
      c.interpretation = null;
      c.statistical_nature = null;
      c.analytical_flexibility = null;
      c.reasoning = null;
      const row = sel.closest("tr");
      if (row) {
        const stack = row.querySelector(".se-vars-type-stack");
        if (stack) {
          stack.innerHTML = typeBadge(sel.value, c.scale_subtype) + renderIntelligence(c);
        } else {
          const badge = row.querySelector(".se-type-badge");
          if (badge) badge.outerHTML = typeBadge(sel.value);
        }
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
    if (m.role === "typing") {
      return `<div class="se-chat-msg is-typing" data-testid="chat-msg-${i}-typing">
        <span class="se-typing-dot"></span><span class="se-typing-dot"></span><span class="se-typing-dot"></span>
      </div>`;
    }
    const cls = ({ system: "is-system", user: "is-user", action: "is-action",
                   ai: "is-ai", clarify: "is-clarify" })[m.role] || "is-system";
    const prefix = m.role === "action" ? "✓ " : "";
    return `<div class="se-chat-msg ${cls}" data-testid="chat-msg-${i}-${m.role}">${prefix}${escapeHtml(m.text)}</div>`;
  }).join("");
  out.scrollTop = out.scrollHeight;
}

function renderAssistantChips() {
  const out = $("#assistant-chips");
  if (!out) return;

  const chips = [];

  // 1. Issue-specific "Fix" chip for every flagged column (most useful — at top)
  const flaggedCols = [...new Set((state.issues || []).map((i) => i.column))].slice(0, 4);
  flaggedCols.forEach((col) => {
    const colIssues = issuesForColumn(col);
    colIssues.forEach((issue) => {
      const cmd = _issueFixCommand(col, issue.type);
      if (cmd) chips.push({ label: `Fix "${col}"`, text: cmd });
    });
  });

  // 2. Always include a global suggestion chip
  chips.push({ label: "What should I do?", text: "What's your suggestion?" });

  // 3. Type-change and exclude shortcuts for the first usable column
  const firstUsable = state.classifications.find(
    (c) => c.detected_type !== "id" && c.detected_type !== "exclude",
  );
  if (firstUsable) {
    chips.push({
      label: `Change type of "${firstUsable.column}"`,
      text: `What type should ${firstUsable.column} be?`,
    });
    chips.push({
      label: `Exclude "${firstUsable.column}"`,
      text: `Exclude ${firstUsable.column} from analysis`,
    });
  }

  // "Trim all" button — shown when ≥2 columns have duplicate_values issues.
  const dupCols = [...new Set(
    (state.issues || []).filter(i => i.type === "duplicate_values").map(i => i.column)
  )];
  const trimAllHtml = dupCols.length >= 2
    ? `<button type="button" class="se-chip se-chip-good" id="chip-trim-all"
         data-testid="chip-trim-all"
         title="Remove trailing/leading spaces from ${dupCols.length} columns at once">
         ✦ Trim all ${dupCols.length} columns
       </button>`
    : "";

  out.innerHTML = trimAllHtml + chips.map(
    (c, i) => `<button type="button" class="se-chip" data-chip="${i}" data-testid="chip-${i}">${escapeHtml(c.label)}</button>`
  ).join("");

  const trimAllBtn = out.querySelector("#chip-trim-all");
  if (trimAllBtn) trimAllBtn.addEventListener("click", () => trimAllWhitespace(dupCols));

  $$(".se-chip:not(#chip-trim-all)", out).forEach((btn, i) => {
    btn.addEventListener("click", () => sendAssistantMessage(chips[i].text));
  });
}

async function trimAllWhitespace(dupCols) {
  const names = dupCols.join(", ");
  state.assistantThread.push({ role: "user", text: `Trim whitespace from all flagged columns (${names})` });
  state.assistantThread.push({ role: "typing", text: "" });
  renderAssistantThread();
  const input = $("#assistant-input");
  if (input) input.disabled = true;
  const clearTyping = () => {
    state.assistantThread = state.assistantThread.filter(m => m.role !== "typing");
  };
  try {
    const res = await api("/trim-all-whitespace", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: state.jobId }),
    });
    clearTyping();
    if (res.status === "applied") {
      state.assistantThread.push({ role: "action", text: "✓ " + (res.confirmation_message || "Done.") });
      await refreshClassifications([], { render: true, detectCategoryDupes: true });
    } else {
      state.assistantThread.push({ role: "clarify", text: res.confirmation_message || "No changes needed." });
      renderAssistantThread();
    }
  } catch (err) {
    clearTyping();
    state.assistantThread.push({ role: "clarify", text: `Could not trim all: ${err.message}` });
    renderAssistantThread();
  } finally {
    if (input) input.disabled = false;
  }
}

async function sendAssistantMessage(message) {
  const text = (message || "").trim();
  if (!text) return;
  state.assistantThread.push({ role: "user", text });
  state.assistantThread.push({ role: "typing", text: "" });
  renderAssistantThread();
  const input = $("#assistant-input");
  if (input) { input.value = ""; input.disabled = true; }

  const clearTyping = () => {
    state.assistantThread = state.assistantThread.filter((m) => m.role !== "typing");
  };

  try {
    let res = await api("/variable-assistant", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: state.jobId, message: text }),
    });
    clearTyping();
    if (res.status === "preview") {
      const preview = res.change_preview || {};
      const approved = confirmAIStateChange("Variable Assistant suggested a change", {
        affected: preview.affected || res.column,
        before: preview.before,
        after: preview.after,
        details: preview.summary || "",
      });
      if (!approved) {
        state.assistantThread.push({ role: "clarify", text: "Cancelled. No variable or preprocessing changes were made." });
        renderAssistantThread();
        return;
      }
      state.assistantThread.push({ role: "action", text: "Applying confirmed change…" });
      renderAssistantThread();
      res = await api("/variable-assistant", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: state.jobId,
          message: text,
          confirmed_action: res.confirmed_action,
        }),
      });
    }
    if (res.status === "applied") {
      state.assistantThread.push({ role: "action", text: "✓ " + (res.confirmation_message || "Done.") });
      await refreshClassifications([], { render: true, detectCategoryDupes: true });
    } else {
      // Mutation not understood — route to AI chatbox for explanation / guidance
      let aiReplied = false;
      if (state.jobId) {
        try {
          const aiRes = await api("/ai-chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ job_id: state.jobId, kind: "variables", message: text }),
          });
          state.assistantThread.push({ role: aiRes.role || "ai", text: aiRes.text || res.confirmation_message || "Could you rephrase?" });
          aiReplied = true;
        } catch (_) {}
      }
      if (!aiReplied) {
        state.assistantThread.push({ role: "clarify", text: res.confirmation_message || "Could you rephrase that as a command? e.g. 'rename X to Y' or 'exclude Z'." });
      }
      renderAssistantThread();
    }
  } catch (err) {
    clearTyping();
    state.assistantThread.push({
      role: "clarify",
      text: `Variable Assistant action failed: ${err.message}. No confirmed action remains pending.`,
    });
    try {
      await refreshClassifications([], { render: true, detectCategoryDupes: false });
    } catch (_) {
      renderAssistantThread();
    }
    renderAssistantThread();
  } finally {
    if (input) input.disabled = false;
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
    if (_isCategoricalClinicalMarkerName(i.column)) return false;
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
      await refreshClassifications(overrides, { render: false, detectCategoryDupes: false });
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

  const impossible = q.impossible_values || [];
  const dups = q.duplicates || { exact_duplicate_rows: [], duplicate_id_groups: [] };
  const dupRows = (dups.exact_duplicate_rows || []).length;
  const dupGroups = (dups.duplicate_id_groups || []).length;
  const dupCount = dupRows + dupGroups;
  const logical = q.logical_errors || [];

  // ---- Quality score → colour band (green / amber / red) ----
  const score = Number(s.quality_score ?? 100);
  const band = s.score_band || (score >= 90 ? "green" : score >= 70 ? "amber" : "red");
  const missingness = s.missingness || {};

  // ---- Top metric cards (Fix 10 — colour coded by value) ----
  // Issues / Duplicates: green at 0, amber when > 0
  // Score: green/amber/red bands
  const issueBand = impossible.length === 0 ? "green" : "amber";
  const dupBand = dupCount === 0 ? "green" : "amber";
  const allClean = impossible.length === 0 && dupCount === 0 && logical.length === 0;
  const scoreExplanation = allClean && score < 100
    ? (Object.values(missingness).some((pct) => Number(pct) > 0)
      ? "Quality score is reduced due to missing data, but no blocking quality issues remain."
      : "Quality score is reduced by non-blocking quality indicators; no blocking quality issues remain.")
    : "Score accounts for missingness, outliers, duplicates, and consistency.";
  $("#quality-summary").innerHTML = `
    <div class="se-q-card" data-band="neutral"><div class="se-q-label">Total records</div><div class="se-q-value" data-testid="q-total-records">${s.total_records ?? 0}</div></div>
    <div class="se-q-card" data-band="neutral"><div class="se-q-label">Variables checked</div><div class="se-q-value" data-testid="q-vars-checked">${s.variables_checked ?? 0}</div></div>
    <div class="se-q-card" data-band="${issueBand}"><div class="se-q-label">Issues found</div><div class="se-q-value" data-testid="q-issues">${impossible.length}</div></div>
    <div class="se-q-card" data-band="${dupBand}"><div class="se-q-label">Duplicates</div><div class="se-q-value" data-testid="q-duplicates">${dupCount}</div></div>
    <div class="se-q-card is-score" data-band="${band}">
      <div class="se-q-label">Quality score</div>
      <div class="se-q-value" data-testid="q-score">${score}/100</div>
      <div class="se-q-note" data-testid="q-score-explanation">${scoreExplanation}</div>
    </div>
  `;

  // ---- Smart collapse decision (Fix 1) ----
  // When all three Section counts are zero we replace the tables with a
  // single celebratory banner and hide every section / sticky button. The
  // banner keeps its own "Apply and continue" button.
  const screen4 = document.getElementById("screen-4");
  if (screen4) screen4.classList.toggle("has-clean-banner", allClean);

  const banner = document.getElementById("dq-clean-banner");
  if (banner) {
    if (allClean) {
      banner.innerHTML = `
        <div class="se-clean-banner" data-testid="banner-clean">
          <div class="se-clean-banner-head">
            <span class="se-clean-banner-tick" aria-hidden="true">✓</span>
            <h3>Your dataset is clean</h3>
          </div>
          <p>No outliers, duplicate records, or consistency errors were detected.</p>
          <button type="button" class="btn btn-primary" data-action="apply-quality" data-testid="button-apply-quality">Apply and continue →</button>
        </div>
      `;
      banner.classList.remove("is-hidden");
      // Re-bind: the banner button is a fresh element so the original
      // listener on the inline button doesn't apply to it.
      const btn = banner.querySelector('[data-action="apply-quality"]');
      if (btn) btn.addEventListener("click", _applyQualityHandler);
    } else {
      banner.innerHTML = "";
      banner.classList.add("is-hidden");
    }
  }

  // ---- Section visibility (Fix 1, 3 — hide empty sections + bulk btns) ----
  const wrapA = document.getElementById("dq-impossible-wrap");
  const wrapB = document.getElementById("dq-dup-wrap");
  const wrapC = document.getElementById("dq-logical-wrap");
  if (wrapA) wrapA.classList.toggle("is-hidden", impossible.length === 0);
  if (wrapB) wrapB.classList.toggle("is-hidden", dupCount === 0);
  if (wrapC) wrapC.classList.toggle("is-hidden", logical.length === 0);
  // Bulk-action row only appears when Section A has rows.
  const bulkRow = document.querySelector("#dq-impossible-wrap .se-bulk-row");
  if (bulkRow) bulkRow.classList.toggle("is-hidden", impossible.length === 0);

  // ---- Section A — impossible values table ----
  $('[data-testid="count-impossible"]').textContent = impossible.length;
  const tA = $("#dq-impossible-table tbody");
  if (impossible.length) {
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
  } else {
    tA.innerHTML = "";
  }

  // ---- Section B — duplicates ----
  $('[data-testid="count-duplicates"]').textContent = dupCount;
  const dupBody = $("#dq-dup-body");
  let dupHtml = "";
  if (dupRows) {
    dupHtml += `<p data-testid="dq-exact-summary"><strong>${dupRows}</strong> exact duplicate rows. They will be removed automatically when you continue.</p>`;
  }
  if (dupGroups) {
    dupHtml += `<p>Repeated IDs in <strong>${escapeHtml(dups.duplicate_id_groups[0].id_column)}</strong>: ${dupGroups} ID${dupGroups === 1 ? "" : "s"} appear more than once.</p>`;
  }
  dupBody.innerHTML = dupHtml;

  // ---- Section C — consistency errors (now includes case/near-dup/numeric-text) ----
  $('[data-testid="count-logical"]').textContent = logical.length;
  const tC = $("#dq-logical-table tbody");
  if (logical.length) {
    tC.innerHTML = logical.map((f, i) => `
      <tr data-testid="logical-row-${i}">
        <td>${f.row + 1}</td>
        <td>${escapeHtml(f.variable)}</td>
        <td>${escapeHtml(String(f.value))}</td>
        <td>${escapeHtml(f.issue)}</td>
        <td><em>Flagged for review</em></td>
      </tr>
    `).join("");
  } else {
    tC.innerHTML = "";
  }

  // ---- Section D — high missing data decisions ----
  renderMissingDecisions();
  _updateQualityContinueGate();

  // ---- Sticky button visibility (Fix 5) ----
  // The two sticky buttons live outside the screen markup so we toggle
  // them centrally from here. They're only on-screen for Step 4 and only
  // when at least one issue table is shown.
  _toggleStickyStep4Buttons(!allClean);
}

/* ------------------------------------------------------------------ */
/*  Missing-data decision cards (Section D of Step 4)                  */
/* ------------------------------------------------------------------ */

function renderMissingDecisions() {
  // state.classifications records use: .column (name), .missing (count), .missing_pct, .detected_type
  const cols = (state.classifications || []).filter((c) => (c.missing_pct || 0) > 5);
  const wrap    = document.getElementById("dq-missing-wrap");
  const countEl = document.getElementById("count-missing");
  const body    = document.getElementById("dq-missing-body");
  if (!wrap || !body) return;

  if (cols.length === 0) {
    wrap.style.display = "none";
    return;
  }

  wrap.style.display = "";
  if (countEl) countEl.textContent = cols.length;
  state.missingDecisions = state.missingDecisions || {};

  body.innerHTML = cols.map((col) => {
    const colKey   = col.column;
    const pct      = (col.missing_pct || 0).toFixed(1);
    const isHigh   = col.missing_pct > 30;
    const dtype    = col.detected_type || "";
    const isNum    = dtype === "scale" || dtype === "ordinal" || dtype === "discrete";
    const isCat    = dtype === "nominal" || dtype === "binary";
    const existing = state.missingDecisions[colKey];
    const colId    = colKey.replace(/[^a-zA-Z0-9]/g, "_");

    const opt = (val, label, sub) =>
      `<label class="se-missing-opt">
        <input type="radio" name="md-${colId}" value="${val}"
          ${existing === val ? "checked" : ""}
          data-col="${escapeHtml(colKey)}"
          class="se-missing-radio" />
        <span><strong>${label}</strong>${sub ? ` — <em>${sub}</em>` : ""}</span>
      </label>`;

    return `
      <div class="se-missing-card${isHigh ? " is-amber" : ""}" data-col="${escapeHtml(colKey)}">
        <div class="se-missing-card-head">
          <span class="se-missing-col">${escapeHtml(colKey)}</span>
          <span class="se-missing-badge${isHigh ? " is-amber" : ""}">
            ${col.missing ?? "?"} missing &bull; ${pct}%
          </span>
          ${isHigh ? `<span class="se-missing-warn">⚠ &gt;30% — exclusion recommended</span>` : ""}
        </div>
        <div class="se-missing-opts" role="radiogroup" aria-label="Decision for ${escapeHtml(colKey)}">
          ${opt("exclude",       "Exclude",       "remove this variable from all analyses")}
          ${opt("keep",          "Keep",          "note the missing rate in the report")}
          ${isNum ? opt("impute_mean",   "Impute mean",   "fill missing values with the column mean") : ""}
          ${isNum ? opt("impute_median", "Impute median", "fill missing values with the column median") : ""}
          ${isCat ? opt("impute_mode",   "Impute mode",   "fill missing values with the most common value") : ""}
        </div>
      </div>`;
  }).join("");

  // Bind radio changes → update state + re-check gate
  $$(".se-missing-radio").forEach((radio) => {
    radio.addEventListener("change", () => {
      state.missingDecisions[radio.dataset.col] = radio.value;
      _updateMissingContinueGate();
    });
  });

  _updateMissingContinueGate();
}

function _updateMissingContinueGate() {
  // Missingness is non-blocking on Step 4. Decisions can be applied here or
  // deferred to the dedicated missing-data screen before normality testing.
  _updateQualityContinueGate();
}

function _updateQualityContinueGate() {
  const validActions = new Set(["keep", "remove", "cap", "review"]);
  const unresolvedActionable = (state.qualityActions || []).some(
    (item) => !item || !validActions.has(item.action)
  );
  $$('[data-action="apply-quality"]').forEach((btn) => {
    btn.disabled = unresolvedActionable;
  });
}

function _buildMissingDecisionPayload(currentColumns, selectedDecisions = {}) {
  const allowedColumns = new Set((currentColumns || []).map((c) => c.column));
  const actionMap = {
    keep: "leave",
    leave: "leave",
    impute_mean: "impute_mean",
    impute_median: "impute_median",
    impute_mode: "impute_mode",
    drop_rows: "drop_rows",
  };
  const unsupported = Object.entries(selectedDecisions)
    .filter(([column, action]) => allowedColumns.has(column) && !actionMap[action]);
  const missingDecisions = Object.entries(selectedDecisions)
    .filter(([column, action]) => allowedColumns.has(column) && actionMap[action])
    .map(([column, action]) => ({ column, action: actionMap[action] }));
  return { decisions: missingDecisions, unsupported };
}

// Shared apply-quality logic so it can be wired both to the inline button
// and to the clean-banner button without duplicating the network code.
async function _applyQualityHandler() {
  const status = $("#quality-status");

  // Step 0 — apply user's missing-data decisions before running quality fixes
  const missingCols = (state.classifications || []).filter((c) => (c.missing_pct || 0) > 5);
  if (missingCols.length > 0 && state.missingDecisions && Object.keys(state.missingDecisions).length > 0) {
    const { decisions: missingDecisions, unsupported } =
      _buildMissingDecisionPayload(missingCols, state.missingDecisions);
    if (unsupported.length) {
      setStatus(
        status,
        `Unsupported missing-data action for ${unsupported.map(([column]) => column).join(", ")}. Choose Keep or an imputation option.`,
        "error"
      );
      return;
    }
    setStatus(status, "Applying missing-data decisions…", "loading");
    try {
      await api("/apply-missing-decisions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: state.jobId,
          decisions: missingDecisions,
        }),
      });
      state.missingDecisions = {};
    } catch (err) {
      setStatus(status, `Could not apply missing-data decisions: ${err.message}`, "error");
      return;
    }
  }

  setStatus(status, "Applying quality actions…", "loading");
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
    // Skip the old Assign step — the wizard's outcome/group answers were
    // auto-matched during ingestDataset and confirmed on the Step 3 card.
    // Re-save assignment defensively in case the user changed it on the card.
    if (state.assignment && state.assignment.outcome) {
      try {
        await api("/assign", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            job_id: state.jobId,
            outcome: state.assignment.outcome,
            group: state.assignment.group || null,
            covariates: [],
          }),
        });
      } catch (_) { /* tolerate; loadNormality doesn't need assignment */ }
    }
    // Route to screen-missing based on state.classifications (>= 5% missing),
    // not DOM content — the DOM isn't populated until renderMissingScreen() runs.
    // The classifier stores missing_pct on a 0–100 scale, so the threshold is 5.
    const highMissingCols = (state.classifications || []).filter(
      (c) => (c.missing_pct || 0) >= 5
    );
    if (highMissingCols.length > 0) {
      renderMissingScreen();
      showScreen("missing");
      return;
    }
    showScreen("normality");
    loadNormality();
  } catch (err) {
    setStatus(status, `Could not apply: ${err.message}`, "error");
  }
}

function _toggleStickyStep4Buttons(continueVisible) {
  // The sticky bar has two children with independent visibility rules:
  //   - Back button: always visible on Step 4 (so users can return to Step 3
  //     even from the clean-banner state).
  //   - Continue button: hidden when the clean-banner takes over (the
  //     banner has its own continue) and on every screen other than 4.
  const sticky = document.getElementById("dq-sticky-actions");
  if (!sticky) return;
  const onStep4 = state.currentScreen === "4";
  const backBtn = sticky.querySelector(".se-sticky-back");
  const contBtn = sticky.querySelector(".se-sticky-continue");
  if (backBtn) backBtn.classList.toggle("is-hidden", !onStep4);
  if (contBtn) contBtn.classList.toggle("is-hidden", !(onStep4 && continueVisible));
  // The wrapper itself stays in the DOM but collapses when neither child
  // is shown, so it doesn't intercept any layout space.
  sticky.classList.toggle("is-hidden", !onStep4);
}

function actionPicker(idx, recommended) {
  const opts = ["keep", "remove", "cap", "review"];
  const labels = { keep: "Keep (default)", remove: "Remove row", cap: "Cap at boundary", review: "Mark for review" };
  return `<select class="se-type-select se-impossible-action" data-i="${idx}" data-testid="action-${idx}">
    ${opts.map((o) => `<option value="${o}"${o === recommended ? " selected" : ""}>${labels[o]}</option>`).join("")}
  </select>`;
}

function bindScreen4() {
  // The Step 3 → Step 4 back trip preserves classifications because we
  // never call restart() here — variable-type overrides survive untouched.
  $$('[data-action="back-to-classify"]').forEach((b) =>
    b.addEventListener("click", () => showScreen("3"))
  );
  $$('[data-action="bulk-impossible"]').forEach((btn) => {
    btn.addEventListener("click", () => {
      const set = btn.dataset.set;
      state.qualityActions.forEach((a) => { a.action = set; });
      $$("select.se-impossible-action").forEach((sel) => { sel.value = set; });
    });
  });
  // Wire every apply-quality button (inline + sticky). The clean-banner
  // version is wired separately when the banner is rendered, since it
  // doesn't exist in the DOM at bind time.
  $$('[data-action="apply-quality"]').forEach((btn) =>
    btn.addEventListener("click", _applyQualityHandler)
  );
}

/* ------------------------------------------------------------------ */
/*  Soon screen + restart                                              */
/* ------------------------------------------------------------------ */

function bindSoon() {
  // Legacy "soon" screen has been replaced by Step 4–8 screens. Keep the
  // function so initApp() continues to compile; wire restart only if the
  // node still exists in the DOM (older cached HTML).
  const node = document.getElementById("screen-soon");
  if (!node) return;
  const restartBtn = node.querySelector('[data-action="restart"]');
  if (restartBtn) restartBtn.addEventListener("click", restart);
  const back = node.querySelector('[data-action="back-to-quality"]');
  if (back) back.addEventListener("click", () => showScreen("4"));
}

/* ------------------------------------------------------------------ */
/*  Step 4 — Normality                                                 */
/*  (Old Step 4 "Assign" was removed — wizard answers are auto-matched  */
/*  on Step 3 via renderAssignmentCard / saveAssignmentFromCard.)       */
/* ------------------------------------------------------------------ */

async function loadNormality() {
  const status = document.getElementById("normality-status");
  setStatus(status, "Running normality tests…", "loading");
  try {
    const data = await api(`/normality/${state.jobId}`);
    state.normality = data;
    renderNormality();
    openChatbox("normality");
    setStatus(status, `Tested ${data.columns.length} scale variable(s).`, "success");
  } catch (err) {
    setStatus(status, `Could not load: ${err.message}`, "error");
  }
}

function renderNormality() {
  const tbody = document.querySelector("#normality-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const rows = (state.normality && state.normality.columns) || [];
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="9"><em>No scale variables to test. Move to the next step.</em></td></tr>`;
    return;
  }
  rows.forEach((r) => {
    const chip = r.decision === "normal"
      ? `<span class="se-chip se-chip-good" data-testid="chip-${r.column}">Normal</span>`
      : r.decision === "non_normal"
        ? `<span class="se-chip se-chip-warn" data-testid="chip-${r.column}">Non-normal</span>`
        : `<span class="se-chip se-chip-muted" data-testid="chip-${r.column}">Insufficient</span>`;
    const overrideBtn = r.decision === "insufficient" ? "" : `
      <button type="button" class="btn btn-tertiary se-norm-override"
        data-col="${r.column}" data-flip="${r.decision === 'normal' ? 'non_normal' : 'normal'}"
        data-testid="override-${r.column}">
        Mark as ${r.decision === 'normal' ? 'non-normal' : 'normal'}
      </button>`;
    const qq = r.qq_png
      ? `<img class="se-qq-thumb" src="${r.qq_png}" alt="QQ plot for ${r.column}" loading="lazy">`
      : `<span class="se-cov-type">—</span>`;
    const note = r.note ? `<div class="se-norm-note">${r.note}</div>` : "";
    const tr = document.createElement("tr");
    tr.dataset.col = r.column;
    tr.innerHTML = `
      <td><strong>${r.column}</strong>${note}</td>
      <td>${r.n}</td>
      <td>${r.test || '—'}</td>
      <td>${r.p_value === null || r.p_value === undefined ? '—' : (r.p_value < 0.001 ? '&lt;0.001' : r.p_value.toFixed(3))}</td>
      <td>${r.skewness === null || r.skewness === undefined ? '—' : r.skewness.toFixed(2)}</td>
      <td>${r.kurtosis === null || r.kurtosis === undefined ? '—' : r.kurtosis.toFixed(2)}</td>
      <td>${chip}</td>
      <td>${qq}</td>
      <td>${overrideBtn}</td>
    `;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll(".se-norm-override").forEach((btn) => {
    btn.addEventListener("click", () => overrideNormality(btn.dataset.col, btn.dataset.flip));
  });
}

async function overrideNormality(column, decision) {
  try {
    await api("/normality/override", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: state.jobId, column, decision }),
    });
    const row = (state.normality.columns || []).find((c) => c.column === column);
    if (row) {
      row.decision = decision;
      row.overridden = true;
      row.note = (row.note || "") + " (Manually overridden by user.)";
    }
    renderNormality();
  } catch (err) {
    const status = document.getElementById("normality-status");
    setStatus(status, `Override failed: ${err.message}`, "error");
  }
}

function bindNormality() {
  const screen = document.getElementById("screen-normality");
  if (!screen) return;
  const back = screen.querySelector('[data-action="back-to-review"]');
  if (back) back.addEventListener("click", () => showScreen("3"));
  const cont = screen.querySelector('[data-action="continue-to-plan"]');
  if (cont) cont.addEventListener("click", () => { showScreen("plan"); loadPlan(); });
}

/* ------------------------------------------------------------------ */
/*  Step 6 — Plan and Run                                              */
/* ------------------------------------------------------------------ */

async function loadPlan() {
  const status = document.getElementById("plan-status");
  setStatus(status, "Building your plan…", "loading");
  document.getElementById("plan-summary").textContent = "Building your plan…";
  try {
    const data = await api(`/generate-plan/${state.jobId}`);
    state.plan = data.plan;
    state.confirmedTests = new Set((data.plan.tests || []).map((t) => t.id));
    state.confirmedGraphs = new Set((data.plan.graphs || []).map((g) => g.id));
    renderPlan();
    openChatbox("plan");
    setStatus(status, "", "");
  } catch (err) {
    setStatus(status, `Could not build plan: ${err.message}`, "error");
  }
}

function renderPlan() {
  const summary = document.getElementById("plan-summary");
  const descriptive = document.getElementById("plan-descriptive");
  const tests = document.getElementById("plan-tests");
  const multivariate = document.getElementById("plan-multivariate");
  const unavailable = document.getElementById("plan-unavailable");
  const graphs = document.getElementById("plan-graphs");
  if (!summary || !tests || !graphs) return;
  const p = state.plan || { tests: [], graphs: [], outputs: [], summary: "" };
  summary.textContent = p.summary || "";

  // ── Descriptive section — always-on outputs from the plan ─────────
  const allOutputs = p.outputs || [];
  const descriptiveItems = [
    { id: "table_one", icon: "📋", title: "Table 1 — Baseline characteristics",
      why: "Demographics + key variables with descriptive statistics (mean ± SD, median (IQR), frequencies, proportions)." },
    { id: "methods_paragraph", icon: "📝", title: "Methods paragraph",
      why: "Auto-written APA-formatted statistical methods paragraph describing all tests applied." },
    { id: "results_paragraph", icon: "📊", title: "Results paragraph",
      why: "Auto-written results narrative with effect sizes, confidence intervals, and exact p-values for each test." },
  ];
  if (descriptive) {
    descriptive.innerHTML = descriptiveItems.map((item) =>
      `<article class="se-plan-card se-plan-card-fixed" data-testid="card-descriptive-${item.id}">
        <div class="se-plan-card-fixed-row">
          <span class="se-plan-card-icon-sm" aria-hidden="true">${item.icon}</span>
          <span class="se-plan-card-title">${item.title}</span>
        </div>
        <p class="se-plan-card-why">${item.why}</p>
      </article>`
    ).join("");
  }

  // ── Analytical tests ──────────────────────────────────────────────
  const layers = p.analysis_layers || {};
  const bivariateTests = layers.bivariate || (p.tests || []).filter((t) => t.analysis_family !== "regression");
  const multivariateTests = layers.multivariate || (p.tests || []).filter((t) => t.analysis_family === "regression");
  const bivariateHeading = document.querySelector('[data-testid="plan-tests-section"] .se-plan-section-heading');
  if (bivariateHeading) bivariateHeading.textContent = "Bivariate analysis";
  tests.innerHTML = bivariateTests.map((t) => planCard(t, "tests")).join("");
  if (multivariate) {
    multivariate.innerHTML = multivariateTests.map((item) =>
      item.execution_status === "recommended_only"
        ? planSuggestionCard({ ...item, warning: item.why || "Requires researcher confirmation." })
        : planCard(item, "tests")
    ).join("");
  }
  if (unavailable) {
    unavailable.innerHTML = [
      ...(p.unavailable_tests || []).map((item) =>
        planSuggestionCard({ ...item, warning: item.reason || item.warning || "" })
      ),
      ...(p.suggestions || []).map(planSuggestionCard),
      ...(p.warnings || []).map((warning, index) =>
        planSuggestionCard({ id: `layer-warning-${index}`, title: "Planning warning", warning })
      ),
    ].join("");
  }
  graphs.innerHTML = (p.graphs || []).map((g) => planCard(g, "graphs")).join("");

  document.querySelectorAll('[data-plan-toggle]').forEach((cb) => {
    cb.addEventListener("change", () => {
      const set = cb.dataset.kind === "tests" ? state.confirmedTests : state.confirmedGraphs;
      const card = cb.closest(".se-plan-card");
      if (cb.checked) set.add(cb.value); else set.delete(cb.value);
      if (card) card.classList.toggle("is-removed", !cb.checked);
    });
  });

  // Reset the 3 confirmation boxes whenever the plan re-renders so the
  // user re-affirms after any change.
  document.querySelectorAll('[data-confirm]').forEach((cb) => {
    cb.checked = false;
    cb.addEventListener("change", updateRunButton);
  });
  updateRunButton();
}

function planCard(card, kind) {
  const id = card.id;
  const checked = (kind === "tests" ? state.confirmedTests : state.confirmedGraphs).has(id);

  // Variable pair pills (e.g. "Outcome ↔ Group")
  const cols = card.columns || [];
  let pairHtml = "";
  if (cols.length >= 2) {
    pairHtml = `<div class="se-plan-pair">
      <code class="se-plan-col">${escapeHtml(cols[0])}</code>
      <span class="se-plan-pair-sep" aria-hidden="true">↔</span>
      <code class="se-plan-col">${escapeHtml(cols[1])}</code>
    </div>`;
  } else if (cols.length === 1) {
    pairHtml = `<div class="se-plan-pair"><code class="se-plan-col">${escapeHtml(cols[0])}</code></div>`;
  }

  // Parametric / non-parametric badge
  let paramBadge = "";
  if (card.parametric === true) {
    paramBadge = `<span class="se-plan-badge se-plan-badge-param" title="Assumes normally distributed data">Parametric</span>`;
  } else if (card.parametric === false) {
    paramBadge = `<span class="se-plan-badge se-plan-badge-nonparam" title="No normality assumption required">Non-parametric</span>`;
  }

  return `<article class="se-plan-card ${checked ? '' : 'is-removed'}" data-id="${id}" data-testid="card-${kind}-${id}">
    <div class="se-plan-card-header">
      <label class="se-plan-card-toggle">
        <input type="checkbox" data-plan-toggle data-kind="${kind}" value="${id}" ${checked ? 'checked' : ''} data-testid="toggle-${id}">
        <span class="se-plan-card-title">${escapeHtml(card.title)}</span>
      </label>
      ${paramBadge}
    </div>
    ${pairHtml}
    <p class="se-plan-card-why">${escapeHtml(card.why || '')}</p>
  </article>`;
}

function planSuggestionCard(card) {
  return `<article class="se-plan-card se-plan-card-fixed" data-testid="suggestion-${escapeHtml(card.id || '')}">
    <div class="se-plan-card-header">
      <span class="se-plan-card-title">${escapeHtml(card.title || "Optional analysis")}</span>
      <span class="se-plan-badge se-plan-badge-nonparam">${card.blocking ? "Resolve before analysis" : "Requires confirmation"}</span>
    </div>
    <p class="se-plan-card-why">${escapeHtml(card.warning || '')}</p>
  </article>`;
}

function updateRunButton() {
  const allChecked = Array.from(document.querySelectorAll('[data-confirm]')).every((cb) => cb.checked);
  const hasBlockingSuggestion = (state.plan?.suggestions || []).some((item) => item.blocking);
  const btn = document.querySelector('#screen-plan [data-action="run-analysis"]');
  if (btn) btn.disabled = !allChecked || hasBlockingSuggestion;
}

function bindPlan() {
  const screen = document.getElementById("screen-plan");
  if (!screen) return;
  const back = screen.querySelector('[data-action="back-to-normality"]');
  if (back) back.addEventListener("click", () => showScreen("normality"));
  const run = screen.querySelector('[data-action="run-analysis"]');
  if (run) run.addEventListener("click", runAnalysis);
}

/* ------------------------------------------------------------------ */
/*  Step 7 — Results                                                   */
/* ------------------------------------------------------------------ */

async function runAnalysis() {
  const status = document.getElementById("plan-status");
  setStatus(status, "Running analysis — this may take a few seconds…", "loading");
  try {
    const data = await api("/run-analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: state.jobId,
        confirmed_test_ids: Array.from(state.confirmedTests || []),
        confirmed_graph_ids: Array.from(state.confirmedGraphs || []),
      }),
    });
    state.results = data.results;
    state.resultId = data.result_id || data.results?.export_metadata?.result_id || null;
    state.analysisVersion = data.results?.export_metadata?.analysis_version || null;
    setStatus(status, "Done.", "success");
    showScreen("results");
    renderResults();
    openChatbox("results");
    try {
      sessionStorage.setItem('medras.nav.returnHint', JSON.stringify({
        module: 'sigma', label: 'your analysis', url: '/analysis.html',
      }));
    } catch (_) {}
  } catch (err) {
    setStatus(status, `Run failed: ${err.message}`, "error");
  }
}

function renderResults() {
  const tabs = document.getElementById("results-tabs");
  const pane = document.getElementById("results-pane");
  if (!tabs || !pane) return;
  const r = state.results;
  if (!r) {
    pane.innerHTML = "<p>No results yet — run the analysis on Step 6.</p>";
    return;
  }
  const families = [
    ["bivariate", "Bivariate associations"],
    ["regression", "Regression models"],
    ["correlation", "Correlations"],
  ];
  const tabDefs = [{ id: "tab-table-one", label: "Table 1" }];
  families.forEach(([family, label]) => {
    if ((r.tests || []).some((test) => resultFamily(test) === family)) {
      tabDefs.push({ id: `tab-family-${family}`, label });
    }
  });
  if ((r.tests || []).some((test) => resultFamily(test) === "other")) {
    tabDefs.push({ id: "tab-family-other", label: "Other analyses" });
  }
  tabDefs.push({ id: "tab-narrative", label: "Methods + Results" });
  tabs.innerHTML = tabDefs.map((t, i) =>
    `<button type="button" role="tab" class="se-results-tab ${i === 0 ? 'is-active' : ''}" data-tab="${t.id}" data-testid="${t.id}">${t.label}</button>`
  ).join("");
  tabs.querySelectorAll(".se-results-tab").forEach((b) => {
    b.addEventListener("click", () => {
      tabs.querySelectorAll(".se-results-tab").forEach((x) => x.classList.toggle("is-active", x === b));
      renderResultsPane(b.dataset.tab);
    });
  });
  renderResultsPane(tabDefs[0].id);
}

function renderResultsPane(tabId) {
  const pane = document.getElementById("results-pane");
  if (!pane) return;
  const r = state.results;
  if (tabId === "tab-table-one") {
    const t1 = r.table_one || { headers: [], rows: [] };
    pane.innerHTML = `<h3>Table 1 — Baseline characteristics</h3>
      ${tableHtml(t1.headers, t1.rows.map((row) => [row.variable, row.type, ...(row.cells || [])]))}
      <button type="button" class="btn btn-tertiary" data-action="copy-table" data-testid="button-copy-table-one">Copy table</button>`;
    bindCopyTable();
    return;
  }
  if (tabId.startsWith("tab-family-")) {
    const family = tabId.replace("tab-family-", "");
    const familyTests = (r.tests || []).filter((test) => resultFamily(test) === family);
    const familyTitle = {
      bivariate: "Bivariate associations",
      regression: "Regression models",
      correlation: "Correlations",
      other: "Other analyses",
    }[family] || "Analysis results";
    let extraFigures = "";
    if (family === "bivariate") {
      extraFigures = (r.graphs || []).map((g) =>
        `<figure class="se-result-figure"><figcaption>${escapeHtml(g.title)}</figcaption><img src="${escapeHtml(g.png_data_uri)}" alt="${escapeHtml(g.title)}"></figure>`
      ).join("");
    }
    if (family === "regression" && r.forest_plot) {
      extraFigures += `<figure class="se-result-figure"><figcaption>Forest plot — effect sizes</figcaption><img src="${escapeHtml(r.forest_plot)}" alt="Forest plot"></figure>`;
    }
    pane.innerHTML = `<h3>${familyTitle}</h3>${familyTests.map(renderResultTestBlock).join("")}${extraFigures}`;
    bindCopyTable();
    return;
  }
  if (tabId === "tab-narrative") {
    pane.innerHTML = `<h3>Methods</h3><p>${escapeHtml(r.methods_md || '')}</p>
      <h3>Results</h3><p>${escapeHtml(r.results_md || '').replace(/\n\n/g, '</p><p>')}</p>
      <button type="button" class="btn btn-tertiary" data-action="copy-narrative" data-testid="button-copy-narrative">Copy narrative</button>`;
    const btn = pane.querySelector('[data-action="copy-narrative"]');
    if (btn) btn.addEventListener("click", () => {
      navigator.clipboard.writeText(`Methods\n\n${r.methods_md}\n\nResults\n\n${r.results_md}`);
      btn.textContent = "Copied ✓";
    });
    return;
  }
  // Per-test tab.
  const test = (r.tests || []).find((t) => `tab-${t.id}` === tabId);
  if (!test) { pane.innerHTML = ""; return; }
  pane.innerHTML = renderResultTestBlock(test);
  bindCopyTable();
}

function resultFamily(test) {
  if (test && ["bivariate", "regression", "correlation"].includes(test.analysis_family)) {
    return test.analysis_family;
  }
  const type = String((test && test.test_type) || "").toLowerCase();
  if (type.includes("regression") || type.includes("cox")) return "regression";
  if (["pearson", "spearman", "kendall_tau", "correlation"].some((name) => type.includes(name))) return "correlation";
  if (["chi", "fisher", "ttest", "t_test", "mann", "anova", "kruskal", "wilcoxon"].some((name) => type.includes(name))) return "bivariate";
  return "other";
}

function renderResultTestBlock(test) {
  const r = state.results || {};
  let correctionBlock = "";
  if (test.p_corrected !== undefined && test.p_corrected !== null) {
    const origP = (test.p !== undefined && test.p !== null) ? test.p : test.p_value;
    const method = test.correction_method || "corrected";
    const ci = r.correction_info || {};
    correctionBlock = `<div class="se-correction-block" data-testid="correction-${test.id}">
      <div><strong>p (uncorrected)</strong> = ${escapeHtml(fmtPValue(origP))}</div>
      <div><strong>p (${escapeHtml(method)} corrected)</strong> = ${escapeHtml(fmtPValue(test.p_corrected))}</div>
      <p class="se-correction-note"><em>Multiple comparisons correction applied (${escapeHtml(method)}, ${ci.n_tests || ''} tests)</em></p>
    </div>`;
  }
  const tablesHtml = renderResultTables(test);
  const figuresHtml = renderResultFigures(test);
  return `<section class="se-result-test-block"><h4>${escapeHtml(test.title)}</h4>
    ${tablesHtml}
    ${figuresHtml}
    ${correctionBlock}
    <p>${escapeHtml(test.narrative || '')}</p>
    <button type="button" class="btn btn-tertiary" data-action="copy-table" data-testid="button-copy-${test.id}">Copy table</button></section>`;
}

function renderResultTables(test) {
  const tables = Array.isArray(test.tables) ? test.tables.filter((t) =>
    t && Array.isArray(t.headers) && Array.isArray(t.rows) && t.rows.length
  ) : [];
  if (tables.length) {
    return tables.map((t) => `
      <section class="se-result-table-block">
        ${t.title ? `<h4>${escapeHtml(String(t.title))}</h4>` : ""}
        ${tableHtml(t.headers, t.rows)}
      </section>
    `).join("");
  }
  const legacyRows = (test.rows || []).filter((row) =>
    row && Object.prototype.hasOwnProperty.call(row, "label") && Object.prototype.hasOwnProperty.call(row, "value")
  );
  if (!legacyRows.length) return "";
  return tableHtml(["Statistic", "Value"], legacyRows.map((row) => [row.label, row.value]));
}

function renderResultFigures(test) {
  const figures = Array.isArray(test.figures) ? test.figures.filter((fig) => fig && fig.png_data_uri) : [];
  return figures.map((fig) =>
    `<figure class="se-result-figure"><figcaption>${escapeHtml(String(fig.title || "Figure"))}</figcaption><img src="${escapeHtml(String(fig.png_data_uri))}" alt="${escapeHtml(String(fig.title || "Figure"))}"></figure>`
  ).join("");
}

function fmtPValue(p) {
  if (p === null || p === undefined) return "—";
  const n = Number(p);
  if (!isFinite(n) || isNaN(n)) return "—";
  if (n < 0.001) return "< 0.001";
  return n.toFixed(3);
}

function tableHtml(headers, rows) {
  return `<div class="se-table-wrap"><table class="se-table">
    <thead><tr>${headers.map((h) => `<th>${escapeHtml(String(h))}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((row) => `<tr>${row.map((c) => `<td>${escapeHtml(String(c == null ? '' : c))}</td>`).join("")}</tr>`).join("")}</tbody>
  </table></div>`;
}

function bindCopyTable() {
  document.querySelectorAll('[data-action="copy-table"]').forEach((btn) => {
    btn.addEventListener("click", () => {
      const root = btn.closest("#results-pane") || document;
      const tables = Array.from(root.querySelectorAll("table"));
      if (!tables.length) return;
      const tsv = tables.map((table) =>
        Array.from(table.querySelectorAll("tr")).map((tr) =>
          Array.from(tr.querySelectorAll("th,td")).map((c) => c.textContent.trim()).join("\t")
        ).join("\n")
      ).join("\n\n");
      navigator.clipboard.writeText(tsv);
      btn.textContent = "Copied ✓";
    });
  });
}

function bindResults() {
  const screen = document.getElementById("screen-results");
  if (!screen) return;
  const back = screen.querySelector('[data-action="back-to-plan"]');
  if (back) back.addEventListener("click", () => showScreen("plan"));
  const cont = screen.querySelector('[data-action="continue-to-export"]');
  if (cont) cont.addEventListener("click", () => showScreen("export"));

  /* ── Research Assistant trigger ── */
  const raBtn = document.getElementById("btn-ra-open-results");
  if (raBtn) {
    raBtn.addEventListener("click", () => openRADrawer(raBtn));
  }

  /* ── Take to Folio ─────────────────────────────────────────────── */
  const folioBtn = document.getElementById("btn-take-to-folio");
  if (folioBtn) {
    folioBtn.addEventListener("click", () => {
      /* Collect rendered text from the results pane */
      const pane = document.getElementById("results-pane");
      const resultsText = pane ? (pane.innerText || pane.textContent || "") : "";

      /* Build a minimal Sigma payload for Folio */
      const sigma = {
        title: (document.title || "Analysis Results").replace(/\s*·.*$/, "").trim(),
        results: resultsText.slice(0, 8000),
        methods: "",
      };

      /* Supplement with state if available (state object may be on window) */
      try {
        const saved = sessionStorage.getItem("medras.sigma.state");
        if (saved) {
          const st = JSON.parse(saved);
          if (st.methods) sigma.methods = st.methods;
          if (st.title)   sigma.title   = st.title;
        }
      } catch (_) { /* ignore */ }

      sessionStorage.setItem("folio.import.from_sigma", JSON.stringify(sigma));
      window.open("/folio-module/", "_blank");
    });
  }

  /* ── Take to Scriptorium ────────────────────────────────────────── */
  const scriptoriumBtn = document.getElementById("btn-take-to-scriptorium");
  if (scriptoriumBtn) {
    scriptoriumBtn.addEventListener("click", () => {
      const pane = document.getElementById("results-pane");
      const resultsText = pane ? (pane.innerText || pane.textContent || "") : "";

      const sigmaResults = {
        title: (document.title || "Analysis Results").replace(/\s*·.*$/, "").trim(),
        results: resultsText.slice(0, 12000),
      };

      try {
        const saved = sessionStorage.getItem("medras.sigma.state");
        if (saved) {
          const st = JSON.parse(saved);
          if (st.title) sigmaResults.title = st.title;
        }
      } catch (_) { /* ignore */ }

      // Extract structured table data from the results pane DOM
      try {
        const tables = [];
        const paneEl = document.getElementById("results-pane");
        if (paneEl) {
          paneEl.querySelectorAll("table").forEach(function(tbl) {
            const rows = [];
            tbl.querySelectorAll("tr").forEach(function(tr) {
              const cells = [];
              tr.querySelectorAll("th, td").forEach(function(td) {
                cells.push((td.innerText || td.textContent || "").trim());
              });
              if (cells.some(function(c) { return c.length > 0; })) rows.push(cells);
            });
            if (rows.length) {
              // Caption: look for <caption> element or a preceding heading/strong element
              let caption = "";
              const cap = tbl.querySelector("caption");
              if (cap) {
                caption = (cap.innerText || cap.textContent || "").trim();
              } else {
                const prev = tbl.previousElementSibling;
                if (prev && /^(H[1-6]|STRONG|B|P)$/.test(prev.tagName)) {
                  caption = (prev.innerText || prev.textContent || "").trim().slice(0, 120);
                }
              }
              tables.push({ rows: rows, caption: caption });
            }
          });
        }
        sigmaResults.tables = tables;
        sessionStorage.setItem("medras.sigma.results", JSON.stringify(sigmaResults));
      } catch (_) { /* quota — fail silently; editor falls back to folio key */ }

      window.open("/thesis-module/editor.html?ch=results", "_blank");
    });
  }
}

/* ------------------------------------------------------------------ */
/*  Chatboxes 2/3/4 — Normality / Plan / Results explainers           */
/*  (PART 5 of master spec; FIX R9 safety net for chatbox 3)          */
/* ------------------------------------------------------------------ */

const CHATBOX_CHIPS = {
  normality: [
    "Why does normality matter for test selection?",
    "Explain what skewness means",
    "Which variable was borderline?",
    "Can I override a normality decision?",
  ],
  plan: [
    "Add survival analysis (Kaplan-Meier)",
    "Remove regression — I only want comparison",
    "Why parametric vs non-parametric?",
    "What does Tukey HSD do after ANOVA?",
  ],
  results: [
    "What does this p-value mean clinically?",
    "Help me write a results sentence",
    "Explain the confidence interval",
    "Add logistic regression to the analysis",
  ],
};

// FIX R9 — safe parser for chatbox 3 action JSON.
function parseAIAction(responseText) {
  try { return JSON.parse(responseText); } catch (e) {
    const m = responseText.match(/\{[\s\S]*"action"[\s\S]*\}/);
    if (m) { try { return JSON.parse(m[0]); } catch (e2) { return null; } }
    return null;
  }
}

function renderChatThread(kind) {
  const out = document.getElementById(`cb-${kind}-thread`);
  if (!out) return;
  const thread = state.chatThreads[kind] || [];
  out.innerHTML = thread.map((m, i) => {
    if (m.role === "typing") {
      return `<div class="se-chat-msg is-typing" data-testid="cb-${kind}-typing">
        <span class="se-typing-dot"></span><span class="se-typing-dot"></span><span class="se-typing-dot"></span>
      </div>`;
    }
    const cls = ({ system: "is-system", user: "is-user", action: "is-action",
                   ai: "is-ai", clarify: "is-clarify" })[m.role] || "is-system";
    const prefix = m.role === "action" ? "✓ " : "";
    return `<div class="se-chat-msg ${cls}" data-testid="cb-${kind}-msg-${i}-${m.role}">${prefix}${escapeHtml(m.text)}</div>`;
  }).join("");
  out.scrollTop = out.scrollHeight;
}

function renderChatChips(kind) {
  const out = document.getElementById(`cb-${kind}-chips`);
  if (!out) return;
  const chips = CHATBOX_CHIPS[kind] || [];
  out.innerHTML = chips.map((c, i) =>
    `<button type="button" class="se-chip" data-testid="cb-${kind}-chip-${i}">${escapeHtml(c)}</button>`
  ).join("");
  Array.from(out.querySelectorAll(".se-chip")).forEach((btn, i) => {
    btn.addEventListener("click", () => sendChatMessage(kind, chips[i]));
  });
}

async function openChatbox(kind) {
  if (state.chatOpened[kind] || !state.jobId) return;
  state.chatOpened[kind] = true;
  renderChatChips(kind);
  try {
    const res = await api(`/chat/${kind}/opening/${state.jobId}`);
    state.chatThreads[kind].push({ role: "system", text: res.text || "" });
  } catch (err) {
    state.chatThreads[kind].push({
      role: "system",
      text: "Ask me anything about this screen. I explain — the statistical engine calculates.",
    });
  }
  renderChatThread(kind);
}

async function sendChatMessage(kind, message) {
  const text = (message || "").trim();
  if (!text || !state.jobId) return;
  state.chatThreads[kind].push({ role: "user", text });
  // Show typing indicator immediately while waiting for AI response.
  state.chatThreads[kind].push({ role: "typing", text: "" });
  renderChatThread(kind);
  const input = document.getElementById(`cb-${kind}-input`);
  if (input) { input.value = ""; input.disabled = true; }

  try {
    const res = await api(`/ai-chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: state.jobId, kind, message: text }),
    });
    // Remove typing placeholder.
    state.chatThreads[kind] = state.chatThreads[kind].filter((m) => m.role !== "typing");
    if (kind === "plan") {
      handlePlanChatResponse(res);
    } else if (kind === "results") {
      handleResultsChatResponse(res);
    } else {
      state.chatThreads[kind].push({
        role: res.role || "ai",
        text: res.text || "",
      });
    }
  } catch (err) {
    state.chatThreads[kind] = state.chatThreads[kind].filter((m) => m.role !== "typing");
    state.chatThreads[kind].push({ role: "clarify", text: `Could not answer: ${err.message}` });
  } finally {
    if (input) input.disabled = false;
  }
  renderChatThread(kind);
}

// FIX R9 handler — parses ACTION JSON, mutates the plan, falls back to text.
function handlePlanChatResponse(res) {
  const raw = res && res.text ? res.text : "";
  const action = parseAIAction(raw);
  if (action && action.action && action.test_id) {
    if (action.action === "add_test") {
      const approved = confirmAIStateChange("Plan Assistant suggested a change", {
        affected: `planned test: ${action.test_id}`,
        before: state.confirmedTests?.has(action.test_id) ? "included" : "not included",
        after: "included",
        details: action.reason || "",
      });
      if (!approved) {
        state.chatThreads.plan.push({ role: "clarify", text: "Cancelled. The analysis plan was not changed." });
        return;
      }
      addTestToPlanLocal(action.test_id, action.reason || "");
      state.chatThreads.plan.push({
        role: "action",
        text: `Added: ${action.test_id}. ${action.reason || ""}`.trim(),
      });
      return;
    }
    if (action.action === "remove_test") {
      const approved = confirmAIStateChange("Plan Assistant suggested a change", {
        affected: `planned test: ${action.test_id}`,
        before: state.confirmedTests?.has(action.test_id) ? "included" : "not included",
        after: "removed",
        details: action.reason || "",
      });
      if (!approved) {
        state.chatThreads.plan.push({ role: "clarify", text: "Cancelled. The analysis plan was not changed." });
        return;
      }
      removeTestFromPlanLocal(action.test_id);
      state.chatThreads.plan.push({
        role: "action",
        text: `Removed: ${action.test_id}.`,
      });
      return;
    }
  }
  // No actionable JSON — strip any code fences / json blocks then show prose.
  const textPart = raw
    .replace(/```[\s\S]*?```/g, "")
    .replace(/\{[\s\S]*\}/g, "")
    .trim();
  if (textPart.length > 0) {
    state.chatThreads.plan.push({ role: res.role || "ai", text: textPart });
  } else {
    state.chatThreads.plan.push({
      role: "ai",
      text: "I understood your request. To add or remove a test, you can also "
          + "use the tick buttons on the test cards above.",
    });
  }
}

// Results chatbox handler — shows prose, and triggers rerun when AI returns an action.
async function handleResultsChatResponse(res) {
  const raw = (res && res.text) ? res.text : "";
  const action = res.action || parseAIAction(raw);

  if (action && action.action === "rerun") {
    const addIds = action.add_test_ids || [];
    const removeIds = action.remove_test_ids || [];

    // Show a prose explanation of what we're about to do.
    const proseText = raw.replace(/\{[\s\S]*\}/g, "").trim();
    if (proseText) {
      state.chatThreads.results.push({ role: "ai", text: proseText });
    }
    const approved = confirmAIStateChange("Results Assistant suggested a partial re-run", {
      affected: [...addIds, ...removeIds].join(", ") || "result sections",
      before: removeIds.length ? `Current sections include: ${removeIds.join(", ")}` : "Current result sections",
      after: [
        addIds.length ? `add ${addIds.join(", ")}` : "",
        removeIds.length ? `remove ${removeIds.join(", ")}` : "",
      ].filter(Boolean).join("; ") || "re-run selected sections",
      details: "Only the listed result sections will be changed.",
    });
    if (!approved) {
      state.chatThreads.results.push({ role: "clarify", text: "Cancelled. Results were not re-run or replaced." });
      return;
    }
    state.chatThreads.results.push({
      role: "action",
      text: [
        addIds.length ? `Adding: ${addIds.join(", ")}` : "",
        removeIds.length ? `Removing: ${removeIds.join(", ")}` : "",
        "Running analysis…",
      ].filter(Boolean).join(" · "),
    });
    renderChatThread("results");

    try {
      const rerunRes = await api("/rerun-partial", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: state.jobId,
          add_test_ids: addIds,
          remove_test_ids: removeIds,
        }),
      });
      // Merge new/changed tests into state.results without a full rerender.
      // Only patch the tabs/panes for tests that actually changed.
      const incoming = rerunRes.results;
      if (!state.results) {
        state.results = incoming;
        renderResults();
      } else {
        const oldTests = state.results.tests || [];
        const newTests = incoming.tests || [];
        // Build a lookup of the new results keyed by test id
        const newById = Object.fromEntries(newTests.map((t) => [t.id, t]));
        // Remove tests that were in removeIds
        const filtered = oldTests.filter((t) => !removeIds.includes(t.id));
        // Update any test that was re-run (exists in newById)
        const merged = filtered.map((t) => newById[t.id] ? newById[t.id] : t);
        // Append any brand-new tests from addIds that weren't present before
        const existingIds = new Set(filtered.map((t) => t.id));
        for (const t of newTests) {
          if (!existingIds.has(t.id)) merged.push(t);
        }
        state.results = { ...state.results, ...incoming, tests: merged };
        // Patch only the tabs and active pane — rebuild tab bar, keep active selection
        const tabs   = document.getElementById("results-tabs");
        const active = tabs ? (tabs.querySelector(".se-results-tab.is-active")?.dataset.tab || null) : null;
        renderResults();
        // Re-activate the previously active tab if it still exists; else show first
        if (active && tabs) {
          const matchBtn = tabs.querySelector(`[data-tab="${active}"]`);
          if (matchBtn) {
            tabs.querySelectorAll(".se-results-tab").forEach((b) => b.classList.toggle("is-active", b === matchBtn));
            renderResultsPane(active);
          }
        }
      }
      state.resultId = rerunRes.result_id || incoming?.export_metadata?.result_id || null;
      state.analysisVersion = incoming?.export_metadata?.analysis_version || null;
      state.chatThreads.results.push({
        role: "action",
        text: "Analysis updated. Affected result panels have been patched.",
      });
    } catch (err) {
      state.chatThreads.results.push({
        role: "clarify",
        text: `Could not re-run: ${err.message}`,
      });
    }
    return;
  }

  // Plain explanation — no action.
  const prose = raw.replace(/\{[\s\S]*\}/g, "").trim();
  state.chatThreads.results.push({
    role: res.role || "ai",
    text: prose || raw,
  });
}

function addTestToPlanLocal(testId, reason) {
  if (!state.plan) return;
  state.plan.tests = state.plan.tests || [];
  if (!state.plan.tests.some((t) => t.id === testId)) {
    state.plan.tests.push({
      id: testId,
      title: testId,
      why: reason || "Added from the assistant.",
    });
  }
  if (!state.confirmedTests) state.confirmedTests = new Set();
  state.confirmedTests.add(testId);
  renderPlan();
}

function removeTestFromPlanLocal(testId) {
  if (state.confirmedTests) state.confirmedTests.delete(testId);
  if (state.plan && state.plan.tests) {
    // Mark removed (greyed) by unchecking confirmedTests; renderPlan
    // applies is-removed class via the toggle state.
    renderPlan();
  }
}

function bindChatbox(kind) {
  const form = document.getElementById(`cb-${kind}-form`);
  if (!form) return;
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const input = document.getElementById(`cb-${kind}-input`);
    if (input && input.value.trim()) sendChatMessage(kind, input.value);
  });
}

function bindChatboxes() {
  ["normality", "plan", "results"].forEach(bindChatbox);
}

/* ------------------------------------------------------------------ */
/*  Screen AI-CONFIRM — Study type + outcome column confirmation       */
/* ------------------------------------------------------------------ */

const _STUDY_TYPE_LABELS = {
  association: "Association study",
  correlation: "Correlation study",
  comparison:  "Comparison study",
  regression:  "Regression / prediction",
  diagnostic:  "Diagnostic accuracy",
  survival:    "Survival analysis",
  reliability: "Reliability / agreement",
  descriptive: "Descriptive analysis",
};

const _STUDY_TYPE_DESCRIPTIONS = {
  association: "All variables are categorical. Tests the strength of association between each predictor and the outcome using chi-square, Fisher's exact test, Cramér's V, and odds ratios. Important: 'association' and 'correlation' are often confused by researchers — correlation (Pearson/Spearman) specifically measures continuous variable relationships; association applies to categorical data.",
  correlation: "Continuous measurements. Quantifies the linear (Pearson r) or monotonic (Spearman ρ) relationship between continuous predictors and the outcome.",
  comparison:  "Group differences. Compares the outcome between two or more groups — independent t-test / Mann-Whitney U (two groups) or one-way ANOVA / Kruskal-Wallis (multiple groups).",
  regression:  "Prediction and adjusted effects. Fits a linear model for scale outcomes or a logistic model for binary outcomes when the sample and event counts are adequate.",
  diagnostic:  "Test performance. Evaluates sensitivity, specificity, PPV, NPV, and area under the ROC curve (AUC) to assess how well a test identifies the condition.",
  survival:    "Time-to-event. Estimates survival probability (Kaplan-Meier), compares groups (log-rank test), and models hazard ratios (Cox proportional hazards regression).",
  reliability: "Agreement and repeatability. Uses kappa for categorical ratings and ICC / Bland-Altman for continuous measurements.",
  descriptive: "Population profile. Reports frequencies, proportions, means / medians, standard deviations, and 95% confidence intervals for all variables.",
};

const _STUDY_TYPE_ICONS = {
  association: "🔗",
  correlation: "📈",
  comparison:  "⚖️",
  regression:  "📉",
  diagnostic:  "🔬",
  survival:    "⏱️",
  reliability: "✓",
  descriptive: "📋",
};

// Returns the planned statistical test name for a given predictor
function _getPlannedTest(studyType, predictorType, nOutcomeValues) {
  switch (studyType) {
    case "association":
      return nOutcomeValues === 2
        ? "Chi-square / Fisher's exact · Odds Ratio · Cramér's V"
        : "Chi-square · Cramér's V";
    case "correlation":
      if (predictorType === "scale")   return "Pearson r · Spearman ρ";
      if (predictorType === "ordinal") return "Spearman ρ";
      return "Point-biserial r · Phi coefficient";
    case "comparison":
      if (predictorType === "scale" || predictorType === "ordinal")
        return nOutcomeValues === 2
          ? "Independent t-test · Mann-Whitney U"
          : "One-way ANOVA · Kruskal-Wallis";
      return nOutcomeValues === 2
        ? "Chi-square / Fisher's exact · Odds Ratio"
        : "Chi-square · Cramér's V";
    case "diagnostic":
      return "AUC / ROC · Sensitivity · Specificity · PPV · NPV";
    case "survival":
      return "Kaplan-Meier · Log-rank test · Cox regression";
    case "descriptive":
      return "Frequency · Proportion · Mean / Median · 95% CI";
    default:
      return "Chi-square / Fisher's exact";
  }
}

// Plain-English type labels shown in the variables list
const _CONFIRM_TYPE_LABELS = {
  scale:    "continuous",
  ordinal:  "ordinal",
  nominal:  "categorical",
  binary:   "binary (Yes / No)",
  discrete: "count",
};
const _CONFIRM_SKIP_TYPES = new Set(["id", "date", "exclude"]);

function _proposalFriendlySummary(ai) {
  const proposal = ai.proposal_understanding || proposalMetadataPayload() || {};
  const mapping = ai.proposal_mapping || {};
  const title = proposal.study_title || ai.study_title || "your uploaded study";
  const marker = proposal.main_marker || ai.main_marker || "";
  const outcome = mapping.mapped_outcome || ai.outcome_col || proposal.main_outcome_concept || "the main outcome";
  const predictors = (mapping.mapped_predictors || ai.all_predictors || [])
    .filter((v) => v && v !== outcome)
    .slice(0, 12);
  const important = predictors.length ? predictors.join(", ") : "the clinically relevant variables in your sheet";
  const comparison = marker
    ? `${marker} ${outcome}`
    : `${outcome}`;
  return {
    title,
    text:
      `Study: ${title}. ` +
      `Main comparison: ${comparison}. ` +
      `Important variables: ${important}. ` +
      "Recommended analysis: descriptive summary, association testing, and a limited adjusted model if eligible. " +
      "Please confirm or edit before Sigma finalizes the analysis plan.",
  };
}

function renderAiConfirmScreen() {
  const ai = state.aiStudy || {};
  const studyType = ai.study_type || "correlation";
  const outCol    = ai.outcome_col || "";
  const reasoning = ai.reasoning  || "";
  const cleanReasoning = reasoning.replace(/\s*\[.*?\]\s*$/, "").trim();

  const screen = document.getElementById("screen-ai-confirm");
  if (screen) {
    let summary = document.getElementById("ai-doctor-summary");
    if (!summary) {
      summary = document.createElement("div");
      summary.id = "ai-doctor-summary";
      summary.className = "se-confirm-summary";
      screen.insertBefore(summary, screen.firstElementChild?.nextElementSibling || screen.firstElementChild);
    }
    const friendly = _proposalFriendlySummary(ai);
    summary.innerHTML = `
      <strong>Sigma understood your study as:</strong>
      <div>${escapeHtml(friendly.text)}</div>
    `;
  }

  // ── Study-type card ──────────────────────────────────────────────────
  const iconEl = document.getElementById("ai-plan-icon");
  if (iconEl) iconEl.textContent = _STUDY_TYPE_ICONS[studyType] || "📊";

  const typeDisplay = document.getElementById("ai-study-type-display");
  if (typeDisplay) typeDisplay.textContent = _STUDY_TYPE_LABELS[studyType] || studyType;

  const descEl = document.getElementById("ai-study-type-description");
  if (descEl) descEl.textContent = _STUDY_TYPE_DESCRIPTIONS[studyType] || "";

  const reasoningEl = document.getElementById("ai-reasoning-display");
  if (reasoningEl) reasoningEl.textContent = cleanReasoning || _proposalFriendlySummary(ai).text;

  // ── Outcome column display ───────────────────────────────────────────
  const colDisplay = document.getElementById("ai-outcome-col-display");
  if (colDisplay) colDisplay.textContent = outCol || "Not detected — set manually below";

  // ── Populate hidden dropdowns (for manual override + internal wiring) ─
  const colSelect = document.getElementById("ai-outcome-col-select");
  if (colSelect) {
    colSelect.innerHTML = '<option value="">— select a column —</option>';
    const cols = state.columns.map((c) => (typeof c === "string" ? c : c.column));
    cols.forEach((col) => {
      const opt = document.createElement("option");
      opt.value = col;
      opt.textContent = col;
      if (col === outCol) opt.selected = true;
      colSelect.appendChild(opt);
    });
  }
  const typeSelect = document.getElementById("ai-study-type-select");
  if (typeSelect) typeSelect.value = studyType;

  // ── Proceed button label ─────────────────────────────────────────────
  const isPairwise = studyType === "correlation" || studyType === "association";
  const proceedBtn = document.getElementById("btn-ai-proceed");
  if (proceedBtn) {
    proceedBtn.textContent = isPairwise && outCol
      ? "✓ Looks correct — Run Analysis →"
      : "✓ Looks correct — Continue →";
  }

  // ── Detail panels (shown for ALL study types when outcome is known) ──
  if (outCol) {
    _renderAiConfirmDetails(studyType, outCol).catch(() => {});
  } else {
    ["ai-detail-counts", "ai-detail-vars"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.classList.add("is-hidden");
    });
  }

  // ── Test pairs from AI study plan (shown when available) ─────────────
  const pairsSect  = document.getElementById("ai-confirm-test-pairs-section");
  const pairsTbody = document.getElementById("ai-confirm-pairs-tbody");
  const pairs = (state.aiStudy && state.aiStudy.test_pairs) || [];
  if (pairsSect && pairsTbody) {
    if (pairs.length > 0) {
      pairsTbody.innerHTML = pairs.map((p) => `
        <tr>
          <td><code class="se-col-code">${escapeHtml(p.col_a || "")}</code></td>
          <td class="se-pairs-vs">↔</td>
          <td><code class="se-col-code">${escapeHtml(p.col_b || "")}</code></td>
          <td class="se-pairs-test">${escapeHtml(p.test_name || "")}</td>
          <td class="se-pairs-reason">${escapeHtml(p.reason || "")}</td>
        </tr>`).join("");
      pairsSect.classList.remove("is-hidden");
    } else {
      pairsSect.classList.add("is-hidden");
    }
  }
}

async function _renderAiConfirmDetails(studyType, outCol) {
  let countsData = null;
  try {
    countsData = await api(
      `/value-counts/${encodeURIComponent(state.jobId)}?column=${encodeURIComponent(outCol)}`
    );
  } catch (_) {}

  const outcomeCountMap = countsData ? (countsData.counts || {}) : {};
  const outcomeTotal    = countsData ? (countsData.total  || 0) : 0;
  const nOutcomeValues  = Object.keys(outcomeCountMap).length || 2;

  // ── Outcome value distribution ───────────────────────────────────────
  const countsWrap = document.getElementById("ai-detail-counts");
  const countsBody = document.getElementById("ai-detail-counts-body");
  if (countsWrap && countsBody) {
    if (Object.keys(outcomeCountMap).length > 0) {
      countsBody.innerHTML = Object.entries(outcomeCountMap)
        .sort((a, b) => b[1] - a[1])
        .map(([val, n]) => `<span class="se-ai-count-chip">${escapeHtml(val)} = ${n}</span>`)
        .join("") +
        `<span class="se-ai-count-chip" style="background:#f1f5f9;color:#475569">Total = ${outcomeTotal}</span>`;
    }
    countsWrap.classList.remove("is-hidden");
  }

  // ── Predictors + planned tests table ────────────────────────────────
  const predictors = (state.classifications || []).filter(
    (c) => c.column !== outCol && !_CONFIRM_SKIP_TYPES.has(c.detected_type)
  );

  const varsWrap = document.getElementById("ai-detail-vars");
  const varsList = document.getElementById("ai-detail-vars-list"); // now a <tbody>
  if (varsWrap && varsList) {
    if (predictors.length > 0) {
      varsList.innerHTML = predictors.map((c) => {
        const typeLabel = _CONFIRM_TYPE_LABELS[c.detected_type] || c.detected_type;
        const testName  = _getPlannedTest(studyType, c.detected_type, nOutcomeValues);
        return `<tr>
          <td class="se-plan-col-name">${escapeHtml(c.column)}</td>
          <td class="se-plan-col-type">${typeLabel}</td>
          <td class="se-plan-col-test">${escapeHtml(testName)}</td>
        </tr>`;
      }).join("");
      varsWrap.classList.remove("is-hidden");
    } else {
      varsWrap.classList.add("is-hidden");
    }
  }
}

function _updateAiConfirmButtons() {
  const typeSelect = document.getElementById("ai-study-type-select");
  if (!typeSelect) return;
  const studyType = typeSelect.value;
  const isPairwise = studyType === "correlation" || studyType === "association";
  const colSelect  = document.getElementById("ai-outcome-col-select");
  const hasCol     = colSelect && colSelect.value && colSelect.value !== "";
  const colHint    = document.getElementById("ai-outcome-col-required-hint");
  if (colHint) colHint.style.display = (isPairwise && !hasCol) ? "block" : "none";
  // Keep hidden corrBtn in sync (used by proceed-button delegation)
  const corrBtn = document.getElementById("btn-run-correlation");
  if (corrBtn) corrBtn.disabled = !hasCol;
  // Update visible proceed button label
  const proceedBtn = document.getElementById("btn-ai-proceed");
  if (proceedBtn) {
    proceedBtn.textContent = isPairwise && hasCol
      ? "✓ Looks correct — Run Analysis →"
      : "✓ Looks correct — Continue →";
  }
}

function _refreshAiDetailPanels() {
  const typeSelect = document.getElementById("ai-study-type-select");
  const colSelect  = document.getElementById("ai-outcome-col-select");
  const studyType  = typeSelect ? typeSelect.value : "correlation";
  const outCol     = colSelect  ? colSelect.value  : "";
  if (outCol) {
    _renderAiConfirmDetails(studyType, outCol).catch(() => {});
  } else {
    ["ai-detail-counts", "ai-detail-vars"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.classList.add("is-hidden");
    });
  }
}

// ---------------------------------------------------------------------------
// screen-setup — unified study setup (upload-path primary)
// ---------------------------------------------------------------------------

function renderSetupScreen(plan) {
  if (!plan) return;

  const typeEl   = document.getElementById("setup-study-type-display");
  const objEl    = document.getElementById("setup-objective-display");
  const reasonEl = document.getElementById("setup-reasoning-display");
  const nEl      = document.getElementById("setup-sample-size-display");
  const outEl    = document.getElementById("setup-outcome-display");
  const iconEl   = document.getElementById("setup-plan-icon");
  const tbody    = document.getElementById("setup-pairs-tbody");
  const noPairs  = document.getElementById("setup-no-pairs-hint");

  const st = (plan.study_type || "descriptive").toLowerCase();
  if (typeEl)   typeEl.textContent = st.charAt(0).toUpperCase() + st.slice(1) + " study";
  if (iconEl)   iconEl.textContent = _STUDY_TYPE_ICONS[st] || "📊";
  if (objEl)    objEl.textContent  = plan.objective || "—";
  if (reasonEl) {
    reasonEl.textContent = plan.reasoning || "";
    reasonEl.style.display = plan.reasoning ? "" : "none";
  }
  if (nEl) {
    if (plan.sample_size) {
      nEl.textContent = `N = ${plan.sample_size}`;
      nEl.style.display = "";
    } else {
      nEl.style.display = "none";
    }
  }
  if (outEl) {
    if (plan.outcome_col) {
      outEl.textContent = `Outcome: ${plan.outcome_col}`;
      outEl.style.display = "";
    } else {
      outEl.style.display = "none";
    }
  }

  const pairs = plan.test_pairs || [];
  if (tbody) {
    tbody.innerHTML = pairs.map((p) => `
      <tr>
        <td><code class="se-col-code">${escapeHtml(p.col_a || "")}</code></td>
        <td class="se-pairs-vs">↔</td>
        <td><code class="se-col-code">${escapeHtml(p.col_b || "")}</code></td>
        <td class="se-pairs-test">${escapeHtml(p.test_name || "")}</td>
        <td class="se-pairs-reason">${escapeHtml(p.reason || "")}</td>
      </tr>`).join("");
  }
  if (noPairs) noPairs.classList.toggle("is-hidden", pairs.length > 0);

  // Pre-fill description and hide redundant proposal-upload row when
  // study context was already captured on Screen 1.
  const descEl2 = document.getElementById("setup-study-description");
  if (descEl2 && !descEl2.value.trim() && (state.studyDesc || "").trim()) {
    descEl2.value = state.studyDesc;
  }
  const uploadRow = document.querySelector('[data-testid="setup-upload-row"]');
  if (uploadRow) {
    uploadRow.style.display = (state.studyDesc || "").trim() ? "none" : "";
  }

  // Populate grouping-variable dropdown from known columns
  _populateSetupGroupSelect(plan);
}

function _populateSetupGroupSelect(plan) {
  const sel = document.getElementById("setup-group-col");
  if (!sel) return;
  const cols = (state.columns || []).map((c) => (typeof c === "string" ? c : c.column));
  sel.innerHTML = '<option value="">— none (single-group / descriptive) —</option>';
  cols.forEach((col) => {
    const opt = document.createElement("option");
    opt.value = col;
    opt.textContent = col;
    // Pre-select from AI plan or previously set state
    const aiGroup = (plan && plan.group_col) || state.setupGroupCol || "";
    if (col === aiGroup) opt.selected = true;
    sel.appendChild(opt);
  });
  // Restore from state
  if (state.setupGroupCol && !sel.value) sel.value = state.setupGroupCol;
  sel.addEventListener("change", () => {
    state.setupGroupCol = sel.value || "";
  });
}

function bindScreenSetup() {
  const screen = document.getElementById("screen-setup");
  if (!screen) return;

  const statusEl    = document.getElementById("setup-describe-status");
  const adjustBox   = document.getElementById("setup-adjust-box");
  const descTa      = document.getElementById("setup-study-description");
  const corrTa      = document.getElementById("setup-correction-input");

  // ── Back ──────────────────────────────────────────────────────────────────
  screen.querySelector('[data-action="setup-back"]')?.addEventListener("click", () => showScreen("preview"));

  // ── Proceed ───────────────────────────────────────────────────────────────
  screen.querySelector('[data-action="setup-proceed"]')?.addEventListener("click", async () => {
    if (state.aiStudy) {
      state.studyType  = state.aiStudy.study_type  || state.studyType  || "comparison";
      state.outcomeCol = state.aiStudy.outcome_col || state.outcomeCol || null;
    }
    // Capture grouping var from the setup screen dropdown before leaving
    const grpSel = document.getElementById("setup-group-col");
    if (grpSel) state.setupGroupCol = grpSel.value || "";
    showScreen("3");
    await loadVariablesData();
  });

  // ── Re-analyse (free-text path) ───────────────────────────────────────────
  screen.querySelector('[data-action="setup-reanalyse"]')?.addEventListener("click", async () => {
    const desc = descTa?.value.trim() || "";
    if (!state.jobId) return;
    setStatus(statusEl, "Re-analysing…", "info");
    try {
      const res = await fetch("/api/stats/setup-study", {
        method: "POST",
        headers: externalAIHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          job_id: state.jobId,
          description: desc,
          outcome_hint: "",
          profile: selectedDomainProfile(),
          proposal_metadata: proposalMetadataPayload(),
        }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      const plan = await res.json();
      showAIProviderStatus(plan);
      if (!confirmAIStudyReplacement(plan, "AI suggested replacing the current study plan")) {
        setStatus(statusEl, "Cancelled. The current study plan was kept.", "info");
        return;
      }
      state.aiStudy = plan;
      renderSetupScreen(plan);
      setStatus(statusEl, "Plan updated.", "success");
      setTimeout(() => setStatus(statusEl, ""), 2500);
    } catch (err) {
      setStatus(statusEl, `Could not re-analyse: ${err.message}`, "error");
    }
  });

  // ── Proposal document upload path (dual-path intake) ─────────────────────
  const fileInput = document.getElementById("setup-proposal-file");
  if (fileInput) {
    fileInput.addEventListener("change", async () => {
      const file = fileInput.files?.[0];
      if (!file) return;
      setStatus(statusEl, "Reading document…", "info");
      try {
        const text = await file.text();
        // Truncate to 1500 chars to fit textarea maxlength
        const excerpt = text.replace(/\s+/g, " ").trim().slice(0, 1500);
        if (descTa) {
          descTa.value = excerpt;
          descTa.dispatchEvent(new Event("input"));
        }
        setStatus(statusEl, "Document loaded — click Re-analyse to update the plan.", "success");
        setTimeout(() => setStatus(statusEl, ""), 4000);
      } catch (err) {
        setStatus(statusEl, `Could not read file: ${err.message}`, "error");
      }
      // Reset so re-selecting same file fires change again
      fileInput.value = "";
    });
  }

  // ── Inline correction: open / cancel ─────────────────────────────────────
  screen.querySelector('[data-action="setup-adjust-open"]')?.addEventListener("click", () => {
    adjustBox?.classList.remove("is-hidden");
    corrTa?.focus();
  });

  screen.querySelector('[data-action="setup-adjust-cancel"]')?.addEventListener("click", () => {
    adjustBox?.classList.add("is-hidden");
    if (corrTa) corrTa.value = "";
  });

  // ── Inline correction: submit → /adjust-setup ─────────────────────────────
  screen.querySelector('[data-action="setup-adjust-submit"]')?.addEventListener("click", async () => {
    const correction = corrTa?.value.trim() || "";
    if (!correction || !state.jobId) return;
    const adjStatusEl = document.getElementById("setup-describe-status");
    setStatus(adjStatusEl, "Updating plan…", "info");
    try {
      const res = await fetch("/api/stats/adjust-setup", {
        method: "POST",
        headers: externalAIHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          job_id: state.jobId,
          description: descTa?.value.trim() || "",
          correction,
          outcome_hint: "",
        }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      const plan = await res.json();
      showAIProviderStatus(plan);
      if (!confirmAIStudyReplacement(plan, "AI suggested revising the current study plan")) {
        setStatus(adjStatusEl, "Cancelled. The current study plan was kept.", "info");
        return;
      }
      state.aiStudy = plan;
      renderSetupScreen(plan);
      adjustBox?.classList.add("is-hidden");
      if (corrTa) corrTa.value = "";
      setStatus(adjStatusEl, "Plan revised.", "success");
      setTimeout(() => setStatus(adjStatusEl, ""), 2500);
    } catch (err) {
      setStatus(adjStatusEl, `Could not adjust: ${err.message}`, "error");
    }
  });
}

function bindAiConfirm() {
  const screen = document.getElementById("screen-ai-confirm");
  if (!screen) return;

  // Live update buttons + detail panels when manual dropdowns change
  const typeSelect = document.getElementById("ai-study-type-select");
  if (typeSelect) typeSelect.addEventListener("change", () => {
    _updateAiConfirmButtons();
    _refreshAiDetailPanels();
  });
  const colSelectEl = document.getElementById("ai-outcome-col-select");
  if (colSelectEl) colSelectEl.addEventListener("change", () => {
    _refreshAiDetailPanels();
    _updateAiConfirmButtons();
  });

  // ── Back → preview ───────────────────────────────────────────────────
  const backBtn = screen.querySelector('[data-action="back-to-preview-from-ai"]');
  if (backBtn) backBtn.addEventListener("click", () => showScreen("preview"));

  // ── Main proceed button (visible; delegates to hidden internal buttons) ─
  const proceedBtn = document.getElementById("btn-ai-proceed");
  if (proceedBtn) {
    proceedBtn.addEventListener("click", () => {
      const studyType  = (state.aiStudy && state.aiStudy.study_type) || "correlation";
      const outCol     = (state.aiStudy && state.aiStudy.outcome_col) || "";
      const isPairwise = studyType === "correlation" || studyType === "association";
      // Sync hidden dropdowns with current aiStudy so the internal handlers read correctly
      const ts = document.getElementById("ai-study-type-select");
      const cs = document.getElementById("ai-outcome-col-select");
      if (ts) ts.value = studyType;
      if (cs && outCol) cs.value = outCol;
      if (isPairwise && outCol) {
        document.getElementById("btn-run-correlation")?.click();
      } else {
        screen.querySelector('[data-action="ai-confirm-skip-to-variables"]')?.click();
      }
    });
  }

  // ── Skip button (hidden; wired for internal use by proceedBtn) ───────
  const skipBtn = screen.querySelector('[data-action="ai-confirm-skip-to-variables"]');
  if (skipBtn) {
    skipBtn.addEventListener("click", async () => {
      const status    = document.getElementById("ai-confirm-status");
      const studyType = (document.getElementById("ai-study-type-select") || {}).value || "correlation";
      const outCol    = (document.getElementById("ai-outcome-col-select") || {}).value || null;
      setStatus(status, "Confirming…", "loading");
      try {
        await api("/confirm-study", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_id: state.jobId, study_type: studyType, outcome_col: outCol || null }),
        });
        state.outcomeCol = outCol || null;
        state.assignment = { outcome: outCol || null, group: null, covariates: [] };
        state.assignmentConfirmed = !!outCol;
        setStatus(status, "");
        showScreen("3");
        await loadVariablesData();
      } catch (err) {
        setStatus(status, `Error: ${err.message}`, "error");
      }
    });
  }

  // ── Run pairwise (hidden; wired for internal use by proceedBtn) ──────
  const corrBtn = document.getElementById("btn-run-correlation");
  if (corrBtn) {
    corrBtn.addEventListener("click", async () => {
      const status     = document.getElementById("ai-confirm-status");
      const ts         = document.getElementById("ai-study-type-select");
      const cs         = document.getElementById("ai-outcome-col-select");
      const studyType  = ts ? ts.value : "correlation";
      const outCol     = cs ? cs.value : "";
      if (!outCol) {
        setStatus(status, "Please select an outcome column first.", "error");
        return;
      }
      setStatus(status, "Confirming study setup…", "loading");
      if (proceedBtn) { proceedBtn.disabled = true; proceedBtn.textContent = "Running…"; }
      try {
        await api("/confirm-study", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_id: state.jobId, study_type: studyType, outcome_col: outCol }),
        });
        state.outcomeCol = outCol;
        state.assignment = { outcome: outCol, group: null, covariates: [] };
        state.assignmentConfirmed = true;
        setStatus(status, "Running pairwise analysis…", "loading");
        const result = await api("/run-correlation", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_id: state.jobId, outcome_col: outCol }),
        });
        state.corrResults = result.results;
        setStatus(status, "");
        renderCorrResults(outCol);
        showScreen("corr-results");
      } catch (err) {
        setStatus(status, `Analysis failed: ${err.message}`, "error");
      } finally {
        if (proceedBtn) { proceedBtn.disabled = false; proceedBtn.textContent = "✓ Looks correct — Run Analysis →"; }
      }
    });
  }

  // ── Chatbox toggle ────────────────────────────────────────────────────
  const adjustBtn = screen.querySelector('[data-action="ai-confirm-adjust"]');
  const adjustBox = document.getElementById("ai-adjust-box");
  if (adjustBtn && adjustBox) {
    adjustBtn.addEventListener("click", () => {
      adjustBox.classList.toggle("is-hidden");
      if (!adjustBox.classList.contains("is-hidden")) {
        document.getElementById("ai-adjust-input")?.focus();
      }
    });
  }

  // ── Chatbox cancel ────────────────────────────────────────────────────
  const adjustCancel = screen.querySelector('[data-action="ai-adjust-cancel"]');
  if (adjustCancel && adjustBox) {
    adjustCancel.addEventListener("click", () => adjustBox.classList.add("is-hidden"));
  }

  // ── Chatbox submit → POST /adjust-analysis ────────────────────────────
  const adjustSubmit = screen.querySelector('[data-action="ai-adjust-submit"]');
  if (adjustSubmit) {
    adjustSubmit.addEventListener("click", async () => {
      const input   = document.getElementById("ai-adjust-input");
      const status  = document.getElementById("ai-adjust-status");
      const message = (input ? input.value : "").trim();
      if (!message) { if (input) input.focus(); return; }
      setStatus(status, "Updating analysis plan…", "loading");
      adjustSubmit.disabled = true;
      try {
        const result = await api("/adjust-analysis", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            job_id: state.jobId,
            user_message: message,
            current_study_type: (state.aiStudy && state.aiStudy.study_type) || "correlation",
            current_outcome_col: (state.aiStudy && state.aiStudy.outcome_col) || null,
          }),
        });
        if (!confirmAIStudyReplacement(result, "AI suggested changing the analysis setup")) {
          setStatus(status, "Cancelled. The current analysis setup was kept.", "info");
          return;
        }
        state.aiStudy = result;
        if (input) input.value = "";
        if (adjustBox) adjustBox.classList.add("is-hidden");
        setStatus(status, "");
        renderAiConfirmScreen();
        setStatus(document.getElementById("ai-confirm-status"), "");
      } catch (err) {
        setStatus(status, `Could not update: ${err.message}`, "error");
      } finally {
        adjustSubmit.disabled = false;
      }
    });
  }

  // ── Manual override toggle ────────────────────────────────────────────
  const manualToggle = screen.querySelector('[data-action="ai-toggle-manual"]');
  const manualPanel  = document.getElementById("ai-manual-override");
  if (manualToggle && manualPanel) {
    manualToggle.addEventListener("click", () => manualPanel.classList.toggle("is-hidden"));
  }

  // ── Manual apply → update state + re-render ───────────────────────────
  const manualApply = screen.querySelector('[data-action="ai-manual-apply"]');
  if (manualApply) {
    manualApply.addEventListener("click", () => {
      const ts = document.getElementById("ai-study-type-select");
      const cs = document.getElementById("ai-outcome-col-select");
      const studyType = ts ? ts.value : "correlation";
      const outCol    = cs ? cs.value : "";
      state.aiStudy = Object.assign({}, state.aiStudy || {}, {
        study_type: studyType,
        outcome_col: outCol || null,
        reasoning: "Manually set by researcher.",
      });
      if (manualPanel) manualPanel.classList.add("is-hidden");
      renderAiConfirmScreen();
    });
  }

  // ── Re-analyse from plain-English study description ───────────────────
  // Researcher can type a description; clicking "Re-analyse" calls
  // /setup-study which feeds the description to the AI bridge and returns
  // an updated study type + outcome column.
  const reAnalyseBtn = document.getElementById("btn-re-analyse");
  if (reAnalyseBtn) {
    reAnalyseBtn.addEventListener("click", async () => {
      const descEl  = document.getElementById("ai-study-description");
      const descSts = document.getElementById("ai-describe-status");
      const desc    = (descEl ? descEl.value : "").trim();
      if (!desc) {
        if (descEl) descEl.focus();
        return;
      }
      setStatus(descSts, "Analysing your description…", "loading");
      reAnalyseBtn.disabled = true;
      try {
        const result = await api("/setup-study", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            job_id: state.jobId,
            description: desc,
            outcome_hint: "",
            profile: selectedDomainProfile(),
            proposal_metadata: proposalMetadataPayload(),
          }),
        });
        if (!confirmAIStudyReplacement(result, "AI suggested replacing the study setup")) {
          setStatus(descSts, "Cancelled. The current study setup was kept.", "info");
          return;
        }
        state.aiStudy = result;
        setStatus(descSts, "Updated.", "success");
        setTimeout(() => setStatus(descSts, ""), 2500);
        renderAiConfirmScreen();
      } catch (err) {
        setStatus(descSts, `Could not re-analyse: ${err.message}`, "error");
      } finally {
        reAnalyseBtn.disabled = false;
      }
    });
  }
}

/* ------------------------------------------------------------------ */
/*  Screen MISSING — Missing data decision cards + AI assistant        */
/* ------------------------------------------------------------------ */

function renderMissingScreen() {
  const container = document.getElementById("missing-decisions-container");
  if (!container) return;

  // Collect high-missing columns from state
  const missingCols = (state.classifications || []).filter(
    (c) => (c.missing_pct || c.missing_fraction * 100 || 0) > 5
  );

  if (!missingCols.length) {
    // No high-missing columns — skip this screen and go straight to normality
    showScreen("normality");
    loadNormality();
    return;
  }

  container.innerHTML = missingCols.map((c) => {
    const col = c.column || "?";
    const pct = ((c.missing_pct || (c.missing_fraction || 0) * 100) || 0).toFixed(1);
    const slug = col.replace(/[^a-z0-9]/gi, "_");
    const selected = (state.missingDecisions || {})[col] || "leave";
    return `<div class="se-missing-card" data-testid="missing-card-${slug}">
      <div class="se-missing-card-header">
        <strong>${escapeHtml(col)}</strong>
        <span class="se-missing-pct">${pct}% missing</span>
      </div>
      <div class="se-missing-actions">
        <label><input type="radio" name="missing-${slug}" value="leave" ${selected === "leave" ? "checked" : ""} data-missing-col="${escapeAttr(col)}"> Leave as-is</label>
        <label><input type="radio" name="missing-${slug}" value="impute_mean" ${selected === "impute_mean" ? "checked" : ""} data-missing-col="${escapeAttr(col)}"> Fill with mean</label>
        <label><input type="radio" name="missing-${slug}" value="impute_median" ${selected === "impute_median" ? "checked" : ""} data-missing-col="${escapeAttr(col)}"> Fill with median</label>
        <label><input type="radio" name="missing-${slug}" value="impute_mode" ${selected === "impute_mode" ? "checked" : ""} data-missing-col="${escapeAttr(col)}"> Fill with mode (most frequent)</label>
        <label><input type="radio" name="missing-${slug}" value="drop_rows" ${selected === "drop_rows" ? "checked" : ""} data-missing-col="${escapeAttr(col)}"> Drop rows with missing</label>
      </div>
    </div>`;
  }).join("");
}

function bindScreenMissing() {
  document.querySelectorAll("[data-missing-col]").forEach((radio) => {
    radio.addEventListener("change", () => {
      if (!radio.checked) return;
      state.missingDecisions = state.missingDecisions || {};
      state.missingDecisions[radio.dataset.missingCol] = radio.value;
    });
  });

  // ── Back to screen-4 (quality check) ───────────────────────────────────
  const backBtn = document.querySelector('[data-action="back-to-quality-from-missing"]');
  if (backBtn) backBtn.addEventListener("click", () => showScreen("4"));

  // ── Apply decisions and continue → normality ───────────────────────────
  const applyBtn = document.getElementById("btn-apply-missing");
  if (applyBtn) {
    applyBtn.addEventListener("click", async () => {
      const status = document.getElementById("missing-screen-status");

      // Collect all radio decisions
      const selectedDecisions = {};
      document.querySelectorAll("[data-missing-col]").forEach((radio) => {
        if (radio.checked) {
          selectedDecisions[radio.dataset.missingCol] = radio.value;
        }
      });
      const currentMissingCols = (state.classifications || []).filter(
        (c) => (c.missing_pct || c.missing_fraction * 100 || 0) > 5
      );
      const { decisions, unsupported } =
        _buildMissingDecisionPayload(currentMissingCols, selectedDecisions);
      if (unsupported.length) {
        setStatus(status, "Unsupported missing-data action. Choose a supported option.", "error");
        return;
      }

      setStatus(status, "Applying missing-data decisions…", "loading");
      applyBtn.disabled = true;
      try {
        await api("/handle-missing", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_id: state.jobId, decisions }),
        });
        state.missingDecisions = {};
        // Reclassify so downstream screens (normality, plan) see the updated
        // imputed/dropped columns rather than stale classification data.
        setStatus(status, "Reclassifying variables…", "loading");
        try {
          const reclassData = await refreshClassifications(
            [],
            { render: false, detectCategoryDupes: false }
          );
          if (reclassData && reclassData.classifications) {
            state.classifications = reclassData.classifications;
          } else {
            throw new Error("Classification response was incomplete.");
          }
        } catch (err) {
          throw new Error(`Could not reclassify after missing-data cleanup: ${err.message}`);
        }
        setStatus(status, "");
        showScreen("normality");
        loadNormality();
      } catch (err) {
        setStatus(status, `Could not apply: ${err.message}`, "error");
        applyBtn.disabled = false;
      }
    });
  }

  // ── AI assistant chatbox toggle ────────────────────────────────────────
  const toggleBtn = document.querySelector('[data-action="cb-missing-toggle"]');
  const panel     = document.getElementById("cb-missing-panel");
  if (toggleBtn && panel) {
    toggleBtn.addEventListener("click", () => {
      const isOpen = !panel.classList.contains("is-hidden");
      panel.classList.toggle("is-hidden");
      if (!isOpen) {
        // First open: show an opening message
        if (!state._missingChatOpened) {
          state._missingChatOpened = true;
          if (!state._missingThread) state._missingThread = [];
          state._missingThread.push({
            role: "ai",
            text: "I can explain missingness and Sigma's supported choices. I will not apply decisions; select an option for each variable and use Apply decisions.",
          });
          _renderMissingThread();
        }
        document.getElementById("cb-missing-input")?.focus();
      }
    });
  }

  // ── AI chatbox send button ─────────────────────────────────────────────
  const sendBtn = document.querySelector('[data-action="cb-missing-send"]');
  if (sendBtn) sendBtn.addEventListener("click", _sendMissingChatMessage);

  const missingInput = document.getElementById("cb-missing-input");
  if (missingInput) {
    missingInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        _sendMissingChatMessage();
      }
    });
  }
}

function _renderMissingThread() {
  const out = document.getElementById("cb-missing-thread");
  if (!out) return;
  const thread = state._missingThread || [];
  out.innerHTML = thread.map((m, i) => {
    if (m.role === "typing") {
      return `<div class="se-chat-msg is-typing"><span class="se-typing-dot"></span><span class="se-typing-dot"></span><span class="se-typing-dot"></span></div>`;
    }
    const cls = ({ user: "is-user", ai: "is-ai", clarify: "is-clarify" })[m.role] || "is-ai";
    return `<div class="se-chat-msg ${cls}" data-testid="cb-missing-msg-${i}">${escapeHtml(m.text)}</div>`;
  }).join("");
  out.scrollTop = out.scrollHeight;
}

async function _sendMissingChatMessage() {
  const input = document.getElementById("cb-missing-input");
  const msg   = (input ? input.value : "").trim();
  if (!msg) return;

  if (!state._missingThread) state._missingThread = [];
  state._missingThread.push({ role: "user", text: msg });
  state._missingThread.push({ role: "typing", text: "" });
  _renderMissingThread();
  if (input) { input.value = ""; input.disabled = true; }

  const clearTyping = () => {
    state._missingThread = (state._missingThread || []).filter((m) => m.role !== "typing");
  };
  try {
    const selectedMissingDecisions = state.missingDecisions || {};
    const res = await api("/ai-chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: state.jobId,
        kind: "missing",
        message: msg,
        selected_decisions: selectedMissingDecisions,
      }),
    });
    clearTyping();
    state._missingThread.push({ role: res.role || "ai", text: res.text || "" });
  } catch (err) {
    clearTyping();
    state._missingThread.push({ role: "clarify", text: `Error: ${err.message}` });
  } finally {
    if (input) input.disabled = false;
  }
  _renderMissingThread();
}

// Tiny helper — attribute-safe escape (no innerHTML risk in data-*)
function escapeAttr(s) {
  return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/* ------------------------------------------------------------------ */
/*  Screen CORR-RESULTS — Correlation analysis results renderer        */
/* ------------------------------------------------------------------ */

function renderCorrResults(outcomeCol) {
  const res = state.corrResults;
  if (!res) return;

  // Update the settings bar badges + dynamic heading
  _populateSettingsBar();

  const outcomeLabel = document.getElementById("corr-outcome-label");
  if (outcomeLabel) outcomeLabel.textContent = outcomeCol || res.outcome_col || "the outcome";

  const pairs = res.pairs || [];
  const successful = pairs.filter((p) => !p.test_result?.error);
  const nVarsEl = document.getElementById("corr-n-vars");
  if (nVarsEl) nVarsEl.textContent = `${successful.length} variables analysed.`;

  const body = document.getElementById("corr-results-body");
  if (!body) return;
  body.innerHTML = "";

  // Per-variable accordion sections
  successful.forEach((pair, idx) => {
    const predictor = pair.predictor || "";
    const tr        = pair.test_result || {};
    const p         = tr.p;
    const sig       = p !== undefined && p !== null && p < 0.05;
    const pDisplay  = p !== undefined && p !== null
      ? (p < 0.001 ? "< 0.001" : p.toFixed(3))
      : "—";

    const section = document.createElement("details");
    section.className = "se-disclose se-corr-section" + (sig ? " se-corr-sig" : "");
    section.open = (idx === 0);  // first one open by default

    const summary = document.createElement("summary");
    summary.innerHTML = `
      <span class="se-corr-pred">${escapeHtml(predictor)}</span>
      <span class="se-corr-test">${escapeHtml(tr.test_name || "")}</span>
      <span class="se-corr-p ${sig ? "se-corr-p-sig" : ""}">p = ${pDisplay}</span>
      ${sig ? '<span class="se-corr-sig-badge">★ p&lt;0.05</span>' : ""}
    `;
    section.appendChild(summary);

    const inner = document.createElement("div");
    inner.className = "se-corr-inner";

    // Table
    const td = pair.table_data || {};
    if (td.headers && td.headers.length && td.rows && td.rows.length) {
      const tableWrap = document.createElement("div");
      tableWrap.className = "se-table-wrap se-corr-table-wrap";
      const table = document.createElement("table");
      table.className = "se-table se-corr-table";
      const thead = document.createElement("thead");
      thead.innerHTML = `<tr>${td.headers.map((h) => `<th>${escapeHtml(String(h))}</th>`).join("")}</tr>`;
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      td.rows.forEach((row) => {
        const tr_el = document.createElement("tr");
        const isTotal = String(row[0]).trim().toLowerCase() === "total";
        if (isTotal) tr_el.className = "se-corr-total-row";
        row.forEach((cell) => {
          const td_el = document.createElement("td");
          td_el.textContent = String(cell);
          tr_el.appendChild(td_el);
        });
        tbody.appendChild(tr_el);
      });
      table.appendChild(tbody);
      tableWrap.appendChild(table);
      inner.appendChild(tableWrap);
    }

    // Graph
    if (pair.graph_uri) {
      const figDiv = document.createElement("div");
      figDiv.className = "se-corr-fig";
      const img = document.createElement("img");
      img.src = pair.graph_uri;
      img.alt = `${predictor} vs ${outcomeCol}`;
      img.className = "se-corr-img";
      figDiv.appendChild(img);
      inner.appendChild(figDiv);
    }

    // Interpretation
    if (pair.interpretation) {
      const interp = document.createElement("p");
      interp.className = "se-corr-interpretation";
      interp.textContent = pair.interpretation;
      inner.appendChild(interp);
    }

    section.appendChild(inner);
    body.appendChild(section);
  });

  // Failed pairs note
  const failed = pairs.filter((p) => p.test_result?.error);
  if (failed.length) {
    const note = document.createElement("p");
    note.className = "se-hint";
    note.textContent = `${failed.length} variable(s) could not be analysed: ${failed.map((p) => p.predictor).join(", ")}.`;
    body.appendChild(note);
  }

  // Summary table
  const summarySection = document.getElementById("corr-summary-section");
  const summaryTbody   = document.getElementById("corr-summary-tbody");
  const summaryRows = res.summary_table || [];
  if (summaryTbody && summaryRows.length) {
    summaryTbody.innerHTML = "";
    summaryRows.forEach((item) => {
      const tr_el = document.createElement("tr");
      if (item.significant) tr_el.className = "se-corr-sig-row";
      tr_el.innerHTML = `
        <td>${escapeHtml(item.predictor || "")}</td>
        <td>${escapeHtml(item.test || "")}</td>
        <td>${escapeHtml(item.stat || "—")}</td>
        <td class="${item.significant ? "se-corr-p-sig" : ""}">${escapeHtml(item.p || "—")}</td>
        <td>${item.significant ? "★ Yes" : "No"}</td>
      `;
      summaryTbody.appendChild(tr_el);
    });
    if (summarySection) summarySection.classList.remove("is-hidden");
  }

  // Glossary panel
  _renderGlossary(res);
}

/* ── Glossary of Statistical Terms ─────────────────────────────────────── */

function _renderGlossary(corrResults) {
  const container = document.getElementById("corr-glossary-body");
  if (!container) return;

  const pairs = (corrResults && corrResults.pairs) || [];
  const successful = pairs.filter((p) => !p.test_result?.error);
  const allTestNames = successful.map((p) =>
    ((p.test_result || {}).test_name || "").toLowerCase()
  );

  const hasMW      = allTestNames.some((t) => t.includes("mann"));
  const hasKW      = allTestNames.some((t) => t.includes("kruskal"));
  const hasChi     = allTestNames.some((t) => t.includes("chi"));
  const hasFisher  = allTestNames.some((t) => t.includes("fisher"));

  // Build ordered list of (term, definition)
  const entries = [];

  entries.push(["Null hypothesis (H₀)",
    "The default statistical proposition that there is no association or difference between the variables under investigation. A p-value below the pre-specified significance threshold provides evidence against the null hypothesis."]);

  entries.push(["p-value",
    "The probability of obtaining a test statistic as extreme as, or more extreme than, the value observed, assuming the null hypothesis is true. A smaller p-value indicates stronger evidence against the null hypothesis. In this study, p < 0.05 was adopted as the threshold for statistical significance."]);

  entries.push(["Statistical significance",
    "A result is deemed statistically significant when the computed p-value falls below the pre-defined α level (here, α = 0.05), indicating the observed finding is unlikely to have arisen by chance alone. Statistical significance does not, by itself, imply clinical or practical importance."]);

  entries.push(["Effect size",
    "A quantitative measure of the magnitude of an association or difference, independent of sample size. Effect sizes allow comparison of findings across studies and provide information beyond that conveyed by the p-value alone."]);

  if (hasMW || hasKW) {
    entries.push(["Median",
      "The middle value of a ranked dataset. Half of all observations fall above, half below. Preferred over the mean when data are skewed or ordinal."]);
    entries.push(["Interquartile range (IQR)",
      "The range between the 25th percentile (Q1) and the 75th percentile (Q3), capturing the spread of the central 50% of observations. Resistant to the influence of outliers."]);
  }

  if (hasMW) {
    entries.push(["Mann-Whitney U test",
      "A non-parametric test comparing the distributions of a continuous variable between two independent groups. Does not assume normality. Non-parametric counterpart of the independent-samples t-test."]);
    entries.push(["Rank-biserial correlation (rᵦ)",
      "Effect size for the Mann-Whitney U test, ranging from −1 to +1. Represents the proportion of concordant minus discordant pairs between groups. Thresholds: small ≥ 0.10, medium ≥ 0.30, large ≥ 0.50 (Cohen, 1988)."]);
  }

  if (hasKW) {
    entries.push(["Kruskal-Wallis H test",
      "A non-parametric test comparing distributions of a continuous variable across three or more independent groups. Extension of the Mann-Whitney U test. A significant result means at least one group differs — post-hoc tests are needed to identify which."]);
  }

  if (hasChi || hasFisher) {
    entries.push(["Contingency table",
      "A cross-tabulation showing the joint frequency distribution of two categorical variables. Each cell contains the count of observations satisfying both the row and column category."]);
  }

  if (hasChi) {
    entries.push(["Chi-square test of independence (χ²)",
      "Tests whether two categorical variables are associated by comparing observed cell frequencies with those expected under independence. A significant result indicates the variables are not independent."]);
  }

  if (hasFisher) {
    entries.push(["Fisher's exact test",
      "Alternative to the chi-square test used when any expected cell count falls below 5. Calculates exact probabilities rather than relying on a chi-square approximation, making it more accurate for small samples."]);
  }

  if (hasChi || hasFisher) {
    entries.push(["Cramér's V",
      "Effect size for chi-square / Fisher's exact tests, ranging from 0 to 1. Thresholds: negligible < 0.10, weak 0.10–0.29, moderate 0.30–0.49, strong ≥ 0.50 (Cohen, 1988)."]);
  }

  // Render
  container.innerHTML = "";
  const dl = document.createElement("dl");
  dl.className = "se-glossary-list";
  entries.forEach(([term, defn]) => {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = defn;
    dl.appendChild(dt);
    dl.appendChild(dd);
  });
  container.appendChild(dl);

  // Show the panel (was hidden until results loaded)
  const panel = document.getElementById("corr-glossary-panel");
  if (panel) panel.style.display = "";
}

/* ── Analysis Settings bar helpers ─────────────────────────────────────── */

function _populateSettingsBar() {
  const ai = state.aiStudy || {};
  const studyType = ai.study_type || "correlation";
  const outCol    = ai.outcome_col || "";

  const badge = document.getElementById("results-study-type-badge");
  if (badge) badge.textContent = _STUDY_TYPE_LABELS[studyType] || studyType;

  const outBadge = document.getElementById("results-outcome-badge");
  if (outBadge) outBadge.textContent = outCol || "—";

  const heading = document.getElementById("corr-results-heading");
  if (heading) {
    const titles = {
      association: "Association Analysis Results",
      correlation: "Correlation Analysis Results",
      comparison:  "Comparison Analysis Results",
      regression:  "Regression / Prediction Results",
      diagnostic:  "Diagnostic Analysis Results",
      survival:    "Survival Analysis Results",
      reliability: "Reliability / Agreement Results",
      descriptive: "Descriptive Analysis Results",
    };
    heading.textContent = titles[studyType] || "Analysis Results";
  }

  const settingsOutcomeSelect = document.getElementById("settings-outcome-select");
  if (settingsOutcomeSelect) {
    settingsOutcomeSelect.innerHTML = '<option value="">— select —</option>';
    const cols = state.columns.map((c) => (typeof c === "string" ? c : c.column));
    cols.forEach((col) => {
      const opt = document.createElement("option");
      opt.value = col;
      opt.textContent = col;
      if (col === outCol) opt.selected = true;
      settingsOutcomeSelect.appendChild(opt);
    });
  }

  const settingsTypeSelect = document.getElementById("settings-type-select");
  if (settingsTypeSelect) settingsTypeSelect.value = studyType;
}

async function _rerunFromSettings(studyType, outCol) {
  const status = document.getElementById("settings-status");
  setStatus(status, "Re-confirming study setup…", "loading");
  try {
    await api("/confirm-study", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: state.jobId, study_type: studyType, outcome_col: outCol }),
    });
    setStatus(status, "Re-running analysis…", "loading");
    const result = await api("/run-correlation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: state.jobId, outcome_col: outCol }),
    });
    state.corrResults = result.results;
    document.getElementById("settings-panel")?.classList.add("is-hidden");
    document.getElementById("settings-manual")?.classList.add("is-hidden");
    setStatus(status, "");
    renderCorrResults(outCol);
  } catch (err) {
    setStatus(status, `Re-run failed: ${err.message}`, "error");
  }
}

function bindSettingsPanel() {
  const screen = document.getElementById("screen-corr-results");
  if (!screen) return;

  const panel = document.getElementById("settings-panel");

  // ── Toggle panel ─────────────────────────────────────────────────────
  const toggleBtn = screen.querySelector('[data-action="toggle-settings-panel"]');
  if (toggleBtn && panel) {
    toggleBtn.addEventListener("click", () => {
      panel.classList.toggle("is-hidden");
      if (!panel.classList.contains("is-hidden")) {
        document.getElementById("settings-adjust-input")?.focus();
      }
    });
  }

  // ── Cancel ────────────────────────────────────────────────────────────
  const cancelBtn = screen.querySelector('[data-action="settings-cancel"]');
  if (cancelBtn && panel) {
    cancelBtn.addEventListener("click", () => panel.classList.add("is-hidden"));
  }

  // ── AI re-run (open-ended text → /adjust-analysis → /run-correlation) ─
  const rerunBtn = screen.querySelector('[data-action="settings-rerun"]');
  if (rerunBtn) {
    rerunBtn.addEventListener("click", async () => {
      const input   = document.getElementById("settings-adjust-input");
      const status  = document.getElementById("settings-status");
      const message = (input ? input.value : "").trim();
      if (!message) { if (input) input.focus(); return; }
      setStatus(status, "Asking AI to interpret your correction…", "loading");
      rerunBtn.disabled = true;
      try {
        const result = await api("/adjust-analysis", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            job_id: state.jobId,
            user_message: message,
            current_study_type: (state.aiStudy && state.aiStudy.study_type) || "correlation",
            current_outcome_col: (state.aiStudy && state.aiStudy.outcome_col) || null,
          }),
        });
        if (input) input.value = "";
        const outCol = result.outcome_col || "";
        if (!outCol) {
          setStatus(status, "Outcome column not detected — please use 'Override manually' to set it.", "error");
          return;
        }
        if (!confirmAIStudyReplacement(result, "AI suggested changing setup and re-running results")) {
          setStatus(status, "Cancelled. Setup and results were not changed.", "info");
          return;
        }
        state.aiStudy = result;
        _populateSettingsBar();
        await _rerunFromSettings(result.study_type, outCol);
      } catch (err) {
        setStatus(status, `Could not update: ${err.message}`, "error");
      } finally {
        rerunBtn.disabled = false;
      }
    });
  }

  // ── Manual toggle ─────────────────────────────────────────────────────
  const manualToggle = screen.querySelector('[data-action="settings-toggle-manual"]');
  const manualPanel  = document.getElementById("settings-manual");
  if (manualToggle && manualPanel) {
    manualToggle.addEventListener("click", () => manualPanel.classList.toggle("is-hidden"));
  }

  // ── Manual apply → re-run immediately ────────────────────────────────
  const manualApply = screen.querySelector('[data-action="settings-manual-apply"]');
  if (manualApply) {
    manualApply.addEventListener("click", async () => {
      const ts = document.getElementById("settings-type-select");
      const cs = document.getElementById("settings-outcome-select");
      const studyType = ts ? ts.value : "correlation";
      const outCol    = cs ? cs.value : "";
      if (!outCol) {
        setStatus(document.getElementById("settings-status"), "Please select an outcome column.", "error");
        return;
      }
      state.aiStudy = Object.assign({}, state.aiStudy || {}, {
        study_type: studyType,
        outcome_col: outCol,
        reasoning: "Manually adjusted from results screen.",
      });
      _populateSettingsBar();
      await _rerunFromSettings(studyType, outCol);
    });
  }
}

/* ─────────────────────────────────────────────────────────────────────── */

/* ------------------------------------------------------------------ */
/*  Knowledge Assistant — serialise Sigma results for locked_context  */
/* ------------------------------------------------------------------ */

/**
 * Build a locked_context object from the current analysis state.
 * Works for both the correlation path (state.corrResults) and the
 * classic results path (state.results).
 */
function serializeAnalysisContext() {
  const ctx = {};

  /* Study type + outcome from AI study metadata */
  const ai = state.aiStudy || {};
  if (ai.study_type) ctx.study_type = ai.study_type;
  if (ai.outcome_col) ctx.outcome = ai.outcome_col;

  /* ── Correlation / association / comparison path ── */
  const corr = state.corrResults;
  if (corr) {
    if (!ctx.outcome && corr.outcome_col) ctx.outcome = corr.outcome_col;

    const pairs = (corr.pairs || []).filter((p) => !p.test_result?.error);
    ctx.tests = pairs.map((pair) => {
      const tr = pair.test_result || {};
      const pv = tr.p !== undefined ? tr.p : tr.p_value;
      const statRow = (tr.rows || []).find((r) =>
        /statistic|chi|pearson|spearman|U stat|t stat|z stat|W stat/i.test(r.label || "")
      );
      const esRow = (tr.rows || []).find((r) =>
        /effect|cramer|phi|odds|risk|r\s*=/i.test(r.label || "")
      );
      return {
        variable:    pair.predictor || "",
        test_name:   tr.test_name  || "",
        statistic:   statRow ? statRow.value : null,
        p_value:     pv !== undefined ? pv : null,
        effect_size: esRow  ? esRow.value  : null,
        significant: pv !== undefined && pv !== null ? pv < 0.05 : null,
        interpretation: pair.interpretation || "",
      };
    });

    /* Outcome n (from summary or first pair) */
    const firstPair = pairs[0];
    if (firstPair && firstPair.test_result && firstPair.test_result.n) {
      ctx.n = firstPair.test_result.n;
    }
  }

  /* ── Classic results path ── */
  const res = state.results;
  if (res && !corr) {
    ctx.tests = (res.tests || []).map((t) => {
      const pRow = (t.rows || []).find((r) => /p.value|p =/i.test(r.label || ""));
      const sRow = (t.rows || []).find((r) => /statistic/i.test(r.label || ""));
      const eRow = (t.rows || []).find((r) => /effect|cohen|eta|r\s*=/i.test(r.label || ""));
      const pv   = pRow ? parseFloat(pRow.value) : null;
      return {
        variable:    t.title    || t.id || "",
        test_name:   t.test_name|| "",
        statistic:   sRow ? sRow.value : null,
        p_value:     isFinite(pv) ? pv : null,
        effect_size: eRow ? eRow.value : null,
        significant: isFinite(pv) ? pv < 0.05 : null,
        interpretation: t.narrative || "",
      };
    });
    if (res.results_md) ctx.narrative = res.results_md.slice(0, 600);
  }

  return ctx;
}

/**
 * Compose a human-readable prefill question from the analysis context,
 * then open the RA drawer.
 */
function _setRADrawerStatus(triggerButton, message = "") {
  if (!triggerButton) return;
  let status = triggerButton.parentElement?.querySelector(
    `[data-ra-status-for="${triggerButton.id}"]`
  );
  if (!status && message) {
    status = document.createElement("div");
    status.className = "se-status se-status-inline";
    status.dataset.raStatusFor = triggerButton.id;
    status.setAttribute("role", "alert");
    status.setAttribute("aria-live", "assertive");
    triggerButton.insertAdjacentElement("afterend", status);
  }
  setStatus(status, message, message ? "error" : "loading");
}

function openRADrawer(triggerButton = null) {
  const unavailableMessage =
    "Research Assistant is unavailable. Please refresh the page or check server/static assets.";
  if (!window.RADrawer || typeof window.RADrawer.open !== "function") {
    _setRADrawerStatus(triggerButton, unavailableMessage);
    return false;
  }

  const ctx = serializeAnalysisContext();

  /* Build a pre-filled question from the most significant result */
  let prefillQ = "";
  const sigTests = (ctx.tests || []).filter((t) => t.significant);
  const outcome  = ctx.outcome || "the outcome";

  if (sigTests.length > 0) {
    const t = sigTests[0];
    const pLabel = t.p_value !== null
      ? (t.p_value < 0.001 ? "p < 0.001" : `p = ${t.p_value.toFixed(3)}`)
      : "";
    prefillQ =
      `My ${ctx.study_type || "analysis"} found that ${t.variable} was significantly ` +
      `associated with ${outcome}` +
      (t.test_name ? ` (${t.test_name}` : "") +
      (pLabel ? `, ${pLabel}` : "") +
      (t.test_name ? ")" : "") +
      `. What does the published literature say about this association, ` +
      `and is my result clinically meaningful?`;
  } else if ((ctx.tests || []).length > 0) {
    const varNames = ctx.tests.slice(0, 3).map((t) => t.variable).filter(Boolean).join(", ");
    prefillQ =
      `My ${ctx.study_type || "analysis"} examined the association between ` +
      `${varNames || "these variables"} and ${outcome}. ` +
      `None were statistically significant. What does the literature show, ` +
      `and could my sample size be the limiting factor?`;
  }

  try {
    window.RADrawer.open(ctx, prefillQ || null);
    if (!document.querySelector(".ra-drawer.is-open")) {
      throw new Error("Research Assistant drawer did not initialize.");
    }
    _setRADrawerStatus(triggerButton);
    return true;
  } catch (err) {
    console.error("Research Assistant drawer failed to open.", err);
    _setRADrawerStatus(triggerButton, unavailableMessage);
    return false;
  }
}

/* ------------------------------------------------------------------ */
/*  Screen CORR-RESULTS — button binding                               */
/* ------------------------------------------------------------------ */

function bindCorrResults() {
  const screen = document.getElementById("screen-corr-results");
  if (!screen) return;

  bindSettingsPanel();

  /* ── Research Assistant trigger ── */
  const raBtn = document.getElementById("btn-ra-open-corr");
  if (raBtn) {
    raBtn.addEventListener("click", () => openRADrawer(raBtn));
  }

  const backBtn = screen.querySelector('[data-action="back-to-ai-confirm"]');
  if (backBtn) backBtn.addEventListener("click", () => showScreen("ai-confirm"));

  const exportBtn = document.getElementById("btn-export-corr-chapter");
  if (exportBtn) {
    exportBtn.addEventListener("click", async () => {
      const status = document.getElementById("corr-export-status");
      setStatus(status, "Building Word document…", "loading");
      exportBtn.disabled = true;
      try {
        const res = await fetch(`${API_BASE}/export-correlation/${state.jobId}`);
        if (!res.ok) {
          const txt = await res.text();
          throw new Error(txt || `HTTP ${res.status}`);
        }
        const blob = await res.blob();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "medras_correlation_chapter.docx";
        document.body.appendChild(a);
        a.click();
        a.remove();
        setStatus(status, "Downloaded successfully.", "success");
      } catch (err) {
        setStatus(status, `Download failed: ${err.message}`, "error");
      } finally {
        exportBtn.disabled = false;
      }
    });
  }
}

/* ------------------------------------------------------------------ */
/*  Step 8 — Export                                                    */
/* ------------------------------------------------------------------ */

function bindExport() {
  const screen = document.getElementById("screen-export");
  if (!screen) return;
  screen.querySelectorAll('[data-action="download"]').forEach((btn) => {
    btn.addEventListener("click", () => downloadExport(btn.dataset.format, btn));
  });
  // Chapter V thesis-format export buttons
  screen.querySelectorAll('[data-action="download-chapter-v"]').forEach((btn) => {
    btn.addEventListener("click", () => downloadChapterV(btn.dataset.format, btn));
  });
  const back = screen.querySelector('[data-action="back-to-results"]');
  if (back) back.addEventListener("click", () => showScreen("results"));
  const restartBtn = screen.querySelector('[data-action="restart"]');
  if (restartBtn) restartBtn.addEventListener("click", restart);
  bindCorrectionSystem();
  updateExportAvailability();
}

function updateExportAvailability(message = "") {
  const ready = Boolean(state.jobId && state.results && state.resultId);
  document.querySelectorAll('#screen-export [data-action="download"], #screen-export [data-action="download-chapter-v"]')
    .forEach((button) => { button.disabled = !ready; });
  if (!ready && message) {
    setStatus(document.getElementById("export-status"), message, "error");
    setStatus(document.getElementById("chapter-v-status"), message, "error");
  }
  return ready;
}

async function exportErrorMessage(res) {
  const text = await res.text();
  try {
    const payload = JSON.parse(text);
    return payload.detail || payload.message || text || `HTTP ${res.status}`;
  } catch (_) {
    return text || res.statusText || `HTTP ${res.status}`;
  }
}

function downloadBlob(blob, filename) {
  if (!blob || !blob.size) throw new Error("The server returned an empty export file.");
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function downloadChapterV(fmt, button) {
  const statusEl = document.getElementById("chapter-v-status");
  if (!updateExportAvailability("Export state is stale or missing. Run the latest analysis before exporting.")) {
    return;
  }
  if (button) button.disabled = true;
  setStatus(statusEl, "Generating Chapter V…", "loading");
  const fmtKey = fmt === "pdf" ? "chapter_v_pdf" : "chapter_v_word";
  try {
    const resultId = encodeURIComponent(state.resultId);
    const res = await fetch(`${API_BASE}/export/${state.jobId}/${fmtKey}?result_id=${resultId}`);
    if (!res.ok) {
      throw new Error(await exportErrorMessage(res));
    }
    const blob = await res.blob();
    const ext = fmt === "pdf" ? "pdf" : "docx";
    downloadBlob(blob, `chapter_v_results.${ext}`);
    setStatus(statusEl, "Downloaded!", "success");
    setTimeout(() => setStatus(statusEl, ""), 3000);
  } catch (err) {
    setStatus(statusEl, `Download failed: ${err.message}`, "error");
  } finally {
    if (button) button.disabled = false;
  }
}

/* ------------------------------------------------------------------ */
/*  Task 2 — Plain-English document correction system                   */
/* ------------------------------------------------------------------ */

function bindCorrectionSystem() {
  const applyBtn = document.getElementById("btn-apply-corrections");
  if (!applyBtn) return;
  applyBtn.addEventListener("click", async () => {
    const input = document.getElementById("correction-input");
    const instructions = (input && input.value.trim()) || "";
    if (!instructions) {
      setStatus(document.getElementById("correction-status"), "Please enter correction instructions first.", "error");
      return;
    }
    if (!state.jobId) {
      setStatus(document.getElementById("correction-status"), "No active analysis session — run an analysis first.", "error");
      return;
    }
    await applyCorrectionInstructions(instructions);
  });
}

async function applyCorrectionInstructions(instructions) {
  const statusEl = document.getElementById("correction-status");
  const resultsEl = document.getElementById("correction-results");
  const applyBtn = document.getElementById("btn-apply-corrections");
  if (applyBtn) applyBtn.disabled = true;
  setStatus(statusEl, "Parsing corrections with AI\u2026", "loading");
  if (resultsEl) resultsEl.style.display = "none";

  try {
    const data = await api("/apply-corrections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: state.jobId, instructions }),
    });

    state.correctionVersions = state.correctionVersions || [];
    state.correctionVersions.push({
      version: data.version,
      timestamp: new Date().toLocaleTimeString(),
      instructions: instructions.slice(0, 80) + (instructions.length > 80 ? "\u2026" : ""),
      applied: data.applied || [],
      skipped: data.skipped || [],
    });

    const appliedEl = document.getElementById("correction-applied");
    const skippedEl = document.getElementById("correction-skipped");
    if (appliedEl) {
      appliedEl.innerHTML = (data.applied && data.applied.length)
        ? "<strong>\u2713 Applied:</strong><ul style='margin:0.25rem 0 0 1rem;padding:0;list-style:disc;'>"
            + data.applied.map((a) => `<li>${escapeHtml(a)}</li>`).join("")
            + "</ul>"
        : "<em>No changes could be applied.</em>";
    }
    if (skippedEl) {
      skippedEl.innerHTML = (data.skipped && data.skipped.length)
        ? "<strong>\u26a0 Could not apply:</strong><ul style='margin:0.25rem 0 0 1rem;padding:0;list-style:disc;'>"
            + data.skipped.map((s) => `<li>${escapeHtml(s)}</li>`).join("")
            + "</ul>"
        : "";
    }
    if (resultsEl) resultsEl.style.display = "block";

    const totalApplied = (data.applied || []).length;
    const totalSkipped = (data.skipped || []).length;
    setStatus(statusEl,
      `V${data.version} applied \u2014 ${totalApplied} change(s), ${totalSkipped} skipped. Re-download to get the corrected document.`,
      "success");

    renderCorrectionHistory();
    const input = document.getElementById("correction-input");
    if (input) input.value = "";
  } catch (err) {
    setStatus(statusEl, `Correction failed: ${err.message}`, "error");
  } finally {
    if (applyBtn) applyBtn.disabled = false;
  }
}

async function renderCorrectionHistory() {
  const histEl = document.getElementById("correction-history");
  const listEl = document.getElementById("correction-history-list");
  if (!histEl || !listEl || !state.jobId) return;

  let versions = state.correctionVersions || [];
  if (!versions.length) {
    try {
      const data = await api(`/correction-versions/${state.jobId}`);
      versions = (data.versions || []).map((v) => ({
        version: v.version,
        timestamp: v.timestamp ? v.timestamp.replace("T", " ").replace("Z", " UTC") : "",
        instructions: (v.instructions || "").slice(0, 80),
        applied: v.applied || [],
        skipped: v.skipped || [],
      }));
      state.correctionVersions = versions;
    } catch (_) { return; }
  }

  if (!versions.length) { histEl.style.display = "none"; return; }

  listEl.innerHTML = versions.slice().reverse().map((v) => `
    <div class="se-correction-history-item">
      <div class="se-correction-history-head">
        <span class="se-correction-version">V${v.version}</span>
        <span class="se-correction-time">${escapeHtml(v.timestamp)}</span>
        <button type="button" class="btn btn-tertiary se-btn-small"
          onclick="restoreVersion(${v.version})">Restore</button>
      </div>
      <div class="se-correction-instructions">${escapeHtml(v.instructions)}</div>
      <div class="se-correction-count se-correction-count-applied">${v.applied.length} applied</div>
      ${v.skipped.length ? `<div class="se-correction-count se-correction-count-skipped">${v.skipped.length} skipped</div>` : ""}
    </div>
  `).join("");
  histEl.style.display = "block";
}

async function restoreVersion(versionNum) {
  if (!state.jobId) return;
  const statusEl = document.getElementById("correction-status");
  setStatus(statusEl, `Restoring V${versionNum}\u2026`, "loading");
  try {
    await api("/restore-version", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: state.jobId, version: versionNum }),
    });
    setStatus(statusEl,
      `Restored to V${versionNum}. Re-download to get that version of the document.`,
      "success");
  } catch (err) {
    setStatus(statusEl, `Restore failed: ${err.message}`, "error");
  }
}

async function downloadExport(format, button) {
  const status = document.getElementById("export-status");
  if (!updateExportAvailability("Export state is stale or missing. Run the latest analysis before exporting.")) {
    return;
  }
  if (button) button.disabled = true;
  setStatus(status, `Building ${format.toUpperCase()} file…`, "loading");
  try {
    const resultId = encodeURIComponent(state.resultId);
    const url = `${API_BASE}/export/${state.jobId}/${format}?result_id=${resultId}`;
    const res = await fetch(url);
    if (!res.ok) {
      throw new Error(await exportErrorMessage(res));
    }
    const blob = await res.blob();
    const ext = format === "word" ? "docx" : (format === "excel" ? "xlsx" : "pdf");
    downloadBlob(blob, `medras_results.${ext}`);
    setStatus(status, `${format.toUpperCase()} downloaded.`, "success");
  } catch (err) {
    setStatus(status, `Download failed: ${err.message}`, "error");
  } finally {
    if (button) button.disabled = false;
  }
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
  // Reset preview-routing flags + custom-wizard answers so a fresh upload
  // after a prior practice run doesn't inherit Regenerate / Download Excel
  // buttons or stale Q1-Q3 selections.
  state.dataSource = null;
  state.customWizard = { activeQ: 1, variables: [], n: 60, effect: "", instructions: "" };
  // restart() doesn't go through ingestDataset, so hide the practice banner
  // here too — otherwise it persists across "← Change file" → upload flows.
  try {
    const banner = document.getElementById("practice-banner");
    if (banner) banner.classList.add("is-hidden");
  } catch (_) { /* banner is purely cosmetic */ }
  state.issues = [];
  state.autoCoding = [];
  state.assistantThread = [];
  state.recodingChoices = {};
  state.missingDecisions = {};
  state.categoryDupeResults = null;
  state.rejectedMergeSuggestions = new Set();
  state.assignment = null;
  state.normality = null;
  state.plan = null;
  state.confirmedTests = null;
  state.confirmedGraphs = null;
  state.results = null;
  state.resultId = null;
  state.analysisVersion = null;
  state.aiStudy = null;
  state.corrResults = null;
  state.correctionVersions = [];
  state.chatThreads = { normality: [], plan: [], results: [] };
  state.chatOpened  = { normality: false, plan: false, results: false };
  ["normality", "plan", "results"].forEach((k) => {
    const t = document.getElementById(`cb-${k}-thread`);
    if (t) t.innerHTML = "";
    const c = document.getElementById(`cb-${k}-chips`);
    if (c) c.innerHTML = "";
  });
  setStatus($("#upload-status"), "");
  setStatus($("#practice-status"), "");
  setStatus($("#quality-status"), "");
  // Wipe the saved session too — Start Over should not silently bring
  // the previous dataset back on the next refresh.
  clearSavedSession();
  showScreen("1");
}

/* ------------------------------------------------------------------ */
/*  Pass-badge tooltip (Fix 9)                                          */
/* ------------------------------------------------------------------ */

function bindPassBadgeTooltip() {
  // The (?) icon next to "Pass 1 of 2 — data preparation" supports both
  // hover (CSS) and click (here, for keyboard/touch users). Clicking
  // toggles the tooltip; clicking outside closes it.
  const badge = document.querySelector('[data-testid="badge-pass"]');
  if (!badge) return;
  const help = badge.querySelector(".se-pass-help");
  if (!help) return;
  help.addEventListener("click", (e) => {
    e.stopPropagation();
    badge.classList.toggle("is-open");
  });
  document.addEventListener("click", (e) => {
    if (!badge.contains(e.target)) badge.classList.remove("is-open");
  });
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
    bindCustomWizard();
    bindPreview();
    bindScreenSetup();
    bindAiConfirm();
    bindCorrResults();
    bindScreen3();
    bindScreen4();
    bindScreenMissing();
    bindSoon();
    bindNormality();
    bindPlan();
    bindResults();
    bindExport();
    bindChatboxes();
    bindPassBadgeTooltip();
    bindStepNavBack();
    showScreen("1");
    // If ?fresh=1 is in the URL, wipe any saved session immediately and
    // redirect to the clean URL so a refresh doesn't re-trigger the wipe.
    if (new URLSearchParams(window.location.search).get("fresh") === "1") {
      clearSavedSession();
      window.history.replaceState({}, "", window.location.pathname);
      // Stay on screen 1 — no resume modal needed.
    } else {
      // Offer to resume any in-progress session saved in the last 24h.
      // We do this AFTER showScreen("1") so the resume modal sits above
      // the (visible) entry chooser rather than racing against a hidden
      // screen flip. If the saved dataset can't be re-fetched the resume
      // handler quietly falls back to a fresh start.
      const saved = loadSavedSession();
      if (saved) renderResumeBanner(saved);
    }

    // If the user came here from the Practice Data Wizard with
    // ?practice=<job_id>, hydrate the dataset and skip past the entry chooser.
    const practiceId = new URLSearchParams(window.location.search).get("practice");
    if (practiceId) {
      api(`/dataset/${practiceId}`)
        .then((data) => {
          state.entryChoice = "practice";
          // Deep-link from the standalone practice wizard ⇒ treat as a
          // wizard-built dataset so the preview surfaces the same extras
          // (Step-3 note, Download Excel, Regenerate) as the inline path.
          state.dataSource = "custom";
          ingestDataset(data);
          showScreen("preview");
          renderPreview();
        })
        .catch((err) => {
          console.warn("Could not load practice dataset:", err.message);
        });
    }
    // If the user came here from the home-screen "Open and continue" button,
    // restore their session and jump straight to the Export screen.
    const restoreId = new URLSearchParams(window.location.search).get("restore");
    if (restoreId) {
      api(`/restore/${restoreId}`)
        .then((data) => {
          state.jobId = data.job_id;
          // Mark as having results so the export screen behaves correctly.
          state.results = state.results || { _restored: true };
          showScreen("export");
        })
        .catch((_err) => {
          setStatus(
            $("#upload-status"),
            "This analysis has expired after 15 days. Please upload your data again to run a new analysis. " +
            "Your previous Word document is still available if you saved it to your computer.",
            "error"
          );
        });
    }

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

  // Apply quality → screen normality (legacy "Assign" step is gone in the 8-step model)
  click('[data-testid="button-apply-quality"]');
  log("waiting for screen-normality…");
  for (let i = 0; i < 60; i++) {
    if (!document.getElementById("screen-normality").classList.contains("is-hidden")) break;
    await wait(100);
  }
  const normVisible = !document.getElementById("screen-normality").classList.contains("is-hidden");
  log(`screen-normality visible: ${normVisible}`);
  if (!normVisible) throw new Error("screen-normality never became visible");

  log("\n✅ SELFTEST PASSED");
  banner.style.background = "#1f5d36";
}
