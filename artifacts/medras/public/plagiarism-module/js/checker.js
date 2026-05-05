/* Plagiarism checker page — paste/upload + run check + redirect to results. */

(function () {
  "use strict";

  const STORAGE_KEY = "pm:lastResult";
  const MAX_CHARS = 30000;

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  // ---- Mode (check vs reduce) — reflected in eyebrow + title ----
  const params = new URLSearchParams(window.location.search);
  const isReduceMode = params.get("mode") === "reduce";
  if (isReduceMode) {
    document.title = "Reduce plagiarism · MedRAS";
    const eyebrow = $('[data-testid="text-mode-eyebrow"]');
    const title = $('[data-testid="text-mode-title"]');
    const lede = $('[data-testid="text-mode-lede"]');
    const runBtn = $("#pm-run");
    if (eyebrow) eyebrow.textContent = "Plagiarism reducer";
    if (title) title.textContent = "Rewrite to read more original.";
    if (lede) lede.textContent = "Paste or upload your text. We'll rewrite templated phrasing into more natural prose, keeping every number, citation, and technical term intact.";
    if (runBtn) runBtn.textContent = "Reduce plagiarism";
  }

  // ---- Tabs ----
  $$(".pm-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.tab;
      $$(".pm-tab").forEach((t) => {
        t.classList.toggle("is-active", t === tab);
        t.setAttribute("aria-selected", t === tab ? "true" : "false");
      });
      $$(".pm-pane").forEach((p) => {
        p.classList.toggle("is-hidden", p.dataset.pane !== target);
      });
      setStatus("");
    });
  });

  // ---- Counter ----
  const textarea = $("#pm-text");
  const charsEl = $("#pm-count-chars");
  const wordsEl = $("#pm-count-words");
  const counterEl = $("#pm-counter");

  function updateCounter() {
    const text = textarea.value || "";
    const chars = text.length;
    const words = (text.match(/\b\w+\b/g) || []).length;
    charsEl.textContent = chars.toLocaleString();
    wordsEl.textContent = words.toLocaleString();
    counterEl.classList.toggle("is-over", chars > MAX_CHARS);
  }
  textarea.addEventListener("input", updateCounter);
  updateCounter();

  // ---- File picker / dropzone ----
  const dropzone = $("#pm-dropzone");
  const fileInput = $("#pm-file");
  const fileLabel = $("#pm-dropzone-filename");
  let selectedFile = null;

  function setSelectedFile(file) {
    selectedFile = file || null;
    if (selectedFile) {
      fileLabel.textContent = `Selected: ${selectedFile.name} (${(selectedFile.size / 1024).toFixed(1)} KB)`;
      fileLabel.classList.remove("is-hidden");
    } else {
      fileLabel.textContent = "";
      fileLabel.classList.add("is-hidden");
    }
  }

  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });
  fileInput.addEventListener("change", () => {
    setSelectedFile(fileInput.files && fileInput.files[0]);
  });
  ["dragover", "dragenter"].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("is-dragging");
    });
  });
  ["dragleave", "drop"].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.remove("is-dragging");
    });
  });
  dropzone.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) {
      // Reflect into the hidden input so users can re-submit easily.
      try {
        const dt = new DataTransfer();
        dt.items.add(f);
        fileInput.files = dt.files;
      } catch (_) {
        /* DataTransfer not supported in some sandboxed contexts; fine */
      }
      setSelectedFile(f);
    }
  });

  // ---- Status helper ----
  const statusEl = $("#pm-status");
  function setStatus(message, kind) {
    statusEl.className = "pm-status";
    if (!message) { statusEl.textContent = ""; return; }
    statusEl.textContent = message;
    statusEl.classList.add(`is-${kind || "loading"}`);
  }

  // ---- Run check ----
  const runBtn = $("#pm-run");
  const clearBtn = $("#pm-clear");
  const providerSel = $("#pm-provider");

  clearBtn.addEventListener("click", () => {
    textarea.value = "";
    setSelectedFile(null);
    fileInput.value = "";
    updateCounter();
    setStatus("");
  });

  runBtn.addEventListener("click", async () => {
    const activeTab = $(".pm-tab.is-active").dataset.tab;
    const provider = providerSel.value || "auto";

    runBtn.disabled = true;
    setStatus(isReduceMode ? "Rewriting your text…" : "Analysing your text…", "loading");

    try {
      let result;
      if (activeTab === "paste") {
        const text = (textarea.value || "").trim();
        if (!text) throw new Error("Paste some text first.");
        if (text.length > MAX_CHARS) throw new Error(`Text is too long (${text.length.toLocaleString()} chars). Maximum is ${MAX_CHARS.toLocaleString()}.`);
        result = await callApi(isReduceMode ? "/api/plagiarism/reduce" : "/api/plagiarism/check", {
          json: { text, provider },
        });
      } else {
        if (!selectedFile) throw new Error("Choose a file first.");
        if (selectedFile.size > 5 * 1024 * 1024) throw new Error("File is larger than 5 MB.");
        const fd = new FormData();
        fd.append("file", selectedFile);
        fd.append("provider", provider);
        if (isReduceMode) {
          // Reduce mode doesn't have a file endpoint yet — extract text
          // client-side for .txt only, otherwise tell the user.
          if (!/\.(txt|md)$/i.test(selectedFile.name)) {
            throw new Error("Reduce mode currently accepts pasted text or .txt files only. For PDF/DOCX, run a Check first then come back.");
          }
          const text = await selectedFile.text();
          result = await callApi("/api/plagiarism/reduce", { json: { text, provider } });
        } else {
          result = await callApi("/api/plagiarism/check-file", { form: fd });
        }
      }

      if (isReduceMode) {
        // For reduce mode we render the rewrite inline in a simple modal.
        showReduceResult(result);
        setStatus("Rewrite complete.", "success");
      } else {
        // Stash the result for the results page and redirect.
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
          ...result,
          checked_at: new Date().toISOString(),
        }));
        window.location.href = "/plagiarism-module/results.html";
      }
    } catch (err) {
      setStatus(err.message || "Something went wrong.", "error");
      runBtn.disabled = false;
    }
  });

  async function callApi(path, opts) {
    const init = { method: "POST" };
    if (opts.json) {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(opts.json);
    } else if (opts.form) {
      init.body = opts.form;
    }
    const res = await fetch(path, init);
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const j = await res.json();
        detail = j.detail || detail;
      } catch (_) {
        try { detail = (await res.text()) || detail; } catch (_) { /* keep default */ }
      }
      throw new Error(detail);
    }
    return res.json();
  }

  // ---- Reduce result (inline render) ----
  function showReduceResult(result) {
    // Replace the surface card with a before/after view + copy button.
    const host = document.querySelector(".pm-surface-card");
    if (!host) return;
    const original = (result.original_text || "").trim();
    const rewritten = (result.rewritten_text || "").trim();
    host.innerHTML = `
      <h2>Rewritten draft</h2>
      <p class="pm-help">${escapeHtml(result.notes || "Rewrite complete.")} <span style="color:var(--pm-text-soft);">· ${result.changes_made || 0} edits · engine: ${escapeHtml(result.model_used || "auto")}</span></p>
      <textarea class="pm-textarea" id="pm-rewrite-out" data-testid="textarea-pm-rewrite" style="min-height:340px;"></textarea>
      <div class="pm-actions">
        <button type="button" class="pm-btn pm-btn--primary" id="pm-copy" data-testid="button-pm-copy">Copy rewritten text</button>
        <a href="/plagiarism-module/checker.html?mode=reduce" class="pm-btn pm-btn--secondary" data-testid="button-pm-redo">Reduce another</a>
        <a href="/plagiarism-module/checker.html" class="pm-btn pm-btn--secondary" data-testid="button-pm-recheck">Check the rewrite</a>
      </div>
      <details style="margin-top:22px;">
        <summary style="cursor:pointer; font-weight:600; color: var(--pm-navy-700);">Show original</summary>
        <textarea class="pm-textarea" readonly style="margin-top:10px; min-height:200px; background:#f8f9fc;">${escapeHtml(original)}</textarea>
      </details>
    `;
    const out = document.getElementById("pm-rewrite-out");
    out.value = rewritten;
    document.getElementById("pm-copy").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(rewritten);
        setStatus("Copied to clipboard.", "success");
      } catch (_) {
        out.select();
        document.execCommand && document.execCommand("copy");
        setStatus("Selected — press Cmd/Ctrl+C to copy.", "success");
      }
    });
    document.getElementById("pm-recheck").addEventListener("click", () => {
      sessionStorage.setItem("pm:prefillText", rewritten);
    });
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // Pre-fill textarea if user came back from a "Check the rewrite" hop.
  const prefill = sessionStorage.getItem("pm:prefillText");
  if (prefill) {
    textarea.value = prefill;
    sessionStorage.removeItem("pm:prefillText");
    updateCounter();
  }
})();
