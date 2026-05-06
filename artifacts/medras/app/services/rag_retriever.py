"""RAG retriever — concurrent fan-out across academic databases.

NOTE: the original spec for this file was truncated in the request.
The implementation here matches the database list defined in
``rag_router.DOMAIN_DATABASE_MAP`` and provides:

* a ``search(database, query, limit)`` adapter for each free public API
  (Crossref, OpenAlex, Semantic Scholar, PubMed E-utilities, Europe PMC,
  arXiv, DOAJ);
* graceful "not implemented" stubs for the closed sources on the list
  (Cochrane, CINAHL Open, IEEE Open) — the function returns an empty
  list and a stub flag so the orchestrator can still report which
  databases were consulted;
* a ``retrieve(databases, query, limit_per_db, total_limit)`` orchestrator
  that runs adapters concurrently with httpx.AsyncClient, normalises
  every record to a single shape, deduplicates by DOI then by
  title+year, and caps the merged result.

All HTTP calls have a per-request timeout (default 8 s) and a polite
``User-Agent`` header naming MedRAS so APIs that throttle anonymous
traffic (Crossref, OpenAlex) bump us into the higher tier.

Public surface
--------------
* ``ADAPTERS`` — dict[database_id, async callable]
* ``search(database, query, limit)``         -> list[Record]
* ``retrieve(databases, query, ...)``        -> {records, sources}
* ``Record``                                  — TypedDict shape
"""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypedDict

import httpx

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 8.0
DEFAULT_LIMIT_PER_DB = 5
DEFAULT_TOTAL_LIMIT = 25
MAX_DATABASES_PER_CALL = 12   # cap concurrent fan-out to protect outbound conns

_USER_AGENT = "MedRAS/1.0 (academic research assistant; mailto:research@medras.local)"


class Record(TypedDict, total=False):
    source: str             # e.g. "crossref"
    title: str
    authors: List[str]
    year: Optional[int]
    journal: str
    doi: str
    url: str
    abstract: str
    is_stub: bool           # True if the adapter is a placeholder
    raw_id: str             # native id from the source (PMID, OpenAlex W..., etc.)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm_year(v: Any) -> Optional[int]:
    if v is None: return None
    try:
        s = str(v); m = re.search(r"\b(19|20)\d{2}\b", s)
        return int(m.group(0)) if m else None
    except Exception:
        return None


def _clean(s: Any) -> str:
    if s is None: return ""
    return re.sub(r"\s+", " ", str(s)).strip()


async def _get_json(client: httpx.AsyncClient, url: str, params: Optional[dict] = None) -> Optional[Any]:
    try:
        r = await client.get(url, params=params)
        if r.status_code != 200:
            log.info("rag_retriever: %s returned HTTP %s", url, r.status_code)
            return None
        return r.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.info("rag_retriever: %s failed (%s)", url, exc)
        return None


async def _get_text(client: httpx.AsyncClient, url: str, params: Optional[dict] = None) -> Optional[str]:
    try:
        r = await client.get(url, params=params)
        if r.status_code != 200:
            return None
        return r.text
    except httpx.HTTPError as exc:
        log.info("rag_retriever: %s failed (%s)", url, exc)
        return None


# ---------------------------------------------------------------------------
# Adapters — free public APIs
# ---------------------------------------------------------------------------

async def _search_crossref(client: httpx.AsyncClient, query: str, limit: int) -> List[Record]:
    data = await _get_json(client, "https://api.crossref.org/works",
                           params={"query": query, "rows": limit,
                                   "select": "DOI,title,author,issued,container-title,abstract,URL"})
    if not data: return []
    out: List[Record] = []
    for it in (data.get("message") or {}).get("items", [])[:limit]:
        title = (it.get("title") or [""])[0]
        authors = [_clean(" ".join(filter(None, [a.get("given"), a.get("family")])))
                   for a in (it.get("author") or [])]
        issued = (((it.get("issued") or {}).get("date-parts") or [[None]])[0] or [None])[0]
        out.append(Record(
            source="crossref",
            title=_clean(title),
            authors=[a for a in authors if a],
            year=_norm_year(issued),
            journal=_clean((it.get("container-title") or [""])[0]),
            doi=_clean(it.get("DOI")),
            url=_clean(it.get("URL")),
            abstract=_clean(re.sub(r"<[^>]+>", "", it.get("abstract") or "")),
            raw_id=_clean(it.get("DOI")),
        ))
    return out


