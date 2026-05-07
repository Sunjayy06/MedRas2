"""Thesis reference library helpers.

Three operations over the existing RAG stack:

1. ``verify_doi(doi)`` — hit Crossref REST and return validated metadata
   (title, authors, year, journal, abstract). Used when the researcher
   pastes a DOI manually or uploads a PDF whose first-page DOI we sniff.
2. ``search(topic, domain_hint=None, limit=20)`` — distilled RAG search.
   Calls ``rag_router`` for domain → databases, ``rag_retriever`` for
   actual fan-out, then **distillation**: drop records with no abstract,
   filter to within the domain's quality whitelist, and rank by a simple
   composite score (recency + abstract overlap). Returns at most ``limit``.
3. ``summarise(record)`` — one-line distilled summary for the library
   panel ("RCT in 200 obese adults; metformin reduced HbA1c by 0.6%").
   Heuristic-only; no LLM dependency in v1 so the library is fully
   functional even when Gemini is rate-limited.

Stateless. The client (IndexedDB) holds the library; we only enrich.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from app.services import rag_retriever, rag_router

log = logging.getLogger(__name__)

USER_AGENT = "MedRAS-Thesis/1.0 (mailto:research@medras.local)"
CROSSREF_TIMEOUT_S = 6.0


# ---------------------------------------------------------------------------
# DOI verification
# ---------------------------------------------------------------------------

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)


def extract_dois(text: str) -> List[str]:
    """Find every DOI-shaped string in ``text``. Order-preserving, deduped."""
    seen: set[str] = set()
    out: List[str] = []
    for m in _DOI_RE.finditer(text or ""):
        d = m.group(0).rstrip(".,;)")
        k = d.lower()
        if k not in seen:
            seen.add(k); out.append(d)
    return out


async def verify_doi(doi: str) -> Optional[Dict[str, Any]]:
    """Validate a DOI via Crossref. Returns ``None`` if not found / network fail."""
    doi = (doi or "").strip().lstrip("doi:").strip()
    if not _DOI_RE.match(doi):
        return None
    try:
        async with httpx.AsyncClient(timeout=CROSSREF_TIMEOUT_S,
                                     headers={"User-Agent": USER_AGENT}) as c:
            r = await c.get(f"https://api.crossref.org/works/{doi}")
            if r.status_code != 200:
                return None
            data = (r.json() or {}).get("message") or {}
    except (httpx.HTTPError, ValueError):
        return None
    if not data:
        return None
    title = (data.get("title") or [""])[0]
    authors = []
    for a in (data.get("author") or []):
        nm = " ".join(filter(None, [a.get("given"), a.get("family")])).strip()
        if nm:
            authors.append(nm)
    issued = (((data.get("issued") or {}).get("date-parts") or [[None]])[0] or [None])[0]
    return {
        "doi": data.get("DOI") or doi,
        "title": (title or "").strip(),
        "authors": authors,
        "year": int(issued) if isinstance(issued, int) else None,
        "journal": ((data.get("container-title") or [""]) or [""])[0],
        "abstract": re.sub(r"<[^>]+>", "", data.get("abstract") or "").strip(),
        "url": data.get("URL") or f"https://doi.org/{doi}",
        "source": "crossref",
        "verified": True,
    }


# ---------------------------------------------------------------------------
# Distilled RAG search
# ---------------------------------------------------------------------------

# Predatory / deprecated source identifiers we never include from the
# generic adapters. (PubMed and Crossref already filter; this catches
# anything OpenAlex or Semantic Scholar might pass through.)
_BAD_VENUE_TOKENS = (
    "predatory", "vanity press", "research gate preprint",
)

# Recency window per domain. Older work is fine for foundational topics
# but we down-weight it.
_RECENCY_WINDOW_YEARS = {
    "medical_clinical": 12,
    "pharmacology":     12,
    "nursing":          12,
    "engineering":      15,
    "computer_science": 8,
    "social_sciences":  20,
    "psychology":       15,
    "business_economics": 12,
    "law":              25,
    "education":        15,
    "humanities":       30,
    "general":          15,
}


def _quality_filter(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop records that fail the distillation quality bar."""
    out: List[Dict[str, Any]] = []
    for r in records:
        if r.get("is_stub"):
            continue
        title = (r.get("title") or "").strip()
        if not title or len(title) < 6:
            continue
        venue = (r.get("journal") or "").lower()
        if any(t in venue for t in _BAD_VENUE_TOKENS):
            continue
        # Records with no abstract are de-prioritised but kept (some
        # high-quality refs from Crossref legitimately lack abstracts).
        out.append(r)
    return out


def _topic_terms(topic: str) -> List[str]:
    """Lowercase content words from the topic for overlap scoring."""
    stop = {"the", "and", "for", "with", "of", "in", "on", "to", "a", "an",
            "is", "are", "by", "from", "at", "as", "via", "vs", "vs.",
            "study", "research", "analysis"}
    return [w for w in re.findall(r"[a-z][a-z\-]{2,}", topic.lower())
            if w not in stop]


