"""Proposal Writing Module — Step 4 (Outline) API.

Three endpoints:

* ``POST /api/outline/extract``         — Multi-file upload, returns text
  classified into the user's chosen section list.
* ``POST /api/outline/extract-section`` — Single file upload, returns the
  extracted text as one blob (for the per-section "upload doc for this
  section" button).
* ``POST /api/outline/generate``        — Generate a missing section based on
  what the user has already filled in elsewhere.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.services import outline_extractor, plagiarism_analyzer, section_classifier

router = APIRouter(prefix="/outline", tags=["outline"])


# ---------------------------------------------------------------------------
# Caps (mirror the plagiarism module so behaviour is consistent)
# ---------------------------------------------------------------------------
MAX_FILE_BYTES = 100 * 1024 * 1024     # 100 MB per file
MAX_FILES_PER_BATCH = 10               # safety cap on number of files
MAX_TOTAL_BYTES = 200 * 1024 * 1024    # 200 MB combined
MAX_CORPUS_CHARS = 60_000              # combined extracted text cap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _read_with_cap(file: UploadFile, cap: int) -> bytes:
    """Read an UploadFile in chunks, raising 413 if it exceeds ``cap``."""
    chunks: List[bytes] = []
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
                detail=f"'{file.filename or 'upload'}' exceeds {cap // (1024 * 1024)} MB.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _safe_extract(filename: str, content: bytes) -> str:
    try:
        return outline_extractor.extract_text(filename, content)
    except outline_extractor.UploadExtractionError as exc:
        raise HTTPException(status_code=exc.http_status, detail=str(exc))
    except Exception as exc:
        msg = plagiarism_analyzer.sanitize_error_message(str(exc))
        raise HTTPException(status_code=400, detail=f"Could not read '{filename}': {msg}")


def _parse_section_list(raw: str) -> List[str]:
    """Section names come in as a JSON-encoded list of strings."""
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="`sections` must be a JSON list of strings.")
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail="`sections` must be a JSON list of strings.")
    cleaned = [str(s).strip() for s in parsed if str(s).strip()]
    if not cleaned:
        raise HTTPException(status_code=400, detail="`sections` cannot be empty.")
    if len(cleaned) > 50:
        raise HTTPException(status_code=400, detail="Too many sections (max 50).")
    return cleaned


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/extract")
async def extract_outline(
    files: List[UploadFile] = File(...),
    sections: str = Form(...),
    format_label: str = Form(""),
) -> Dict[str, Any]:
    """Extract text from one or more uploads and classify it into sections.

    Returns:
        {
          "by_section": {section_name: text, ...},   # keys match `sections`
          "files":      [{name, chars, ok, error?}, ...],
          "total_chars": int,
          "auto_filled": int                          # count of non-empty sections
        }
    """
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one file.")
    if len(files) > MAX_FILES_PER_BATCH:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files in one batch (max {MAX_FILES_PER_BATCH}).",
        )

    section_names = _parse_section_list(sections)

    file_results: List[Dict[str, Any]] = []
    pieces: List[str] = []
    running_bytes = 0

    for upload in files:
        fname = upload.filename or "(unnamed)"
        try:
            raw = await _read_with_cap(upload, MAX_FILE_BYTES)
        except HTTPException as exc:
            file_results.append({"name": fname, "chars": 0, "ok": False, "error": exc.detail})
            continue

        running_bytes += len(raw)
        if running_bytes > MAX_TOTAL_BYTES:
            file_results.append(
                {"name": fname, "chars": 0, "ok": False,
                 "error": "Skipped — combined upload size exceeded limit."}
            )
            continue

        try:
            text = _safe_extract(fname, raw)
        except HTTPException as exc:
            file_results.append({"name": fname, "chars": 0, "ok": False, "error": exc.detail})
            continue

        text = (text or "").strip()
        if not text:
            file_results.append(
                {"name": fname, "chars": 0, "ok": False,
                 "error": "No readable text found."}
            )
            continue

        file_results.append({"name": fname, "chars": len(text), "ok": True})
        pieces.append(f"=== {fname} ===\n{text}")

    if not pieces:
        # Nothing extracted — return an all-empty section map and the per-file errors.
        return {
            "by_section": {name: "" for name in section_names},
            "files": file_results,
            "total_chars": 0,
            "auto_filled": 0,
        }

    corpus = "\n\n".join(pieces)
    if len(corpus) > MAX_CORPUS_CHARS:
        corpus = corpus[:MAX_CORPUS_CHARS]

    try:
        by_section = section_classifier.classify_corpus_into_sections(
            corpus=corpus,
            section_names=section_names,
            format_label=format_label or "",
        )
    except plagiarism_analyzer.ProviderQuotaExhausted as exc:
        raise HTTPException(
            status_code=503,
            detail="The AI service is temporarily over its quota. Please try again later.",
        ) from exc
    except Exception as exc:
        msg = plagiarism_analyzer.sanitize_error_message(str(exc))
        raise HTTPException(status_code=502, detail=f"Section classification failed: {msg}")

    auto_filled = sum(1 for v in by_section.values() if v.strip())

    return {
        "by_section": by_section,
        "files": file_results,
        "total_chars": len(corpus),
        "auto_filled": auto_filled,
    }


@router.post("/extract-section")
async def extract_for_section(
    file: UploadFile = File(...),
    section_name: str = Form(...),
) -> Dict[str, Any]:
    """Extract text from a single file for one specific section."""
    name = (section_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="`section_name` is required.")

    fname = file.filename or "(unnamed)"
    raw = await _read_with_cap(file, MAX_FILE_BYTES)
    text = _safe_extract(fname, raw).strip()
    if not text:
        raise HTTPException(status_code=400, detail="No readable text found in this file.")

    if len(text) > section_classifier.MAX_SECTION_CHARS:
        text = text[: section_classifier.MAX_SECTION_CHARS]

    return {"section_name": name, "text": text, "chars": len(text), "file": fname}


@router.post("/generate")
async def generate_section(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Draft a missing section based on what the user has filled elsewhere.

    Body:
        {
          "section_name":  "Methodology",
          "format_label":  "ICMR — ...",
          "filled":        {"Background": "...", "Objectives": "...", ...}
        }
    """
    section_name = str(payload.get("section_name") or "").strip()
    if not section_name:
        raise HTTPException(status_code=400, detail="`section_name` is required.")

    format_label = str(payload.get("format_label") or "")
    filled_raw = payload.get("filled") or {}
    if not isinstance(filled_raw, dict):
        raise HTTPException(status_code=400, detail="`filled` must be an object.")

    filled: Dict[str, str] = {}
    for k, v in filled_raw.items():
        if isinstance(k, str) and isinstance(v, str):
            filled[k] = v

    try:
        text = section_classifier.generate_missing_section(
            section_name=section_name,
            format_label=format_label,
            filled=filled,
        )
    except plagiarism_analyzer.ProviderQuotaExhausted as exc:
        raise HTTPException(
            status_code=503,
            detail="The AI service is temporarily over its quota. Please try again later.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        msg = plagiarism_analyzer.sanitize_error_message(str(exc))
        raise HTTPException(status_code=502, detail=f"Generation failed: {msg}")

    return {"section_name": section_name, "text": text, "chars": len(text)}
