"""Practice Data Wizard — backend routes.

Adds a 4-step wizard (objective + variables + sample-size + special
instructions) on top of the existing template-based dummy-data flow. The
wizard produces a custom DataFrame and a formatted Excel file, and can
hand the result off to the analysis pipeline by registering it with
`dataset_store` (same `is_dummy` flag the template flow uses, plus an
extra `is_practice_wizard` marker so the Excel export can show the red
disclaimer).
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.core.limiter import limiter
from app.services import data_generator, dataset_store


router = APIRouter(prefix="/practice", tags=["practice"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class VariableInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    # Restrict to the three types the generator actually supports — anything
    # else previously fell through to "scale" silently and produced confusing
    # data. Pydantic now rejects unknown values up front.
    type: Optional[Literal["scale", "binary", "nominal"]] = None
    min: Optional[float] = None
    max: Optional[float] = None
    percent: Optional[float] = Field(default=None, ge=0, le=100)
    levels: Optional[List[str]] = Field(default=None, max_length=12)
    is_outcome: Optional[bool] = False


class GenerateRequest(BaseModel):
    objective: str = Field(default="", max_length=600)
    outcome: str = Field(default="", max_length=120)
    variables: List[VariableInput] = Field(default_factory=list, max_length=40)
    n: int = Field(default=60, ge=20, le=500)
    expected_effect: str = Field(default="", max_length=400)
    instructions: str = Field(default="", max_length=800)
    missing_pct: float = Field(default=5.0, ge=0.0, le=30.0)
    seed: Optional[int] = Field(default=None, ge=0, le=2**31 - 1)


class DetectRequest(BaseModel):
    text: str = Field(default="", max_length=2000)


# ---------------------------------------------------------------------------
# In-process store of generated practice datasets keyed by job_id.
# We re-use `dataset_store` so the analysis pipeline can pick the dataset
# up by the same job_id it would get from a normal upload.
# ---------------------------------------------------------------------------


def _spec_from(payload: GenerateRequest) -> data_generator.GenerateSpec:
    vs: List[data_generator.VariableSpec] = []
    for v in payload.variables:
        vs.append(
            data_generator.VariableSpec(
                name=v.name,
                type=(v.type or data_generator.detect_type(v.name)).lower(),
                min=v.min,
                max=v.max,
                percent=v.percent,
                levels=list(v.levels or []),
                is_outcome=bool(v.is_outcome),
            )
        )
    return data_generator.GenerateSpec(
        objective=payload.objective,
        outcome=payload.outcome,
        variables=vs,
        n=payload.n,
        expected_effect=payload.expected_effect,
        instructions=payload.instructions,
        seed=payload.seed,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/detect-types")
@limiter.limit("60/minute")
async def detect_types(request: Request, payload: DetectRequest) -> Dict[str, Any]:
    """Auto-detect type for each line in the user's free-text variable list."""
    return {"variables": data_generator.parse_variable_list(payload.text)}


@router.post("/generate")
@limiter.limit("20/minute")
async def generate(request: Request, payload: GenerateRequest) -> Dict[str, Any]:
    if not payload.variables:
        raise HTTPException(status_code=400, detail="At least one variable is required.")

    spec = _spec_from(payload)
    df = data_generator.generate_dataset(spec, missing_pct=payload.missing_pct)

    meta: Dict[str, Any] = {
        "filename": "practice_dataset.xlsx",
        "size_bytes": 0,
        "rows": int(df.shape[0]),
        "cols": int(df.shape[1]),
        "sheet_names": [],
        "selected_sheet": None,
        "is_dummy": True,
        "is_practice_wizard": True,
        "practice_objective": payload.objective,
        "practice_outcome": payload.outcome,
        "practice_expected_effect": payload.expected_effect,
        "practice_instructions": payload.instructions,
    }
    job_id = dataset_store.put(df, meta)

    return {
        "job_id": job_id,
        "rows": int(df.shape[0]),
        "cols": int(df.shape[1]),
        "columns": list(df.columns),
        "sample": df.head(5).fillna("").to_dict(orient="records"),
        "missing_pct": float(payload.missing_pct),
        "objective": payload.objective,
        "outcome": payload.outcome,
        "expected_effect": payload.expected_effect,
        "instructions": payload.instructions,
        "download_url": f"/api/practice/{job_id}/excel",
    }


@router.get("/{job_id}/excel")
async def download_excel(job_id: str) -> Response:
    entry = dataset_store.get(job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Practice dataset expired or not found.")
    study = (entry.meta.get("practice_objective") or "Practice dataset")[:80]
    payload_bytes = data_generator.save_to_excel(entry.df, study_name=study)
    filename = f"medras_practice_{job_id[:8]}.xlsx"
    return Response(
        content=payload_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{job_id}")
async def info(job_id: str) -> Dict[str, Any]:
    entry = dataset_store.get(job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Practice dataset expired or not found.")
    if not entry.meta.get("is_practice_wizard"):
        raise HTTPException(status_code=404, detail="Not a wizard dataset.")
    return {
        "job_id": job_id,
        "rows": int(entry.df.shape[0]),
        "cols": int(entry.df.shape[1]),
        "columns": list(entry.df.columns),
        "objective": entry.meta.get("practice_objective", ""),
        "outcome": entry.meta.get("practice_outcome", ""),
        "expected_effect": entry.meta.get("practice_expected_effect", ""),
        "instructions": entry.meta.get("practice_instructions", ""),
    }
