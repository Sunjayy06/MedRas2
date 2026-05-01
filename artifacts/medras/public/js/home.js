/**
 * MedRAS homepage script.
 *
 * - Hero slider: 6 slides. First auto-advance is delayed by
 *   INITIAL_AUTOPLAY_DELAY_MS so visitors can read slide 1; subsequent
 *   ticks fire every AUTO_ADVANCE_MS. Any interaction (arrow / dot /
 *   swipe) pauses autoplay for INTERACTION_PAUSE_MS. Buttons are
 *   debounced for CLICK_DEBOUNCE_MS to swallow synthetic double-clicks.
 *   Autoplay is disabled entirely when the user prefers reduced motion.
 * - Modules feature carousel: prev/next arrow buttons (scroll one card
 *   at a time), mouse drag-to-scroll, native touch scroll. Arrow
 *   disabled state is driven by an IntersectionObserver on the first /
 *   last child cards (no fragile scrollLeft math).
 * - Dashboard preview slider: same arrow + drag mechanics as the
 *   modules carousel.
 * - Lifecycle rail: mouse-drag to scroll on desktop (touch already works
 *   via overflow-x).
 */
(function () {
  "use strict";

  const AUTO_ADVANCE_MS = 7500;
  const INTERACTION_PAUSE_MS = 12000;
  const SWIPE_THRESHOLD_PX = 40;
  // Wait this long after page load before auto-advance kicks in. Gives
  // the visitor time to read the first slide and avoids racing with
  // automated test runners.
  const INITIAL_AUTOPLAY_DELAY_MS = 8000;
  // Ignore subsequent button clicks that fire within this many ms of the
  // last one. Defends against synthetic double-clicks (focus + click,
  // touchstart + click, etc.).
  const CLICK_DEBOUNCE_MS = 250;

  document.addEventListener("DOMContentLoaded", function () {
    initHeroSlider();
    initLifecycleDrag();
    document.querySelectorAll("[data-rail]").forEach(initRailCarousel);
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
    const prevBtn = root.querySelector("[data-slider-prev]");
    const nextBtn = root.querySelector("[data-slider-next]");
    if (!track || slides.length === 0) return;

    let index = 0;
    let timer = null;

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
      slides.forEach(function (s, i) {
        s.classList.toggle("is-active", i === index);
      });
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

    function markInteraction() {
      stop();
      timer = window.setTimeout(function () { start(); }, INTERACTION_PAUSE_MS);
    }

    let lastClickAt = 0;
    function handleNavClick(direction) {
      const now = Date.now();
      if (now - lastClickAt < CLICK_DEBOUNCE_MS) return;
      lastClickAt = now;
      stop();
      if (direction === "next") next();
      else prev();
      markInteraction();
    }

    if (prevBtn) {
      prevBtn.addEventListener("click", function () { handleNavClick("prev"); });
    }
    if (nextBtn) {
      nextBtn.addEventListener("click", function () { handleNavClick("next"); });
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
      else render();
      markInteraction();
    }

    if (window.PointerEvent) {
      viewport.addEventListener("pointerdown", onPointerDown);
      viewport.addEventListener("pointermove", onPointerMove);
      viewport.addEventListener("pointerup", onPointerUp);
      viewport.addEventListener("pointercancel", onPointerUp);
    }

    document.addEventListener("visibilitychange", function () {
      if (document.hidden) stop();
      else if (timer === null) {
        timer = window.setTimeout(function () { start(); }, INTERACTION_PAUSE_MS);
      }
    });

    render();
    // Skip autoplay entirely when the visitor prefers reduced motion.
    const reduceMotion =
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!reduceMotion) {
      // Defer the first auto-advance so the visitor has time to read the
      // first slide and so automated tests have a stable initial state.
      timer = window.setTimeout(function () { start(); }, INITIAL_AUTOPLAY_DELAY_MS);
    }
  }

  /* ----------------------------------------------------------------- */
  /* Lifecycle rail — mouse drag to scroll                              */
  /* ----------------------------------------------------------------- */
  function initLifecycleDrag() {
    const rail = document.querySelector("[data-lifecycle-rail]");
    if (!rail) return;
    enableDragScroll(rail);
  }

  /* ----------------------------------------------------------------- */
  /* Generic scroll-rail carousel with prev/next arrow buttons          */
  /* ----------------------------------------------------------------- */
  function initRailCarousel(rail) {
    enableDragScroll(rail);

    const id = rail.getAttribute("data-rail");
    const prevBtn = document.querySelector('[data-rail-prev="' + id + '"]');
    const nextBtn = document.querySelector('[data-rail-next="' + id + '"]');

    function step() {
      const card = rail.querySelector(":scope > *");
      const gap = parseFloat(getComputedStyle(rail).columnGap || "0") || 18;
      return (card ? card.getBoundingClientRect().width : 280) + gap;
    }

    if (prevBtn) {
      prevBtn.addEventListener("click", function () {
        rail.scrollBy({ left: -step(), behavior: "smooth" });
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener("click", function () {
        rail.scrollBy({ left: step(), behavior: "smooth" });
      });
    }

    // Use IntersectionObserver on the first and last child cards for
    // reliable edge detection. This fires on initial layout and on every
    // scroll, with no fragile scrollLeft math or timing assumptions.
    const cards = rail.children;
    if (cards.length === 0 || typeof window.IntersectionObserver !== "function") {
      return;
    }
    const first = cards[0];
    const last = cards[cards.length - 1];

    const io = new window.IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.target === first && prevBtn) {
            prevBtn.toggleAttribute("disabled", entry.isIntersecting);
          }
          if (entry.target === last && nextBtn) {
            nextBtn.toggleAttribute("disabled", entry.isIntersecting);
          }
        });
      },
      { root: rail, threshold: 0.9 }
    );
    io.observe(first);
    io.observe(last);
  }

  /* ----------------------------------------------------------------- */
  /* Mouse drag-to-scroll for any horizontal rail                       */
  /* ----------------------------------------------------------------- */
  function enableDragScroll(rail) {
    let down = false;
    let startX = 0;
    let scrollStart = 0;
    let moved = false;

    rail.addEventListener("mousedown", function (e) {
      // Don't start a drag on a clickable card if the user clicked it.
      if (e.button !== 0) return;
      down = true;
      moved = false;
      startX = e.clientX;
      scrollStart = rail.scrollLeft;
      rail.classList.add("is-grabbing");
    });
    window.addEventListener("mousemove", function (e) {
      if (!down) return;
      const dx = e.clientX - startX;
      if (Math.abs(dx) > 4) moved = true;
      rail.scrollLeft = scrollStart - dx;
    });
    window.addEventListener("mouseup", function () {
      down = false;
      rail.classList.remove("is-grabbing");
    });
    rail.addEventListener(
      "click",
      function (e) {
        if (moved) {
          e.preventDefault();
          e.stopPropagation();
        }
      },
      true
    );
  }
})();
