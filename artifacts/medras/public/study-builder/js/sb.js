/* MedRAS Research Assistant — sb.js */
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

  const SRC_LABELS = {
    pubmed:'PubMed', cochrane:'Cochrane', europe_pmc:'Europe PMC',
    semantic_scholar:'Semantic Scholar', openalex:'OpenAlex',
    who_iris:'WHO IRIS', crossref:'Crossref', core:'CORE', medrxiv:'medRxiv',
    scopus:'Scopus',
  };
  const EV_LABELS = {
    systematic_review:'Sys. Review', rct:'RCT',
    observational:'Observational', guideline:'Guideline',
  };

  let busy = false;
  let inChat = false;

  /* ── Input auto-resize ── */
  function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 130) + 'px';
  }
  welcomeInp.addEventListener('input', () => autoResize(welcomeInp));
  chatInp.addEventListener('input', () => autoResize(chatInp));

  /* ── Enter to send ── */
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
    chatSend.disabled = welcomeSend.disabled = true;

    appendUser(question);
    const aiMsg  = appendAIPlaceholder();
    scrollEnd();

    try {
      const res  = await fetch('/api/study-builder/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      renderAIMessage(aiMsg, data);
      updateDbStrip(data.sources_searched || []);
    } catch (e) {
      aiMsg.innerHTML = `<div class="msg-error">⚠ ${esc(e.message || 'Request failed — please try again.')}</div>`;
    } finally {
      busy = false;
      chatSend.disabled = welcomeSend.disabled = false;
      scrollEnd();
    }
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
    const el   = mk('div', 'msg-ai fade-in');
    const wrap = mk('div', 'typing-wrap');
    for (let i = 0; i < 3; i++) wrap.appendChild(mk('div', 'typing-dot'));
    el.appendChild(wrap);
    thread.appendChild(el);
    return el;
  }

  function renderAIMessage(el, d) {
    el.innerHTML = '';

    /* answer body */
    const body = mk('div', 'msg-ai-body');
    body.innerHTML = renderMarkdown(d.answer || '');
    el.appendChild(body);

    /* meta pills */
    const meta = mk('div', 'msg-meta');
    const mp = mk('span', 'meta-tag tag-method');
    mp.textContent = methodLabel(d.synthesis_method);
    meta.appendChild(mp);
    if (d.total_found > 0) {
      const cp = mk('span', 'meta-tag tag-count');
      cp.textContent = `${d.total_found} papers found`;
      meta.appendChild(cp);
    }
    const oaCount = (d.papers || []).filter((p) => p.open_access).length;
    if (oaCount > 0) {
      const oa = mk('span', 'meta-tag tag-oa');
      oa.textContent = `${oaCount} open access`;
      meta.appendChild(oa);
    }
    el.appendChild(meta);

    /* sources */
    if (d.papers && d.papers.length) {
      el.appendChild(buildSources(d.papers, d.sources_searched || []));
    }

    /* follow-up chips */
    if (d.suggested_questions && d.suggested_questions.length) {
      const row = mk('div', 'followup-row');
      d.suggested_questions.forEach((q) => {
        const chip = mk('button', 'followup-chip');
        chip.textContent = q;
        chip.addEventListener('click', () => { chatInp.value = q; submitFromChat(); });
        row.appendChild(chip);
      });
      el.appendChild(row);
    }

    /* disclaimer */
    const disc = mk('div', 'disclaimer');
    disc.textContent = d.disclaimer || '';
    el.appendChild(disc);
  }

  function buildSources(papers, searched) {
    const wrap   = mk('div', 'sources-section');
    const head   = mk('div', 'sources-head');
    const label  = mk('span', 'src-toggle-label');
    label.textContent = `▶ ${papers.length} sources`;
    const arrow  = mk('span', 'src-toggle-arrow');
    const pills  = mk('div', 'src-db-pills');

    searched.forEach((s) => {
      const p = mk('span', 'src-db-pill');
      p.textContent = SRC_LABELS[s] || s;
      pills.appendChild(p);
    });

    head.appendChild(label);
    head.appendChild(arrow);
    head.appendChild(pills);

    const cards = mk('div', 'src-cards');
    papers.forEach((p, i) => cards.appendChild(buildSourceCard(p, i + 1)));

    head.addEventListener('click', () => {
      const open = cards.classList.toggle('open');
      arrow.classList.toggle('open', open);
      label.textContent = `${open ? '▼' : '▶'} ${papers.length} sources`;
    });

    wrap.appendChild(head);
    wrap.appendChild(cards);
    return wrap;
  }

  function buildSourceCard(p, num) {
    const card = mk('div', 'src-card');
    card.id = `ref-${num}`;

    const n = mk('div', 'sc-num');
    n.textContent = `[${num}]`;
    card.appendChild(n);

    if (p.url) {
      const a = mk('a', 'sc-title');
      a.href = p.url; a.target = '_blank'; a.rel = 'noopener';
      a.textContent = p.title || 'Untitled';
      card.appendChild(a);
    } else {
      const s = mk('span', 'sc-title-plain');
      s.textContent = p.title || 'Untitled';
      card.appendChild(s);
    }

    const meta = mk('div', 'sc-meta');

    const ev = mk('span', `ev-tag ev-${p.evidence_type || 'observational'}`);
    ev.textContent = EV_LABELS[p.evidence_type] || 'Observational';
    meta.appendChild(ev);

    if (p.open_access) {
      const oa = mk('span', 'oa-tag'); oa.textContent = 'Open Access';
      meta.appendChild(oa);
    }
    if (p.journal) {
      const j = mk('span'); j.textContent = p.journal; meta.appendChild(j);
    }
    if (p.year) {
      const y = mk('span'); y.textContent = p.year; meta.appendChild(y);
    }
    if (p.authors && p.authors.length) {
      const au = mk('span');
      au.textContent = p.authors.slice(0, 2).join(', ') + (p.authors.length > 2 ? ' et al.' : '');
      meta.appendChild(au);
    }
    if (p.citation_count > 0) {
      const c = mk('span'); c.textContent = `cited ${p.citation_count}×`; meta.appendChild(c);
    }
    const src = mk('span', 'src-tag');
    src.textContent = SRC_LABELS[p.source] || p.source || '';
    meta.appendChild(src);

    card.appendChild(meta);
    return card;
  }

  /* ── Markdown renderer ── */
  function renderMarkdown(raw) {
    if (!raw) return '';
    let text = esc(raw);

    /* citation refs [1] [1,2] → superscript links anchored to source cards */
    text = text.replace(/\[(\d+(?:,\s*\d+)*)\]/g, (_, nums) =>
      nums.split(',').map((n) => {
        const id = n.trim();
        return `<a class="cite" href="#ref-${id}">[${id}]</a>`;
      }).join('')
    );

    /* headings */
    text = text.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    text = text.replace(/^## (.+)$/gm,  '<h3>$1</h3>');

    /* bold / italic */
    text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/\*(.+?)\*/g,     '<em>$1</em>');

    /* bullet lists — collect runs */
    text = text.replace(/((?:^[-•] .+\n?)+)/gm, (block) => {
      const items = block.trim().split('\n').map((l) => `<li>${l.replace(/^[-•] /, '')}</li>`).join('');
      return `<ul>${items}</ul>`;
    });

    /* References section — style it */
    text = text.replace(
      /(References\n)([\s\S]+?)($|(?=\n\n))/g,
      (_, heading, body) => {
        const lines = body.trim().split('\n').map((l) => `<p>${l}</p>`).join('');
        return `<div class="ref-section"><strong>References</strong>${lines}</div>`;
      }
    );

    /* paragraphs — wrap non-tagged lines */
    text = text
      .split('\n\n')
      .map((chunk) => {
        chunk = chunk.trim();
        if (!chunk) return '';
        if (/^<(h[234]|ul|ol|div)/.test(chunk)) return chunk;
        return `<p>${chunk.replace(/\n/g, '<br>')}</p>`;
      })
      .join('\n');

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
  function methodLabel(m) {
    return { 'gpt-4o-mini': 'GPT-4o-mini', gemini: 'Gemini 2.5 Flash',
             raw_sources: 'Sources only', no_papers: 'No results' }[m] || m;
  }

  function esc(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
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
