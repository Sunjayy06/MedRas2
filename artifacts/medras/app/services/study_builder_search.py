"""Study Builder — multi-source academic literature search."""

from __future__ import annotations

import asyncio
import datetime
import logging
import math
import os
import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx

log = logging.getLogger(__name__)

_TIMEOUT      = 5.0
_UA           = "MedRAS/1.0 (academic research assistant; mailto:research@medras.local)"
_CURRENT_YEAR = datetime.datetime.now().year

NCBI_ESEARCH  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
NCBI_EFETCH   = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EPMC_BASE     = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
S2_BASE       = "https://api.semanticscholar.org/graph/v1/paper/search"
OPENALEX_BASE = "https://api.openalex.org/works"
WHO_IRIS_BASE = "https://iris.who.int/rest/search"


def classify_evidence(title: str, journal: str = "", source: str = "") -> str:
    text = (title + " " + journal + " " + source).lower()
    if any(k in text for k in ("cochrane", "systematic review", "meta-analysis",
                                "meta analysis", "scoping review")):
        return "systematic_review"
    if any(k in text for k in ("randomized", "randomised", "randomized controlled",
                                "clinical trial", " rct", "rct ")):
        return "rct"
    if any(k in text for k in ("guideline", "recommendation", "who report",
                                "clinical practice guideline", "icmr", "national guideline")):
        return "guideline"
    return "observational"


def _reconstruct_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos: dict[int, str] = {}
    for word, positions in inv.items():
        for p in positions:
            pos[p] = word
    return " ".join(pos[i] for i in sorted(pos))


