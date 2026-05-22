/* MedRAS Research Assistant — sb.js  (Phase 3: Paper upload) */
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
  const attachedPapersBar    = document.getElementById('attached-papers-bar');
  const attachedPapersLabel  = document.getElementById('attached-papers-label');

  /* ── Folio DOM ── */
  const folioPanelEl   = document.getElementById('folio-panel');
  const folioToggleBtn = document.getElementById('folio-toggle-btn');
  const folioBadge     = document.getElementById('folio-badge');
  const folioCount     = document.getElementById('folio-count');
  const folioCloseBtn  = document.getElementById('folio-close-btn');
  const folioList      = document.getElementById('folio-list');
  const folioEmpty     = document.getElementById('folio-empty');
  const folioFoot      = document.getElementById('folio-foot');

  /* ── Labels ── */
  const SRC_LABELS = {
    pubmed:'PubMed', cochrane:'Cochrane', europe_pmc:'Europe PMC',
    pmc:'PubMed Central', semantic_scholar:'Semantic Scholar',
    openalex:'OpenAlex', who_iris:'WHO IRIS', crossref:'Crossref',
    core:'CORE', medrxiv:'medRxiv', clinicaltrials:'ClinicalTrials.gov',
    doaj:'DOAJ', lens:'Lens.org', ieee:'IEEE Xplore',
    wos:'Web of Science', scopus:'Scopus',
    uploaded:'Your uploaded paper',
  };
  const EV_LABELS = {
    systematic_review:'Sys. Review', rct:'RCT',
    observational:'Observational', guideline:'Guideline',
    uploaded:'Uploaded Paper',
  };
  const GRADE_META = {
    HIGH:      { cls:'grade-high',     label:'HIGH EVIDENCE',      icon:'◆' },
    MODERATE:  { cls:'grade-moderate', label:'MODERATE EVIDENCE',  icon:'◈' },
    LOW:       { cls:'grade-low',      label:'LOW EVIDENCE',       icon:'◇' },
    'VERY LOW':{ cls:'grade-verylow',  label:'VERY LOW EVIDENCE',  icon:'○' },
  };

  /* ── Session & upload state ── */
  let sessionId      = sessionStorage.getItem('sb.session_id') || null;
  let busy           = false;
  let inChat         = false;
  let attachedPapers = [];   /* [{filename, wordCount, paperIndex}] */
  let uploading      = false;

  /* ── Folio state (persisted to sessionStorage) ── */
  let folioItems = JSON.parse(sessionStorage.getItem('sb.folio') || '[]');

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

  /* ── Attach button ── */
  attachBtn.addEventListener('click', () => {
    if (!inChat || !sessionId) {
      /* No session yet — give a gentle nudge */
      chatInp.focus();
      const orig = chatInp.placeholder;
      chatInp.placeholder = 'Ask a question first to start a session, then attach papers.';
      setTimeout(() => { chatInp.placeholder = orig; }, 3000);
      return;
    }
    if (uploading) return;
    fileInput.click();
  });

  fileInput.addEventListener('change', () => {
    const file = fileInput.files[0];
    fileInput.value = '';   /* reset so same file can be re-selected */
    if (file) uploadPaper(file);
  });

  /* ── New chat ── */
  newChatBtn.addEventListener('click', () => {
    thread.innerHTML = '';
    sessionId      = null;
    attachedPapers = [];
    uploading      = false;
    folioItems     = [];
    sessionStorage.removeItem('sb.session_id');
    sessionStorage.removeItem('medras.nav.returnHint');
    sessionStorage.removeItem('sb.folio');
    updateAttachedUI();
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
  document.getElementById('folio-copy-van').addEventListener('click', () => {
    const btn = document.getElementById('folio-copy-van');
    navigator.clipboard.writeText(_toVancouver(folioItems))
      .then(() => {
        btn.textContent = 'Copied \u2713';
        setTimeout(() => { btn.textContent = 'Copy'; }, 2200);
      })
      .catch(() => _dlText('folio-citations.txt', _toVancouver(folioItems)));
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
     PAPER UPLOAD
  ══════════════════════════════════════════════════════════════════ */

  async function uploadPaper(file) {
    uploading = true;
    const progressEl = appendUploadProgress(file.name);

    try {
      const form = new FormData();
      form.append('session_id', sessionId);
      form.append('file', file);

      const res = await fetch('/api/study-builder/upload-paper', {
        method: 'POST',
        body:   form,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Upload failed (HTTP ${res.status})`);
      }

      const data = await res.json();

      /* Replace spinner with success pill */
      progressEl.remove();
      appendPaperPill(data.filename, data.word_count, data.paper_index, data.preview);

      attachedPapers.push({
        filename:   data.filename,
        wordCount:  data.word_count,
        paperIndex: data.paper_index,
      });
      updateAttachedUI();

    } catch (e) {
      progressEl.remove();
      appendPaperError(e.message);
    } finally {
      uploading = false;
    }
  }

  function appendUploadProgress(filename) {
    const el = mk('div', 'upload-pill fade-in');
    el.innerHTML =
      `<div class="up-spinner"></div>` +
      `<div class="up-text">Extracting text from <strong>${esc(filename)}</strong>\u2026</div>`;
    thread.appendChild(el);
    scrollEnd();
    return el;
  }

  function appendPaperPill(filename, wordCount, idx, preview) {
    const el = mk('div', 'paper-pill fade-in');
    el.innerHTML =
      `<div class="pp-icon">&#128196;</div>` +
      `<div class="pp-body">` +
        `<div class="pp-name">${esc(filename)}</div>` +
        `<div class="pp-meta">${Number(wordCount).toLocaleString()} words extracted` +
          (preview ? ` &middot; &ldquo;${esc(preview.substring(0, 90))}&hellip;&rdquo;` : '') +
        `</div>` +
      `</div>` +
      `<div class="pp-badge">Paper ${idx} attached</div>`;
    thread.appendChild(el);
    scrollEnd();
    return el;
  }

  function appendPaperError(msg) {
    const el = mk('div', 'pp-error fade-in');
    el.innerHTML = `&#9888; ${esc(msg)}`;
    thread.appendChild(el);
    scrollEnd();
    setTimeout(() => el.remove(), 6000);
  }

  function updateAttachedUI() {
    const n = attachedPapers.length;
    if (n === 0) {
      attachedPapersBar.style.display = 'none';
      attachBtn.classList.remove('has-papers');
    } else {
      attachedPapersBar.style.display = '';
      attachedPapersLabel.textContent = `${n} paper${n > 1 ? 's' : ''} attached`;
      attachBtn.classList.add('has-papers');
      attachBtn.title = `${n} paper${n > 1 ? 's' : ''} attached — click to add another`;
    }
  }

  /* ══════════════════════════════════════════════════════════════════
     ASK  (unchanged from Phase 2 except session_id is sent)
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

      const res = await fetch('/api/study-builder/ask', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(body),
      });
      clearInterval(stageTmr);

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

      await renderAIMessage(aiEl, data);
      updateDbStrip(data.sources_searched || []);

    } catch (e) {
      clearInterval(stageTmr);
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
  async function renderAIMessage(el, d) {
    el.innerHTML = '';

    /* 1 — Evidence grade banner */
    const grade = (d.evidence_grade || 'VERY LOW').toUpperCase();
    const gm    = GRADE_META[grade] || GRADE_META['VERY LOW'];
    const banner = mk('div', `ev-banner ${gm.cls}`);
    banner.innerHTML =
      `<span class="ev-icon">${gm.icon}</span>` +
      `<span class="ev-label">${gm.label}</span>` +
      `<span class="ev-expl">${esc(d.evidence_grade_explanation || '')}</span>`;
    /* If uploaded papers contributed, note it */
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
      const p = mk('span', `src-db-pill${s === 'uploaded' ? ' pill-uploaded' : ''}`);
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
    const card = mk('div', `src-card${p.source === 'uploaded' ? ' src-card-uploaded' : ''}`);
    card.id = `ref-${num}`;

    const n = mk('div', 'sc-num'); n.textContent = `[${num}]`; card.appendChild(n);

    if (p.url) {
      const a = mk('a', 'sc-title');
      a.href = p.url; a.target = '_blank'; a.rel = 'noopener';
      a.textContent = p.title || 'Untitled';
      card.appendChild(a);
    } else {
      const s = mk('span', 'sc-title-plain');
      s.textContent = p.title || 'Untitled'; card.appendChild(s);
    }

    const meta = mk('div', 'sc-meta');
    const ev   = mk('span', `ev-tag ev-${p.evidence_type || 'observational'}`);
    ev.textContent = EV_LABELS[p.evidence_type] || 'Observational';
    meta.appendChild(ev);
    if (p.open_access) {
      const oa = mk('span', 'oa-tag'); oa.textContent = 'OA'; meta.appendChild(oa);
    }
    if (p.journal && p.source !== 'uploaded') {
      const j = mk('span'); j.textContent = p.journal; meta.appendChild(j);
    }
    if (p.year) { const y = mk('span'); y.textContent = p.year; meta.appendChild(y); }
    if (p.authors && p.authors.length && p.source !== 'uploaded') {
      const au = mk('span');
      au.textContent = p.authors.slice(0, 2).join(', ') + (p.authors.length > 2 ? ' et al.' : '');
      meta.appendChild(au);
    }
    if (p.citation_count > 0) {
      const c = mk('span'); c.textContent = `cited ${p.citation_count}\u00d7`; meta.appendChild(c);
    }
    const src = mk('span', 'src-tag');
    src.textContent = SRC_LABELS[p.source] || p.source || ''; meta.appendChild(src);
    card.appendChild(meta);

    /* Bookmark / pin button */
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
      'gemini-2.5-flash':  'Gemini 2.5 Flash',
      gemini:              'Gemini 2.5 Flash',
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
    /* Only include papers with a real title; skip uploaded-only papers for
       BibTeX/RIS as they have no bibliographic metadata. */
    const exportable = (papers || []).filter((p) => p.title && p.title.length > 3);
    if (exportable.length < 1) return null;

    const n    = exportable.length;
    const row  = mk('div', 'export-row');
    const lbl  = mk('span', 'export-label');
    lbl.textContent = `Export ${n} citation${n !== 1 ? 's' : ''} as:`;
    row.appendChild(lbl);

    /* Format buttons */
    [
      { label:'BibTeX',     ext:'.bib', fn: _toBibtex    },
      { label:'RIS',        ext:'.ris', fn: _toRis       },
      { label:'Vancouver',  ext:'.txt', fn: _toVancouver },
      { label:'Plain text', ext:'.txt', fn: _toPlainText },
    ].forEach(({ label, ext, fn }) => {
      const btn = mk('button', 'export-chip');
      btn.textContent = label;
      btn.addEventListener('click', () =>
        _dlText(`medras-citations${ext}`, fn(exportable))
      );
      row.appendChild(btn);
    });

    /* Copy-Vancouver shortcut */
    const copyBtn = mk('button', 'export-chip export-copy');
    copyBtn.textContent = 'Copy Vancouver';
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(_toVancouver(exportable))
        .then(() => {
          copyBtn.textContent = 'Copied \u2713';
          setTimeout(() => { copyBtn.textContent = 'Copy Vancouver'; }, 2000);
        })
        .catch(() => {
          /* clipboard blocked — fall back to download */
          _dlText('medras-citations.txt', _toVancouver(exportable));
        });
    });
    row.appendChild(copyBtn);

    return row;
  }

  /* ── Format generators ── */

  function _extractDoi(url) {
    if (!url) return '';
    const m = url.match(/doi\.org\/(.+)$/i);
    return m ? decodeURIComponent(m[1]).trim() : '';
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
      const auth = _fmtVancouverAuthors(p.authors || []);
      const doi  = _extractDoi(p.url);
      let   ref  = `${i + 1}. ${auth}${auth ? ' ' : ''}${p.title || 'Untitled'}.`;
      if (p.journal) ref += ` ${p.journal}.`;
      if (p.year)    ref += ` ${p.year}.`;
      if (doi)       ref += ` doi: ${doi}`;
      else if (p.url) ref += ` Available from: ${p.url}`;
      return ref.trim();
    }).join('\n');
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

  /* ══════════════════════════════════════════════════════════════════
     FOLIO  (Phase 5 — saved-papers sidebar)
  ══════════════════════════════════════════════════════════════════ */

  function _folioKey(p) {
    return ((p.url || p.title || '').trim().toLowerCase()).substring(0, 120);
  }

  function _isPinned(p) {
    const k = _folioKey(p);
    return folioItems.some((x) => _folioKey(x) === k);
  }

  function _togglePin(paperData, triggerBtn) {
    const k   = _folioKey(paperData);
    const idx = folioItems.findIndex((x) => _folioKey(x) === k);
    if (idx >= 0) {
      folioItems.splice(idx, 1);
    } else {
      folioItems.push({ ...paperData, _pinnedAt: Date.now() });
      /* Open panel briefly so the user sees the paper land */
      folioPanelEl.classList.add('open');
    }
    sessionStorage.setItem('sb.folio', JSON.stringify(folioItems));
    _renderFolio();
    _updateFolioToggle();
    /* Sync the button that was just clicked (covers papers with no URL) */
    if (triggerBtn) {
      const nowPinned = _isPinned(paperData);
      triggerBtn.classList.toggle('pinned', nowPinned);
      triggerBtn.title = nowPinned ? 'Remove from Folio' : 'Save to Folio';
    }
  }

  function _updateFolioToggle() {
    const n = folioItems.length;
    if (n === 0) {
      folioToggleBtn.style.display = 'none';
    } else {
      folioToggleBtn.style.display = '';
      folioBadge.textContent = String(n);
      folioBadge.classList.remove('badge-pulse');
      void folioBadge.offsetWidth;   /* force reflow to restart animation */
      folioBadge.classList.add('badge-pulse');
    }
  }

  function _renderFolio() {
    const n = folioItems.length;
    folioCount.textContent = n > 0 ? `${n} saved` : '';

    if (n === 0) {
      folioEmpty.style.display = '';
      folioList.style.display  = 'none';
      folioFoot.style.display  = 'none';
      return;
    }
    folioEmpty.style.display = 'none';
    folioList.style.display  = '';
    folioFoot.style.display  = '';

    folioList.innerHTML = '';
    folioItems.forEach((p) => folioList.appendChild(_buildFolioItem(p)));

    /* Sync pin-btn states across all source cards in the thread */
    document.querySelectorAll('.pin-btn[data-url]').forEach((btn) => {
      const pinned = folioItems.some((x) => (x.url || '').trim() === btn.dataset.url.trim());
      btn.classList.toggle('pinned', pinned);
      btn.title = pinned ? 'Remove from Folio' : 'Save to Folio';
    });
  }

  function _buildFolioItem(p) {
    const item = mk('div', 'folio-item');

    /* Top row: title + remove button */
    const top = mk('div', 'fi-top');
    const titleEl = p.url ? mk('a', 'fi-title') : mk('span', 'fi-title');
    if (p.url) { titleEl.href = p.url; titleEl.target = '_blank'; titleEl.rel = 'noopener'; }
    titleEl.textContent = p.title || 'Untitled';
    top.appendChild(titleEl);

    const rmBtn = mk('button', 'fi-remove');
    rmBtn.title     = 'Remove from Folio';
    rmBtn.innerHTML = '\u00d7';
    rmBtn.addEventListener('click', () => _togglePin(p, null));
    top.appendChild(rmBtn);
    item.appendChild(top);

    /* Meta row: evidence type · journal · year */
    const meta = mk('div', 'fi-meta');
    const ev   = mk('span', `ev-tag ev-${p.evidence_type || 'observational'}`);
    ev.textContent = EV_LABELS[p.evidence_type] || 'Paper';
    meta.appendChild(ev);

    if (p.journal && p.source !== 'uploaded') {
      const j = mk('span', 'fi-j'); j.textContent = p.journal; meta.appendChild(j);
    }
    if (p.year) { const y = mk('span', 'fi-y'); y.textContent = p.year; meta.appendChild(y); }
    item.appendChild(meta);

    return item;
  }

  function _dlText(filename, content) {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

})();
