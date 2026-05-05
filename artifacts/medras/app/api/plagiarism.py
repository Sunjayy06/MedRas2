"""Plagiarism & AI-reduction module — backend routes.

Provides three endpoints under ``/api/plagiarism``:

  * ``POST /check``    — score originality + AI likelihood from raw text
  * ``POST /check-file`` — same, but accepts a PDF/DOCX/TXT upload
  * ``POST /reduce``   — rewrite text to read more human / less templated

All endpoints return JSON. The actual analysis is delegated to
``app.services.plagiarism_analyzer``, which wraps OpenAI and Gemini.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app.core.limiter import limiter
from app.core.logging import get_logger
from app.services import plagiarism_analyzer

log = get_logger(__name__)

router = APIRouter(prefix="/plagiarism", tags=["plagiarism"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


# Hard cap on how much text we'll send to the LLM in a single call. A
# typical academic paragraph is ~150 words ≈ 1000 chars; 30 KB is roughly
# 5000 words which is plenty for a thesis chapter section. Larger files
# should be analysed in chunks (a future enhancement).
MAX_TEXT_CHARS = 30_000

# Hard cap on file uploads to keep memory bounded. PDFs blow up quickly.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB


class CheckRequest(BaseModel):
    text: str = Field(..., min_length=1)
    provider: Literal["openai", "gemini", "auto"] = "auto"


class ReduceRequest(BaseModel):
    text: str = Field(..., min_length=1)
    provider: Literal["openai", "gemini", "auto"] = "auto"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/check")
@limiter.limit("20/minute")
async def check_text(request: Request, payload: CheckRequest) -> dict:
    """Score originality + AI likelihood for pasted text."""
    text = payload.text.strip()
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Text is too long ({len(text)} chars). Maximum is {MAX_TEXT_CHARS}.",
        )
    try:
        result = plagiarism_analyzer.check_originality(text, provider=payload.provider)
    except RuntimeError as exc:
        # Missing API key — surface as 503 so the UI can show a helpful note.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("plagiarism check failed")
        raise HTTPException(status_code=502, detail=f"Analysis failed: {exc}") from exc
    return result


@router.post("/check-file")
@limiter.limit("10/minute")
async def check_file(
    request: Request,
    file: UploadFile = File(...),
    provider: str = Form("auto"),
) -> dict:
    """Same as /check but accepts a PDF/DOCX/TXT file upload."""
    if provider not in ("openai", "gemini", "auto"):
        provider = "auto"
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content)} bytes). Maximum is {MAX_UPLOAD_BYTES} bytes.",
        )

    try:
        text = plagiarism_analyzer.extract_text_from_upload(file.filename or "", content)
    except Exception as exc:  # noqa: BLE001
        log.exception("plagiarism file extract failed")
        raise HTTPException(status_code=400, detail=f"Could not read file: {exc}") from exc

    text = (text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="No readable text found in the file.")
    if len(text) > MAX_TEXT_CHARS:
        # Trim rather than reject — the UI will tell the user we analysed the
        # first N characters. Truncating gives a useful answer instead of an
        # error for a long PDF.
        text = text[:MAX_TEXT_CHARS]

    try:
        result = plagiarism_analyzer.check_originality(text, provider=provider)  # type: ignore[arg-type]
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("plagiarism file check failed")
        raise HTTPException(status_code=502, detail=f"Analysis failed: {exc}") from exc

    result["filename"] = file.filename
    result["analysed_chars"] = len(text)
    return result


@router.post("/reduce")
@limiter.limit("10/minute")
async def reduce_text(request: Request, payload: ReduceRequest) -> dict:
    """Rewrite text to read more human and less templated."""
    text = payload.text.strip()
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Text is too long ({len(text)} chars). Maximum is {MAX_TEXT_CHARS}.",
        )
    try:
        result = plagiarism_analyzer.reduce_plagiarism(text, provider=payload.provider)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("plagiarism reduce failed")
        raise HTTPException(status_code=502, detail=f"Rewrite failed: {exc}") from exc
    return result
