"""Thesis Writing Module API.

Endpoints
---------
* ``GET  /api/thesis/spine``                 — chapter spine + default rules
* ``POST /api/thesis/parse-guidelines``      — multipart upload of uni rules PDF
* ``POST /api/thesis/references/verify-dois``— bulk DOI verification
* ``POST /api/thesis/references/search``     — distilled RAG search
* ``POST /api/thesis/draft-section``         — RAG-grounded fresh section draft
* ``POST /api/thesis/improve-section``       — sentence-level inline-diff suggestions
* ``POST /api/thesis/compliance-check``      — pre-flight checks on full state
* ``POST /api/thesis/extract-text``          — extract text from uploaded stats / data file
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile

from app.core.limiter import limiter
from app.services import (
    thesis_compliance, thesis_export, thesis_formats, thesis_guidelines_parser,
    thesis_reference_library, thesis_section_writer,
)
from app.services.proposal_generator import GeneratorError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/thesis", tags=["thesis"])

MAX_UPLOAD_BYTES = 30 * 1024 * 1024


# ---------------------------------------------------------------------------
# Spine + defaults
# ---------------------------------------------------------------------------

@router.get("/spine")
async def get_spine(
    mode: str = "thesis",
    article_type: str = "",
    design: str = "",
    tier: str = "",
    citation_style: str = "",
) -> Dict[str, Any]:
    """Return the right chapter spine for the writer.

    * ``mode=thesis`` (default) → canonical Indian MD/DNB/PhD spine.
    * ``mode=article`` → the spine for the matching reporting checklist
      (CARE / CONSORT / STROBE / PRISMA / MOOSE / COREQ / IMRaD /
      narrative), with per-section word budgets sized from the journal
      tier (``t1``..``t4``, default ``t3``).
    """
    if (mode or "").strip().lower() == "article":
        spine = thesis_formats.get_article_spine(article_type, design)
        tier_targets = thesis_formats.get_tier_targets(tier)
        spine = thesis_formats.apply_tier_to_spine(spine, tier_targets)
        rules = dict(thesis_formats.DEFAULT_RULES)
        rules["citation_style"] = (
            (citation_style or "").strip().lower()
            or tier_targets.get("default_citation_style", "vancouver")
        )
        rules["min_references"] = tier_targets.get("ref_min") or rules["min_references"]
        if tier_targets.get("ref_max"):
            rules["max_references"] = tier_targets["ref_max"]
        rules["abstract_words"] = tier_targets.get("abstract_words")
        rules["abstract_structured"] = tier_targets.get("abstract_structured")
        rules["max_pages"] = None  # articles aren't page-capped, they're word-capped
        return {
            "spine":     spine,
            "rules":     rules,
            "tier":      tier_targets,
            "checklist": thesis_formats.resolve_checklist(article_type, design),
            "mode":      "article",
            "version":   "v2-article-tier-aware",
        }
    return {
        "spine":   thesis_formats.CHAPTER_SPINE,
        "rules":   thesis_formats.DEFAULT_RULES,
        "mode":    "thesis",
        "version": "v1-indian-md-dnb-phd",
    }


# ---------------------------------------------------------------------------
# Guidelines parser
# ---------------------------------------------------------------------------

@router.post("/parse-guidelines")
@limiter.limit("10/minute")
async def parse_guidelines(request: Request, file: UploadFile = File(...)) -> Dict[str, Any]:
    """Upload a university thesis-guidelines PDF / DOCX / TXT and get back
    the rules autofilled from it (plus any rules that fell back to defaults).
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (>30 MB).")
    try:
        return thesis_guidelines_parser.parse_guidelines(file.filename or "", data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Reference library
# ---------------------------------------------------------------------------

@router.post("/references/verify-dois")
@limiter.limit("20/minute")
async def verify_dois(request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Body: ``{dois: ["10.x/y", ...]}``  →  per-DOI verified record or
    ``{verified: false, error: ...}``."""
    dois: List[str] = payload.get("dois") or []
    if not isinstance(dois, list):
        raise HTTPException(status_code=400, detail="`dois` must be a list.")
    dois = [str(d).strip() for d in dois if str(d).strip()][:60]
    out = await thesis_reference_library.verify_dois(dois)
    # Attach a one-line distilled summary for verified records
    for r in out:
        if r.get("verified"):
            r["summary"] = thesis_reference_library.summarise(r)
    return {"records": out}


@router.post("/references/extract-dois")
@limiter.limit("20/minute")
async def extract_dois(request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Body: ``{text: "..."}``  →  ``{dois: [...]}``. Used after the user
    pastes text or uploads a PDF whose text the client has extracted."""
    text = (payload.get("text") or "")
    if not isinstance(text, str):
        raise HTTPException(status_code=400, detail="`text` must be a string.")
    return {"dois": thesis_reference_library.extract_dois(text[:200_000])}


@router.post("/references/search")
@limiter.limit("20/minute")
async def references_search(request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Body: ``{topic, domain_hint?, limit?}``."""
    topic = (payload.get("topic") or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="`topic` is required.")
    domain_hint = payload.get("domain_hint")
    limit = max(5, min(int(payload.get("limit") or 20), 40))
    res = await thesis_reference_library.search(topic, domain_hint=domain_hint, limit=limit)
    # Attach distilled summaries
    for r in res.get("records", []):
        r["summary"] = thesis_reference_library.summarise(r)
    return res


# ---------------------------------------------------------------------------
# Section writer
# ---------------------------------------------------------------------------

@router.post("/draft-section")
@limiter.limit("8/minute")
async def draft_section(request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Body: ``{chapter_id, topic, citation_style?, locked_numbers?,
    extra_context?, domain_hint?}``."""
    try:
        result = await thesis_section_writer.draft_section(
            chapter_id=payload.get("chapter_id") or "",
            topic=payload.get("topic") or "",
            citation_style=(payload.get("citation_style") or "vancouver"),
            locked_numbers=payload.get("locked_numbers") or {},
            extra_context=payload.get("extra_context"),
            domain_hint=payload.get("domain_hint"),
        )
    except GeneratorError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.post("/improve-section")
@limiter.limit("12/minute")
async def improve_section(request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Body: ``{chapter_id, topic, current_text, citation_style?,
    locked_numbers?, domain_hint?}``."""
    try:
        result = await thesis_section_writer.improve_section(
            chapter_id=payload.get("chapter_id") or "",
            topic=payload.get("topic") or "",
            current_text=payload.get("current_text") or "",
            citation_style=(payload.get("citation_style") or "vancouver"),
            locked_numbers=payload.get("locked_numbers") or {},
            domain_hint=payload.get("domain_hint"),
        )
    except GeneratorError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------

@router.post("/compliance-check")
async def compliance_check(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Body: full thesis state JSON. Returns ``{items, summary}``."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object.")
    return thesis_compliance.check(payload)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _export_filename(payload: Dict[str, Any], ext: str) -> str:
    state = payload.get("state") or {}
    tm = payload.get("title_meta") or state.get("title_meta") or {}
    setup = state.get("setup") or {}
    name = (tm.get("study_title") or setup.get("topic") or "thesis").strip()
    import re as _re
    safe = _re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:60] or "thesis"
    return f"{safe}.{ext}"


@router.post("/export/docx")
@limiter.limit("12/minute")
async def export_docx(request: Request, payload: Dict[str, Any]) -> Response:
    """Body: ``{state, title_meta?, consent?, assets?}``. Returns DOCX bytes."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object.")
    try:
        data = thesis_export.build_docx(payload)
    except Exception as exc:                                      # noqa: BLE001
        log.exception("thesis docx export failed")
        raise HTTPException(status_code=500, detail=f"Word export failed: {exc}")
    fname = _export_filename(payload, "docx")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/export/pdf")
@limiter.limit("12/minute")
async def export_pdf(request: Request, payload: Dict[str, Any]) -> Response:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object.")
    try:
        data = thesis_export.build_pdf(payload)
    except Exception as exc:                                      # noqa: BLE001
        log.exception("thesis pdf export failed")
        raise HTTPException(status_code=500, detail=f"PDF export failed: {exc}")
    fname = _export_filename(payload, "pdf")
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/export/zip")
@limiter.limit("8/minute")
async def export_zip(request: Request, payload: Dict[str, Any]) -> Response:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object.")
    try:
        data = thesis_export.build_zip(payload)
    except Exception as exc:                                      # noqa: BLE001
        log.exception("thesis zip export failed")
        raise HTTPException(status_code=500, detail=f"Bundle export failed: {exc}")
    fname = _export_filename(payload, "zip")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/export/plaintext")
@limiter.limit("20/minute")
async def export_plaintext(request: Request, payload: Dict[str, Any]) -> Dict[str, str]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object.")
    try:
        return {"text": thesis_export.build_plaintext(payload)}
    except Exception as exc:                                      # noqa: BLE001
        log.exception("thesis plaintext export failed")
        raise HTTPException(status_code=500, detail=f"Plaintext export failed: {exc}")
