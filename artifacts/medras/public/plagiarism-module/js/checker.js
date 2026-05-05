/* Plagiarism checker page — paste/upload + (for uploads) document analysis,
 * then run check or reduce against the resulting text + protected terms.
 */

(function () {
  "use strict";

  const STORAGE_KEY = "pm:lastResult";
  const MAX_CHARS = 30000;
  const TERM_TYPE_LABELS = {
    p_value: "p-values",
    confidence_interval: "confidence intervals",
    test_statistic: "test statistics",
    percentage: "percentages",
    dose_unit: "doses & units",
    drug_name: "drug names",
    citation: "citations",
    doi: "DOIs",
    pmid: "PubMed IDs",
    gene_symbol: "gene symbols",
    icd_code: "ICD codes",
    statistic: "numbers",
  };

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

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

  // ---- File picker / dropzone / document analysis ----
  const dropzone = $("#pm-dropzone");
  const fileInput = $("#pm-file");
  const fileLabel = $("#pm-dropzone-filename");
  const docAnalysisEl = $("#pm-doc-analysis");
  const docTitleEl = $("#pm-doc-title");
  const docMetaEl = $("#pm-doc-meta");
  const docTruncEl = $("#pm-doc-truncated");
  const sectionListEl = $("#pm-section-list");
  const sectionCountEl = $("#pm-doc-section-count");
  const sectionSelectedEl = $("#pm-section-selected");
  const termSummaryEl = $("#pm-term-summary");
  const termListEl = $("#pm-term-list");
  const termCountEl = $("#pm-doc-term-count");
  const docClearBtn = $("#pm-doc-clear");
  const sectionAllBtn = $("#pm-section-all");
  const sectionNoneBtn = $("#pm-section-none");

  let selectedFile = null;
  let docAnalysis = null;       // server response from /analyze-file
  let sectionTextById = {};     // not currently used (server returns previews); reserved for chunked re-fetch

  function setSelectedFile(file) {
    selectedFile = file || null;
    if (selectedFile) {
      fileLabel.textContent = `Selected: ${selectedFile.name} (${formatBytes(selectedFile.size)})`;
      fileLabel.classList.remove("is-hidden");
    } else {
      fileLabel.textContent = "";
      fileLabel.classList.add("is-hidden");
    }
  }

  function formatBytes(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / (1024 * 1024)).toFixed(1)} MB`;
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
    if (selectedFile) runDocumentAnalysis(selectedFile);
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
      try {
        const dt = new DataTransfer();
        dt.items.add(f);
        fileInput.files = dt.files;
      } catch (_) {
        /* DataTransfer not supported in some sandboxed contexts; fine */
      }
      setSelectedFile(f);
      runDocumentAnalysis(f);
    }
  });

  docClearBtn.addEventListener("click", () => {
    setSelectedFile(null);
    fileInput.value = "";
    docAnalysis = null;
    sectionTextById = {};
    docAnalysisEl.classList.add("is-hidden");
    setStatus("");
  });

  sectionAllBtn.addEventListener("click", () => {
    $$('.pm-section-row input[type="checkbox"]').forEach((c) => { c.checked = true; });
    updateSelectedCount();
  });
  sectionNoneBtn.addEventListener("click", () => {
    $$('.pm-section-row input[type="checkbox"]').forEach((c) => { c.checked = false; });
    updateSelectedCount();
  });

  async function runDocumentAnalysis(file) {
    if (file.size > 100 * 1024 * 1024) {
      setStatus("File is larger than 100 MB.", "error");
      return;
    }
    setStatus(`Reading "${file.name}" and detecting sections…`, "loading");
    docAnalysisEl.classList.add("is-hidden");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const result = await callApi("/api/plagiarism/analyze-file", { form: fd });
      docAnalysis = result;
      renderDocAnalysis(result);
      setStatus("Document analysed. Pick the sections to include, then run a check.", "success");
    } catch (err) {
      setStatus(err.message || "Could not analyse the file.", "error");
    }
  }

  function renderDocAnalysis(result) {
    docAnalysisEl.classList.remove("is-hidden");
    docTitleEl.textContent = result.filename || "Document";
    const meta = [
      `${(result.total_word_count || 0).toLocaleString()} words`,
      `${(result.total_char_count || 0).toLocaleString()} chars`,
      formatBytes(result.size_bytes || 0),
    ];
    docMetaEl.textContent = meta.join(" · ");

    if (result.truncated) {
      docTruncEl.textContent = `This document is very large — only the first ${result.extracted_chars.toLocaleString()} characters were analysed.`;
      docTruncEl.classList.remove("is-hidden");
    } else {
      docTruncEl.classList.add("is-hidden");
    }

    // Sections
    const sections = Array.isArray(result.sections) ? result.sections : [];
    sectionCountEl.textContent = `${sections.length} found`;
    if (!sections.length) {
      sectionListEl.innerHTML = `<div class="pm-help" style="padding:10px;">No section headings detected. The whole document will be analysed as one block.</div>`;
    } else {
      sectionListEl.innerHTML = sections.map((s, i) => `
        <label class="pm-section-row" data-testid="section-row-${i}">
          <input type="checkbox" checked
                 data-section-index="${i}"
                 data-words="${s.word_count || 0}"
                 data-testid="section-check-${i}" />
          <span class="pm-section-label">${escapeHtml(s.label || "Untitled")}</span>
          <span class="pm-section-words">${(s.word_count || 0).toLocaleString()} words</span>
        </label>
      `).join("");
      $$('.pm-section-row input[type="checkbox"]').forEach((cb) => {
        cb.addEventListener("change", updateSelectedCount);
      });
    }
    updateSelectedCount();

    // Protected terms
    const terms = Array.isArray(result.protected_terms) ? result.protected_terms : [];
    const counts = result.protected_term_counts || {};
    termCountEl.textContent = `${terms.length} found`;
    if (!terms.length) {
      termSummaryEl.innerHTML = `<div class="pm-help">No technical terms detected — typical for a short or non-clinical text.</div>`;
      termListEl.innerHTML = "";
    } else {
      termSummaryEl.innerHTML = Object.entries(counts)
        .sort((a, b) => b[1] - a[1])
        .map(([type, n]) => `
          <span class="pm-term-chip">
            ${escapeHtml(TERM_TYPE_LABELS[type] || type)}
            <span class="pm-term-chip-count">${n}</span>
          </span>
        `).join("");
      termListEl.innerHTML = terms.slice(0, 200)
        .map((t) => `<code title="${escapeHtml(t.type)}">${escapeHtml(t.text)}</code>`)
        .join("");
    }
  }

  function updateSelectedCount() {
    if (!docAnalysis) {
      sectionSelectedEl.textContent = "0 words selected";
      return;
    }
    const checked = $$('.pm-section-row input[type="checkbox"]:checked');
    const total = checked.reduce((sum, cb) => sum + (parseInt(cb.dataset.words, 10) || 0), 0);
    const sectionCount = checked.length;
    const totalSections = $$('.pm-section-row input[type="checkbox"]').length;
    sectionSelectedEl.textContent = totalSections
      ? `${sectionCount} of ${totalSections} sections · ${total.toLocaleString()} words selected`
      : `${total.toLocaleString()} words`;
  }

  function buildSelectedText() {
    if (!docAnalysis) return "";
    const sections = docAnalysis.sections || [];
    const fullText = docAnalysis.extracted_text || "";
    if (!sections.length) return fullText;
    const checked = $$('.pm-section-row input[type="checkbox"]:checked')
      .map((cb) => parseInt(cb.dataset.sectionIndex, 10))
      .filter((i) => !isNaN(i));
    if (!checked.length) return "";
    if (checked.length === sections.length) return fullText;
    // Reconstruct each selected section by slicing the extracted_text using
    // start_line. We split once, slice, then re-join — only the checked
    // sections survive. This keeps server payloads small (we ship just the
    // breakdown back, not per-section text).
    const lines = fullText.split(/\r?\n/);
    const ordered = sections.slice().sort((a, b) => a.start_line - b.start_line);
    const pieces = [];
    for (let i = 0; i < ordered.length; i++) {
      const idx = sections.indexOf(ordered[i]);
      if (!checked.includes(idx)) continue;
      const startLine = ordered[i].start_line - 1;
      const endLine = (i + 1 < ordered.length) ? ordered[i + 1].start_line - 1 : lines.length;
      const sliceText = lines.slice(startLine, endLine).join("\n").trim();
      if (sliceText) pieces.push(sliceText);
    }
    return pieces.join("\n\n");
  }

  function getProtectedTerms(scopedText) {
    // Only return terms that actually appear in the text we're about to
    // send to the LLM. Otherwise, deselecting the Methods section but
    // still passing the p-values from Methods would produce phantom
    // "missing protected terms" warnings on the rewrite.
    if (!docAnalysis || !Array.isArray(docAnalysis.protected_terms)) return [];
    const haystack = scopedText || "";
    if (!haystack) return [];
    return docAnalysis.protected_terms
      .map((t) => t.text)
      .filter((t) => t && haystack.indexOf(t) !== -1);
  }

  // ---- Status helper ----
  const statusEl = $("#pm-status");
  function setStatus(message, kind) {
    statusEl.className = "pm-status";
    if (!message) { statusEl.textContent = ""; return; }
    statusEl.textContent = message;
    statusEl.classList.add(`is-${kind || "loading"}`);
  }

  // ---- Run check / reduce ----
  const runBtn = $("#pm-run");
  const clearBtn = $("#pm-clear");
  const providerSel = $("#pm-provider");

  clearBtn.addEventListener("click", () => {
    textarea.value = "";
    setSelectedFile(null);
    fileInput.value = "";
    docAnalysis = null;
    docAnalysisEl.classList.add("is-hidden");
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
      let text;
      let protectedTerms = [];

      if (activeTab === "paste") {
        text = (textarea.value || "").trim();
        if (!text) throw new Error("Paste some text first.");
      } else {
        if (!docAnalysis) throw new Error("Upload a file first — analysis hasn't run yet.");
        text = buildSelectedText().trim();
        if (!text) throw new Error("Pick at least one section to include.");
        // Pass only the protected terms that appear in the selected text.
        protectedTerms = getProtectedTerms(text);
      }

      if (text.length > MAX_CHARS) {
        throw new Error(`Selected text is ${text.length.toLocaleString()} chars — max is ${MAX_CHARS.toLocaleString()}. Deselect some sections or shorten the text.`);
      }

      if (isReduceMode) {
        result = await callApi("/api/plagiarism/reduce", {
          json: { text, provider, protected_terms: protectedTerms },
        });
        showReduceResult(result);
        setStatus("Rewrite complete.", "success");
      } else {
        result = await callApi("/api/plagiarism/check", { json: { text, provider } });
        if (docAnalysis && docAnalysis.filename) {
          result.filename = docAnalysis.filename;
        }
        if (protectedTerms.length) {
          result.protected_terms_count = protectedTerms.length;
        }
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
    const host = document.querySelector(".pm-surface-card");
    if (!host) return;
    const original = (result.original_text || "").trim();
    const rewritten = (result.rewritten_text || "").trim();
    const missing = Array.isArray(result.preserved_terms_missing) ? result.preserved_terms_missing : [];
    const protectedCount = result.protected_terms_count || 0;
    const protectedNote = protectedCount
      ? `<span style="color:var(--pm-text-soft);"> · ${protectedCount} protected terms passed in</span>`
      : "";
    const missingBlock = missing.length
      ? `<div class="pm-status is-error" style="display:block; margin-top:12px;" data-testid="text-missing-terms">
           ⚠ ${missing.length} protected term${missing.length === 1 ? "" : "s"} were not found in the rewrite — review carefully:
           <code style="display:block; margin-top:6px; font-size:12px;">${missing.slice(0, 20).map(escapeHtml).join(" · ")}</code>
         </div>`
      : "";
    host.innerHTML = `
      <h2>Rewritten draft</h2>
      <p class="pm-help">${escapeHtml(result.notes || "Rewrite complete.")} <span style="color:var(--pm-text-soft);">· ${result.changes_made || 0} edits · engine: ${escapeHtml(result.model_used || "auto")}${protectedNote}</span></p>
      ${missingBlock}
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

  // Pre-fill textarea if user came back from a "Check the rewrite" hop.
  const prefill = sessionStorage.getItem("pm:prefillText");
  if (prefill) {
    textarea.value = prefill;
    sessionStorage.removeItem("pm:prefillText");
    updateCounter();
  }
})();
