/* MedRAS Research Assistant — sb.js  (Phase 2: Conversational UX) */
(function () {
  'use strict';

  /* ── DOM ── */
  const welcome     = document.getElementById('welcome');
  const thread      = document.getElementById('thread');
  const chatBar     = document.getElementById('chat-bar');
  const welcomeInp  = document.getElementById('welcome-input');
  const welcomeSend = document.getElementById('welcome-send');
  const chatInp     = document.getElementById('chat-input');
  const chatSend    = document.getElementById('chat-send');
  const dbStrip     = document.getElementById('db-strip');
  const newChatBtn  = document.getElementById('new-chat-btn');
  const raWrap      = document.getElementById('ra-wrap');

  /* ── Source / evidence labels ── */
  const SRC_LABELS = {
    pubmed:'PubMed', cochrane:'Cochrane', europe_pmc:'Europe PMC',
    pmc:'PubMed Central', semantic_scholar:'Semantic Scholar',
    openalex:'OpenAlex', who_iris:'WHO IRIS', crossref:'Crossref',
    core:'CORE', medrxiv:'medRxiv', clinicaltrials:'ClinicalTrials.gov',
    doaj:'DOAJ', lens:'Lens.org', ieee:'IEEE Xplore',
    wos:'Web of Science', scopus:'Scopus',
  };
  const EV_LABELS = {
    systematic_review:'Sys. Review', rct:'RCT',
    observational:'Observational', guideline:'Guideline',
  };
  const GRADE_META = {
    HIGH:      { cls:'grade-high',     label:'HIGH EVIDENCE',      icon:'◆' },
    MODERATE:  { cls:'grade-moderate', label:'MODERATE EVIDENCE',  icon:'◈' },
    LOW:       { cls:'grade-low',      label:'LOW EVIDENCE',       icon:'◇' },
    'VERY LOW':{ cls:'grade-verylow',  label:'VERY LOW EVIDENCE',  icon:'○' },
  };

  /* ── Session state ── */
  let sessionId = sessionStorage.getItem('sb.session_id') || null;
  let busy      = false;
  let inChat    = false;

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
  chatInp.addEventListener('input', () => autoResize(chatInp));

  /* ── Keyboard shortcuts ── */
  welcomeInp.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitFromWelcome(); }
  });
  chatInp.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitFromChat(); }
  });
  welcomeSend.addEventListener('click', submitFromWelcome);
  chatSend.addEventListener('click', submitFromChat);

  /* ── Topic cards ── */
  document.querySelectorAll('.topic-card').forEach((btn) => {
    btn.addEventListener('click', () => {
      welcomeInp.value = btn.dataset.q;
      submitFromWelcome();
    });
  });

  /* ── New chat ── */
  newChatBtn.addEventListener('click', () => {
    thread.innerHTML = '';
    sessionId = null;
    sessionStorage.removeItem('sb.session_id');
    sessionStorage.removeItem('medras.nav.returnHint');
    switchToWelcome();
  });

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

  /* ── Core ask ── */
  async function ask(question) {
    busy = true;
    setSendState(true);

    appendUser(question);
    const { aiEl, stageEl } = appendAIPlaceholder();
    scrollEnd();

    /* Stage cycling timer */
    let stageIdx   = 0;
    const stageTmr = setInterval(() => {
      stageIdx = Math.min(stageIdx + 1, STAGES.length - 1);
      if (stageEl) stageEl.textContent = STAGES[stageIdx];
    }, 2600);

    try {
      const body = { question };
      if (sessionId) body.session_id = sessionId;

      const res  = await fetch('/api/study-builder/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
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
          module: 'helix',
          label:  'your research question',
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

    /* 1 ── Evidence grade banner */
    const grade = (d.evidence_grade || 'VERY LOW').toUpperCase();
    const gm    = GRADE_META[grade] || GRADE_META['VERY LOW'];
    const banner = mk('div', `ev-banner ${gm.cls}`);
    banner.innerHTML =
      `<span class="ev-icon">${gm.icon}</span>` +
      `<span class="ev-label">${gm.label}</span>` +
      `<span class="ev-expl">${esc(d.evidence_grade_explanation || '')}</span>`;
    el.appendChild(banner);

    /* 2 ── Summary (typewriter) */
    const summaryWrap = mk('div', 'msg-ai-body');
    el.appendChild(summaryWrap);
    scrollEnd();

    /* Extract just the summary paragraph (first paragraph of answer) */
    const answerText  = d.answer || '';
    const summaryText = extractSummary(answerText);
    await typewrite(summaryWrap, summaryText, 14);

    /* 3 ── Structured sections (appear after typewriter) */

    /* Key findings */
    const findings = d.key_findings || [];
    if (findings.length) {
      const section = mk('div', 'answer-section findings-section');
      const h = mk('div', 'section-label');
      h.textContent = 'Key findings';
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

    /* What agrees / What is debated — side by side if both exist */
    const agrees  = d.what_agrees  || '';
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
        const li = mk('li');
        li.innerHTML = highlightStats(esc(c));
        ul.appendChild(li);
      });
      callout.appendChild(ul);
      el.appendChild(callout);
    }

    /* Limitations */
    const limits = d.limitations || '';
    if (limits) {
      const lim = mk('div', 'limitations-note');
      lim.innerHTML =
        `<span class="lim-label">Limitations:</span> ${highlightStats(esc(limits))}`;
      el.appendChild(lim);
    }

    /* 4 ── Action buttons */
    const topic = encodeURIComponent((d.answer || '').substring(0, 120));
    const actRow = mk('div', 'action-row');
    const actions = [
      { label: 'Take to Proposal Writer', url: '/proposal-module/', icon: '✦', primary: true },
      { label: 'Design a study on this',  url: '/study-builder/design.html', icon: '⊹', primary: false },
      { label: 'Calculate sample size',   url: '/sample-size.html', icon: '∑', primary: false },
    ];
    actions.forEach(({ label, url, icon, primary }) => {
      const btn = mk('a', `action-btn${primary ? ' action-btn-primary' : ''}`);
      btn.href = url;
      btn.innerHTML = `<span>${icon}</span> ${label}`;
      /* Proposal handoff via sessionStorage */
      if (url.includes('proposal')) {
        btn.addEventListener('click', () => {
          try {
            sessionStorage.setItem('medras.proposal.intake.background_hint', d.answer || '');
          } catch (_) {}
        });
      }
      actRow.appendChild(btn);
    });
    el.appendChild(actRow);

    /* 5 ── Meta row */
    const meta = mk('div', 'msg-meta');
    addTag(meta, methodLabel(d.synthesis_method), 'tag-method');
    if (d.total_found > 0) addTag(meta, `${d.total_found} papers found`, 'tag-count');
    const oaCount = (d.papers || []).filter((p) => p.open_access).length;
    if (oaCount > 0) addTag(meta, `${oaCount} open access`, 'tag-oa');
    el.appendChild(meta);

    /* 6 ── Sources (collapsible) */
    if (d.papers && d.papers.length) {
      el.appendChild(buildSources(d.papers, d.sources_searched || []));
    }

    /* 7 ── Follow-up chips (AI-generated) */
    const questions = d.suggested_questions || [];
    if (questions.length) {
      const row = mk('div', 'followup-row');
      questions.forEach((q) => {
        const chip = mk('button', 'followup-chip');
        chip.textContent = q;
        chip.addEventListener('click', () => {
          chatInp.value = q;
          submitFromChat();
        });
        row.appendChild(chip);
      });
      el.appendChild(row);
    }

    /* 8 ── Disclaimer */
    const disc = mk('div', 'disclaimer');
    disc.textContent = d.disclaimer || '';
    el.appendChild(disc);

    scrollEnd();
  }

  /* ── Typewriter effect ── */
  function typewrite(container, text, msPerChar) {
    return new Promise((resolve) => {
      if (!text) { resolve(); return; }
      /* Render as HTML then typewrite the visible text character by character */
      const html   = renderMarkdown(text);
      const tmp    = document.createElement('div');
      tmp.innerHTML = html;
      const full   = tmp.innerHTML;

      /* Strip tags to get char count, then reveal full html at each char boundary */
      const plainLen = tmp.textContent.length;
      if (plainLen === 0) { container.innerHTML = full; resolve(); return; }

      let charIdx = 0;
      /* Build a char-indexed reveal by inserting a marker and slicing */
      const chars  = tmp.textContent;

      function step() {
        charIdx += 2; /* 2 chars per frame for snappy feel */
        if (charIdx >= plainLen) {
          container.innerHTML = full;
          highlightStatsDom(container);
          resolve();
          return;
        }
        /* Reveal partial text — simple approach: show rendered HTML up to char boundary */
        const partial = buildPartialHTML(tmp, charIdx);
        container.innerHTML = partial;
        scrollEnd();
        setTimeout(step, msPerChar);
      }
      step();
    });
  }

  /* Build partial HTML by walking nodes and cutting at charIdx */
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
      let inner   = '';
      for (const child of node.childNodes) {
        inner += walk(child);
        if (remaining <= 0) break;
      }
      const attrs = Array.from(node.attributes)
        .map((a) => ` ${a.name}="${a.value}"`)
        .join('');
      return `<${tag}${attrs}>${inner}</${tag}>`;
    }
    let out = '';
    for (const child of root.childNodes) {
      out += walk(child);
      if (remaining <= 0) break;
    }
    return out;
  }

  /* Extract the summary (first meaningful paragraph) from the full answer */
  function extractSummary(answerText) {
    const lines = answerText.split('\n');
    let para = '';
    for (const line of lines) {
      const t = line.trim();
      if (!t) { if (para) break; continue; }
      if (t.startsWith('**') && t.endsWith('**')) break; /* section heading */
      if (t.startsWith('- ') || t.startsWith('* ')) break;
      if (t.startsWith('[') && t.match(/^\[\d+\]/)) break;
      para = t;
      break;
    }
    return para || answerText.split('\n\n')[0] || answerText.substring(0, 300);
  }

  /* ── Statistical value highlighter ── */
  function highlightStats(escapedText) {
    /* Input is already HTML-escaped — apply regex to highlight stat patterns */
    return escapedText.replace(STAT_RE, (m) =>
      `<mark class="stat-hl">${m}</mark>`
    );
  }

  function highlightStatsDom(container) {
    /* Walk text nodes and wrap stat patterns */
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null);
    const toReplace = [];
    let node;
    while ((node = walker.nextNode())) {
      if (STAT_RE.test(node.textContent)) {
        toReplace.push(node);
      }
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
    label.textContent = `▶ ${papers.length} sources`;
    const pills = mk('div', 'src-db-pills');
    searched.forEach((s) => {
      const p = mk('span', 'src-db-pill');
      p.textContent = SRC_LABELS[s] || s;
      pills.appendChild(p);
    });
    head.appendChild(label);
    head.appendChild(pills);

    const cards = mk('div', 'src-cards');
    papers.forEach((p, i) => cards.appendChild(buildSourceCard(p, i + 1)));

    head.addEventListener('click', () => {
      const open = cards.classList.toggle('open');
      label.textContent = `${open ? '▼' : '▶'} ${papers.length} sources`;
    });
    wrap.appendChild(head);
    wrap.appendChild(cards);
    return wrap;
  }

  function buildSourceCard(p, num) {
    const card = mk('div', 'src-card');
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
    if (p.journal) { const j = mk('span'); j.textContent = p.journal; meta.appendChild(j); }
    if (p.year)    { const y = mk('span'); y.textContent = p.year;    meta.appendChild(y); }
    if (p.authors && p.authors.length) {
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
    return card;
  }

  /* ── Markdown renderer ── */
  function renderMarkdown(raw) {
    if (!raw) return '';
    let text = esc(raw);
    /* citations → superscript links */
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
    text = text.replace(/((?:^[-•] .+\n?)+)/gm, (block) => {
      const items = block.trim().split('\n')
        .map((l) => `<li>${l.replace(/^[-•] /, '')}</li>`).join('');
      return `<ul>${items}</ul>`;
    });
    text = text
      .split('\n\n')
      .map((chunk) => {
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
    t.textContent = text;
    parent.appendChild(t);
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

  function scrollEnd() {
    raWrap.scrollTop = raWrap.scrollHeight;
  }

})();
