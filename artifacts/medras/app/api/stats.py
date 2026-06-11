"""Statistical Analysis Engine API.

Endpoints (all under ``/api/stats``):

* ``POST /upload``         — upload an Excel/CSV, get back a job_id and preview.
* ``POST /generate-dummy`` — generate a dummy dataset, returns same shape.
* ``GET  /dataset/{job_id}`` — retrieve dataset metadata + classifications + preview.
* ``POST /classify``       — re-classify (or accept user overrides) for a dataset.
* ``POST /analyze``        — run the primary test for a chosen outcome / group.
* ``GET  /templates``      — list available dummy templates.

State (the parsed DataFrame) lives in ``app.services.dataset_store``. This is
deliberately in-process for Phase 1 — single uvicorn worker — and will be
swapped for a shared cache when we move to a multi-worker deployment.
"""

from __future__ import annotations

import asyncio
import io
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from app.core.limiter import limiter
from app.core.logging import get_logger
from app.services import (
    ai_bridge as ai_bridge_service,
    ai_chatbox,
    category_merger,
    chatboxes,
    data_quality,
    dataset_store,
    doc_correction,
    dummy_data,
    excel_loader,
    export as export_service,
    normality as normality_service,
    outline_extractor,
    plan as plan_service,
    proposal_store,
    results as results_service,
    stats_tests,
    variable_assistant,
    variable_classifier,
    variable_issues,
)
from fastapi.responses import Response

import pandas as pd


# Allowed extensions for the intake proposal upload (lowercase, with dot).
_PROPOSAL_EXTS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".txt", ".md", ".rtf"}
_PROPOSAL_MAX_BYTES = 8 * 1024 * 1024  # 8 MB


log = get_logger(__name__)
router = APIRouter(prefix="/stats", tags=["stats"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class DatasetSummary(BaseModel):
    job_id: str
    filename: str
    rows: int
    cols: int
    sheet_names: List[str] = Field(default_factory=list)
    selected_sheet: Optional[str] = None


VarTypeLiteral = Literal[
    "scale", "ordinal", "nominal", "discrete", "date", "id", "exclude"
]
TemplateLiteral = Literal["anaemia", "diabetes", "hypertension", "rct"]


class ClassificationOverride(BaseModel):
    column: str = Field(..., min_length=1, max_length=200)
    detected_type: VarTypeLiteral


class ClassifyRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    overrides: List[ClassificationOverride] = Field(default_factory=list, max_length=200)


class AnalyzeRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    outcome: str = Field(..., min_length=1, max_length=200)
    group: Optional[str] = Field(default=None, max_length=200)
    alpha: float = Field(default=0.05, gt=0.0, lt=1.0)


class IntakeContext(BaseModel):
    """Free-form research context the user provides up front so later analysis
    steps can interpret variables and instructions in the user's own words.

    Two branches based on `what_you_have`:
      * "proposal"  → user uploads a study proposal document; we keep a
        reference to it via `proposal_id` (the bytes live in `proposal_store`).
      * "objective" → user pastes the study objective(s) and an expected
        sample size; we keep both as plain text/number.
    Either branch may also include free-text `instructions`.
    """
    what_you_have: Literal["proposal", "objective"] = "proposal"
    # Proposal branch
    proposal_id: Optional[str] = Field(default=None, max_length=64)
    proposal_filename: Optional[str] = Field(default=None, max_length=300)
    proposal_size_bytes: Optional[int] = Field(default=None, ge=0)
    # Objective branch
    objective: str = Field(default="", max_length=8000)
    sample_size: Optional[int] = Field(default=None, ge=1, le=10_000_000)
    # Always available — short plain-English descriptions of the variables
    # the researcher cares about. These are advisory hints; the actual
    # column-by-column variable types are still set on the classification
    # screen (Screen 3) once the worksheet is loaded.
    outcomes: str = Field(default="", max_length=4000)
    independents: str = Field(default="", max_length=4000)
    instructions: str = Field(default="", max_length=4000)


class GenerateDummyRequest(BaseModel):
    template: TemplateLiteral
    n_patients: int = Field(default=150, ge=10, le=5000)
    n_groups: int = Field(default=2, ge=1, le=3)
    missing_pct: float = Field(default=5.0, ge=0.0, le=50.0)
    seed: Optional[int] = Field(default=None, ge=0, le=2**31 - 1)
    intake: Optional[IntakeContext] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_session_view(entry, classifications, assignment) -> Dict[str, Any]:
    """Build the `session` dict consumed by phase-B trigger logic.

    Pulls intake answers, assignment and per-column display names so that
    new tests can resolve names and detect study-design hints.
    """
    from app.services.results import clean_display_name as _clean
    intake = entry.meta.get("intake") or {}
    objective = ""
    if isinstance(intake, dict):
        objective = (intake.get("objective")
                     or intake.get("objective_text")
                     or intake.get("text")
                     or "")
    variables = {}
    for c in classifications or []:
        col = c.get("column")
        if col:
            variables[str(col)] = {
                "display_name": _clean(col),
                "type": c.get("detected_type"),
                "subtype": c.get("subtype"),
                "unit": "",
            }
    return {
        "objective": str(objective),
        "variables": variables,
        "outcome_variable": (assignment or {}).get("outcome"),
        "grouping_variable": (assignment or {}).get("group"),
        "covariates": list((assignment or {}).get("covariates") or []),
        # Future wizard work will populate these:
        "paired": bool(intake.get("paired")) if isinstance(intake, dict) else False,
        "design": intake.get("design") if isinstance(intake, dict) else None,
        "timepoints": list(intake.get("timepoints") or []) if isinstance(intake, dict) else [],
        "time_variable": intake.get("time_variable") if isinstance(intake, dict) else None,
        "event_variable": intake.get("event_variable") if isinstance(intake, dict) else None,
        "outcome_type": intake.get("outcome_type") if isinstance(intake, dict) else None,
    }


def _build_response(job_id: str, entry) -> Dict[str, Any]:
    classifications = entry.meta.get("classifications") or variable_classifier.classify_dataframe(entry.df)
    entry.meta["classifications"] = classifications
    preview = excel_loader.preview_records(entry.df, n=10)
    columns = list(entry.df.columns)
    # Include columns whose NAME strongly suggests an identifier even if the
    # classifier flagged them otherwise (longitudinal/follow-up files have many
    # repeats per ID by design, so uniqueness-based id detection misses them).
    id_columns = list(
        {c["column"] for c in classifications if c.get("detected_type") == "id"}
        | {c for c in entry.df.columns if variable_classifier.column_name_looks_like_id(c)}
    )
    repeated_ids = excel_loader.detect_repeated_ids(entry.df, id_columns) if id_columns else {
        "any_repeats": False, "columns": [],
    }
    return {
        "job_id": job_id,
        "summary": {
            "filename": entry.meta.get("filename"),
            "rows": int(entry.df.shape[0]),
            "cols": int(entry.df.shape[1]),
            "sheet_names": entry.meta.get("sheet_names", []),
            "selected_sheet": entry.meta.get("selected_sheet"),
            "merged_sheets": entry.meta.get("merged_sheets") or [],
            "merge_group_column": entry.meta.get("merge_group_column"),
            "skipped_blank_sheets": entry.meta.get("skipped_blank_sheets") or [],
            "header_looks_numeric": bool(entry.meta.get("header_looks_numeric", False)),
            "is_dummy": bool(entry.meta.get("is_dummy", False)),
            "is_practice_wizard": bool(entry.meta.get("is_practice_wizard", False)),
            "template": entry.meta.get("template"),
            "preview_confirmed": bool(entry.meta.get("preview_confirmed", False)),
            "follow_up_data": entry.meta.get("follow_up_data"),
        },
        "columns": columns,
        "classifications": classifications,
        "preview": preview,
        "repeated_ids": repeated_ids,
        "intake": entry.meta.get("intake"),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/templates")
def list_templates() -> Dict[str, Any]:
    return {"templates": dummy_data.list_templates()}


@router.post("/upload-proposal")
@limiter.limit("20/minute")
async def upload_proposal(request: Request, file: UploadFile = File(...)) -> Dict[str, Any]:
    """Accept a study-proposal document (PDF/DOCX/PPTX/TXT/MD/RTF) at intake.

    Returns a `proposal_id` the client passes back inside `intake.proposal_id`
    when it later calls `/upload`, `/generate-dummy`, or `/confirm-preview`.
    """
    filename = file.filename or "proposal"
    # Validate extension.
    lower = filename.lower()
    ext = ""
    if "." in lower:
        ext = "." + lower.rsplit(".", 1)[-1]
    if ext not in _PROPOSAL_EXTS:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported file type. Please upload a PDF, Word (.doc/.docx),"
                " PowerPoint (.ppt/.pptx), or plain text (.txt/.md/.rtf) file."
            ),
        )
    # Stream the upload in chunks so an attacker can't pin a large blob in
    # memory before we get a chance to reject it. Abort as soon as we see
    # more than _PROPOSAL_MAX_BYTES bytes on the wire.
    chunks: list[bytes] = []
    total = 0
    chunk_size = 64 * 1024
    while True:
        piece = await file.read(chunk_size)
        if not piece:
            break
        total += len(piece)
        if total > _PROPOSAL_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Limit is {_PROPOSAL_MAX_BYTES // (1024 * 1024)} MB.",
            )
        chunks.append(piece)
    raw = b"".join(chunks)
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    meta = {
        "filename": filename,
        "size_bytes": len(raw),
        "content_type": file.content_type or "",
        "ext": ext,
    }
    proposal_id = proposal_store.put(raw, meta)
    return {
        "proposal_id": proposal_id,
        "filename": filename,
        "size_bytes": len(raw),
        "content_type": file.content_type or "",
    }


import re as _re
import os as _os
import json as _json
import httpx as _httpx

from app.services.llm_client import openai_chat_url as _openai_chat_url, openai_auth_header as _openai_auth_header, openai_is_configured as _openai_is_configured, gemini_is_configured as _gemini_is_configured, get_gemini_client as _get_gemini_client, provider_status_payload as _provider_status_payload
from app.services.phi_redaction import screen_external_ai_payload as _screen_external_ai_payload
_PARSE_TIMEOUT = 25.0

_PARSE_PROMPT = """\
You are a medical research assistant. The text below is extracted from a \
study proposal or synopsis document. Extract the following fields and return \
ONLY valid JSON with exactly these keys — no markdown, no extra text:

{{
  "objective": "<Full study aim or primary objective. 2-4 sentences. \
If multiple objectives, include all. Empty string if not found.>",
  "outcomes": "<The PRIMARY outcome variable name exactly as it would \
appear as a column header in an Excel/SPSS spreadsheet. \
Examples: HbA1c, P/N, Allred Score, OS, SBP. \
Short, precise. Empty string if not found.>",
  "study_type": "<One of: comparison | correlation | diagnostic | \
survival | descriptive. Choose the best fit. Default to correlation.>",
  "sample_size": <Integer sample size if stated, or null>
}}

=== DOCUMENT TEXT (first 4000 chars) ===
{text}
=== END ===
"""


def _heuristic_extract(text: str) -> dict:
    """Return best-effort extraction using regex — used as fallback."""
    obj = ""
    obj_pat = _re.compile(
        r"(?:primary\s+)?(?:aim|objective|purpose|goal|hypothesis)\s*[:\-–—]\s*"
        r"(.+?)(?:\n\n|\n(?=[A-Z])|\Z)",
        _re.IGNORECASE | _re.DOTALL,
    )
    m = obj_pat.search(text)
    if m:
        obj = m.group(1).strip()[:600]
    if not obj:
        para_pat = _re.compile(
            r"(?:to\s+(?:study|evaluate|compare|assess|determine|investigate|"
            r"examine|analyse|analyze)\b.{20,400})",
            _re.IGNORECASE | _re.DOTALL,
        )
        pm = para_pat.search(text)
        if pm:
            obj = pm.group(0).strip()[:600]

    out = ""
    out_pat = _re.compile(
        r"(?:primary\s+)?(?:outcome|endpoint|variable|measure)\s*[:\-–—]\s*([^\n]{3,120})",
        _re.IGNORECASE,
    )
    om = out_pat.search(text)
    if om:
        token = _re.split(r"[,;()\n]", om.group(1).strip())[0].strip()
        out = token[:80]

    n = None
    n_pat = _re.compile(
        r"(?:sample\s+size|n\s*=|enrol(?:l?ed)?|participants?|subjects?)\s*[:\=\-–]?\s*(\d{2,5})",
        _re.IGNORECASE,
    )
    nm = n_pat.search(text)
    if nm:
        try:
            n = int(nm.group(1))
        except ValueError:
            pass

    study_type = "correlation"
    dl = text.lower()
    for st, words in [
        ("diagnostic", ["sensitiv", "specific", "roc", "auc", "diagnostic accuracy"]),
        ("survival", ["survival", "mortality", "time to event", "kaplan", "disease-free"]),
        ("comparison", ["compar", " vs ", "versus", "between group", "randomis", "randomiz", "trial"]),
        ("descriptive", ["prevalence", "incidence", "frequenc", "characteris", "profile"]),
    ]:
        if any(w in dl for w in words):
            study_type = st
            break

    return {"objective": obj, "outcomes": out, "study_type": study_type, "sample_size": n}


async def _ai_extract(text: str, external_ai_consent: bool = False) -> tuple[
    dict | None, str | None, bool, bool
]:
    """Try Gemini then OpenAI to extract structured fields from proposal text.

    Returns parsed dict or None on failure — caller falls back to heuristics.
    """
    if not external_ai_consent:
        return None, None, False, False

    screening = _screen_external_ai_payload(text[:4000])
    if screening.blocked:
        return None, None, screening.redaction_applied, True
    snippet = screening.value
    prompt = _PARSE_PROMPT.format(text=snippet)

    # ── Try Gemini first ────────────────────────────────────────────────────
    if _gemini_is_configured():
        def _gemini_call() -> dict | None:
            from google.genai import types as _gtypes
            gc = _get_gemini_client()
            resp = gc.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=_gtypes.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=512,
                    response_mime_type="application/json",
                ),
            )
            raw = (resp.text or "").strip()
            raw = _re.sub(r"^```(?:json)?\s*", "", raw, flags=_re.IGNORECASE)
            raw = _re.sub(r"\s*```$", "", raw.strip())
            result = _json.loads(raw)
            return result if isinstance(result, dict) and "objective" in result else None

        try:
            result = await asyncio.to_thread(_gemini_call)
            if result:
                return result, "gemini", screening.redaction_applied, False
        except Exception:
            pass

    # ── Fall back to OpenAI ─────────────────────────────────────────────────
    if _openai_is_configured():
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 512,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        try:
            async with _httpx.AsyncClient(timeout=_PARSE_TIMEOUT) as client:
                resp = await client.post(
                    _openai_chat_url(),
                    json=payload,
                    headers={"Authorization": _openai_auth_header()},
                )
            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"].strip()
                result = _json.loads(raw)
                if isinstance(result, dict) and "objective" in result:
                    return result, "openai", screening.redaction_applied, False
        except Exception:
            pass

    return None, None, screening.redaction_applied, False


