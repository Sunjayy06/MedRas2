"""Extract reference metadata from uploaded PDF/DOCX/TXT files using Gemini.

For each reference found in the corpus we return a dict with keys:
``title, authors[], journal, year, volume, issue, pages, doi, raw``.

Used by Step 5 of the Proposal Writing Module. Reuses the shared text
extractor (`outline_extractor`) and the shared Gemini helpers in
`plagiarism_analyzer`.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from app.services import outline_extractor, plagiarism_analyzer as _pa

MAX_CORPUS_CHARS = 40_000
MAX_REFS = 200

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.I)


_EXTRACT_SYSTEM_PROMPT = (
    "You are a bibliographic metadata extractor. The user has uploaded one or "
    "more documents that contain academic references (a reference list, a "
    "single paper they want to cite, or a literature-review export). Identify "
    "every distinct citation in the corpus and return a JSON object.\n\n"
    "OUTPUT SCHEMA — return EXACTLY this shape:\n"
    "{\n"
    '  "references": [\n'
    "    {\n"
    '      "title":   "string (paper title, no trailing period)",\n'
    '      "authors": ["Last F", "Last F", ...],   // each as written\n'
    '      "journal": "string (journal/conference/book name) or empty",\n'
    '      "year":    "YYYY string or empty",\n'
    '      "volume":  "string or empty",\n'
    '      "issue":   "string or empty",\n'
    '      "pages":   "string like 123-145 or empty",\n'
    '      "doi":     "10.xxxx/yyyy without https prefix, or empty"\n'
    "    }, ...\n"
    "  ]\n"
    "}\n\n"
    "RULES:\n"
    "- Extract ONLY references that actually appear in the corpus. Never invent.\n"
    "- If a single uploaded document IS itself a paper (not a list of references), "
    "return ONE reference describing that paper.\n"
    "- Deduplicate obvious repeats (same DOI or near-identical title+year).\n"
    "- If a field is missing in the source, return an empty string for it (never null).\n"
    "- Return at most 200 references."
)


def _truncate(text: str, cap: int) -> str:
    if len(text) <= cap: return text
    return text[:cap].rsplit(" ", 1)[0] + " …"


def _normalise_doi(doi: str) -> str:
    if not doi: return ""
    d = doi.strip()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d, flags=re.I)
    d = re.sub(r"^doi:\s*", "", d, flags=re.I)
    return d.strip().rstrip(".,;)")


def _coerce_ref(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict): return {}
    authors_raw = raw.get("authors") or []
    if isinstance(authors_raw, str):
        authors_raw = [a.strip() for a in re.split(r"[,;]| and ", authors_raw) if a.strip()]
    authors = [str(a).strip() for a in authors_raw if str(a).strip()]
    return {
        "title":   str(raw.get("title") or "").strip(),
        "authors": authors[:30],
        "journal": str(raw.get("journal") or "").strip(),
        "year":    str(raw.get("year") or "").strip(),
        "volume":  str(raw.get("volume") or "").strip(),
        "issue":   str(raw.get("issue") or "").strip(),
        "pages":   str(raw.get("pages") or "").strip(),
        "doi":     _normalise_doi(str(raw.get("doi") or "")),
    }


def extract_references_from_text(corpus: str) -> List[Dict[str, Any]]:
    """Ask Gemini to pull structured references out of a free-text corpus."""
    text = (corpus or "").strip()
    if not text:
        return []
    text = _truncate(text, MAX_CORPUS_CHARS)

    def _call() -> Dict[str, Any]:
        return _pa._call_gemini_json(  # noqa: SLF001
            system_prompt=_EXTRACT_SYSTEM_PROMPT,
            user_text="--- CORPUS ---\n" + text,
            max_tokens=8192,
        )

    try:
        raw = _pa._with_retry(_call, attempts=2, base_delay=1.5)
    except _pa.ProviderQuotaExhausted:
        raise
    except json.JSONDecodeError:
        return []

    if not isinstance(raw, dict): return []
    items = raw.get("references")
    if not isinstance(items, list): return []
    out = []
    for it in items[:MAX_REFS]:
        ref = _coerce_ref(it)
        # Salvage DOI from title if model put it in the wrong field
        if not ref.get("doi"):
            for blob in (ref.get("title", ""), ref.get("journal", "")):
                m = _DOI_RE.search(blob)
                if m:
                    ref["doi"] = _normalise_doi(m.group(0))
                    break
        if ref.get("title") or ref.get("doi"):
            out.append(ref)
    return out


def extract_references_from_upload(filename: str, content: bytes) -> List[Dict[str, Any]]:
    """Extract text from a single PDF/DOCX/PPTX/TXT/MD upload then pull refs."""
    text = outline_extractor.extract_text(filename, content)
    return extract_references_from_text(text or "")
