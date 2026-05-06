"""Proposal Writing Module — Step 6 (Generate) API.

* ``POST /api/proposal/generate-rag-sections`` — given the user's intake
  state, run the RAG pipeline and return Background / Literature Review /
  Rationale grounded in real verified papers, plus the source list.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.services.proposal_generator import GeneratorError, generate_rag_sections

router = APIRouter(prefix="/proposal", tags=["proposal"])


@router.post("/generate-rag-sections")
async def generate_rag_sections_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Body: ``{intake: {role, format, topic, language?}}`` (or fields at the top
    level). Returns ``{sections, sources, all_retrieved, domain, databases_meta}``.
    """
    intake = payload.get("intake") if isinstance(payload, dict) else None
    if not isinstance(intake, dict):
        intake = payload if isinstance(payload, dict) else {}
    try:
        return await generate_rag_sections(intake)
    except GeneratorError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
