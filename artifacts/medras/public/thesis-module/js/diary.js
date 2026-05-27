/* ================================================================
   MedRAS Research Diary — IndexedDB store, pure data layer
   DB: medras-research-diary  v1
   Store: entries  (keyPath: id, index: thesis_id + created_at)
   ================================================================ */
(function () {
  'use strict';

  var DB_NAME    = 'medras-research-diary';
  var STORE      = 'entries';
  var DB_VERSION = 1;

  var TAGS = [
    { id: 'general',          label: 'General',          color: '#56645d', bg: '#eef1ef', emoji: '📝' },
    { id: 'writing',          label: 'Writing',          color: '#059669', bg: '#ecfdf5', emoji: '✍️' },
    { id: 'literature',       label: 'Literature',       color: '#7c3aed', bg: '#f5f3ff', emoji: '📚' },
    { id: 'data-collection',  label: 'Data collection',  color: '#2563eb', bg: '#eff6ff', emoji: '🔬' },
    { id: 'analysis',         label: 'Analysis',         color: '#0891b2', bg: '#ecfeff', emoji: '📊' },
    { id: 'meeting',          label: 'Meeting',          color: '#d97706', bg: '#fffbeb', emoji: '🤝' },
    { id: 'milestone',        label: 'Milestone',        color: '#b45309', bg: '#fef9c3', emoji: '🏆' },
    { id: 'issue',            label: 'Issue / blocker',  color: '#dc2626', bg: '#fef2f2', emoji: '⚠️' },
  ];

  /* ---- IndexedDB helpers ---- */
  function _open() {
    return new Promise(function (resolve, reject) {
      if (!window.indexedDB) { reject(new Error('IndexedDB unavailable')); return; }
      var req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function (e) {
        var db = e.target.result;
        if (!db.objectStoreNames.contains(STORE)) {
          var store = db.createObjectStore(STORE, { keyPath: 'id' });
          store.createIndex('by_thesis', 'thesis_id', { unique: false });
          store.createIndex('by_date',   'created_at', { unique: false });
        }
      };
      req.onsuccess = function (e) { resolve(e.target.result); };
      req.onerror   = function (e) { reject(e.target.error); };
    });
  }

  function _tx(db, mode) {
    return db.transaction([STORE], mode).objectStore(STORE);
  }

  function _promisify(req) {
    return new Promise(function (resolve, reject) {
      req.onsuccess = function (e) { resolve(e.target.result); };
      req.onerror   = function (e) { reject(e.target.error); };
    });
  }

  /* ---- public API ---- */

  function newId() {
    return 'dr_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  }

  async function add(thesisId, tag, text) {
    var entry = {
      id:         newId(),
      thesis_id:  thesisId,
      created_at: new Date().toISOString(),
      tag:        tag || 'general',
      text:       String(text).trim(),
      word_count: (String(text).match(/\b\w+\b/g) || []).length,
      edited:     false,
    };
    var db = await _open();
    await _promisify(_tx(db, 'readwrite').add(entry));
    db.close();
    return entry;
  }

  async function update(id, thesisId, tag, text) {
    var db = await _open();
    var store = _tx(db, 'readwrite');
    var existing = await _promisify(store.get(id));
    if (!existing || existing.thesis_id !== thesisId) { db.close(); return null; }
    existing.tag        = tag || existing.tag;
    existing.text       = String(text).trim();
    existing.word_count = (String(text).match(/\b\w+\b/g) || []).length;
    existing.edited     = true;
    existing.edited_at  = new Date().toISOString();
    var db2 = await _open();
    await _promisify(_tx(db2, 'readwrite').put(existing));
    db2.close();
    return existing;
  }

  async function remove(id) {
    var db = await _open();
    await _promisify(_tx(db, 'readwrite').delete(id));
    db.close();
  }

  async function listForThesis(thesisId) {
    var db = await _open();
    var index = _tx(db, 'readonly').index('by_thesis');
    var all   = await _promisify(index.getAll(IDBKeyRange.only(thesisId)));
    db.close();
    return all.sort(function (a, b) { return b.created_at.localeCompare(a.created_at); });
  }

  async function exportMarkdown(thesisId, thesisTitle) {
    var entries = await listForThesis(thesisId);
    if (!entries.length) return '# Research Diary\n\n_No entries yet._';
    var lines = ['# Research Diary — ' + (thesisTitle || 'Untitled'), ''];
    var grouped = {};
    entries.forEach(function (e) {
      var day = e.created_at.slice(0, 10);
      if (!grouped[day]) grouped[day] = [];
      grouped[day].push(e);
    });
    Object.keys(grouped).sort(function (a, b) { return b.localeCompare(a); }).forEach(function (day) {
      lines.push('## ' + _fmtDay(day));
      grouped[day].forEach(function (e) {
        var tagObj = TAGS.find(function (t) { return t.id === e.tag; }) || TAGS[0];
        var time   = e.created_at.slice(11, 16);
        lines.push('');
        lines.push('**[' + time + '] ' + tagObj.emoji + ' ' + tagObj.label + '**');
        lines.push('');
        lines.push(e.text);
      });
      lines.push('');
    });
    return lines.join('\n');
  }

  function _fmtDay(iso) {
    var d = new Date(iso + 'T12:00:00Z');
    return d.toLocaleDateString('en-IN', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
  }

  function stats(entries) {
    var now    = new Date();
    var weekAgo = new Date(now - 7 * 86400000);
    var daySet  = new Set();
    var wordTotal = 0;
    entries.forEach(function (e) {
      wordTotal += (e.word_count || 0);
      daySet.add(e.created_at.slice(0, 10));
    });
    var thisWeek = entries.filter(function (e) {
      return new Date(e.created_at) >= weekAgo;
    }).length;
    var streak  = _streak(daySet);
    return { total: entries.length, words: wordTotal, thisWeek: thisWeek, streak: streak, days: daySet.size };
  }

  function _streak(daySet) {
    if (!daySet.size) return 0;
    var today  = new Date().toISOString().slice(0, 10);
    var streak = 0;
    var cur    = new Date();
    while (true) {
      var d = cur.toISOString().slice(0, 10);
      if (!daySet.has(d)) {
        if (streak === 0 && d === today) { cur.setDate(cur.getDate() - 1); continue; }
        break;
      }
      streak++;
      cur.setDate(cur.getDate() - 1);
    }
    return streak;
  }

  window.ResearchDiary = { add: add, update: update, remove: remove, listForThesis: listForThesis, exportMarkdown: exportMarkdown, TAGS: TAGS, stats: stats };
})();