@router.post("/parse-proposal")
@limiter.limit("10/minute")
async def parse_proposal(request: Request, file: UploadFile = File(...)) -> Dict[str, Any]:
    """Parse a study-proposal document and extract structured study details.

    Accepts PDF / DOCX / PPTX / TXT / MD / RTF.
    Uses Gemini → OpenAI → regex heuristic fallback chain.
    Returns ``{objective, outcomes, study_type, sample_size, source}``.
    """
    filename = file.filename or "proposal"
    lower = filename.lower()
    ext = ("." + lower.rsplit(".", 1)[-1]) if "." in lower else ""
    if ext not in _PROPOSAL_EXTS:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported file type. Please upload a PDF, Word (.doc/.docx),"
                " PowerPoint (.ppt/.pptx), or plain text (.txt/.md/.rtf) file."
            ),
        )
    raw = await file.read()
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(raw) > _PROPOSAL_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Limit is {_PROPOSAL_MAX_BYTES // (1024 * 1024)} MB.",
        )
    try:
        text = outline_extractor.extract_text(filename, raw)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Could not read the file: {exc}",
        ) from exc

    # Try AI extraction first, fall back to heuristics.
    external_ai_consent = request.headers.get("X-External-AI-Consent", "").lower() == "true"
    ai_result, provider, redaction_applied, phi_blocked = await _ai_extract(
        text, external_ai_consent
    )
    if ai_result and isinstance(ai_result, dict) and ai_result.get("objective"):
        sample_size = ai_result.get("sample_size")
        if sample_size is not None:
            try:
                sample_size = int(sample_size)
            except (ValueError, TypeError):
                sample_size = None
        valid_types = {"comparison", "correlation", "diagnostic", "survival", "descriptive"}
        study_type = str(ai_result.get("study_type") or "correlation").strip().lower()
        if study_type not in valid_types:
            study_type = "correlation"
        return {
            "objective": str(ai_result.get("objective") or "").strip(),
            "outcomes": str(ai_result.get("outcomes") or "").strip(),
            "study_type": study_type,
            "sample_size": sample_size,
            "source": provider or "ai",
            **_provider_status_payload(
                provider or "ai_unavailable",
                external_ai_consent,
                redaction_applied,
                phi_blocked,
            ),
        }

    # Heuristic fallback.
    h = _heuristic_extract(text)
    return {
        **h,
        "source": "heuristic",
        **_provider_status_payload(
            "local_fallback", external_ai_consent, redaction_applied, phi_blocked
        ),
    }


@router.post("/upload")
@limiter.limit("20/minute")
async def upload_dataset(request: Request, file: UploadFile = File(...)) -> Dict[str, Any]:
    raw = await file.read()
    try:
        df, meta = excel_loader.parse_upload(filename=file.filename or "upload", raw=raw)
    except excel_loader.UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job_id = dataset_store.put(df, meta)
    entry = dataset_store.get(job_id)
    return _build_response(job_id, entry)


