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
    pingBackend();
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

  function pingBackend() {
    var statusEl = document.querySelector('[data-testid="text-status"]');
    if (!statusEl) return;
    fetch("/api/readyz", { headers: { Accept: "application/json" } })
      .then(function (response) {
        if (!response.ok) throw new Error("readyz " + response.status);
        return response.json();
      })
      .then(function (data) {
        var integrations = data && data.integrations ? data.integrations : {};
        var notes = [];
        if (!integrations.openai) notes.push("OpenAI key missing");
        if (!integrations.copyleaks) notes.push("Copyleaks credentials missing");
        var statusText = notes.length
          ? "Foundation ready \u00b7 " + notes.join(" \u00b7 ")
          : "Foundation ready \u00b7 all integrations connected";
        var dot = statusEl.querySelector(".status-dot");
        statusEl.textContent = "";
        if (dot) statusEl.appendChild(dot);
        statusEl.appendChild(document.createTextNode(" " + statusText));
      })
      .catch(function () {
        /* Silent: status defaults to its initial markup. */
      });
  }
})();