async def _search_openalex(client: httpx.AsyncClient, query: str, limit: int) -> List[Record]:
    data = await _get_json(client, "https://api.openalex.org/works",
                           params={"search": query, "per-page": limit,
                                   "select": "id,title,authorships,publication_year,host_venue,doi,abstract_inverted_index"})
    if not data: return []
    out: List[Record] = []
    for it in (data.get("results") or [])[:limit]:
        # Reconstruct abstract from inverted index.
        ab_idx = it.get("abstract_inverted_index") or {}
        abstract = ""
        if ab_idx:
            positions = []
            for word, idxs in ab_idx.items():
                for i in idxs: positions.append((i, word))
            positions.sort()
            abstract = " ".join(w for _, w in positions)[:1500]
        authors = [_clean(((a.get("author") or {}).get("display_name")))
                   for a in (it.get("authorships") or [])]
        venue = _clean(((it.get("host_venue") or {}).get("display_name")))
        doi = _clean((it.get("doi") or "").replace("https://doi.org/", ""))
        out.append(Record(
            source="openalex",
            title=_clean(it.get("title")),
            authors=[a for a in authors if a],
            year=_norm_year(it.get("publication_year")),
            journal=venue,
            doi=doi,
            url=_clean(it.get("id")),
            abstract=abstract,
            raw_id=_clean(it.get("id")),
        ))
    return out


async def _search_semantic_scholar(client: httpx.AsyncClient, query: str, limit: int) -> List[Record]:
    fields = "title,authors,year,venue,externalIds,abstract,url"
    data = await _get_json(client, "https://api.semanticscholar.org/graph/v1/paper/search",
                           params={"query": query, "limit": limit, "fields": fields})
    if not data: return []
    out: List[Record] = []
    for it in (data.get("data") or [])[:limit]:
        ext = it.get("externalIds") or {}
        out.append(Record(
            source="semantic_scholar",
            title=_clean(it.get("title")),
            authors=[_clean(a.get("name")) for a in (it.get("authors") or []) if a.get("name")],
            year=_norm_year(it.get("year")),
            journal=_clean(it.get("venue")),
            doi=_clean(ext.get("DOI") or ""),
            url=_clean(it.get("url")),
            abstract=_clean(it.get("abstract")),
            raw_id=_clean(it.get("paperId") or ext.get("DOI") or ""),
        ))
    return out


async def _search_pubmed(client: httpx.AsyncClient, query: str, limit: int) -> List[Record]:
    # 1) esearch -> list of PMIDs
    es = await _get_json(client, "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                         params={"db": "pubmed", "term": query, "retmax": limit, "retmode": "json"})
    if not es: return []
    ids = (((es.get("esearchresult") or {}).get("idlist")) or [])[:limit]
    if not ids: return []
    # 2) esummary -> metadata
    su = await _get_json(client, "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                         params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"})
    if not su: return []
    res = (su.get("result") or {})
    out: List[Record] = []
    for pmid in ids:
        item = res.get(pmid) or {}
        if not item: continue
        authors = [_clean(a.get("name")) for a in (item.get("authors") or []) if a.get("name")]
        # Find DOI from articleids
        doi = ""
        for a in (item.get("articleids") or []):
            if a.get("idtype") == "doi":
                doi = _clean(a.get("value")); break
        out.append(Record(
            source="pubmed",
            title=_clean(item.get("title")),
            authors=authors,
            year=_norm_year(item.get("pubdate") or item.get("epubdate")),
            journal=_clean(item.get("fulljournalname") or item.get("source")),
            doi=doi,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            abstract="",  # PubMed esummary doesn't include abstract; would need efetch
            raw_id=pmid,
        ))
    return out