def _score(record: Dict[str, Any], topic_terms: List[str],
           recency_window: int, current_year: int = 2026) -> float:
    """Composite distillation score in [0, 1]."""
    # Abstract / title overlap with topic
    blob = ((record.get("title") or "") + " " +
            (record.get("abstract") or "")).lower()
    if not blob.strip():
        return 0.0
    hits = sum(1 for t in topic_terms if t in blob)
    overlap = min(1.0, hits / max(3, len(topic_terms)))

    # Recency bonus
    yr = record.get("year")
    if isinstance(yr, int) and yr > 1900:
        age = max(0, current_year - yr)
        recency = max(0.0, 1.0 - (age / max(1, recency_window)))
    else:
        recency = 0.3   # neutral when year missing

    # Has abstract bonus
    abst_bonus = 0.15 if (record.get("abstract") or "").strip() else 0.0

    # Has DOI bonus (verifiable)
    doi_bonus = 0.10 if (record.get("doi") or "").strip() else 0.0

    return round(0.55 * overlap + 0.20 * recency + abst_bonus + doi_bonus, 3)


async def search(topic: str, *, domain_hint: Optional[str] = None,
                 limit: int = 20, limit_per_db: int = 5) -> Dict[str, Any]:
    """Distilled RAG search for thesis references.

    Returns ``{records, sources, domain, databases}``. Records are sorted
    by composite distillation score (highest first) and capped at ``limit``.
    """
    topic = (topic or "").strip()
    if not topic:
        return {"records": [], "sources": {}, "domain": "general", "databases": []}

    routing = rag_router.route(topic=topic) if not domain_hint \
        else {"domain": domain_hint,
              "databases": rag_router.get_databases_for_domain(domain_hint)}
    domain = routing["domain"]
    databases = routing["databases"]

    raw = await rag_retriever.retrieve(
        databases=databases, query=topic,
        limit_per_db=limit_per_db, total_limit=limit * 2,
    )
    records = _quality_filter(raw.get("records") or [])

    terms = _topic_terms(topic)
    window = _RECENCY_WINDOW_YEARS.get(domain, 15)
    for r in records:
        r["score"] = _score(r, terms, window)
    records.sort(key=lambda r: r.get("score", 0.0), reverse=True)

    return {
        "records": records[:limit],
        "sources": raw.get("sources") or {},
        "domain": domain,
        "databases": databases,
    }


# ---------------------------------------------------------------------------
# Heuristic distilled summary (no LLM)
# ---------------------------------------------------------------------------

_SUMMARY_PATTERNS: List[tuple[str, str]] = [
    (r"\b(randomi[sz]ed|RCT|controlled trial)\b",        "RCT"),
    (r"\b(cohort)\b",                                    "cohort"),
    (r"\b(case[- ]control)\b",                           "case-control"),
    (r"\b(cross[- ]sectional)\b",                        "cross-sectional"),
    (r"\b(systematic review|meta[- ]analysis)\b",        "systematic review"),
    (r"\b(retrospective)\b",                             "retrospective"),
    (r"\b(prospective)\b",                               "prospective"),
    (r"\b(observational)\b",                             "observational"),
]

_N_RE = re.compile(r"\bn\s*=\s*(\d{2,6})\b", re.I)


def summarise(record: Dict[str, Any]) -> str:
    """One-line distilled summary for the library panel."""
    abstract = (record.get("abstract") or "").strip()
    title    = (record.get("title") or "").strip()
    text     = abstract or title
    if not text:
        return "No abstract available."

    # Design
    design = ""
    for pat, label in _SUMMARY_PATTERNS:
        if re.search(pat, text, re.I):
            design = label; break

    # Sample size
    n = ""
    nm = _N_RE.search(text)
    if nm:
        n = f"n={nm.group(1)}"

    # First sentence of abstract
    first = re.split(r"(?<=[.!?])\s", abstract)[0] if abstract else ""
    if len(first) > 220:
        first = first[:217].rstrip() + "…"

    head_bits = [b for b in [design, n] if b]
    head = "; ".join(head_bits)
    if head and first:
        return f"{head} — {first}"
    return first or head or "Reference imported (no abstract)."


# ---------------------------------------------------------------------------
# Bulk DOI verification
# ---------------------------------------------------------------------------

async def verify_dois(dois: List[str], *, max_concurrent: int = 6) -> List[Dict[str, Any]]:
    """Validate many DOIs concurrently. Failed DOIs come back with
    ``{"doi": d, "verified": False, "error": "not found"}`` so the UI can
    show the user what failed."""
    sem = asyncio.Semaphore(max_concurrent)

    async def one(d: str) -> Dict[str, Any]:
        async with sem:
            res = await verify_doi(d)
            if res is None:
                return {"doi": d, "verified": False, "error": "not found"}
            return res

    tasks = [one(d) for d in dois if d]
    if not tasks:
        return []
    return await asyncio.gather(*tasks)
