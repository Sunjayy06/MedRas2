/* ============================================================
   Proposal Writing Module — Step 4: Outline (upload + sections)
   ============================================================ */
(function () {
  "use strict";

  var STORAGE_KEY = "medras.proposal.intake";

  // Status thresholds (chars of trimmed content)
  var THRESHOLD_FULL = 200;   // ≥ FULL  → green
  var THRESHOLD_SHORT = 1;    // ≥ SHORT → amber, else red

  // ===================== State =====================
  var format = null;          // {id,label,sections:[{name,included}], ...}
  var includedSections = [];  // [name, name, ...]
  var sectionContent = {};    // {name: text}
  var queuedFiles = [];       // [File, ...]
  var openSet = {};           // {name: true}
  var SAMPLE_SIZE_RE = /sample\s*size|statistical\s+(analysis|plan)/i;

  // ===================== DOM refs =====================
  var formatLabelEl, preflight, preYesBtn, preNoBtn, uploadCard, dropzone, fileInput,
      fileList, processBtn, processStatus, skipBtn, sectionsCard, accList,
      auditCard, auditList, progressBar, progressPct, nextBtn;

  // ===================== Storage helpers =====================
  function readState() {
    try { var raw = sessionStorage.getItem(STORAGE_KEY); return raw ? JSON.parse(raw) : {}; }
    catch (e) { return {}; }
  }
  function writeState(patch) {
    var cur = readState();
    var next = Object.assign({}, cur, patch);
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch (e) {}
    return next;
  }

  // ===================== Status helpers =====================
  function statusFor(text) {
    var len = (text || "").trim().length;
    if (len >= THRESHOLD_FULL) return "full";
    if (len >= THRESHOLD_SHORT) return "short";
    return "empty";
  }
  function statusIcon(s) {
    if (s === "full") return "✓";
    if (s === "short") return "·";
    return "✕";
  }
  function statusLabel(s) {
    if (s === "full") return "Looks complete";
    if (s === "short") return "A bit thin — expand it";
    return "Empty";
  }

  function isSampleSizeSection(name) { return SAMPLE_SIZE_RE.test(name || ""); }

  // ===================== Persistence =====================
  function persist() {
    var saved = readState();
    var prev = saved.outline || {};
    writeState({
      outline: Object.assign({}, prev, {
        sections: Object.assign({}, sectionContent),
        updatedAt: Date.now(),
      }),
    });
  }

  // ===================== Rendering — accordion =====================
  function renderAccordion() {
    accList.innerHTML = "";
    includedSections.forEach(function (name, idx) {
      var content = sectionContent[name] || "";
      var stat = statusFor(content);
      var open = !!openSet[name];

      var li = document.createElement("li");
      li.className = "prop-out-acc-item is-" + stat + (open ? " is-open" : "");
      li.dataset.section = name;

      // Header
      var head = document.createElement("button");
      head.type = "button";
      head.className = "prop-out-acc-head";
      head.setAttribute("aria-expanded", open ? "true" : "false");
      head.setAttribute("data-testid", "button-acc-head-" + idx);

      var iconWrap = document.createElement("span");
      iconWrap.className = "prop-out-acc-icon prop-out-acc-icon--" + stat;
      iconWrap.title = statusLabel(stat);
      iconWrap.textContent = statusIcon(stat);

      var num = document.createElement("span");
      num.className = "prop-out-acc-num";
      num.textContent = String(idx + 1);

      var nameEl = document.createElement("span");
      nameEl.className = "prop-out-acc-name";
      nameEl.textContent = name;

      var meta = document.createElement("span");
      meta.className = "prop-out-acc-meta";
      var len = (content || "").trim().length;
      meta.textContent = len ? (len + " chars") : "Empty";

      var chev = document.createElement("span");
      chev.className = "prop-out-acc-chev";
      chev.setAttribute("aria-hidden", "true");
      chev.textContent = open ? "▾" : "▸";

      head.appendChild(iconWrap);
      head.appendChild(num);
      head.appendChild(nameEl);
      head.appendChild(meta);
      head.appendChild(chev);

      head.addEventListener("click", function () {
        openSet[name] = !openSet[name];
        renderAccordion();
      });

      li.appendChild(head);

      // Body
      if (open) {
        var body = document.createElement("div");
        body.className = "prop-out-acc-body";

        var ta = document.createElement("textarea");
        ta.className = "prop-out-acc-textarea";
        ta.rows = 10;
        ta.placeholder = "Type the content for \"" + name + "\" here, or use the buttons below to import or auto-draft it.";
        ta.value = content;
        ta.setAttribute("data-testid", "textarea-section-" + idx);
        ta.addEventListener("input", function () {
          sectionContent[name] = ta.value;
          // Live update the header counter & status without rebuilding (minor)
          meta.textContent = ta.value.trim().length ? (ta.value.trim().length + " chars") : "Empty";
          var s2 = statusFor(ta.value);
          li.className = "prop-out-acc-item is-" + s2 + " is-open";
          iconWrap.className = "prop-out-acc-icon prop-out-acc-icon--" + s2;
          iconWrap.textContent = statusIcon(s2);
          iconWrap.title = statusLabel(s2);
        });
        ta.addEventListener("blur", function () {
          persist();
          renderAudit();
        });
        body.appendChild(ta);

        // Action buttons
        var actions = document.createElement("div");
        actions.className = "prop-out-acc-actions";

        // 1. Upload doc for this section
        var uploadLabel = document.createElement("label");
        uploadLabel.className = "prop-out-acc-btn";
        uploadLabel.setAttribute("data-testid", "button-section-upload-" + idx);
        uploadLabel.title = "Upload one document just for this section";
        uploadLabel.innerHTML = "📎 <span>Upload doc for this section</span>";
        var sInput = document.createElement("input");
        sInput.type = "file";
        sInput.accept = ".pdf,.docx,.pptx,.txt,.md";
        sInput.hidden = true;
        sInput.addEventListener("change", function () {
          if (sInput.files && sInput.files[0]) {
            uploadForSection(name, sInput.files[0], ta, meta, iconWrap, li);
            sInput.value = "";
          }
        });
        uploadLabel.appendChild(sInput);
        actions.appendChild(uploadLabel);

        // 2. Sample Size Calculator (only on sample-size sections)
        if (isSampleSizeSection(name)) {
          var ssBtn = document.createElement("a");
          ssBtn.className = "prop-out-acc-btn";
          ssBtn.href = "/sample-size.html";
          ssBtn.target = "_blank";
          ssBtn.rel = "noopener";
          ssBtn.setAttribute("data-testid", "button-section-samplesize-" + idx);
          ssBtn.title = "Open the Sample Size Calculator in a new tab";
          ssBtn.innerHTML = "🧮 <span>Use Sample Size Calculator</span>";
          actions.appendChild(ssBtn);
        }

        // 3. Study Builder (placeholder — coming soon)
        var sbBtn = document.createElement("button");
        sbBtn.type = "button";
        sbBtn.className = "prop-out-acc-btn is-disabled";
        sbBtn.disabled = true;
        sbBtn.title = "Study Builder is coming soon";
        sbBtn.setAttribute("data-testid", "button-section-studybuilder-" + idx);
        sbBtn.innerHTML = "🛠 <span>Use Study Builder</span> <em>· soon</em>";
        actions.appendChild(sbBtn);

        body.appendChild(actions);
        li.appendChild(body);
      }

      accList.appendChild(li);
    });
  }

  // ===================== Rendering — audit =====================
  function renderAudit() {
    auditList.innerHTML = "";
    var fullCount = 0;
    var total = includedSections.length || 1;

    includedSections.forEach(function (name, idx) {
      var content = sectionContent[name] || "";
      var stat = statusFor(content);
      if (stat === "full") fullCount += 1;
      // Partial counts as half for the percentage
      // (so a half-finished outline isn't 0%)
      // Done below.

      var li = document.createElement("li");
      li.className = "prop-out-audit-item is-" + stat;
      li.setAttribute("data-testid", "audit-row-" + idx);

      var badge = document.createElement("span");
      badge.className = "prop-out-audit-badge prop-out-audit-badge--" + stat;
      badge.textContent = statusIcon(stat);

      var nm = document.createElement("span");
      nm.className = "prop-out-audit-name";
      nm.textContent = (idx + 1) + ". " + name;

      var label = document.createElement("span");
      label.className = "prop-out-audit-label";
      label.textContent = statusLabel(stat);

      li.appendChild(badge);
      li.appendChild(nm);
      li.appendChild(label);

      if (stat === "empty") {
        var genBtn = document.createElement("button");
        genBtn.type = "button";
        genBtn.className = "prop-out-audit-gen";
        genBtn.setAttribute("data-testid", "button-generate-" + idx);
        genBtn.textContent = "✨ Let MedRAS Generate This";
        genBtn.addEventListener("click", function () { generateSection(name, genBtn); });
        li.appendChild(genBtn);
      }

      auditList.appendChild(li);
    });

    // Half-credit for short sections so progress feels honest
    var partial = 0;
    includedSections.forEach(function (n) {
      var s = statusFor(sectionContent[n] || "");
      if (s === "short") partial += 0.5;
    });
    var pct = Math.round(((fullCount + partial) / total) * 100);
    pct = Math.max(0, Math.min(100, pct));
    progressBar.style.width = pct + "%";
    progressBar.dataset.level = pct >= 80 ? "high" : pct >= 40 ? "mid" : "low";
    progressPct.textContent = pct + "%";
  }

  // ===================== Bulk upload flow =====================
  function humanSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function renderQueuedFiles() {
    fileList.innerHTML = "";
    queuedFiles.forEach(function (f, i) {
      var li = document.createElement("li");
      li.className = "prop-out-fileitem";
      li.setAttribute("data-testid", "file-row-" + i);

      var nm = document.createElement("span");
      nm.className = "prop-out-fileitem-name";
      nm.textContent = f.name;

      var sz = document.createElement("span");
      sz.className = "prop-out-fileitem-size";
      sz.textContent = humanSize(f.size);

      var rm = document.createElement("button");
      rm.type = "button";
      rm.className = "prop-out-fileitem-rm";
      rm.title = "Remove file";
      rm.setAttribute("aria-label", "Remove " + f.name);
      rm.setAttribute("data-testid", "button-remove-file-" + i);
      rm.textContent = "✕";
      rm.addEventListener("click", function () {
        queuedFiles.splice(i, 1);
        renderQueuedFiles();
      });

      li.appendChild(nm);
      li.appendChild(sz);
      li.appendChild(rm);
      fileList.appendChild(li);
    });
    processBtn.disabled = queuedFiles.length === 0;
  }

  function addFiles(fileLikeList) {
    var allowed = /\.(pdf|docx|pptx|txt|md)$/i;
    var added = 0;
    Array.prototype.forEach.call(fileLikeList || [], function (f) {
      if (queuedFiles.length >= 10) return;
      if (!allowed.test(f.name || "")) return;
      // de-dupe by name+size
      var dup = queuedFiles.some(function (g) { return g.name === f.name && g.size === f.size; });
      if (dup) return;
      queuedFiles.push(f);
      added += 1;
    });
    renderQueuedFiles();
    return added;
  }

  function setProcessStatus(msg, kind) {
    processStatus.textContent = msg || "";
    processStatus.dataset.kind = kind || "";
  }

  function processBulk() {
    if (window.MedrasProposalState) window.MedrasProposalState.setBusy(true);
    if (!queuedFiles.length) return;
    processBtn.disabled = true;
    setProcessStatus("Reading " + queuedFiles.length + " file(s) and asking AI to slot the content into your sections — this can take 20-40 seconds…", "info");

    var fd = new FormData();
    queuedFiles.forEach(function (f) { fd.append("files", f, f.name); });
    fd.append("sections", JSON.stringify(includedSections));
    fd.append("format_label", format.label || "");

    fetch("/api/outline/extract", { method: "POST", body: fd })
      .then(function (r) {
        return r.json().then(function (j) { return { ok: r.ok, status: r.status, body: j }; });
      })
      .then(function (res) {
        if (!res.ok) {
          var msg = (res.body && res.body.detail) ? res.body.detail : ("Request failed (" + res.status + ").");
          setProcessStatus("⚠ " + msg, "error");
          processBtn.disabled = false; if (window.MedrasProposalState) window.MedrasProposalState.setBusy(false);
          return;
        }
        var by = (res.body && res.body.by_section) || {};
        var auto = res.body && res.body.auto_filled || 0;
        var fileMsgs = (res.body && res.body.files) || [];
        // Merge: never overwrite content the user has already typed
        includedSections.forEach(function (name) {
          var incoming = (by[name] || "").trim();
          if (!incoming) return;
          var existing = (sectionContent[name] || "").trim();
          if (existing) return;        // don't overwrite user's own work
          sectionContent[name] = incoming;
          openSet[name] = false;       // collapse so the audit reads as full
        });
        var skipped = fileMsgs.filter(function (f) { return !f.ok; });
        var summary = "✓ Auto-filled " + auto + " of " + includedSections.length + " sections from " + fileMsgs.filter(function (f) { return f.ok; }).length + " file(s).";
        if (skipped.length) {
          summary += " " + skipped.length + " file(s) skipped: " + skipped.map(function (f) { return f.name + " (" + (f.error || "unknown") + ")"; }).join("; ") + ".";
        }
        setProcessStatus(summary, "ok");
        queuedFiles = [];
        renderQueuedFiles();
        persist();
        renderAccordion();
        renderAudit();
      })
      .catch(function (err) {
        setProcessStatus("⚠ Network error: " + (err && err.message ? err.message : err), "error");
        processBtn.disabled = queuedFiles.length === 0;
        if (window.MedrasProposalState) window.MedrasProposalState.setBusy(false);
      });
  }

  // ===================== Per-section upload =====================
  function uploadForSection(name, file, textareaEl, metaEl, iconEl, liEl) {
    var prevValue = textareaEl.value;
    textareaEl.disabled = true;
    var wasMeta = metaEl.textContent;
    metaEl.textContent = "Uploading…";

    var fd = new FormData();
    fd.append("file", file, file.name);
    fd.append("section_name", name);

    fetch("/api/outline/extract-section", { method: "POST", body: fd })
      .then(function (r) {
        return r.json().then(function (j) { return { ok: r.ok, status: r.status, body: j }; });
      })
      .then(function (res) {
        textareaEl.disabled = false;
        if (!res.ok) {
          var msg = (res.body && res.body.detail) ? res.body.detail : ("Request failed (" + res.status + ").");
          metaEl.textContent = wasMeta;
          window.alert("Could not extract that file:\n\n" + msg);
          return;
        }
        var incoming = (res.body && res.body.text) || "";
        if (!incoming.trim()) {
          metaEl.textContent = wasMeta;
          window.alert("That file didn't contain any readable text.");
          return;
        }
        var merged = prevValue.trim() ? (prevValue.trim() + "\n\n" + incoming) : incoming;
        textareaEl.value = merged;
        sectionContent[name] = merged;
        var s = statusFor(merged);
        liEl.className = "prop-out-acc-item is-" + s + " is-open";
        iconEl.className = "prop-out-acc-icon prop-out-acc-icon--" + s;
        iconEl.textContent = statusIcon(s);
        iconEl.title = statusLabel(s);
        metaEl.textContent = merged.trim().length + " chars";
        persist();
        renderAudit();
      })
      .catch(function (err) {
        textareaEl.disabled = false;
        metaEl.textContent = wasMeta;
        window.alert("Network error uploading file: " + (err && err.message ? err.message : err));
      });
  }

  // ===================== Generate missing section =====================
  function generateSection(name, btnEl) {
    var origLabel = btnEl.textContent;
    btnEl.disabled = true;
    btnEl.textContent = "✨ Drafting… (10-30s)";

    var filledForCall = {};
    includedSections.forEach(function (n) {
      var c = (sectionContent[n] || "").trim();
      if (n !== name && c) filledForCall[n] = c;
    });

    fetch("/api/outline/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        section_name: name,
        format_label: format.label || "",
        filled: filledForCall,
      }),
    })
      .then(function (r) {
        return r.json().then(function (j) { return { ok: r.ok, status: r.status, body: j }; });
      })
      .then(function (res) {
        btnEl.disabled = false;
        btnEl.textContent = origLabel;
        if (!res.ok) {
          var msg = (res.body && res.body.detail) ? res.body.detail : ("Request failed (" + res.status + ").");
          window.alert("Could not generate that section:\n\n" + msg);
          return;
        }
        var draft = (res.body && res.body.text) || "";
        if (!draft.trim()) {
          window.alert("The model returned an empty draft. Try filling in a few more sections first so it has more to work from.");
          return;
        }
        sectionContent[name] = draft;
        openSet[name] = true;     // open so the user can review the draft
        persist();
        renderAccordion();
        renderAudit();
      })
      .catch(function (err) {
        btnEl.disabled = false;
        btnEl.textContent = origLabel;
        window.alert("Network error: " + (err && err.message ? err.message : err));
      });
  }

  // ===================== Flow control =====================
  function showSectionsAndAudit() {
    sectionsCard.hidden = false;
    auditCard.hidden = false;
    renderAccordion();
    renderAudit();
  }

  function showUploadCard() {
    preflight.hidden = true;
    uploadCard.hidden = false;
    showSectionsAndAudit();
  }

  function startFresh() {
    preflight.hidden = true;
    uploadCard.hidden = true;
    showSectionsAndAudit();
  }

  // ===================== Init =====================
  function init() {
    formatLabelEl = document.getElementById("prop-out-format-label");
    preflight = document.getElementById("prop-out-preflight");
    preYesBtn = document.getElementById("prop-out-pre-yes");
    preNoBtn = document.getElementById("prop-out-pre-no");
    uploadCard = document.getElementById("prop-out-upload");
    dropzone = document.getElementById("prop-out-dropzone");
    fileInput = document.getElementById("prop-out-files");
    fileList = document.getElementById("prop-out-filelist");
    processBtn = document.getElementById("prop-out-process");
    processStatus = document.getElementById("prop-out-process-status");
    skipBtn = document.getElementById("prop-out-skip-upload");
    sectionsCard = document.getElementById("prop-out-sections");
    accList = document.getElementById("prop-out-acc");
    auditCard = document.getElementById("prop-out-audit");
    auditList = document.getElementById("prop-out-audit-list");
    progressBar = document.getElementById("prop-out-progress-bar");
    progressPct = document.getElementById("prop-out-progress-pct");
    nextBtn = document.getElementById("prop-out-next");

    // Gates
    var saved = readState();
    if (!saved.role) { window.location.replace("/proposal-module/role.html"); return; }
    if (!saved.langMode) { window.location.replace("/proposal-module/language.html"); return; }
    if (!saved.format || !Array.isArray(saved.format.sections) || !saved.format.sections.length) {
      window.location.replace("/proposal-module/format.html");
      return;
    }

    format = saved.format;
    includedSections = format.sections
      .filter(function (s) { return s && s.included !== false && s.name; })
      .map(function (s) { return s.name; });

    if (!includedSections.length) {
      window.location.replace("/proposal-module/format.html");
      return;
    }

    formatLabelEl.textContent = format.label.split(" — ")[0];

    // Restore previously-saved outline content
    if (saved.outline && saved.outline.sections) {
      includedSections.forEach(function (n) {
        var v = saved.outline.sections[n];
        if (typeof v === "string") sectionContent[n] = v;
      });
    }
    includedSections.forEach(function (n) { if (!(n in sectionContent)) sectionContent[n] = ""; });

    // ---- Pre-flight buttons ----
    preYesBtn.addEventListener("click", showUploadCard);
    preNoBtn.addEventListener("click", startFresh);
    skipBtn.addEventListener("click", startFresh);

    // ---- Dropzone ----
    fileInput.addEventListener("change", function () {
      addFiles(fileInput.files);
      fileInput.value = "";
    });
    ["dragenter", "dragover"].forEach(function (ev) {
      dropzone.addEventListener(ev, function (e) {
        e.preventDefault(); e.stopPropagation();
        dropzone.classList.add("is-drag");
      });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      dropzone.addEventListener(ev, function (e) {
        e.preventDefault(); e.stopPropagation();
        dropzone.classList.remove("is-drag");
      });
    });
    dropzone.addEventListener("drop", function (e) {
      var dt = e.dataTransfer;
      if (dt && dt.files && dt.files.length) addFiles(dt.files);
    });

    processBtn.addEventListener("click", processBulk);

    // ---- Continue ----
    nextBtn.addEventListener("click", function () {
      persist();
      window.location.href = "/proposal-module/references.html";
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
