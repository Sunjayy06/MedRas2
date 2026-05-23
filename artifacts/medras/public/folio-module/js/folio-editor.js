/* Folio — Editor: DOM rendering, interactions, drag-drop, export
   ============================================================== */
'use strict';

(function () {

  // ── Guards ─────────────────────────────────────────────────────────────────
  if (!FolioCore.load()) {
    window.location.href = 'index.html';
    return;
  }

  var doc = FolioCore.getDoc();

  // ── Elements ───────────────────────────────────────────────────────────────
  var outlineList     = document.getElementById('outline-list');
  var outlineDocTitle = document.getElementById('outline-doc-title');
  var docPage         = document.getElementById('doc-page');
  var docTitleInput   = document.getElementById('doc-title-input');
  var refList         = document.getElementById('ref-list');
  var refCount        = document.getElementById('ref-count');
  var feedbackOverlay = document.getElementById('feedback-overlay');
  var feedbackText    = document.getElementById('feedback-text');
  var feedbackParse   = document.getElementById('feedback-parse');
  var feedbackCancel  = document.getElementById('feedback-cancel');
  var opsPreview      = document.getElementById('ops-preview');
  var opsList         = document.getElementById('ops-list');
  var toastEl         = document.getElementById('toast');
  var styleTabs       = document.querySelectorAll('.fl-style-tab');
  var btnCopyRefs     = document.getElementById('btn-copy-refs');
  var btnExport       = document.getElementById('btn-export');
  var btnFeedback     = document.getElementById('btn-feedback');
  var btnAddSection   = document.getElementById('btn-add-section');
  var btnHome         = document.getElementById('btn-home');

  var currentStyle = 'vancouver';
  var _parsedOps   = [];
  var _dragSrcIdx  = null;

  // ── Toast ──────────────────────────────────────────────────────────────────
  function toast(msg, dur) {
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    setTimeout(function () { toastEl.classList.remove('show'); }, dur || 2500);
  }

  // ── Escape HTML ────────────────────────────────────────────────────────────
  function esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Highlight in-text citations / table / figure references ───────────────
  function _annotateText(text) {
    return esc(text)
      .replace(/\[(\d+)\]/g, '<span class="fl-cite">[$1]</span>')
      .replace(/\b(Table\s+\d+)\b/g, '<span class="fl-table-ref">$1</span>')
      .replace(/\b(Figure\s+\d+|Fig\.\s*\d+)\b/g, '<span class="fl-fig-ref">$1</span>');
  }

  // ── Render everything ─────────────────────────────────────────────────────
  function render() {
    doc = FolioCore.getDoc();
    docTitleInput.value       = doc.title || '';
    outlineDocTitle.textContent = doc.title || 'Untitled';
    _renderOutline();
    _renderPage();
    _renderRefs();
    /* Update session hint for nav continuity */
    sessionStorage.setItem('medras.nav.returnHint', JSON.stringify({
      module: 'folio', label: 'your document', url: '/folio-module/editor.html',
    }));
  }

  // ── Outline ───────────────────────────────────────────────────────────────
  function _renderOutline() {
    outlineList.innerHTML = '';
    doc.sections.forEach(function (sec, idx) {
      var item = document.createElement('div');
      item.className = 'fl-outline-item';
      item.setAttribute('data-level', sec.level || 1);
      item.setAttribute('data-idx', idx);
      item.setAttribute('draggable', 'true');
      item.innerHTML =
        '<span class="fl-drag-handle" aria-hidden="true">⠿</span>' +
        '<span class="fl-outline-label">' + esc(sec.title) + '</span>';

      item.addEventListener('click', function () { _scrollToSection(sec.id); });

      /* Drag-and-drop */
      item.addEventListener('dragstart', function (e) {
        _dragSrcIdx = idx;
        e.dataTransfer.effectAllowed = 'move';
        item.style.opacity = '.4';
      });
      item.addEventListener('dragend', function () {
        item.style.opacity = '';
        outlineList.querySelectorAll('.drag-over').forEach(function (el) {
          el.classList.remove('drag-over');
        });
      });
      item.addEventListener('dragover', function (e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        outlineList.querySelectorAll('.drag-over').forEach(function (el) { el.classList.remove('drag-over'); });
        item.classList.add('drag-over');
      });
      item.addEventListener('drop', function (e) {
        e.preventDefault();
        item.classList.remove('drag-over');
        var toIdx = parseInt(item.getAttribute('data-idx'), 10);
        if (_dragSrcIdx !== null && _dragSrcIdx !== toIdx) {
          FolioCore.moveSectionByIndex(_dragSrcIdx, toIdx);
          toast('Section moved and document renumbered.');
          render();
        }
        _dragSrcIdx = null;
      });

      outlineList.appendChild(item);
    });
  }

  function _scrollToSection(secId) {
    var el = document.getElementById('sec-' + secId);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    outlineList.querySelectorAll('.fl-outline-item').forEach(function (it) { it.classList.remove('is-active'); });
    var idx = doc.sections.findIndex(function (s) { return s.id === secId; });
    var items = outlineList.querySelectorAll('.fl-outline-item');
    if (items[idx]) items[idx].classList.add('is-active');
  }

  // ── Document page ─────────────────────────────────────────────────────────
  function _renderPage() {
    docPage.innerHTML = '';
    doc.sections.forEach(function (sec) {
      var block = document.createElement('div');
      block.className = 'fl-section-block';
      block.id = 'sec-' + sec.id;

      /* Section heading */
      var h = document.createElement('div');
      h.className = 'fl-section-heading';
      h.setAttribute('data-level', sec.level || 1);
      h.setAttribute('contenteditable', 'true');
      h.setAttribute('spellcheck', 'true');
      h.textContent = sec.title;
      h.addEventListener('blur', function () {
        FolioCore.updateSectionTitle(sec.id, h.textContent.trim());
        _renderOutline();
        outlineDocTitle.textContent = FolioCore.getDoc().title || 'Untitled';
      });
      block.appendChild(h);

      /* Paragraphs */
      if (sec.paragraphs.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'fl-empty-section';
        empty.textContent = '(no content)';
        block.appendChild(empty);
      }

      sec.paragraphs.forEach(function (para) {
        block.appendChild(_buildPara(sec, para));
      });

      /* Add-paragraph button */
      var addBtn = document.createElement('button');
      addBtn.style.cssText = 'display:block;margin:4px 0 8px;font-size:11px;color:var(--fl-hint);background:none;border:none;cursor:pointer;padding:0;';
      addBtn.textContent = '+ Add paragraph';
      addBtn.addEventListener('click', function () {
        var lastParaId = sec.paragraphs.length
          ? sec.paragraphs[sec.paragraphs.length - 1].id
          : null;
        var newP = FolioCore.addParagraph(sec.id, lastParaId);
        if (newP) {
          doc = FolioCore.getDoc();
          var pEl = _buildPara(sec, newP);
          block.insertBefore(pEl, addBtn);
          pEl.focus();
        }
      });
      block.appendChild(addBtn);

      docPage.appendChild(block);
    });
  }

  function _buildPara(sec, para) {
    var p = document.createElement('div');
    p.className = 'fl-para';
    p.id = 'para-' + para.id;
    p.setAttribute('contenteditable', 'true');
    p.setAttribute('spellcheck', 'true');
    p.setAttribute('data-placeholder', 'Start typing…');
    if (!para.text) p.setAttribute('data-empty', '');

    /* Render with annotation on load; switch to plain on focus */
    if (para.text) {
      p.innerHTML = _annotateText(para.text);
    }

    p.addEventListener('focus', function () {
      p.removeAttribute('data-empty');
      p.textContent = para.text || '';
    });
    p.addEventListener('blur', function () {
      var newText = p.textContent.trim();
      FolioCore.updateParagraph(sec.id, para.id, newText);
      para.text = newText;
      if (newText) {
        p.innerHTML = _annotateText(newText);
        p.removeAttribute('data-empty');
      } else {
        p.textContent = '';
        p.setAttribute('data-empty', '');
      }
    });
    p.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        /* Save current and create next */
        FolioCore.updateParagraph(sec.id, para.id, p.textContent.trim());
        para.text = p.textContent.trim();
        var newP = FolioCore.addParagraph(sec.id, para.id);
        if (newP) {
          doc = FolioCore.getDoc();
          var sec2 = doc.sections.find(function (s) { return s.id === sec.id; });
          var newEl = _buildPara(sec2, newP);
          p.parentNode.insertBefore(newEl, p.nextSibling);
          newEl.focus();
        }
      }
    });
    return p;
  }

  // ── References ────────────────────────────────────────────────────────────
  function _renderRefs() {
    doc = FolioCore.getDoc();
    var refs = doc.references || [];
    refCount.textContent = refs.length + ' ref' + (refs.length !== 1 ? 's' : '');
    refList.innerHTML = '';

    if (refs.length === 0) {
      var empty = document.createElement('div');
      empty.className = 'fl-ref-empty';
      empty.textContent = 'No references detected yet.';
      refList.appendChild(empty);
      return;
    }

    refs.forEach(function (ref, i) {
      var item = document.createElement('div');
      item.className = 'fl-ref-item';

      var numEl = document.createElement('span');
      numEl.className = 'fl-ref-num';
      numEl.textContent = (i + 1) + '.';

      var textEl = document.createElement('span');
      textEl.className = 'fl-ref-text';
      var raw = (ref.raw || ref.text || '').replace(/^\d+[.\)]\s*/, '').trim();
      textEl.textContent = raw;

      var delBtn = document.createElement('button');
      delBtn.className = 'fl-ref-del';
      delBtn.title     = 'Delete this reference and renumber';
      delBtn.textContent = '×';
      delBtn.addEventListener('click', function () {
        FolioCore.deleteRef(ref.id);
        toast('Reference deleted and document renumbered.');
        render();
      });

      item.appendChild(numEl);
      item.appendChild(textEl);
      item.appendChild(delBtn);
      refList.appendChild(item);
    });
  }

  // ── Citation style ────────────────────────────────────────────────────────
  styleTabs.forEach(function (tab) {
    tab.addEventListener('click', function () {
      var style = tab.getAttribute('data-style');
      if (style === currentStyle) return;
      currentStyle = style;
      styleTabs.forEach(function (t) { t.classList.remove('is-active'); });
      tab.classList.add('is-active');

      /* Call backend to reformat */
      fetch('/api/folio/format-references', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ style: style, references: doc.references }),
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.ok && data.formatted) {
            data.formatted.forEach(function (f) {
              var ref = doc.references.find(function (r) { return r.id === f.id; });
              if (ref) ref.text = f.text;
            });
            FolioCore.save();
            _renderRefs();
            toast('Style changed to ' + style.toUpperCase() + '.');
          }
        })
        .catch(function () { toast('Style switch failed — check connection.'); });
    });
  });

  // ── Copy all references ───────────────────────────────────────────────────
  btnCopyRefs.addEventListener('click', function () {
    var text = FolioCore.allRefText(currentStyle);
    if (!text) { toast('No references to copy.'); return; }
    navigator.clipboard.writeText(text)
      .then(function () { toast('References copied ✓'); })
      .catch(function () { toast('Could not access clipboard.'); });
  });

  // ── Add section ───────────────────────────────────────────────────────────
  btnAddSection.addEventListener('click', function () {
    FolioCore.addSection(doc.sections.length - 1);
    toast('Section added.');
    render();
  });

  // ── Title input ───────────────────────────────────────────────────────────
  docTitleInput.addEventListener('input', function () {
    doc.title = docTitleInput.value;
    outlineDocTitle.textContent = doc.title || 'Untitled';
    FolioCore.save();
    sessionStorage.setItem('medras.nav.returnHint', JSON.stringify({
      module: 'folio', label: doc.title || 'your document', url: '/folio-module/editor.html',
    }));
  });

  // ── Home ──────────────────────────────────────────────────────────────────
  btnHome.addEventListener('click', function () {
    window.location.href = 'index.html';
  });

  // ── Guide feedback modal ──────────────────────────────────────────────────
  btnFeedback.addEventListener('click', function () {
    _parsedOps = [];
    feedbackText.value = '';
    opsPreview.style.display = 'none';
    opsList.innerHTML = '';
    feedbackParse.textContent = 'Parse feedback';
    feedbackOverlay.classList.remove('hidden');
    feedbackText.focus();
  });

  feedbackCancel.addEventListener('click', function () {
    feedbackOverlay.classList.add('hidden');
    _parsedOps = [];
  });

  feedbackOverlay.addEventListener('click', function (e) {
    if (e.target === feedbackOverlay) {
      feedbackOverlay.classList.add('hidden');
      _parsedOps = [];
    }
  });

  var OP_ICONS = {
    delete_refs:    '🗑',
    move_section:   '↕',
    edit_text:      '✏',
    change_chart:   '📊',
    add_section:    '＋',
    delete_section: '🗑',
  };

  feedbackParse.addEventListener('click', function () {
    /* If ops already parsed, apply them */
    if (_parsedOps.length > 0) {
      FolioCore.applyOperations(_parsedOps);
      feedbackOverlay.classList.add('hidden');
      _parsedOps = [];
      render();
      toast('Changes applied. Previous version saved for undo.');
      return;
    }

    var fb = feedbackText.value.trim();
    if (!fb) { toast('Please enter some feedback text.'); return; }

    feedbackParse.textContent = 'Parsing…';
    feedbackParse.disabled = true;

    fetch('/api/folio/parse-feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ feedback: fb, document: doc }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        feedbackParse.disabled = false;
        if (!data.ok || !data.operations) {
          toast('Could not parse feedback.');
          feedbackParse.textContent = 'Parse feedback';
          return;
        }
        _parsedOps = data.operations || [];
        opsList.innerHTML = '';
        if (_parsedOps.length === 0) {
          opsPreview.style.display = 'block';
          opsList.innerHTML = '<div style="font-size:13px;color:var(--fl-muted);padding:8px 0;">No actionable changes found in this feedback.</div>';
          feedbackParse.textContent = 'Parse feedback';
          return;
        }
        _parsedOps.forEach(function (op) {
          var item = document.createElement('div');
          item.className = 'fl-op-item';
          var icon = OP_ICONS[op.type] || '•';
          item.innerHTML = '<span class="fl-op-icon">' + icon + '</span><span>' + esc(op.description || op.type) + '</span>';
          opsList.appendChild(item);
        });
        opsPreview.style.display = 'block';
        feedbackParse.textContent = 'Apply ' + _parsedOps.length + ' change' + (_parsedOps.length !== 1 ? 's' : '') + ' ✓';
      })
      .catch(function () {
        feedbackParse.disabled = false;
        feedbackParse.textContent = 'Parse feedback';
        toast('AI service error. Check your connection.');
      });
  });

  // ── Undo (restore snapshot) ───────────────────────────────────────────────
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
      if (FolioCore.restoreSnapshot()) {
        render();
        toast('Restored previous version.');
      }
    }
  });

  // ── Novus handoff ─────────────────────────────────────────────────────────
  var btnNovus = document.getElementById('btn-novus');
  if (btnNovus) {
    btnNovus.addEventListener('click', function () {
      // Collect all paragraph text from every section in order
      var parts = [];
      (doc.sections || []).forEach(function (sec) {
        if (sec.title) parts.push(sec.title.toUpperCase());
        (sec.paragraphs || []).forEach(function (p) {
          var t = (p.text || '').trim();
          if (t) parts.push(t);
        });
      });
      var fullText = parts.join('\n\n').trim();
      if (!fullText) {
        toast('No content to send — write something first.');
        return;
      }
      try {
        sessionStorage.setItem('medras.plagiarism.prefill', fullText);
        toast('Opening Novus…');
        window.open('/plagiarism-module/checker.html', '_blank');
      } catch (e) {
        toast('Could not stage text: ' + e.message);
      }
    });
  }

  // ── DOCX export ───────────────────────────────────────────────────────────
  btnExport.addEventListener('click', function () {
    btnExport.textContent = 'Exporting…';
    btnExport.disabled = true;

    fetch('/api/folio/export-docx', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ document: doc, style: currentStyle }),
    })
      .then(function (res) {
        if (!res.ok) return res.json().then(function (d) { throw new Error(d.detail || 'Export failed'); });
        return res.blob();
      })
      .then(function (blob) {
        var url  = URL.createObjectURL(blob);
        var a    = document.createElement('a');
        var name = (doc.title || 'document').replace(/[^\w\s-]/g, '').slice(0, 40).trim().replace(/\s+/g, '_');
        a.href     = url;
        a.download = name + '_folio.docx';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        toast('Document exported ✓');
      })
      .catch(function (err) { toast('Export failed: ' + err.message); })
      .finally(function () {
        btnExport.textContent = '↓ Export DOCX';
        btnExport.disabled = false;
      });
  });

  // ── Intersection observer to highlight active outline item ────────────────
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        var secId = entry.target.id.replace('sec-', '');
        var idx   = doc.sections.findIndex(function (s) { return s.id === secId; });
        outlineList.querySelectorAll('.fl-outline-item').forEach(function (it) { it.classList.remove('is-active'); });
        var items = outlineList.querySelectorAll('.fl-outline-item');
        if (items[idx]) items[idx].classList.add('is-active');
      }
    });
  }, { threshold: 0.2 });

  function _observeSections() {
    document.querySelectorAll('.fl-section-block').forEach(function (el) {
      observer.observe(el);
    });
  }

  // ── Initial render ────────────────────────────────────────────────────────
  render();
  _observeSections();
})();
