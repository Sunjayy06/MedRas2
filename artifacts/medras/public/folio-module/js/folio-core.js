/* Folio — Core: state management, reference tracking, numbering
   ============================================================= */
'use strict';

var FolioCore = (function () {

  var STORAGE_KEY    = 'folio.doc';
  var SNAPSHOT_KEY   = 'folio.doc.snapshot';
  var CITE_IN_TEXT   = /\[(\d+)\]/g;
  var TABLE_IN_TEXT  = /\bTable\s+(\d+)\b/g;
  var FIG_IN_TEXT    = /\b(?:Figure|Fig\.?)\s+(\d+)\b/g;

  // ── State ──────────────────────────────────────────────────────────────────

  var _doc = null;   /* live document model */

  function load() {
    var raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return false;
    try {
      _doc = JSON.parse(raw);
      return true;
    } catch (e) {
      return false;
    }
  }

  function save() {
    if (_doc) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(_doc));
  }

  function snapshot() {
    if (_doc) localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(_doc));
  }

  function restoreSnapshot() {
    var raw = localStorage.getItem(SNAPSHOT_KEY);
    if (!raw) return false;
    try {
      _doc = JSON.parse(raw);
      save();
      return true;
    } catch (e) { return false; }
  }

  function getDoc()   { return _doc; }
  function setDoc(d)  { _doc = d; save(); }

  // ── UID ───────────────────────────────────────────────────────────────────

  function uid() {
    return Math.random().toString(36).slice(2, 10);
  }

  // ── Reference tracking ────────────────────────────────────────────────────

  /* After any deletion or reorder, reassign sequential numbers and update
     every [N] marker in all paragraph text.                                 */
  function renumberRefs() {
    var refs = _doc.references;
    /* Build old-number → new-number map */
    var map = {};
    refs.forEach(function (r, i) { map[r.number] = i + 1; });
    /* Reassign numbers */
    refs.forEach(function (r, i) { r.number = i + 1; });
    /* Update in-text [N] across all paragraphs */
    _eachPara(function (p) {
      p.text = p.text.replace(CITE_IN_TEXT, function (_, n) {
        var newN = map[parseInt(n, 10)];
        return newN != null ? '[' + newN + ']' : '[?]';
      });
    });
    save();
  }

  function deleteRef(id) {
    snapshot();
    _doc.references = _doc.references.filter(function (r) { return r.id !== id; });
    renumberRefs();
  }

  function reorderRefs(fromIdx, toIdx) {
    snapshot();
    var refs  = _doc.references;
    var moved = refs.splice(fromIdx, 1)[0];
    refs.splice(toIdx, 0, moved);
    renumberRefs();
  }

  // ── Table tracking ────────────────────────────────────────────────────────

  function renumberTables() {
    var tbls = _doc.tables;
    var map  = {};
    tbls.forEach(function (t, i) { map[t.number] = i + 1; });
    tbls.forEach(function (t, i) { t.number = i + 1; });
    _eachPara(function (p) {
      p.text = p.text.replace(TABLE_IN_TEXT, function (_, n) {
        var newN = map[parseInt(n, 10)];
        return newN != null ? 'Table ' + newN : 'Table ?';
      });
    });
    save();
  }

  function deleteTable(id) {
    snapshot();
    _doc.tables = _doc.tables.filter(function (t) { return t.id !== id; });
    renumberTables();
  }

  // ── Figure tracking ───────────────────────────────────────────────────────

  function renumberFigures() {
    var figs = _doc.figures;
    var map  = {};
    figs.forEach(function (f, i) { map[f.number] = i + 1; });
    figs.forEach(function (f, i) { f.number = i + 1; });
    _eachPara(function (p) {
      p.text = p.text.replace(FIG_IN_TEXT, function (match, n) {
        var newN   = map[parseInt(n, 10)];
        var prefix = match.startsWith('Fig') ? 'Fig. ' : 'Figure ';
        return newN != null ? prefix + newN : prefix + '?';
      });
    });
    save();
  }

  function deleteFigure(id) {
    snapshot();
    _doc.figures = _doc.figures.filter(function (f) { return f.id !== id; });
    renumberFigures();
  }

  // ── Section operations ────────────────────────────────────────────────────

  function moveSectionByIndex(fromIdx, toIdx) {
    snapshot();
    var secs  = _doc.sections;
    var moved = secs.splice(fromIdx, 1)[0];
    secs.splice(toIdx, 0, moved);
    /* After reorder, renumber refs in new order */
    renumberRefs();
    renumberTables();
    renumberFigures();
    save();
  }

  function addSection(afterIdx) {
    var sec = { id: uid(), level: 1, title: 'New Section', paragraphs: [{ id: uid(), text: '' }] };
    _doc.sections.splice(afterIdx + 1, 0, sec);
    save();
    return sec;
  }

  function deleteSection(id) {
    snapshot();
    _doc.sections = _doc.sections.filter(function (s) { return s.id !== id; });
    save();
  }

  function updateParagraph(secId, paraId, text) {
    var sec = _doc.sections.find(function (s) { return s.id === secId; });
    if (!sec) return;
    var para = sec.paragraphs.find(function (p) { return p.id === paraId; });
    if (para) { para.text = text; save(); }
  }

  function updateSectionTitle(secId, title) {
    var sec = _doc.sections.find(function (s) { return s.id === secId; });
    if (sec) { sec.title = title; save(); }
  }

  function addParagraph(secId, afterParaId) {
    var sec = _doc.sections.find(function (s) { return s.id === secId; });
    if (!sec) return null;
    var newPara = { id: uid(), text: '' };
    var idx = sec.paragraphs.findIndex(function (p) { return p.id === afterParaId; });
    if (idx < 0) sec.paragraphs.push(newPara);
    else sec.paragraphs.splice(idx + 1, 0, newPara);
    save();
    return newPara;
  }

  // ── Apply feedback operations ─────────────────────────────────────────────

  function applyOperations(ops) {
    snapshot();
    ops.forEach(function (op) {
      switch (op.type) {
        case 'delete_refs': {
          var from = (op.params && op.params.from) || 1;
          var to   = (op.params && op.params.to)   || from;
          _doc.references = _doc.references.filter(function (r) {
            return r.number < from || r.number > to;
          });
          renumberRefs();
          break;
        }
        case 'move_section': {
          var sTitle = (op.params && op.params.section)  || '';
          var tTitle = (op.params && op.params.target)   || '';
          var pos    = (op.params && op.params.position) || 'before';
          var sIdx   = _doc.sections.findIndex(function (s) { return s.title.toLowerCase().includes(sTitle.toLowerCase()); });
          var tIdx   = _doc.sections.findIndex(function (s) { return s.title.toLowerCase().includes(tTitle.toLowerCase()); });
          if (sIdx >= 0 && tIdx >= 0 && sIdx !== tIdx) {
            moveSectionByIndex(sIdx, pos === 'after' ? tIdx : Math.max(0, tIdx));
          }
          break;
        }
        case 'delete_section': {
          var dt = (op.params && op.params.title) || '';
          var ds = _doc.sections.find(function (s) { return s.title.toLowerCase().includes(dt.toLowerCase()); });
          if (ds) deleteSection(ds.id);
          break;
        }
        case 'add_section': {
          var at = (op.params && op.params.after) || '';
          var ai = _doc.sections.findIndex(function (s) { return s.title.toLowerCase().includes(at.toLowerCase()); });
          addSection(ai >= 0 ? ai : _doc.sections.length - 1);
          var newS = _doc.sections[ai >= 0 ? ai + 1 : _doc.sections.length - 1];
          if (newS && op.params && op.params.title) newS.title = op.params.title;
          break;
        }
        default: break;
      }
    });
    save();
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  function _eachPara(fn) {
    (_doc.sections || []).forEach(function (sec) {
      (sec.paragraphs || []).forEach(fn);
    });
  }

  function allRefText(style) {
    return (_doc.references || []).map(function (r, i) {
      var n = i + 1;
      var raw = r.raw || r.text || '';
      raw = raw.replace(/^\d+[.\)]\s*/, '').trim();
      if (style === 'apa' || style === 'harvard') return raw;
      return n + '. ' + raw;
    }).join('\n');
  }

  // ── Public API ────────────────────────────────────────────────────────────
  return {
    load: load, save: save, snapshot: snapshot, restoreSnapshot: restoreSnapshot,
    getDoc: getDoc, setDoc: setDoc, uid: uid,
    deleteRef: deleteRef, reorderRefs: reorderRefs, renumberRefs: renumberRefs,
    deleteTable: deleteTable, deleteFigure: deleteFigure,
    moveSectionByIndex: moveSectionByIndex, addSection: addSection,
    deleteSection: deleteSection, updateParagraph: updateParagraph,
    updateSectionTitle: updateSectionTitle, addParagraph: addParagraph,
    applyOperations: applyOperations, allRefText: allRefText,
  };
})();
