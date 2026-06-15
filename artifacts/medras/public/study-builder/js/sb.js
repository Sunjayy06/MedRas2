/* MedRAS Research Assistant — sb.js  (Phase 3: PDF chunked upload) */
(function () {
  'use strict';

  /* ── DOM ── */
  const welcome              = document.getElementById('welcome');
  const thread               = document.getElementById('thread');
  const chatBar              = document.getElementById('chat-bar');
  const welcomeInp           = document.getElementById('welcome-input');
  const welcomeSend          = document.getElementById('welcome-send');
  const chatInp              = document.getElementById('chat-input');
  const chatSend             = document.getElementById('chat-send');
  const dbStrip              = document.getElementById('db-strip');
  const newChatBtn           = document.getElementById('new-chat-btn');
  const raWrap               = document.getElementById('ra-wrap');
  const attachBtn            = document.getElementById('attach-btn');
  const fileInput            = document.getElementById('file-input');

  /* PDF pill elements (in input bar) */
  const pdfInputPill = document.getElementById('pdf-input-pill');
  const pipName      = document.getElementById('pip-name');
  const pipPages     = document.getElementById('pip-pages');
  const pipClear     = document.getElementById('pip-clear');

  /* ── Folio DOM ── */
  const folioPanelEl   = document.getElementById('folio-panel');
  const folioToggleBtn = document.getElementById('folio-toggle-btn');
  const folioBadge     = document.getElementById('folio-badge');
  const folioCount     = document.getElementById('folio-count');
  const folioCloseBtn  = document.getElementById('folio-close-btn');
  const folioList      = document.getElementById('folio-list');
  const folioEmpty     = document.getElementById('folio-empty');
  const folioFoot      = document.getElementById('folio-foot');

  /* ── Copy-all DOM ── */
  const copyAllWrap  = document.getElementById('copy-all-wrap');
  const copyAllVan   = document.getElementById('copy-all-van');
  const copyAllApa   = document.getElementById('copy-all-apa');

  /* ── Labels ── */
  const SRC_LABELS = {
    pubmed:'PubMed', cochrane:'Cochrane', europe_pmc:'Europe PMC',
    pmc:'PubMed Central', semantic_scholar:'Semantic Scholar',
    openalex:'OpenAlex', who_iris:'WHO IRIS', crossref:'Crossref',
    core:'CORE', medrxiv:'medRxiv', clinicaltrials:'ClinicalTrials.gov',
    doaj:'DOAJ', lens:'Lens.org', ieee:'IEEE Xplore',
    wos:'Web of Science', scopus:'Scopus',
    uploaded:'Your uploaded paper',
    uploaded_pdf:'Uploaded PDF',
  };
  const EV_LABELS = {
    systematic_review:'Sys. Review', rct:'RCT',
    observational:'Observational', guideline:'Guideline',
    uploaded:'Uploaded Paper', uploaded_pdf:'Uploaded PDF',
  };
  const GRADE_META = {
    HIGH:      { cls:'grade-high',     label:'HIGH EVIDENCE',      icon:'◆' },
    MODERATE:  { cls:'grade-moderate', label:'MODERATE EVIDENCE',  icon:'◈' },
    LOW:       { cls:'grade-low',      label:'LOW EVIDENCE',       icon:'◇' },
    'VERY LOW':{ cls:'grade-verylow',  label:'VERY LOW EVIDENCE',  icon:'○' },
  };

  /* ── Statistical test patterns (Phase 6) ── */
  const _STAT_TESTS = [
    { re: /\bt[\s-]test\b|student.s\s+t[\s-]test/i,              name: 't-test'              },
    { re: /\bchi[\s-]?square\b|χ²|chi.squared\b/i,               name: 'chi-square'          },
    { re: /\banova\b/i,                                           name: 'ANOVA'               },
    { re: /\bmann[\s-]whitney\b|\bwilcoxon\b/i,                   name: 'Mann-Whitney'        },
    { re: /\blogistic\s+regression\b/i,                           name: 'logistic regression' },
    { re: /\blinear\s+regression\b/i,                             name: 'linear regression'   },
    { re: /\bcox\s+(?:regression|model)\b/i,                      name: 'Cox regression'      },
    { re: /\bkaplan[\s-]meier\b|\bsurvival\s+analysis\b/i,        name: 'Kaplan-Meier'        },
    { re: /\bpearson\b|\bspearman\b|\bcorrelation\s+analysis\b/i, name: 'correlation'         },
    { re: /\broc\s+(?:curve|analysis)\b|\bauroc\b/i,              name: 'ROC analysis'        },
    { re: /\bkruskal[\s-]wallis\b/i,                              name: 'Kruskal-Wallis'      },
    { re: /\bmcnemar\b|\bfisher.s\s+exact\b/i,                   name: "Fisher's exact"      },
  ];

  /* ── Session & upload state ── */
  let sessionId      = sessionStorage.getItem('sb.session_id') || null;
  let busy           = false;
  let inChat         = false;
  let uploading      = false;

  /* PDF state — at most 1 PDF per session */
  let pdfAttached    = false;   /* true when a PDF is stored in the session */

  /* ── Folio state (persisted to sessionStorage) ── */
  let folioItems = JSON.parse(sessionStorage.getItem('sb.folio') || '[]');

  /* ── Conversation-wide citation tracking ── */
  /* Key: normalised DOI (preferred) or lowercased title */
  const convPapersMap = new Map();

  /* ── Export dropdown state — only one open at a time ── */
  let _openExportDd = null;

  /* ── Statistical highlight regex ── */
  const STAT_RE = /(\bp\s*[<>=≤≥]\s*0\.\d+\b|\bOR\s+[\d.]+\b|\bRR\s+[\d.]+\b|\bHR\s+[\d.]+\b|\bNNT\s+\d+\b|\bARR\s+[\d.]+%?\b|\bRRR\s+[\d.]+%?\b|95\s*%\s*CI[^,;.]{0,30}|\bCIs?\b\s*[\[(][\d., –\-]+[\])]|\bn\s*=\s*[\d,]+\b|\bN\s*=\s*[\d,]+\b|[\d.]+\s*%\s*(?:reduction|increase|improvement|decrease|sensitivity|specificity|accuracy)|\bSMD\s+[\d.]+\b|\bWMD\s+[\d.]+\b|\bMD\s+[\d.]+\b|\baOR\s+[\d.]+\b)/gi;

  /* ── Loading stage messages ── */
  const STAGES = [
    'Searching 16 databases\u2026',
    'Extracting key findings\u2026',
    'Synthesising answer\u2026',
  ];

  /* ── Input auto-resize ── */
  function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 130) + 'px';
  }
  welcomeInp.addEventListener('input', () => autoResize(welcomeInp));
  chatInp.addEventListener('input',   () => autoResize(chatInp));

  /* ── Keyboard shortcuts ── */
  welcomeInp.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitFromWelcome(); }
  });
  chatInp.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitFromChat(); }
  });
  welcomeSend.addEventListener('click', submitFromWelcome);
  chatSend.addEventListener('click',   submitFromChat);

  /* ── Topic cards ── */
  document.querySelectorAll('.topic-card').forEach((btn) => {
    btn.addEventListener('click', () => {
      welcomeInp.value = btn.dataset.q;
      submitFromWelcome();
    });
  });

  /* ── Attach button → triggers PDF file picker ── */
  attachBtn.addEventListener('click', () => {
    if (!inChat || !sessionId) {
      chatInp.focus();
      const orig = chatInp.placeholder;
      chatInp.placeholder = 'Ask a question first to start a session, then attach a PDF.';
      setTimeout(() => { chatInp.placeholder = orig; }, 3000);
      return;
    }
    if (uploading) return;
    fileInput.click();
  });

  fileInput.addEventListener('change', () => {
    const file = fileInput.files[0];
    fileInput.value = '';   /* reset so same file can be re-selected */
    if (file) uploadPdf(file);
  });

  /* ── PDF pill clear button ── */
  pipClear.addEventListener('click', clearPdf);

  /* ── New chat ── */
  newChatBtn.addEventListener('click', () => {
    thread.innerHTML = '';
    sessionId      = null;
    pdfAttached    = false;
    uploading      = false;
    folioItems     = [];
    convPapersMap.clear();
    if (copyAllWrap) copyAllWrap.style.display = 'none';
    sessionStorage.removeItem('sb.session_id');
    sessionStorage.removeItem('medras.nav.returnHint');
    sessionStorage.removeItem('sb.folio');
    updatePdfPill(null);
    _renderFolio();
    _updateFolioToggle();
    folioPanelEl.classList.remove('open');
    switchToWelcome();
  });

  /* ── Folio toggle / close ── */
  folioToggleBtn.addEventListener('click', () => folioPanelEl.classList.toggle('open'));
  folioCloseBtn.addEventListener('click',  () => folioPanelEl.classList.remove('open'));

  /* ── Folio export buttons ── */
  document.getElementById('folio-exp-bibtex').addEventListener('click', () =>
    _dlText('folio-citations.bib', _toBibtex(folioItems)));
  document.getElementById('folio-exp-ris').addEventListener('click', () =>
    _dlText('folio-citations.ris', _toRis(folioItems)));
  document.getElementById('folio-exp-van').addEventListener('click', () =>
    _dlText('folio-citations.txt', _toVancouver(folioItems)));
  document.getElementById('folio-exp-apa').addEventListener('click', () =>
    _dlText('folio-citations-apa.txt', _toApa(folioItems)));
  document.getElementById('folio-copy-van').addEventListener('click', () => {
    const btn = document.getElementById('folio-copy-van');
    navigator.clipboard.writeText(_toVancouver(folioItems))
      .then(() => {
        btn.textContent = 'Copied \u2713';
        setTimeout(() => { btn.textContent = 'Copy Vancouver'; }, 2200);
      })
      .catch(() => _dlText('folio-citations.txt', _toVancouver(folioItems)));
  });
  document.getElementById('folio-copy-apa').addEventListener('click', () => {
    const btn = document.getElementById('folio-copy-apa');
    navigator.clipboard.writeText(_toApa(folioItems))
      .then(() => {
        btn.textContent = 'Copied \u2713';
        setTimeout(() => { btn.textContent = 'Copy APA'; }, 2200);
      })
      .catch(() => _dlText('folio-citations-apa.txt', _toApa(folioItems)));
  });

  /* Initialise from any session-restored folio data */
  _renderFolio();
  _updateFolioToggle();

  /* ── Submit handlers ── */
  function submitFromWelcome() {
    const q = welcomeInp.value.trim();
    if (!q || busy) return;
    welcomeInp.value = '';
    switchToChat();
    ask(q);
  }

  function submitFromChat() {
    const q = chatInp.value.trim();
    if (!q || busy) return;
    chatInp.value = '';
    autoResize(chatInp);
    ask(q);
  }

  function switchToChat() {
    if (inChat) return;
    inChat = true;
    welcome.style.display = 'none';
    thread.style.display  = 'flex';
    chatBar.style.display = 'block';
  }

  function switchToWelcome() {
    inChat = false;
    welcome.style.display = '';
    thread.style.display  = 'none';
    chatBar.style.display = 'none';
  }

  /* ══════════════════════════════════════════════════════════════════
     PDF UPLOAD  (chunked — calls /api/study-builder/upload-pdf)
  ══════════════════════════════════════════════════════════════════ */

  async function uploadPdf(file) {
    /* Client-side checks before even sending */
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      appendPdfError('Only PDF files are supported. Please select a .pdf file.');
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      const mb = (file.size / 1_048_576).toFixed(1);
      appendPdfError(
        `This PDF is ${mb} MB, which exceeds the 10 MB limit. ` +
        'Please use a smaller file or split the PDF into sections.'
      );
      return;
    }

    uploading = true;
    attachBtn.disabled = true;

    /* Show extracting progress in thread */
    const progressEl = appendPdfProgress(file.name);

    try {
      const form = new FormData();
      form.append('session_id', sessionId);
      form.append('file', file);

      const res = await fetch('/api/study-builder/upload-pdf', {
        method: 'POST',
        body:   form,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Upload failed (HTTP ${res.status})`);
      }

      const data = await res.json();

      /* Persist session id (upload may have been made on a refreshed tab
         where sessionId still matches the server — but we sync anyway) */
      if (data.session_id) {
        sessionId = data.session_id;
        sessionStorage.setItem('sb.session_id', sessionId);
      }

      /* Replace progress with a compact success message in thread */
      progressEl.innerHTML =
        `<svg class="pps-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">` +
        `<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>` +
        `<polyline points="14 2 14 8 20 8"/>` +
        `</svg>` +
        `<span class="pps-text"><strong>${esc(data.filename)}</strong> processed — ` +
        `${data.page_count} page${data.page_count !== 1 ? 's' : ''}, ` +
        `${data.chunk_count} retrievable sections. ` +
        `Only the most relevant sections will be sent to the AI per question.</span>`;
      progressEl.className = 'pdf-progress-success fade-in';

      /* Show the pill in the input bar */
      updatePdfPill(data);
      pdfAttached = true;

    } catch (e) {
      progressEl.remove();
      appendPdfError(e.message);
    } finally {
      uploading      = false;
      attachBtn.disabled = false;
    }
  }

  function appendPdfProgress(filename) {
    const el = mk('div', 'pdf-progress fade-in');
    el.innerHTML =
      `<div class="up-spinner"></div>` +
      `<div class="up-text">Processing PDF\u2026 extracting text from ` +
      `<strong>${esc(filename)}</strong></div>`;
    thread.appendChild(el);
    scrollEnd();
    return el;
  }

  function appendPdfError(msg) {
    const el = mk('div', 'pp-error fade-in');
    el.innerHTML = `&#9888; ${esc(msg)}`;
    thread.appendChild(el);
    scrollEnd();
    setTimeout(() => el.remove(), 8000);
  }

  /* Update the PDF pill in the input bar.
     data == null → hide the pill. */
  function updatePdfPill(data) {
    if (!data) {
      pdfInputPill.style.display = 'none';
      attachBtn.classList.remove('has-papers');
      attachBtn.title = 'Attach a PDF (up to 10 MB)';
      return;
    }
    pipName.textContent  = data.filename;
    pipPages.textContent = `${data.page_count} page${data.page_count !== 1 ? 's' : ''}`;
    pdfInputPill.style.display = '';
    attachBtn.classList.add('has-papers');
    attachBtn.title = `${data.filename} attached — click to replace`;
  }

  /* Clear the PDF from the session (DELETE endpoint) */
  async function clearPdf() {
    if (!sessionId) { updatePdfPill(null); pdfAttached = false; return; }
    try {
      await fetch(`/api/study-builder/upload-pdf?session_id=${encodeURIComponent(sessionId)}`, {
        method: 'DELETE',
      });
    } catch (_) { /* ignore network errors on clear */ }
    pdfAttached = false;
    updatePdfPill(null);
  }

  /* ══════════════════════════════════════════════════════════════════
     ASK
  ══════════════════════════════════════════════════════════════════ */

  async function ask(question) {
    busy = true;
    setSendState(true);

    appendUser(question);
    const { aiEl, stageEl } = appendAIPlaceholder();
    scrollEnd();

    let stageIdx   = 0;
    const stageTmr = setInterval(() => {
      stageIdx = Math.min(stageIdx + 1, STAGES.length - 1);
      if (stageEl) stageEl.textContent = STAGES[stageIdx];
    }, 2600);

    try {
      const body = { question };
      if (sessionId) body.session_id = sessionId;

      window.MedrasJobs?.start('helix-ask', 'Helix searching & synthesising\u2026');
      const res = await fetch('/api/study-builder/ask', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(body),
      });
      clearInterval(stageTmr);
      window.MedrasJobs?.finish('helix-ask');

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();

      /* Persist session */
      if (data.session_id) {
        sessionId = data.session_id;
        sessionStorage.setItem('sb.session_id', sessionId);
        sessionStorage.setItem('medras.nav.returnHint', JSON.stringify({
          module: 'helix', label: 'your research question',
          url:    '/study-builder/chat.html',
        }));
      }

      await renderAIMessage(aiEl, data, question);
      updateDbStrip(data.sources_searched || []);

    } catch (e) {
      clearInterval(stageTmr);
      window.MedrasJobs?.finish('helix-ask');
      aiEl.innerHTML = `<div class="msg-error">&#9888; ${esc(e.message || 'Request failed — please try again.')}</div>`;
    } finally {
      busy = false;
      setSendState(false);
      scrollEnd();
    }
  }

  function setSendState(disabled) {
    chatSend.disabled = welcomeSend.disabled = disabled;
  }

  /* ── DOM builders ── */
  function appendUser(text) {
    const el = mk('div', 'msg-user fade-in');
    const b  = mk('div', 'msg-user-bubble');
    b.textContent = text;
    el.appendChild(b);
    thread.appendChild(el);
  }

  function appendAIPlaceholder() {
    const aiEl   = mk('div', 'msg-ai fade-in');
    const loader = mk('div', 'loader-wrap');
    const dots   = mk('div', 'typing-wrap');
    for (let i = 0; i < 3; i++) dots.appendChild(mk('div', 'typing-dot'));
    const stageEl = mk('span', 'stage-text');
    stageEl.textContent = STAGES[0];
    loader.appendChild(dots);
    loader.appendChild(stageEl);
    aiEl.appendChild(loader);
    thread.appendChild(aiEl);
    return { aiEl, stageEl };
  }

  /* ── Main renderer (structured) ── */
  async function renderAIMessage(el, d, question) {
    el.innerHTML = '';

    /* 1 — Evidence grade banner */
    const grade = (d.evidence_grade || 'VERY LOW').toUpperCase();
    const gm    = GRADE_META[grade] || GRADE_META['VERY LOW'];
    const banner = mk('div', `ev-banner ${gm.cls}`);
    banner.innerHTML =
      `<span class="ev-icon">${gm.icon}</span>` +
      `<span class="ev-label">${gm.label}</span>` +
      `<span class="ev-expl">${esc(d.evidence_grade_explanation || '')}</span>`;
    if ((d.uploaded_count || 0) > 0) {
      const note = mk('span', 'ev-upload-note');
      note.textContent =
        `\u00b7 ${d.uploaded_count} attached paper${d.uploaded_count > 1 ? 's' : ''} included`;
      banner.appendChild(note);
    }
    el.appendChild(banner);

    /* 2 — Summary (typewriter) */
    const summaryWrap = mk('div', 'msg-ai-body');
    el.appendChild(summaryWrap);
    scrollEnd();

    const summaryText = extractSummary(d.answer || '');
    await typewrite(summaryWrap, summaryText, 14);

    /* 3 — Structured sections */

    /* Key findings */
    const findings = d.key_findings || [];
    if (findings.length) {
      const section = mk('div', 'answer-section findings-section');
      const h = mk('div', 'section-label'); h.textContent = 'Key findings';
      section.appendChild(h);
      const list = mk('ul', 'findings-list');
      findings.forEach((f) => {
        const li   = mk('li', 'finding-item');
        const srcs = (f.sources || []).map((n) =>
          `<a class="cite" href="#ref-${n}">[${n}]</a>`
        ).join('');
        li.innerHTML = highlightStats(esc(f.finding || '')) + ' ' + srcs;
        list.appendChild(li);
      });
      section.appendChild(list);
      el.appendChild(section);
    }

    /* Agrees / debated */
    const agrees  = d.what_agrees     || '';
    const debated = d.what_is_debated || '';
    if (agrees || debated) {
      const row = mk('div', 'consensus-row');
      if (agrees) {
        const box = mk('div', 'consensus-box agrees-box');
        box.innerHTML =
          `<div class="consensus-label"><span class="cl-dot dot-green"></span>Evidence agrees</div>` +
          `<div class="consensus-text">${highlightStats(esc(agrees))}</div>`;
        row.appendChild(box);
      }
      if (debated) {
        const box = mk('div', 'consensus-box debated-box');
        box.innerHTML =
          `<div class="consensus-label"><span class="cl-dot dot-amber"></span>Still debated</div>` +
          `<div class="consensus-text">${highlightStats(esc(debated))}</div>`;
        row.appendChild(box);
      }
      el.appendChild(row);
    }

    /* Contradictions callout */
    const contras = d.contradictions || [];
    if (contras.length) {
      const callout = mk('div', 'contradiction-callout');
      callout.innerHTML =
        `<div class="contra-head">&#9888;&#xFE0E; Conflicting findings in this evidence</div>`;
      const ul = mk('ul', 'contra-list');
      contras.forEach((c) => {
        const li = mk('li'); li.innerHTML = highlightStats(esc(c)); ul.appendChild(li);
      });
      callout.appendChild(ul);
      el.appendChild(callout);
    }

    /* Limitations */
    if (d.limitations) {
      const lim = mk('div', 'limitations-note');
      lim.innerHTML =
        `<span class="lim-label">Limitations:</span> ${highlightStats(esc(d.limitations))}`;
      el.appendChild(lim);
    }

    /* 4 — Action buttons */
    const actRow = mk('div', 'action-row');
    [
      { label: 'Take to Proposal Writer', url: '/proposal-module/',          icon: '✦', primary: true  },
      { label: 'Design a study on this',  url: '/study-builder/design.html', icon: '⊹', primary: false },
      { label: 'Calculate sample size',   url: '/sample-size.html',          icon: '\u2211', primary: false },
    ].forEach(({ label, url, icon, primary }) => {
      const btn = mk('a', `action-btn${primary ? ' action-btn-primary' : ''}`);
      btn.href = url;
      btn.innerHTML = `<span>${icon}</span> ${label}`;
      if (url.includes('proposal')) {
        btn.addEventListener('click', () => {
          try { sessionStorage.setItem('medras.proposal.intake.background_hint', d.answer || ''); }
          catch (_) {}
        });
      }
      actRow.appendChild(btn);
    });
    el.appendChild(actRow);

    /* 4b — Contextual statistical callout */
    const statHints = _extractStatHints(d.answer, d.key_findings);
    if (statHints.hasSampleSize || statHints.hasStatTest) {
      el.appendChild(_buildStatCallout(statHints, question || '', d.answer));
    }

    /* 5 — Meta row */
    const meta = mk('div', 'msg-meta');
    addTag(meta, methodLabel(d.synthesis_method), 'tag-method');
    if (d.total_found > 0) addTag(meta, `${d.total_found} papers found`, 'tag-count');
    const oaCount = (d.papers || []).filter((p) => p.open_access).length;
    if (oaCount > 0) addTag(meta, `${oaCount} open access`, 'tag-oa');
    if ((d.uploaded_count || 0) > 0) {
      addTag(meta, `${d.uploaded_count} attached`, 'tag-uploaded');
    }
    el.appendChild(meta);

    /* 6 — Sources + citation export */
    if (d.papers && d.papers.length) {
      el.appendChild(buildSources(d.papers, d.sources_searched || []));
      const exportRow = buildExportRow(d.papers);
      if (exportRow) el.appendChild(exportRow);

      /* Track unique papers across the whole conversation */
      (d.papers || []).forEach((p) => {
        if (!p.title || p.title.length <= 3) return;
        if (p.evidence_type === 'uploaded_pdf') return;
        /* Dedup by DOI first (normalised lowercase), then lowercased title */
        const rawDoi = (p.doi && String(p.doi).trim()) || _extractDoi(p.url || '');
        const key    = rawDoi ? rawDoi.toLowerCase() : p.title.toLowerCase().trim();
        if (!convPapersMap.has(key)) convPapersMap.set(key, p);
      });
      if (copyAllWrap && convPapersMap.size > 0) copyAllWrap.style.display = '';
    }

    /* 7 — Follow-up chips */
    const questions = d.suggested_questions || [];
    if (questions.length) {
      const row = mk('div', 'followup-row');
      questions.forEach((q) => {
        const chip = mk('button', 'followup-chip');
        chip.textContent = q;
        chip.addEventListener('click', () => { chatInp.value = q; submitFromChat(); });
        row.appendChild(chip);
      });
      el.appendChild(row);
    }

    /* 8 — Disclaimer */
    const disc = mk('div', 'disclaimer');
    disc.textContent = d.disclaimer || '';
    el.appendChild(disc);

    scrollEnd();
  }

  /* ── Typewriter ── */
  function typewrite(container, text, msPerChar) {
    return new Promise((resolve) => {
      if (!text) { resolve(); return; }
      const html    = renderMarkdown(text);
      const tmp     = document.createElement('div');
      tmp.innerHTML = html;
      const full    = tmp.innerHTML;
      const plainLen = tmp.textContent.length;
      if (plainLen === 0) { container.innerHTML = full; resolve(); return; }

      let charIdx = 0;
      function step() {
        charIdx += 2;
        if (charIdx >= plainLen) {
          container.innerHTML = full;
          highlightStatsDom(container);
          resolve();
          return;
        }
        container.innerHTML = buildPartialHTML(tmp, charIdx);
        scrollEnd();
        setTimeout(step, msPerChar);
      }
      step();
    });
  }

  function buildPartialHTML(root, limit) {
    let remaining = limit;
    function walk(node) {
      if (remaining <= 0) return '';
      if (node.nodeType === Node.TEXT_NODE) {
        const slice = node.textContent.substring(0, remaining);
        remaining  -= slice.length;
        return esc(slice);
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return '';
      const tag   = node.tagName.toLowerCase();
      let   inner = '';
      for (const child of node.childNodes) {
        inner += walk(child);
        if (remaining <= 0) break;
      }
      const attrs = Array.from(node.attributes)
        .map((a) => ` ${a.name}="${a.value}"`).join('');
      return `<${tag}${attrs}>${inner}</${tag}>`;
    }
    let out = '';
    for (const child of root.childNodes) {
      out += walk(child);
      if (remaining <= 0) break;
    }
    return out;
  }

  function extractSummary(answerText) {
    const lines = answerText.split('\n');
    for (const line of lines) {
      const t = line.trim();
      if (!t) continue;
      if (t.startsWith('**') && t.endsWith('**')) break;
      if (t.startsWith('- ') || t.startsWith('* ')) break;
      if (t.startsWith('[') && t.match(/^\[\d+\]/)) break;
      return t;
    }
    return answerText.split('\n\n')[0] || answerText.substring(0, 300);
  }

  /* ── Statistical highlighter ── */
  function highlightStats(escapedText) {
    return escapedText.replace(STAT_RE, (m) => `<mark class="stat-hl">${m}</mark>`);
  }

  function highlightStatsDom(container) {
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null);
    const toReplace = [];
    let node;
    while ((node = walker.nextNode())) {
      if (STAT_RE.test(node.textContent)) toReplace.push(node);
      STAT_RE.lastIndex = 0;
    }
    toReplace.forEach((tn) => {
      const span = document.createElement('span');
      span.innerHTML = esc(tn.textContent).replace(STAT_RE, (m) =>
        `<mark class="stat-hl">${m}</mark>`
      );
      tn.parentNode.replaceChild(span, tn);
    });
  }

  /* ── Sources panel ── */
  function buildSources(papers, searched) {
    const wrap  = mk('div', 'sources-section');
    const head  = mk('div', 'sources-head');
    const label = mk('span', 'src-toggle-label');
    label.textContent = `\u25b6 ${papers.length} sources`;
    const pills = mk('div', 'src-db-pills');
    searched.forEach((s) => {
      const isPdf = (s === 'uploaded_pdf');
      const p = mk('span', `src-db-pill${(s === 'uploaded' || isPdf) ? ' pill-uploaded' : ''}`);
      p.textContent = SRC_LABELS[s] || s;
      pills.appendChild(p);
    });
    head.appendChild(label);
    head.appendChild(pills);
    const cards = mk('div', 'src-cards');
    papers.forEach((p, i) => cards.appendChild(buildSourceCard(p, i + 1)));
    head.addEventListener('click', () => {
      const open = cards.classList.toggle('open');
      label.textContent = `${open ? '\u25bc' : '\u25b6'} ${papers.length} sources`;
    });
    wrap.appendChild(head);
    wrap.appendChild(cards);
    return wrap;
  }

  function buildSourceCard(p, num) {
    const isPdf      = (p.evidence_type === 'uploaded_pdf');
    const isUploaded = (p.source === 'uploaded');

    const card = mk('div', `src-card${(isUploaded || isPdf) ? ' src-card-uploaded' : ''}`);
    if (isPdf) card.classList.add('src-card-pdf');
    card.id = `ref-${num}`;

    const n = mk('div', 'sc-num'); n.textContent = `[${num}]`; card.appendChild(n);

    /* PDF gets a document icon label instead of a link */
    if (isPdf) {
      const titleRow = mk('div', 'sc-pdf-title-row');
      const icon = mk('span', 'sc-pdf-icon');
      icon.innerHTML =
        '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>' +
        '<polyline points="14 2 14 8 20 8"/></svg>';
      const s = mk('span', 'sc-title-plain');
      s.textContent = p.title || p.filename || 'Uploaded PDF';
      titleRow.appendChild(icon);
      titleRow.appendChild(s);
      card.appendChild(titleRow);
    } else if (p.url) {
      const a = mk('a', 'sc-title');
      a.href = p.url; a.target = '_blank'; a.rel = 'noopener';
      a.textContent = p.title || 'Untitled';
      card.appendChild(a);
    } else {
      const s = mk('span', 'sc-title-plain');
      s.textContent = p.title || 'Untitled'; card.appendChild(s);
    }

    const meta = mk('div', 'sc-meta');
    const ev   = mk('span', `ev-tag ev-${isPdf ? 'uploaded_pdf' : (p.evidence_type || 'observational')}`);
    ev.textContent = EV_LABELS[isPdf ? 'uploaded_pdf' : p.evidence_type] || 'Observational';
    meta.appendChild(ev);

    /* Page ranges for PDF source */
    if (isPdf && p.pages_used && p.pages_used.length) {
      const pg = mk('span', 'sc-pages-tag');
      pg.textContent = p.pages_used.join(', ');
      meta.appendChild(pg);
    }

    if (p.open_access) {
      const oa = mk('span', 'oa-tag'); oa.textContent = 'OA'; meta.appendChild(oa);
    }
    if (p.journal && !isUploaded && !isPdf) {
      const j = mk('span'); j.textContent = p.journal; meta.appendChild(j);
    }
    if (p.year) { const y = mk('span'); y.textContent = p.year; meta.appendChild(y); }
    if (p.authors && p.authors.length && !isUploaded && !isPdf) {
      const au = mk('span');
      au.textContent = p.authors.slice(0, 2).join(', ') + (p.authors.length > 2 ? ' et al.' : '');
      meta.appendChild(au);
    }
    if (p.citation_count > 0) {
      const c = mk('span'); c.textContent = `cited ${p.citation_count}\u00d7`; meta.appendChild(c);
    }

    if (!isPdf) {
      const src = mk('span', 'src-tag');
      src.textContent = SRC_LABELS[p.source] || p.source || ''; meta.appendChild(src);
    }

    card.appendChild(meta);

    /* Bookmark / pin button (not for PDF — it's a local file) */
    if (!isPdf) {
      const pinBtn = mk('button', `pin-btn${_isPinned(p) ? ' pinned' : ''}`);
      pinBtn.title = _isPinned(p) ? 'Remove from Folio' : 'Save to Folio';
      if (p.url) pinBtn.dataset.url = p.url.trim();
      pinBtn.innerHTML =
        '<svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">' +
        '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>';
      pinBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        _togglePin(p, pinBtn);
      });
      card.appendChild(pinBtn);
    }

    return card;
  }

  /* ── Markdown renderer ── */
  function renderMarkdown(raw) {
    if (!raw) return '';
    let text = esc(raw);
    text = text.replace(/\[(\d+(?:,\s*\d+)*)\]/g, (_, nums) =>
      nums.split(',').map((n) => {
        const id = n.trim();
        return `<a class="cite" href="#ref-${id}">[${id}]</a>`;
      }).join('')
    );
    text = text.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    text = text.replace(/^## (.+)$/gm,  '<h3>$1</h3>');
    text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/\*(.+?)\*/g,     '<em>$1</em>');
    text = text.replace(/((?:^[-\u2022] .+\n?)+)/gm, (block) => {
      const items = block.trim().split('\n')
        .map((l) => `<li>${l.replace(/^[-\u2022] /, '')}</li>`).join('');
      return `<ul>${items}</ul>`;
    });
    text = text.split('\n\n').map((chunk) => {
      chunk = chunk.trim();
      if (!chunk) return '';
      if (/^<(h[234]|ul|ol|div)/.test(chunk)) return chunk;
      return `<p>${chunk.replace(/\n/g, '<br>')}</p>`;
    }).join('\n');
    return text;
  }

  /* ── DB strip ── */
  function updateDbStrip(sources) {
    dbStrip.innerHTML = '';
    sources.forEach((s) => {
      const sp = mk('span', 'db-strip-item');
      sp.textContent = SRC_LABELS[s] || s;
      dbStrip.appendChild(sp);
    });
  }

  /* ── Helpers ── */
  function addTag(parent, text, cls) {
    const t = mk('span', `meta-tag ${cls}`);
    t.textContent = text; parent.appendChild(t);
  }

  function methodLabel(m) {
    return {
      'gpt-4o-mini':       'GPT-4o-mini',
      openrouter:          'OpenRouter',
      raw_sources:         'Sources only',
      no_papers:           'No results',
    }[m] || (m || '');
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function mk(tag, cls) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    return e;
  }

  function scrollEnd() { raWrap.scrollTop = raWrap.scrollHeight; }

  /* ══════════════════════════════════════════════════════════════════
     CITATION EXPORT  (Phase 4 — all formats generated client-side)
  ══════════════════════════════════════════════════════════════════ */

  function buildExportRow(papers) {
    const exportable = (papers || []).filter(
      (p) => p.title && p.title.length > 3 && p.evidence_type !== 'uploaded_pdf'
    );
    if (exportable.length < 1) return null;

    const n    = exportable.length;
    const row  = mk('div', 'export-row');

    /* Single trigger button */
    const wrap = mk('div', 'export-btn-wrap');
    const trig = mk('button', 'export-trigger');
    trig.innerHTML = `Export ${n} citation${n !== 1 ? 's' : ''} <span class="export-arrow">\u25be</span>`;

    /* Dropdown panel */
    const dd = mk('div', 'export-dropdown');

    /* Copy options via backend */
    [
      { label: 'Copy Vancouver', style: 'vancouver' },
      { label: 'Copy APA 7th',   style: 'apa'       },
    ].forEach(({ label, style }) => {
      const item = mk('button', 'export-dd-item export-dd-copy');
      item.textContent = label;
      item.addEventListener('click', () => {
        dd.classList.remove('open'); _openExportDd = null;
        _copyViaBackend(exportable, style, item, label);
      });
      dd.appendChild(item);
    });

    /* Divider */
    dd.appendChild(mk('div', 'export-dd-divider'));

    /* Download options (client-side for instant response) */
    [
      { label: 'Download Vancouver (.txt)', file: 'citations_vancouver.txt', fn: _toVancouver },
      { label: 'Download APA 7th (.txt)',   file: 'citations_apa.txt',       fn: _toApa       },
      { label: 'Download BibTeX (.bib)',     file: 'citations.bib',           fn: _toBibtex    },
      { label: 'Download RIS (.ris)',        file: 'citations.ris',           fn: _toRis       },
    ].forEach(({ label, file, fn }) => {
      const item = mk('button', 'export-dd-item');
      item.textContent = label;
      item.addEventListener('click', () => {
        dd.classList.remove('open'); _openExportDd = null;
        _dlText(file, fn(exportable));
      });
      dd.appendChild(item);
    });

    /* Toggle open/close; close any other open dropdown first */
    trig.addEventListener('click', (e) => {
      e.stopPropagation();
      if (_openExportDd && _openExportDd !== dd) {
        _openExportDd.classList.remove('open');
        _openExportDd = null;
      }
      if (dd.classList.toggle('open')) {
        _openExportDd = dd;
      } else {
        _openExportDd = null;
      }
    });

    wrap.appendChild(trig);
    wrap.appendChild(dd);
    row.appendChild(wrap);
    return row;
  }

  /* Close open export dropdown on any outside click */
  document.addEventListener('click', () => {
    if (_openExportDd) { _openExportDd.classList.remove('open'); _openExportDd = null; }
  });

  /* ── Copy via backend (with client-side fallback) ── */

  async function _copyViaBackend(papers, style, btn, originalLabel) {
    const prev  = btn.textContent;
    btn.textContent = 'Copying\u2026';
    btn.disabled    = true;
    try {
      const res = await fetch('/api/study-builder/format-citations', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ papers, style }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      await navigator.clipboard.writeText(data.formatted);
      btn.textContent = 'Copied \u2713';
      setTimeout(() => { btn.textContent = originalLabel; btn.disabled = false; }, 2000);
    } catch (_) {
      /* Fallback: format client-side then copy */
      const text = style === 'vancouver' ? _toVancouver(papers) : _toApa(papers);
      navigator.clipboard.writeText(text)
        .then(() => {
          btn.textContent = 'Copied \u2713';
          setTimeout(() => { btn.textContent = originalLabel; btn.disabled = false; }, 2000);
        })
        .catch(() => {
          _dlText('medras-citations.txt', text);
          btn.textContent = originalLabel;
          btn.disabled = false;
        });
    }
  }

  /* Wire up the conversation-wide copy-all buttons */
  if (copyAllVan) {
    copyAllVan.addEventListener('click', () => {
      const papers = Array.from(convPapersMap.values());
      _copyViaBackend(papers, 'vancouver', copyAllVan, 'Copy all \u2014 Vancouver');
    });
  }
  if (copyAllApa) {
    copyAllApa.addEventListener('click', () => {
      const papers = Array.from(convPapersMap.values());
      _copyViaBackend(papers, 'apa', copyAllApa, 'Copy all \u2014 APA');
    });
  }

  /* ── Format generators ── */

  function _extractDoi(url) {
    if (!url) return '';
    const m = url.match(/doi\.org\/(.+)$/i);
    return m ? decodeURIComponent(m[1]).trim() : '';
  }

  function _getDoi(p) {
    /* Explicit doi field first, then extract from URL */
    const direct = p.doi && String(p.doi).trim();
    return direct || _extractDoi(p.url || '');
  }

  function _extractNct(url) {
    if (!url) return '';
    const m = url.match(/NCT\d+/i);
    return m ? m[0] : '';
  }

  function _bibtexKey(p, idx) {
    const last = (p.authors && p.authors[0])
      ? p.authors[0].trim().split(/\s+/).pop().toLowerCase().replace(/[^a-z]/g, '')
      : `ref${idx}`;
    const yr   = p.year || 'nd';
    const kw   = (p.title || '').toLowerCase()
      .split(/\s+/)
      .find((w) => w.length > 3 && !/^(the|and|for|with|from|that|this)$/.test(w))
      || 'paper';
    return `${last}${yr}${kw.replace(/[^a-z]/g, '').substring(0, 8)}`;
  }

  function _toBibtex(papers) {
    return papers.map((p, i) => {
      const doi     = _extractDoi(p.url);
      const authors = (p.authors || []).join(' and ') || 'Unknown';
      const key     = _bibtexKey(p, i + 1);
      const lines   = [
        `@article{${key},`,
        `  author  = {${authors}},`,
        `  title   = {${(p.title || '').replace(/[{}]/g, '')}},`,
        `  journal = {${p.journal || ''}},`,
        `  year    = {${p.year || ''}},`,
      ];
      if (doi)   lines.push(`  doi     = {${doi}},`);
      if (p.url) lines.push(`  url     = {${p.url}},`);
      lines.push('}');
      return lines.join('\n');
    }).join('\n\n');
  }

  function _toRis(papers) {
    return papers.map((p) => {
      const doi   = _extractDoi(p.url);
      const lines = ['TY  - JOUR'];
      (p.authors || []).forEach((a) => lines.push(`AU  - ${a}`));
      lines.push(`TI  - ${p.title || ''}`);
      if (p.journal) lines.push(`JO  - ${p.journal}`);
      if (p.year)    lines.push(`PY  - ${p.year}`);
      if (doi)       lines.push(`DO  - ${doi}`);
      if (p.url)     lines.push(`UR  - ${p.url}`);
      lines.push('ER  -');
      return lines.join('\n');
    }).join('\n\n');
  }

  function _fmtVancouverAuthors(authors) {
    if (!authors || !authors.length) return '';
    const fmt = authors.slice(0, 6).map((a) => {
      const parts    = a.trim().split(/\s+/);
      if (parts.length < 2) return a;
      const last     = parts[parts.length - 1];
      const initials = parts.slice(0, -1).map((n) => n[0].toUpperCase()).join('');
      return `${last} ${initials}`;
    });
    if (authors.length > 6) fmt.push('et al');
    return fmt.join(', ') + '.';
  }

  function _toVancouver(papers) {
    return papers.map((p, i) => {
      const src = (p.source || '').toLowerCase();

      /* ClinicalTrials.gov — registration format */
      if (src === 'clinicaltrials') {
        const sponsor = (p.authors && p.authors[0]) || 'Unknown Sponsor';
        const nct     = _extractNct(p.url || '');
        let ref = `${i + 1}. ${sponsor}. ${p.title || 'Untitled'} [Clinical trial registration]. ClinicalTrials.gov.`;
        if (nct)    ref += ` ${nct}`;
        else if (p.url) ref += ` Available from: ${p.url}`;
        return ref.trim();
      }

      /* WHO IRIS — use institutional name directly (not personal-name formatter) */
      if (src === 'who_iris' && !(p.authors && p.authors.length)) {
        const doi = _getDoi(p);
        let ref   = `${i + 1}. World Health Organization. ${p.title || 'Untitled'}.`;
        if (p.journal) ref += ` ${p.journal}.`;
        if (p.year)    ref += ` ${p.year}.`;
        if (doi)       ref += ` doi: ${doi}`;
        else if (p.url) ref += ` Available from: ${p.url}`;
        return ref.trim();
      }

      const auth  = _fmtVancouverAuthors(p.authors || []);
      const doi   = _getDoi(p);
      const vol   = (p.volume || '').toString().trim();
      const issue = (p.issue  || '').toString().trim();
      const pages = (p.pages  || '').toString().trim();
      let   ref   = `${i + 1}. ${auth}${auth ? ' ' : ''}${p.title || 'Untitled'}.`;
      if (p.journal && src !== 'uploaded') ref += ` ${p.journal}.`;
      /* Vancouver date/volume: "Year;Vol(Issue):Pages." */
      if (vol || issue || pages) {
        let yrVol = p.year ? ` ${p.year}` : ' n.d.';
        if (vol) { yrVol += `;${vol}`; if (issue) yrVol += `(${issue})`; }
        if (pages) yrVol += `:${pages}`;
        ref += `${yrVol}.`;
      } else if (p.year) {
        ref += ` ${p.year}.`;
      }
      if (doi)        ref += ` doi: ${doi}`;
      else if (p.url) ref += ` Available from: ${p.url}`;
      return ref.trim();
    }).join('\n');
  }

  function _fmtApaAuthors(authors) {
    if (!authors || !authors.length) return '';
    const fmt = authors.slice(0, 20).map((a) => {
      const parts = a.trim().split(/\s+/);
      if (parts.length < 2) return a;
      const last     = parts[parts.length - 1];
      const initials = parts.slice(0, -1)
        .map((n) => n[0] ? n[0].toUpperCase() + '.' : '')
        .filter(Boolean)
        .join(' ');
      return `${last}, ${initials}`;
    });
    if (authors.length > 20) {
      const lastAuthor = fmt[fmt.length - 1];
      return fmt.slice(0, 19).join(', ') + ', \u2026 ' + lastAuthor;
    }
    if (fmt.length === 1) return fmt[0];
    const last = fmt.pop();
    return fmt.join(', ') + ', & ' + last;
  }

  function _toApa(papers) {
    return papers.map((p) => {
      const src = (p.source || '').toLowerCase();

      /* ClinicalTrials.gov — registration format */
      if (src === 'clinicaltrials') {
        const sponsor  = (p.authors && p.authors[0]) || 'Unknown Sponsor';
        const yr       = p.year ? `(${p.year})` : '(n.d.)';
        const rawTitle = (p.title || 'Untitled').trim();
        const title    = rawTitle.charAt(0).toUpperCase() + rawTitle.slice(1);
        const nct      = _extractNct(p.url || '');
        let ref = `${sponsor} ${yr}. *${title}* [Clinical trial registration]. ClinicalTrials.gov.`;
        if (nct)    ref += ` ${nct}`;
        else if (p.url) ref += ` ${p.url}`;
        return ref.trim();
      }

      /* WHO IRIS — use institutional name directly (not personal-name formatter) */
      if (src === 'who_iris' && !(p.authors && p.authors.length)) {
        const doi      = _getDoi(p);
        const year     = p.year ? `(${p.year})` : '(n.d.)';
        const rawTitle = (p.title || 'Untitled').trim();
        const title    = rawTitle.charAt(0).toUpperCase() + rawTitle.slice(1);
        let ref = `World Health Organization ${year}. ${title}.`;
        if (p.journal) ref += ` *${p.journal}*.`;
        if (doi)       ref += ` https://doi.org/${doi}`;
        else if (p.url) ref += ` ${p.url}`;
        return ref.trim();
      }

      const auth     = _fmtApaAuthors(p.authors || []);
      const doi      = _getDoi(p);
      const year     = p.year ? `(${p.year})` : '(n.d.)';
      const rawTitle = (p.title || 'Untitled').trim();
      const title    = rawTitle.charAt(0).toUpperCase() + rawTitle.slice(1);
      const vol      = (p.volume || '').toString().trim();
      const issue    = (p.issue  || '').toString().trim();
      const pages    = (p.pages  || '').toString().trim();
      let ref = auth ? `${auth} ${year}. ` : `${year}. `;
      ref += `${title}.`;
      /* Journal with vol/issue/pages in APA italics format */
      if (p.journal && src !== 'uploaded') {
        let jPart = ` *${p.journal}*`;
        if (vol) { jPart += `, *${vol}*`; if (issue) jPart += `(${issue})`; }
        if (pages) jPart += `, ${pages}`;
        ref += jPart + '.';
      }
      if (doi)        ref += ` https://doi.org/${doi}`;
      else if (p.url) ref += ` ${p.url}`;
      return ref.trim();
    }).join('\n\n');
  }

  function _toPlainText(papers) {
    return papers.map((p, i) => {
      const auth = (p.authors || []).slice(0, 3).join(', ')
        + (p.authors && p.authors.length > 3 ? ' et al.' : '');
      const doi  = _extractDoi(p.url);
      let   ref  = `[${i + 1}] ${p.title || 'Untitled'}`;
      if (auth)      ref += `. ${auth}`;
      if (p.journal) ref += `. ${p.journal}`;
      if (p.year)    ref += ` (${p.year})`;
      if (doi)       ref += `. doi: ${doi}`;
      else if (p.url) ref += `. ${p.url}`;
      return ref;
    }).join('\n\n');
  }

  function _dlText(filename, content) {
    const a   = document.createElement('a');
    const url = URL.createObjectURL(new Blob([content], { type: 'text/plain' }));
    a.href     = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  /* ══════════════════════════════════════════════════════════════════
     STATISTICAL CONTEXT  (Phase 6 — contextual tool deep-links)
  ══════════════════════════════════════════════════════════════════ */

  function _extractStatHints(answerText, keyFindings) {
    const combined = [
      answerText || '',
      ...((keyFindings || []).map((f) => (f.finding || ''))),
    ].join(' ');

    const hints = {
      hasSampleSize:    false,
      hasStatTest:      false,
      sampleSizeParams: {},
      detectedParams:   [],
      detectedTests:    [],
    };

    const toNum = (s) => s ? s.replace('%', '').trim() : null;

    const p1m = combined.match(/\bp1\s*[=:≈]\s*(0\.\d+|\d{1,3}(?:\.\d+)?%?)/i);
    const p2m = combined.match(/\bp2\s*[=:≈]\s*(0\.\d+|\d{1,3}(?:\.\d+)?%?)/i);
    if (p1m) {
      hints.sampleSizeParams.p1 = toNum(p1m[1]);
      hints.detectedParams.push(`p\u2081 \u2248 ${p1m[1]}`);
      hints.hasSampleSize = true;
    }
    if (p2m) {
      hints.sampleSizeParams.p2 = toNum(p2m[1]);
      hints.detectedParams.push(`p\u2082 \u2248 ${p2m[1]}`);
      hints.hasSampleSize = true;
    }

    const pwrm = combined.match(/\b(\d{2,3})\s*%\s*power\b/i)
      || combined.match(/\bpower\s+of\s+(?:0\.)(\d{1,2})\b/i);
    if (pwrm) {
      const pw = pwrm[1] ? (parseFloat(pwrm[1]) <= 1 ? String(Math.round(parseFloat('0.' + pwrm[1]) * 100)) : pwrm[1]) : '80';
      hints.sampleSizeParams.power = pw;
      hints.detectedParams.push(`${pw}% power`);
      hints.hasSampleSize = true;
    }

    const alm = combined.match(/\balpha\s*[=:≈]\s*(0\.\d{2})\b/i)
      || combined.match(/significance\s+level\s+of\s+(0\.\d{2})\b/i)
      || combined.match(/\bp\s*[<>]\s*(0\.0[15])\b/i);
    if (alm) {
      hints.sampleSizeParams.alpha = alm[1];
      hints.detectedParams.push(`\u03b1 = ${alm[1]}`);
      hints.hasSampleSize = true;
    }

    const nntm = combined.match(/\bNNT\s*(?:=|of)?\s*(\d{1,4})\b/i);
    if (nntm) {
      hints.detectedParams.push(`NNT = ${nntm[1]}`);
      hints.hasSampleSize = true;
    }

    const orm = combined.match(/\bOR\s+([\d.]+)\b/);
    if (orm && parseFloat(orm[1]) !== 1) {
      hints.detectedParams.push(`OR = ${orm[1]}`);
      hints.hasSampleSize = hints.hasSampleSize || true;
    }

    const nm = combined.match(/\bn\s*=\s*(\d{2,5})\b/i)
      || combined.match(/\bsample\s+size\s+of\s+(\d{2,5})\b/i);
    if (nm) {
      hints.sampleSizeParams.n = nm[1];
      hints.detectedParams.push(`n = ${nm[1]}`);
      hints.hasSampleSize = true;
    }

    _STAT_TESTS.forEach(({ re, name }) => {
      if (re.test(combined) && !hints.detectedTests.includes(name)) {
        hints.detectedTests.push(name);
        hints.hasStatTest = true;
      }
    });

    return hints;
  }

  function _buildStatCallout(hints, question, answerText) {
    const box = mk('div', 'stat-callout');

    const head = mk('div', 'stc-head');
    head.innerHTML =
      '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">' +
      '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>' +
      '<span>Statistical tools for this question</span>';
    box.appendChild(head);

    const all = [...hints.detectedParams, ...hints.detectedTests];
    if (all.length) {
      const row = mk('div', 'stc-chip-row');
      all.forEach((label) => {
        const chip = mk('span', 'stc-chip'); chip.textContent = label; row.appendChild(chip);
      });
      box.appendChild(row);
    }

    const btnRow = mk('div', 'stc-btn-row');

    if (hints.hasSampleSize) {
      const a = mk('a', 'stc-btn stc-btn-cohort');
      a.href = '/sample-size.html';
      a.innerHTML = '\u03a3 Calculate sample size <span class="stc-arrow">\u2192</span>';
      a.addEventListener('click', () => {
        try {
          sessionStorage.setItem('medras.cohort.prefill', JSON.stringify({
            objective: question,
            context:   `Research question: ${question}\n\n${(answerText || '').substring(0, 600)}`,
            params:    hints.sampleSizeParams,
            detected:  hints.detectedParams,
            ts:        Date.now(),
          }));
        } catch (_) {}
      });
      btnRow.appendChild(a);
    }

    if (hints.hasStatTest) {
      const a = mk('a', 'stc-btn stc-btn-sigma');
      a.href = '/analysis.html';
      a.innerHTML = '\u03a3 Open Sigma analysis engine <span class="stc-arrow">\u2192</span>';
      a.addEventListener('click', () => {
        try {
          sessionStorage.setItem('medras.sigma.prefill', JSON.stringify({
            context:  answerText || '',
            tests:    hints.detectedTests,
            question: question,
            ts:       Date.now(),
          }));
        } catch (_) {}
      });
      btnRow.appendChild(a);
    }

    box.appendChild(btnRow);
    return box;
  }

  /* ══════════════════════════════════════════════════════════════════
     FOLIO  (bookmarks / saved papers)
  ══════════════════════════════════════════════════════════════════ */

  function _isPinned(p) {
    if (!p.url) return false;
    return folioItems.some((f) => f.url === p.url.trim());
  }

  function _togglePin(p, btn) {
    if (!p.url) return;
    const url = p.url.trim();
    if (_isPinned(p)) {
      folioItems = folioItems.filter((f) => f.url !== url);
      btn.classList.remove('pinned');
      btn.title = 'Save to Folio';
    } else {
      folioItems.push({
        url, title: p.title, journal: p.journal, year: p.year,
        authors: p.authors || [], source: p.source,
      });
      btn.classList.add('pinned');
      btn.title = 'Remove from Folio';
      /* Pulse animation */
      if (folioBadge) {
        folioBadge.classList.remove('badge-pulse');
        void folioBadge.offsetWidth;
        folioBadge.classList.add('badge-pulse');
      }
    }
    try { sessionStorage.setItem('sb.folio', JSON.stringify(folioItems)); } catch (_) {}
    _syncHelixMirror();
    _renderFolio();
    _updateFolioToggle();
  }

  /* Write a normalised copy of folio to the key Scriptorium + Prologue import buttons read. */
  function _syncHelixMirror() {
    try {
      var mirror = folioItems.map(function (f) {
        return {
          title:   f.title   || '',
          authors: Array.isArray(f.authors) ? f.authors : (f.authors ? [f.authors] : []),
          journal: f.journal || '',
          year:    String(f.year   || ''),
          doi:     f.doi     || '',
          url:     f.url     || '',
          source:  'helix',
        };
      });
      localStorage.setItem('medras.helix.references', JSON.stringify(mirror));
    } catch (_) {}
  }

  function _renderFolio() {
    if (!folioList || !folioEmpty) return;
    if (!folioItems.length) {
      folioList.style.display  = 'none';
      folioEmpty.style.display = '';
      if (folioFoot) folioFoot.style.display = 'none';
      if (folioCount) folioCount.textContent = '';
      return;
    }
    folioList.style.display  = '';
    folioEmpty.style.display = 'none';
    if (folioFoot) folioFoot.style.display = '';
    if (folioCount) folioCount.textContent = `${folioItems.length} saved`;
    folioList.innerHTML = '';
    folioItems.forEach((item, idx) => {
      const el = mk('div', 'folio-item');

      const top = mk('div', 'fi-top');
      if (item.url) {
        const a = mk('a', 'fi-title');
        a.href = item.url; a.target = '_blank'; a.rel = 'noopener';
        a.textContent = item.title || 'Untitled';
        top.appendChild(a);
      } else {
        const s = mk('span', 'fi-title');
        s.textContent = item.title || 'Untitled';
        top.appendChild(s);
      }
      const rem = mk('button', 'fi-remove');
      rem.title = 'Remove';
      rem.textContent = '\u00d7';
      rem.addEventListener('click', () => {
        folioItems.splice(idx, 1);
        try { sessionStorage.setItem('sb.folio', JSON.stringify(folioItems)); } catch (_) {}
        _syncHelixMirror();
        _renderFolio();
        _updateFolioToggle();
      });
      top.appendChild(rem);
      el.appendChild(top);

      const metaRow = mk('div', 'fi-meta');
      if (item.journal) { const j = mk('span', 'fi-j'); j.textContent = item.journal; metaRow.appendChild(j); }
      if (item.year)    { const y = mk('span', 'fi-y'); y.textContent = item.year;    metaRow.appendChild(y); }
      el.appendChild(metaRow);

      folioList.appendChild(el);
    });
  }

  function _updateFolioToggle() {
    if (!folioToggleBtn) return;
    if (folioItems.length > 0) {
      folioToggleBtn.style.display = '';
      if (folioBadge) folioBadge.textContent = String(folioItems.length);
    } else {
      folioToggleBtn.style.display = 'none';
    }
  }

})();
