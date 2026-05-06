/* ============================================================
   Proposal Writing Module — Step 6: Generate (RAG-backed)
   ============================================================
   Calls POST /api/proposal/generate-rag-sections with the user's
   intake state + research topic, then renders Background / Lit
   Review / Rationale alongside a Sources panel that lists every
   real article the model was allowed to cite.
   ============================================================ */
(function () {
  "use strict";

  var STORAGE_KEY  = "medras.proposal.intake";
  var TOPIC_KEY    = "medras.proposal.topic";
  var ENDPOINT     = "/api/proposal/generate-rag-sections";

  // ----- state -----
  function readState() {
    try {
      var raw = sessionStorage.getItem(STORAGE_KEY);
      var s = raw ? JSON.parse(raw) : {};
      return s && typeof s === "object" ? s : {};
    } catch (e) { return {}; }
  }
  function writeTopic(t) {
    try { sessionStorage.setItem(TOPIC_KEY, t || ""); } catch (e) {}
  }
  function readTopic() {
    try { return sessionStorage.getItem(TOPIC_KEY) || ""; } catch (e) { return ""; }
  }

  // ----- DOM helpers -----
  function $(id) { return document.getElementById(id); }
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // Render text containing [CITE_n] tags. Each tag becomes a clickable
  // pill that scrolls to / highlights the matching source-list entry.
  function renderWithCitations(text) {
    var safe = escapeHtml(text || "");
    return safe.replace(/\[CITE_(\d+)\]/g, function (_, n) {
      return '<a href="#gen-src-' + n + '" class="gen-cite" data-cite="' + n + '">[' + n + ']</a>';
    });
  }

  function setStatus(kind, html) {
    var el = $("gen-status");
    if (!el) return;
    if (!html) { el.classList.add("gen-hidden"); el.innerHTML = ""; return; }
    el.classList.remove("gen-hidden", "is-info", "is-error", "is-ok");
    el.classList.add("is-" + kind);
    el.innerHTML = html;
  }

  function formatAuthors(arr) {
    if (!arr || !arr.length) return "Anonymous";
    if (arr.length === 1) return escapeHtml(arr[0]);
    if (arr.length <= 3) return arr.map(escapeHtml).join(", ");
    return escapeHtml(arr[0]) + " <em>et al.</em>";
  }

  function renderSources(sources) {
    var listEl = $("gen-src-list");
    var countEl = $("gen-src-count");
    countEl.textContent = String(sources.length);
    if (!sources.length) {
      listEl.innerHTML = '<p style="color:#8aa0c5;font-size:.84rem">' +
        'The model did not cite any of the retrieved sources. Try a more specific topic.</p>';
      return;
    }
    var html = sources.map(function (s) {
      var n = (s.cite_id || "").replace(/^CITE_/, "");
      var titleHtml = escapeHtml(s.title || "(untitled)");
      var link = s.url || (s.doi ? "https://doi.org/" + encodeURIComponent(s.doi) : "");
      var titleEl = link
        ? '<a href="' + escapeHtml(link) + '" target="_blank" rel="noopener noreferrer">' + titleHtml + '</a>'
        : titleHtml;
      var meta = [];
      if (s.journal) meta.push(escapeHtml(s.journal));
      if (s.year) meta.push(escapeHtml(String(s.year)));
      if (s.doi) meta.push('doi:' + escapeHtml(s.doi));
      return '' +
        '<div class="gen-source-item" id="gen-src-' + escapeHtml(n) + '">' +
          '<span class="gen-src-id">[' + escapeHtml(n) + ']</span>' +
          '<span class="gen-src-badge">' + escapeHtml(s.source || "?") + '</span>' +
          '<div class="gen-src-title">' + titleEl + '</div>' +
          '<div class="gen-src-meta">' + formatAuthors(s.authors) +
            (meta.length ? ' · ' + meta.join(' · ') : '') +
          '</div>' +
        '</div>';
    }).join("");
    listEl.innerHTML = html;
  }

  function renderDatabasesMeta(meta) {
    var stripEl  = $("gen-db-strip");
    var stubEl   = $("gen-stub-list");
    var stubBody = $("gen-stub-body");
    var pills = [];
    var stubs = [];
    Object.keys(meta || {}).forEach(function (db) {
      var m = meta[db] || {};
      var cls = "gen-db-pill";
      var label = db;
      if (m.stub) {
        cls += " is-stub";
        label = db + " · subscription";
        if (m.message) stubs.push({ db: db, message: m.message });
      } else if (m.error) {
        cls += " is-error";
        label = db + " · error";
      } else if (m.cached) {
        cls += " is-cached";
        label = db + " · " + (m.count || 0) + " (cached)";
      } else {
        label = db + " · " + (m.count || 0);
      }
      pills.push('<span class="' + cls + '" title="' + escapeHtml(m.message || m.error || "") + '">' +
                 escapeHtml(label) + '</span>');
    });
    stripEl.innerHTML = pills.join("");
    if (stubs.length) {
      stubBody.innerHTML = stubs.map(function (s) {
        return '<p><strong>' + escapeHtml(s.db) + ':</strong> ' + escapeHtml(s.message) + '</p>';
      }).join("");
      stubEl.classList.remove("gen-hidden");
    } else {
      stubEl.classList.add("gen-hidden");
    }
  }

  function renderResults(data) {
    $("gen-out-background").innerHTML        = renderWithCitations(data.sections.background);
    $("gen-out-literature_review").innerHTML = renderWithCitations(data.sections.literature_review);
    $("gen-out-rationale").innerHTML         = renderWithCitations(data.sections.rationale);
    renderSources(data.sources || []);
    renderDatabasesMeta(data.databases_meta || {});
    var metaParts = [];
    if (data.domain) metaParts.push("Domain: <strong>" + escapeHtml(data.domain) + "</strong>");
    if (data.all_retrieved) metaParts.push(data.all_retrieved.length + " papers retrieved");
    $("gen-src-meta").innerHTML = metaParts.join(" · ");
    $("gen-results").classList.remove("gen-hidden");
  }

  // ----- network -----
  async function generate(topic) {
    var state = readState();
    var intake = {
      role:     state.role || null,
      language: state.language || null,
      format:   state.format || null,
      topic:    topic,
    };
    var resp;
    try {
      resp = await fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ intake: intake }),
      });
    } catch (err) {
      throw new Error("Network error: " + (err && err.message ? err.message : "could not reach server"));
    }
    var body;
    try { body = await resp.json(); } catch (e) { body = null; }
    if (!resp.ok) {
      var msg = (body && body.detail) || ("Server returned " + resp.status);
      throw new Error(msg);
    }
    return body;
  }

  // ----- init -----
  function init() {
    var form  = $("gen-form");
    var input = $("gen-topic");
    var btn   = $("gen-go");
    if (!form || !input || !btn) return;

    // Pre-fill topic from sessionStorage if present.
    var prior = readTopic();
    if (prior) input.value = prior;

    form.addEventListener("submit", async function (e) {
      e.preventDefault();
      var topic = (input.value || "").trim();
      if (topic.length < 8) {
        setStatus("error", "Please describe your research topic in at least a sentence.");
        input.focus();
        return;
      }
      writeTopic(topic);
      btn.disabled = true;
      setStatus("info",
        '<span class="gen-spinner"></span>Searching real academic databases and drafting sections (≈30–60s)…');
      try {
        var data = await generate(topic);
        renderResults(data);
        setStatus("ok",
          "Drafted from " + (data.sources || []).length + " cited papers (" +
          (data.all_retrieved || []).length + " retrieved). Click any [n] tag to jump to the source.");
        // Smooth-scroll to results.
        setTimeout(function () {
          var r = $("gen-results");
          if (r) r.scrollIntoView({ behavior: "smooth", block: "start" });
        }, 50);
      } catch (err) {
        setStatus("error", escapeHtml(err.message || String(err)));
      } finally {
        btn.disabled = false;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
