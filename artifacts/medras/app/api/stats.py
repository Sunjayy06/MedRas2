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
    proposal_store,
    stats_tests,
    variable_assistant,
    variable_classifier,
    variable_issues,
)


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
            "merged_sheets": entry.meta.get("merged_sheets") or [],
            "merge_group_column": entry.meta.get("merge_group_column"),
            "skipped_blank_sheets": entry.meta.get("skipped_blank_sheets") or [],
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
    # Pre-clean: extract numeric values from text cells like "2mm" /
    # "Grade 3" / "12 kg" so the classifier sees them as numeric (scale)
    # per the MedRAS biostatistician spec. The cleaner is idempotent —
    # already-numeric columns are skipped — so it is safe to invoke on
    # every classify call. The notes themselves are persisted on the
    # dataset entry so subsequent reclassifies can still surface them.
    cleaned_df, fresh_cleanup_notes = variable_classifier.clean_numeric_like_columns(entry.df)
    if fresh_cleanup_notes:
        dataset_store.replace_df(payload.job_id, cleaned_df)
        existing_notes = dict(entry.meta.get("cleanup_notes") or {})
        existing_notes.update(fresh_cleanup_notes)
        entry.meta["cleanup_notes"] = existing_notes
        # When the underlying df changed, any previously stored
        # classifications are no longer valid (the dtypes shifted) — so
        # force a full re-classify by ignoring the stored copy.
        entry.meta.pop("classifications", None)
        # Refresh the entry handle so we read the new df below.
        entry = dataset_store.get(payload.job_id)
        assert entry is not None
    cleanup_notes: Dict[str, str] = dict(entry.meta.get("cleanup_notes") or {})
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


@router.post("/variable-assistant")
@limiter.limit("60/minute")
async def variable_assistant_endpoint(
    request: Request, payload: VariableAssistantRequest
) -> Dict[str, Any]:
    entry = dataset_store.get(payload.job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dataset expired or not found.")

    columns = list(entry.df.columns)
    intent = variable_assistant.parse_intent(payload.message, columns)

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
        }

    new_df, meta = variable_assistant.apply_action(entry.df, intent)

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
            if c["column"] == target_col:
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
        "classifications": classifications,
        "issues": issues,
        "auto_coding_plan": coding,
        "blocking_issues": variable_issues.has_blocking_issues(issues),
    }


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