@router.post("/generate-dummy")
@limiter.limit("30/minute")
async def generate_dummy(request: Request, payload: GenerateDummyRequest) -> Dict[str, Any]:
    try:
        df = dummy_data.generate(
            template=payload.template,
            n_patients=payload.n_patients,
            n_groups=payload.n_groups,
            missing_pct=payload.missing_pct,
            seed=payload.seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    meta = {
        "filename": f"dummy_{payload.template}.xlsx",
        "size_bytes": 0,
        "rows": int(df.shape[0]),
        "cols": int(df.shape[1]),
        "sheet_names": [],
        "selected_sheet": None,
        "is_dummy": True,
        "template": payload.template,
        "intake": payload.intake.model_dump() if payload.intake else None,
    }
    job_id = dataset_store.put(df, meta)
    entry = dataset_store.get(job_id)
    return _build_response(job_id, entry)


@router.get("/dataset/{job_id}")
async def get_dataset(job_id: str) -> Dict[str, Any]:
    entry = dataset_store.get(job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    return _build_response(job_id, entry)


class SelectSheetRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    sheet_name: str = Field(..., min_length=1, max_length=200)


@router.post("/select-sheet")
async def select_sheet(payload: SelectSheetRequest) -> Dict[str, Any]:
    """Re-parse a previously uploaded Excel using a different sheet."""
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    raw = entry.meta.get("raw_bytes")
    filename = entry.meta.get("filename") or "upload.xlsx"
    if not raw:
        raise HTTPException(status_code=400, detail="No raw file available to re-read.")
    if payload.sheet_name not in (entry.meta.get("sheet_names") or []):
        raise HTTPException(status_code=400, detail="Unknown sheet name.")
    try:
        df, meta = excel_loader.parse_upload(
            filename=filename, raw=raw, sheet_name=payload.sheet_name
        )
    except excel_loader.UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Replace dataframe + meta but keep job_id stable so the UI doesn't lose state.
    dataset_store.replace_df(payload.job_id, df)
    # Preserve raw_bytes; clear classifications so they re-derive for the new sheet.
    # Also explicitly clear merge bookkeeping — update_meta is a merge, so without
    # this an earlier /combine-sheets run would leave merged_sheets dangling.
    meta["raw_bytes"] = raw
    dataset_store.update_meta(
        payload.job_id,
        **meta,
        classifications=None,
        merged_sheets=[],
        merge_group_column=None,
        skipped_blank_sheets=[],
    )
    entry = dataset_store.get(payload.job_id)
    return _build_response(payload.job_id, entry)


class CombineSheetsRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    sheet_names: List[str] = Field(..., min_length=2, max_length=20)
    add_group_column: bool = Field(default=True)
    group_column_name: str = Field(default="Group", min_length=1, max_length=60)


@router.post("/combine-sheets")
async def combine_sheets(payload: CombineSheetsRequest) -> Dict[str, Any]:
    """Concatenate the rows of two or more sheets into a single dataset.

    Common use case: each treatment arm lives on its own sheet and the
    researcher needs them stacked together with a "Group" column so a
    between-groups test can be run.
    """
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    raw = entry.meta.get("raw_bytes")
    filename = entry.meta.get("filename") or "upload.xlsx"
    if not raw:
        raise HTTPException(status_code=400, detail="No raw file available to re-read.")
    available = entry.meta.get("sheet_names") or []
    unknown = [s for s in payload.sheet_names if s not in available]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown sheets: {', '.join(unknown)}.")
    # Reject duplicate sheet names — concatenating the same sheet twice would
    # silently double its rows and bias every downstream summary statistic.
    if len(set(payload.sheet_names)) != len(payload.sheet_names):
        raise HTTPException(status_code=400, detail="Pick each sheet at most once.")
    try:
        df, meta = excel_loader.combine_sheets(
            filename=filename,
            raw=raw,
            sheet_names=payload.sheet_names,
            add_group_column=payload.add_group_column,
            group_column_name=payload.group_column_name,
        )
    except excel_loader.UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dataset_store.replace_df(payload.job_id, df)
    meta["raw_bytes"] = raw
    dataset_store.update_meta(payload.job_id, **meta, classifications=None)
    entry = dataset_store.get(payload.job_id)
    return _build_response(payload.job_id, entry)


class ConfirmPreviewRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    follow_up_data: Optional[bool] = None  # answer to "is this follow-up data?"
    intake: Optional[IntakeContext] = None


@router.post("/confirm-preview")
async def confirm_preview(payload: ConfirmPreviewRequest) -> Dict[str, Any]:
    """Lock the file-preview confirmation (Screen 2A step)."""
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    update_kwargs: Dict[str, Any] = {
        "preview_confirmed": True,
        "follow_up_data": payload.follow_up_data,
    }
    # Only overwrite intake if the client sent one (uploads attach intake here
    # for the first time; practice mode already sent it on /generate-dummy).
    if payload.intake is not None:
        update_kwargs["intake"] = payload.intake.model_dump()
    dataset_store.update_meta(payload.job_id, **update_kwargs)
    entry = dataset_store.get(payload.job_id)
    return _build_response(payload.job_id, entry)


@router.get("/quality-check/{job_id}")
async def quality_check(job_id: str) -> Dict[str, Any]:
    """Run the data-quality report (Screen 4)."""
    entry = dataset_store.get(job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    classifications = entry.meta.get("classifications") or variable_classifier.classify_dataframe(entry.df)
    entry.meta["classifications"] = classifications
    return await asyncio.to_thread(data_quality.quality_report, entry.df, classifications=classifications)


class QualityAction(BaseModel):
    row: int
    variable: str = Field(..., min_length=1, max_length=400)
    action: Literal["keep", "remove", "cap", "review"]
    bound_low: Optional[float] = None
    bound_high: Optional[float] = None


class ApplyQualityRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    actions: List[QualityAction] = Field(default_factory=list, max_length=5000)
    remove_exact_duplicates: bool = True


@router.post("/apply-quality")
@limiter.limit("30/minute")
async def apply_quality(request: Request, payload: ApplyQualityRequest) -> Dict[str, Any]:
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    _actions_list = [a.model_dump() for a in payload.actions]
    new_df, log_counts = await asyncio.to_thread(
        lambda: data_quality.apply_actions(
            entry.df,
            actions=_actions_list,
            remove_exact_duplicates=payload.remove_exact_duplicates,
        )
    )
    _invalidate_downstream(entry, keep_normality=False)
    dataset_store.replace_df(payload.job_id, new_df)
    dataset_store.update_meta(
        payload.job_id,
        classifications=None,  # recompute, since rows changed
        rows=int(new_df.shape[0]),
        quality_applied=True,
        quality_log=log_counts,
    )
    entry = dataset_store.get(payload.job_id)
    response = _build_response(payload.job_id, entry)
    response["log"] = log_counts
    return response


@router.post("/classify")
async def classify(payload: ClassifyRequest) -> Dict[str, Any]:
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    # Pre-clean in a reversible, previewable way. Each helper is idempotent;
    # backups keep the original source columns so /cleanup-undo can restore
    # them or remove derived columns.
    source_df = entry.df
    fresh_cleanup_notes: Dict[str, str] = {}
    cleanup_suppressed = set(entry.meta.get("cleanup_suppressed") or [])

    def _merge_cleanup_notes(notes: Dict[str, str]) -> None:
        for col, note in notes.items():
            if col in fresh_cleanup_notes:
                fresh_cleanup_notes[col] = f"{fresh_cleanup_notes[col]} {note}"
            else:
                fresh_cleanup_notes[col] = note

    cleaned_df, string_notes = variable_classifier.normalize_string_columns(
        source_df, skip_columns=cleanup_suppressed
    )
    _merge_cleanup_notes(string_notes)
    cleaned_df, node_notes, derived_by_source = variable_classifier.derive_node_fraction_columns(
        cleaned_df, skip_columns=cleanup_suppressed
    )
    _merge_cleanup_notes(node_notes)
    cleaned_df, numeric_notes = variable_classifier.clean_numeric_like_columns(
        cleaned_df, skip_columns=cleanup_suppressed
    )
    _merge_cleanup_notes(numeric_notes)
    applied_cleanup_cols = set(derived_by_source)
    for col in source_df.columns:
        if col in cleaned_df.columns and not source_df[col].equals(cleaned_df[col]):
            applied_cleanup_cols.add(col)
    cleanup_changed = bool(applied_cleanup_cols)

    if fresh_cleanup_notes:
        # Snapshot the original (pre-cleanup) values so the user can
        # undo preprocessing from Step 3 if our heuristic was wrong. We store
        # only the source columns that changed to keep memory bounded.
        backups = dict(entry.meta.get("cleanup_backups") or {})
        for col in applied_cleanup_cols:
            derived_cols = list(derived_by_source.get(col) or [])
            if col in source_df.columns and col not in backups:
                # Convert the original Series to a list so the backup
                # survives DataFrame mutations and JSON-serialises
                # cleanly through dataset_store's pickle round-trip.
                values = source_df[col].tolist()
                backups[col] = (
                    {"values": values, "derived_columns": derived_cols}
                    if derived_cols else values
                )
            elif derived_cols and col in backups:
                existing = backups[col]
                if isinstance(existing, dict):
                    prior = list(existing.get("derived_columns") or [])
                    existing["derived_columns"] = list(dict.fromkeys(prior + derived_cols))
                    backups[col] = existing
                else:
                    backups[col] = {
                        "values": existing,
                        "derived_columns": derived_cols,
                    }
        entry.meta["cleanup_backups"] = backups
        existing_notes = dict(entry.meta.get("cleanup_notes") or {})
        existing_notes.update(fresh_cleanup_notes)
        entry.meta["cleanup_notes"] = existing_notes
        if cleanup_changed:
            _invalidate_downstream(entry, keep_normality=False)
        if cleanup_changed:
            dataset_store.replace_df(payload.job_id, cleaned_df)
        # When the underlying df changed, any previously stored
        # classifications are no longer valid (the dtypes shifted) — so
        # force a full re-classify by ignoring the stored copy.
        entry.meta.pop("classifications", None)
        # Refresh the entry handle so we read the new df below.
        entry = dataset_store.get(payload.job_id)
        assert entry is not None
    cleanup_notes: Dict[str, str] = dict(entry.meta.get("cleanup_notes") or {})
    cleanup_backups = entry.meta.get("cleanup_backups") or {}
    # Reuse a previously stored classification if there are no overrides
    # AND we already have one — this preserves changes made by the
    # variable-assistant (e.g. type promoted to scale after strip_prefix)
    # so a plain refresh doesn't wipe them.
    stored = entry.meta.get("classifications") if not payload.overrides else None
    if stored:
        # Still need to refresh sample_values / missing counts in case the
        # DataFrame was mutated by the assistant.
        fresh = variable_classifier.classify_dataframe(entry.df)
        fresh_by_col = {c["column"]: c for c in fresh}
        classifications: List[Dict[str, Any]] = []
        for c in fresh:
            prev = next((p for p in stored if p["column"] == c["column"]), None)
            if prev and prev.get("reason", "").startswith(("Manually set", "Set by assistant")):
                # User/assistant override wins over re-detection. Re-run
                # the Variable Intelligence Layer so the four theory-aware
                # axes match the overridden detected_type instead of the
                # one the auto-classifier just produced.
                c["detected_type"] = prev["detected_type"]
                c["reason"] = prev["reason"]
                if c["column"] in entry.df.columns:
                    variable_classifier.reenrich_after_override(
                        c, entry.df[c["column"]], c["column"],
                    )
            classifications.append(c)
        # Append columns that exist only in stored (shouldn't normally happen).
        for prev in stored:
            if prev["column"] not in fresh_by_col:
                classifications.append(prev)
    else:
        classifications = variable_classifier.classify_dataframe(entry.df)
        if payload.overrides:
            ov = {o.column: o.detected_type for o in payload.overrides}
            for c in classifications:
                if c["column"] in ov:
                    c["detected_type"] = ov[c["column"]]
                    c["reason"] = f"Manually set to {ov[c['column']]}."
                    if c["column"] in entry.df.columns:
                        variable_classifier.reenrich_after_override(
                            c, entry.df[c["column"]], c["column"],
                        )
    # Attach cleanup notes (if any) onto the affected classifications so
    # the UI can show users what was auto-extracted from text cells.
    if cleanup_notes:
        for c in classifications:
            note = cleanup_notes.get(c["column"])
            if not note:
                continue
            c["cleanup_note"] = note
            c["cleanup_undo_available"] = c["column"] in cleanup_backups
            existing_reason = c.get("reasoning") or ""
            if note not in existing_reason:
                c["reasoning"] = (note + " " + existing_reason).strip()

    entry.meta["classifications"] = classifications

    issues = variable_issues.detect_issues(entry.df, classifications)
    coding = variable_issues.auto_coding_plan(entry.df, classifications)
    entry.meta["variable_issues"] = issues
    entry.meta["auto_coding_plan"] = coding

    return {
        "job_id": payload.job_id,
        "classifications": classifications,
        "issues": issues,
        "auto_coding_plan": coding,
        "blocking_issues": variable_issues.has_blocking_issues(issues),
    }


# ---------------------------------------------------------------------------
# Variable Assistant (Step 3, Zone E)
# ---------------------------------------------------------------------------


class VariableAssistantRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=600)
    confirmed_action: Optional[Dict[str, Any]] = None


@router.post("/variable-assistant")
@limiter.limit("60/minute")
async def variable_assistant_endpoint(
    request: Request, payload: VariableAssistantRequest
) -> Dict[str, Any]:
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")

    columns = list(entry.df.columns)
    stored_classifications = entry.meta.get("classifications") or []

    external_ai_consent = request.headers.get("X-External-AI-Consent", "").lower() == "true"
    provider_meta: Dict[str, Any] = {}

    if payload.confirmed_action is not None:
        intent = {
            "action": payload.confirmed_action.get("action"),
            "column": payload.confirmed_action.get("column"),
            "params": payload.confirmed_action.get("params") or {},
        }
        pending_action = entry.meta.pop("pending_variable_assistant_action", None)
        if pending_action != intent:
            raise HTTPException(
                status_code=409,
                detail="This assistant action was not previewed or is no longer current.",
            )
        allowed = {
            "rename", "exclude_column", "change_type", "strip_prefix",
            "add_numeric_column", "trim_whitespace",
        }
        if intent["action"] not in allowed or intent["column"] not in entry.df.columns:
            raise HTTPException(status_code=400, detail="Confirmed assistant action is invalid or stale.")
        if not isinstance(intent["params"], dict):
            raise HTTPException(status_code=400, detail="Confirmed assistant action parameters are invalid.")
        if intent["action"] == "change_type" and intent["params"].get("new_type") not in {
            "scale", "ordinal", "nominal", "date", "id", "exclude",
            "scale_discrete", "scale_continuous",
        }:
            raise HTTPException(status_code=400, detail="Confirmed variable type is invalid.")
    else:
        # AI may suggest an action, but the endpoint returns a preview before applying it.
        entry.meta.pop("pending_variable_assistant_action", None)
        ai_intent, provider_status, screening_meta = await ai_chatbox.parse_variable_intent(
            payload.message,
            {"classifications": stored_classifications},
            external_ai_consent=external_ai_consent,
        )
        provider_meta = _provider_status_payload(
            provider_status,
            external_ai_consent,
            screening_meta["redaction_applied"],
            screening_meta["phi_blocked"],
        )

        _ai_action = (ai_intent or {}).get("action")
        _ai_col = (ai_intent or {}).get("column")
        _ai_col_valid = _ai_col and _ai_col in entry.df.columns
        if ai_intent and _ai_col_valid:
            if _ai_action == "rename" and ai_intent.get("new_name"):
                intent = {
                    "action": "rename",
                    "column": _ai_col,
                    "params": {"new_name": ai_intent["new_name"]},
                }
            elif _ai_action in ("exclude",):
                intent = {"action": "exclude_column", "column": _ai_col, "params": {}}
            elif _ai_action == "set_type" and ai_intent.get("new_type"):
                intent = {
                    "action": "change_type",
                    "column": _ai_col,
                    "params": {"new_type": ai_intent["new_type"]},
                }
            else:
                intent = variable_assistant.parse_intent(payload.message, columns)
        elif ai_intent and _ai_col and not _ai_col_valid:
            logger.warning(
                "AI variable intent referenced non-existent column %r — rule-based fallback",
                _ai_col,
            )
            intent = variable_assistant.parse_intent(payload.message, columns)
        else:
            intent = variable_assistant.parse_intent(payload.message, columns)

    if (
        intent.get("action") == "strip_prefix"
        and variable_classifier.is_known_categorical_clinical_marker(intent.get("column", ""))
    ):
        entry.meta.pop("pending_variable_assistant_action", None)
        return {
            "status": "clarify",
            "action": "clarify",
            "column": intent.get("column"),
            "params": {},
            "confirmation_message": (
                f"'{intent.get('column')}' is a categorical clinical marker. "
                "Use Nominal for status labels or Ordinal for HER2 score categories; "
                "do not strip Positive/Negative text."
            ),
            "classifications": stored_classifications,
            "issues": entry.meta.get("variable_issues") or [],
            "auto_coding_plan": entry.meta.get("auto_coding_plan") or [],
            "blocking_issues": variable_issues.has_blocking_issues(
                entry.meta.get("variable_issues") or []
            ),
            **provider_meta,
        }

    # Informational intents (no DataFrame mutation): the assistant either
    # gives a tailored suggestion ("what should I do?") or a clarification
    # whose example commands reference real columns from THIS dataset.
    if intent["action"] in ("clarify", "suggest"):
        stored_classifications = entry.meta.get("classifications") or []
        stored_issues = entry.meta.get("variable_issues") or []
        if intent["action"] == "suggest":
            confirmation_message = variable_assistant.suggest_message(
                columns, stored_classifications, stored_issues,
            )
        else:
            confirmation_message = variable_assistant.generic_clarify(columns)
        return {
            "status": "clarify",
            "action": intent["action"],
            "column": intent.get("column"),
            "params": {},
            "confirmation_message": confirmation_message,
            "classifications": stored_classifications,
            "issues": stored_issues,
            "auto_coding_plan": entry.meta.get("auto_coding_plan") or [],
            "blocking_issues": variable_issues.has_blocking_issues(stored_issues),
            **provider_meta,
        }

    if payload.confirmed_action is None:
        column = intent.get("column")
        params = intent.get("params") or {}
        current = next(
            (c.get("detected_type") for c in stored_classifications if c.get("column") == column),
            "unchanged",
        )
        action = intent["action"]
        before = {
            "rename": column,
            "change_type": current,
            "exclude_column": current,
            "strip_prefix": current,
            "add_numeric_column": "no numeric companion column",
            "trim_whitespace": "original string values",
        }.get(action, current)
        after = {
            "rename": params.get("new_name"),
            "change_type": params.get("new_type"),
            "exclude_column": "exclude",
            "strip_prefix": "numeric values; classification becomes scale",
            "add_numeric_column": f"new numeric companion column for {column}",
            "trim_whitespace": "trimmed string values",
        }.get(action, "updated")
        entry.meta["pending_variable_assistant_action"] = intent
        return {
            "status": "preview",
            "action": action,
            "column": column,
            "params": params,
            "confirmed_action": intent,
            "change_preview": {
                "affected": column,
                "before": before,
                "after": after,
                "summary": f"{action.replace('_', ' ').title()} for '{column}'.",
            },
            **provider_meta,
        }

    # Consume the preview before applying so a failed action can never leave
    # a stale confirmation token behind.
    entry.meta.pop("pending_variable_assistant_action", None)
    try:
        new_df, meta = variable_assistant.apply_action(entry.df, intent)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Variable Assistant action failed: {exc}. No changes were applied.",
        ) from exc
    _invalidate_downstream(entry, keep_normality=False)

    # Apply DataFrame mutation if the action produced one.
    if new_df is not None:
        dataset_store.replace_df(payload.job_id, new_df)
        # Bookkeeping: if a column was renamed, propagate to stored
        # classifications so the override logic above keeps working.
        if intent["action"] == "rename":
            old = meta.get("old_column")
            new = meta.get("new_column")
            stored = entry.meta.get("classifications") or []
            for c in stored:
                if c.get("column") == old:
                    c["column"] = new

    # Recompute classifications, then layer assistant-driven overrides.
    classifications = variable_classifier.classify_dataframe(entry.df)
    stored = entry.meta.get("classifications") or []
    stored_by_col = {c.get("column"): c for c in stored}

    # Prefer an explicit target_column from the action (e.g. add_numeric_column
    # creates a NEW column and wants the scale flag on the new one, not the
    # original). Fall back to meta["column"] / intent["column"] for actions
    # that operate on the original column directly.
    target_col = (
        meta.get("target_column")
        or meta.get("column")
        or intent.get("column")
    )
    type_after = meta.get("type_after") or meta.get("new_type")

    # Carry forward any prior manual / assistant overrides on other columns.
    for c in classifications:
        prev = stored_by_col.get(c["column"])
        if prev and prev.get("reason", "").startswith(("Manually set", "Set by assistant")):
            c["detected_type"] = prev["detected_type"]
            c["reason"] = prev["reason"]
            if c["column"] in entry.df.columns:
                variable_classifier.reenrich_after_override(
                    c, entry.df[c["column"]], c["column"],
                )

    # Apply this action's type change.
    if target_col and type_after:
        for c in classifications:
            if c["column"] != target_col:
                continue
            # Per spec Rule 5: "treat as discrete" / "treat as continuous"
            # do NOT change the variable type. They only flip the
            # info-only scale_subtype so descriptive summaries report
            # integers vs floats. The variable still routes through the
            # exact same scale-test machinery.
            if type_after in ("scale_discrete", "scale_continuous"):
                subtype = "discrete" if type_after == "scale_discrete" else "continuous"
                c["detected_type"] = "scale"
                c["scale_subtype"] = subtype
                c["reason"] = f"Set by assistant to scale ({subtype})."
                if c["column"] in entry.df.columns:
                    variable_classifier.reenrich_after_override(
                        c, entry.df[c["column"]], c["column"],
                    )
                # reenrich resets scale_subtype based on dtype — restore
                # the user's explicit choice so it doesn't get clobbered.
                c["scale_subtype"] = subtype
            else:
                c["detected_type"] = type_after
                c["reason"] = f"Set by assistant to {type_after}."
                if c["column"] in entry.df.columns:
                    variable_classifier.reenrich_after_override(
                        c, entry.df[c["column"]], c["column"],
                    )
            break

    entry.meta["classifications"] = classifications
    issues = variable_issues.detect_issues(entry.df, classifications)
    coding = variable_issues.auto_coding_plan(entry.df, classifications)
    entry.meta["variable_issues"] = issues
    entry.meta["auto_coding_plan"] = coding

    return {
        "status": "applied",
        "action": intent["action"],
        "column": target_col,
        "params": intent.get("params") or {},
        "confirmation_message": meta.get("confirmation_message", ""),
        **provider_meta,
        "classifications": classifications,
        "issues": issues,
        "auto_coding_plan": coding,
        "blocking_issues": variable_issues.has_blocking_issues(issues),
    }


# ---------------------------------------------------------------------------
# Trim-all whitespace — batch clean all duplicate_values columns at once
# ---------------------------------------------------------------------------


class TrimAllRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)


