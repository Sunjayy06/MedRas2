"""Plagiarism & AI-reduction module — backend routes.

Provides the following endpoints under ``/api/plagiarism``:

  * ``POST /check``        — score originality + AI likelihood from raw text
  * ``POST /check-file``   — same, but accepts a PDF/DOCX/TXT upload
  * ``POST /reduce``       — rewrite text to read more human / less templated
  * ``POST /analyze-file`` — extract text from a PDF/DOCX/TXT, detect IMRaD
                             sections and protected technical terms, return
                             the breakdown plus the extracted text so the
                             frontend can run /check or /reduce afterwards
                             without re-uploading the file

All endpoints return JSON. The actual analysis is delegated to
``app.services.plagiarism_analyzer`` (LLM calls) and
``app.services.text_analyzer`` (regex-based section + term detection).
"""

from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app.core.limiter import limiter
from app.core.logging import get_logger
from app.services import plagiarism_analyzer, text_analyzer

log = get_logger(__name__)

router = APIRouter(prefix="/plagiarism", tags=["plagiarism"])


# ---------------------------------------------------------------------------
# Request models & limits
# ---------------------------------------------------------------------------

# Hard cap on how much text we'll send to the LLM in a single call.
# A typical academic paragraph is ~150 words ≈ 1000 chars; 30 KB is roughly
# 5000 words. Larger inputs are truncated client-side OR analysed
# section-by-section using /analyze-file first.
MAX_TEXT_CHARS = 30_000

# Hard cap on uploaded file size. The user explicitly asked for 100 MB. We
# read the upload in 64 KB chunks and bail as soon as the running total
# exceeds the cap, so an attacker can't lie about Content-Length.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB

# How much extracted text we'll accept downstream of an upload. Even if a
# 500-page PDF extracts to 2 MB of plain text, we won't analyse all of it —
# section detection runs on the full body (cheap), but the LLM-bound text
# is capped at ANALYZE_TEXT_CHARS.
ANALYZE_TEXT_CHARS = 1_000_000  # 1 MB of UTF-8 text — plenty for a thesis


class CheckRequest(BaseModel):
    text: str = Field(..., min_length=1)
    provider: Literal["openai", "gemini", "auto"] = "auto"


class PipelineSectionIn(BaseModel):
    """One section to feed into the 3-stage rewrite pipeline.

    The label drives References-skip detection (sections labelled
    "References", "Bibliography", "Works Cited", "Literature Cited" are
    kept verbatim and not rewritten).
    """
    label: str = Field(..., min_length=1, max_length=200)
    text: str = Field(..., min_length=1)


class ReduceRequest(BaseModel):
    text: str = Field(..., min_length=1)
    provider: Literal["openai", "gemini", "auto"] = "auto"
    # Strings that MUST appear unchanged in the rewrite. Usually populated
    # from the output of /analyze-file's protected_terms list.
    protected_terms: Optional[List[str]] = None
    # If supplied, /reduce runs the 3-stage GPT-4o → Gemini → GPT-4o
    # pipeline per section instead of the legacy single-shot rewrite.
    # ``text`` is still required (used for size validation and as the
    # legacy fallback if the pipeline raises).
    sections: Optional[List[PipelineSectionIn]] = None
    # Force the pipeline path even without explicit sections (treats the
    # full text as one body section). Useful for the paste-text flow
    # when the user wants the higher-quality multi-stage rewrite.
    pipeline: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _read_with_cap(file: UploadFile, cap: int) -> bytes:
    """Read an UploadFile in chunks, raising 413 as soon as ``cap`` is hit.

    ``await file.read()`` would happily slurp a 200 MB body into memory
    before any size check runs. Reading in 64 KB chunks lets us reject
    abusive uploads early with a clear error.
    """
    chunks: list[bytes] = []
    total = 0
    chunk_size = 64 * 1024
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds {cap // (1024 * 1024)} MB. Got at least {total} bytes.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _normalise_provider(value: str | None) -> Literal["openai", "gemini", "auto"]:
    if value not in ("openai", "gemini", "auto"):
        return "auto"
    return value  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/check")
@limiter.limit("20/minute")
async def check_text(request: Request, payload: CheckRequest) -> dict:
    """Score originality + AI likelihood for pasted or pre-extracted text."""
    text = payload.text.strip()
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Text is too long ({len(text):,} chars). Maximum is {MAX_TEXT_CHARS:,}.",
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
    """Same as /check but accepts a PDF/DOCX/TXT file upload (≤100 MB)."""
    provider_choice = _normalise_provider(provider)
    content = await _read_with_cap(file, MAX_UPLOAD_BYTES)
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        text = plagiarism_analyzer.extract_text_from_upload(file.filename or "", content)
    except Exception as exc:  # noqa: BLE001
        log.exception("plagiarism file extract failed")
        raise HTTPException(status_code=400, detail=f"Could not read file: {exc}") from exc

    text = (text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="No readable text found in the file.")
    truncated = False
    if len(text) > MAX_TEXT_CHARS:
        # Trim rather than reject — the UI tells the user we analysed the
        # first N characters. Truncating gives a useful answer instead of
        # an error for a long PDF.
        text = text[:MAX_TEXT_CHARS]
        truncated = True

    try:
        result = plagiarism_analyzer.check_originality(text, provider=provider_choice)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("plagiarism file check failed")
        raise HTTPException(status_code=502, detail=f"Analysis failed: {exc}") from exc

    result["filename"] = file.filename
    result["analysed_chars"] = len(text)
    result["truncated"] = truncated
    return result


@router.post("/analyze-file")
@limiter.limit("10/minute")
async def analyze_file(
    request: Request,
    file: UploadFile = File(...),
) -> dict:
    """Extract text from an upload and return the IMRaD breakdown.

    No LLM is called here — this endpoint is fast and cheap, and is the
    "step 1" the UI runs after a user picks a file. The response includes:

      * total word & character counts
      * detected sections with word counts and short previews
      * detected protected terms (drug names, p-values, citations, etc.)
      * the extracted plain text (capped at ANALYZE_TEXT_CHARS) so the UI
        can pass it back to /check or /reduce without re-uploading
    """
    content = await _read_with_cap(file, MAX_UPLOAD_BYTES)
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    name = (file.filename or "").lower()
    if not (name.endswith(".pdf") or name.endswith(".docx") or name.endswith(".txt") or name.endswith(".md")):
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Upload a .pdf, .docx, .txt, or .md file.",
        )

    try:
        text = plagiarism_analyzer.extract_text_from_upload(file.filename or "", content)
    except Exception as exc:  # noqa: BLE001
        log.exception("plagiarism analyze-file extract failed")
        raise HTTPException(status_code=400, detail=f"Could not read file: {exc}") from exc

    text = (text or "").strip()
    if not text:
        raise HTTPException(
            status_code=400,
            detail="No readable text found in the file. Scanned PDFs without OCR cannot be analysed.",
        )

    truncated = False
    if len(text) > ANALYZE_TEXT_CHARS:
        text = text[:ANALYZE_TEXT_CHARS]
        truncated = True

    try:
        breakdown = text_analyzer.analyze_document(text)
    except Exception as exc:  # noqa: BLE001
        log.exception("plagiarism analyze-file detection failed")
        raise HTTPException(status_code=500, detail=f"Document analysis failed: {exc}") from exc

    return {
        "filename": file.filename,
        "size_bytes": len(content),
        "extracted_chars": len(text),
        "truncated": truncated,
        "extracted_text": text,
        **breakdown,
    }


