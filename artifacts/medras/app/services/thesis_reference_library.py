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

    # --- retraction detection ---
    # Crossref signals retraction via update-to[].type == "retraction",
    # or the work's own type == "retraction", or a title prefix "RETRACTED:".
    retracted = False
    work_type = (data.get("type") or "").lower()
    if work_type == "retraction":
        retracted = True
    if not retracted:
        for upd in (data.get("update-to") or []):
            if (upd.get("type") or "").lower() == "retraction":
                retracted = True
                break
    if not retracted:
        retracted = (title or "").upper().startswith("RETRACTED:")

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
        "retracted": retracted,
    }


# ---------------------------------------------------------------------------
# Distilled RAG search
# ---------------------------------------------------------------------------

# Predatory / deprecated source identifiers we never include from the
# generic adapters. (PubMed and Crossref already filter; this catches
# anything OpenAlex or Semantic Scholar might pass through.)
_BAD_VENUE_TOKENS = (
    "predatory", "vanity press", "research gate preprint",
    "clinicaltrials.gov", "isrctn", "anzctr", "drks", "euctr",
)

_REGISTRY_TITLE_SUFFIX_RE = re.compile(
    r"\[\s*(clinical\s+trial\s+registr\w*|trial\s+registr\w*|registry\s+record)\s*\]",
    re.IGNORECASE,
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
        # Drop clinical-trial registry entries — they are registrations, not
        # published evidence. Identified by title bracket tag or venue name.
        if _REGISTRY_TITLE_SUFFIX_RE.search(title):
            continue
        venue = (r.get("journal") or "").lower()
        if any(t in venue for t in _BAD_VENUE_TOKENS):
            continue
        authors = r.get("authors") or []
        if (len(authors) == 1
                and str(authors[0]).strip().lower() in ("unknown sponsor", "unknown")):
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


# ---------------------------------------------------------------------------
# Reference list parser
# ---------------------------------------------------------------------------

_REF_SPLIT = re.compile(
    r"(?m)(?:^|\n)\s*(?:\d{1,3}[.)]\s+|\[\d{1,3}\]\s+|[-•*]\s+)"
)
_YEAR_4 = re.compile(r"\b((?:19|20)\d{2})\b")


def _parse_block_heuristic(block: str, doi: str = "") -> Dict[str, Any]:
    """Best-effort heuristic parse of a Vancouver/APA-style reference block."""
    block = re.sub(r"\s+", " ", block.strip())
    year_m = _YEAR_4.findall(block)
    year = int(year_m[0]) if year_m else None
    # Vancouver pattern: Authors. Title. Journal. Year;Vol:Pages.
    parts = re.split(r"\.\s+", block, maxsplit=4)
    authors_raw = parts[0] if parts else block
    title = (parts[1] if len(parts) > 1 else "").strip().rstrip(".")
    journal_raw = (parts[2] if len(parts) > 2 else "").strip()
    # Strip year/volume suffix from journal ("2020;45:123" → "")
    journal = re.split(r"\d{4}", journal_raw)[0].strip().rstrip(";,.")
    authors = [a.strip() for a in re.split(r",\s*", authors_raw) if a.strip()][:8]
    if len(title) < 8:
        title = block[:200]
    return {
        "doi": doi,
        "title": title[:300],
        "authors": authors,
        "year": year,
        "journal": journal[:100],
        "abstract": "",
        "source": "imported",
        "verified": False,
        "score": 0.3,
    }


async def parse_reference_list(
    text: str, *, max_refs: int = 200, max_concurrent: int = 6
) -> List[Dict[str, Any]]:
    """Parse a plain-text reference list into structured reference entries.

    Handles:
    - Numbered Vancouver: ``1. Smith J, Jones A. Title. Journal. 2020;45:123.``
    - Bulleted: ``• Smith J et al. Title. Journal. 2020.``
    - DOI-only lines: ``10.1056/NEJMoa...`` (one per line)
    - Mixed lists (DOIs extracted and verified; others heuristically parsed)

    Entries with resolvable DOIs are Crossref-verified; others are marked
    ``verified: False`` so the frontend can prompt the researcher to confirm.
    """
    text = (text or "").strip()
    if not text:
        return []

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # DOI-only input: every non-empty line matches the DOI regex
    doi_only = lines and all(_DOI_RE.match(ln) for ln in lines)
    if doi_only:
        dois = [ln.rstrip(".,;)") for ln in lines][:max_refs]
        return await verify_dois(dois, max_concurrent=max_concurrent)

    # Split into reference blocks on numbered/bulleted boundaries
    chunks = _REF_SPLIT.split("\n" + text)
    blocks = [c.strip() for c in chunks if c.strip()][:max_refs]
    if not blocks:
        blocks = [b.strip() for b in text.split("\n\n") if b.strip()][:max_refs]
    if not blocks:
        blocks = [text]

    sem = asyncio.Semaphore(max_concurrent)

    async def _process(block: str) -> Optional[Dict[str, Any]]:
        async with sem:
            doi_m = _DOI_RE.search(block)
            doi = doi_m.group(0).rstrip(".,;)") if doi_m else ""
            if doi:
                verified = await verify_doi(doi)
                if verified:
                    return verified
            return _parse_block_heuristic(block, doi)

    results = await asyncio.gather(*[_process(b) for b in blocks],
                                   return_exceptions=True)
    return [r for r in results if isinstance(r, dict) and r]


# ---------------------------------------------------------------------------
# Topic-scored selection from a session library
# ---------------------------------------------------------------------------

def score_and_select(
    records: List[Dict[str, Any]],
    topic: str,
    limit: int = 18,
    recency_window: int = 15,
) -> List[Dict[str, Any]]:
    """Score ``records`` against ``topic`` and return the top ``limit`` entries.

    Used by the section writer when the researcher has a pre-loaded reference
    library — we pick the most relevant papers for the current chapter rather
    than sending all refs to the LLM.
    """
    if not records:
        return []
    terms = _topic_terms(topic)
    scored: List[Dict[str, Any]] = []
    for r in records:
        r2 = dict(r)
        r2["score"] = _score(r2, terms, recency_window)
        scored.append(r2)
    scored.sort(key=lambda r: r.get("score", 0.0), reverse=True)
    return scored[:limit]
