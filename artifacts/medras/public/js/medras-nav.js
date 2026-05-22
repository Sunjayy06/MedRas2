/**
 * MedRAS Global Navigation Bar — Phase 7
 *
 * Injects a slim cross-module nav bar above every page's existing header.
 * Pages opt in by adding  data-medras-module="<id>"  to <body>.
 *
 * Module IDs:
 *   helix        Research Assistant (Study Builder)
 *   cohort       Sample Size Calculator
 *   sigma        Statistical Analysis Engine
 *   prologue     Proposal Writing (Prologue)
 *   scriptorium  Thesis & Article Writing
 *   novus        Plagiarism & AI Reduction
 *
 * Session continuity dots:
 *   A filled dot appears next to a module name when that module has an
 *   in-progress session in sessionStorage. This lets the researcher see
 *   at a glance where they left off.
 */
(function () {
  'use strict';

  /* ── Module catalogue ──────────────────────────────────────────── */
  var MODULES = [
    {
      id:    'helix',
      label: 'Helix',
      title: 'Research Assistant',
      url:   '/study-builder/chat.html',
      sessionKey: 'sb.session_id',
    },
    {
      id:    'cohort',
      label: 'Cohort',
      title: 'Sample Size',
      url:   '/sample-size.html',
      sessionKey: null,
    },
    {
      id:    'sigma',
      label: 'Sigma',
      title: 'Statistics',
      url:   '/analysis.html',
      sessionKey: null,
    },
    {
      id:    'prologue',
      label: 'Prologue',
      title: 'Proposal Writer',
      url:   '/proposal-module/',
      sessionKey: 'medras.proposal.intake',
    },
    {
      id:    'scriptorium',
      label: 'Scriptorium',
      title: 'Thesis & Articles',
      url:   '/thesis-module/',
      sessionKey: 'medras.thesis.active',
    },
    {
      id:    'novus',
      label: 'Novus',
      title: 'Plagiarism Check',
      url:   '/plagiarism-module/',
      sessionKey: null,
    },
  ];

  /* ── Detect active module from <body data-medras-module="..."> ── */
  function activeModuleId() {
    return (document.body.getAttribute('data-medras-module') || '').trim();
  }

  /* ── Check whether a module has an in-progress session ─────────── */
  function hasSession(mod) {
    if (!mod.sessionKey) return false;
    try {
      var val = sessionStorage.getItem(mod.sessionKey);
      if (!val) return false;
      if (mod.sessionKey === 'sb.session_id') return val.length > 0;
      var obj = JSON.parse(val);
      return obj && typeof obj === 'object' && Object.keys(obj).length > 0;
    } catch (_) {
      return false;
    }
  }

  /* ── Build and inject the bar ──────────────────────────────────── */
  function buildNav() {
    var active = activeModuleId();

    var bar = document.createElement('div');
    bar.className = 'mn-bar';
    bar.setAttribute('role', 'navigation');
    bar.setAttribute('aria-label', 'MedRAS modules');

    /* Left: wordmark */
    var logo = document.createElement('a');
    logo.className = 'mn-logo';
    logo.href = '/';
    logo.setAttribute('aria-label', 'MedRAS home');
    logo.innerHTML =
      '<span class="mn-logo-mark">M</span>' +
      '<span class="mn-logo-text">MedRAS</span>';
    bar.appendChild(logo);

    /* Centre: module links */
    var list = document.createElement('div');
    list.className = 'mn-modules';

    MODULES.forEach(function (mod) {
      var isActive  = mod.id === active;
      var inSession = hasSession(mod);

      var a = document.createElement('a');
      a.href = mod.url;
      a.className = 'mn-item' + (isActive ? ' mn-item-active' : '');
      a.setAttribute('title', mod.title);
      a.setAttribute('aria-current', isActive ? 'page' : 'false');

      var labelSpan = document.createElement('span');
      labelSpan.textContent = mod.label;
      a.appendChild(labelSpan);

      if (inSession) {
        var dot = document.createElement('span');
        dot.className = 'mn-dot';
        dot.setAttribute('aria-label', 'session in progress');
        a.appendChild(dot);
      }

      /* Don't navigate when already on this page */
      if (isActive) {
        a.addEventListener('click', function (e) {
          e.preventDefault();
          window.scrollTo({ top: 0, behavior: 'smooth' });
        });
      }

      list.appendChild(a);
    });

    bar.appendChild(list);

    /* Right: home link */
    var right = document.createElement('div');
    right.className = 'mn-right';

    var homeLink = document.createElement('a');
    homeLink.href = '/';
    homeLink.className = 'mn-home';
    homeLink.textContent = 'All tools';
    right.appendChild(homeLink);

    bar.appendChild(right);

    /* Insert before <body>'s first child */
    var body = document.body;
    if (body.firstChild) {
      body.insertBefore(bar, body.firstChild);
    } else {
      body.appendChild(bar);
    }

    /* Push all direct children below (except the bar itself) down by
       the bar's height so nothing is hidden underneath it */
    bar.style.position = 'fixed';

    /* We use a CSS class on <html> to tell pages to add top padding */
    document.documentElement.classList.add('mn-active');
  }

  /* ── Run after DOM is ready ─────────────────────────────────────── */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', buildNav);
  } else {
    buildNav();
  }
}());
