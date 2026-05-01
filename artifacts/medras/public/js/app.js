/**
 * MedRAS shared frontend script.
 *
 * Currently only a thin foundation: smooth in-page scroll for anchor links
 * and a connectivity ping to the backend. Module-specific logic will live in
 * separate per-module scripts loaded from their respective HTML pages.
 */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    enableSmoothAnchors();
    blockDisabledAnchors();
  });

  // Anchors marked aria-disabled="true" (planned modules in the orbit) must
  // NOT navigate or hash-jump on click / Enter / Space — they are visual-only
  // placeholders. Native <a> elements ignore aria-disabled, so we cancel
  // activation here.
  function blockDisabledAnchors() {
    var disabled = document.querySelectorAll('a[aria-disabled="true"]');
    disabled.forEach(function (a) {
      a.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
      });
      a.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
          e.preventDefault();
        }
      });
    });
  }

  function enableSmoothAnchors() {
    var links = document.querySelectorAll('a[href^="#"]');
    links.forEach(function (link) {
      link.addEventListener("click", function (event) {
        var hash = link.getAttribute("href");
        if (!hash || hash === "#") return;
        var target = document.querySelector(hash);
        if (!target) return;
        event.preventDefault();
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

})();