async def _search_europe_pmc(client: httpx.AsyncClient, query: str, limit: int) -> List[Record]:
    data = await _get_json(client, "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                           params={"query": query, "pageSize": limit, "format": "json",
                                   "resultType": "core"})
    if not data: return []
    out: List[Record] = []
    for it in ((data.get("resultList") or {}).get("result") or [])[:limit]:
        authors_raw = (it.get("authorList") or {}).get("author") or []
        authors = [_clean(a.get("fullName") or " ".join(filter(None, [a.get("firstName"), a.get("lastName")])))
                   for a in authors_raw]
        out.append(Record(
            source="europe_pmc",
            title=_clean(it.get("title")),
            authors=[a for a in authors if a],
            year=_norm_year(it.get("pubYear")),
            journal=_clean(it.get("journalTitle")),
            doi=_clean(it.get("doi")),
            url=_clean(it.get("fullTextUrlList", {}).get("fullTextUrl", [{}])[0].get("url")
                       if it.get("fullTextUrlList") else ""),
            abstract=_clean(it.get("abstractText")),
            raw_id=_clean(it.get("id") or it.get("pmid") or ""),
        ))
    return out


async def _search_arxiv(client: httpx.AsyncClient, query: str, limit: int) -> List[Record]:
    text = await _get_text(client, "http://export.arxiv.org/api/query",
                           params={"search_query": f"all:{query}", "start": 0, "max_results": limit})
    if not text: return []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    out: List[Record] = []
    for e in root.findall("a:entry", ns)[:limit]:
        title = _clean((e.findtext("a:title", default="", namespaces=ns)))
        summary = _clean(e.findtext("a:summary", default="", namespaces=ns))
        published = e.findtext("a:published", default="", namespaces=ns)
        link = ""
        for l in e.findall("a:link", ns):
            if l.attrib.get("rel") == "alternate":
                link = l.attrib.get("href", ""); break
        authors = [_clean(a.findtext("a:name", default="", namespaces=ns))
                   for a in e.findall("a:author", ns)]
        out.append(Record(
            source="arxiv",
            title=title,
            authors=[a for a in authors if a],
            year=_norm_year(published),
            journal="arXiv preprint",
            doi="",
            url=link,
            abstract=summary,
            raw_id=link,
        ))
    return out


async def _search_doaj(client: httpx.AsyncClient, query: str, limit: int) -> List[Record]:
    # DOAJ requires URL-encoded path segment for the query.
    from urllib.parse import quote
    data = await _get_json(client, f"https://doaj.org/api/search/articles/{quote(query)}",
                           params={"pageSize": limit, "page": 1})
    if not data: return []
    out: List[Record] = []
    for it in (data.get("results") or [])[:limit]:
        bib = (it.get("bibjson") or {})
        ids = bib.get("identifier") or []
        doi = ""
        for ident in ids:
            if (ident.get("type") or "").lower() == "doi":
                doi = _clean(ident.get("id")); break
        link = ""
        for ln in (bib.get("link") or []):
            if (ln.get("type") or "").lower() == "fulltext":
                link = _clean(ln.get("url")); break
        authors = [_clean(a.get("name")) for a in (bib.get("author") or []) if a.get("name")]
        out.append(Record(
            source="doaj",
            title=_clean(bib.get("title")),
            authors=authors,
            year=_norm_year(bib.get("year")),
            journal=_clean(((bib.get("journal") or {}).get("title"))),
            doi=doi,
            url=link,
            abstract=_clean(bib.get("abstract")),
            raw_id=_clean(it.get("id") or doi),
        ))
    return out


# ---------------------------------------------------------------------------
# Stubs for sources without a free public API
# ---------------------------------------------------------------------------

async def _stub(source_name: str) -> List[Record]:
    log.debug("rag_retriever: stub adapter '%s' returned no results", source_name)
    return [Record(source=source_name, is_stub=True, title="", authors=[], year=None,
                   journal="", doi="", url="", abstract="", raw_id="")]


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------

# Each adapter is wrapped to share the AsyncClient. The dispatcher in
# ``search()`` builds a fresh client when called standalone.
_LIVE_ADAPTERS: Dict[str, Callable[[httpx.AsyncClient, str, int], Awaitable[List[Record]]]] = {
    "crossref":         _search_crossref,
    "openalex":         _search_openalex,
    "semantic_scholar": _search_semantic_scholar,
    "pubmed":           _search_pubmed,
    "europe_pmc":       _search_europe_pmc,
    "arxiv":            _search_arxiv,
    "doaj":             _search_doaj,
}