@router.post("/trim-all-whitespace")
@limiter.limit("30/minute")
async def trim_all_whitespace_endpoint(
    request: Request, payload: TrimAllRequest
) -> Dict[str, Any]:
    """Trim whitespace from every flagged (duplicate_values) string column
    in one atomic operation — equivalent to clicking Fix for each column
    individually, but instant.
    """
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")

    classifications = entry.meta.get("classifications") or variable_classifier.classify_dataframe(entry.df)
    issues = variable_issues.detect_issues(entry.df, classifications)

    # Target only columns with duplicate_values issues; fall back to all strings.
    dup_cols = [i["column"] for i in issues if i["type"] == "duplicate_values"]
    target = dup_cols or [col for col in entry.df.columns if entry.df[col].dtype == object]

    new_df, trim_meta = await asyncio.to_thread(
        variable_assistant.trim_all_whitespace, entry.df, target
    )

    if trim_meta["total_changed"]:
        _invalidate_downstream(entry, keep_normality=False)
    dataset_store.replace_df(payload.job_id, new_df)

    # Recompute classifications, preserving any manual overrides.
    classifications = variable_classifier.classify_dataframe(entry.df)
    stored = entry.meta.get("classifications") or []
    stored_by_col = {c.get("column"): c for c in stored}
    for c in classifications:
        prev = stored_by_col.get(c["column"])
        if prev and prev.get("reason", "").startswith(("Manually set", "Set by assistant")):
            c["detected_type"] = prev["detected_type"]
            c["reason"] = prev["reason"]
            if c["column"] in entry.df.columns:
                variable_classifier.reenrich_after_override(
                    c, entry.df[c["column"]], c["column"],
                )
    entry.meta["classifications"] = classifications

    issues = variable_issues.detect_issues(entry.df, classifications)
    coding = variable_issues.auto_coding_plan(entry.df, classifications)
    entry.meta["variable_issues"] = issues
    entry.meta["auto_coding_plan"] = coding

    changed = trim_meta["changed_cols"]
    total  = trim_meta["total_changed"]
    if changed:
        msg = (
            f"Trimmed whitespace in {len(changed)} column(s): "
            f"{', '.join(changed)}. {total} cell(s) standardised."
        )
    else:
        msg = "No extra whitespace found — all columns already clean."

    if changed:
        cleaning_actions = list(entry.meta.get("cleaning_actions") or [])
        cleaning_actions.append(msg)
        entry.meta["cleaning_actions"] = cleaning_actions

    return {
        "status": "applied",
        "confirmation_message": msg,
        "classifications": classifications,
        "issues": issues,
        "auto_coding_plan": coding,
        "blocking_issues": variable_issues.has_blocking_issues(issues),
    }


