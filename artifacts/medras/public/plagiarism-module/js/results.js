/* Plagiarism results page — read latest check from sessionStorage and render. */

(function () {
  "use strict";

  const STORAGE_KEY = "pm:lastResult";

  const $ = (sel) => document.querySelector(sel);

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatTime(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return d.toLocaleString();
    } catch (_) {
      return iso;
    }
  }

  // Lower originality score = safer. Lower AI-likelihood = more human.
  function verdictForScore(score, opts) {
    // opts.kind: "originality" | "ai"
    const lowLabel = opts.kind === "ai" ? "Looks human-written" : "Reads as original";
    const midLabel = opts.kind === "ai" ? "Mixed signals" : "Some templated phrasing";
    const highLabel = opts.kind === "ai" ? "Likely AI-generated" : "High overlap with templated patterns";
    if (score < 30) return { label: lowLabel, cls: "pm-verdict--good" };
    if (score < 60) return { label: midLabel, cls: "pm-verdict--mid" };
    return { label: highLabel, cls: "pm-verdict--bad" };
  }

  let raw;
  try {
    raw = sessionStorage.getItem(STORAGE_KEY);
  } catch (_) {
    raw = null;
  }
  if (!raw) {
    showEmpty();
    return;
  }

  let result;
  try {
    result = JSON.parse(raw);
  } catch (_) {
    showEmpty();
    return;
  }

  function showEmpty() {
    $("#pm-empty").classList.remove("is-hidden");
    $("#pm-results").style.display = "none";
  }

  // ---- Render scores ----
  const overall = Math.max(0, Math.min(100, Number(result.overall_score) || 0));
  const ai = Math.max(0, Math.min(100, Number(result.ai_likelihood) || 0));
  const words = Number(result.word_count) || 0;
  const flagged = Array.isArray(result.flagged_passages) ? result.flagged_passages : [];

  $("#pm-score-overall").textContent = overall;
  $("#pm-score-ai").textContent = ai;
  $("#pm-score-words").textContent = words.toLocaleString();
  $("#pm-score-flagcount").textContent = `${flagged.length} flagged passage${flagged.length === 1 ? "" : "s"}`;

  // Animate bar fills after a tick so the transition runs.
  requestAnimationFrame(() => {
    $("#pm-score-overall-bar").style.width = `${overall}%`;
    $("#pm-score-ai-bar").style.width = `${ai}%`;
  });

  const ovVerdict = verdictForScore(overall, { kind: "originality" });
  const aiVerdict = verdictForScore(ai, { kind: "ai" });
  const ovEl = $("#pm-score-overall-verdict");
  ovEl.textContent = ovVerdict.label;
  ovEl.classList.add(ovVerdict.cls);
  const aiEl = $("#pm-score-ai-verdict");
  aiEl.textContent = aiVerdict.label;
  aiEl.classList.add(aiVerdict.cls);

  // ---- Summary ----
  $("#pm-summary").textContent = (result.summary || "No summary returned by the analyser.").trim();

  // ---- Flagged passages ----
  const list = $("#pm-flag-list");
  if (!flagged.length) {
    list.innerHTML = `<div class="pm-help" data-testid="text-no-flags" style="padding: 14px; background: var(--pm-surface-soft); border-radius: 8px;">
      No specific passages were flagged. Either the text is short or the analyser found nothing risky.
    </div>`;
  } else {
    list.innerHTML = flagged.map((f, i) => {
      const sev = (f.severity || "medium").toLowerCase();
      return `
        <div class="pm-flag" data-testid="flag-${i}">
          <div class="pm-flag-head">
            <span class="pm-flag-reason">${escapeHtml(f.reason || "Flagged")}</span>
            <span class="pm-sev pm-sev--${sev}" data-testid="flag-${i}-sev">${escapeHtml(sev)}</span>
          </div>
          ${f.text ? `<div class="pm-flag-text">"${escapeHtml(f.text)}"</div>` : ""}
          ${f.suggestion ? `<div class="pm-flag-suggestion"><strong>Suggested rewrite:</strong> ${escapeHtml(f.suggestion)}</div>` : ""}
        </div>`;
    }).join("");
  }

  // ---- Meta ----
  $("#pm-meta-model").textContent = result.model_used || "—";
  $("#pm-meta-time").textContent = formatTime(result.checked_at);
  if (result.filename) {
    const fnEl = $("#pm-meta-filename");
    fnEl.classList.remove("is-hidden");
    fnEl.innerHTML = `File: <strong>${escapeHtml(result.filename)}</strong>`;
  }
})();