async def _search_pubmed(query: str, client: httpx.AsyncClient, n: int = 6) -> list[dict]:
    ncbi_key = os.environ.get("NCBI_API_KEY", "")
    params: dict[str, Any] = {"db": "pubmed", "term": query, "retmax": n,
                               "retmode": "json", "sort": "relevance"}
    if ncbi_key:
        params["api_key"] = ncbi_key
    try:
        r = await client.get(NCBI_ESEARCH, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        fp: dict[str, Any] = {"db": "pubmed", "id": ",".join(ids),
                               "rettype": "abstract", "retmode": "xml"}
        if ncbi_key:
            fp["api_key"] = ncbi_key
        fr = await client.get(NCBI_EFETCH, params=fp, timeout=_TIMEOUT)
        fr.raise_for_status()
        return _parse_pubmed_xml(fr.text)
    except Exception as exc:
        log.warning("PubMed failed: %s", exc)
        return []


def _parse_pubmed_xml(xml_text: str) -> list[dict]:
    papers = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    for art in root.findall(".//PubmedArticle"):
        try:
            citation = art.find("MedlineCitation")
            article  = citation.find("Article")
            title    = (article.findtext("ArticleTitle") or "").strip()
            parts    = [t.text or "" for t in article.findall(".//AbstractText")]
            abstract = " ".join(parts).strip()
            journal  = (article.findtext("Journal/Title")
                        or article.findtext("Journal/ISOAbbreviation") or "")
            year_el  = (article.find("Journal/JournalIssue/PubDate/Year")
                        or article.find("Journal/JournalIssue/PubDate/MedlineDate"))
            year = int(year_el.text[:4]) if (year_el is not None and year_el.text) else 0
            authors = []
            for a in article.findall("AuthorList/Author")[:3]:
                ln = a.findtext("LastName") or ""
                fn = a.findtext("ForeName") or ""
                if ln:
                    authors.append(f"{ln} {fn}".strip())
            pmid = citation.findtext("PMID") or ""
            doi  = ""
            for id_el in art.findall(".//ArticleId"):
                if id_el.get("IdType") == "doi":
                    doi = id_el.text or ""
            papers.append({
                "title": title, "abstract": abstract, "journal": journal,
                "year": year, "authors": authors, "doi": doi, "pmid": pmid,
                "citation_count": 0, "source": "pubmed",
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
                "evidence_type": classify_evidence(title, journal),
            })
        except Exception:
            continue
    return papers


async def _search_europe_pmc(query: str, client: httpx.AsyncClient, n: int = 5) -> list[dict]:
    params = {"query": query, "format": "json", "resultType": "core",
              "pageSize": n, "sort": "CITED"}
    try:
        r = await client.get(EPMC_BASE, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return [_epmc_paper(i, "europe_pmc")
                for i in r.json().get("resultList", {}).get("result", [])]
    except Exception as exc:
        log.warning("EuropePMC failed: %s", exc)
        return []


async def _search_cochrane(query: str, client: httpx.AsyncClient, n: int = 4) -> list[dict]:
    params = {"query": f'({query}) AND JOURNAL:"Cochrane Database"',
              "format": "json", "resultType": "core", "pageSize": n}
    try:
        r = await client.get(EPMC_BASE, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        papers = [_epmc_paper(i, "cochrane_via_epmc")
                  for i in r.json().get("resultList", {}).get("result", [])]
        for p in papers:
            p["evidence_type"] = "systematic_review"
        return papers
    except Exception as exc:
        log.warning("Cochrane failed: %s", exc)
        return []


def _epmc_paper(item: dict, source: str) -> dict:
    title   = (item.get("title") or "").strip()
    doi     = item.get("doi", "")
    pmid    = item.get("pmid", "")
    journal = item.get("journalTitle", "")
    url     = (f"https://europepmc.org/article/MED/{pmid}" if pmid
               else f"https://doi.org/{doi}" if doi else "")
    return {
        "title": title, "abstract": (item.get("abstractText") or "").strip(),
        "journal": journal, "year": int(item.get("pubYear", 0) or 0),
        "authors": [a.strip() for a in (item.get("authorString") or "").split(",")][:3],
        "doi": doi, "pmid": pmid,
        "citation_count": int(item.get("citedByCount", 0) or 0),
        "source": source, "url": url,
        "evidence_type": classify_evidence(title, journal, source),
    }


async def _search_semantic_scholar(query: str, client: httpx.AsyncClient, n: int = 5) -> list[dict]:
    s2_key  = os.environ.get("SEMANTIC_SCHOLAR_KEY", "")
    params  = {"query": query,
               "fields": "title,authors,abstract,year,venue,citationCount,externalIds",
               "limit": n}
    headers = {"X-API-KEY": s2_key} if s2_key else {}
    try:
        r = await client.get(S2_BASE, params=params, headers=headers, timeout=_TIMEOUT)
        r.raise_for_status()
        papers = []
        for item in r.json().get("data", []):
            ext   = item.get("externalIds") or {}
            doi   = ext.get("DOI", "")
            title = (item.get("title") or "").strip()
            papers.append({
                "title": title, "abstract": item.get("abstract") or "",
                "journal": item.get("venue") or "",
                "year": item.get("year") or 0,
                "authors": [a.get("name", "") for a in (item.get("authors") or [])[:3]],
                "doi": doi, "pmid": str(ext.get("PubMed", "")),
                "citation_count": item.get("citationCount") or 0,
                "source": "semantic_scholar",
                "url": f"https://doi.org/{doi}" if doi else "",
                "evidence_type": classify_evidence(title, item.get("venue", "")),
            })
        return papers
    except Exception as exc:
        log.warning("SemanticScholar failed: %s", exc)
        return []


async def _search_openalex(query: str, client: httpx.AsyncClient, n: int = 5) -> list[dict]:
    params = {
        "search": query, "per-page": n,
        "select": ("title,authorships,publication_year,primary_location,"
                   "abstract_inverted_index,cited_by_count,ids"),
        "mailto": "research@medras.local",
    }
    try:
        r = await client.get(OPENALEX_BASE, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        papers = []
        for item in r.json().get("results", []):
            ids      = item.get("ids") or {}
            doi_raw  = ids.get("doi", "")
            doi      = doi_raw.replace("https://doi.org/", "") if doi_raw else ""
            pmid_raw = ids.get("pmid", "")
            pmid     = pmid_raw.replace("https://pubmed.ncbi.nlm.nih.gov/", "").strip("/") if pmid_raw else ""
            loc      = item.get("primary_location") or {}
            journal  = (loc.get("source") or {}).get("display_name", "")
            title    = (item.get("title") or "").strip()
            papers.append({
                "title": title,
                "abstract": _reconstruct_abstract(item.get("abstract_inverted_index")),
                "journal": journal, "year": item.get("publication_year") or 0,
                "authors": [(a.get("author") or {}).get("display_name", "")
                            for a in (item.get("authorships") or [])[:3]],
                "doi": doi, "pmid": pmid,
                "citation_count": item.get("cited_by_count") or 0,
                "source": "openalex",
                "url": f"https://doi.org/{doi}" if doi else "",
                "evidence_type": classify_evidence(title, journal),
            })
        return papers
    except Exception as exc:
        log.warning("OpenAlex failed: %s", exc)
        return []


async def _search_who_iris(query: str, client: httpx.AsyncClient, n: int = 3) -> list[dict]:
    params = {"query": query, "scope": "/", "expand": "metadata", "limit": n, "offset": 0}
    try:
        r = await client.get(WHO_IRIS_BASE, params=params, timeout=_TIMEOUT,
                             headers={"Accept": "application/json"})
        r.raise_for_status()
        data  = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        papers = []
        for item in items[:n]:
            meta     = {m.get("key", ""): m.get("value", "") for m in (item.get("metadata") or [])}
            title    = meta.get("dc.title", item.get("name", "")).strip()
            if not title:
                continue
            year_str = meta.get("dc.date.issued", "")
            year     = int(year_str[:4]) if year_str and len(year_str) >= 4 else 0
            handle   = item.get("handle", "")
            papers.append({
                "title": title,
                "abstract": meta.get("dc.description.abstract", "").strip(),
                "journal": "WHO IRIS", "year": year,
                "authors": ["World Health Organization"],
                "doi": "", "pmid": "", "citation_count": 0,
                "source": "who_iris",
                "url": f"https://iris.who.int/handle/{handle}" if handle else "",
                "evidence_type": "guideline",
            })
        return papers
    except Exception as exc:
        log.warning("WHO IRIS failed: %s", exc)
        return []


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())


def _deduplicate(papers: list[dict]) -> list[dict]:
    seen_doi:   set[str] = set()
    seen_title: set[str] = set()
    out = []
    for p in papers:
        doi = (p.get("doi") or "").strip().lower()
        nt  = _norm(p.get("title", ""))
        if doi and doi in seen_doi:
            continue
        if nt and nt in seen_title:
            continue
        if doi:
            seen_doi.add(doi)
        if nt:
            seen_title.add(nt)
        out.append(p)
    return out


def _score(p: dict) -> float:
    year  = p.get("year") or 0
    cites = p.get("citation_count") or 0
    recency = max(0.0, 1.0 - 0.08 * (_CURRENT_YEAR - year)) if year else 0.0
    base    = 0.6 * recency + 0.4 * min(math.log1p(cites) / 10.0, 1.0)
    etype   = p.get("evidence_type", "")
    if etype == "systematic_review":
        base += 0.4
    elif etype == "guideline":
        base += 0.15
    return base


async def multi_source_search(query: str, top_n: int = 8) -> dict:
    hdrs = {"User-Agent": _UA}
    async with httpx.AsyncClient(headers=hdrs, follow_redirects=True) as client:
        results = await asyncio.gather(
            _search_pubmed(query, client),
            _search_cochrane(query, client),
            _search_europe_pmc(query, client),
            _search_semantic_scholar(query, client),
            _search_openalex(query, client),
            _search_who_iris(query, client),
            return_exceptions=True,
        )
    labels = ["pubmed", "cochrane_via_epmc", "europe_pmc",
              "semantic_scholar", "openalex", "who_iris"]
    papers:      list[dict] = []
    sources_hit: set[str]   = set()
    for label, res in zip(labels, results):
        if isinstance(res, list) and res:
            papers.extend(res)
            sources_hit.add(label)
        elif isinstance(res, Exception):
            log.warning("Source %s: %s", label, res)
    deduped = _deduplicate(papers)
    ranked  = sorted(deduped, key=_score, reverse=True)[:top_n]
    return {"papers": ranked, "sources_searched": sorted(sources_hit),
            "total_found": len(deduped)}
