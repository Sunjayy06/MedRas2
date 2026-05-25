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
    {
      id:    'folio',
      label: 'Folio',
      title: 'Document Management',
      url:   '/folio-module/',
      sessionKey: 'folio.doc',
    },
    {
      id:      'compass',
      label:   'Compass',
      title:   'Journal Finder — Coming soon',
      url:     null,
      sessionKey: null,
      soon:    true,
    },
    {
      id:      'fieldwork',
      label:   'Fieldwork',
      title:   'Data Collection — Coming soon',
      url:     null,
      sessionKey: null,
      soon:    true,
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

      var a = document.createElement(mod.soon ? 'span' : 'a');
      if (!mod.soon) a.href = mod.url;
      a.className = 'mn-item' +
        (isActive ? ' mn-item-active' : '') +
        (mod.soon ? ' mn-item-soon' : '');
      a.setAttribute('title', mod.title);
      if (!mod.soon) a.setAttribute('aria-current', isActive ? 'page' : 'false');

      var labelSpan = document.createElement('span');
      labelSpan.textContent = mod.label;
      a.appendChild(labelSpan);

      if (mod.soon) {
        var pill = document.createElement('span');
        pill.className = 'mn-soon-pill';
        pill.textContent = 'soon';
        a.appendChild(pill);
      }

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

    /* ── Global feedback widget ─────────────────────────────────────── */
    _buildFeedbackWidget();

    /* ── Running-jobs badge ─────────────────────────────────────────── */
    _buildJobsBadge();
  }

  function _buildFeedbackWidget() {
    /* Styles */
    var style = document.createElement('style');
    style.textContent = [
      '.mn-fb-btn{position:fixed;bottom:22px;right:22px;z-index:9998;',
      'background:#1a2e5a;color:#e6eefb;border:none;border-radius:999px;',
      'padding:9px 16px;font-size:13px;font-weight:600;cursor:pointer;',
      'box-shadow:0 4px 16px rgba(0,0,0,.35);transition:background .15s;}',
      '.mn-fb-btn:hover{background:#243e78;}',
      '.mn-fb-panel{position:fixed;bottom:68px;right:22px;z-index:9999;',
      'width:320px;background:#fff;border-radius:14px;',
      'box-shadow:0 8px 32px rgba(0,0,0,.22);padding:20px;',
      'display:none;flex-direction:column;gap:10px;}',
      '.mn-fb-panel.is-open{display:flex;}',
      '.mn-fb-title{font-size:15px;font-weight:700;color:#1a2e5a;margin:0;}',
      '.mn-fb-sub{font-size:12px;color:#6b7280;margin:0;}',
      '.mn-fb-label{font-size:11px;font-weight:600;color:#374151;',
      'text-transform:uppercase;letter-spacing:.05em;}',
      '.mn-fb-select,.mn-fb-textarea,.mn-fb-input{width:100%;box-sizing:border-box;',
      'padding:7px 10px;border:1.5px solid #dde3f0;border-radius:8px;',
      'font-family:inherit;font-size:13px;color:#1a2e5a;background:#f8f9fc;}',
      '.mn-fb-textarea{resize:vertical;min-height:88px;}',
      '.mn-fb-row{display:flex;gap:8px;}',
      '.mn-fb-submit{flex:1;padding:9px;background:#1a2e5a;color:#fff;',
      'border:none;border-radius:8px;font-weight:600;font-size:13px;cursor:pointer;}',
      '.mn-fb-submit:hover{background:#243e78;}',
      '.mn-fb-submit:disabled{opacity:.55;cursor:not-allowed;}',
      '.mn-fb-cancel{padding:9px 14px;background:#f1f5f9;color:#374151;',
      'border:none;border-radius:8px;font-size:13px;cursor:pointer;}',
      '.mn-fb-ok{font-size:13px;color:#1a6e3a;font-weight:600;text-align:center;',
      'padding:6px 0;}',
    ].join('');
    document.head.appendChild(style);

    /* Floating button */
    var btn = document.createElement('button');
    btn.className = 'mn-fb-btn';
    btn.setAttribute('aria-label', 'Send feedback');
    btn.textContent = '💬 Feedback';

    /* Panel */
    var panel = document.createElement('div');
    panel.className = 'mn-fb-panel';

    /* Auto-detect module */
    var modId = (document.body && document.body.dataset && document.body.dataset.medrasModule) || '';
    var modLabels = {
      helix:'Helix (Study Builder)', cohort:'Cohort (Sample Size)',
      sigma:'Sigma (Statistics)', prologue:'Prologue (Proposal)',
      scriptorium:'Scriptorium (Thesis / Article)',
      novus:'Novus (Plagiarism & AI)', folio:'Folio (Document Polish)',
    };

    panel.innerHTML = [
      '<p class="mn-fb-title">Share your feedback</p>',
      '<p class="mn-fb-sub">Tell us what\'s working, what\'s broken, or what you\'d love to see. We read every message.</p>',
      '<div>',
        '<label class="mn-fb-label">Module</label>',
        '<select class="mn-fb-select" id="mn-fb-module">',
          '<option value="">— whole platform —</option>',
          Object.entries(modLabels).map(function(e){
            return '<option value="'+e[0]+'"'+(e[0]===modId?' selected':'')+'>'+e[1]+'</option>';
          }).join(''),
        '</select>',
      '</div>',
      '<div>',
        '<label class="mn-fb-label">What can we improve?</label>',
        '<textarea class="mn-fb-textarea" id="mn-fb-message" placeholder="e.g. The outline modal closes unexpectedly when I press Esc while typing…"></textarea>',
      '</div>',
      '<div>',
        '<label class="mn-fb-label">Your email <span style="font-weight:400;text-transform:none;">(optional — only if you want a reply)</span></label>',
        '<input class="mn-fb-input" id="mn-fb-email" type="email" placeholder="you@example.com" />',
      '</div>',
      '<div class="mn-fb-row">',
        '<button class="mn-fb-cancel" id="mn-fb-cancel">Cancel</button>',
        '<button class="mn-fb-submit" id="mn-fb-submit">Send feedback</button>',
      '</div>',
      '<div class="mn-fb-ok" id="mn-fb-ok" style="display:none;">✓ Sent — thank you!</div>',
    ].join('');

    document.body.appendChild(btn);
    document.body.appendChild(panel);

    /* Toggle */
    btn.addEventListener('click', function () {
      panel.classList.toggle('is-open');
      if (panel.classList.contains('is-open')) {
        setTimeout(function () {
          var ta = document.getElementById('mn-fb-message');
          if (ta) ta.focus();
        }, 50);
      }
    });

    /* Cancel */
    document.getElementById('mn-fb-cancel').addEventListener('click', function () {
      panel.classList.remove('is-open');
    });

    /* Submit */
    document.getElementById('mn-fb-submit').addEventListener('click', function () {
      var msgEl  = document.getElementById('mn-fb-message');
      var modEl  = document.getElementById('mn-fb-module');
      var emlEl  = document.getElementById('mn-fb-email');
      var okEl   = document.getElementById('mn-fb-ok');
      var subBtn = document.getElementById('mn-fb-submit');
      var msg    = msgEl ? msgEl.value.trim() : '';
      if (!msg) { if (msgEl) { msgEl.style.borderColor = '#e74c3c'; msgEl.focus(); } return; }
      if (msgEl) msgEl.style.borderColor = '';
      subBtn.disabled = true;
      subBtn.textContent = 'Sending…';
      fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: msg,
          module:  modEl  ? (modEl.value  || null) : null,
          page:    window.location.pathname,
          email:   emlEl  ? (emlEl.value.trim() || null) : null,
        }),
      })
        .then(function (r) { return r.json(); })
        .then(function () {
          if (msgEl) msgEl.value = '';
          if (okEl) { okEl.style.display = ''; }
          subBtn.textContent = 'Send feedback';
          subBtn.disabled = false;
          setTimeout(function () {
            panel.classList.remove('is-open');
            if (okEl) okEl.style.display = 'none';
          }, 2200);
        })
        .catch(function () {
          subBtn.textContent = 'Send feedback';
          subBtn.disabled = false;
          alert('Could not send feedback. Please try again.');
        });
    });
  }

  /* ── Running-jobs badge system ──────────────────────────────────── */
  var JOBS_KEY = 'medras.running_jobs';
  var _jobsBadgeEl = null;

  function _parseJobs() {
    try {
      var raw = localStorage.getItem(JOBS_KEY);
      if (!raw) return [];
      var arr = JSON.parse(raw);
      /* Auto-expire jobs older than 10 minutes (stale from crashed tab) */
      var now = Date.now();
      return arr.filter(function(j) { return now - (j.started || 0) < 600000; });
    } catch (_) { return []; }
  }

  function _saveJobs(arr) {
    try { localStorage.setItem(JOBS_KEY, JSON.stringify(arr)); } catch (_) {}
  }

  function _renderJobsBadge() {
    if (!_jobsBadgeEl) return;
    var jobs = _parseJobs();
    if (jobs.length === 0) {
      _jobsBadgeEl.style.display = 'none';
    } else {
      _jobsBadgeEl.style.display = 'flex';
      var label = jobs.length === 1 ? jobs[0].label : (jobs.length + ' tasks running');
      _jobsBadgeEl.querySelector('.mn-jobs-lbl').textContent = label;
    }
  }

  function _buildJobsBadge() {
    var style = document.createElement('style');
    style.textContent = [
      '@keyframes mn-jog{0%,100%{opacity:1}50%{opacity:.35}}',
      '.mn-jobs-badge{position:fixed;bottom:22px;left:22px;z-index:9997;',
        'display:none;align-items:center;gap:7px;',
        'background:#0f2040;color:#c7d9f5;border-radius:999px;',
        'padding:8px 15px 8px 11px;font-size:12px;font-weight:600;',
        'box-shadow:0 4px 18px rgba(0,0,0,.4);pointer-events:none;',
        'transition:opacity .25s;}',
      '.mn-jobs-dot{width:8px;height:8px;border-radius:50%;',
        'background:#60a5fa;flex-shrink:0;',
        'animation:mn-jog 1.1s ease-in-out infinite;}',
    ].join('');
    document.head.appendChild(style);

    var badge = document.createElement('div');
    badge.className = 'mn-jobs-badge';
    badge.setAttribute('role', 'status');
    badge.setAttribute('aria-live', 'polite');
    badge.innerHTML = '<div class="mn-jobs-dot"></div><span class="mn-jobs-lbl"></span>';
    document.body.appendChild(badge);
    _jobsBadgeEl = badge;
    _renderJobsBadge();

    /* Poll every 2.5 s in case another tab updates the job list */
    setInterval(_renderJobsBadge, 2500);

    /* React immediately to cross-tab localStorage changes */
    window.addEventListener('storage', function (e) {
      if (e.key === JOBS_KEY) _renderJobsBadge();
    });
  }

  /**
   * MedrasJobs — public API available on every page that loads medras-nav.js
   *
   *   window.MedrasJobs.start('sigma-analysis', 'Running analysis…')
   *   window.MedrasJobs.finish('sigma-analysis')
   *   window.MedrasJobs.finishAll()
   */
  window.MedrasJobs = {
    start: function (id, label) {
      var jobs = _parseJobs().filter(function (j) { return j.id !== id; });
      jobs.push({ id: id, label: label || 'Processing…', started: Date.now() });
      _saveJobs(jobs);
      _renderJobsBadge();
    },
    finish: function (id) {
      var jobs = _parseJobs().filter(function (j) { return j.id !== id; });
      _saveJobs(jobs);
      _renderJobsBadge();
    },
    finishAll: function () {
      _saveJobs([]);
      _renderJobsBadge();
    },
  };

  /* ── Run after DOM is ready ─────────────────────────────────────── */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', buildNav);
  } else {
    buildNav();
  }
}());
