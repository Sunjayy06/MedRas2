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

import io
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app.core.limiter import limiter
from app.core.logging import get_logger
from app.services import (
    data_quality,
    dataset_store,
    dummy_data,
    excel_loader,
    stats_tests,
    variable_classifier,
)


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


class GenerateDummyRequest(BaseModel):
    template: TemplateLiteral
    n_patients: int = Field(default=150, ge=10, le=5000)
    n_groups: int = Field(default=2, ge=1, le=3)
    missing_pct: float = Field(default=5.0, ge=0.0, le=50.0)
    seed: Optional[int] = Field(default=None, ge=0, le=2**31 - 1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_response(job_id: str, entry) -> Dict[str, Any]:
    classifications = entry.meta.get("classifications") or variable_classifier.classify_dataframe(entry.df)
    entry.meta["classifications"] = classifications
    preview = excel_loader.preview_records(entry.df, n=5)
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
            "header_looks_numeric": bool(entry.meta.get("header_looks_numeric", False)),
            "is_dummy": bool(entry.meta.get("is_dummy", False)),
            "template": entry.meta.get("template"),
            "preview_confirmed": bool(entry.meta.get("preview_confirmed", False)),
            "follow_up_data": entry.meta.get("follow_up_data"),
        },
        "columns": columns,
        "classifications": classifications,
        "preview": preview,
        "repeated_ids": repeated_ids,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/templates")
def list_templates() -> Dict[str, Any]:
    return {"templates": dummy_data.list_templates()}


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
    meta["raw_bytes"] = raw
    dataset_store.update_meta(payload.job_id, **meta, classifications=None)
    entry = dataset_store.get(payload.job_id)
    return _build_response(payload.job_id, entry)


class ConfirmPreviewRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64)
    follow_up_data: Optional[bool] = None  # answer to "is this follow-up data?"


@router.post("/confirm-preview")
async def confirm_preview(payload: ConfirmPreviewRequest) -> Dict[str, Any]:
    """Lock the file-preview confirmation (Screen 2A step)."""
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    dataset_store.update_meta(
        payload.job_id,
        preview_confirmed=True,
        follow_up_data=payload.follow_up_data,
    )
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
    return data_quality.quality_report(entry.df, classifications=classifications)


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
    new_df, log_counts = data_quality.apply_actions(
        entry.df,
        actions=[a.model_dump() for a in payload.actions],
        remove_exact_duplicates=payload.remove_exact_duplicates,
    )
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
    classifications = variable_classifier.classify_dataframe(entry.df)
    # Apply user overrides on top of auto-classification.
    if payload.overrides:
        ov = {o.column: o.detected_type for o in payload.overrides}
        for c in classifications:
            if c["column"] in ov:
                c["detected_type"] = ov[c["column"]]
                c["reason"] = f"Manually set to {ov[c['column']]}."
    entry.meta["classifications"] = classifications
    return {"job_id": payload.job_id, "classifications": classifications}


@router.post("/analyze")
@limiter.limit("30/minute")
async def analyze(request: Request, payload: AnalyzeRequest) -> Dict[str, Any]:
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")
    classifications = entry.meta.get("classifications") or variable_classifier.classify_dataframe(entry.df)
    df = variable_classifier.encode_for_analysis(entry.df, classifications)
    try:
        result = stats_tests.run_primary_analysis(
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
