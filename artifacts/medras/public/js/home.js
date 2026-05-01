/**
 * MedRAS homepage script.
 *
 * - Hero slider: 6 slides, auto-advance every 4.5s, pause 8s after any
 *   user interaction (click on dot, swipe, drag, etc.). Touch swipe and
 *   mouse drag both work.
 * - Lifecycle rail: mouse-drag to scroll on desktop (touch already works
 *   natively via overflow-x). Visible peek of next card.
 */
(function () {
  "use strict";

  const AUTO_ADVANCE_MS = 4500;
  const INTERACTION_PAUSE_MS = 8000;
  const SWIPE_THRESHOLD_PX = 40;

  document.addEventListener("DOMContentLoaded", function () {
    initHeroSlider();
    initLifecycleDrag();
  });

  /* ----------------------------------------------------------------- */
  /* Hero slider                                                        */
  /* ----------------------------------------------------------------- */
  function initHeroSlider() {
    const root = document.querySelector("[data-slider]");
    if (!root) return;
    const viewport = root.querySelector(".slider-viewport");
    const track = root.querySelector(".slider-track");
    const slides = Array.from(root.querySelectorAll(".slide"));
    const dotsWrap = root.querySelector(".slider-dots");
    if (!track || slides.length === 0) return;

    let index = 0;
    let timer = null;

    // Build dots
    if (dotsWrap) {
      dotsWrap.innerHTML = "";
      slides.forEach(function (_, i) {
        const dot = document.createElement("button");
        dot.type = "button";
        dot.className = "dot" + (i === 0 ? " is-active" : "");
        dot.setAttribute("aria-label", "Show slide " + (i + 1));
        dot.dataset.testid = "slider-dot-" + i;
        dot.addEventListener("click", function () {
          goTo(i);
          markInteraction();
        });
        dotsWrap.appendChild(dot);
      });
    }

    function render() {
      track.style.transform = "translateX(" + (-index * 100) + "%)";
      if (dotsWrap) {
        Array.from(dotsWrap.children).forEach(function (d, i) {
          d.classList.toggle("is-active", i === index);
        });
      }
    }

    function goTo(i) {
      index = (i + slides.length) % slides.length;
      render();
    }

    function next() { goTo(index + 1); }
    function prev() { goTo(index - 1); }

    function start() {
      stop();
      timer = window.setTimeout(function tick() {
        next();
        timer = window.setTimeout(tick, AUTO_ADVANCE_MS);
      }, AUTO_ADVANCE_MS);
    }

    function stop() {
      if (timer) { window.clearTimeout(timer); timer = null; }
    }

    // Pause auto-advance for INTERACTION_PAUSE_MS, then resume.
    function markInteraction() {
      stop();
      timer = window.setTimeout(function () { start(); }, INTERACTION_PAUSE_MS);
    }

    /* ---- Pointer drag / swipe ---- */
    let dragStartX = null;
    let dragLastX = null;
    let dragging = false;
    let pointerId = null;

    function onPointerDown(e) {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      dragStartX = e.clientX;
      dragLastX = e.clientX;
      dragging = true;
      pointerId = e.pointerId;
      track.classList.add("is-dragging");
      try { viewport.setPointerCapture(pointerId); } catch (_) { /* ignore */ }
      markInteraction();
    }

    function onPointerMove(e) {
      if (!dragging) return;
      dragLastX = e.clientX;
      const dx = dragLastX - dragStartX;
      const pct = (dx / viewport.clientWidth) * 100;
      track.style.transform =
        "translateX(calc(" + (-index * 100) + "% + " + pct + "%))";
    }

    function onPointerUp() {
      if (!dragging) return;
      const dx = (dragLastX || 0) - (dragStartX || 0);
      track.classList.remove("is-dragging");
      dragging = false;
      try { viewport.releasePointerCapture(pointerId); } catch (_) { /* ignore */ }
      pointerId = null;
      if (dx <= -SWIPE_THRESHOLD_PX) next();
      else if (dx >= SWIPE_THRESHOLD_PX) prev();
      else render(); // snap back
      markInteraction();
    }

    if (window.PointerEvent) {
      viewport.addEventListener("pointerdown", onPointerDown);
      viewport.addEventListener("pointermove", onPointerMove);
      viewport.addEventListener("pointerup", onPointerUp);
      viewport.addEventListener("pointercancel", onPointerUp);
    }

    // Pause auto-advance when the tab is hidden (saves CPU and avoids
    // the slider racing on a user's first focus return).
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) stop();
      else start();
    });

    // Pause on hover (desktop nicety).
    viewport.addEventListener("mouseenter", function () { markInteraction(); });

    render();
    start();
  }

  /* ----------------------------------------------------------------- */
  /* Lifecycle rail — mouse drag to scroll                              */
  /* ----------------------------------------------------------------- */
  function initLifecycleDrag() {
    const rail = document.querySelector("[data-lifecycle-rail]");
    if (!rail) return;
    let down = false;
    let startX = 0;
    let scrollStart = 0;
    let moved = false;

    rail.addEventListener("mousedown", function (e) {
      down = true;
      moved = false;
      startX = e.clientX;
      scrollStart = rail.scrollLeft;
      rail.style.cursor = "grabbing";
    });
    window.addEventListener("mousemove", function (e) {
      if (!down) return;
      const dx = e.clientX - startX;
      if (Math.abs(dx) > 4) moved = true;
      rail.scrollLeft = scrollStart - dx;
    });
    window.addEventListener("mouseup", function () {
      down = false;
      rail.style.cursor = "";
    });
    // Suppress accidental click on a card after a drag.
    rail.addEventListener("click", function (e) {
      if (moved) {
        e.preventDefault();
        e.stopPropagation();
      }
    }, true);
  }
})();
