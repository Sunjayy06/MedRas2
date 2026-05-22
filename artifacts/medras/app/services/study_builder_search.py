"""Study Builder — multi-source academic literature search (RAG layer)."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import math
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import httpx

log = logging.getLogger(__name__)

_TIMEOUT      = 6.0
_UA           = "MedRAS/1.0 (academic research assistant; mailto:research@medras.local)"
_CURRENT_YEAR = datetime.datetime.now().year

NCBI_ESEARCH   = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
NCBI_EFETCH    = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EPMC_BASE      = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
S2_BASE        = "https://api.semanticscholar.org/graph/v1/paper/search"
OPENALEX_BASE  = "https://api.openalex.org/works"
WHO_IRIS_BASE  = "https://iris.who.int/rest/search"
CROSSREF_BASE  = "https://api.crossref.org/works"
CORE_BASE      = "https://api.core.ac.uk/v3/search/works"
MEDRXIV_BASE   = "https://api.medrxiv.org/details/medrxiv"
SCOPUS_BASE    = "https://api.elsevier.com/content/search/scopus"


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


# ── PubMed ──────────────────────────────────────────────────────────────────
async def _search_pubmed(query: str, client: httpx.AsyncClient, n: int = 7) -> list[dict]:
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
                "open_access": False,
            })
        except Exception:
            continue
    return papers


# ── Europe PMC ──────────────────────────────────────────────────────────────
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
        papers = [_epmc_paper(i, "cochrane") for i in
                  r.json().get("resultList", {}).get("result", [])]
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
        "open_access": bool(item.get("isOpenAccess") == "Y"),
    }


# ── Semantic Scholar ─────────────────────────────────────────────────────────
async def _search_semantic_scholar(query: str, client: httpx.AsyncClient, n: int = 6) -> list[dict]:
    s2_key  = os.environ.get("SEMANTIC_SCHOLAR_KEY", "")
    params  = {"query": query,
               "fields": "title,authors,abstract,year,venue,citationCount,externalIds,isOpenAccess",
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
                "open_access": bool(item.get("isOpenAccess")),
            })
        return papers
    except Exception as exc:
        log.warning("SemanticScholar failed: %s", exc)
        return []


# ── OpenAlex ─────────────────────────────────────────────────────────────────
async def _search_openalex(query: str, client: httpx.AsyncClient, n: int = 5) -> list[dict]:
    params = {
        "search": query, "per-page": n,
        "select": ("title,authorships,publication_year,primary_location,"
                   "abstract_inverted_index,cited_by_count,ids,open_access"),
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
            oa       = (item.get("open_access") or {})
            oa_url   = oa.get("oa_url", "")
            papers.append({
                "title": title,
                "abstract": _reconstruct_abstract(item.get("abstract_inverted_index")),
                "journal": journal, "year": item.get("publication_year") or 0,
                "authors": [(a.get("author") or {}).get("display_name", "")
                            for a in (item.get("authorships") or [])[:3]],
                "doi": doi, "pmid": pmid,
                "citation_count": item.get("cited_by_count") or 0,
                "source": "openalex",
                "url": oa_url or (f"https://doi.org/{doi}" if doi else ""),
                "evidence_type": classify_evidence(title, journal),
                "open_access": bool(oa.get("is_oa")),
            })
        return papers
    except Exception as exc:
        log.warning("OpenAlex failed: %s", exc)
        return []


# ── Crossref ─────────────────────────────────────────────────────────────────
async def _search_crossref(query: str, client: httpx.AsyncClient, n: int = 5) -> list[dict]:
    params = {
        "query": query, "rows": n,
        "select": "DOI,title,author,published,container-title,abstract,is-referenced-by-count",
        "mailto": "research@medras.local",
        "filter": "type:journal-article",
    }
    try:
        r = await client.get(CROSSREF_BASE, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        papers = []
        for item in r.json().get("message", {}).get("items", []):
            doi   = item.get("DOI", "")
            titles = item.get("title") or []
            title = titles[0] if titles else ""
            if not title:
                continue
            journals = item.get("container-title") or []
            journal  = journals[0] if journals else ""
            pub  = item.get("published") or {}
            dp   = (pub.get("date-parts") or [[0]])[0]
            year = dp[0] if dp else 0
            authors = []
            for a in (item.get("author") or [])[:3]:
                fn = a.get("given", "")
                ln = a.get("family", "")
                if ln:
                    authors.append(f"{ln} {fn}".strip())
            abstract = re.sub(r"<[^>]+>", "", item.get("abstract") or "").strip()
            papers.append({
                "title": title.strip(), "abstract": abstract,
                "journal": journal, "year": year, "authors": authors,
                "doi": doi, "pmid": "",
                "citation_count": item.get("is-referenced-by-count") or 0,
                "source": "crossref",
                "url": f"https://doi.org/{doi}" if doi else "",
                "evidence_type": classify_evidence(title, journal),
                "open_access": False,
            })
        return papers
    except Exception as exc:
        log.warning("Crossref failed: %s", exc)
        return []


# ── CORE (Open Access) ────────────────────────────────────────────────────────
async def _search_core(query: str, client: httpx.AsyncClient, n: int = 4) -> list[dict]:
    core_key = os.environ.get("CORE_API_KEY", "")
    headers  = {"Authorization": f"Bearer {core_key}"} if core_key else {}
    params   = {"q": query, "limit": n, "fields": "title,authors,abstract,yearPublished,doi,downloadUrl,journals"}
    try:
        r = await client.get(CORE_BASE, params=params, headers=headers, timeout=_TIMEOUT)
        r.raise_for_status()
        papers = []
        for item in r.json().get("results", []):
            title = (item.get("title") or "").strip()
            if not title:
                continue
            doi   = item.get("doi", "") or ""
            doi   = doi.replace("https://doi.org/","").strip()
            jlist = item.get("journals") or []
            journal = jlist[0].get("title","") if jlist else ""
            papers.append({
                "title": title,
                "abstract": (item.get("abstract") or "").strip(),
                "journal": journal,
                "year": item.get("yearPublished") or 0,
                "authors": [(a.get("name","") if isinstance(a,dict) else str(a))
                            for a in (item.get("authors") or [])[:3]],
                "doi": doi, "pmid": "",
                "citation_count": 0,
                "source": "core",
                "url": item.get("downloadUrl","") or (f"https://doi.org/{doi}" if doi else ""),
                "evidence_type": classify_evidence(title, journal),
                "open_access": True,
            })
        return papers
    except Exception as exc:
        log.warning("CORE failed: %s", exc)
        return []


# ── medRxiv preprints ─────────────────────────────────────────────────────────
async def _search_medrxiv(query: str, client: httpx.AsyncClient, n: int = 3) -> list[dict]:
    cursor   = 0
    endpoint = f"{MEDRXIV_BASE}/{query}/{cursor}"
    try:
        r = await client.get(endpoint, timeout=_TIMEOUT)
        r.raise_for_status()
        papers = []
        for item in (r.json().get("collection") or [])[:n]:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            doi   = item.get("doi", "")
            papers.append({
                "title": title,
                "abstract": (item.get("abstract") or "").strip(),
                "journal": "medRxiv (preprint)",
                "year": int(str(item.get("date","0"))[:4]) if item.get("date") else 0,
                "authors": [item.get("authors","").split(";")[0].strip()],
                "doi": doi, "pmid": "",
                "citation_count": 0,
                "source": "medrxiv",
                "url": f"https://www.medrxiv.org/content/{doi}" if doi else "",
                "evidence_type": "observational",
                "open_access": True,
            })
        return papers
    except Exception as exc:
        log.warning("medRxiv failed: %s", exc)
        return []


# ── WHO IRIS ──────────────────────────────────────────────────────────────────
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
                "open_access": True,
            })
        return papers
    except Exception as exc:
        log.warning("WHO IRIS failed: %s", exc)
        return []


# ── PubMed Central (full-text open access) ───────────────────────────────────
async def _search_pmc(query: str, client: httpx.AsyncClient, n: int = 5) -> list[dict]:
    ncbi_key = os.environ.get("NCBI_API_KEY", "")
    params: dict[str, Any] = {"db": "pmc", "term": query, "retmax": n,
                               "retmode": "json", "sort": "relevance"}
    if ncbi_key:
        params["api_key"] = ncbi_key
    try:
        r = await client.get(NCBI_ESEARCH, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        sp: dict[str, Any] = {"db": "pmc", "id": ",".join(ids), "retmode": "json"}
        if ncbi_key:
            sp["api_key"] = ncbi_key
        sr = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            params=sp, timeout=_TIMEOUT)
        sr.raise_for_status()
        result = sr.json().get("result", {})
        papers = []
        for pmcid in ids:
            item = result.get(pmcid, {})
            title = (item.get("title") or "").strip()
            if not title:
                continue
            doi = pmid = ""
            for aid in item.get("articleids", []):
                if aid.get("idtype") == "doi":
                    doi = aid.get("value", "")
                elif aid.get("idtype") == "pubmed":
                    pmid = aid.get("value", "")
            journal   = item.get("source", "")
            year_str  = item.get("pubdate", "")
            year      = int(year_str[:4]) if year_str and len(year_str) >= 4 else 0
            authors   = [a.get("name", "") for a in item.get("authors", [])[:3]]
            papers.append({
                "title": title, "abstract": "",
                "journal": journal, "year": year, "authors": authors,
                "doi": doi, "pmid": pmid, "citation_count": 0,
                "source": "pmc",
                "url": f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/",
                "evidence_type": classify_evidence(title, journal),
                "open_access": True,
            })
        return papers
    except Exception as exc:
        log.warning("PMC failed: %s", exc)
        return []


# ── ClinicalTrials.gov ────────────────────────────────────────────────────────
async def _search_clinicaltrials(query: str, client: httpx.AsyncClient, n: int = 5) -> list[dict]:
    params = {"query.term": query, "pageSize": n, "format": "json"}
    try:
        r = await client.get("https://clinicaltrials.gov/api/v2/studies",
                             params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        papers = []
        for study in r.json().get("studies", []):
            ps      = study.get("protocolSection", {})
            id_mod  = ps.get("identificationModule", {})
            desc    = ps.get("descriptionModule", {})
            status  = ps.get("statusModule", {})
            design  = ps.get("designModule", {})
            nct_id  = id_mod.get("nctId", "")
            title   = (id_mod.get("briefTitle") or "").strip()
            if not title:
                continue
            abstract   = (desc.get("briefSummary") or "").strip()
            start_date = (status.get("startDateStruct") or {}).get("date", "")
            year       = int(start_date[:4]) if start_date and len(start_date) >= 4 else 0
            stype      = (design.get("studyType") or "").upper()
            ev_type    = "rct" if "INTERVENTIONAL" in stype else "observational"
            papers.append({
                "title": title, "abstract": abstract,
                "journal": "ClinicalTrials.gov", "year": year,
                "authors": [], "doi": "", "pmid": "",
                "citation_count": 0, "source": "clinicaltrials",
                "url": f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else "",
                "evidence_type": ev_type, "open_access": True,
            })
        return papers
    except Exception as exc:
        log.warning("ClinicalTrials.gov failed: %s", exc)
        return []


# ── DOAJ (Directory of Open Access Journals) ──────────────────────────────────
async def _search_doaj(query: str, client: httpx.AsyncClient, n: int = 5) -> list[dict]:
    encoded = urllib.parse.quote(query)
    url     = f"https://doaj.org/api/v2/search/articles/{encoded}"
    params  = {"pageSize": n, "page": 1}
    try:
        r = await client.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        papers = []
        for item in r.json().get("results", []):
            bib     = item.get("bibjson", {})
            title   = (bib.get("title") or "").strip()
            if not title:
                continue
            abstract  = (bib.get("abstract") or "").strip()
            j_info    = bib.get("journal", {})
            journal   = j_info.get("title", "") if isinstance(j_info, dict) else ""
            year_raw  = bib.get("year", "")
            year      = int(str(year_raw)) if str(year_raw).isdigit() else 0
            doi       = ""
            for ident in bib.get("identifier", []):
                if ident.get("type") == "doi":
                    doi = ident.get("id", "")
            authors   = [(a.get("name") or "") for a in bib.get("author", [])[:3]]
            links     = bib.get("link", [])
            paper_url = links[0].get("url", "") if links else ""
            if not paper_url and doi:
                paper_url = f"https://doi.org/{doi}"
            papers.append({
                "title": title, "abstract": abstract,
                "journal": journal, "year": year, "authors": authors,
                "doi": doi, "pmid": "", "citation_count": 0,
                "source": "doaj", "url": paper_url,
                "evidence_type": classify_evidence(title, journal),
                "open_access": True,
            })
        return papers
    except Exception as exc:
        log.warning("DOAJ failed: %s", exc)
        return []


# ── Lens.org ──────────────────────────────────────────────────────────────────
async def _search_lens(query: str, client: httpx.AsyncClient, n: int = 5) -> list[dict]:
    lens_key = os.environ.get("LENS_API_KEY", "")
    if not lens_key:
        return []
    headers = {"Authorization": f"Bearer {lens_key}", "Content-Type": "application/json"}
    payload = {
        "query": {
            "bool": {
                "should": [
                    {"match": {"title": query}},
                    {"match": {"abstract": query}},
                ],
                "minimum_should_match": 1,
            }
        },
        "size": n,
        "sort": [{"scholarly_citations_count": "desc"}],
        "include": ["title", "authors", "abstract", "year_published",
                    "source", "doi", "pmid", "scholarly_citations_count", "open_access"],
    }
    try:
        r = await client.post("https://api.lens.org/scholarly/search",
                              headers=headers, content=json.dumps(payload),
                              timeout=_TIMEOUT)
        r.raise_for_status()
        papers = []
        for item in r.json().get("data", []):
            title   = (item.get("title") or "").strip()
            if not title:
                continue
            doi     = (item.get("doi") or "").replace("https://doi.org/", "").strip()
            pmid    = str(item.get("pmid") or "")
            src     = item.get("source") or {}
            journal = (src.get("title") or "") if isinstance(src, dict) else ""
            authors = [(a.get("display_name") or "")
                       for a in (item.get("authors") or [])[:3]
                       if isinstance(a, dict)]
            papers.append({
                "title": title,
                "abstract": (item.get("abstract") or "").strip(),
                "journal": journal,
                "year": item.get("year_published") or 0,
                "authors": authors, "doi": doi, "pmid": pmid,
                "citation_count": item.get("scholarly_citations_count") or 0,
                "source": "lens",
                "url": f"https://doi.org/{doi}" if doi else "",
                "evidence_type": classify_evidence(title, journal),
                "open_access": bool(item.get("open_access")),
            })
        return papers
    except Exception as exc:
        log.warning("Lens.org failed: %s", exc)
        return []


# ── IEEE Xplore ───────────────────────────────────────────────────────────────
async def _search_ieee(query: str, client: httpx.AsyncClient, n: int = 4) -> list[dict]:
    api_key = os.environ.get("IEEE_API_KEY", "")
    if not api_key:
        return []
    params = {"querytext": query, "max_records": n, "apikey": api_key,
              "format": "json", "start_record": 1}
    try:
        r = await client.get("https://ieeexplore.ieee.org/rest/search",
                             params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        papers = []
        for item in r.json().get("articles", []):
            title = (item.get("title") or "").strip()
            if not title:
                continue
            doi   = item.get("doi", "")
            pub   = item.get("publication_title", "")
            papers.append({
                "title": title,
                "abstract": (item.get("abstract") or "").strip(),
                "journal": pub,
                "year": item.get("publication_year") or 0,
                "authors": [(a.get("full_name") or "")
                            for a in (item.get("authors", {}).get("authors") or [])[:3]],
                "doi": doi, "pmid": "",
                "citation_count": 0,
                "source": "ieee",
                "url": item.get("html_url") or (f"https://doi.org/{doi}" if doi else ""),
                "evidence_type": classify_evidence(title, pub),
                "open_access": item.get("access_type") == "OPEN_ACCESS",
            })
        return papers
    except Exception as exc:
        log.warning("IEEE Xplore failed: %s", exc)
        return []


# ── Web of Science (Clarivate WoS Starter) ────────────────────────────────────
async def _search_wos(query: str, client: httpx.AsyncClient, n: int = 5) -> list[dict]:
    wos_key = os.environ.get("WOS_API_KEY", "")
    if not wos_key:
        return []
    headers = {"X-ApiKey": wos_key, "Accept": "application/json"}
    params  = {"q": f"TS=({query})", "db": "WOK", "limit": n, "page": 1}
    try:
        r = await client.get(
            "https://api.clarivate.com/apis/wos-starter/v1/documents",
            params=params, headers=headers, timeout=_TIMEOUT)
        r.raise_for_status()
        papers = []
        for item in r.json().get("hits", []):
            title = ""
            for t in (item.get("title") or {}).get("value", []):
                if t:
                    title = t.strip()
                    break
            if not title:
                continue
            src       = item.get("source") or {}
            journal   = src.get("sourceTitle", "")
            year_raw  = src.get("publishYear")
            year      = int(year_raw) if year_raw else 0
            doi       = ""
            for ident in (item.get("identifiers") or {}).get("doi", []):
                doi = ident.strip()
                break
            authors = [(a.get("displayName") or "")
                       for a in (item.get("authors") or {}).get("authors", [])[:3]]
            cites = (item.get("citations") or {}).get("timesCited", 0) or 0
            papers.append({
                "title": title, "abstract": "",
                "journal": journal, "year": year, "authors": authors,
                "doi": doi, "pmid": "",
                "citation_count": cites,
                "source": "wos",
                "url": f"https://doi.org/{doi}" if doi else "",
                "evidence_type": classify_evidence(title, journal),
                "open_access": False,
            })
        return papers
    except Exception as exc:
        log.warning("Web of Science failed: %s", exc)
        return []


# ── Scopus (Elsevier) ────────────────────────────────────────────────────────
async def _search_scopus(query: str, client: httpx.AsyncClient, n: int = 6) -> list[dict]:
    api_key = os.environ.get("SCOPUS_API_KEY", "")
    if not api_key:
        return []
    headers = {
        "X-ELS-APIKey": api_key,
        "Accept": "application/json",
    }
    params = {
        "query": query,
        "count": n,
        "field": "dc:title,dc:description,prism:publicationName,prism:coverDate,"
                 "dc:creator,prism:doi,eid,citedby-count,openaccess",
        "sort": "citedby-count",
    }
    try:
        r = await client.get(SCOPUS_BASE, params=params, headers=headers, timeout=_TIMEOUT)
        r.raise_for_status()
        entries = (r.json()
                   .get("search-results", {})
                   .get("entry", []))
        papers = []
        for item in entries:
            title = (item.get("dc:title") or "").strip()
            if not title:
                continue
            doi   = (item.get("prism:doi") or "").strip()
            eid   = (item.get("eid") or "").strip()
            date  = item.get("prism:coverDate") or ""
            year  = int(date[:4]) if date and len(date) >= 4 else 0
            journal = (item.get("prism:publicationName") or "").strip()
            creator = (item.get("dc:creator") or "").strip()
            authors = [creator] if creator else []
            cites   = int(item.get("citedby-count") or 0)
            oa      = str(item.get("openaccess") or "0") == "1"
            url = (f"https://doi.org/{doi}" if doi
                   else f"https://www.scopus.com/record/display.uri?eid={eid}" if eid
                   else "")
            papers.append({
                "title": title,
                "abstract": (item.get("dc:description") or "").strip(),
                "journal": journal,
                "year": year,
                "authors": authors,
                "doi": doi,
                "pmid": "",
                "citation_count": cites,
                "source": "scopus",
                "url": url,
                "evidence_type": classify_evidence(title, journal),
                "open_access": oa,
            })
        return papers
    except Exception as exc:
        log.warning("Scopus failed: %s", exc)
        return []


# ── Dedup + rank ──────────────────────────────────────────────────────────────
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
    recency = max(0.0, 1.0 - 0.07 * (_CURRENT_YEAR - year)) if year else 0.0
    base    = 0.55 * recency + 0.35 * min(math.log1p(cites) / 10.0, 1.0)
    etype   = p.get("evidence_type", "")
    if etype == "systematic_review":
        base += 0.40
    elif etype == "guideline":
        base += 0.20
    elif etype == "rct":
        base += 0.10
    if p.get("open_access"):
        base += 0.03
    return base


SOURCE_LABELS = {
    "pubmed":           "PubMed",
    "cochrane":         "Cochrane",
    "europe_pmc":       "Europe PMC",
    "semantic_scholar": "Semantic Scholar",
    "openalex":         "OpenAlex",
    "who_iris":         "WHO IRIS",
    "crossref":         "Crossref",
    "core":             "CORE",
    "medrxiv":          "medRxiv",
    "pmc":              "PubMed Central",
    "clinicaltrials":   "ClinicalTrials.gov",
    "doaj":             "DOAJ",
    "lens":             "Lens.org",
    "ieee":             "IEEE Xplore",
    "wos":              "Web of Science",
    "scopus":           "Scopus",
}


async def multi_source_search(query: str, top_n: int = 10) -> dict:
    hdrs = {"User-Agent": _UA}
    async with httpx.AsyncClient(headers=hdrs, follow_redirects=True) as client:
        results = await asyncio.gather(
            _search_pubmed(query, client),
            _search_cochrane(query, client),
            _search_europe_pmc(query, client),
            _search_semantic_scholar(query, client),
            _search_openalex(query, client),
            _search_who_iris(query, client),
            _search_crossref(query, client),
            _search_core(query, client),
            _search_medrxiv(query, client),
            _search_pmc(query, client),
            _search_clinicaltrials(query, client),
            _search_doaj(query, client),
            _search_lens(query, client),
            _search_ieee(query, client),
            _search_wos(query, client),
            _search_scopus(query, client),
            return_exceptions=True,
        )
    labels = ["pubmed", "cochrane", "europe_pmc", "semantic_scholar",
              "openalex", "who_iris", "crossref", "core", "medrxiv",
              "pmc", "clinicaltrials", "doaj", "lens", "ieee", "wos", "scopus"]
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
    return {
        "papers": ranked,
        "sources_searched": sorted(sources_hit),
        "sources_hit": len(sources_hit),
        "total_found": len(deduped),
    }
