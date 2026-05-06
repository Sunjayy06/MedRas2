/* ============================================================
   Proposal Writing Module — intake (role + language)
   ============================================================ */
(function () {
  "use strict";

  var STORAGE_KEY = "medras.proposal.intake";

  var ROLE_LABELS = {
    ug: "UG Student",
    pg: "PG or Resident",
    phd: "PhD Researcher",
    cti: "Clinical Trial Investigator",
    faculty: "Faculty or Institution",
    indep: "Independent Researcher",
  };

  var LANG_LABELS = {
    hi: "Hindi", ta: "Tamil", te: "Telugu", kn: "Kannada", ml: "Malayalam",
    mr: "Marathi", bn: "Bengali", gu: "Gujarati", pa: "Punjabi", other: "Other",
  };

  function readState() {
    try {
      var raw = sessionStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (e) {
      return {};
    }
  }

  function writeState(patch) {
    var current = readState();
    var next = Object.assign({}, current, patch);
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch (e) { /* sessionStorage disabled — non-fatal */ }
    return next;
  }

  // ===================== Role page =====================
  function initRolePage() {
    var cards = document.querySelectorAll(".prop-role-card");
    var nextBtn = document.getElementById("prop-role-next");
    if (!cards.length || !nextBtn) return;

    var saved = readState();
    var selected = saved.role || null;

    function applySelection() {
      cards.forEach(function (card) {
        var isSel = card.getAttribute("data-role") === selected;
        card.classList.toggle("is-selected", isSel);
        card.setAttribute("aria-pressed", isSel ? "true" : "false");
      });
      nextBtn.disabled = !selected;
    }

    cards.forEach(function (card) {
      card.setAttribute("role", "radio");
      card.setAttribute("aria-pressed", "false");
      card.addEventListener("click", function () {
        selected = card.getAttribute("data-role");
        applySelection();
      });
    });

    nextBtn.addEventListener("click", function () {
      if (!selected) return;
      writeState({
        role: selected,
        roleLabel: ROLE_LABELS[selected] || selected,
      });
      window.location.href = "/proposal-module/language.html";
    });

    applySelection();
  }

  // ===================== Language page =====================
  function initLanguagePage() {
    var cards = document.querySelectorAll(".prop-lang-card");
    var nextBtn = document.getElementById("prop-lang-next");
    var sel = document.getElementById("prop-second-lang");
    var otherInput = document.getElementById("prop-second-lang-other");
    var roleRecall = document.getElementById("prop-role-recall");
    if (!cards.length || !nextBtn) return;

    // If user landed here without picking a role, send them back.
    var saved = readState();
    if (!saved.role) {
      window.location.replace("/proposal-module/role.html");
      return;
    }

    if (roleRecall) {
      var strong = roleRecall.querySelector("strong");
      var label = saved.roleLabel || ROLE_LABELS[saved.role] || saved.role;
      if (strong) strong.textContent = label;
      roleRecall.hidden = false;
    }

    var mode = saved.langMode || null;
    var secondLang = saved.secondLang || "";
    var secondLangOther = saved.secondLangOther || "";

    if (sel && secondLang) sel.value = secondLang;
    if (otherInput && secondLangOther) otherInput.value = secondLangOther;

    function isValid() {
      if (mode === "english") return true;
      if (mode === "bilingual") {
        if (!secondLang) return false;
        if (secondLang === "other" && !secondLangOther.trim()) return false;
        return true;
      }
      return false;
    }

    function syncOtherVisibility() {
      if (!otherInput) return;
      otherInput.hidden = !(mode === "bilingual" && secondLang === "other");
    }

    function applySelection() {
      cards.forEach(function (card) {
        var isSel = card.getAttribute("data-lang-mode") === mode;
        card.classList.toggle("is-selected", isSel);
        card.setAttribute("aria-checked", isSel ? "true" : "false");
      });
      syncOtherVisibility();
      nextBtn.disabled = !isValid();
    }

    function selectCard(card) {
      mode = card.getAttribute("data-lang-mode");
      applySelection();
    }

    cards.forEach(function (card) {
      card.addEventListener("click", function (ev) {
        // Don't reselect when interacting with the dropdown / input inside the card.
        var tag = (ev.target.tagName || "").toLowerCase();
        if (tag === "select" || tag === "input" || tag === "label" || tag === "option") return;
        selectCard(card);
      });
      card.addEventListener("keydown", function (ev) {
        if (ev.key === " " || ev.key === "Enter") {
          var tag = (ev.target.tagName || "").toLowerCase();
          if (tag === "select" || tag === "input") return;
          ev.preventDefault();
          selectCard(card);
        }
      });
    });

    if (sel) {
      sel.addEventListener("change", function () {
        // Choosing from the dropdown implies bilingual mode.
        mode = "bilingual";
        secondLang = sel.value;
        if (secondLang !== "other") secondLangOther = "";
        applySelection();
      });
      sel.addEventListener("click", function (ev) { ev.stopPropagation(); });
    }
    if (otherInput) {
      otherInput.addEventListener("input", function () {
        secondLangOther = otherInput.value;
        applySelection();
      });
      otherInput.addEventListener("click", function (ev) { ev.stopPropagation(); });
    }

    nextBtn.addEventListener("click", function () {
      if (!isValid()) return;
      var payload = { langMode: mode };
      if (mode === "bilingual") {
        payload.secondLang = secondLang;
        payload.secondLangLabel = secondLang === "other"
          ? secondLangOther.trim()
          : (LANG_LABELS[secondLang] || secondLang);
        payload.secondLangOther = secondLang === "other" ? secondLangOther.trim() : "";
      } else {
        payload.secondLang = "";
        payload.secondLangLabel = "";
        payload.secondLangOther = "";
      }
      writeState(payload);
      window.location.href = "/proposal-module/format.html";
    });

    applySelection();
  }

  // ===================== Boot =====================
  document.addEventListener("DOMContentLoaded", function () {
    if (document.body.dataset.testid === "page-prop-role") initRolePage();
    if (document.body.dataset.testid === "page-prop-language") initLanguagePage();
  });
})();
