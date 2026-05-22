/* Study Builder Part 2 — Study Design & Proposal Builder */
(function () {
  'use strict';

  const TOTAL_STEPS = 6;
  const SK = 'medras.studydesign.state';

  /* ─── state ─── */
  let state = {
    step: 1,
    question: '', objective_type: 'analytical',
    pico: { P: '', I: '', C: '', O: '' },
    selectedDesignId: '', selectedDesignName: '',
    recommendations: [], general_advice: '', all_designs: [],
    methodology: {}, stats: {}, ethics: {
      iec: false, consent: true, helsinki: false, icmr: false,
      risk: 'minimal', waiver: false, waiver_justification: ''
    },
    export_text: '', title: '',
  };

  function saveState() {
    try { sessionStorage.setItem(SK, JSON.stringify(state)); } catch (_) {}
  }
  function loadState() {
    try {
      const s = sessionStorage.getItem(SK);
      if (s) state = { ...state, ...JSON.parse(s) };
    } catch (_) {}
  }

  /* ─── DOM refs ─── */
  const stepCards = () => document.querySelectorAll('.step-card');
  const psDots    = () => document.querySelectorAll('.ps');
  const btnBack   = document.getElementById('btn-back');
  const btnNext   = document.getElementById('btn-next');
  const stepInfo  = document.getElementById('step-info');

  /* ─── progress ─── */
  function renderProgress() {
    psDots().forEach((el, i) => {
      el.classList.toggle('done', i + 1 < state.step);
      el.classList.toggle('active', i + 1 === state.step);
    });
    stepInfo.textContent = `Step ${state.step} of ${TOTAL_STEPS}`;
    btnBack.disabled = state.step === 1;
    btnNext.textContent = state.step === TOTAL_STEPS ? 'Finish' : 'Next →';
    btnNext.classList.remove('loading');
    btnNext.disabled = false;
  }

  function showStep(n) {
    stepCards().forEach((c, i) => c.classList.toggle('active', i + 1 === n));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  /* ─── Step 1: Research Question ─── */
  function initStep1() {
    const q   = document.getElementById('s1-question');
    const obj = document.getElementById('s1-objective');
    const title = document.getElementById('s1-title');
    if (q)     q.value   = state.question;
    if (obj)   obj.value = state.objective_type;
    if (title) title.value = state.title || '';
    q?.addEventListener('input', () => { state.question = q.value.trim(); saveState(); });
    obj?.addEventListener('change', () => { state.objective_type = obj.value; saveState(); });
    title?.addEventListener('input', () => { state.title = title.value.trim(); saveState(); });
    ['P','I','C','O'].forEach((k) => {
      const el = document.getElementById('pico-'+k);
      if (el) {
        el.value = state.pico[k] || '';
        el.addEventListener('input', () => { state.pico[k] = el.value.trim(); saveState(); });
      }
    });
  }

  function validateStep1() {
    if (!state.question || state.question.length < 10) {
      alert('Please enter a research question (at least 10 characters).'); return false;
    }
    if (!state.pico.P && !state.pico.O) {
      alert('Please fill in at least Population (P) and Outcome (O) in the PICO framework.'); return false;
    }
    return true;
  }

  /* ─── Step 2: Design Selection ─── */
  let designsLoaded = false;

  async function loadDesigns() {
    if (designsLoaded && state.recommendations.length) {
      renderDesigns(); return;
    }
    const container = document.getElementById('design-container');
    container.innerHTML = `<div class="designs-loading"><div class="loading-spinner"></div><br>Analysing your research question and recommending study designs…</div>`;
    btnNext.disabled = true;

    try {
      const r = await fetch('/api/study-builder/design/recommend', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: state.question, pico: state.pico,
                               objective_type: state.objective_type }),
      });
      const d = await r.json();
      state.recommendations = d.recommendations || [];
      state.general_advice  = d.general_advice  || '';
      state.all_designs     = d.all_designs      || [];
      saveState();
      designsLoaded = true;
    } catch (e) {
      container.innerHTML = `<div class="designs-loading" style="color:#f87171">⚠ Could not load design recommendations. Please try again.</div>`;
      btnNext.disabled = false; return;
    }
    renderDesigns();
    btnNext.disabled = false;
  }

  function renderDesigns() {
    const container = document.getElementById('design-container');
    let html = '';
    if (state.general_advice) {
      html += `<div class="ai-advice"><div class="ai-advice-label">AI Methodologist</div>${esc(state.general_advice)}</div>`;
    }
    html += `<div class="design-cards" id="rec-cards">`;
    (state.recommendations || []).forEach((d) => {
      const isSel = d.id === state.selectedDesignId;
      const feas  = d.feasibility || 'medium';
      html += `
        <div class="design-card ai-rec${isSel?' selected':''}" data-id="${d.id}" data-name="${esc(d.name)}">
          <div class="design-sel-mark">${isSel?'✓':''}</div>
          <div class="design-card-head">
            <div class="design-icon">${d.icon||'📋'}</div>
            <div class="design-info">
              <div class="design-name">${esc(d.name)}<span class="design-cat">${esc(d.category||'')}</span></div>
              <div class="design-desc">${esc(d.description||'')}</div>
            </div>
          </div>
          <div class="design-meta">
            <span class="dmeta-pill ev-pill">Level ${d.evidence_level||'—'}</span>
            <span class="dmeta-pill feas-pill-${feas}">Feasibility: ${cap(feas)}</span>
            ${d.timeline_estimate?`<span class="dmeta-pill timeline-pill">~${esc(d.timeline_estimate)}</span>`:''}
          </div>
          <div class="design-rationale">${esc(d.rationale||'')}</div>
          ${d.key_consideration?`<div class="design-rationale" style="display:block;color:var(--sb-teal-lt);font-size:.77rem">💡 ${esc(d.key_consideration)}</div>`:''}
        </div>`;
    });
    html += `</div>`;
    html += `<button class="show-more-btn" id="show-more-btn">Show all study designs ▼</button>`;
    html += `<div class="all-designs-wrap" id="all-designs-wrap">
      <div class="all-designs-grid" id="all-designs-grid">`;
    (state.all_designs || []).forEach((d) => {
      const isSel = d.id === state.selectedDesignId;
      html += `<div class="mini-design-card${isSel?' selected':''}" data-id="${d.id}" data-name="${esc(d.name)}">
        <div class="mini-icon">${d.icon||'📋'}</div>
        <div><div class="mini-name">${esc(d.name)}</div><div class="mini-cat">${esc(d.category||'')} · Level ${d.evidence_level||'—'}</div></div>
      </div>`;
    });
    html += `</div></div>`;
    container.innerHTML = html;

    container.querySelectorAll('.design-card[data-id],.mini-design-card[data-id]').forEach((el) => {
      el.addEventListener('click', () => {
        state.selectedDesignId   = el.dataset.id;
        state.selectedDesignName = el.dataset.name;
        saveState();
        designsLoaded = false;
        renderDesigns();
      });
    });
    document.getElementById('show-more-btn')?.addEventListener('click', () => {
      const w = document.getElementById('all-designs-wrap');
      w.classList.toggle('open');
      document.getElementById('show-more-btn').textContent =
        w.classList.contains('open') ? 'Hide ▲' : 'Show all study designs ▼';
    });
  }

  function validateStep2() {
    if (!state.selectedDesignId) { alert('Please select a study design.'); return false; }
    return true;
  }

  /* ─── Step 3: Methodology ─── */
  let methLoaded = false;

  async function loadMethodology() {
    if (methLoaded && Object.keys(state.methodology).length) {
      renderMethodology(); return;
    }
    const cont = document.getElementById('meth-container');
    cont.innerHTML = `<div class="meth-loading"><div class="loading-spinner"></div><br>Generating methodology for ${esc(state.selectedDesignName)}…</div>`;
    btnNext.disabled = true;

    try {
      const r = await fetch('/api/study-builder/design/methodology', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: state.question, pico: state.pico,
                               design_id: state.selectedDesignId, extra: {} }),
      });
      const d = await r.json();
      state.methodology = d.methodology || {};
      saveState(); methLoaded = true;
    } catch (e) {
      cont.innerHTML = `<div class="meth-loading" style="color:#f87171">⚠ Could not generate methodology. Please try again.</div>`;
      btnNext.disabled = false; return;
    }
    renderMethodology();
    btnNext.disabled = false;
  }

  function renderMethodology() {
    const m    = state.methodology;
    const cont = document.getElementById('meth-container');
    cont.innerHTML = `
      <div class="meth-grid">
        <div class="field">
          <label class="field-label">Study Setting</label>
          <input class="field-input" id="m-setting" value="${esc(m.study_setting||'')}" placeholder="e.g. Tertiary care hospital OPD"/>
        </div>
        <div class="field">
          <label class="field-label">Study Period</label>
          <input class="field-input" id="m-period" value="${esc(m.study_period||'')}" placeholder="e.g. 12 months"/>
        </div>
        <div class="field meth-full">
          <label class="field-label">Study Population</label>
          <textarea class="field-input" id="m-population" rows="2">${esc(m.study_population||'')}</textarea>
        </div>
        <div class="field">
          <label class="field-label">Sampling Technique</label>
          <input class="field-input" id="m-sampling" value="${esc(m.sampling_technique||'')}" placeholder="e.g. Consecutive sampling"/>
        </div>
        <div class="field">
          <label class="field-label">Data Collection Tool</label>
          <input class="field-input" id="m-tool" value="${esc(m.data_collection_tool||'')}" placeholder="e.g. Structured proforma"/>
        </div>
        <div class="field meth-full">
          <label class="field-label">Primary Outcome</label>
          <input class="field-input" id="m-primary-outcome" value="${esc(m.primary_outcome||'')}" placeholder="Define with measurement scale"/>
        </div>
      </div>

      <div class="field" style="margin-top:.75rem">
        <label class="field-label">Inclusion Criteria</label>
        <div class="list-editor" id="inc-list"></div>
        <button class="list-add-btn" id="add-inc">+ Add inclusion criterion</button>
      </div>
      <div class="field">
        <label class="field-label">Exclusion Criteria</label>
        <div class="list-editor" id="exc-list"></div>
        <button class="list-add-btn" id="add-exc">+ Add exclusion criterion</button>
      </div>
      <div class="field">
        <label class="field-label">Secondary Outcomes</label>
        <div class="list-editor" id="sec-out-list"></div>
        <button class="list-add-btn" id="add-sec-out">+ Add secondary outcome</button>
      </div>

      <div class="field" style="margin-top:.5rem">
        <label class="field-label">Study Variables</label>
        <table class="vars-table">
          <thead><tr><th>Variable Name</th><th>Type</th><th>Scale</th><th></th></tr></thead>
          <tbody id="vars-tbody"></tbody>
        </table>
        <button class="add-var-row" id="add-var">+ Add variable</button>
      </div>
    `;

    initListEditor('inc-list', 'add-inc', m.inclusion_criteria || []);
    initListEditor('exc-list', 'add-exc', m.exclusion_criteria || []);
    initListEditor('sec-out-list', 'add-sec-out', m.secondary_outcomes || []);
    initVarsTable(m.variables || []);

    ['m-setting','m-period','m-population','m-sampling','m-tool','m-primary-outcome'].forEach((id) => {
      document.getElementById(id)?.addEventListener('input', saveMeth);
    });
  }

  function saveMeth() {
    state.methodology.study_setting       = val('m-setting');
    state.methodology.study_period        = val('m-period');
    state.methodology.study_population    = val('m-population');
    state.methodology.sampling_technique  = val('m-sampling');
    state.methodology.data_collection_tool= val('m-tool');
    state.methodology.primary_outcome     = val('m-primary-outcome');
    state.methodology.inclusion_criteria  = listVals('inc-list');
    state.methodology.exclusion_criteria  = listVals('exc-list');
    state.methodology.secondary_outcomes  = listVals('sec-out-list');
    state.methodology.variables           = tableVars();
    saveState();
  }

  function initListEditor(listId, addId, initial) {
    const list = document.getElementById(listId);
    const addBtn = document.getElementById(addId);
    (initial.length ? initial : ['']).forEach((v) => addListRow(list, v));
    addBtn?.addEventListener('click', () => { addListRow(list, ''); });
  }

  function addListRow(list, value) {
    const row = mk('div','list-item-row');
    const inp = mk('input','list-item-input'); inp.value = value;
    inp.placeholder = 'Enter criterion…';
    inp.addEventListener('input', saveMeth);
    const del = mk('button','list-item-del'); del.textContent = '✕';
    del.addEventListener('click', () => { row.remove(); saveMeth(); });
    row.appendChild(inp); row.appendChild(del); list.appendChild(row);
  }

  function listVals(id) {
    return [...document.querySelectorAll(`#${id} .list-item-input`)]
      .map((el) => el.value.trim()).filter(Boolean);
  }

  function initVarsTable(vars) {
    const tbody = document.getElementById('vars-tbody');
    (vars.length ? vars : []).forEach((v) => addVarRow(tbody, v));
    document.getElementById('add-var')?.addEventListener('click', () =>
      addVarRow(tbody, { name: '', type: 'independent', scale: 'nominal' }));
  }

  function addVarRow(tbody, v) {
    const tr = mk('tr','');
    tr.innerHTML = `
      <td><input value="${esc(v.name||'')}" placeholder="Variable name"/></td>
      <td><select><option value="independent"${v.type==='independent'?' selected':''}>Independent</option>
        <option value="dependent"${v.type==='dependent'?' selected':''}>Dependent</option>
        <option value="confounding"${v.type==='confounding'?' selected':''}>Confounding</option></select></td>
      <td><select><option value="nominal"${v.scale==='nominal'?' selected':''}>Nominal</option>
        <option value="ordinal"${v.scale==='ordinal'?' selected':''}>Ordinal</option>
        <option value="interval"${v.scale==='interval'?' selected':''}>Interval</option>
        <option value="ratio"${v.scale==='ratio'?' selected':''}>Ratio</option></select></td>
      <td><button class="var-del">✕</button></td>`;
    tr.querySelectorAll('input,select').forEach((el) => el.addEventListener('input', saveMeth));
    tr.querySelector('.var-del')?.addEventListener('click', () => { tr.remove(); saveMeth(); });
    tbody.appendChild(tr);
  }

  function tableVars() {
    return [...document.querySelectorAll('#vars-tbody tr')].map((tr) => {
      const cells = tr.querySelectorAll('input,select');
      return { name: cells[0]?.value||'', type: cells[1]?.value||'independent',
               scale: cells[2]?.value||'nominal' };
    }).filter((v) => v.name);
  }

  /* ─── Step 4: Statistical Plan ─── */
  function initStep4() {
    const m = state.methodology;
    const s = state.stats;
    const n  = (id, fb) => s[id] !== undefined ? s[id] : (m[id] || fb || '');

    const sw = document.getElementById('s4-software');
    if (sw) { sw.value = n('software', 'SPSS'); sw.addEventListener('change', saveStats); }
    ['s4-sample-size','s4-alpha','s4-power','s4-missing'].forEach((id) => {
      const el = document.getElementById(id);
      const key = id.replace('s4-','').replace('-','_');
      if (el) { el.value = s[key]||''; el.addEventListener('input', saveStats); }
    });

    const testsList = document.getElementById('stat-tests-list');
    const addTestInp = document.getElementById('add-test-input');
    const addTestBtn = document.getElementById('add-test-btn');

    const tests = (m.statistical_tests || s.tests || []);
    tests.forEach((t) => addTestChip(testsList, t));
    addTestBtn?.addEventListener('click', () => {
      const v = addTestInp.value.trim();
      if (!v) return; addTestChip(testsList, v); addTestInp.value=''; saveStats();
    });
    addTestInp?.addEventListener('keydown', (e) => {
      if (e.key==='Enter') { e.preventDefault(); addTestBtn.click(); }
    });
  }

  function addTestChip(list, text) {
    const row = mk('div','stat-test-row');
    row.textContent = text;
    const rm = mk('button','remove-test'); rm.textContent = '✕';
    rm.addEventListener('click', () => { row.remove(); saveStats(); });
    row.appendChild(rm); list.appendChild(row);
  }

  function saveStats() {
    state.stats = {
      software:     val('s4-software'),
      sample_size:  val('s4-sample-size'),
      alpha:        val('s4-alpha'),
      power:        val('s4-power'),
      missing_data: val('s4-missing'),
      tests:        [...document.querySelectorAll('#stat-tests-list .stat-test-row')]
                      .map((r) => r.childNodes[0].textContent.trim()).filter(Boolean),
    };
    saveState();
  }

  /* ─── Step 5: Ethics ─── */
  function initStep5() {
    const e = state.ethics;
    const items = ['iec','consent','helsinki','icmr'];
    items.forEach((key) => {
      const el = document.getElementById('chk-'+key);
      if (!el) return;
      if (e[key]) el.classList.add('checked');
      el.addEventListener('click', () => {
        el.classList.toggle('checked');
        const box = el.querySelector('.check-box');
        if (box) box.textContent = el.classList.contains('checked') ? '✓' : '';
        state.ethics[key] = el.classList.contains('checked');
        saveState();
      });
      const box = el.querySelector('.check-box');
      if (box && e[key]) box.textContent = '✓';
    });

    document.querySelectorAll('.risk-opt').forEach((opt) => {
      const risk = opt.dataset.risk;
      if (e.risk === risk) opt.classList.add('selected-'+risk);
      opt.addEventListener('click', () => {
        document.querySelectorAll('.risk-opt').forEach((o) => {
          o.classList.remove('selected-minimal','selected-greater');
        });
        opt.classList.add('selected-'+risk);
        state.ethics.risk = risk; saveState();
      });
    });

    const waiverChk = document.getElementById('chk-waiver');
    const waiverBox = document.getElementById('waiver-justification-wrap');
    if (waiverChk) {
      if (e.waiver) { waiverChk.classList.add('checked'); waiverChk.querySelector('.check-box').textContent='✓'; if(waiverBox)waiverBox.style.display=''; }
      waiverChk.addEventListener('click', () => {
        waiverChk.classList.toggle('checked');
        const box=waiverChk.querySelector('.check-box'); if(box) box.textContent=waiverChk.classList.contains('checked')?'✓':'';
        state.ethics.waiver=waiverChk.classList.contains('checked');
        if(waiverBox) waiverBox.style.display=state.ethics.waiver?'':'none';
        saveState();
      });
    }
    const wj = document.getElementById('waiver-justification');
    if (wj) { wj.value=e.waiver_justification||''; wj.addEventListener('input',()=>{state.ethics.waiver_justification=wj.value;saveState();}); }
    if (waiverBox && !e.waiver) waiverBox.style.display='none';
  }

  /* ─── Step 6: Export ─── */
  async function loadExport() {
    const prev = document.getElementById('export-preview');
    if (prev) prev.textContent = 'Generating protocol summary…';
    btnNext.disabled = true;
    saveStats();
    try {
      const r = await fetch('/api/study-builder/design/export-text', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: state.question, pico: state.pico,
          design_id: state.selectedDesignId, design_name: state.selectedDesignName,
          methodology: state.methodology, stats_plan: state.stats,
          ethics: state.ethics, title: state.title,
        }),
      });
      const d = await r.json();
      state.export_text = d.text || '';
      if (state.title && d.title) state.title = d.title;
      saveState();
      if (prev) prev.textContent = state.export_text;
    } catch (e) {
      if (prev) prev.textContent = 'Error generating preview.';
    }
    btnNext.disabled = false;

    document.getElementById('btn-copy')?.addEventListener('click', () => {
      navigator.clipboard.writeText(state.export_text).then(() => {
        const b = document.getElementById('btn-copy'); b.textContent = 'Copied!';
        setTimeout(() => { b.textContent = 'Copy text'; }, 1800);
      });
    });

    document.getElementById('btn-send-prologue')?.addEventListener('click', () => {
      sessionStorage.setItem('medras.proposal.intake', JSON.stringify({
        topic: state.question, study_type: state.selectedDesignName,
        aim: state.question, primary_objective: state.methodology.primary_outcome||'',
        population: state.pico.P||'', setting: state.methodology.study_setting||'',
        study_period: state.methodology.study_period||'',
      }));
      window.location.href = '/proposal-module/role.html';
    });

    document.getElementById('btn-send-thesis')?.addEventListener('click', () => {
      sessionStorage.setItem('medras.thesis.from_study_builder', JSON.stringify({
        title: state.title || state.question,
        aim: state.question, primary_objective: state.methodology.primary_outcome||'',
        study_type: state.selectedDesignName,
        population: state.pico.P||'', setting: state.methodology.study_setting||'',
        study_period: state.methodology.study_period||'',
      }));
      window.location.href = '/thesis-module/setup.html';
    });

    document.getElementById('btn-download')?.addEventListener('click', () => {
      const blob = new Blob([state.export_text], { type: 'text/plain' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'study_design_protocol.txt';
      a.click();
      URL.revokeObjectURL(a.href);
    });

    document.getElementById('btn-new')?.addEventListener('click', () => {
      if (!confirm('Start a new study design? Current progress will be cleared.')) return;
      sessionStorage.removeItem(SK);
      state = { step:1, question:'', objective_type:'analytical',
        pico:{P:'',I:'',C:'',O:''}, selectedDesignId:'', selectedDesignName:'',
        recommendations:[], general_advice:'', all_designs:[],
        methodology:{}, stats:{}, ethics:{iec:false,consent:true,helsinki:false,icmr:false,risk:'minimal',waiver:false,waiver_justification:''},
        export_text:'', title:'',
      };
      designsLoaded = false; methLoaded = false;
      navigateTo(1);
    });
  }

  /* ─── Navigation ─── */
  async function navigateTo(n) {
    state.step = n; saveState();
    renderProgress(); showStep(n);
    if (n === 2) await loadDesigns();
    if (n === 3) await loadMethodology();
    if (n === 4) initStep4();
    if (n === 5) initStep5();
    if (n === 6) await loadExport();
  }

  btnBack?.addEventListener('click', () => {
    if (state.step > 1) navigateTo(state.step - 1);
  });

  btnNext?.addEventListener('click', async () => {
    if (state.step === 1 && !validateStep1()) return;
    if (state.step === 2 && !validateStep2()) return;
    if (state.step === 3) saveMeth();
    if (state.step === 4) saveStats();
    if (state.step === TOTAL_STEPS) { alert('Your study design is complete! Use the export options above.'); return; }
    btnNext.classList.add('loading'); btnNext.disabled = true;
    await navigateTo(state.step + 1);
    btnNext.classList.remove('loading'); btnNext.disabled = false;
  });

  psDots().forEach((el, i) => {
    el.addEventListener('click', () => {
      if (i + 1 < state.step) navigateTo(i + 1);
    });
  });

  /* ─── Helpers ─── */
  function val(id) { return (document.getElementById(id)||{}).value||''; }
  function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
  function cap(s) { return s ? s[0].toUpperCase()+s.slice(1) : ''; }
  function mk(tag,cls) { const e=document.createElement(tag); if(cls) e.className=cls; return e; }

  /* ─── Boot ─── */
  loadState();
  renderProgress();
  showStep(state.step);
  initStep1();
  if (state.step === 4) initStep4();
  if (state.step === 5) initStep5();
  if (state.step > 1) navigateTo(state.step);

})();
