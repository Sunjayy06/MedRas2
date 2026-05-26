/* ── Research Assistant Drawer — ra-drawer.js ─────────────────────────────
   Self-contained side-panel that connects to /api/study-builder/ask.
   Designed to be included on any MedRAS page that wants to surface the
   Knowledge Assistant grounded in the researcher's own analysis results.

   API
   ───
   window.RADrawer.open(lockedCtx, prefillQuestion)
     lockedCtx       — object matching the locked_context schema the backend
                       expects; if null the drawer opens as a standard RA chat.
     prefillQuestion — optional string; if provided the drawer auto-sends this
                       question on first open (before the user types anything).

   window.RADrawer.close()

   The drawer injects its own DOM when the page loads and keeps itself out of
   the way until open() is called.
   ──────────────────────────────────────────────────────────────────────── */

(function () {
  "use strict";

  /* ── Constants ──────────────────────────────────────────────────────── */

  const ASK_ENDPOINT = "/api/study-builder/ask";

  /* ── State ──────────────────────────────────────────────────────────── */

  let _sessionId   = null;   // grows across turns within one drawer open
  let _lockedCtx   = null;   // current locked_context (from Sigma)
  let _busy        = false;
  let _thread      = [];     // [{q, a, keyFindings, grade, gradeExpl, suggestions}]
  let _initialized = false;

  /* ── DOM refs (populated by _inject) ───────────────────────────────── */

  let _overlay, _drawer, _thread_el, _input_el, _send_el, _ctx_pill;

  /* ── Helpers ────────────────────────────────────────────────────────── */

  function _escHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* Minimal markdown: **bold**, [N] citations */
  function _renderText(s) {
    return _escHtml(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\[(\d+)\]/g, '<sup class="ra-cite">[$1]</sup>');
  }

  function _fmtPV(pv) {
    if (pv === null || pv === undefined) return "—";
    const n = Number(pv);
    if (!isFinite(n)) return "—";
    return n < 0.001 ? "< 0.001" : n.toFixed(3);
  }

  /* ── DOM injection ──────────────────────────────────────────────────── */

  function _inject() {
    if (_initialized) return;
    _initialized = true;

    /* Overlay */
    _overlay = document.createElement("div");
    _overlay.className = "ra-overlay";
    _overlay.setAttribute("aria-hidden", "true");
    _overlay.addEventListener("click", _close);

    /* Drawer */
    _drawer = document.createElement("aside");
    _drawer.className = "ra-drawer";
    _drawer.setAttribute("role", "dialog");
    _drawer.setAttribute("aria-modal", "true");
    _drawer.setAttribute("aria-label", "Research Assistant");
    _drawer.innerHTML = `
      <div class="ra-drawer-header">
        <div class="ra-drawer-icon">RA</div>
        <div>
          <div class="ra-drawer-title">Research Assistant</div>
          <div class="ra-drawer-subtitle">Knowledge Assistant · powered by MedRAS</div>
        </div>
        <button class="ra-drawer-close" aria-label="Close Research Assistant" type="button">&times;</button>
      </div>
      <div class="ra-drawer-ctx-pill" id="ra-ctx-pill" style="display:none"></div>
      <div class="ra-drawer-thread" id="ra-thread" role="log" aria-live="polite" aria-atomic="false"></div>
      <div class="ra-drawer-input-area">
        <div class="ra-drawer-input-row">
          <textarea
            id="ra-input"
            class="ra-drawer-input"
            rows="1"
            maxlength="1200"
            placeholder="Ask about your results or the literature…"
            aria-label="Your question"
          ></textarea>
          <button id="ra-send" class="ra-drawer-send" type="button" aria-label="Send">Send</button>
        </div>
        <p class="ra-drawer-hint">Literature search · evidence grading · clinical context</p>
      </div>
    `;

    document.body.appendChild(_overlay);
    document.body.appendChild(_drawer);

    _thread_el = document.getElementById("ra-thread");
    _input_el  = document.getElementById("ra-input");
    _send_el   = document.getElementById("ra-send");
    _ctx_pill  = document.getElementById("ra-ctx-pill");

    /* Close button */
    _drawer.querySelector(".ra-drawer-close").addEventListener("click", _close);

    /* Keyboard: Esc closes, Enter sends (Shift+Enter = newline) */
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && _drawer.classList.contains("is-open")) _close();
    });
    _input_el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); _send(); }
    });
    _input_el.addEventListener("input", _autoResize);

    _send_el.addEventListener("click", _send);
  }

  function _autoResize() {
    _input_el.style.height = "auto";
    _input_el.style.height = Math.min(_input_el.scrollHeight, 120) + "px";
  }

  /* ── Render thread ──────────────────────────────────────────────────── */

  function _renderThread() {
    if (!_thread_el) return;

    if (_thread.length === 0) {
      _thread_el.innerHTML = `
        <div class="ra-drawer-empty">
          <div style="font-size:1.5rem">📚</div>
          <div>Ask a question about your results<br>or the published literature.</div>
        </div>`;
      return;
    }

    const parts = [];
    _thread.forEach((turn, i) => {
      if (i > 0) parts.push('<hr class="ra-turn-divider">');

      /* User question */
      parts.push(`<div class="ra-msg-q">${_escHtml(turn.q)}</div>`);

      if (turn.typing) {
        parts.push(`<div class="ra-typing">
          <div class="ra-typing-dot"></div>
          <div class="ra-typing-dot"></div>
          <div class="ra-typing-dot"></div>
        </div>`);
        return;
      }

      /* AI answer */
      parts.push(`<div class="ra-msg-a">${_renderText(turn.a || "")}</div>`);

      /* Key findings */
      if (turn.keyFindings && turn.keyFindings.length) {
        const items = turn.keyFindings
          .map((kf) => {
            const cite = (kf.sources || []).map((n) => `[${n}]`).join("");
            return `<li>${_escHtml(kf.finding || kf)} ${_escHtml(cite)}</li>`;
          })
          .join("");
        parts.push(`<ul class="ra-findings">${items}</ul>`);
      }

      /* Evidence grade */
      if (turn.grade) {
        const gradeClass =
          turn.grade === "HIGH"     ? "ra-grade-HIGH"
          : turn.grade === "MODERATE" ? "ra-grade-MODERATE"
          : turn.grade === "LOW"      ? "ra-grade-LOW"
          : "ra-grade-default";
        const tooltip = _escHtml(turn.gradeExpl || "");
        parts.push(
          `<div class="${gradeClass} ra-grade" title="${tooltip}">` +
          `GRADE: ${_escHtml(turn.grade)}</div>`
        );
      }

      /* Suggested follow-up chips */
      if (turn.suggestions && turn.suggestions.length) {
        const chips = turn.suggestions
          .slice(0, 3)
          .map((q) => `<button class="ra-suggestion-chip" type="button" data-q="${_escHtml(q)}">${_escHtml(q)}</button>`)
          .join("");
        parts.push(`<div class="ra-suggestions">${chips}</div>`);
      }

      /* Take to Proposal Writer */
      parts.push(
        `<button class="ra-proposal-btn" type="button" data-turn="${i}">` +
        `✦ Take to Proposal Writer</button>`
      );
    });

    _thread_el.innerHTML = parts.join("");

    /* Bind chip clicks */
    _thread_el.querySelectorAll(".ra-suggestion-chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        const q = btn.dataset.q;
        if (q && !_busy) {
          _input_el.value = q;
          _autoResize();
          _send();
        }
      });
    });

    /* Bind "Take to Proposal Writer" */
    _thread_el.querySelectorAll(".ra-proposal-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.dataset.turn, 10);
        _handoffToProposal(idx);
      });
    });

    /* Scroll to bottom */
    _thread_el.scrollTop = _thread_el.scrollHeight;
  }

  /* ── Context pill ───────────────────────────────────────────────────── */

  function _renderCtxPill(ctx) {
    if (!_ctx_pill) return;
    if (!ctx) { _ctx_pill.style.display = "none"; return; }

    const studyType = ctx.study_type || "";
    const outcome   = ctx.outcome    || "";
    const tests     = (ctx.tests     || []).slice(0, 3);
    const sigTests  = tests.filter((t) => t.significant);

    let html = `<strong>📊 Grounded in your Sigma analysis</strong>`;
    if (studyType) html += `Study type: ${_escHtml(studyType)}`;
    if (outcome)   html += ` · Outcome: <em>${_escHtml(outcome)}</em>`;
    if (sigTests.length) {
      const names = sigTests
        .map((t) => _escHtml(t.variable || t.predictor || ""))
        .filter(Boolean)
        .join(", ");
      if (names) html += `<br>Significant: ${names}`;
    }

    _ctx_pill.innerHTML = html;
    _ctx_pill.style.display = "";
  }

  /* ── Send ───────────────────────────────────────────────────────────── */

  async function _send(questionOverride) {
    const question = (questionOverride || _input_el.value || "").trim();
    if (!question || _busy) return;

    _busy = true;
    _send_el.disabled = true;
    _input_el.value   = "";
    _input_el.style.height = "auto";

    /* Optimistic typing indicator */
    const turnIdx = _thread.length;
    _thread.push({ q: question, a: "", typing: true, keyFindings: [], grade: "", gradeExpl: "", suggestions: [] });
    _renderThread();

    try {
      const body = { question, session_id: _sessionId };
      if (_lockedCtx) body.locked_context = _lockedCtx;

      const resp = await fetch(ASK_ENDPOINT, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(body),
      });

      if (!resp.ok) {
        const err = await resp.text();
        throw new Error(err || `HTTP ${resp.status}`);
      }

      const data = await resp.json();
      _sessionId = data.session_id || _sessionId;

      /* Replace typing placeholder */
      _thread[turnIdx] = {
        q:           question,
        a:           data.answer || "",
        keyFindings: data.key_findings || [],
        grade:       data.evidence_grade || "",
        gradeExpl:   data.evidence_grade_explanation || "",
        suggestions: data.suggested_questions || [],
        papers:      data.papers || [],
      };

    } catch (err) {
      _thread[turnIdx] = {
        q: question,
        a: `Could not get an answer: ${err.message}. Please try again.`,
        keyFindings: [], grade: "", gradeExpl: "", suggestions: [],
      };
    }

    _busy = false;
    _send_el.disabled = false;
    _renderThread();
    _input_el.focus();
  }

  /* ── Proposal handoff ───────────────────────────────────────────────── */

  function _handoffToProposal(turnIdx) {
    const turn = _thread[turnIdx];
    if (!turn || !turn.a) return;

    /* Build a background snippet with answer + source list */
    const lines = [turn.a];

    if (turn.keyFindings && turn.keyFindings.length) {
      lines.push("\nKey findings:");
      turn.keyFindings.forEach((kf) => {
        const cite = (kf.sources || []).map((n) => `[${n}]`).join("");
        lines.push(`• ${kf.finding || kf} ${cite}`.trim());
      });
    }

    if (turn.papers && turn.papers.length) {
      lines.push("\nReferences:");
      turn.papers.slice(0, 8).forEach((p, i) => {
        const authors = (p.authors || []).join(", ");
        const doi     = (p.doi || p.url || "").replace(/.*doi\.org\//, "");
        lines.push(
          `[${i + 1}] ${authors}. ${p.title || ""}. ${p.journal || ""} (${p.year || ""}). ${doi ? "DOI: " + doi : ""}`
        );
      });
    }

    const backgroundText = lines.join("\n");

    /* Merge into existing proposal intake if present */
    let intake = {};
    try {
      const saved = sessionStorage.getItem("medras.proposal.intake");
      if (saved) intake = JSON.parse(saved);
    } catch (_) {}

    intake._ra_background = backgroundText.slice(0, 3000);
    intake._ra_question   = turn.q;
    intake._ra_ts         = Date.now();

    try {
      sessionStorage.setItem("medras.proposal.intake", JSON.stringify(intake));
    } catch (_) {}

    /* Also write to the background key the proposal generator reads */
    try {
      const existing = JSON.parse(sessionStorage.getItem("medras.proposal.generated") || "{}");
      if (!existing.background) {
        existing.background = backgroundText.slice(0, 4000);
        sessionStorage.setItem("medras.proposal.generated", JSON.stringify(existing));
      }
    } catch (_) {}

    /* Visual feedback then navigate */
    const btn = _thread_el && _thread_el.querySelector(`.ra-proposal-btn[data-turn="${turnIdx}"]`);
    if (btn) {
      btn.textContent = "✓ Sent to Proposal Writer!";
      btn.style.borderColor = "rgba(52,211,153,.5)";
      btn.style.color = "#34d399";
    }

    setTimeout(() => {
      window.open("/proposal-module/", "_blank");
    }, 400);
  }

  /* ── Open / Close ───────────────────────────────────────────────────── */

  function _open(lockedCtx, prefillQuestion) {
    _inject();
    _lockedCtx = lockedCtx || null;

    /* Reset session on each open-with-new-context so the AI doesn't bleed
       the locked numbers from a previous study into the new one. */
    if (lockedCtx) {
      _sessionId = null;
      _thread    = [];
    }

    _renderCtxPill(lockedCtx);
    _renderThread();

    _overlay.classList.add("is-open");
    _drawer.classList.add("is-open");
    _overlay.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";

    _input_el.focus();

    /* Auto-send prefill question if provided */
    if (prefillQuestion && _thread.length === 0) {
      setTimeout(() => _send(prefillQuestion), 200);
    }
  }

  function _close() {
    if (!_initialized) return;
    _overlay.classList.remove("is-open");
    _drawer.classList.remove("is-open");
    _overlay.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  /* ── Inject CSS if not already linked ──────────────────────────────── */

  (function _ensureCSS() {
    const href = "/study-builder/css/ra-drawer.css";
    if (!document.querySelector(`link[href="${href}"]`)) {
      const link = document.createElement("link");
      link.rel  = "stylesheet";
      link.href = href;
      document.head.appendChild(link);
    }
  }());

  /* ── Public API ─────────────────────────────────────────────────────── */

  window.RADrawer = {
    open:  _open,
    close: _close,
  };
}());