@router.post("/reduce")
@limiter.limit("10/minute")
async def reduce_text(request: Request, payload: ReduceRequest) -> dict:
    """Rewrite text to read more human and less templated.

    Two paths:

    1. **Pipeline path** — taken when ``sections`` is supplied OR
       ``pipeline=true``. Runs each section through 3 LLM stages:
       paraphrase (gpt-4o) → humanise (gemini-2.5-flash) → polish
       (gpt-4o). Sections labelled References / Bibliography / Works
       Cited / Literature Cited are skipped entirely and kept verbatim
       in the combined output. The ``provider`` field is ignored on this
       path — each stage has a fixed primary with the other provider as
       its automatic fallback.

    2. **Legacy single-shot path** — original behaviour. Used when
       neither ``sections`` nor ``pipeline`` is set.

    In both paths, ``protected_terms`` substrings are passed to the LLM
    as hard "do not change" constraints AND verified post-hoc.
    """
    text = payload.text.strip()
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Text is too long ({len(text):,} chars). Maximum is {MAX_TEXT_CHARS:,}.",
        )

    use_pipeline = bool(payload.sections) or payload.pipeline
    if use_pipeline:
        sections_payload: list[dict[str, str]]
        if payload.sections:
            total = sum(len(s.text) for s in payload.sections)
            if total > MAX_TEXT_CHARS:
                raise HTTPException(
                    status_code=413,
                    detail=f"Combined sections are too long ({total:,} chars). Maximum is {MAX_TEXT_CHARS:,}.",
                )
            sections_payload = [{"label": s.label, "text": s.text} for s in payload.sections]
        else:
            sections_payload = [{"label": "Body", "text": text}]
        try:
            result = plagiarism_analyzer.rewrite_pipeline(
                sections_payload,
                protected_terms=payload.protected_terms,
            )
        except plagiarism_analyzer.ProviderQuotaExhausted as exc:
            # Both AI providers are out of quota. Surface a clear,
            # actionable 503 the UI can show instead of a 502 stack trace.
            raise HTTPException(
                status_code=503,
                detail=(
                    "Both AI providers are out of quota right now. "
                    "OpenAI returned insufficient_quota (billing) and Gemini "
                    "hit its free-tier daily request limit. Please try again "
                    "tomorrow, or top up one of the provider accounts."
                ),
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            log.exception("plagiarism rewrite_pipeline failed")
            raise HTTPException(status_code=502, detail=f"Rewrite pipeline failed: {exc}") from exc
        return result

    try:
        result = plagiarism_analyzer.reduce_plagiarism(
            text,
            provider=payload.provider,
            protected_terms=payload.protected_terms,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("plagiarism reduce failed")
        raise HTTPException(status_code=502, detail=f"Rewrite failed: {exc}") from exc
    return result
