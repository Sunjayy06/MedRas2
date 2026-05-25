"""Proposal Writing Module API.

* ``POST /api/proposal/generate-rag-sections`` — Step 6: run RAG pipeline +
  Gemini and return the seven drafted sections + cited sources.
* ``POST /api/proposal/export/docx``           — Step 8: download Word doc.
* ``POST /api/proposal/export/pdf``            — Step 8: download PDF.
* ``POST /api/proposal/export/zip``            — Step 8: download both as a zip.
* ``POST /api/proposal/export/plaintext``      — Step 8: returns the proposal
  as JSON ``{text}`` for the Plagiarism Checker handoff.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.services.proposal_export import (
    build_docx, build_pdf, build_plaintext, build_zip,
)
from app.services.proposal_generator import GeneratorError, generate_rag_sections

log = logging.getLogger(__name__)
router = APIRouter(prefix="/proposal", tags=["proposal"])


@router.post("/generate-rag-sections")
async def generate_rag_sections_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Body: ``{intake: {role, format, topic, language?}}`` (or fields at the
    top level). Returns ``{sections, sources, all_retrieved, domain,
    databases_meta}`` with all seven sections.
    """
    intake = payload.get("intake") if isinstance(payload, dict) else None
    if not isinstance(intake, dict):
        intake = payload if isinstance(payload, dict) else {}
    try:
        return await generate_rag_sections(intake)
    except GeneratorError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Step 8 — Export endpoints
# ---------------------------------------------------------------------------
def _safe_filename(stem: str, ext: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", stem or "proposal")[:60] or "proposal"
    return f"{base}.{ext}"


def _validate_export_payload(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload — expected JSON object.")
    sections = payload.get("sections")
    if not isinstance(sections, dict) or not any((v or "").strip() for v in sections.values()):
        raise HTTPException(status_code=400,
            detail="No generated sections found — please run Step 6 first.")
    return payload


@router.post("/export/docx")
async def export_docx(payload: Dict[str, Any]) -> Response:
    payload = _validate_export_payload(payload)
    try:
        data = await asyncio.to_thread(build_docx, payload)
    except Exception as exc:                                  # noqa: BLE001
        log.exception("docx export failed")
        raise HTTPException(status_code=500, detail=f"Word export failed: {exc}")
    fname = _safe_filename((payload.get("title_meta") or {}).get("study_title")
                           or (payload.get("intake") or {}).get("topic") or "proposal", "docx")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/export/pdf")
async def export_pdf(payload: Dict[str, Any]) -> Response:
    payload = _validate_export_payload(payload)
    try:
        data = await asyncio.to_thread(build_pdf, payload)
    except Exception as exc:                                  # noqa: BLE001
        log.exception("pdf export failed")
        raise HTTPException(status_code=500, detail=f"PDF export failed: {exc}")
    fname = _safe_filename((payload.get("title_meta") or {}).get("study_title")
                           or (payload.get("intake") or {}).get("topic") or "proposal", "pdf")
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/export/zip")
async def export_zip(payload: Dict[str, Any]) -> Response:
    payload = _validate_export_payload(payload)
    try:
        data = await asyncio.to_thread(build_zip, payload)
    except Exception as exc:                                  # noqa: BLE001
        log.exception("zip export failed")
        raise HTTPException(status_code=500, detail=f"Bundle export failed: {exc}")
    fname = _safe_filename((payload.get("title_meta") or {}).get("study_title")
                           or (payload.get("intake") or {}).get("topic") or "proposal", "zip")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/export/plaintext")
async def export_plaintext(payload: Dict[str, Any]) -> Dict[str, str]:
    payload = _validate_export_payload(payload)
    try:
        return {"text": build_plaintext(payload)}
    except Exception as exc:                                  # noqa: BLE001
        log.exception("plaintext export failed")
        raise HTTPException(status_code=500, detail=f"Plaintext export failed: {exc}")
