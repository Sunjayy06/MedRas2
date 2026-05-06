/* ============================================================
   Proposal Writing Module — shared state utility
   Mirrors sessionStorage to localStorage so progress survives
   tab close. On a fresh tab, restores the saved state and shows
   a "Welcome back" banner. Also installs a beforeunload guard
   while a long-running operation is in flight.
   ============================================================ */
(function () {
  "use strict";

  var KEY = "medras.proposal.intake";
  var META_KEY = "medras.proposal.meta";
  var BANNER_DISMISS_KEY = "medras.proposal.bannerDismissed";

  // ----- LocalStorage <-> sessionStorage mirror -----------------------------
  function readLocal()  { try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { return null; } }
  function readSession(){ try { return JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch (e) { return null; } }
  function readMeta()   { try { return JSON.parse(localStorage.getItem(META_KEY) || "null"); } catch (e) { return null; } }

  function writeMeta(meta) {
    try { localStorage.setItem(META_KEY, JSON.stringify(meta)); } catch (e) {}
  }

  function mirrorSessionToLocal() {
    var s = readSession();
    if (!s || !Object.keys(s).length) return;
    try {
      localStorage.setItem(KEY, JSON.stringify(s));
      writeMeta({ savedAt: Date.now(), at: window.location.pathname });
    } catch (e) {}
  }

  // Watch sessionStorage for changes initiated by the page's own scripts
  // by re-mirroring on a slow interval. Cheap and robust.
  var lastMirrored = "";
  function tickMirror() {
    var raw = sessionStorage.getItem(KEY) || "";
    if (raw && raw !== lastMirrored) {
      lastMirrored = raw;
      mirrorSessionToLocal();
    }
  }

  // ----- Restore from localStorage on fresh tab -----------------------------
  function restoreFromLocalIfFresh() {
    var s = readSession();
    if (s && Object.keys(s).length) return false;        // session has data → nothing to restore
    var l = readLocal();
    if (!l || !Object.keys(l).length) return false;
    try { sessionStorage.setItem(KEY, JSON.stringify(l)); } catch (e) { return false; }
    return true;
  }

  // ----- Welcome-back banner ------------------------------------------------
  function describeProgress(state) {
    if (!state) return "";
    var bits = [];
    if (state.role)         bits.push("role");
    if (state.langMode)     bits.push("language");
    if (state.format)       bits.push("format");
    if (state.outline)      bits.push("outline");
    if (state.references)   bits.push("references");
    if (!bits.length) return "your previous work";
    if (bits.length === 1) return bits[0];
    return bits.slice(0, -1).join(", ") + " and " + bits[bits.length - 1];
  }

  function relativeTime(ts) {
    if (!ts) return "earlier";
    var s = Math.max(1, Math.floor((Date.now() - ts) / 1000));
    if (s < 60)        return s + "s ago";
    if (s < 3600)      return Math.floor(s / 60) + "m ago";
    if (s < 86400)     return Math.floor(s / 3600) + "h ago";
    return Math.floor(s / 86400) + "d ago";
  }

  function showBanner(state, restored) {
    if (sessionStorage.getItem(BANNER_DISMISS_KEY) === "1") return;
    var meta = readMeta() || {};
    var banner = document.createElement("div");
    banner.className = "prop-welcome-banner";
    banner.setAttribute("role", "status");
    banner.setAttribute("data-testid", "banner-welcome-back");

    var msg = document.createElement("span");
    msg.className = "prop-welcome-msg";
    var prefix = restored ? "👋 Welcome back! We restored " : "👋 Picking up where you left off — ";
    msg.textContent = prefix + describeProgress(state) + " from " + relativeTime(meta.savedAt) + ".";
    banner.appendChild(msg);

    var actions = document.createElement("span");
    actions.className = "prop-welcome-actions";

    var dismiss = document.createElement("button");
    dismiss.type = "button"; dismiss.className = "prop-welcome-dismiss";
    dismiss.textContent = "Got it";
    dismiss.setAttribute("data-testid", "button-banner-dismiss");
    dismiss.addEventListener("click", function () {
      sessionStorage.setItem(BANNER_DISMISS_KEY, "1");
      banner.remove();
    });

    var fresh = document.createElement("button");
    fresh.type = "button"; fresh.className = "prop-welcome-startover";
    fresh.textContent = "Start over";
    fresh.setAttribute("data-testid", "button-banner-startover");
    fresh.addEventListener("click", function () {
      if (!window.confirm("Clear ALL your saved proposal progress and start from Step 1? This can't be undone.")) return;
      try { localStorage.removeItem(KEY); localStorage.removeItem(META_KEY); } catch (e) {}
      try { sessionStorage.removeItem(KEY); sessionStorage.removeItem(BANNER_DISMISS_KEY); } catch (e) {}
      window.location.href = "/proposal-module/role.html";
    });

    actions.appendChild(dismiss);
    actions.appendChild(fresh);
    banner.appendChild(actions);

    function attach() {
      var host = document.querySelector("main.prop-shell") || document.body;
      var stepper = document.querySelector(".prop-stepper");
      if (stepper && stepper.parentNode === host) host.insertBefore(banner, stepper.nextSibling);
      else host.insertBefore(banner, host.firstChild);
    }
    if (document.body) attach();
    else document.addEventListener("DOMContentLoaded", attach);
  }

  // ----- beforeunload guard for in-flight operations ------------------------
  var busyCount = 0;
  function setBusy(v) {
    busyCount = Math.max(0, busyCount + (v ? 1 : -1));
  }
  window.addEventListener("beforeunload", function (e) {
    if (busyCount > 0) {
      var msg = "An AI operation is still running. If you leave now you'll lose the result. Are you sure?";
      e.preventDefault();
      e.returnValue = msg;
      return msg;
    }
  });

  // ----- Public surface -----------------------------------------------------
  window.MedrasProposalState = {
    KEY: KEY,
    mirror: mirrorSessionToLocal,
    setBusy: setBusy,
    clearAll: function () {
      try { localStorage.removeItem(KEY); localStorage.removeItem(META_KEY); } catch (e) {}
      try { sessionStorage.removeItem(KEY); sessionStorage.removeItem(BANNER_DISMISS_KEY); } catch (e) {}
    },
    summarise: describeProgress,
  };

  // ----- Bootstrap ----------------------------------------------------------
  var restored = restoreFromLocalIfFresh();
  var state = readSession();
  if (state && Object.keys(state).length) {
    showBanner(state, restored);
  }
  // Light polling so we always mirror without forcing each page to call us.
  setInterval(tickMirror, 1000);
  window.addEventListener("pagehide", mirrorSessionToLocal);
  window.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") mirrorSessionToLocal();
  });
})();