_STUB_SOURCES = ("cochrane", "cinahl_open", "ieee_open")

ADAPTERS: tuple[str, ...] = tuple(list(_LIVE_ADAPTERS.keys()) + list(_STUB_SOURCES))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def search(database: str, query: str, limit: int = DEFAULT_LIMIT_PER_DB,
                 timeout_s: float = DEFAULT_TIMEOUT_S) -> List[Record]:
    """Search a single database. Convenience wrapper for one-off use."""
    db = (database or "").strip().lower()
    if db in _STUB_SOURCES:
        return await _stub(db)
    fn = _LIVE_ADAPTERS.get(db)
    if not fn:
        log.info("rag_retriever: unknown database '%s'", db)
        return []
    async with httpx.AsyncClient(timeout=timeout_s, headers={"User-Agent": _USER_AGENT}) as client:
        return await fn(client, query, max(1, int(limit or 1)))


def _dedupe(records: List[Record]) -> List[Record]:
    """Drop records with no title; deduplicate by DOI then by (title, year)."""
    seen_doi: set[str] = set()
    seen_tk: set[str] = set()
    out: List[Record] = []
    for r in records:
        if r.get("is_stub"): continue
        title = (r.get("title") or "").strip()
        if not title: continue
        doi = (r.get("doi") or "").strip().lower()
        if doi:
            if doi in seen_doi: continue
            seen_doi.add(doi)
        # Unicode-aware normalisation: keep all letters/digits in any script
        # (\w with re.UNICODE — the default in py3), collapse everything else
        # to a single space. Avoids collisions for non-ASCII titles.
        tk = re.sub(r"[^\w]+", " ", title.lower(), flags=re.UNICODE).strip() + "|" + str(r.get("year") or "")
        if tk in seen_tk: continue
        seen_tk.add(tk)
        out.append(r)
    return out


async def retrieve(databases: List[str], query: str,
                   limit_per_db: int = DEFAULT_LIMIT_PER_DB,
                   total_limit: int = DEFAULT_TOTAL_LIMIT,
                   timeout_s: float = DEFAULT_TIMEOUT_S) -> Dict[str, Any]:
    """Fan out the query across the given databases concurrently.

    Returns ``{"records": [...], "sources": {db: {"count": n, "stub": bool, "error": Optional[str]}}}``.
    Adapter failures are isolated — one source going down never fails the
    whole call.
    """
    q = (query or "").strip()
    if not q or not databases:
        return {"records": [], "sources": {}}

    # Cap fan-out — protect against accidental DoS if a caller passes a
    # huge databases list. The longest legitimate mapping is 5 entries.
    if len(databases) > MAX_DATABASES_PER_CALL:
        databases = list(databases)[:MAX_DATABASES_PER_CALL]

    sources: Dict[str, Dict[str, Any]] = {}
    tasks: List[Awaitable[List[Record]]] = []
    used: List[str] = []

    async with httpx.AsyncClient(timeout=timeout_s, headers={"User-Agent": _USER_AGENT}) as client:
        for db in databases:
            db = (db or "").strip().lower()
            if not db or db in sources: continue
            if db in _STUB_SOURCES:
                sources[db] = {"count": 0, "stub": True, "error": None}
                continue
            fn = _LIVE_ADAPTERS.get(db)
            if not fn:
                sources[db] = {"count": 0, "stub": False, "error": "unknown database"}
                continue
            tasks.append(fn(client, q, max(1, int(limit_per_db or 1))))
            used.append(db)
        results: List[Any] = await asyncio.gather(*tasks, return_exceptions=True)

    merged: List[Record] = []
    for db, res in zip(used, results):
        if isinstance(res, Exception):
            sources[db] = {"count": 0, "stub": False, "error": str(res)}
            continue
        sources[db] = {"count": len(res), "stub": False, "error": None}
        merged.extend(res)

    deduped = _dedupe(merged)
    return {"records": deduped[: max(1, int(total_limit))], "sources": sources}
