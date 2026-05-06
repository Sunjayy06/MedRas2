/* ============================================================
   Proposal Writing Module — Step 8: Download
   ============================================================
   Reads from sessionStorage:
     - medras.proposal.intake     (role, format, langMode, secondLangLabel, …)
     - medras.proposal.generated  (sections, sources, all_retrieved, domain)
     - medras.proposal.manual     (budget, timeline)
     - medras.proposal.titlepage  (this page's auto-saved title-page metadata)
     - medras.proposal.consent    (this page's auto-saved language picks +
                                   delivery-mode picker)

   Calls:
     POST /api/proposal/export/docx
     POST /api/proposal/export/pdf
     POST /api/proposal/export/zip
     POST /api/proposal/export/plaintext

   "Send to Plagiarism Checker" pre-fills the checker via a session-scoped
   handoff key (sessionStorage["medras.plagiarism.prefill"]).
   ============================================================ */
(function () {
  "use strict";

  var INTAKE_KEY   = "medras.proposal.intake";
  var RESULT_KEY   = "medras.proposal.generated";
  var MANUAL_KEY   = "medras.proposal.manual";
  var TITLE_KEY    = "medras.proposal.titlepage";
  var CONSENT_KEY  = "medras.proposal.consent";
  var PLAGIARISM_PREFILL_KEY = "medras.plagiarism.prefill";

  // Format ids that get the extended Indian-MD-thesis cover layout
  // (Phone, Email, year-of-residency, "Submitted in partial fulfilment of MD/MS
  // in [Specialty] under [University]", etc.). Mirrors the backend allow-list
  // in `app/services/proposal_export.py:_INDIAN_THESIS_FORMAT_IDS`.
  var INDIAN_THESIS_FORMAT_IDS = ["phd-syn", "md-ms-syn", "inst-diss"];

  // 11-language consent picker. English is mandatory. The other 10 are the
  // 8th-Schedule Indian languages most commonly required by IRB/IEC review
  // for participant-facing consent — Hindi, the four Dravidian languages
  // (Tamil, Telugu, Kannada, Malayalam), Marathi, Bengali, Gujarati,
  // Punjabi, and Odia.
  var CONSENT_LANGUAGES = [
    { code: "en", label: "English",   native: "English",   mandatory: true  },
    { code: "hi", label: "Hindi",     native: "हिन्दी"            },
    { code: "ta", label: "Tamil",     native: "தமிழ்"             },
    { code: "te", label: "Telugu",    native: "తెలుగు"            },
    { code: "kn", label: "Kannada",   native: "ಕನ್ನಡ"            },
    { code: "ml", label: "Malayalam", native: "മലയാളം"           },
    { code: "mr", label: "Marathi",   native: "मराठी"             },
    { code: "bn", label: "Bengali",   native: "বাংলা"             },
    { code: "gu", label: "Gujarati",  native: "ગુજરાતી"           },
    { code: "pa", label: "Punjabi",   native: "ਪੰਜਾਬੀ"           },
    { code: "or", label: "Odia",      native: "ଓଡ଼ିଆ"             },
  ];

  var ALL_KEYS = [
    INTAKE_KEY, RESULT_KEY, MANUAL_KEY, TITLE_KEY, CONSENT_KEY,
    "medras.proposal.topic",
  ];

  function $(id) { return document.getElementById(id); }
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function readJSON(key, fallback) {
    try { return JSON.parse(sessionStorage.getItem(key) || "null") || fallback; }
    catch (e) { return fallback; }
  }
  function writeJSON(key, val) {
    try { sessionStorage.setItem(key, JSON.stringify(val)); } catch (e) {}
  }

  // ---- title-page metadata ----
  function defaultTitleMeta() {
    return {
      institution: "", committee: "Institutional Research Committee",
      study_title: "", year: String(new Date().getFullYear()),
      degree: "", specialty: "", university: "", submission_date: "",
      pi:       { name: "", designation: "Principal Investigator", department: "",
                  year_of_residency: "", phone: "", email: "" },
      guide:    { name: "", designation: "Guide",    department: "", phone: "", email: "" },
      co_guide: { name: "", designation: "Co-Guide", department: "", phone: "", email: "" },
    };
  }
  function readTitleMeta() {
    var stored = readJSON(TITLE_KEY, null);
    var def = defaultTitleMeta();
    if (!stored) return def;
    // Shallow merge with defaults so newly-added fields don't break old saves.
    return {
      institution: stored.institution || def.institution,
      committee:   stored.committee   || def.committee,
      study_title: stored.study_title || def.study_title,
      year:        stored.year        || def.year,
      degree:      stored.degree      || def.degree,
      specialty:   stored.specialty   || def.specialty,
      university:  stored.university  || def.university,
      submission_date: stored.submission_date || def.submission_date,
      pi:       Object.assign({}, def.pi,       stored.pi       || {}),
      guide:    Object.assign({}, def.guide,    stored.guide    || {}),
      co_guide: Object.assign({}, def.co_guide, stored.co_guide || {}),
    };
  }
  function setNested(obj, dottedKey, value) {
    var parts = dottedKey.split(".");
    var cur = obj;
    for (var i = 0; i < parts.length - 1; i++) {
      if (!cur[parts[i]] || typeof cur[parts[i]] !== "object") cur[parts[i]] = {};
      cur = cur[parts[i]];
    }
    cur[parts[parts.length - 1]] = value;
  }
  function getNested(obj, dottedKey) {
    return dottedKey.split(".").reduce(function (acc, k) {
      return (acc == null ? undefined : acc[k]);
    }, obj);
  }

  // ---- consent state (languages + delivery) ----
  function defaultConsentState(intake) {
    // Pre-tick the language they picked back at Step 2 if it is in our grid.
    var picks = { en: true };
    var second = (intake && intake.secondLang || "").toLowerCase();
    var secondLabel = (intake && intake.secondLangLabel || "").toLowerCase();
    CONSENT_LANGUAGES.forEach(function (l) {
      if (l.code === "en") return;
      if (second && l.code === second) picks[l.code] = true;
      if (secondLabel && l.label.toLowerCase() === secondLabel) picks[l.code] = true;
    });
    return { picks: picks, delivery: "attached" };
  }
  function readConsentState(intake) {
    var stored = readJSON(CONSENT_KEY, null);
    var def = defaultConsentState(intake);
    if (!stored) return def;
    return {
      picks: Object.assign({ en: true }, stored.picks || {}, { en: true }),
      delivery: ["attached","separate","both"].indexOf(stored.delivery) >= 0
        ? stored.delivery : def.delivery,
    };
  }
  function writeConsentState(state) { writeJSON(CONSENT_KEY, state); }

  function selectedLanguages(consentState) {
    return CONSENT_LANGUAGES.filter(function (l) {
      return l.code === "en" || !!consentState.picks[l.code];
    }).map(function (l) { return { code: l.code, label: l.label }; });
  }

  // ---- format gating (Indian thesis vs everything else) ----
  function isIndianThesisFormat(intake) {
    var fid = ((intake.format || {}).id || "").toLowerCase();
    return INDIAN_THESIS_FORMAT_IDS.indexOf(fid) >= 0;
  }
  function applyFormatGating(intake) {
    var show = isIndianThesisFormat(intake);
    var els = document.querySelectorAll(".dl-thesis-only");
    Array.prototype.forEach.call(els, function (el) {
      el.hidden = !show;
    });
  }

  // ---- payload ----
  function buildPayload() {
    var intake = readJSON(INTAKE_KEY, {}) || {};
    var generated = readJSON(RESULT_KEY, null);
    if (!generated || !generated.sections) return null;
    var manual = readJSON(MANUAL_KEY, {}) || {};
    var titleMeta = readTitleMeta();
    if (!titleMeta.study_title) titleMeta.study_title = intake.topic || generated.topic || "";
    var consent = readConsentState(intake);
    return {
      intake: intake,
      sections: generated.sections,
      manual: manual,
      sources: generated.sources || [],
      title_meta: titleMeta,
      consent_languages: selectedLanguages(consent),
      consent_delivery: consent.delivery,
    };
  }

  // ---- summary card ----
  function renderSummary(payload) {
    var sections = payload.sections || {};
    var manual = payload.manual || {};
    var sectionCount = 0;
    ["background","literature_review","rationale","methods","statistical_plan","ethics","expected_outcomes"]
      .forEach(function (k) { if ((sections[k] || "").trim()) sectionCount++; });
    var manualCount = 0;
    if ((manual.budget   || "").trim()) manualCount++;
    if ((manual.timeline || "").trim()) manualCount++;
    var sourceCount = (payload.sources || []).length;
    var totalWords = 0;
    Object.keys(sections).forEach(function (k) {
      var s = (sections[k] || "").trim();
      if (s) totalWords += s.split(/\s+/).length;
    });
    if ((manual.budget   || "").trim()) totalWords += manual.budget.trim().split(/\s+/).length;
    if ((manual.timeline || "").trim()) totalWords += manual.timeline.trim().split(/\s+/).length;

    var tiles = [
      ["Sections drafted", sectionCount + " of 7"],
      ["Manual sections",  manualCount  + " of 2"],
      ["Cited sources",    String(sourceCount)],
      ["Approx. word count", totalWords.toLocaleString()],
    ];
    $("dl-summary").innerHTML = tiles.map(function (t) {
      return '<div class="dl-tile"><div class="dl-tile-label">' + escapeHtml(t[0]) + '</div>' +
             '<div class="dl-tile-value">' + escapeHtml(t[1]) + '</div></div>';
    }).join("");

    var langs = payload.consent_languages || [];
    $("dl-langs").innerHTML = langs.map(function (l) {
      return '<span class="dl-lang-pill" data-testid="pill-lang-' + escapeHtml(l.code) + '">' +
             escapeHtml(l.label) + '</span>';
    }).join("");
  }

  // ---- title-page form binding ----
  function bindTitleMetaForm() {
    var meta = readTitleMeta();
    var inputs = document.querySelectorAll("input[data-meta]");
    Array.prototype.forEach.call(inputs, function (input) {
      var key = input.getAttribute("data-meta");
      var val = getNested(meta, key);
      if (val != null) input.value = val;
      input.addEventListener("input", function () {
        var fresh = readTitleMeta();
        setNested(fresh, key, input.value);
        writeJSON(TITLE_KEY, fresh);
      });
    });
  }

  // ---- consent UI binding ----
  function bindConsentUI(intake) {
    var grid = $("dl-lang-grid");
    var consent = readConsentState(intake);
    grid.innerHTML = CONSENT_LANGUAGES.map(function (l) {
      var locked = !!l.mandatory;
      var checked = locked || !!consent.picks[l.code];
      return '<label class="dl-lang-cb' + (locked ? ' is-locked' : '') + '">' +
        '<input type="checkbox" value="' + escapeHtml(l.code) + '"' +
          ' data-testid="checkbox-lang-' + escapeHtml(l.code) + '"' +
          (checked ? ' checked' : '') + (locked ? ' disabled' : '') + ' />' +
        '<span class="dl-lang-cb-name">' + escapeHtml(l.label) + '</span>' +
        '<span class="dl-lang-cb-native">' + escapeHtml(l.native) + '</span>' +
        '</label>';
    }).join("");
    Array.prototype.forEach.call(grid.querySelectorAll('input[type="checkbox"]'), function (cb) {
      cb.addEventListener("change", function () {
        if (cb.disabled) return;
        var fresh = readConsentState(intake);
        if (cb.checked) fresh.picks[cb.value] = true; else delete fresh.picks[cb.value];
        fresh.picks.en = true;
        writeConsentState(fresh);
        // refresh summary pills so the user sees their selection reflected
        var p = buildPayload();
        if (p) renderSummary(p);
        updateDeliveryNote();
      });
    });

    var radios = document.querySelectorAll('input[name="dl-delivery"]');
    Array.prototype.forEach.call(radios, function (r) {
      r.checked = (r.value === consent.delivery);
      r.addEventListener("change", function () {
        if (!r.checked) return;
        var fresh = readConsentState(intake);
        fresh.delivery = r.value;
        writeConsentState(fresh);
        updateDeliveryNote();
      });
    });
    updateDeliveryNote();
  }

  function updateDeliveryNote() {
    var checked = document.querySelector('input[name="dl-delivery"]:checked');
    var mode = checked ? checked.value : "attached";
    var note = $("dl-delivery-note");
    if (!note) return;
    if (mode === "attached") {
      note.textContent = "Word and PDF buttons return a single file. The .zip option still bundles both.";
    } else if (mode === "separate") {
      note.textContent = "Use “Download Both (.zip)” to receive the consent-only file alongside the proposal — single-file Word/PDF buttons will omit the consent forms.";
    } else {
      note.textContent = "Use “Download Both (.zip)” to receive the consent-only file in addition to the proposal copy that already contains it.";
    }
  }

  // ---- status helpers ----
  function setStatus(kind, html) {
    var el = $("dl-status");
    el.className = "dl-status is-" + kind;
    el.innerHTML = html;
    el.classList.remove("gen-hidden");
  }
  function clearStatus() { $("dl-status").classList.add("gen-hidden"); }

  // ---- download flow ----
  function downloadBlob(blob, filename) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 0);
  }

  function safeFilename(stem, ext) {
    var base = (stem || "proposal").replace(/[^A-Za-z0-9._-]+/g, "_").slice(0, 60) || "proposal";
    return base + "." + ext;
  }

  async function postExport(endpoint, payload) {
    var resp = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      var msg = "Server returned " + resp.status;
      try { var j = await resp.json(); if (j.detail) msg = j.detail; } catch (e) {}
      throw new Error(msg);
    }
    return resp;
  }

  function disableAll(disabled) {
    ["dl-btn-docx","dl-btn-pdf","dl-btn-both","dl-btn-plag"].forEach(function (id) {
      var b = $(id); if (b) b.disabled = disabled;
    });
  }

  function showSuccessNew() { $("dl-btn-new").classList.remove("gen-hidden"); }

  async function runDownload(kind) {
    var payload = buildPayload();
    if (!payload) { setStatus("error", "No generated proposal found."); return; }
    var stem = (payload.title_meta && payload.title_meta.study_title) || "proposal";
    var endpoint, ext, label;
    if      (kind === "docx") { endpoint = "/api/proposal/export/docx"; ext = "docx"; label = "Word document"; }
    else if (kind === "pdf")  { endpoint = "/api/proposal/export/pdf";  ext = "pdf";  label = "PDF document"; }
    else                      { endpoint = "/api/proposal/export/zip";  ext = "zip";  label = "Word + PDF bundle"; }

    disableAll(true);
    setStatus("info", '<span class="dl-spinner"></span>Generating ' + escapeHtml(label) +
      ' (consent translation may take 20-40s the first time)…');
    try {
      var resp = await postExport(endpoint, payload);
      var blob = await resp.blob();
      downloadBlob(blob, safeFilename(stem, ext));
      setStatus("ok", "Downloaded " + escapeHtml(label) + " — check your downloads folder.");
      showSuccessNew();
    } catch (err) {
      setStatus("error", "Could not generate the file: " + escapeHtml(err.message));
    } finally {
      disableAll(false);
    }
  }

  async function sendToPlagiarismChecker() {
    var payload = buildPayload();
    if (!payload) { setStatus("error", "No generated proposal found."); return; }
    disableAll(true);
    setStatus("info", '<span class="dl-spinner"></span>Bundling proposal text for the Plagiarism Checker…');
    try {
      var resp = await postExport("/api/proposal/export/plaintext", payload);
      var data = await resp.json();
      if (!data || typeof data.text !== "string" || !data.text.trim()) {
        throw new Error("Server returned no text.");
      }
      try {
        sessionStorage.setItem(PLAGIARISM_PREFILL_KEY, JSON.stringify({
          text: data.text,
          source: "proposal-writing-module",
          title: (payload.title_meta && payload.title_meta.study_title) || "",
          createdAt: new Date().toISOString(),
        }));
      } catch (e) {
        throw new Error("Could not stage text in session storage (" + e.message + ").");
      }
      setStatus("ok", "Text staged. Opening the Plagiarism Checker…");
      setTimeout(function () { window.location.href = "/plagiarism-module/checker.html"; }, 400);
    } catch (err) {
      setStatus("error", "Could not stage for plagiarism checker: " + escapeHtml(err.message));
      disableAll(false);
    }
  }

  function startNewProposal() {
    if (!confirm("Start a new proposal? This will clear the current draft from your browser session.")) return;
    ALL_KEYS.forEach(function (k) {
      try { sessionStorage.removeItem(k); } catch (e) {}
      try { localStorage.removeItem(k); } catch (e) {}
    });
    window.location.href = "/proposal-module/role.html";
  }

  // ---- init ----
  function init() {
    var generated = readJSON(RESULT_KEY, null);
    if (!generated || !generated.sections) {
      $("dl-empty").classList.remove("gen-hidden");
      return;
    }
    ["dl-summary-card","dl-meta-card","dl-consent-card","dl-actions-card","dl-handoff-card"].forEach(function (id) {
      var el = $(id); if (el) el.classList.remove("gen-hidden");
    });

    var intake = readJSON(INTAKE_KEY, {}) || {};
    applyFormatGating(intake);
    bindTitleMetaForm();
    bindConsentUI(intake);

    var payload = buildPayload();
    if (payload) renderSummary(payload);

    $("dl-btn-docx").addEventListener("click", function () { runDownload("docx"); });
    $("dl-btn-pdf" ).addEventListener("click", function () { runDownload("pdf");  });
    $("dl-btn-both").addEventListener("click", function () { runDownload("zip");  });
    $("dl-btn-plag").addEventListener("click", sendToPlagiarismChecker);
    $("dl-btn-new" ).addEventListener("click", startNewProposal);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
