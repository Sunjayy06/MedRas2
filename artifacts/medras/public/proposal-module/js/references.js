/* ============================================================
   Proposal Writing Module — Step 5: References
   ============================================================ */
(function () {
  "use strict";

  var STORAGE_KEY = "medras.proposal.intake";

  // ===================== State =====================
  var format = null;
  var detectedStyles = ["Vancouver"];
  var currentStyle = "Vancouver";
  var refs = [];          // [{title, authors[], journal, year, volume, issue, pages, doi, is_ai_generated?, validation?}]
  var queuedFiles = [];
  var preferences = {};   // {minCount, maxYearsBack, journals[], minYear}

  // ===================== DOM =====================
  var styleNameEl, preflight, preYesBtn, preNoBtn,
      uploadCard, switchToGenBtn, dropzone, fileInput, fileList, extractBtn, extractStatus,
      generateCard, switchToUpBtn, genTopic, genCount, genRecency, genJournals, genBtn, genStatus,
      results, refList, refCountEl, warningEl, styleSelect, chatLog, chatForm, chatInput,
      nextBtn;

  // ===================== Storage =====================
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
  function persist() {
    writeState({
      references: {
        items: refs,
        style: currentStyle,
        preferences: preferences,
        updatedAt: Date.now(),
      },
    });
  }

  // ===================== Helpers =====================
  function escHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function detectStylesClient(citationField) {
    var pats = [
      ["Vancouver", /vancouver/i],
      ["APA",       /\bAPA\b/i],
      ["AMA",       /\bAMA\b|\bNLM\b/i],
      ["IEEE",      /\bIEEE\b/i],
      ["Chicago",   /chicago/i],
    ];
    var out = [];
    pats.forEach(function (p) { if (p[1].test(citationField || "")) out.push(p[0]); });
    return out.length ? out : ["Vancouver"];
  }

  function deriveTopicFromOutline() {
    var s = readState();
    var sects = (s.outline && s.outline.sections) || {};
    var pieces = [];
    ["Title", "Background & Rationale", "Background", "Aims & Objectives", "Objectives", "Aims and Objectives"].forEach(function (k) {
      if (sects[k] && sects[k].trim()) pieces.push(sects[k].trim().slice(0, 600));
    });
    return pieces.join("\n\n").slice(0, 1500);
  }

  function humanSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function setStatus(el, msg, kind) {
    el.textContent = msg || "";
    el.dataset.kind = kind || "";
  }

  // ===================== File queue =====================
  function renderQueuedFiles() {
    fileList.innerHTML = "";
    queuedFiles.forEach(function (f, i) {
      var li = document.createElement("li");
      li.className = "prop-out-fileitem";
      li.setAttribute("data-testid", "file-row-" + i);
      var nm = document.createElement("span"); nm.className = "prop-out-fileitem-name"; nm.textContent = f.name;
      var sz = document.createElement("span"); sz.className = "prop-out-fileitem-size"; sz.textContent = humanSize(f.size);
      var rm = document.createElement("button"); rm.type = "button"; rm.className = "prop-out-fileitem-rm";
      rm.textContent = "✕"; rm.title = "Remove file"; rm.setAttribute("aria-label", "Remove " + f.name);
      rm.addEventListener("click", function () { queuedFiles.splice(i, 1); renderQueuedFiles(); });
      li.appendChild(nm); li.appendChild(sz); li.appendChild(rm);
      fileList.appendChild(li);
    });
    extractBtn.disabled = queuedFiles.length === 0;
  }
  function addFiles(list) {
    var ok = /\.(pdf|docx|pptx|txt|md)$/i;
    Array.prototype.forEach.call(list || [], function (f) {
      if (queuedFiles.length >= 10) return;
      if (!ok.test(f.name || "")) return;
      var dup = queuedFiles.some(function (g) { return g.name === f.name && g.size === f.size; });
      if (dup) return;
      queuedFiles.push(f);
    });
    renderQueuedFiles();
  }

  // ===================== Local format helpers (mirror server) =====================
  function fmtAuthorsVancouver(authors) {
    if (!authors || !authors.length) return "";
    var names = authors.map(function (a) {
      var n = String(a || "").replace(/\./g, "").trim();
      if (!n) return "";
      if (n.indexOf(",") > -1) {
        var parts = n.split(",");
        var last = parts[0].trim();
        var initials = parts.slice(1).join(" ").split(/\s+/).filter(Boolean).map(function (p) { return p[0].toUpperCase(); }).join("");
        return (last + " " + initials).trim();
      }
      var pieces = n.split(/\s+/).filter(Boolean);
      if (pieces.length === 1) return pieces[0];
      var lastN = pieces[pieces.length - 1];
      var initN = pieces.slice(0, -1).map(function (p) { return p[0].toUpperCase(); }).join("");
      return (lastN + " " + initN).trim();
    }).filter(Boolean);
    if (names.length > 6) return names.slice(0, 6).join(", ") + ", et al";
    return names.join(", ");
  }
  function fmtAuthorsAPA(authors) {
    if (!authors || !authors.length) return "";
    var names = authors.map(function (a) {
      var n = String(a || "").replace(/\./g, "").trim();
      if (!n) return "";
      var last, rest;
      if (n.indexOf(",") > -1) { var p = n.split(","); last = p[0].trim(); rest = p.slice(1).join(" ").trim(); }
      else { var pp = n.split(/\s+/); last = pp[pp.length - 1]; rest = pp.slice(0, -1).join(" "); }
      var inits = rest.split(/\s+/).filter(Boolean).map(function (x) { return x[0].toUpperCase() + "."; }).join(" ");
      return (last + ", " + inits).replace(/,\s*$/, "");
    }).filter(Boolean);
    if (names.length === 1) return names[0];
    return names.slice(0, -1).join(", ") + ", & " + names[names.length - 1];
  }
  function formatCitationLocal(ref, style, idx) {
    var t = (ref.title || "").replace(/\.\s*$/, "");
    var j = ref.journal || "";
    var y = ref.year || "";
    var v = ref.volume || ""; var iss = ref.issue || ""; var p = ref.pages || "";
    var doi = ref.doi || "";
    if (style === "APA") {
      var s = fmtAuthorsAPA(ref.authors);
      if (y) s += " (" + y + ").";
      if (t) s += " " + t + ".";
      if (j) {
        s += " *" + j + "*";
        if (v) { s += ", *" + v + "*"; if (iss) s += "(" + iss + ")"; }
        if (p) s += ", " + p;
        s += ".";
      }
      if (doi) s += " https://doi.org/" + doi;
      return s.trim();
    }
    if (style === "IEEE") {
      var s2 = "[" + idx + "] " + fmtAuthorsAPA(ref.authors);
      if (t) s2 += ', "' + t + ',"';
      if (j) s2 += " *" + j + "*,";
      if (v) s2 += " vol. " + v + ",";
      if (iss) s2 += " no. " + iss + ",";
      if (p) s2 += " pp. " + p + ",";
      if (y) s2 += " " + y + ".";
      if (doi) s2 += " doi: " + doi + ".";
      return s2.trim();
    }
    if (style === "Chicago") {
      var s3 = fmtAuthorsAPA(ref.authors); if (s3) s3 += ".";
      if (y) s3 += " " + y + ".";
      if (t) s3 += ' "' + t + '."';
      if (j) {
        s3 += " *" + j + "*";
        if (v) s3 += " " + v;
        if (iss) s3 += ", no. " + iss;
        if (p) s3 += ": " + p;
        s3 += ".";
      }
      if (doi) s3 += " https://doi.org/" + doi + ".";
      return s3.trim();
    }
    // Vancouver / AMA default
    var head = fmtAuthorsVancouver(ref.authors); if (head) head += ".";
    if (t) head += " " + t + ".";
    if (j) {
      head += " " + j + ".";
      if (y) {
        head += " " + y;
        if (v) { head += ";" + v; if (iss) head += "(" + iss + ")"; }
        if (p) head += ":" + p;
        head += ".";
      }
    } else if (y) head += " " + y + ".";
    if (doi) head += " doi:" + doi;
    return idx + ". " + head.trim();
  }

  // ===================== Duplicate detection (client mirror) =====================
  function findDuplicatesClient(list) {
    var seenDoi = {}; var seenTitle = {}; var flagged = {};
    list.forEach(function (r, i) {
      var doi = (r.doi || "").trim().toLowerCase();
      var tk = (r.title || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
      var year = (r.year || "").trim();
      if (doi) {
        if (seenDoi[doi] != null) { flagged[i] = "Duplicate DOI of #" + (seenDoi[doi] + 1); return; }
        seenDoi[doi] = i;
      }
      if (tk) {
        var k = tk + "::" + year;
        if (seenTitle[k] != null) { flagged[i] = "Duplicate of #" + (seenTitle[k] + 1) + " (same title/year)"; return; }
        seenTitle[k] = i;
      }
    });
    return flagged;
  }

  // ===================== Render references =====================
  function renderRefs() {
    refCountEl.textContent = "(" + refs.length + ")";
    refList.innerHTML = "";
    var dupes = findDuplicatesClient(refs);

    refs.forEach(function (r, i) {
      var li = document.createElement("li");
      li.className = "prop-ref-item";
      if (r.is_ai_generated) li.classList.add("is-ai");
      if (dupes[i]) li.classList.add("is-dup");

      // Citation text
      var cite = document.createElement("div");
      cite.className = "prop-ref-cite";
      cite.textContent = formatCitationLocal(r, currentStyle, i + 1);
      li.appendChild(cite);

      // Badges row
      var badges = document.createElement("div");
      badges.className = "prop-ref-badges";

      if (r.is_ai_generated) {
        var b = document.createElement("span"); b.className = "prop-ref-badge is-warn"; b.textContent = "AI-generated · verify";
        badges.appendChild(b);
      }
      if (dupes[i]) {
        var bd = document.createElement("span"); bd.className = "prop-ref-badge is-warn"; bd.textContent = dupes[i];
        badges.appendChild(bd);
      }
      if (r.doi) {
        var bvd = document.createElement("span");
        bvd.className = "prop-ref-badge " + (r.validation === "ok" ? "is-ok" : r.validation === "not_found" ? "is-bad" : r.validation === "format_error" ? "is-bad" : "is-mute");
        bvd.textContent = r.validation === "ok" ? "DOI ✓ verified"
                       : r.validation === "not_found" ? "DOI not found"
                       : r.validation === "format_error" ? "DOI malformed"
                       : r.validation === "network_error" ? "DOI check failed"
                       : "DOI not yet checked";
        badges.appendChild(bvd);
      } else if (!r.is_ai_generated) {
        var bnd = document.createElement("span"); bnd.className = "prop-ref-badge is-mute"; bnd.textContent = "No DOI";
        badges.appendChild(bnd);
      }

      li.appendChild(badges);

      // Action buttons
      var act = document.createElement("div");
      act.className = "prop-ref-actions";

      var editBtn = document.createElement("button");
      editBtn.type = "button"; editBtn.className = "prop-ref-act"; editBtn.textContent = "✎ Edit";
      editBtn.setAttribute("data-testid", "button-edit-ref-" + i);
      editBtn.addEventListener("click", function () { openEditor(i, li); });
      act.appendChild(editBtn);

      if (r.doi) {
        var vBtn = document.createElement("button");
        vBtn.type = "button"; vBtn.className = "prop-ref-act"; vBtn.textContent = "🔍 Check DOI";
        vBtn.setAttribute("data-testid", "button-check-doi-" + i);
        vBtn.addEventListener("click", function () { validateDOI(i, vBtn); });
        act.appendChild(vBtn);
      }

      var rmBtn = document.createElement("button");
      rmBtn.type = "button"; rmBtn.className = "prop-ref-act is-danger"; rmBtn.textContent = "✕ Remove";
      rmBtn.setAttribute("data-testid", "button-remove-ref-" + i);
      rmBtn.addEventListener("click", function () {
        refs.splice(i, 1); persist(); renderRefs();
      });
      act.appendChild(rmBtn);

      li.appendChild(act);
      refList.appendChild(li);
    });

    // Add manual button
    var addLi = document.createElement("li");
    addLi.className = "prop-ref-additem";
    var addBtn = document.createElement("button");
    addBtn.type = "button"; addBtn.className = "prop-ref-act prop-ref-act--add";
    addBtn.textContent = "+ Add reference manually";
    addBtn.setAttribute("data-testid", "button-add-manual");
    addBtn.addEventListener("click", function () {
      refs.push({ title: "", authors: [], journal: "", year: "", volume: "", issue: "", pages: "", doi: "" });
      persist(); renderRefs();
      // Open editor on the new one
      var lastLi = refList.querySelectorAll(".prop-ref-item")[refs.length - 1];
      if (lastLi) openEditor(refs.length - 1, lastLi);
    });
    addLi.appendChild(addBtn);
    refList.appendChild(addLi);
  }

  // ===================== Editor (inline) =====================
  function openEditor(i, liEl) {
    var r = refs[i];
    if (!r) return;
    if (liEl.querySelector(".prop-ref-editor")) return;     // already open

    var ed = document.createElement("div");
    ed.className = "prop-ref-editor";

    function field(label, key, type) {
      var wrap = document.createElement("label"); wrap.className = "prop-ref-field";
      var lbl = document.createElement("span"); lbl.className = "prop-ref-field-lbl"; lbl.textContent = label;
      var inp = type === "textarea" ? document.createElement("textarea") : document.createElement("input");
      if (type !== "textarea") inp.type = "text";
      if (type === "textarea") inp.rows = 2;
      inp.value = key === "authors" ? (r.authors || []).join("; ") : (r[key] || "");
      inp.addEventListener("input", function () {
        if (key === "authors") r.authors = inp.value.split(";").map(function (s) { return s.trim(); }).filter(Boolean);
        else r[key] = inp.value;
      });
      wrap.appendChild(lbl); wrap.appendChild(inp);
      return wrap;
    }

    ed.appendChild(field("Title", "title", "textarea"));
    ed.appendChild(field("Authors (separated by ;)", "authors", "text"));
    var row = document.createElement("div"); row.className = "prop-ref-fieldrow";
    row.appendChild(field("Journal", "journal", "text"));
    row.appendChild(field("Year", "year", "text"));
    ed.appendChild(row);
    var row2 = document.createElement("div"); row2.className = "prop-ref-fieldrow";
    row2.appendChild(field("Volume", "volume", "text"));
    row2.appendChild(field("Issue", "issue", "text"));
    row2.appendChild(field("Pages", "pages", "text"));
    ed.appendChild(row2);
    ed.appendChild(field("DOI", "doi", "text"));

    var saveBtn = document.createElement("button");
    saveBtn.type = "button"; saveBtn.className = "prop-cta-primary prop-cta-sm"; saveBtn.textContent = "Save";
    saveBtn.addEventListener("click", function () {
      // Strip leading https://doi.org/ from DOI
      r.doi = (r.doi || "").replace(/^https?:\/\/(dx\.)?doi\.org\//i, "").replace(/^doi:\s*/i, "").trim();
      r.is_ai_generated = false;     // user-edited
      delete r.validation;
      persist(); renderRefs();
    });
    ed.appendChild(saveBtn);

    liEl.appendChild(ed);
  }

  // ===================== DOI validation =====================
  function validateDOI(i, btnEl) {
    var r = refs[i]; if (!r || !r.doi) return;
    var orig = btnEl.textContent;
    btnEl.disabled = true; btnEl.textContent = "Checking…";
    fetch("/api/references/validate-doi", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doi: r.doi }),
    })
      .then(function (resp) { return resp.json().then(function (j) { return { ok: resp.ok, body: j }; }); })
      .then(function (res) {
        btnEl.disabled = false; btnEl.textContent = orig;
        if (!res.ok) { window.alert("DOI check failed: " + (res.body.detail || "unknown")); return; }
        r.validation = res.body.status;
        if (res.body.metadata) {
          if (!r.title)   r.title = res.body.metadata.title || r.title;
          if (!r.journal) r.journal = res.body.metadata.journal || r.journal;
          if (!r.year)    r.year = res.body.metadata.year || r.year;
        }
        persist(); renderRefs();
      })
      .catch(function (err) {
        btnEl.disabled = false; btnEl.textContent = orig;
        window.alert("Network error: " + (err && err.message || err));
      });
  }

  // ===================== Style picker =====================
  function buildStyleSelect() {
    styleSelect.innerHTML = "";
    detectedStyles.forEach(function (s) {
      var o = document.createElement("option"); o.value = s; o.textContent = s;
      if (s === currentStyle) o.selected = true;
      styleSelect.appendChild(o);
    });
    styleSelect.addEventListener("change", function () {
      currentStyle = styleSelect.value;
      styleNameEl.textContent = currentStyle;
      persist();
      renderRefs();
    });
  }

  // ===================== Extract upload =====================
  function doExtract() {
    if (!queuedFiles.length) return;
    if (window.MedrasProposalState) window.MedrasProposalState.setBusy(true);
    extractBtn.disabled = true;
    setStatus(extractStatus, "Reading " + queuedFiles.length + " file(s) and extracting references — this can take 20-40 seconds…", "info");
    var fd = new FormData();
    queuedFiles.forEach(function (f) { fd.append("files", f, f.name); });
    fetch("/api/references/extract", { method: "POST", body: fd })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, status: r.status, body: j }; }); })
      .then(function (res) {
        extractBtn.disabled = false;
        if (window.MedrasProposalState) window.MedrasProposalState.setBusy(false);
        if (!res.ok) {
          setStatus(extractStatus, "⚠ " + (res.body.detail || ("Failed (" + res.status + ")")), "error");
          return;
        }
        var got = res.body.references || [];
        // Append (don't replace) so multiple uploads accumulate
        refs = refs.concat(got);
        var skipped = (res.body.files || []).filter(function (f) { return !f.ok; });
        var msg = "✓ Extracted " + got.length + " reference(s) from " + (res.body.files || []).filter(function (f) { return f.ok; }).length + " file(s).";
        if (skipped.length) msg += " " + skipped.length + " skipped: " + skipped.map(function (f) { return f.name + " (" + f.error + ")"; }).join("; ");
        setStatus(extractStatus, msg, "ok");
        queuedFiles = []; renderQueuedFiles();
        showResults();
        persist(); renderRefs();
      })
      .catch(function (err) {
        extractBtn.disabled = false;
        if (window.MedrasProposalState) window.MedrasProposalState.setBusy(false);
        setStatus(extractStatus, "⚠ Network error: " + (err && err.message || err), "error");
      });
  }

  // ===================== Generate ====================
  function doGenerate() {
    var topic = (genTopic.value || "").trim();
    if (!topic) { window.alert("Please describe your research topic."); return; }
    if (window.MedrasProposalState) window.MedrasProposalState.setBusy(true);
    var count = parseInt(genCount.value, 10) || 15;
    var recency = parseInt(genRecency.value, 10) || 7;
    var journals = (genJournals.value || "").split(",").map(function (s) { return s.trim(); }).filter(Boolean);
    genBtn.disabled = true;
    setStatus(genStatus, "Generating " + count + " reference suggestions — this takes 20-40 seconds…", "info");
    fetch("/api/references/generate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic: topic, count: count, recency_years: recency, journals: journals }),
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, status: r.status, body: j }; }); })
      .then(function (res) {
        genBtn.disabled = false;
        if (window.MedrasProposalState) window.MedrasProposalState.setBusy(false);
        if (!res.ok) { setStatus(genStatus, "⚠ " + (res.body.detail || ("Failed (" + res.status + ")")), "error"); return; }
        var got = res.body.references || [];
        refs = refs.concat(got);
        setStatus(genStatus, "✓ Generated " + got.length + " suggestions.", "ok");
        showWarning(res.body.warning || "");
        showResults();
        persist(); renderRefs();
      })
      .catch(function (err) {
        genBtn.disabled = false;
        if (window.MedrasProposalState) window.MedrasProposalState.setBusy(false);
        setStatus(genStatus, "⚠ Network error: " + (err && err.message || err), "error");
      });
  }

  function showWarning(msg) {
    if (!msg) { warningEl.hidden = true; return; }
    warningEl.hidden = false;
    warningEl.textContent = "⚠ " + msg;
  }

  function showResults() {
    results.hidden = false;
  }

  // ===================== Chatbox =====================
  function chatPush(role, text) {
    var b = document.createElement("div");
    b.className = "prop-ref-chat-msg is-" + role;
    b.textContent = text;
    chatLog.appendChild(b);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  function applyChat(raw) {
    var t = raw.toLowerCase().trim();
    var actions = [];
    var minMatch = t.match(/(?:minimum|at least|>=|>\s*=?\s*)\s*(\d+)/);
    if (minMatch) {
      preferences.minCount = parseInt(minMatch[1], 10);
      actions.push("Noted minimum count: " + preferences.minCount + ".");
    }
    var yrsMatch = t.match(/(?:past|last|recent)\s*(\d+)\s*years?/);
    if (yrsMatch) {
      var n = parseInt(yrsMatch[1], 10);
      preferences.maxYearsBack = n;
      var cutoff = (new Date()).getFullYear() - n;
      preferences.minYear = cutoff;
      var before = refs.length;
      refs = refs.filter(function (r) { var y = parseInt(r.year, 10); return !y || y >= cutoff; });
      actions.push("Kept references from " + cutoff + " onward (removed " + (before - refs.length) + ").");
    }
    var yearMatch = t.match(/(?:after|since|from)\s*(19|20)(\d{2})/);
    if (yearMatch && !yrsMatch) {
      var year = parseInt(yearMatch[1] + yearMatch[2], 10);
      preferences.minYear = year;
      var before2 = refs.length;
      refs = refs.filter(function (r) { var y = parseInt(r.year, 10); return !y || y >= year; });
      actions.push("Kept references from " + year + " onward (removed " + (before2 - refs.length) + ").");
    }
    var beforeY = t.match(/(?:before|until|prior to)\s*(19|20)(\d{2})/);
    if (beforeY) {
      var y = parseInt(beforeY[1] + beforeY[2], 10);
      var before3 = refs.length;
      refs = refs.filter(function (r) { var ry = parseInt(r.year, 10); return !ry || ry < y; });
      actions.push("Kept references before " + y + " (removed " + (before3 - refs.length) + ").");
    }
    var jMatch = t.match(/(?:only|from|in)\s+(?:journals?\s*[:\-]?\s*)?(.+)/);
    if (/(?:^|\s)only\s+/.test(t) && jMatch && !yrsMatch && !yearMatch && !beforeY && !minMatch) {
      var rawList = (raw.split(/only\s+/i)[1] || "").trim();
      rawList = rawList.replace(/^journals?\s*[:\-]?\s*/i, "").replace(/\.$/, "");
      var list = rawList.split(/[,;]| and /).map(function (s) { return s.trim(); }).filter(Boolean);
      if (list.length) {
        preferences.journals = list;
        var before4 = refs.length;
        refs = refs.filter(function (r) {
          var j = (r.journal || "").toLowerCase();
          return list.some(function (x) { return j.indexOf(x.toLowerCase()) > -1; });
        });
        actions.push("Kept only " + list.join(", ") + " (removed " + (before4 - refs.length) + ").");
      }
    }
    if (/^(reset|clear filters?|undo)/.test(t)) {
      preferences = {};
      actions.push("Cleared all reference preferences.");
    }
    if (/dedupe|duplicates?/.test(t)) {
      var d = findDuplicatesClient(refs);
      var dupIdx = Object.keys(d).map(Number).sort(function (a, b) { return b - a; });
      dupIdx.forEach(function (i) { refs.splice(i, 1); });
      actions.push("Removed " + dupIdx.length + " duplicate(s).");
    }

    if (!actions.length) {
      actions.push("Sorry — I didn't catch a rule there. Try things like \"minimum 30\", \"only past 5 years\", \"only Lancet, NEJM\", \"after 2020\", \"dedupe\", or \"reset\".");
    } else {
      persist(); renderRefs();
      var min = preferences.minCount;
      if (min && refs.length < min) {
        actions.push("Heads up: you now have " + refs.length + " refs but asked for at least " + min + ".");
      }
    }
    chatPush("bot", actions.join(" "));
  }

  // ===================== Flow =====================
  function showUpload() { preflight.hidden = true; uploadCard.hidden = false; generateCard.hidden = true; }
  function showGenerate() {
    preflight.hidden = true; uploadCard.hidden = true; generateCard.hidden = false;
    if (!genTopic.value.trim()) genTopic.value = deriveTopicFromOutline();
  }

  // ===================== Init =====================
  function init() {
    styleNameEl = document.getElementById("prop-ref-style-name");
    preflight = document.getElementById("prop-ref-preflight");
    preYesBtn = document.getElementById("prop-ref-pre-yes");
    preNoBtn = document.getElementById("prop-ref-pre-no");
    uploadCard = document.getElementById("prop-ref-upload");
    switchToGenBtn = document.getElementById("prop-ref-switch-gen");
    dropzone = document.getElementById("prop-ref-dropzone");
    fileInput = document.getElementById("prop-ref-files");
    fileList = document.getElementById("prop-ref-filelist");
    extractBtn = document.getElementById("prop-ref-extract");
    extractStatus = document.getElementById("prop-ref-extract-status");
    generateCard = document.getElementById("prop-ref-generate");
    switchToUpBtn = document.getElementById("prop-ref-switch-up");
    genTopic = document.getElementById("prop-ref-gen-topic");
    genCount = document.getElementById("prop-ref-gen-count");
    genRecency = document.getElementById("prop-ref-gen-recency");
    genJournals = document.getElementById("prop-ref-gen-journals");
    genBtn = document.getElementById("prop-ref-do-generate");
    genStatus = document.getElementById("prop-ref-gen-status");
    results = document.getElementById("prop-ref-results");
    refList = document.getElementById("prop-ref-list");
    refCountEl = document.getElementById("prop-ref-count");
    warningEl = document.getElementById("prop-ref-warning");
    styleSelect = document.getElementById("prop-ref-style");
    chatLog = document.getElementById("prop-ref-chat-log");
    chatForm = document.getElementById("prop-ref-chat-form");
    chatInput = document.getElementById("prop-ref-chat-input");
    nextBtn = document.getElementById("prop-ref-next");

    // Gates
    var saved = readState();
    if (!saved.role) { window.location.replace("/proposal-module/role.html"); return; }
    if (!saved.langMode) { window.location.replace("/proposal-module/language.html"); return; }
    if (!saved.format) { window.location.replace("/proposal-module/format.html"); return; }
    if (!saved.outline || !saved.outline.sections) { window.location.replace("/proposal-module/outline.html"); return; }

    format = saved.format;
    detectedStyles = detectStylesClient(format.citation || "");

    var savedRefs = saved.references || {};
    if (savedRefs.style && detectedStyles.indexOf(savedRefs.style) > -1) currentStyle = savedRefs.style;
    else currentStyle = detectedStyles[0];
    if (Array.isArray(savedRefs.items)) refs = savedRefs.items;
    if (savedRefs.preferences) preferences = savedRefs.preferences;

    styleNameEl.textContent = currentStyle;
    buildStyleSelect();

    if (refs.length) showResults();
    renderRefs();

    // ----- Pre-flight -----
    preYesBtn.addEventListener("click", showUpload);
    preNoBtn.addEventListener("click", showGenerate);
    switchToGenBtn.addEventListener("click", showGenerate);
    switchToUpBtn.addEventListener("click", showUpload);

    // ----- Upload -----
    fileInput.addEventListener("change", function () { addFiles(fileInput.files); fileInput.value = ""; });
    ["dragenter", "dragover"].forEach(function (ev) {
      dropzone.addEventListener(ev, function (e) { e.preventDefault(); e.stopPropagation(); dropzone.classList.add("is-drag"); });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      dropzone.addEventListener(ev, function (e) { e.preventDefault(); e.stopPropagation(); dropzone.classList.remove("is-drag"); });
    });
    dropzone.addEventListener("drop", function (e) { if (e.dataTransfer && e.dataTransfer.files.length) addFiles(e.dataTransfer.files); });
    extractBtn.addEventListener("click", doExtract);

    // ----- Generate -----
    genBtn.addEventListener("click", doGenerate);

    // ----- Chat -----
    chatForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var v = (chatInput.value || "").trim();
      if (!v) return;
      chatPush("you", v);
      chatInput.value = "";
      applyChat(v);
    });

    // ----- Continue -----
    nextBtn.addEventListener("click", function () {
      persist();
      var n = refs.length;
      var min = preferences.minCount || 0;
      if (min && n < min) {
        if (!window.confirm("You have " + n + " references but asked for at least " + min + ". Continue anyway?")) return;
      }
      window.location.href = "/proposal-module/generate.html";
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
