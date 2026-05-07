/* Track-changes inline-diff renderer.

   Given the editor text and a list of suggestions of shape:
     [{ original: "<verbatim substring>", suggested: "...",
        reason: "...", kind: "fact" | "clarity" | ... }]
   we render the suggestions as inline overlays in a paired preview pane
   and let the user accept/reject each. On accept, the underlying
   editor text is mutated AT THE EXACT OFFSET we matched at render time
   (not via indexOf/replace) so that repeated substrings cannot be
   mutated at the wrong location.

   Yellow-locked numbers are auto-wrapped wherever they appear in text.

   Public: window.TrackChanges
     - render(previewEl, text, suggestions, onChange, lockedNumbers)
         onChange(newText, remainingSuggestions, info)
     - acceptAt(text, start, end, suggested) -> text'
     - findUniqueOffsets(text, original) -> {start,end} | null
     - escapeHtml(s)
*/
(function () {
  'use strict';

  function escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }

  function escapeRegex(s) {
    return String(s).replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&');
  }

  function wrapLockedNumbers(html, lockedNumbers) {
    if (!lockedNumbers) return html;
    const values = Object.values(lockedNumbers).filter(Boolean);
    let out = html;
    values.forEach((v) => {
      const safe = escapeRegex(String(v));
      const re = new RegExp('(^|[\\s>(\\[])(' + safe + ')(?=$|[\\s.,;:)\\]<])', 'g');
      out = out.replace(re, function (_m, lead, val) {
        return lead + '<span class="th-locked" title="Locked from your data">' + escapeHtml(val) + '</span>';
      });
    });
    return out;
  }

  // Slice-based replacement — never uses indexOf/replace at apply time.
  function acceptAt(text, start, end, suggested) {
    text = String(text || '');
    if (start == null || end == null || start < 0 || end > text.length || start > end) return text;
    return text.slice(0, start) + String(suggested || '') + text.slice(end);
  }

  // Returns {start, end} only when `original` appears EXACTLY once; null
  // otherwise. Callers that don't have positional offsets (e.g. the
  // right-hand suggestions panel before any render) use this to refuse
  // applying ambiguous edits.
  function findUniqueOffsets(text, original) {
    text = String(text || '');
    const orig = String(original || '');
    if (!orig) return null;
    const first = text.indexOf(orig);
    if (first < 0) return null;
    if (text.indexOf(orig, first + 1) >= 0) return null;
    return { start: first, end: first + orig.length };
  }

  function render(previewEl, text, suggestions, onChange, lockedNumbers) {
    if (!previewEl) return;
    text = String(text || '');
    suggestions = Array.isArray(suggestions) ? suggestions.slice() : [];

    // Compute non-overlapping placements. For each suggestion we record
    // the *first occurrence* offset; if multiple occurrences exist and
    // the suggestion lacks an explicit anchor, we still render it but
    // accept will use the SAME stored offset so the right occurrence
    // gets mutated.
    const placements = [];
    const taken = []; // [start, end)
    suggestions.forEach((s, idx) => {
      const orig = s.original || '';
      if (!orig) return;
      const start = text.indexOf(orig);
      if (start < 0) return;
      const end = start + orig.length;
      const overlap = taken.some(([a, b]) => !(end <= a || start >= b));
      if (overlap) return;
      taken.push([start, end]);
      placements.push({ start, end, sug: s, idx });
    });
    placements.sort((a, b) => a.start - b.start);

    // Build HTML
    let cursor = 0;
    const parts = [];
    placements.forEach((p) => {
      if (p.start > cursor) {
        parts.push(wrapLockedNumbers(escapeHtml(text.slice(cursor, p.start)), lockedNumbers));
      }
      const kind = (p.sug.kind || 'clarity');
      parts.push('<span class="th-diff-block" data-idx="' + p.idx + '" data-kind="' + escapeHtml(kind) + '">');
      parts.push('<span class="th-diff-del">' + escapeHtml(p.sug.original) + '</span>');
      if ((p.sug.suggested || '').length) {
        parts.push('<span class="th-diff-add">' + wrapLockedNumbers(escapeHtml(p.sug.suggested), lockedNumbers) + '</span>');
      }
      parts.push(
        '<span class="th-diff-actions" contenteditable="false">' +
        '<button class="th-accept" data-act="accept" data-idx="' + p.idx + '" title="Accept (' + escapeHtml(p.sug.reason || '') + ')">✓</button>' +
        '<button class="th-reject" data-act="reject" data-idx="' + p.idx + '" title="Reject">✗</button>' +
        '</span>'
      );
      parts.push('</span>');
      cursor = p.end;
    });
    if (cursor < text.length) {
      parts.push(wrapLockedNumbers(escapeHtml(text.slice(cursor)), lockedNumbers));
    }
    previewEl.innerHTML = parts.join('') ||
      '<em class="th-empty">No text yet — click "AI: Draft this section" or start writing.</em>';

    // Build a quick lookup: idx -> placement (so accept uses the EXACT
    // offset we matched at render time, never indexOf at apply time).
    const placementByIdx = {};
    placements.forEach((p) => { placementByIdx[p.idx] = p; });

    previewEl.querySelectorAll('button[data-act]').forEach((btn) => {
      btn.addEventListener('click', (ev) => {
        ev.preventDefault();
        const act = btn.dataset.act;
        const idx = parseInt(btn.dataset.idx, 10);
        const sug = suggestions[idx];
        const place = placementByIdx[idx];
        if (!sug || !place) return;
        let nextText = text;
        if (act === 'accept') {
          nextText = acceptAt(text, place.start, place.end, sug.suggested);
        }
        const remaining = suggestions.filter((_, i) => i !== idx);
        if (typeof onChange === 'function') {
          onChange(nextText, remaining, { accepted: act === 'accept', sug });
        }
      });
    });
  }

  function renderPlain(previewEl, text, lockedNumbers) {
    if (!previewEl) return;
    const html = wrapLockedNumbers(escapeHtml(String(text || '')), lockedNumbers);
    previewEl.innerHTML = html ||
      '<em class="th-empty">No text yet — click "AI: Draft this section" or start writing.</em>';
  }

  // Returns the inner HTML for plain text + locked-number wraps. Used
  // when callers need to compose larger HTML structures.
  function renderPlainInline(text, lockedNumbers) {
    return wrapLockedNumbers(escapeHtml(String(text || '')), lockedNumbers);
  }

  // Back-compat shim: prefer acceptAt / findUniqueOffsets in callers.
  function applyAccept(text, sug) {
    const off = findUniqueOffsets(text, sug && sug.original);
    if (!off) return text;
    return acceptAt(text, off.start, off.end, sug.suggested);
  }

  window.TrackChanges = { render, renderPlain, renderPlainInline, acceptAt,
                          findUniqueOffsets, applyAccept, escapeHtml };
})();
