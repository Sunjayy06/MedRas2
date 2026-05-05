/* Reduce-results page — kicks off a background job, polls progress
 * every 5 s, and renders each section card the moment it lands so a
 * 200-page document feels live instead of waiting for one big payload.
 *
 * Replaces the previous NDJSON streaming approach: long-lived
 * connections drop on mobile sleep, proxy timeouts, etc. Polling is
 * boring and reliable.
 *
 * Input is read from sessionStorage key "pm:reduceInput", set by
 * checker.js when the user clicks "Reduce plagiarism".
 */
(function () {
  "use strict";

  const INPUT_KEY = "pm:reduceInput";
  const RESULT_KEY = "pm:reduceResult";
  const JOB_KEY = "pm:reduceJobId";
  const POLL_INTERVAL_MS = 5000;

  const $ = (s) => document.querySelector(s);

  // ---------- HTML / regex helpers ----------
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
  let _termRegex = null;
  function buildTermRegex(terms) {
    if (!terms || !terms.length) return null;
    const cleaned = Array.from(new Set(
      terms.map((t) => String(t || "").trim()).filter(Boolean)
    ));
    if (!cleaned.length) return null;
    cleaned.sort((a, b) => b.length - a.length);
    const pat = cleaned.map(escapeRegex).join("|");
    try { return new RegExp("(" + pat + ")", "g"); } catch (_) { return null; }
  }
  // XSS-safe: escape THEN inject. Protected terms can contain <, >, &.
  function highlightTerms(text, rx) {
    const safe = String(text == null ? "" : text);
    if (!rx) return escapeHtml(safe) || '<span class="pm-compare-empty">—</span>';
    let out = ""; let lastIdx = 0; rx.lastIndex = 0; let m;
    while ((m = rx.exec(safe)) !== null) {
      if (m.index === rx.lastIndex) { rx.lastIndex++; continue; }
      out += escapeHtml(safe.slice(lastIdx, m.index));
      out += '<mark class="pm-protected-term">' + escapeHtml(m[0]) + '</mark>';
      lastIdx = rx.lastIndex;
    }
    out += escapeHtml(safe.slice(lastIdx));
    return out || '<span class="pm-compare-empty">—</span>';
  }
  function fmtDuration(seconds) {
    if (seconds == null || !isFinite(seconds) || seconds < 0) return "—";
    const s = Math.round(seconds);
    if (s < 60) return s + "s";
    const m = Math.floor(s / 60);
    const r = s % 60;
    if (m < 60) return r ? `${m}m ${r}s` : `${m}m`;
    const h = Math.floor(m / 60);
    const rm = m % 60;
    return rm ? `${h}h ${rm}m` : `${h}h`;
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
  const progressPass = $("#pm-progress-pass");
  const progressEta = $("#pm-progress-eta");
  const progressCounts = $("#pm-progress-counts");
  const sectionCards = $("#pm-section-cards");
  const errorMessage = $("#pm-error-message");
  const downloadBtn = $("#pm-download");
  const summaryWarnings = $("#pm-summary-warnings");
  const statSections = $("#pm-stat-sections");
  const statEdits = $("#pm-stat-edits");
  const statTerms = $("#pm-stat-terms");
  const retryBanner = $("#pm-retry-banner");
  const retryBtn = $("#pm-retry-btn");
  const retryMsg = $("#pm-retry-message");

  // ---------- State ----------
  let docFilename = null;
  let docTitle = "Rewritten document";
  let jobId = null;
  let pollTimer = null;
  let pollingTerminated = false;     // once true, no more polls scheduled
  let renderedIndices = new Set();   // section indices we've already drawn a card for
  let sectionListBuilt = false;      // progress list built once on first poll
  let lastSnapshot = null;           // most recent /jobs/{id} response
  let inputProtectedTerms = [];

  // ---------- Boot ----------
  let input;
  try { input = JSON.parse(sessionStorage.getItem(INPUT_KEY) || "null"); }
  catch (_) { input = null; }

  if (!input || (!input.text && !(input.sections && input.sections.length))) {
    progressCard.classList.add("is-hidden");
    empty.classList.remove("is-hidden");
    return;
  }
  docFilename = input.filename || null;
  docTitle = input.title || "Rewritten document";
  inputProtectedTerms = Array.isArray(input.protected_terms) ? input.protected_terms : [];
  _termRegex = buildTermRegex(inputProtectedTerms);

  // The summary card and section-cards container live inside #pm-results.
  // For incremental rendering we reveal #pm-results immediately, but
  // keep the summary stats showing "—" until completion. The user sees
  // section cards stream in below the (initially placeholder) stats.
  // Reveal results container so cards can fade in as they arrive.
  resultsBlock.classList.remove("is-hidden");
  // Hide download until everything finished — partial download could mislead.
  downloadBtn.disabled = true;

  startJob(input).catch((err) => {
    showError(err && err.message ? err.message : "Network error.");
  });

  // ---------- Job lifecycle ----------
  async function startJob(payload) {
    const body = {
      protected_terms: payload.protected_terms || [],
      title: docTitle,
      filename: docFilename,
    };
    if (payload.sections && payload.sections.length) {
      body.sections = payload.sections;
    } else {
      body.text = payload.text;
    }

    const res = await fetch("/api/plagiarism/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(json.detail || `Failed to start job (HTTP ${res.status})`);
    }
    jobId = json.job_id;
    try { sessionStorage.setItem(JOB_KEY, jobId); } catch (_) { /* quota */ }
    progressCurrent.textContent = `Queued ${json.total_sections} section${json.total_sections === 1 ? "" : "s"}…`;

    // Poll once immediately, then every POLL_INTERVAL_MS.
    await pollOnce();
    schedulePoll();
  }

  function schedulePoll() {
    if (pollingTerminated) return;
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(async () => {
      let fatal = false;
      try { await pollOnce(); }
      catch (err) {
        // 404 (or any sentinel-flagged error) is fatal — stop polling
        // immediately or we'd hammer the server forever. Other network
        // blips are transient; we keep going.
        if (err && err.fatal) {
          fatal = true;
          showError(err.message || "Job no longer available.");
        } else {
          console.warn("plagiarism poll failed:", err);
        }
      }
      if (fatal) return;
      const status = lastSnapshot && lastSnapshot.status;
      if (status !== "complete" && status !== "failed" && status !== "cancelled") {
        schedulePoll();
      }
    }, POLL_INTERVAL_MS);
  }

  async function pollOnce() {
    if (!jobId || pollingTerminated) return;
    const res = await fetch(`/api/plagiarism/jobs/${encodeURIComponent(jobId)}`);
    if (res.status === 404) {
      // Stop polling — the server has no record of this job and never
      // will. Without this guard the schedulePoll loop would treat it
      // as a transient error and hammer the endpoint forever.
      pollingTerminated = true;
      const err = new Error("This job has expired. Please start a new rewrite.");
      err.fatal = true;
      throw err;
    }
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      throw new Error(j.detail || `HTTP ${res.status}`);
    }
    const snap = await res.json();
    lastSnapshot = snap;
    applySnapshot(snap);
  }

  // ---------- Snapshot → DOM ----------
  function applySnapshot(snap) {
    // First snapshot: build the progress list with all section labels.
    if (!sectionListBuilt) {
      buildProgressList(snap);
      sectionListBuilt = true;
    }
    updateProgressMeta(snap);
    renderNewSections(snap);
    if (snap.status === "complete" || snap.status === "failed" || snap.status === "cancelled") {
      finalize(snap);
    }
  }

  function buildProgressList(snap) {
    progressList.innerHTML = (snap.sections || []).map((s) => {
      return `<li class="pm-progress-item" data-index="${s.index}" data-testid="progress-item-${s.index}">
        <span class="pm-progress-item-label">${escapeHtml(s.label || "Section")}</span>
        <span class="pm-progress-item-state" data-testid="progress-item-state-${s.index}">Queued</span>
      </li>`;
    }).join("");
  }

  function updateProgressMeta(snap) {
    const pct = snap.percent || 0;
    progressFill.style.width = pct + "%";
    progressPct.textContent = pct + "%";
    progressBar.setAttribute("aria-valuenow", String(pct));

    if (snap.current_section) {
      progressCurrent.textContent = `Rewriting ${snap.current_section}…`;
    } else if (snap.status === "queued") {
      progressCurrent.textContent = "Queued…";
    } else if (snap.status === "processing") {
      progressCurrent.textContent = "Processing…";
    }

    if (progressPass) {
      progressPass.textContent = snap.current_pass_label || "";
    }
    if (progressCounts) {
      const totalNonSkipped = (snap.sections || []).filter((s) => s.status !== "skipped" || s.status === "skipped").length;
      progressCounts.textContent = `${snap.completed_count} of ${snap.total_sections} sections complete${snap.failed_count ? ` · ${snap.failed_count} failed` : ""}`;
    }
    if (progressEta) {
      if (snap.status === "processing" && snap.eta_seconds != null) {
        progressEta.textContent = `≈ ${fmtDuration(snap.eta_seconds)} remaining`;
      } else if (snap.status === "complete") {
        progressEta.textContent = `Done in ${fmtDuration(snap.elapsed_seconds)}.`;
      } else {
        progressEta.textContent = "";
      }
    }

    // Per-row state in the list.
    (snap.sections || []).forEach((s) => {
      const item = progressList.querySelector(`[data-index="${s.index}"]`);
      if (!item) return;
      item.classList.remove("is-active", "is-done", "is-failed", "is-skipped");
      const state = item.querySelector(".pm-progress-item-state");
      switch (s.status) {
        case "pending":
          if (state) state.textContent = "Queued";
          break;
        case "processing":
          item.classList.add("is-active");
          if (state) state.textContent = snap.current_pass_label || "Processing…";
          break;
        case "complete":
          item.classList.add("is-done");
          if (state) state.textContent = "Done ✓";
          break;
        case "skipped":
          item.classList.add("is-skipped", "is-done");
          if (state) state.textContent = (s.skip_reason === "references") ? "Kept verbatim ✓" : "Skipped ✓";
          break;
        case "failed":
          item.classList.add("is-failed");
          if (state) state.textContent = "Failed ✗";
          break;
        case "timed_out":
          item.classList.add("is-failed");
          if (state) state.textContent = "Timed out ✗";
          break;
      }
    });
  }

  function renderNewSections(snap) {
    const sections = snap.sections || [];
    for (const sec of sections) {
      // Render once a section reaches a terminal status (complete, skipped,
      // failed, timed_out). Pending / processing are left to the progress
      // list above.
      const isTerminal = ["complete", "skipped", "failed", "timed_out"].indexOf(sec.status) !== -1;
      if (!isTerminal) continue;
      if (renderedIndices.has(sec.index)) continue;
      const html = renderCard(sec);
      const wrap = document.createElement("div");
      wrap.innerHTML = html;
      const node = wrap.firstElementChild;
      if (node) {
        node.classList.add("pm-section-card--fadein");
        sectionCards.appendChild(node);
        wireCard(node);
      }
      renderedIndices.add(sec.index);
    }
  }

  function wireCard(card) {
    const t = card.querySelector(".pm-section-card-toggle");
    if (t) t.addEventListener("click", () => card.classList.toggle("is-expanded"));
    const sToggle = card.querySelector(".pm-stage-toggle");
    if (sToggle) sToggle.addEventListener("click", () => {
      const wrap = sToggle.closest(".pm-section-card-stages");
      if (wrap) wrap.classList.toggle("is-open");
    });
  }

  function finalize(snap) {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    pollingTerminated = true;
    // Stop the spinner / pass label, keep the bar at its terminal value.
    if (progressPass) progressPass.textContent = "";
    if (snap.status === "complete") {
      progressCurrent.textContent = "Done.";
    } else if (snap.status === "cancelled") {
      progressCurrent.textContent = "Cancelled.";
    } else {
      progressCurrent.textContent = "Stopped.";
    }

    // Build the summary card from settled sections.
    populateSummary(snap);
    showRetryBannerIfNeeded(snap);

    // Persist to sessionStorage as a result for back-button / refresh.
    try {
      sessionStorage.setItem(RESULT_KEY, JSON.stringify(buildLegacyResultShape(snap)));
    } catch (_) { /* quota — ok */ }

    // Job is done — collapse the progress card so the cards take focus.
    // We keep it visible (not hidden) so the user can still see the
    // per-section list with green ticks.
    progressCard.classList.add("is-finished");

    // If everything succeeded, enable download. If anything failed, the
    // user can still download what we have, but the warning banner
    // explains it's partial.
    downloadBtn.disabled = false;
  }

  function populateSummary(snap) {
    const sections = snap.sections || [];
    const succeeded = sections.filter((s) => s.status === "complete" || s.status === "skipped");
    const nonSkipped = succeeded.filter((s) => !s.skipped);
    const totalEdits = nonSkipped.reduce((acc, s) => acc + (s.edits || 0), 0);
    const protectedTotal = (snap.protected_terms || []).length;

    // Count missing terms across all completed sections (de-duplicated).
    const missingSet = new Set();
    for (const s of nonSkipped) {
      (s.missing_terms || []).forEach((t) => missingSet.add(t));
    }
    const missing = Array.from(missingSet);
    const preserved = Math.max(0, protectedTotal - missing.length);

    statSections.textContent = String(nonSkipped.length);
    statEdits.textContent = totalEdits.toLocaleString();
    statTerms.textContent = protectedTotal === 0 ? "0 / 0" : `${preserved} / ${protectedTotal}`;

    const warnings = [];
    if (snap.status === "failed" && snap.error === "providers_exhausted") {
      warnings.push("<strong>Both AI providers ran out of quota mid-job.</strong> Try again later, or top up one of the provider accounts.");
    }
    if (missing.length > 0) {
      const sample = missing.slice(0, 6).map(escapeHtml).join(", ");
      const more = missing.length > 6 ? ` (+${missing.length - 6} more)` : "";
      warnings.push(`<strong>Heads up:</strong> ${missing.length} protected term${missing.length === 1 ? " did" : "s did"} not survive the rewrite — ${sample}${more}. Restore manually before submitting.`);
    }
    const fallbackUsed = nonSkipped.some((s) => s.fallback_used);
    if (fallbackUsed) {
      warnings.push("One or more stages used the <strong>fallback provider</strong>. Sections affected are flagged orange below.");
    }
    if (warnings.length) {
      summaryWarnings.innerHTML = warnings.map((w) => `<div class="pm-summary-warning">${w}</div>`).join("");
      summaryWarnings.classList.remove("is-hidden");
    } else {
      summaryWarnings.classList.add("is-hidden");
    }

    // Wire the download button (idempotent — finalize may run more than
    // once if the user retries, so we replace the listener).
    const fresh = downloadBtn.cloneNode(true);
    downloadBtn.parentNode.replaceChild(fresh, downloadBtn);
    fresh.disabled = false;
    fresh.addEventListener("click", () => downloadDocx(snap));
    // Update our reference so future finalize() calls see the new node.
    Object.defineProperty(window, "_pmDownloadBtn", { value: fresh, configurable: true });
  }

  function showRetryBannerIfNeeded(snap) {
    if (!retryBanner) return;
    const failed = (snap.sections || []).filter((s) => s.status === "failed" || s.status === "timed_out");
    if (!failed.length) {
      retryBanner.classList.add("is-hidden");
      return;
    }
    if (retryMsg) {
      retryMsg.textContent = `${failed.length} section${failed.length === 1 ? "" : "s"} could not be processed. Click below to retry just ${failed.length === 1 ? "that one" : "those"}.`;
    }
    retryBanner.classList.remove("is-hidden");
    if (retryBtn) {
      retryBtn.disabled = false;
      // Replace listener on each finalize so we always have one binding.
      const fresh = retryBtn.cloneNode(true);
      retryBtn.parentNode.replaceChild(fresh, retryBtn);
      fresh.addEventListener("click", () => retryFailed(failed.map((s) => s.index)));
    }
  }

  async function retryFailed(indices) {
    if (!jobId || !indices.length) return;
    // Clear cards we're about to re-render so we don't end up with
    // duplicate entries when the next snapshot brings new results.
    // Also reset the matching progress-list rows so the user sees
    // them go from "Failed ✗" back to "Queued" instead of stale.
    for (const idx of indices) {
      const card = sectionCards.querySelector(`[data-section-index="${idx}"]`);
      if (card) card.remove();
      renderedIndices.delete(idx);
      const item = progressList.querySelector(`[data-index="${idx}"]`);
      if (item) {
        item.classList.remove("is-failed", "is-done", "is-active");
        const state = item.querySelector(".pm-progress-item-state");
        if (state) state.textContent = "Queued";
      }
    }
    if (retryBanner) retryBanner.classList.add("is-hidden");
    progressCard.classList.remove("is-finished");
    const dlNow = document.getElementById("pm-download");
    if (dlNow) dlNow.disabled = true;
    pollingTerminated = false;  // re-arm polling for the retry run

    try {
      const res = await fetch(`/api/plagiarism/jobs/${encodeURIComponent(jobId)}/retry`, { method: "POST" });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j.detail || `HTTP ${res.status}`);
      lastSnapshot = j;
      applySnapshot(j);
      schedulePoll();
    } catch (err) {
      pollingTerminated = true;
      alert("Retry failed: " + (err && err.message ? err.message : err));
    }
  }

  function showError(msg) {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    progressCard.classList.add("is-hidden");
    errorCard.classList.remove("is-hidden");
    errorMessage.textContent = msg;
  }

  // ---------- Per-section card ----------
  function renderCard(sec) {
    const q = sec.quality || { key: "gray", label: "—", hint: "" };
    const skipped = !!sec.skipped;
    const failed = sec.status === "failed" || sec.status === "timed_out";
    const skipReason = sec.skip_reason || "";
    const original = sec.original || "";
    const finalText = sec.final_text || "";
    const wordCount = (original.match(/\S+/g) || []).length;
    const editsTxt = (skipped || failed) ? "" : `${(sec.edits || 0).toLocaleString()} edits`;
    let labelChip;
    if (failed) {
      labelChip = sec.status === "timed_out" ? "Timed out" : "Failed";
    } else if (skipped) {
      labelChip = (skipReason === "references") ? "Kept verbatim" : "Empty";
    } else {
      labelChip = `${wordCount.toLocaleString()} words · ${editsTxt}`;
    }

    const stageModels = sec.stage_models || {};
    const stagesHtml = (skipped || failed) ? "" : `
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

    const compareHtml = failed
      ? `<div class="pm-section-card-failed" data-testid="text-section-failed-${sec.index}">
           <p><strong>${sec.status === "timed_out" ? "This section timed out." : "This section failed."}</strong> ${escapeHtml(sec.error || "")}</p>
           <p>Use the <em>Retry Failed Sections</em> button at the top of the results to try again. Your other sections are unaffected.</p>
         </div>`
      : `<div class="pm-section-card-compare" data-testid="compare-${sec.index}">
          <div class="pm-compare-col">
            <div class="pm-compare-head">Original</div>
            <div class="pm-compare-text" data-testid="text-original-${sec.index}">${highlightTerms(original, _termRegex)}</div>
          </div>
          <div class="pm-compare-col">
            <div class="pm-compare-head">Rewritten${skipped && skipReason === "references" ? " (verbatim)" : ""}</div>
            <div class="pm-compare-text" data-testid="text-rewritten-${sec.index}">${highlightTerms(finalText, _termRegex)}</div>
          </div>
        </div>`;

    const qKey = failed ? "orange" : (q.key || "gray");
    const qLabel = failed ? labelChip : (q.label || "—");
    const qHint = failed ? (sec.error || "") : (q.hint || "");

    return `<article class="pm-section-card pm-section-card--${escapeHtml(qKey)}" data-section-index="${sec.index}" data-testid="card-section-${sec.index}">
      <header class="pm-section-card-head">
        <div class="pm-section-card-title">
          <h3 data-testid="text-section-label-${sec.index}">${escapeHtml(sec.label || "Section")}</h3>
          <span class="pm-section-card-meta" data-testid="text-section-meta-${sec.index}">${escapeHtml(labelChip)}</span>
        </div>
        <span class="pm-quality-chip pm-quality-chip--${escapeHtml(qKey)}" data-testid="chip-quality-${sec.index}" title="${escapeHtml(qHint)}">
          ${escapeHtml(qLabel)}
        </span>
      </header>
      ${qHint ? `<p class="pm-section-card-hint">${escapeHtml(qHint)}</p>` : ""}
      ${compareHtml}
      ${stagesHtml}
    </article>`;
  }

  // ---------- DOCX download ----------
  function buildLegacyResultShape(snap) {
    // Keeps RESULT_KEY backward compatible with anything else that
    // might read it.
    return {
      original_text: "",
      rewritten_text: (snap.sections || []).filter((s) => s.status === "complete" || s.status === "skipped").map((s) => s.final_text || "").join("\n\n"),
      changes_made: (snap.sections || []).reduce((a, s) => a + (s.edits || 0), 0),
      protected_terms_count: (snap.protected_terms || []).length,
      preserved_terms_missing: [],
      pipeline: { sections: snap.sections || [] },
    };
  }

  async function downloadDocx(snap) {
    const sections = (snap.sections || [])
      .filter((s) => s.status === "complete" || s.status === "skipped")
      .map((s) => ({
        label: s.label || "Section",
        text: s.final_text || "",
        skipped: !!s.skipped,
        skip_reason: s.skip_reason || null,
      }));
    if (!sections.length) {
      alert("Nothing to download yet — all sections are either failed or pending.");
      return;
    }
    const payload = {
      title: docTitle,
      filename: docFilename || docTitle,
      sections,
    };

    const btn = document.getElementById("pm-download");
    if (!btn) return;
    btn.disabled = true;
    const orig = btn.innerHTML;
    btn.innerHTML = '<span class="pm-btn-icon" aria-hidden="true">⏳</span> Building Word document…';
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
      let dlName = "rewritten.docx";
      const cd = res.headers.get("Content-Disposition") || "";
      const m = /filename="([^"]+)"/i.exec(cd);
      if (m) dlName = m[1];
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = dlName;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1500);
    } catch (err) {
      alert("Download failed: " + (err && err.message ? err.message : err));
    } finally {
      btn.disabled = false;
      btn.innerHTML = orig;
    }
  }
})();
