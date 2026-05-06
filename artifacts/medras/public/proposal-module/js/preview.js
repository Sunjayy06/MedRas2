/* ============================================================
   Proposal Writing Module — Step 7: Preview
   ============================================================
   Read-only display of the seven generated sections + Budget /
   Timeline manual editors + the Sources panel from Step 6.
   Reads from sessionStorage["medras.proposal.generated"].
   ============================================================ */
(function () {
  "use strict";

  var RESULT_KEY = "medras.proposal.generated";
  var MANUAL_KEY = "medras.proposal.manual";

  var SECTION_TITLES = [
    ["background",        "Background"],
    ["literature_review", "Literature Review"],
    ["rationale",         "Rationale"],
    ["methods",           "Methods"],
    ["statistical_plan",  "Statistical Plan"],
    ["ethics",            "Ethics"],
    ["expected_outcomes", "Expected Outcomes"],
  ];
  var MANUAL_FIELDS = [
    ["budget",   "Budget",
     "Itemise costs (personnel, consumables, equipment, travel, contingency). Follow your institution's funding-body template."],
    ["timeline", "Timeline",
     "Month-by-month milestones from project start through dissemination. Include ethics approval, recruitment, follow-up, analysis and write-up."],
  ];

  function $(id) { return document.getElementById(id); }
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function renderWithCitations(text) {
    return escapeHtml(text || "").replace(/\[CITE_(\d+)\]/g, function (_, n) {
      return '<a href="#pv-src-' + escapeHtml(n) + '" class="pv-cite">[' + escapeHtml(n) + ']</a>';
    });
  }
  function readResult() {
    try { return JSON.parse(sessionStorage.getItem(RESULT_KEY) || "null"); }
    catch (e) { return null; }
  }
  function readManual() {
    try { return JSON.parse(sessionStorage.getItem(MANUAL_KEY) || "{}") || {}; }
    catch (e) { return {}; }
  }
  function writeManual(patch) {
    var cur = readManual();
    var next = Object.assign({}, cur, patch);
    try { sessionStorage.setItem(MANUAL_KEY, JSON.stringify(next)); } catch (e) {}
  }
  function formatAuthors(arr) {
    if (!arr || !arr.length) return "Anonymous";
    if (arr.length === 1) return escapeHtml(arr[0]);
    if (arr.length <= 3) return arr.map(escapeHtml).join(", ");
    return escapeHtml(arr[0]) + " et al.";
  }

  function render(result) {
    var sections = result.sections || {};
    var manual = readManual();

    // Meta block
    var metaParts = [];
    if (result.topic)    metaParts.push("<strong>Topic:</strong> " + escapeHtml(result.topic));
    if (result.domain)   metaParts.push("<strong>Domain:</strong> " + escapeHtml(result.domain));
    metaParts.push("<strong>Cited sources:</strong> " + (result.sources || []).length);
    if (result.generatedAt) {
      var d = new Date(result.generatedAt);
      if (!isNaN(d.getTime())) metaParts.push("<strong>Drafted:</strong> " + d.toLocaleString());
    }
    var metaEl = $("pv-meta");
    metaEl.innerHTML = metaParts.join(" · ");
    metaEl.classList.remove("gen-hidden");

    // Sections + manual + sources
    var html = "";
    SECTION_TITLES.forEach(function (pair) {
      var key = pair[0], label = pair[1];
      var body = (sections[key] || "").trim();
      html += '' +
        '<section class="pv-section" data-testid="card-pv-' + key.replace(/_/g, "-") + '">' +
          '<h2>' + escapeHtml(label) + '</h2>' +
          '<div class="pv-body">' + (body ? renderWithCitations(body) :
            '<em style="color:#8aa0c5">(empty — re-run Step 6)</em>') + '</div>' +
        '</section>';
    });

    MANUAL_FIELDS.forEach(function (pair) {
      var key = pair[0], label = pair[1], hint = pair[2];
      var val = (manual[key] || "");
      html += '' +
        '<section class="pv-section is-manual" data-testid="card-pv-' + key + '">' +
          '<h2>' + escapeHtml(label) + ' <span style="font-size:.7rem;font-weight:600;letter-spacing:.05em;text-transform:uppercase;padding:2px 8px;border-radius:999px;background:rgba(255,180,80,.1);color:#ffd9a8;border:1px solid rgba(255,180,80,.28);margin-left:8px;">Manual</span></h2>' +
          '<p style="font-size:.84rem;color:#a8b9d6;margin:0 0 8px">' + escapeHtml(hint) + '</p>' +
          '<textarea data-manual-key="' + key + '" data-testid="input-manual-' + key + '" placeholder="Type your ' + label.toLowerCase() + ' here…">' + escapeHtml(val) + '</textarea>' +
        '</section>';
    });

    var sources = result.sources || [];
    if (sources.length) {
      html += '<section class="pv-section" data-testid="card-pv-sources"><h2>Sources cited</h2><ul class="pv-sources-list">';
      sources.forEach(function (s) {
        var n = (s.cite_id || "").replace(/^CITE_/, "");
        var link = s.url || (s.doi ? "https://doi.org/" + encodeURIComponent(s.doi) : "");
        var title = escapeHtml(s.title || "(untitled)");
        var titleEl = link ? '<a href="' + escapeHtml(link) + '" target="_blank" rel="noopener noreferrer">' + title + '</a>' : title;
        var meta = [];
        if (s.journal) meta.push(escapeHtml(s.journal));
        if (s.year) meta.push(escapeHtml(String(s.year)));
        if (s.doi) meta.push("doi:" + escapeHtml(s.doi));
        html += '<li id="pv-src-' + escapeHtml(n) + '">' +
                  '<span class="pv-src-id">[' + escapeHtml(n) + ']</span>' +
                  formatAuthors(s.authors) + ' (' + escapeHtml(String(s.year || "n.d.")) + '). ' +
                  titleEl + (meta.length ? ". " + meta.join(" · ") : "") +
                '</li>';
      });
      html += "</ul></section>";
    }

    var content = $("pv-content");
    content.innerHTML = html;
    content.classList.remove("gen-hidden");

    // Wire manual textareas to persist on input.
    Array.prototype.forEach.call(content.querySelectorAll("textarea[data-manual-key]"), function (ta) {
      ta.addEventListener("input", function () {
        var patch = {};
        patch[ta.getAttribute("data-manual-key")] = ta.value;
        writeManual(patch);
      });
    });
  }

  function init() {
    var result = readResult();
    if (!result || !result.sections) {
      $("pv-empty").classList.remove("gen-hidden");
      return;
    }
    render(result);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
