/* Intake flow for the plagiarism reducer.
 *
 * Three steps:
 *   1) User picks "with report" or "without report"
 *   2A) Upload original + plagiarism report + select software
 *   2B) Upload single document
 *   3) → reduce-results.html (existing job-polling pipeline)
 *
 * Output handoff matches the existing sessionStorage contract that
 * reduce-results.js already understands:
 *
 *   sessionStorage["pm:reduceInput"] = JSON.stringify({
 *     sections: [{label, text}, ...],     // from /analyze-file
 *     protected_terms: [...],
 *     filename, title,
 *     report: { software, flagged_map }   // ONLY for Path A
 *   })
 *
 * The new "report" field is optional — Path B simply omits it and the
 * results page behaves exactly as before.
 */
(function () {
  "use strict";

  const INPUT_KEY = "pm:reduceInput";
  const $ = (s) => document.querySelector(s);

  // ---------- Step navigation ----------
  function showStep(n) {
    document.querySelectorAll(".pm-intake-step").forEach((el) => el.classList.add("is-hidden"));
    const target = document.getElementById("pm-step-" + n);
    if (target) target.classList.remove("is-hidden");
    // Stepper highlight: 2a + 2b both count as step 2.
    const idx = (n === "2a" || n === "2b") ? 2 : (n === "1" ? 1 : 3);
    document.querySelectorAll(".pm-stepper-item").forEach((el) => {
      const step = parseInt(el.dataset.step, 10);
      el.classList.toggle("is-active", step === idx);
      el.classList.toggle("is-done", step < idx);
    });
    // Scroll-to-top so users see the new step's heading; smooth on
    // desktop, instant on reduced-motion.
    try { window.scrollTo({ top: 0, behavior: "smooth" }); } catch (_) { window.scrollTo(0, 0); }
  }

  // Step 1 → Step 2 routing
  $("#pm-choice-with").addEventListener("click", () => showStep("2a"));
  $("#pm-choice-without").addEventListener("click", () => showStep("2b"));

  // Back buttons
  document.querySelectorAll("[data-back-to]").forEach((b) => {
    b.addEventListener("click", () => showStep(b.dataset.backTo));
  });

  // ---------- Dropzone wiring (factored — used 3× below) ----------
  // Returns a getter that yields the currently-picked File or null.
  function wireDropzone(zoneId, inputId, fileLabelId, accept, onChange) {
    const zone = document.getElementById(zoneId);
    const input = document.getElementById(inputId);
    const fileLabel = document.getElementById(fileLabelId);
    let current = null;

    function setFile(f) {
      current = f;
      if (f) {
        const sz = (f.size / (1024 * 1024)).toFixed(2);
        fileLabel.textContent = `📎 ${f.name} (${sz} MB)`;
        fileLabel.classList.add("is-set");
      } else {
        fileLabel.textContent = "";
        fileLabel.classList.remove("is-set");
      }
      if (onChange) onChange(current);
    }

    function pick(f) {
      if (!f) return;
      const ext = (f.name.split(".").pop() || "").toLowerCase();
      const allowed = accept.map((a) => a.replace(".", "").toLowerCase());
      if (!allowed.includes(ext)) {
        alert(`Unsupported file type ".${ext}". Allowed: ${accept.join(", ")}`);
        return;
      }
      setFile(f);
    }

    zone.addEventListener("click", () => input.click());
    zone.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
    });
    input.addEventListener("change", () => pick(input.files && input.files[0]));

    ["dragenter", "dragover"].forEach((ev) => {
      zone.addEventListener(ev, (e) => {
        e.preventDefault(); e.stopPropagation();
        zone.classList.add("is-dragging");
      });
    });
    ["dragleave", "drop"].forEach((ev) => {
      zone.addEventListener(ev, (e) => {
        e.preventDefault(); e.stopPropagation();
        zone.classList.remove("is-dragging");
      });
    });
    zone.addEventListener("drop", (e) => {
      const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) pick(f);
    });

    return () => current;
  }

  // ---------- Path A — with report ----------
  const analyseBoth = $("#pm-analyse-both");
  const analyseBothLabel = $("#pm-analyse-both-label");
  const stepAErr = $("#pm-step2a-error");

  const getOriginalA = wireDropzone(
    "pm-drop-original", "pm-file-original", "pm-drop-original-file",
    [".pdf", ".docx"], updateAnalyseBothEnabled,
  );
  const getReportA = wireDropzone(
    "pm-drop-report", "pm-file-report", "pm-drop-report-file",
    [".pdf", ".docx", ".txt", ".text"], updateAnalyseBothEnabled,
  );

  function updateAnalyseBothEnabled() {
    analyseBoth.disabled = !(getOriginalA() && getReportA());
  }

  analyseBoth.addEventListener("click", async () => {
    const orig = getOriginalA();
    const report = getReportA();
    const software = $("#pm-software").value || "Other";
    if (!orig || !report) return;

    stepAErr.classList.add("is-hidden");
    analyseBoth.disabled = true;
    analyseBothLabel.textContent = "Reading your document…";

    try {
      // Step 1: original document → /analyze-file (extracts sections)
      const docFd = new FormData();
      docFd.append("file", orig);
      const docRes = await fetch("/api/plagiarism/analyze-file", { method: "POST", body: docFd });
      const docJson = await docRes.json().catch(() => ({}));
      if (!docRes.ok) throw new Error(docJson.detail || `Analyse failed (HTTP ${docRes.status})`);

      analyseBothLabel.textContent = "Reading your plagiarism report…";

      // Step 2: report → /parse-report (extracts flagged-sections map)
      const repFd = new FormData();
      repFd.append("file", report);
      repFd.append("software", software);
      const repRes = await fetch("/api/plagiarism/parse-report", { method: "POST", body: repFd });
      const repJson = await repRes.json().catch(() => ({}));
      if (!repRes.ok) throw new Error(repJson.detail || `Report parse failed (HTTP ${repRes.status})`);

      // Build the same shape reduce-results.js already expects, plus
      // optional `report` metadata.
      const sections = buildSectionsFromAnalyze(docJson);
      const protectedTerms = collectProtectedTerms(docJson.extracted_text || "");

      const payload = {
        sections,
        protected_terms: protectedTerms,
        filename: docJson.filename || orig.name,
        title: stripExtension(docJson.filename || orig.name) || "Rewritten document",
        report: {
          software: repJson.software || software,
          flagged_map: repJson.flagged_map || {},
          summary: repJson.summary || null,
          parsed_section_count: repJson.parsed_section_count || 0,
        },
      };
      sessionStorage.setItem(INPUT_KEY, JSON.stringify(payload));
      window.location.href = "/plagiarism-module/reduce-results.html";
    } catch (err) {
      stepAErr.textContent = (err && err.message) ? err.message : "Something went wrong.";
      stepAErr.classList.remove("is-hidden");
      analyseBoth.disabled = false;
      analyseBothLabel.textContent = "Analyse Both Files";
    }
  });

  // ---------- Path B — without report ----------
  const analyseDirect = $("#pm-analyse-direct");
  const analyseDirectLabel = $("#pm-analyse-direct-label");
  const stepBErr = $("#pm-step2b-error");

  const getOriginalB = wireDropzone(
    "pm-drop-direct", "pm-file-direct", "pm-drop-direct-file",
    [".pdf", ".docx"], (f) => { analyseDirect.disabled = !f; },
  );

  analyseDirect.addEventListener("click", async () => {
    const f = getOriginalB();
    if (!f) return;

    stepBErr.classList.add("is-hidden");
    analyseDirect.disabled = true;
    analyseDirectLabel.textContent = "Reading your document…";

    try {
      const fd = new FormData();
      fd.append("file", f);
      const res = await fetch("/api/plagiarism/analyze-file", { method: "POST", body: fd });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || `Analyse failed (HTTP ${res.status})`);

      const sections = buildSectionsFromAnalyze(json);
      const protectedTerms = collectProtectedTerms(json.extracted_text || "");

      const payload = {
        sections,
        protected_terms: protectedTerms,
        filename: json.filename || f.name,
        title: stripExtension(json.filename || f.name) || "Rewritten document",
        // No `report` field → Path B behaviour on the results page.
      };
      sessionStorage.setItem(INPUT_KEY, JSON.stringify(payload));
      window.location.href = "/plagiarism-module/reduce-results.html";
    } catch (err) {
      stepBErr.textContent = (err && err.message) ? err.message : "Something went wrong.";
      stepBErr.classList.remove("is-hidden");
      analyseDirect.disabled = false;
      analyseDirectLabel.textContent = "Analyse My Document";
    }
  });

  // ---------- Helpers ----------
  // Slice the analyse-file response (which already gave us a section
  // breakdown by start_line + label) into the [{label, text}] shape
  // reduce-results expects. Mirrors checker.js#buildSelectedSections,
  // minus the "user picked a subset" branching.
  function buildSectionsFromAnalyze(doc) {
    const text = doc.extracted_text || "";
    const sections = (doc.sections || []).slice();
    if (!sections.length) {
      return [{ label: "Body", text }];
    }
    const lines = text.split(/\r?\n/);
    sections.sort((a, b) => (a.start_line || 0) - (b.start_line || 0));

    const out = [];
    for (let i = 0; i < sections.length; i++) {
      const s = sections[i];
      const start = Math.max(0, s.start_line || 0);
      const end = (i + 1 < sections.length)
        ? Math.max(start, sections[i + 1].start_line || start)
        : lines.length;
      let body = lines.slice(start, end).join("\n");
      // Drop the heading line itself (mirrors checker.js behaviour) so
      // we don't feed "Introduction" back to the rewriter as content.
      if (s.label && body.split("\n", 1)[0].trim().toLowerCase().includes(s.label.toLowerCase())) {
        body = body.split("\n").slice(1).join("\n");
      }
      out.push({ label: s.label || `Section ${i + 1}`, text: body });
    }
    return out;
  }

  // Lightweight protected-terms extraction — anything that looks like
  // a number, citation, or all-caps acronym. The rewriter does its
  // own validation so this is a hint, not a contract.
  function collectProtectedTerms(text) {
    if (!text) return [];
    const set = new Set();
    // Numbers with units / decimals / percentages
    (text.match(/\b\d+(?:[.,]\d+)?\s*(?:%|mg|kg|ml|µg|µl|n=|p=|p<|p>)?[a-zA-Z]*\b/g) || [])
      .forEach((m) => { const t = m.trim(); if (t.length >= 2 && t.length <= 40) set.add(t); });
    // Citations like (Smith, 2020) / [1]
    (text.match(/\([A-Z][a-zA-Z\-]+(?:\s+et\s+al\.?)?,?\s*\d{4}\)/g) || []).forEach((m) => set.add(m));
    (text.match(/\[\d+(?:[-,\s]?\d+)*\]/g) || []).forEach((m) => set.add(m));
    // Acronyms (3-8 caps)
    (text.match(/\b[A-Z]{3,8}\b/g) || []).forEach((m) => set.add(m));
    // Cap to keep payload small.
    return Array.from(set).slice(0, 200);
  }

  function stripExtension(name) {
    if (!name) return "";
    const i = name.lastIndexOf(".");
    return i > 0 ? name.slice(0, i) : name;
  }
})();
