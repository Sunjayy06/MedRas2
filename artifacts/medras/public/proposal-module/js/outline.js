/* ============================================================
   Proposal Writing Module — Step 4: Outline (upload + sections)
   ============================================================
   Sections list still renders inline, but clicking a row opens a
   centred modal popup with: a focused textarea, helper buttons
   (per-section upload / Sample Size Calculator / Study Builder),
   and — on sample-size sections — a live formula preview that
   substitutes numbers parsed from the textarea.
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
  var SAMPLE_SIZE_RE = /sample\s*size|statistical\s+(analysis|plan)/i;

  // Modal state
  var modalSection = null;          // currently-edited section name (or null)
  var modalOriginalValue = "";      // value when modal opened (for Cancel)
  var modalDesign = "single_proportion";

  // ===================== DOM refs =====================
  var formatLabelEl, preflight, preYesBtn, preNoBtn, uploadCard, dropzone, fileInput,
      fileList, processBtn, processStatus, skipBtn, sectionsCard, accList,
      auditCard, auditList, progressBar, progressPct, nextBtn,
      modalEl, modalTitle, modalNum, modalTextarea, modalMeta, modalActions,
      modalSaveBtn, modalCancelBtn, modalCloseBtn, modalSsPanel,
      modalSsFormula, modalSsSub, modalSsResult, modalSsDesignSel;

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

  // ===================== Rendering — section list =====================
  function renderAccordion() {
    accList.innerHTML = "";
    includedSections.forEach(function (name, idx) {
      var content = sectionContent[name] || "";
      var stat = statusFor(content);

      var li = document.createElement("li");
      li.className = "prop-out-acc-item is-" + stat;
      li.dataset.section = name;

      var head = document.createElement("button");
      head.type = "button";
      head.className = "prop-out-acc-head";
      head.setAttribute("data-testid", "button-acc-head-" + idx);
      head.title = "Click to open in editor";

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
      chev.textContent = "✎";

      head.appendChild(iconWrap);
      head.appendChild(num);
      head.appendChild(nameEl);
      head.appendChild(meta);
      head.appendChild(chev);

      head.addEventListener("click", function () { openModal(name); });

      li.appendChild(head);
      accList.appendChild(li);
    });
  }

  // ===================== Modal — open / close =====================
  function openModal(name) {
    modalSection = name;
    var content = sectionContent[name] || "";
    modalOriginalValue = content;

    var idx = includedSections.indexOf(name);
    modalNum.textContent = String(idx + 1);
    modalTitle.textContent = name;
    modalTextarea.value = content;
    updateModalMeta();

    renderModalActions(name);

    // Sample-size formula panel
    if (isSampleSizeSection(name)) {
      modalSsPanel.hidden = false;
      modalSsDesignSel.value = modalDesign;
      renderSampleSizeFormula();
    } else {
      modalSsPanel.hidden = true;
    }

    modalEl.hidden = false;
    document.body.style.overflow = "hidden";
    setTimeout(function () { modalTextarea.focus(); }, 30);
  }

  function closeModal(save) {
    if (modalSection == null) return;
    if (save) {
      sectionContent[modalSection] = modalTextarea.value;
      persist();
      renderAccordion();
      renderAudit();
    } else {
      // discard — restore original
      sectionContent[modalSection] = modalOriginalValue;
    }
    modalSection = null;
    modalEl.hidden = true;
    document.body.style.overflow = "";
  }

  function updateModalMeta() {
    var len = (modalTextarea.value || "").trim().length;
    var s = statusFor(modalTextarea.value);
    modalMeta.textContent = (len ? (len + " chars · ") : "Empty · ") + statusLabel(s);
    modalMeta.className = "prop-modal-meta is-" + s;
  }

  function renderModalActions(name) {
    modalActions.innerHTML = "";

    // 1. Upload doc for this section
    var uploadLabel = document.createElement("label");
    uploadLabel.className = "prop-out-acc-btn";
    uploadLabel.setAttribute("data-testid", "button-modal-upload");
    uploadLabel.title = "Upload one document just for this section";
    uploadLabel.innerHTML = "📎 <span>Upload doc for this section</span>";
    var sInput = document.createElement("input");
    sInput.type = "file";
    sInput.accept = ".pdf,.docx,.pptx,.txt,.md";
    sInput.hidden = true;
    sInput.addEventListener("change", function () {
      if (sInput.files && sInput.files[0]) {
        uploadForSectionInModal(name, sInput.files[0]);
        sInput.value = "";
      }
    });
    uploadLabel.appendChild(sInput);
    modalActions.appendChild(uploadLabel);

    // 2. Sample Size Calculator (only on sample-size sections)
    if (isSampleSizeSection(name)) {
      var ssBtn = document.createElement("a");
      ssBtn.className = "prop-out-acc-btn";
      ssBtn.href = "/sample-size.html";
      ssBtn.target = "_blank";
      ssBtn.rel = "noopener";
      ssBtn.setAttribute("data-testid", "button-modal-samplesize");
      ssBtn.title = "Open the Sample Size Calculator in a new tab";
      ssBtn.innerHTML = "🧮 <span>Use Sample Size Calculator</span>";
      modalActions.appendChild(ssBtn);
    }

    // 3. Study Builder — soft handoff (the page lives on the MedRAS home)
    var sbBtn = document.createElement("a");
    sbBtn.className = "prop-out-acc-btn";
    sbBtn.href = "/#study-builder";
    sbBtn.target = "_blank";
    sbBtn.rel = "noopener";
    sbBtn.setAttribute("data-testid", "button-modal-studybuilder");
    sbBtn.title = "Open the Study Builder in a new tab";
    sbBtn.innerHTML = "🛠 <span>Use Study Builder</span>";
    modalActions.appendChild(sbBtn);
  }

  // ===================== Sample-size formula preview =====================
  // Parse free-text values for common stats parameters. Returns a {sym: num}
  // map. Accepts forms like "p = 0.5", "p=0.5", "Z α = 1.96", "power = 80%",
  // "σ = 1.2", "alpha = 0.05".
  function parseStatValues(text) {
    if (!text) return {};
    var out = {};
    var lower = text.toLowerCase();

    function find(re, key, normalizer) {
      var m = re.exec(lower);
      if (!m) return;
      var raw = m[m.length - 1];
      var num = parseFloat(raw);
      if (isNaN(num)) return;
      out[key] = normalizer ? normalizer(num, raw) : num;
    }

    // Convert percentages "50%" → 0.5 only if value > 1.
    function maybePercent(num, raw) {
      if (raw && raw.indexOf("%") >= 0 && num > 1) return num / 100;
      if (num > 1 && num <= 100) return num / 100;
      return num;
    }

    // Z values (default to 1.96 if alpha=0.05 detected and Z not given).
    find(/\bz[_ -]*α?\s*[:=]\s*([\d.]+)/i, "Z_alpha");
    find(/\bz[_ -]*β?\s*[:=]\s*([\d.]+)/i, "Z_beta");
    find(/\bz\s*[:=]\s*([\d.]+%?)/i,        "Z");

    // Alpha and power
    find(/\b(?:α|alpha)\s*[:=]\s*([\d.]+%?)/i, "alpha", maybePercent);
    find(/\b(?:1\s*-\s*β|power)\s*[:=]\s*([\d.]+%?)/i, "power", maybePercent);
    find(/\b(?:β|beta)\s*[:=]\s*([\d.]+%?)/i, "beta", maybePercent);

    // Single / two proportions
    find(/\bp\s*[:=]\s*([\d.]+%?)/i,  "p",  maybePercent);
    find(/\bp[_ ]?1\s*[:=]\s*([\d.]+%?)/i, "p1", maybePercent);
    find(/\bp[_ ]?2\s*[:=]\s*([\d.]+%?)/i, "p2", maybePercent);
    find(/\bq\s*[:=]\s*([\d.]+%?)/i,  "q",  maybePercent);

    // Precision / margin
    find(/\b(?:d|margin|precision|absolute\s+error)\s*[:=]\s*([\d.]+%?)/i, "d", maybePercent);
    find(/\b(?:e|relative\s+error)\s*[:=]\s*([\d.]+%?)/i, "E", maybePercent);

    // Means / SD
    find(/\b(?:σ|sigma|sd|s\.d\.)\s*[:=]\s*([\d.]+)/i,  "sigma");
    find(/\bμ?[_ ]?1\s*[:=]\s*([\d.]+)/i, "mu1");
    find(/\bμ?[_ ]?2\s*[:=]\s*([\d.]+)/i, "mu2");
    find(/\b(?:Δ|delta|effect|difference)\s*[:=]\s*([\d.]+)/i, "delta");

    // Sensitivity / Specificity / Prevalence
    find(/\b(?:sn|sens|sensitivity)\s*[:=]\s*([\d.]+%?)/i, "Sn", maybePercent);
    find(/\b(?:sp|spec|specificity)\s*[:=]\s*([\d.]+%?)/i, "Sp", maybePercent);
    find(/\b(?:prev|prevalence)\s*[:=]\s*([\d.]+%?)/i,    "prev", maybePercent);

    // Correlation
    find(/\br\s*[:=]\s*(-?[\d.]+)/i, "r");

    // Auto-derive Z from alpha if not explicit (common α values)
    if (!out.Z_alpha && out.alpha != null) {
      var alphaMap = { 0.10: 1.645, 0.05: 1.96, 0.01: 2.576 };
      var key = Math.round(out.alpha * 100) / 100;
      if (alphaMap[key]) out.Z_alpha = alphaMap[key];
    }
    if (!out.Z_beta && out.power != null) {
      var powerMap = { 0.80: 0.84, 0.90: 1.282, 0.95: 1.645 };
      var pk = Math.round(out.power * 100) / 100;
      if (powerMap[pk]) out.Z_beta = powerMap[pk];
    }
    // If just "Z" was given and Z_alpha missing, treat as Z_alpha
    if (!out.Z_alpha && out.Z != null) out.Z_alpha = out.Z;
    return out;
  }

  function fmt(x) {
    if (x == null || isNaN(x)) return "?";
    if (Number.isInteger(x)) return String(x);
    var s = x.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
    return s || String(x);
  }

  // Returns {symbolic, substituted, result} HTML strings.
  function buildSampleSizeFormula(design, vals) {
    // Symbolic forms use HTML for super/sub-scripts.
    var Z  = vals.Z_alpha != null ? vals.Z_alpha : (vals.Z != null ? vals.Z : 1.96);
    var Zb = vals.Z_beta  != null ? vals.Z_beta  : 0.84;

    function r(o) { return o; }

    if (design === "single_proportion" || design === "sens_spec") {
      // n = Z² × p × (1−p) / d²
      var p = vals.p;
      if (design === "sens_spec") {
        // For sens/spec, p = Sn or Sp (whichever the user gave); n is for the
        // disease-positive (Sn) or disease-negative (Sp) subgroup.
        if (p == null) p = vals.Sn != null ? vals.Sn : vals.Sp;
      }
      var d = vals.d;
      var sym = "n = Z<sub>α/2</sub><sup>2</sup> × p × (1 − p) / d<sup>2</sup>";
      if (p == null || d == null) {
        return r({ symbolic: sym, substituted: "Provide <code>p</code> and <code>d</code> in your text to substitute.",
                   result: "" });
      }
      var sub = "n = (" + fmt(Z) + ")<sup>2</sup> × " + fmt(p) + " × (1 − " + fmt(p) + ") / (" + fmt(d) + ")<sup>2</sup>";
      var n = (Z * Z) * p * (1 - p) / (d * d);
      var nUp = Math.ceil(n);
      var note = design === "sens_spec"
        ? " (subgroup size — multiply by 1/prevalence for the total enrolment)"
        : "";
      return r({ symbolic: sym, substituted: sub, result: "n ≈ " + fmt(n) + " → enrol <strong>" + nUp + "</strong>" + note });
    }

    if (design === "two_proportions") {
      // n per group = (Z_α + Z_β)² × [p1(1−p1) + p2(1−p2)] / (p1 − p2)²
      var p1 = vals.p1, p2 = vals.p2;
      var sym = "n<sub>per group</sub> = (Z<sub>α/2</sub> + Z<sub>β</sub>)<sup>2</sup> × [p<sub>1</sub>(1−p<sub>1</sub>) + p<sub>2</sub>(1−p<sub>2</sub>)] / (p<sub>1</sub> − p<sub>2</sub>)<sup>2</sup>";
      if (p1 == null || p2 == null || p1 === p2) {
        return r({ symbolic: sym, substituted: "Provide <code>p1</code> and <code>p2</code> (must differ) in your text to substitute.",
                   result: "" });
      }
      var sub = "n = (" + fmt(Z) + " + " + fmt(Zb) + ")<sup>2</sup> × [" + fmt(p1) + "(1−" + fmt(p1) + ") + " + fmt(p2) + "(1−" + fmt(p2) + ")] / (" + fmt(p1) + " − " + fmt(p2) + ")<sup>2</sup>";
      var n = Math.pow(Z + Zb, 2) * (p1 * (1 - p1) + p2 * (1 - p2)) / Math.pow(p1 - p2, 2);
      var nUp = Math.ceil(n);
      return r({ symbolic: sym, substituted: sub, result: "n ≈ " + fmt(n) + " per group → enrol <strong>" + nUp + " per group</strong> (" + (2 * nUp) + " total)" });
    }

    if (design === "single_mean") {
      // n = (Z × σ / E)²
      var sigma = vals.sigma;
      var E = vals.E != null ? vals.E : vals.d;
      var sym = "n = (Z<sub>α/2</sub> × σ / E)<sup>2</sup>";
      if (sigma == null || E == null) {
        return r({ symbolic: sym, substituted: "Provide <code>σ</code> (SD) and <code>E</code> (margin of error) in your text to substitute.",
                   result: "" });
      }
      var sub = "n = (" + fmt(Z) + " × " + fmt(sigma) + " / " + fmt(E) + ")<sup>2</sup>";
      var n = Math.pow(Z * sigma / E, 2);
      var nUp = Math.ceil(n);
      return r({ symbolic: sym, substituted: sub, result: "n ≈ " + fmt(n) + " → enrol <strong>" + nUp + "</strong>" });
    }

    if (design === "two_means") {
      // n per group = 2 × (Z_α + Z_β)² × σ² / Δ²
      var sigma2 = vals.sigma;
      var delta = vals.delta != null ? vals.delta
                  : (vals.mu1 != null && vals.mu2 != null ? Math.abs(vals.mu1 - vals.mu2) : null);
      var sym = "n<sub>per group</sub> = 2 × (Z<sub>α/2</sub> + Z<sub>β</sub>)<sup>2</sup> × σ<sup>2</sup> / Δ<sup>2</sup>";
      if (sigma2 == null || delta == null || delta === 0) {
        return r({ symbolic: sym, substituted: "Provide <code>σ</code> (pooled SD) and <code>Δ</code> (mean difference, or μ1 &amp; μ2) to substitute.",
                   result: "" });
      }
      var sub = "n = 2 × (" + fmt(Z) + " + " + fmt(Zb) + ")<sup>2</sup> × (" + fmt(sigma2) + ")<sup>2</sup> / (" + fmt(delta) + ")<sup>2</sup>";
      var n = 2 * Math.pow(Z + Zb, 2) * (sigma2 * sigma2) / (delta * delta);
      var nUp = Math.ceil(n);
      return r({ symbolic: sym, substituted: sub, result: "n ≈ " + fmt(n) + " per group → enrol <strong>" + nUp + " per group</strong> (" + (2 * nUp) + " total)" });
    }

    if (design === "correlation") {
      // n = ((Z_α + Z_β) / 0.5·ln((1+r)/(1−r)))² + 3
      var rv = vals.r;
      var sym = "n = ((Z<sub>α/2</sub> + Z<sub>β</sub>) / [½ × ln((1 + r) / (1 − r))])<sup>2</sup> + 3";
      if (rv == null || rv <= -1 || rv >= 1 || rv === 0) {
        return r({ symbolic: sym, substituted: "Provide a non-zero correlation <code>r</code> (between −1 and 1) to substitute.",
                   result: "" });
      }
      var fisher = 0.5 * Math.log((1 + rv) / (1 - rv));
      var sub = "n = ((" + fmt(Z) + " + " + fmt(Zb) + ") / " + fmt(fisher) + ")<sup>2</sup> + 3";
      var n = Math.pow((Z + Zb) / fisher, 2) + 3;
      var nUp = Math.ceil(n);
      return r({ symbolic: sym, substituted: sub, result: "n ≈ " + fmt(n) + " → enrol <strong>" + nUp + "</strong>" });
    }

    return r({ symbolic: "(Pick a study design above.)", substituted: "", result: "" });
  }

  function renderSampleSizeFormula() {
    if (!modalSsPanel || modalSsPanel.hidden) return;
    var vals = parseStatValues(modalTextarea.value);
    var out = buildSampleSizeFormula(modalDesign, vals);
    modalSsFormula.innerHTML = "<span class='prop-ss-label'>Formula</span> " + out.symbolic;
    modalSsSub.innerHTML     = out.substituted ? "<span class='prop-ss-label'>With your values</span> " + out.substituted : "";
    modalSsResult.innerHTML  = out.result ? "<span class='prop-ss-label'>Result</span> " + out.result : "";
  }

  // ===================== Per-section upload (in modal) =====================
  function uploadForSectionInModal(name, file) {
    var prevValue = modalTextarea.value;
    modalTextarea.disabled = true;
    var origMeta = modalMeta.textContent;
    modalMeta.textContent = "Uploading " + file.name + "…";

    var fd = new FormData();
    fd.append("file", file, file.name);
    fd.append("section_name", name);

    fetch("/api/outline/extract-section", { method: "POST", body: fd })
      .then(function (r) {
        return r.json().then(function (j) { return { ok: r.ok, status: r.status, body: j }; });
      })
      .then(function (res) {
        modalTextarea.disabled = false;
        if (!res.ok) {
          modalMeta.textContent = origMeta;
          window.alert("Could not extract that file:\n\n" +
            ((res.body && res.body.detail) ? res.body.detail : ("Request failed (" + res.status + ").")));
          return;
        }
        var incoming = (res.body && res.body.text) || "";
        if (!incoming.trim()) {
          modalMeta.textContent = origMeta;
          window.alert("That file didn't contain any readable text.");
          return;
        }
        var merged = prevValue.trim() ? (prevValue.trim() + "\n\n" + incoming) : incoming;
        modalTextarea.value = merged;
        updateModalMeta();
        renderSampleSizeFormula();
      })
      .catch(function (err) {
        modalTextarea.disabled = false;
        modalMeta.textContent = origMeta;
        window.alert("Network error uploading file: " + (err && err.message ? err.message : err));
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
        includedSections.forEach(function (name) {
          var incoming = (by[name] || "").trim();
          if (!incoming) return;
          var existing = (sectionContent[name] || "").trim();
          if (existing) return;
          sectionContent[name] = incoming;
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
        persist();
        renderAccordion();
        renderAudit();
        // Open the modal on the freshly-generated section so the user can review.
        openModal(name);
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

    // Modal refs
    modalEl         = document.getElementById("prop-out-modal");
    modalTitle      = document.getElementById("prop-out-modal-title");
    modalNum        = document.getElementById("prop-out-modal-num");
    modalTextarea   = document.getElementById("prop-out-modal-textarea");
    modalMeta       = document.getElementById("prop-out-modal-meta");
    modalActions    = document.getElementById("prop-out-modal-actions");
    modalSaveBtn    = document.getElementById("prop-out-modal-save");
    modalCancelBtn  = document.getElementById("prop-out-modal-cancel");
    modalCloseBtn   = document.getElementById("prop-out-modal-close");
    modalSsPanel    = document.getElementById("prop-out-modal-ss");
    modalSsFormula  = document.getElementById("prop-out-modal-ss-formula");
    modalSsSub      = document.getElementById("prop-out-modal-ss-sub");
    modalSsResult   = document.getElementById("prop-out-modal-ss-result");
    modalSsDesignSel= document.getElementById("prop-out-modal-ss-design");

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

    // ---- Modal wiring ----
    modalTextarea.addEventListener("input", function () {
      updateModalMeta();
      renderSampleSizeFormula();
    });
    modalSsDesignSel.addEventListener("change", function () {
      modalDesign = modalSsDesignSel.value;
      renderSampleSizeFormula();
    });
    modalSaveBtn.addEventListener("click", function () { closeModal(true); });
    modalCancelBtn.addEventListener("click", function () { closeModal(false); });
    modalCloseBtn.addEventListener("click", function () { closeModal(false); });
    modalEl.addEventListener("click", function (e) {
      if (e.target === modalEl) closeModal(false);
    });
    document.addEventListener("keydown", function (e) {
      if (modalSection == null) return;
      if (e.key === "Escape") closeModal(false);
      else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) closeModal(true);
    });

    // ---- Continue ----
    nextBtn.addEventListener("click", function () {
      persist();
      window.location.href = "/proposal-module/references.html";
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
