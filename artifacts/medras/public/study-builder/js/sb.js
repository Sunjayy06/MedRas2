/* Study Builder — Part 1: Medical Knowledge Assistant */
(function () {
  'use strict';

  const chatEl    = document.getElementById('sb-chat');
  const inputEl   = document.getElementById('sb-input');
  const sendBtn   = document.getElementById('sb-send');
  const welcomeEl = document.getElementById('sb-welcome');

  const SRC = {
    pubmed:'PubMed', cochrane_via_epmc:'Cochrane', europe_pmc:'Europe PMC',
    semantic_scholar:'Semantic Scholar', openalex:'OpenAlex', who_iris:'WHO IRIS',
  };
  const EVL = {
    systematic_review:'Systematic Review', rct:'RCT',
    observational:'Observational', guideline:'Guideline',
  };

  let busy = false;

  inputEl.addEventListener('input', () => {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 130) + 'px';
  });
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
  });
  sendBtn.addEventListener('click', submit);
  document.querySelectorAll('.sb-eg').forEach((b) => {
    b.addEventListener('click', () => { inputEl.value = b.dataset.q; submit(); });
  });

  function submit() {
    const q = inputEl.value.trim();
    if (!q || busy) return;
    inputEl.value = ''; inputEl.style.height = 'auto';
    sendQuestion(q);
  }

  function sendQuestion(question) {
    busy = true; sendBtn.disabled = true;
    if (welcomeEl) welcomeEl.style.display = 'none';
    appendUser(question);
    const typingEl = appendTyping();
    scrollEnd();

    fetch('/api/study-builder/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    })
    .then((r) => { if (!r.ok) return r.json().then((d) => Promise.reject(d)); return r.json(); })
    .then((d) => { typingEl.remove(); appendAnswer(d); })
    .catch((e) => { typingEl.remove(); appendError(e?.detail || 'Search failed — please try again.'); })
    .finally(() => { busy = false; sendBtn.disabled = false; scrollEnd(); });
  }

  function appendUser(text) {
    const msg = mk('div','msg msg-user');
    const b   = mk('div','msg-bubble'); b.textContent = text;
    msg.appendChild(b); chatEl.appendChild(msg);
  }

  function appendTyping() {
    const msg  = mk('div','msg msg-ai');
    const wrap = mk('div','typing');
    for (let i=0;i<3;i++) wrap.appendChild(mk('div','typing-dot'));
    msg.appendChild(wrap); chatEl.appendChild(msg); return msg;
  }

  function appendError(text) {
    const msg = mk('div','msg msg-ai');
    const b   = mk('div','msg-bubble'); b.style.color='#f87171'; b.textContent='⚠ '+text;
    msg.appendChild(b); chatEl.appendChild(msg);
  }

  function appendAnswer(d) {
    const msg = mk('div','msg msg-ai');
    const bub = mk('div','msg-bubble');

    const body = mk('div','answer-body');
    body.innerHTML = citify(d.answer);
    bub.appendChild(body);

    const meta = mk('div','answer-meta');
    const mp = mk('span','meta-pill pill-method');
    mp.textContent = mlabel(d.synthesis_method); meta.appendChild(mp);
    if (d.total_found > 0) {
      const cp = mk('span','meta-pill pill-count');
      cp.textContent = d.total_found + ' papers found'; meta.appendChild(cp);
    }
    bub.appendChild(meta);

    if (d.papers && d.papers.length) {
      const tog  = mk('button','sources-toggle');
      const arr  = mk('span','toggle-arrow'); arr.textContent = '▶';
      tog.appendChild(arr);
      tog.appendChild(document.createTextNode(' Sources (' + d.papers.length + ')'));
      const list = mk('div','sources-list');
      d.papers.forEach((p,i) => list.appendChild(paperCard(p, i+1)));
      tog.addEventListener('click', () => { tog.classList.toggle('open'); list.classList.toggle('open'); });
      bub.appendChild(tog); bub.appendChild(list);
    }

    if (d.sources_searched && d.sources_searched.length) {
      const strip = mk('div','db-strip');
      const lbl = mk('span','db-strip-label'); lbl.textContent = 'Searched:';
      strip.appendChild(lbl);
      d.sources_searched.forEach((s) => {
        const t = mk('span','db-tag'); t.textContent = SRC[s]||s; strip.appendChild(t);
      });
      bub.appendChild(strip);
    }

    if (d.suggested_questions && d.suggested_questions.length) {
      const wrap = mk('div','sugg-wrap');
      const lbl  = mk('div','sugg-label'); lbl.textContent = 'You might also ask';
      wrap.appendChild(lbl);
      const chips = mk('div','sugg-chips');
      d.suggested_questions.forEach((q) => {
        const c = mk('button','sugg-chip'); c.textContent = q;
        c.addEventListener('click', () => sendQuestion(q));
        chips.appendChild(c);
      });
      wrap.appendChild(chips); bub.appendChild(wrap);
    }

    if (d.action_buttons && d.action_buttons.length) {
      const row = mk('div','action-row');
      d.action_buttons.forEach((btn) => {
        const a = mk('a','action-btn'+(btn.action==='sample_size'?' secondary':''));
        a.textContent = btn.label;
        if (btn.url) { a.href=btn.url; a.target=btn.external?'_blank':'_self'; if(btn.external)a.rel='noopener'; }
        row.appendChild(a);
      });
      bub.appendChild(row);
    }

    const disc = mk('div','disclaimer'); disc.textContent = d.disclaimer;
    bub.appendChild(disc);

    msg.appendChild(bub); chatEl.appendChild(msg);
  }

  function paperCard(p, num) {
    const card = mk('div','paper-card'); card.id = 'ref-'+num;
    const n = mk('div','paper-num'); n.textContent = '['+num+']'; card.appendChild(n);
    if (p.url) {
      const a = mk('a','paper-title-link');
      a.href=p.url; a.target='_blank'; a.rel='noopener';
      a.textContent = p.title||'Untitled'; card.appendChild(a);
    } else {
      const s = mk('span','paper-title-nolink'); s.textContent=p.title||'Untitled'; card.appendChild(s);
    }
    const info = mk('div','paper-info');
    const ev = mk('span','ev-badge ev-'+(p.evidence_type||'observational'));
    ev.textContent = EVL[p.evidence_type]||'Observational'; info.appendChild(ev);
    if (p.journal) { const j=mk('span');j.textContent=p.journal;info.appendChild(j); }
    if (p.year)    { const y=mk('span');y.textContent=p.year;info.appendChild(y); }
    if (p.authors && p.authors.length) {
      const au=mk('span');
      au.textContent=p.authors.slice(0,2).join(', ')+(p.authors.length>2?' et al.':'');
      info.appendChild(au);
    }
    if (p.citation_count>0) {
      const c=mk('span','cite-count');c.textContent='cited '+p.citation_count+'\u00d7';info.appendChild(c);
    }
    const src=mk('span','src-tag');src.textContent=SRC[p.source]||p.source||'';info.appendChild(src);
    card.appendChild(info); return card;
  }

  function citify(text) {
    if (!text) return '';
    const esc = text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    return esc.replace(/\[(\d+(?:,\s*\d+)*)\]/g, (_,nums) =>
      nums.split(',').map((n) => {
        const id=n.trim();
        return '<sup><a href="#ref-'+id+'">['+id+']</a></sup>';
      }).join('')
    );
  }

  function mlabel(m) {
    return {'gpt-4o-mini':'GPT-4o-mini',gemini:'Gemini',raw_sources:'Sources only',no_papers:'No results'}[m]||m;
  }
  function mk(tag,cls) { const e=document.createElement(tag);if(cls)e.className=cls;return e; }
  function scrollEnd() { chatEl.scrollTop=chatEl.scrollHeight; }

})();
