"""PDF chunking and TF-IDF keyword retrieval for Study Builder.

No external ML libraries — pure Python with pypdf.

Chunking strategy
─────────────────
Text is extracted page-by-page so each word retains its page number.
Chunks of ~400 words are created with a 50-word overlap between neighbours.
Each chunk records the page range it spans.

Retrieval strategy
──────────────────
Question keywords (stop-words removed) are matched against chunk keywords
using simple set overlap.  A small numeric-content bonus rewards chunks that
contain numbers, which tend to carry the quantitative evidence researchers
most need.
"""

from __future__ import annotations

import io
import logging
import re

log = logging.getLogger(__name__)

_CHUNK_WORDS   = 400   # target words per chunk
_OVERLAP_WORDS = 50    # overlap between adjacent chunks
_MIN_TEXT_LEN  = 200   # chars — fewer → scanned/image PDF

_SW: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "of", "in", "is", "are", "for", "to",
    "with", "on", "at", "by", "from", "be", "was", "were", "this", "that",
    "which", "it", "its", "as", "we", "our", "their", "there", "these",
    "those", "but", "not", "no", "has", "have", "had", "been",
    "also", "than", "however", "between", "among", "after", "before",
    "results", "methods", "conclusions", "background", "objective",
    "patients", "patient", "study", "studies", "found", "showed",
})


def _keywords(text: str) -> frozenset[str]:
    clean = re.sub(r"[^\w\s]", " ", text.lower())
    return frozenset(w for w in clean.split() if w not in _SW and len(w) > 2)


def chunk_pdf(content: bytes, filename: str) -> dict:
    """Extract text from PDF *content* bytes and split into overlapping chunks.

    Returns::

        {
            "title":       str,          # from PDF metadata or filename
            "page_count":  int,
            "chunks":      [             # ordered by position in doc
                {
                    "text":       str,
                    "start_page": int,   # 1-based
                    "end_page":   int,   # 1-based
                    "chunk_idx":  int,   # 0-based
                }
            ],
            "total_words": int,
        }

    Raises :class:`ValueError` with a user-friendly message on failure.
    """
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(content))
    except Exception as exc:
        raise ValueError(
            "Could not open this PDF. It may be corrupted or password-protected."
        ) from exc

    page_count = len(reader.pages)
    if page_count == 0:
        raise ValueError("This PDF contains no pages.")

    # ── Per-page text extraction ────────────────────────────────────────────
    # page_words: list of (word, 1-based page number)
    page_words: list[tuple[str, int]] = []
    for page_num, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        for w in text.split():
            page_words.append((w, page_num))

    all_text = " ".join(w for w, _ in page_words)
    if len(all_text.strip()) < _MIN_TEXT_LEN:
        raise ValueError(
            "This PDF appears to be a scanned image. Please use a text-based PDF."
        )

    total_words = len(page_words)

    # ── Overlapping chunks ──────────────────────────────────────────────────
    chunks: list[dict] = []
    start     = 0
    chunk_idx = 0

    while start < total_words:
        end          = min(start + _CHUNK_WORDS, total_words)
        chunk_slice  = page_words[start:end]
        chunk_text   = " ".join(w for w, _ in chunk_slice)
        start_page   = chunk_slice[0][1]  if chunk_slice else 1
        end_page     = chunk_slice[-1][1] if chunk_slice else page_count

        chunks.append({
            "text":       chunk_text,
            "start_page": start_page,
            "end_page":   end_page,
            "chunk_idx":  chunk_idx,
        })
        chunk_idx += 1

        if end >= total_words:
            break
        start += _CHUNK_WORDS - _OVERLAP_WORDS

    # ── PDF title from metadata ─────────────────────────────────────────────
    title = filename
    try:
        meta = reader.metadata
        if meta and getattr(meta, "title", None) and len(meta.title.strip()) > 3:
            title = meta.title.strip()
    except Exception:
        pass

    log.debug(
        "chunk_pdf '%s': %d pages, %d words → %d chunks",
        filename, page_count, total_words, len(chunks),
    )

    return {
        "title":       title,
        "page_count":  page_count,
        "chunks":      chunks,
        "total_words": total_words,
    }


def retrieve_top_chunks(
    chunks: list[dict],
    question: str,
    top_n: int = 5,
) -> list[dict]:
    """Return the *top_n* most relevant chunks for *question*.

    Scoring: keyword overlap with question + 0.5 bonus if the chunk
    contains any digit and overlap > 0 (numeric evidence reward).
    Falls back to the first *top_n* chunks if there are no useful keywords.
    """
    if not chunks:
        return []

    q_kw = _keywords(question)
    if not q_kw:
        return chunks[:top_n]

    scored: list[tuple[float, dict]] = []
    _has_num = re.compile(r"\d")

    for chunk in chunks:
        chunk_kw = _keywords(chunk["text"])
        overlap  = len(q_kw & chunk_kw)
        bonus    = 0.5 if overlap > 0 and _has_num.search(chunk["text"]) else 0.0
        scored.append((overlap + bonus, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_n]]
