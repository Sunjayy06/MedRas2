/* Thesis state store — sessionStorage as the source of truth for the
   active thesis, IndexedDB for the persistent library across theses.

   Schema (sessionStorage `medras.thesis.active`):
     {
       id, created_at, updated_at,
       setup: {title, researcher, guide, co_guide, institution, year,
               domain, format, citation_style, submission_date},
       rules: {...DEFAULT_RULES merged with university overrides...},
       guideline_evidence: [...],
       references: [{doi, title, authors, year, journal, abstract,
                     summary, source, verified, score, suggested_chapters}],
       chapters: { <chapter_id>: { text, notes, last_edited,
                                   accepted_suggestions: [], topic } },
       locked_numbers: { "<label>": "<value>" },
       plagiarism: { pct, ai_pct },
       assets: { pictures: [...], certificates: [...] },
       stats_import: { raw_text, parsed_tables, organize_choice }
     }

   Public API: window.ThesisState
*/
(function () {
  'use strict';

  const KEY = 'medras.thesis.active';
  const LIB_DB = 'medras-thesis-lib';
  const LIB_STORE = 'references';
  const LIB_VERSION = 1;

  // ---------- session-store ----------
  function _read() {
    try { return JSON.parse(sessionStorage.getItem(KEY) || 'null'); }
    catch (_) { return null; }
  }
  function _write(state) {
    state.updated_at = new Date().toISOString();
    var payload;
    try {
      payload = JSON.stringify(state);
    } catch (e) {
      // Circular ref or unserialisable value — surface, do nothing.
      console && console.warn && console.warn('ThesisState: serialise failed', e);
      return;
    }
    try {
      sessionStorage.setItem(KEY, payload);
    } catch (e) {
      // Browser sessionStorage hard cap (~5 MB per origin) — most
      // commonly hit when a researcher attaches large figures. Surface
      // a clear toast so they know to compress / drop assets, then
      // best-effort store everything except `assets` so chapter text /
      // references / locks still survive the page reload.
      if (e && (e.name === 'QuotaExceededError' || e.code === 22)) {
        try {
          var lite = Object.assign({}, state, {
            assets: { pictures: [], certificates: [], annexures: [],
                      __overflow: true }
          });
          sessionStorage.setItem(KEY, JSON.stringify(lite));
        } catch (_) { /* even the lite write failed — give up silently */ }
        if (window.ThesisState && typeof window.ThesisState.toast === 'function') {
          window.ThesisState.toast(
            'Browser storage is full — compress or remove some figures, ' +
            'then re-attach them. Your chapter text was kept safe.', 5000);
        }
        return;
      }
      console && console.warn && console.warn('ThesisState: storage write failed', e);
      return;
    }
    // Mirror to localStorage so a tab refresh doesn't lose work.
    try { localStorage.setItem(KEY, payload); } catch (_) {}
  }
  function _newId() { return 'th_' + Math.random().toString(36).slice(2, 12); }

  function get() {
    let s = _read();
    if (!s) {
      // try localStorage mirror
      try {
        const mirror = localStorage.getItem(KEY);
        if (mirror) { s = JSON.parse(mirror); sessionStorage.setItem(KEY, mirror); }
      } catch (_) {}
    }
    if (!s) {
      s = {
        id: _newId(),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        setup: {}, rules: {}, guideline_evidence: [],
        references: [], chapters: {}, locked_numbers: {},
        plagiarism: {}, assets: { pictures: [], certificates: [] },
        stats_import: {},
      };
      _write(s);
    }
    return s;
  }
  function patch(updater) {
    const s = get();
    const next = (typeof updater === 'function') ? updater(s) : Object.assign(s, updater);
    _write(next || s);
    return next || s;
  }
  function reset() {
    sessionStorage.removeItem(KEY);
    try { localStorage.removeItem(KEY); } catch (_) {}
  }

  // ---------- persistent reference library (IndexedDB) ----------
  function _openDB() {
    return new Promise((resolve, reject) => {
      if (!window.indexedDB) { reject(new Error('IndexedDB unavailable')); return; }
      const req = indexedDB.open(LIB_DB, LIB_VERSION);
      req.onupgradeneeded = (e) => {
        const db = e.target.result;
        if (!db.objectStoreNames.contains(LIB_STORE)) {
          const store = db.createObjectStore(LIB_STORE, { keyPath: 'doi' });
          store.createIndex('year', 'year');
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror   = () => reject(req.error);
    });
  }
  async function libSave(record) {
    if (!record || !record.doi) return;
    try {
      const db = await _openDB();
      await new Promise((res, rej) => {
        const tx = db.transaction(LIB_STORE, 'readwrite');
        tx.objectStore(LIB_STORE).put({ ...record, _saved_at: Date.now() });
        tx.oncomplete = res; tx.onerror = () => rej(tx.error);
      });
    } catch (_) { /* IndexedDB is a nice-to-have */ }
  }
  async function libSaveMany(records) {
    if (!records || !records.length) return;
    try {
      const db = await _openDB();
      await new Promise((res, rej) => {
        const tx = db.transaction(LIB_STORE, 'readwrite');
        const store = tx.objectStore(LIB_STORE);
        records.forEach((r) => { if (r && r.doi) store.put({ ...r, _saved_at: Date.now() }); });
        tx.oncomplete = res; tx.onerror = () => rej(tx.error);
      });
    } catch (_) {}
  }
  async function libAll() {
    try {
      const db = await _openDB();
      return await new Promise((res, rej) => {
        const out = []; const tx = db.transaction(LIB_STORE, 'readonly');
        tx.objectStore(LIB_STORE).openCursor().onsuccess = (e) => {
          const c = e.target.result;
          if (c) { out.push(c.value); c.continue(); } else res(out);
        };
        tx.onerror = () => rej(tx.error);
      });
    } catch (_) { return []; }
  }
  async function libRemove(doi) {
    try {
      const db = await _openDB();
      await new Promise((res, rej) => {
        const tx = db.transaction(LIB_STORE, 'readwrite');
        tx.objectStore(LIB_STORE).delete(doi);
        tx.oncomplete = res; tx.onerror = () => rej(tx.error);
      });
    } catch (_) {}
  }

  // ---------- helpers ----------
  function setChapter(id, fields) {
    return patch((s) => {
      s.chapters[id] = Object.assign(s.chapters[id] || {}, fields,
        { last_edited: new Date().toISOString() });
      return s;
    });
  }
  function getChapter(id) {
    const s = get();
    return s.chapters[id] || { text: '', notes: '', accepted_suggestions: [] };
  }
  function setLock(label, value) {
    if (!label || !value) return;
    return patch((s) => {
      s.locked_numbers[label] = String(value);
      return s;
    });
  }
  function unsetLock(label) {
    return patch((s) => { delete s.locked_numbers[label]; return s; });
  }
  function _stableId(r) {
    // Deterministic stable ID so no-DOI entries can be deduped and removed correctly
    if (r._id) return r._id;
    const seed = ((r.doi || '') + '|' + (r.title || '') + '|' + (r.year || '')).toLowerCase().replace(/\s+/g, '');
    let h = 0;
    for (let i = 0; i < seed.length; i++) { h = Math.imul(31, h) + seed.charCodeAt(i) | 0; }
    return (h >>> 0).toString(36);
  }
  function addReferences(records) {
    return patch((s) => {
      const seen = new Set((s.references || []).map((r) => r._id || _stableId(r)));
      (records || []).forEach((r) => {
        if (!r._id) r._id = _stableId(r);
        if (!seen.has(r._id)) { s.references.push(r); seen.add(r._id); }
      });
      return s;
    });
  }

  // ---------- toast ----------
  function toast(msg, ms) {
    let el = document.getElementById('th-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'th-toast';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.remove('show'), ms || 2400);
  }

  // ---------- minimal API client ----------
  async function api(path, body) {
    const opts = { method: body ? 'POST' : 'GET',
                   headers: { 'Content-Type': 'application/json' } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch('/api/thesis' + path, opts);
    const text = await r.text();
    let data; try { data = text ? JSON.parse(text) : {}; } catch (_) { data = { detail: text }; }
    if (!r.ok) {
      const msg = (data && (data.detail || data.error)) || r.statusText || 'Request failed';
      throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    }
    return data;
  }
  async function apiUpload(path, formData) {
    const r = await fetch('/api/thesis' + path, { method: 'POST', body: formData });
    const text = await r.text();
    let data; try { data = text ? JSON.parse(text) : {}; } catch (_) { data = { detail: text }; }
    if (!r.ok) throw new Error((data && (data.detail || data.error)) || r.statusText);
    return data;
  }

  window.ThesisState = {
    get, patch, reset, setChapter, getChapter, setLock, unsetLock,
    addReferences,
    libSave, libSaveMany, libAll, libRemove,
    toast, api, apiUpload,
  };
})();
