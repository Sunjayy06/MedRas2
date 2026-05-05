/* Reduce-results page — streams the 3-stage rewrite pipeline progress
 * via NDJSON, renders a section-by-section progress bar, then shows
 * colour-coded cards with side-by-side original / rewritten text and
 * a download button that POSTs back to /api/plagiarism/export-docx.
 *
 * Input is read from sessionStorage key "pm:reduceInput", set by
 * checker.js when the user clicks "Reduce plagiarism".
 */
(function () {
  "use strict";

  const INPUT_KEY = "pm:reduceInput";
  const RESULT_KEY = "pm:reduceResult";

  const $ = (s) => document.querySelector(s);

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function escapeRegex(s) {
    return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  // Build a single case-insensitive regex matching any protected term, with
  // longest-first ordering so e.g. "p < 0.001" wins over "0.001". Returns
  // ``null`` when no terms are supplied. The regex is recreated once per
  // page render rather than once per card.
  let _termRegex = null;
  function buildTermRegex(terms) {
    if (!terms || !terms.length) return null;
    const cleaned = Array.from(new Set(
      terms.map((t) => String(t || "").trim()).filter(Boolean)
    ));
    if (!cleaned.length) return null;
    cleaned.sort((a, b) => b.length - a.length);
    const pat = cleaned.map(escapeRegex).join("|");
    try {
      return new RegExp("(" + pat + ")", "g");
    } catch (_) {
      return null;
    }
  }

  // Escape ``text`` and wrap any matches of ``rx`` in <mark>. Done in a
  // single pass so HTML in the protected terms (e.g. "<5%") is escaped
  // BEFORE being injected — the input is treated as plain text throughout.
  function highlightTerms(text, rx) {
    const safe = String(text == null ? "" : text);
    if (!rx) return escapeHtml(safe);
    let out = "";
    let lastIdx = 0;
    rx.lastIndex = 0;
    let m;
    while ((m = rx.exec(safe)) !== null) {
      // Defensive against zero-width matches.
      if (m.index === rx.lastIndex) { rx.lastIndex++; continue; }
      out += escapeHtml(safe.slice(lastIdx, m.index));
      out += '<mark class="pm-protected-term">' + escapeHtml(m[0]) + '</mark>';
      lastIdx = rx.lastIndex;
    }
    out += escapeHtml(safe.slice(lastIdx));
    return out || '<span class="pm-compare-empty">—</span>';
  }

  // ---------- DOM refs ----------
  const empty = $("#pm-empty");
  const progressCard = $("#pm-progress-card");
  const errorCard = $("#pm-error-card");
  const resultsBlock = $("#pm-results");
  const progressFill = $("#pm-progress-fill");
  const progressBar = $("#pm-progress-bar");
  const progressPct = $("#pm-progress-pct");
  const progressCurrent = $("#pm-progress-current");
  const progressList = $("#pm-progress-list");
  const sectionCards = $("#pm-section-cards");
  const errorMessage = $("#pm-error-message");
  const downloadBtn = $("#pm-download");
  const summaryWarnings = $("#pm-summary-warnings");
  const statSections = $("#pm-stat-sections");
  const statEdits = $("#pm-stat-edits");
  const statTerms = $("#pm-stat-terms");

  // ---------- State ----------
  let totalSections = 0;     // non-skipped count (the units of progress)
  let totalSteps = 0;        // totalSections * 3 stages + skipped sections
  let completedSteps = 0;
  let docFilename = null;
  let docTitle = "Rewritten document";

  // ---------- Boot ----------
  let input;
  try {
    input = JSON.parse(sessionStorage.getItem(INPUT_KEY) || "null");
  } catch (_) { input = null; }

  if (!input || (!input.text && !(input.sections && input.sections.length))) {
    progressCard.classList.add("is-hidden");
    empty.classList.remove("is-hidden");
    return;
  }
  docFilename = input.filename || null;
  docTitle = input.title || "Rewritten document";

  startStream(input).catch((err) => {
    showError(err && err.message ? err.message : "Network error.");
  });

  // ---------- Streaming ----------
  async function startStream(payload) {
    const body = {
      protected_terms: payload.protected_terms || [],
    };
    if (payload.sections && payload.sections.length) {
      body.sections = payload.sections;
    } else {
      body.text = payload.text;
    }

    const res = await fetch("/api/plagiarism/reduce-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const j = await res.json();
        detail = j.detail || detail;
      } catch (_) { /* keep default */ }
      throw new Error(detail);
    }
    if (!res.body) throw new Error("Streaming not supported by this browser.");

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) !== -1) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        let evt;
        try { evt = JSON.parse(line); } catch (_) { continue; }
        handleEvent(evt);
      }
    }
    // Flush any trailing line.
    const trailing = buf.trim();
    if (trailing) {
      try { handleEvent(JSON.parse(trailing)); } catch (_) { /* ignore */ }
    }
  }

  function handleEvent(evt) {
    switch (evt.type) {
      case "init": return onInit(evt);
      case "section_start": return onSectionStart(evt);
      case "stage_done": return onStageDone(evt);
      case "section_done": return onSectionDone(evt);
      case "complete": return onComplete(evt);
      case "error": return onErrorEvent(evt);
    }
  }

  function onInit(evt) {
    const secs = Array.isArray(evt.sections) ? evt.sections : [];
    totalSections = secs.filter((s) => !s.skipped).length;
    totalSteps = totalSections * 3 + secs.filter((s) => s.skipped).length;
    if (totalSteps === 0) totalSteps = 1; // avoid /0
    progressList.innerHTML = secs.map((s) => {
      const cls = s.skipped ? "is-skipped" : "";
      const sub = s.skipped
        ? (s.skip_reason === "references" ? "Kept verbatim" : "Empty — skipped")
        : "Queued";
      return `<li class="pm-progress-item ${cls}" data-index="${s.index}" data-testid="progress-item-${s.index}">
        <span class="pm-progress-item-label">${escapeHtml(s.label)}</span>
        <span class="pm-progress-item-state" data-testid="progress-item-state-${s.index}">${escapeHtml(sub)}</span>
      </li>`;
    }).join("");
    progressCurrent.textContent = totalSections > 0
      ? `Preparing ${totalSections} section${totalSections === 1 ? "" : "s"}…`
      : "Nothing to rewrite.";
    // Skipped sections count toward progress too (instant work).
    const skipped = secs.filter((s) => s.skipped).length;
    completedSteps += skipped;
    updateProgress();
  }

  function onSectionStart(evt) {
    const item = progressList.querySelector(`[data-index="${evt.index}"]`);
    if (item) {
      item.classList.add("is-active");
      const state = item.querySelector(".pm-progress-item-state");
      if (state) state.textContent = "Stage A: paraphrase…";
    }
    progressCurrent.textContent = `Section ${evt.index + 1}: ${evt.label}`;
  }

  function onStageDone(evt) {
    completedSteps += 1;
    updateProgress();
    const item = progressList.querySelector(`[data-index="${evt.index}"]`);
    if (item) {
      const state = item.querySelector(".pm-progress-item-state");
      if (state) {
        if (evt.stage === "a") state.textContent = "Stage B: humanise…";
        else if (evt.stage === "b") state.textContent = "Stage C: polish…";
        else if (evt.stage === "c") state.textContent = "Finalising…";
      }
    }
  }

  function onSectionDone(evt) {
    const sec = evt.section || {};
    const item = progressList.querySelector(`[data-index="${sec.index}"]`);
    if (item) {
      item.classList.remove("is-active");
      item.classList.add("is-done");
      const state = item.querySelector(".pm-progress-item-state");
      if (state) {
        if (sec.skipped) {
          state.textContent = sec.skip_reason === "references" ? "Kept verbatim ✓" : "Skipped ✓";
        } else {
          state.textContent = "Done ✓";
        }
      }
    }
  }

  function onComplete(evt) {
    completedSteps = totalSteps;
    updateProgress();
    progressCurrent.textContent = "Done.";
    try {
      sessionStorage.setItem(RESULT_KEY, JSON.stringify(evt.result));
    } catch (_) { /* quota — ok to skip cache */ }
    renderResult(evt.result);
  }

  function onErrorEvent(evt) {
    showError(evt.message || "Rewrite failed.");
  }

  function updateProgress() {
    const pct = Math.min(100, Math.round((completedSteps / totalSteps) * 100));
    progressFill.style.width = pct + "%";
    progressPct.textContent = pct + "%";
    progressBar.setAttribute("aria-valuenow", String(pct));
  }

  function showError(msg) {
    progressCard.classList.add("is-hidden");
    errorCard.classList.remove("is-hidden");
    errorMessage.textContent = msg;
  }

  // ---------- Render results ----------
  function renderResult(result) {
    if (!result || !result.pipeline) {
      showError("Rewrite returned no usable output.");
      return;
    }
    const sections = result.pipeline.sections || [];
    const nonSkipped = sections.filter((s) => !s.skipped);
    const totalEdits = result.changes_made || 0;
    const protectedTotal = result.protected_terms_count || 0;
    const missing = Array.isArray(result.preserved_terms_missing) ? result.preserved_terms_missing : [];
    const preserved = Math.max(0, protectedTotal - missing.length);

    statSections.textContent = String(nonSkipped.length);
    statEdits.textContent = totalEdits.toLocaleString();
    statTerms.textContent = protectedTotal === 0
      ? "0 / 0"
      : `${preserved} / ${protectedTotal}`;

    // Build the highlight regex from whatever protected terms we sent to
    // the pipeline (plus any that came back). Terms that the LLM dropped
    // are still highlighted in the original column so the user can find
    // and reinsert them.
    const termsForHighlight = (input && Array.isArray(input.protected_terms))
      ? input.protected_terms
      : [];
    _termRegex = buildTermRegex(termsForHighlight);

    // Surface warnings (missing terms, fallbacks)
    const warnings = [];
    if (missing.length > 0) {
      const sample = missing.slice(0, 6).map(escapeHtml).join(", ");
      const more = missing.length > 6 ? ` (+${missing.length - 6} more)` : "";
      warnings.push(`<strong>Heads up:</strong> ${missing.length} protected term${missing.length === 1 ? " did" : "s did"} not survive the rewrite — ${sample}${more}. Restore manually before submitting.`);
    }
    if (result.pipeline.any_fallback) {
      warnings.push("One or more stages used the <strong>fallback provider</strong>. Sections affected are flagged orange below.");
    }
    if (warnings.length) {
      summaryWarnings.innerHTML = warnings.map((w) => `<div class="pm-summary-warning">${w}</div>`).join("");
      summaryWarnings.classList.remove("is-hidden");
    }

    // Render per-section cards
    sectionCards.innerHTML = sections.map(renderCard).join("");
    sectionCards.querySelectorAll(".pm-section-card-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        const card = btn.closest(".pm-section-card");
        if (card) card.classList.toggle("is-expanded");
      });
    });
    sectionCards.querySelectorAll(".pm-stage-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        const wrap = btn.closest(".pm-section-card-stages");
        if (wrap) wrap.classList.toggle("is-open");
      });
    });

    // Wire download
    downloadBtn.addEventListener("click", () => downloadDocx(result));

    // Reveal results, hide progress
    progressCard.classList.add("is-hidden");
    resultsBlock.classList.remove("is-hidden");
  }

  function renderCard(sec) {
    const q = sec.quality || { key: "gray", label: "—", hint: "" };
    const skipped = !!sec.skipped;
    const skipReason = sec.skip_reason || "";
    const original = sec.original || "";
    const finalText = sec.final_text || "";
    const wordCount = (original.match(/\S+/g) || []).length;
    const editsTxt = skipped ? "0 edits" : `${(sec.edits || 0).toLocaleString()} edits`;
    const labelChip = skipped
      ? (skipReason === "references" ? "Kept verbatim" : "Empty")
      : `${wordCount.toLocaleString()} words · ${editsTxt}`;

    const stageModels = sec.stage_models || {};
    const stagesHtml = skipped ? "" : `
      <div class="pm-section-card-stages">
        <button type="button" class="pm-stage-toggle" data-testid="toggle-stages-${sec.index}">
          <span>Show pipeline stages (A → B → C)</span>
          <span class="pm-stage-toggle-caret" aria-hidden="true">▾</span>
        </button>
        <div class="pm-stage-grid">
          <div class="pm-stage-col">
            <div class="pm-stage-head">Stage A · paraphrase</div>
            <div class="pm-stage-model">${escapeHtml(stageModels.a || "—")}</div>
            <pre class="pm-stage-text">${escapeHtml(sec.stage_a_text || "")}</pre>
          </div>
          <div class="pm-stage-col">
            <div class="pm-stage-head">Stage B · humanise</div>
            <div class="pm-stage-model">${escapeHtml(stageModels.b || "—")}</div>
            <pre class="pm-stage-text">${escapeHtml(sec.stage_b_text || "")}</pre>
          </div>
          <div class="pm-stage-col">
            <div class="pm-stage-head">Stage C · polish</div>
            <div class="pm-stage-model">${escapeHtml(stageModels.c || "—")}</div>
            <pre class="pm-stage-text">${escapeHtml(sec.stage_c_text || "")}</pre>
          </div>
        </div>
      </div>`;

    return `<article class="pm-section-card pm-section-card--${escapeHtml(q.key)}" data-testid="card-section-${sec.index}">
      <header class="pm-section-card-head">
        <div class="pm-section-card-title">
          <h3 data-testid="text-section-label-${sec.index}">${escapeHtml(sec.label || "Section")}</h3>
          <span class="pm-section-card-meta" data-testid="text-section-meta-${sec.index}">${escapeHtml(labelChip)}</span>
        </div>
        <span class="pm-quality-chip pm-quality-chip--${escapeHtml(q.key)}" data-testid="chip-quality-${sec.index}" title="${escapeHtml(q.hint || "")}">
          ${escapeHtml(q.label)}
        </span>
      </header>
      ${q.hint ? `<p class="pm-section-card-hint">${escapeHtml(q.hint)}</p>` : ""}
      <div class="pm-section-card-compare" data-testid="compare-${sec.index}">
        <div class="pm-compare-col">
          <div class="pm-compare-head">Original</div>
          <div class="pm-compare-text" data-testid="text-original-${sec.index}">${highlightTerms(original, _termRegex)}</div>
        </div>
        <div class="pm-compare-col">
          <div class="pm-compare-head">Rewritten${skipped && skipReason === "references" ? " (verbatim)" : ""}</div>
          <div class="pm-compare-text" data-testid="text-rewritten-${sec.index}">${highlightTerms(finalText, _termRegex)}</div>
        </div>
      </div>
      ${stagesHtml}
    </article>`;
  }

  // ---------- DOCX download ----------
  async function downloadDocx(result) {
    const sections = (result.pipeline && result.pipeline.sections) || [];
    const payload = {
      title: docTitle,
      filename: docFilename || docTitle,
      notes: result.notes || null,
      sections: sections.map((s) => ({
        label: s.label || "Section",
        text: s.final_text || "",
        skipped: !!s.skipped,
        skip_reason: s.skip_reason || null,
      })),
    };

    downloadBtn.disabled = true;
    const orig = downloadBtn.innerHTML;
    downloadBtn.innerHTML = '<span class="pm-btn-icon" aria-hidden="true">⏳</span> Building Word document…';

    try {
      const res = await fetch("/api/plagiarism/export-docx", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try { const j = await res.json(); detail = j.detail || detail; } catch (_) { /* keep default */ }
        throw new Error(detail);
      }
      const blob = await res.blob();
      // Try to pull filename from Content-Disposition.
      let dlName = "rewritten.docx";
      const cd = res.headers.get("Content-Disposition") || "";
      const m = /filename="([^"]+)"/i.exec(cd);
      if (m) dlName = m[1];

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = dlName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1500);
    } catch (err) {
      alert("Download failed: " + (err && err.message ? err.message : err));
    } finally {
      downloadBtn.disabled = false;
      downloadBtn.innerHTML = orig;
    }
  }
})();