# ---------------------------------------------------------------------------
# Chatboxes 2/3/4 — Normality / Plan / Results explainers
# ---------------------------------------------------------------------------


class ChatboxRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=600)


_VALID_CHATBOX_KINDS = frozenset({"variables", "missing", "normality", "plan", "results"})


def _chatbox_context(
    job_id: str, kind: str, selected_decisions: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    entry = dataset_store.get(job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    if kind == "variables":
        return {
            "classifications": entry.meta.get("classifications") or [],
            "issues": entry.meta.get("variable_issues") or [],
        }
    if kind == "missing":
        classifications = (
            entry.meta.get("classifications")
            or variable_classifier.classify_dataframe(entry.df)
        )
        by_col = {c.get("column"): c for c in classifications}
        supported_actions = [
            "drop_rows", "impute_mean", "impute_median", "impute_mode", "leave",
        ]
        decisions = {
            column: action
            for column, action in (selected_decisions or {}).items()
            if action in supported_actions
        }
        columns = []
        total = len(entry.df)
        for col in entry.df.columns:
            missing_count = int(entry.df[col].isna().sum())
            if missing_count <= 0:
                continue
            info = by_col.get(col) or {}
            columns.append({
                "column": col,
                "missing_count": missing_count,
                "missing_pct": (missing_count / total * 100.0) if total else 0.0,
                "detected_type": info.get("detected_type", "unknown"),
                "selected_decision": decisions.get(col, "leave"),
            })
        return {
            "columns": columns,
            "supported_actions": supported_actions,
            "guidance_only": True,
        }
    if kind == "normality":
        return {"columns": (entry.meta.get("normality") or {}).get("columns") or []}
    if kind == "plan":
        return {"plan": entry.meta.get("plan") or {}}
    if kind == "results":
        return {"results": entry.meta.get("results") or {}}
    return {}


@router.get("/chat/{kind}/opening/{job_id}")
async def chatbox_opening(request: Request, kind: str, job_id: str) -> Dict[str, Any]:
    if kind not in _VALID_CHATBOX_KINDS:
        raise HTTPException(status_code=404, detail="Unknown chatbox kind.")
    ctx = _chatbox_context(job_id, kind)
    external_ai_consent = request.headers.get("X-External-AI-Consent", "").lower() == "true"
    return await ai_chatbox.opening_message(
        kind, ctx, external_ai_consent=external_ai_consent
    )


@router.post("/chat/{kind}")
@limiter.limit("60/minute")
async def chatbox_reply(
    request: Request, kind: str, payload: ChatboxRequest,
) -> Dict[str, Any]:
    if kind not in _VALID_CHATBOX_KINDS:
        raise HTTPException(status_code=404, detail="Unknown chatbox kind.")
    ctx = _chatbox_context(payload.job_id, kind)
    external_ai_consent = request.headers.get("X-External-AI-Consent", "").lower() == "true"
    return await ai_chatbox.chat(
        kind, payload.message, ctx, external_ai_consent=external_ai_consent
    )


# ---------------------------------------------------------------------------
# Cleanup undo (Step 3) — restores the original text values for a column
# whose entries were auto-stripped to numeric by clean_numeric_like_columns.
# Per spec Rule 2: the auto-strip notice must be undoable so users always
# have a way out if our heuristic mis-fires on a labelled categorical
# column that happened to embed numbers.
# ---------------------------------------------------------------------------


class CleanupUndoRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    column: str = Field(..., min_length=1, max_length=200)


@router.post("/cleanup-undo")
async def cleanup_undo(payload: CleanupUndoRequest) -> Dict[str, Any]:
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    backups = entry.meta.get("cleanup_backups") or {}
    if payload.column not in backups:
        raise HTTPException(
            status_code=404,
            detail=f"No cleanup backup found for column '{payload.column}'.",
        )
    if payload.column not in entry.df.columns:
        raise HTTPException(
            status_code=404,
            detail=f"Column '{payload.column}' is no longer present in the dataset.",
        )
    backup = backups[payload.column]
    if isinstance(backup, dict):
        values = backup.get("values")
        derived_columns = list(backup.get("derived_columns") or [])
    else:
        values = backup
        derived_columns = []
    new_df = entry.df.copy()
    for derived_col in derived_columns:
        if derived_col in new_df.columns:
            new_df = new_df.drop(columns=[derived_col])
    new_df[payload.column] = pd.Series(values, index=new_df.index, dtype="object")
    _invalidate_downstream(entry, keep_normality=False)
    dataset_store.replace_df(payload.job_id, new_df)
    # Drop the cleanup note + backup so the undo is permanent and the
    # next /classify call doesn't re-strip the same column.
    notes = dict(entry.meta.get("cleanup_notes") or {})
    notes.pop(payload.column, None)
    entry.meta["cleanup_notes"] = notes
    new_backups = dict(backups)
    new_backups.pop(payload.column, None)
    entry.meta["cleanup_backups"] = new_backups
    suppressed = list(entry.meta.get("cleanup_suppressed") or [])
    if payload.column not in suppressed:
        suppressed.append(payload.column)
    entry.meta["cleanup_suppressed"] = suppressed
    # Force a fresh classify so the type badge updates from Scale →
    # whatever the original text values warrant (usually nominal).
    entry.meta.pop("classifications", None)
    return {"status": "restored", "column": payload.column, "removed_columns": derived_columns}


# ---------------------------------------------------------------------------
# Step 4 — Variable assignment (outcome / group / covariates)
# ---------------------------------------------------------------------------


class AssignRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    outcome: Optional[str] = Field(default=None, max_length=200)
    group: Optional[str] = Field(default=None, max_length=200)
    covariates: List[str] = Field(default_factory=list, max_length=20)


def _invalidate_downstream(entry, *, keep_normality: bool = False) -> None:
    """Drop cached plan/results (and optionally normality) when an upstream
    decision changes, so we never run on stale assumptions."""
    for k in ("plan", "results", "correlation_plan", "correlation_results"):
        entry.meta.pop(k, None)
    if not keep_normality:
        entry.meta.pop("normality", None)


@router.post("/assign")
async def save_assignment(payload: AssignRequest) -> Dict[str, Any]:
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    cols = set(entry.df.columns)
    if payload.outcome and payload.outcome not in cols:
        raise HTTPException(status_code=400, detail=f"Outcome '{payload.outcome}' not in dataset.")
    if payload.group and payload.group not in cols:
        raise HTTPException(status_code=400, detail=f"Group '{payload.group}' not in dataset.")
    bad = [c for c in payload.covariates if c not in cols]
    if bad:
        raise HTTPException(status_code=400, detail=f"Unknown covariate(s): {', '.join(bad)}")
    new_assignment = {
        "outcome": payload.outcome,
        "group": payload.group,
        "covariates": list(payload.covariates),
    }
    if entry.meta.get("assignment") != new_assignment:
        # Assignment changed — plan & results are stale. Normality (per-column)
        # is still valid since the column data hasn't changed.
        _invalidate_downstream(entry, keep_normality=True)
    entry.meta["assignment"] = new_assignment
    return {"status": "saved", "assignment": entry.meta["assignment"]}


# ---------------------------------------------------------------------------
# Step 5 — Normality
# ---------------------------------------------------------------------------


@router.get("/normality/{job_id}")
async def get_normality(job_id: str) -> Dict[str, Any]:
    entry = dataset_store.get(job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    classifications = entry.meta.get("classifications") or variable_classifier.classify_dataframe(entry.df)
    entry.meta["classifications"] = classifications
    out = await asyncio.to_thread(
        normality_service.normality_for_dataset, entry.df, classifications, True
    )
    entry.meta["normality"] = out
    return {"job_id": job_id, **out}


class NormalityOverrideRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    column: str = Field(..., min_length=1, max_length=200)
    decision: Literal["normal", "non_normal"]


@router.post("/normality/override")
async def override_normality(payload: NormalityOverrideRequest) -> Dict[str, Any]:
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    norm = entry.meta.get("normality") or {"columns": []}
    found = False
    for row in norm.get("columns") or []:
        if row.get("column") == payload.column:
            row["decision"] = payload.decision
            row["overridden"] = True
            row["note"] = (row.get("note") or "") + " (Manually overridden by user.)"
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail=f"Column '{payload.column}' not in normality results.")
    entry.meta["normality"] = norm
    # Plan & results depend on per-column normality verdicts → invalidate them.
    entry.meta.pop("plan", None)
    entry.meta.pop("results", None)
    return {"status": "overridden", "column": payload.column, "decision": payload.decision}


# ---------------------------------------------------------------------------
# Step 6 — Plan and Run
# ---------------------------------------------------------------------------


@router.get("/generate-plan/{job_id}")
async def generate_plan(job_id: str) -> Dict[str, Any]:
    entry = dataset_store.get(job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    classifications = entry.meta.get("classifications") or variable_classifier.classify_dataframe(entry.df)
    entry.meta["classifications"] = classifications
    assignment = entry.meta.get("assignment") or {}
    normality_data = entry.meta.get("normality")
    if not normality_data:
        normality_data = await asyncio.to_thread(
            normality_service.normality_for_dataset, entry.df, classifications, False
        )
        entry.meta["normality"] = normality_data
    session_view = _build_session_view(entry, classifications, assignment)
    plan_dict = await asyncio.to_thread(
        plan_service.generate_plan,
        entry.df, classifications, assignment, normality_data, session=session_view,
    )
    entry.meta["plan"] = plan_dict
    return {"job_id": job_id, "assignment": assignment, "plan": plan_dict}


class RunAnalysisRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    confirmed_test_ids: List[str] = Field(default_factory=list, max_length=50)
    confirmed_graph_ids: List[str] = Field(default_factory=list, max_length=50)


@router.post("/run-analysis")
async def run_analysis(payload: RunAnalysisRequest) -> Dict[str, Any]:
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    classifications = entry.meta.get("classifications") or variable_classifier.classify_dataframe(entry.df)
    assignment = entry.meta.get("assignment") or {}
    plan_dict = entry.meta.get("plan")
    if not plan_dict:
        normality_data = entry.meta.get("normality") or await asyncio.to_thread(
            normality_service.normality_for_dataset, entry.df, classifications, False
        )
        session_view = _build_session_view(entry, classifications, assignment)
        plan_dict = await asyncio.to_thread(
            plan_service.generate_plan,
            entry.df, classifications, assignment, normality_data, session=session_view,
        )
        entry.meta["plan"] = plan_dict
    session_view = _build_session_view(entry, classifications, assignment)
    res = await asyncio.to_thread(
        results_service.run_plan,
        entry.df, classifications, assignment, plan_dict,
        confirmed_test_ids=payload.confirmed_test_ids or None,
        confirmed_graph_ids=payload.confirmed_graph_ids or None,
        session=session_view,
    )
    entry.meta["results"] = res
    _title = (entry.meta.get("study_description") or "").strip() or "Untitled analysis"
    _var_count = sum(
        1 for c in (entry.meta.get("classifications") or [])
        if c.get("detected_type") not in ("id",)
    )
    dataset_store.mark_completed(payload.job_id, _title, _var_count)
    return {"job_id": payload.job_id, "results": res}


# ---------------------------------------------------------------------------
# Category near-duplicate detection + merge (Step 3 quality gate)
# ---------------------------------------------------------------------------


class DetectDupesRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)


@router.post("/detect-category-dupes")
async def detect_category_dupes(payload: DetectDupesRequest) -> Dict[str, Any]:
    """Scan every nominal/ordinal column for near-duplicate category labels."""
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    classifications = (
        entry.meta.get("classifications")
        or variable_classifier.classify_dataframe(entry.df)
    )
    entry.meta["classifications"] = classifications
    result = await asyncio.to_thread(
        category_merger.detect_all_columns, entry.df, classifications
    )
    return {"job_id": payload.job_id, "columns": result}


class MergeItem(BaseModel):
    column: str = Field(..., min_length=1, max_length=200)
    canonical: str = Field(..., min_length=1, max_length=500)
    members: List[str] = Field(default_factory=list, max_length=200)


class ApplyMergeRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    merges: List[MergeItem] = Field(default_factory=list, max_length=100)


@router.post("/apply-category-merge")
async def apply_category_merge(payload: ApplyMergeRequest) -> Dict[str, Any]:
    """Apply approved merge decisions to the in-memory dataset."""
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    if not payload.merges:
        return {"status": "no_changes", "actions": []}
    merges_dicts = [m.model_dump() for m in payload.merges]
    new_df, actions = await asyncio.to_thread(
        category_merger.apply_merges, entry.df, merges_dicts
    )
    entry.df = new_df
    # Downstream artefacts are now stale
    _invalidate_downstream(entry, keep_normality=False)
    for key in ("classifications", "variable_issues", "auto_coding_plan"):
        entry.meta.pop(key, None)
    # Record merge actions in cleaning log for export
    existing_cleaning = list(entry.meta.get("cleaning_actions") or [])
    existing_cleaning.extend(actions)
    entry.meta["cleaning_actions"] = existing_cleaning
    return {"status": "applied", "actions": actions, "n_merges": len(actions)}


# ---------------------------------------------------------------------------
# Chapter V — thesis-format export
# ---------------------------------------------------------------------------


@router.get("/export/{job_id}/chapter_v_word")
async def export_chapter_v_word(job_id: str) -> Response:
    """Download Chapter V — Results as thesis-format DOCX (TNR 12pt, 1.5 spacing)."""
    entry = dataset_store.get(job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    res = entry.meta.get("results")
    if not res:
        raise HTTPException(
            status_code=400,
            detail="No results available — run the analysis first.",
        )
    payload_bytes = await asyncio.to_thread(
        export_service.generate_chapter_v_word,
        entry, res, entry.meta.get("assignment") or {},
    )
    filename = f"chapter_v_results_{job_id[:8]}.docx"
    return Response(
        content=payload_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/{job_id}/chapter_v_pdf")
async def export_chapter_v_pdf(job_id: str) -> Response:
    """Download Chapter V — Results as thesis-format PDF (TNR equivalent, 1.5 spacing)."""
    entry = dataset_store.get(job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    res = entry.meta.get("results")
    if not res:
        raise HTTPException(
            status_code=400,
            detail="No results available — run the analysis first.",
        )
    payload_bytes = await asyncio.to_thread(
        export_service.generate_chapter_v_pdf,
        entry, res, entry.meta.get("assignment") or {},
    )
    filename = f"chapter_v_results_{job_id[:8]}.pdf"
    return Response(
        content=payload_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Step 8 — Export
# ---------------------------------------------------------------------------


@router.get("/export/{job_id}/{fmt}")
async def export(job_id: str, fmt: str) -> Response:
    entry = dataset_store.get(job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    exporter = export_service.EXPORTERS.get(fmt.lower())
    if not exporter:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {fmt}. Use word/pdf/excel.")
    res = entry.meta.get("results")
    if not res:
        raise HTTPException(status_code=400, detail="No results available — run the analysis on Step 7 first.")
    fn, mime, ext = exporter
    payload_bytes = fn(entry, res, entry.meta.get("assignment") or {})
    filename = f"medras_results_{job_id[:8]}.{ext}"
    return Response(
        content=payload_bytes,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# AI Bridge — study type + outcome column identification (T002)
# ---------------------------------------------------------------------------


class AiBridgeRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    description: str = Field(default="", max_length=2000)
    outcome_hint: str = Field(default="", max_length=200)
    study_type_hint: Optional[str] = Field(default=None, max_length=50)


@router.post("/ai-bridge")
@limiter.limit("15/minute")
async def ai_bridge(request: Request, payload: AiBridgeRequest) -> Dict[str, Any]:
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    classifications = (
        entry.meta.get("classifications")
        or variable_classifier.classify_dataframe(entry.df)
    )
    entry.meta["classifications"] = classifications
    columns = list(entry.df.columns)
    result = ai_bridge_service.identify_study(
        description=payload.description,
        outcome_hint=payload.outcome_hint,
        columns=columns,
        classifications=classifications,
        study_type_hint=payload.study_type_hint or None,
        external_ai_consent=request.headers.get("X-External-AI-Consent", "").lower() == "true",
    )
    return result


class AdjustAnalysisRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    user_message: str = Field(..., min_length=1, max_length=1000)
    current_study_type: str = Field(default="correlation", max_length=50)
    current_outcome_col: Optional[str] = Field(default=None, max_length=200)


@router.post("/adjust-analysis")
@limiter.limit("10/minute")
async def adjust_analysis(request: Request, payload: AdjustAnalysisRequest) -> Dict[str, Any]:
    """Re-run the AI bridge using the researcher's plain-English correction."""
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    classifications = (
        entry.meta.get("classifications")
        or variable_classifier.classify_dataframe(entry.df)
    )
    entry.meta["classifications"] = classifications
    columns = list(entry.df.columns)
    result = ai_bridge_service.identify_study(
        description=payload.user_message,
        outcome_hint=payload.current_outcome_col or "",
        columns=columns,
        classifications=classifications,
        study_type_hint=None,  # researcher is explicitly overriding; ignore old hint
        external_ai_consent=request.headers.get("X-External-AI-Consent", "").lower() == "true",
    )
    return result


class ConfirmStudyRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    study_type: str = Field(..., max_length=50)
    outcome_col: Optional[str] = Field(default=None, max_length=200)


@router.post("/confirm-study")
async def confirm_study(payload: ConfirmStudyRequest) -> Dict[str, Any]:
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    if payload.outcome_col and payload.outcome_col not in entry.df.columns:
        raise HTTPException(
            status_code=400,
            detail=f"Column '{payload.outcome_col}' not found in dataset.",
        )
    entry.meta["confirmed_study_type"] = payload.study_type
    entry.meta["confirmed_outcome_col"] = payload.outcome_col
    entry.meta["ai_study"] = {
        "study_type": payload.study_type,
        "outcome_col": payload.outcome_col,
        "source": "confirmed",
    }
    # Apply yes/no standardisation whenever a study is confirmed (T004)
    df, yn_notes = variable_classifier.clean_yes_no_columns(entry.df)
    if yn_notes:
        _invalidate_downstream(entry, keep_normality=False)
        dataset_store.replace_df(payload.job_id, df)
        entry.meta["yesno_cleaning_notes"] = yn_notes
        entry.meta.pop("classifications", None)  # force re-classify on cleaned data
    return {
        "status": "confirmed",
        "study_type": payload.study_type,
        "outcome_col": payload.outcome_col,
        "yesno_cleaned": list(yn_notes.keys()),
    }


# ---------------------------------------------------------------------------
# Run Correlation — pairwise all-vs-outcome (T005 / T006)
# ---------------------------------------------------------------------------


class RunCorrelationRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    outcome_col: str = Field(..., min_length=1, max_length=200)


@router.post("/run-correlation")
@limiter.limit("10/minute")
async def run_correlation(
    request: Request, payload: RunCorrelationRequest
) -> Dict[str, Any]:
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    if payload.outcome_col not in entry.df.columns:
        raise HTTPException(
            status_code=400,
            detail=f"Column '{payload.outcome_col}' not found in dataset.",
        )
    classifications = (
        entry.meta.get("classifications")
        or variable_classifier.classify_dataframe(entry.df)
    )
    entry.meta["classifications"] = classifications

    corr_plan = await asyncio.to_thread(
        plan_service.generate_correlation_plan,
        entry.df, classifications, payload.outcome_col,
    )
    entry.meta["correlation_plan"] = corr_plan

    corr_results = await asyncio.to_thread(
        results_service.run_correlation_plan,
        entry.df, classifications, corr_plan,
    )

    # Build methods_text so the Word export has a populated Methods section
    missing_actions = entry.meta.get("missing_decision_actions") or []
    methods_lines = [
        "All statistical analyses were performed using Python (scipy, statsmodels). "
        "A two-tailed p-value < 0.05 was considered statistically significant. "
        "Categorical variables were expressed as frequencies and percentages; "
        "continuous variables as median (IQR) or mean ± SD depending on normality. "
        "Associations between each predictor variable and the outcome were evaluated "
        "using Chi-square or Fisher's exact test (categorical predictors), "
        "and Mann-Whitney U or Kruskal-Wallis test (continuous/ordinal predictors)."
    ]
    if missing_actions:
        methods_lines.append(
            "Missing data were handled as follows: " + " ".join(missing_actions)
        )
    corr_results["methods_text"] = " ".join(methods_lines)

    entry.meta["correlation_results"] = corr_results

    return {"job_id": payload.job_id, "results": corr_results}


@router.get("/export-correlation/{job_id}")
async def export_correlation(job_id: str) -> Response:
    entry = dataset_store.get(job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    corr_results = entry.meta.get("correlation_results")
    if not corr_results:
        raise HTTPException(
            status_code=400,
            detail="No correlation results found — run pairwise analysis first.",
        )
    docx_bytes = export_service.generate_correlation_chapter_word(entry, corr_results)
    filename = f"medras_correlation_{job_id[:8]}.docx"
    return Response(
        content=docx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Outcome value counts (for plan confirmation screen)
# ---------------------------------------------------------------------------


@router.get("/value-counts/{job_id}")
async def value_counts(job_id: str, column: str = Query(..., min_length=1, max_length=200)) -> Dict[str, Any]:
    entry = dataset_store.get(job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    if column not in entry.df.columns:
        raise HTTPException(status_code=400, detail=f"Column '{column}' not found.")
    raw = entry.df[column].dropna().astype(str).value_counts().to_dict()
    total = int(entry.df[column].notna().sum())
    return {
        "column": column,
        "total": total,
        "counts": {str(k): int(v) for k, v in raw.items()},
    }


# ---------------------------------------------------------------------------
# Apply missing data decisions (T003)
# ---------------------------------------------------------------------------


class MissingDecision(BaseModel):
    column: str = Field(..., min_length=1, max_length=200)
    action: Literal["drop_rows", "impute_mean", "impute_median", "impute_mode", "leave"] = "leave"


class ApplyMissingRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    decisions: List[MissingDecision] = Field(default_factory=list, max_length=100)


@router.post("/apply-missing-decisions")
async def apply_missing_decisions(
    payload: ApplyMissingRequest,
) -> Dict[str, Any]:
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    df = entry.df.copy()
    actions_taken: List[str] = []
    for dec in payload.decisions:
        col = dec.column
        if col not in df.columns:
            continue
        if dec.action == "drop_rows":
            before = len(df)
            df = df.dropna(subset=[col])
            after = len(df)
            actions_taken.append(
                f"Dropped {before - after} rows with missing {col}."
            )
        elif dec.action == "impute_mean":
            mean_val = pd.to_numeric(df[col], errors="coerce").mean()
            if pd.notna(mean_val):
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(mean_val)
                actions_taken.append(
                    f"Imputed missing {col} with mean ({mean_val:.2f})."
                )
        elif dec.action == "impute_median":
            med = pd.to_numeric(df[col], errors="coerce").median()
            if pd.notna(med):
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(med)
                actions_taken.append(
                    f"Imputed missing {col} with median ({med:.2f})."
                )
        elif dec.action == "impute_mode":
            mode_val = df[col].mode()
            if not mode_val.empty:
                df[col] = df[col].fillna(mode_val.iloc[0])
                actions_taken.append(
                    f"Imputed missing {col} with mode ({mode_val.iloc[0]})."
                )
    if actions_taken:
        _invalidate_downstream(entry, keep_normality=False)
        dataset_store.replace_df(payload.job_id, df)
        entry.meta.pop("classifications", None)
    # Persist the human-readable action log so the Methods section can include it
    entry.meta["missing_decision_actions"] = actions_taken
    return {"status": "applied", "actions": actions_taken, "n_rows": len(df)}


# ---------------------------------------------------------------------------
# Unified AI chat endpoint — variables | normality | plan | results
# ---------------------------------------------------------------------------


class AiChatRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    kind: str = Field(..., pattern="^(variables|missing|normality|plan|results)$")
    message: str = Field(..., min_length=1, max_length=600)
    selected_decisions: Dict[str, str] = Field(default_factory=dict)


@router.post("/ai-chat")
@limiter.limit("60/minute")
async def ai_chat_unified(request: Request, payload: AiChatRequest) -> Dict[str, Any]:
    """Unified AI chatbox endpoint — routes supported assistants to ai_chatbox.chat()."""
    ctx = _chatbox_context(payload.job_id, payload.kind, payload.selected_decisions)
    external_ai_consent = request.headers.get("X-External-AI-Consent", "").lower() == "true"
    return await ai_chatbox.chat(
        payload.kind, payload.message, ctx, external_ai_consent=external_ai_consent
    )


# ---------------------------------------------------------------------------
# Study setup — plain-English description → study type + outcome column
# ---------------------------------------------------------------------------


class SetupStudyRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    description: str = Field(default="", max_length=2000)
    outcome_hint: str = Field(default="", max_length=200)


@router.post("/setup-study")
@limiter.limit("10/minute")
async def setup_study(request: Request, payload: SetupStudyRequest) -> Dict[str, Any]:
    """AI reads a plain-English study description and identifies study type + outcome.

    Returns the same shape as ``/ai-bridge`` and stores the result in the session.
    Use in place of or alongside ``/ai-bridge`` when the researcher has typed a
    description on the AI-confirm / setup screen.
    """
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    classifications = (
        entry.meta.get("classifications")
        or variable_classifier.classify_dataframe(entry.df)
    )
    entry.meta["classifications"] = classifications
    columns = list(entry.df.columns)
    n_rows = len(entry.df)
    result = await ai_chatbox.plan_study_setup(
        description=payload.description,
        columns=columns,
        classifications=classifications,
        n_rows=n_rows,
        external_ai_consent=request.headers.get("X-External-AI-Consent", "").lower() == "true",
    )
    # Augment with outcome_hint if provided and AI didn't detect an outcome
    if payload.outcome_hint.strip() and not result.get("outcome_col"):
        result["outcome_col"] = payload.outcome_hint.strip()
    return result


# ---------------------------------------------------------------------------
# Adjust setup — inline correction loop for screen-setup
# ---------------------------------------------------------------------------


class AdjustSetupRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    description: str = Field(default="", max_length=2000)
    correction: str = Field(default="", max_length=1000)
    outcome_hint: str = Field(default="", max_length=200)


@router.post("/adjust-setup")
@limiter.limit("10/minute")
async def adjust_setup(request: Request, payload: AdjustSetupRequest) -> Dict[str, Any]:
    """Inline correction loop for screen-setup.

    Combines the researcher's original description with a correction hint and
    calls ``plan_study_setup`` to return an updated rich plan.  Results are
    returned as a suggestion; it is persisted only after explicit confirmation.
    """
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    classifications = (
        entry.meta.get("classifications")
        or variable_classifier.classify_dataframe(entry.df)
    )
    entry.meta["classifications"] = classifications
    columns = list(entry.df.columns)
    n_rows = len(entry.df)
    # Merge stored description + correction into the new prompt
    stored_desc = entry.meta.get("study_description") or ""
    merged = " ".join(filter(None, [
        payload.description or stored_desc,
        payload.correction,
    ]))
    result = await ai_chatbox.plan_study_setup(
        description=merged,
        columns=columns,
        classifications=classifications,
        n_rows=n_rows,
        external_ai_consent=request.headers.get("X-External-AI-Consent", "").lower() == "true",
    )
    if payload.outcome_hint.strip() and not result.get("outcome_col"):
        result["outcome_col"] = payload.outcome_hint.strip()
    return result


# ---------------------------------------------------------------------------
# Handle missing — apply missing-data decisions (named alias)
# ---------------------------------------------------------------------------


class HandleMissingRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    decisions: List[MissingDecision] = Field(default_factory=list, max_length=100)


@router.post("/handle-missing")
async def handle_missing(payload: HandleMissingRequest) -> Dict[str, Any]:
    """Named alias for ``/apply-missing-decisions``.

    Accepts the same payload and produces the same response; exists so the
    ``screen-missing`` frontend can call a semantically distinct endpoint.
    """
    return await apply_missing_decisions(
        ApplyMissingRequest(job_id=payload.job_id, decisions=payload.decisions)
    )


# ---------------------------------------------------------------------------
# Partial re-run — true delta: run only new tests, merge into existing results
# ---------------------------------------------------------------------------


class RerunPartialRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    add_test_ids: List[str] = Field(default_factory=list, max_length=20)
    remove_test_ids: List[str] = Field(default_factory=list, max_length=20)


@router.post("/rerun-partial")
@limiter.limit("10/minute")
async def rerun_partial(request: Request, payload: RerunPartialRequest) -> Dict[str, Any]:
    """True delta re-run: execute only the requested new tests and merge.

    - ``add_test_ids``: tests to run and splice into existing results.
    - ``remove_test_ids``: tests to drop from the existing results.
    No existing test is re-run unless it is listed in ``add_test_ids``.
    """
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")

    classifications = (
        entry.meta.get("classifications")
        or variable_classifier.classify_dataframe(entry.df)
    )
    assignment = entry.meta.get("assignment") or {}
    plan_dict = entry.meta.get("plan")
    if not plan_dict:
        raise HTTPException(
            status_code=400,
            detail="No plan found — complete the plan step before requesting a re-run.",
        )

    # Index existing test RESULTS so we can merge without re-running them.
    existing_results: Dict[str, Any] = entry.meta.get("results") or {}
    existing_tests_by_id: Dict[str, Any] = {
        t["id"]: t for t in (existing_results.get("tests") or [])
    }

    remove_set = set(payload.remove_test_ids)

    # Build a mini-plan for ALL add_test_ids so the researcher can force-rerun
    # an existing comparison as well as add new ones.
    plan_tests_by_id: Dict[str, Any] = {
        t["id"]: t for t in (plan_dict.get("tests") or [])
    }
    new_test_entries: List[Dict[str, Any]] = []
    for tid in payload.add_test_ids:
        if tid in remove_set:
            # Contradictory request — skip
            continue
        existing_plan_entry = plan_tests_by_id.get(tid)
        if existing_plan_entry:
            # Reuse the stored plan metadata (title, columns, parametric flag).
            new_test_entries.append(dict(existing_plan_entry))
        else:
            new_test_entries.append({
                "id": tid,
                "title": tid.replace("_", " ").title(),
                "why": "Added via Results assistant.",
                "columns": list(filter(None, [
                    assignment.get("outcome"),
                    assignment.get("group"),
                ])),
                "parametric": None,
            })

    # Execute only the new tests (delta run).
    if new_test_entries:
        mini_plan: Dict[str, Any] = {
            "tests": new_test_entries,
            "graphs": [],
            "outputs": [],
            "summary": "",
        }
        session_view = _build_session_view(entry, classifications, assignment)
        delta_res = await asyncio.to_thread(
            results_service.run_plan,
            entry.df,
            classifications,
            assignment,
            mini_plan,
            confirmed_test_ids=[t["id"] for t in new_test_entries],
            confirmed_graph_ids=[],
            session=session_view,
        )
        for new_t in (delta_res.get("tests") or []):
            existing_tests_by_id[new_t["id"]] = new_t

    # Remove dropped tests.
    for rid in remove_set:
        existing_tests_by_id.pop(rid, None)

    # Build and store the merged results dict.
    merged_results = dict(existing_results)
    merged_results["tests"] = list(existing_tests_by_id.values())
    entry.meta["results"] = merged_results

    # Keep the stored plan in sync (add new entries, drop removed ones).
    updated_plan = dict(plan_dict)
    plan_tests = [t for t in (plan_dict.get("tests") or []) if t["id"] not in remove_set]
    for t in new_test_entries:
        if not any(p["id"] == t["id"] for p in plan_tests):
            plan_tests.append(t)
    updated_plan["tests"] = plan_tests
    entry.meta["plan"] = updated_plan

    return {"job_id": payload.job_id, "results": merged_results}


@router.post("/analyze")
@limiter.limit("30/minute")
async def analyze(request: Request, payload: AnalyzeRequest) -> Dict[str, Any]:
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    classifications = entry.meta.get("classifications") or variable_classifier.classify_dataframe(entry.df)
    df = variable_classifier.encode_for_analysis(entry.df, classifications)
    try:
        result = await asyncio.to_thread(
            stats_tests.run_primary_analysis,
            df,
            outcome=payload.outcome,
            group=payload.group,
            classifications=classifications,
            alpha=payload.alpha,
        )
    except Exception:  # noqa: BLE001 - guard against stats library failures
        # Log full traceback server-side; return a generic message to the client
        # so we never leak internal library error text.
        log.exception("analysis_failed", outcome=payload.outcome, group=payload.group)
        raise HTTPException(
            status_code=500,
            detail="The analysis could not be completed. Please try a different "
            "outcome or group variable.",
        )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ---------------------------------------------------------------------------
# Task 2 — Plain-English document correction system
# ---------------------------------------------------------------------------


class CorrectionRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    instructions: str = Field(..., min_length=1, max_length=2000)


@router.post("/apply-corrections")
@limiter.limit("20/minute")
async def apply_corrections(
    request: Request, payload: CorrectionRequest,
) -> Dict[str, Any]:
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    results = entry.meta.get("results")
    if not results:
        raise HTTPException(
            status_code=400,
            detail="No results available — run the analysis first.",
        )
    inventory = doc_correction.get_document_inventory(entry, results)
    actions = doc_correction._call_openai_correction(payload.instructions, inventory)
    if actions is None:
        raise HTTPException(
            status_code=503,
            detail="Could not parse the correction instructions. Please rephrase and try again.",
        )
    applied, skipped = doc_correction.apply_correction_actions(entry, actions)
    version_num = doc_correction.record_correction_version(
        entry, payload.instructions, applied, skipped,
    )
    return {
        "version": version_num,
        "applied": applied,
        "skipped": skipped,
        "total_actions": len(actions),
    }


@router.get("/correction-versions/{job_id}")
async def correction_versions(job_id: str) -> Dict[str, Any]:
    entry = dataset_store.get(job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    return {"versions": doc_correction.get_correction_versions(entry)}


class RestoreVersionRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    version: int = Field(..., ge=1)


@router.post("/restore-version")
async def restore_correction_version(payload: RestoreVersionRequest) -> Dict[str, Any]:
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    ok = doc_correction.restore_version(entry, payload.version)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Version {payload.version} not found.",
        )
    return {"status": "restored", "version": payload.version}


# ---------------------------------------------------------------------------
# Session history — recent analyses + restore
# ---------------------------------------------------------------------------


@router.get("/recent-sessions")
async def recent_sessions() -> Dict[str, Any]:
    """Return the last 5 completed analysis sessions for the home-screen history."""
    return {"sessions": dataset_store.list_recent(5)}


@router.get("/restore/{job_id}")
async def restore_session(job_id: str) -> Dict[str, Any]:
    """Touch a session (reset its 15-day TTL) and return metadata for the client.

    The client uses the returned job_id to jump directly to the Export screen.
    Returns 404 with a user-friendly message if the session has expired.
    """
    entry = dataset_store.get(job_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "This analysis has expired after 15 days. Please upload your "
                "data again to run a new analysis. Your previous Word document "
                "is still available if you saved it to your computer."
            ),
        )
    title = (
        getattr(entry, "session_title", None)
        or entry.meta.get("study_description")
        or "Untitled analysis"
    )
    var_count = (
        getattr(entry, "variable_count", None)
        or sum(
            1 for c in (entry.meta.get("classifications") or [])
            if c.get("detected_type") not in ("id",)
        )
    )
    return {
        "job_id": job_id,
        "title": title,
        "variable_count": var_count,
        "expires_in_days": 15.0,
    }
