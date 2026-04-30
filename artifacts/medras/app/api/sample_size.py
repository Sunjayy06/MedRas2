"""Sample Size Calculator routes.

Two endpoints power the module's three-step UI:

1. ``POST /api/sample-size/analyze``  — classify a research objective and
   suggest a formula.
2. ``POST /api/sample-size/calculate`` — run the chosen formula with the
   researcher's parameters and return the full breakdown (n, adjusted n,
   formula, constants, inputs, notes), plus an optional comparison against
   the researcher's expected sample size.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.core.limiter import limiter
from app.core.logging import get_logger
from app.services import sample_size as ss_engine
from app.services.objective_analyzer import VALID_FORMULAS, analyze_objective

log = get_logger(__name__)

router = APIRouter(prefix="/sample-size", tags=["sample-size"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    objective: str = Field(..., min_length=10, max_length=4000)


class AnalyzeResponse(BaseModel):
    objective: str
    detected_groups: int
    outcome_type: str
    study_design: str
    suggested_formula: str
    confidence: str
    rationale: str
    source: str
    warnings: List[str]


class CalculateRequest(BaseModel):
    formula: Literal[
        "single_proportion",
        "single_mean",
        "two_proportions",
        "two_means",
        "paired_means",
        "anova_means",
        "repeated_measures",
        "linear_regression",
        "prediction_model",
        "kappa_agreement",
        "roc_auc",
    ]
    parameters: Dict[str, Any]
    expected_sample_size: Optional[int] = Field(
        default=None,
        ge=1,
        le=1_000_000,
        description="Optional researcher-targeted sample size for comparison.",
    )

    @field_validator("parameters")
    @classmethod
    def parameters_not_empty(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if not value:
            raise ValueError("parameters cannot be empty")
        return value


class ExpectedComparison(BaseModel):
    expected_sample_size: int
    statistically_required_total: int
    adjusted_required_total: int
    meets_requirement: bool
    shortfall: int
    achieved_power_estimate: Optional[float] = None
    verdict: str


class CalculateResponse(BaseModel):
    formula: str
    formula_label: str
    formula_expression: str
    n_per_group: int
    number_of_groups: int
    total_n: int
    adjusted_n: int
    inputs: Dict[str, Any]
    constants: Dict[str, float]
    notes: List[str]
    expected_comparison: Optional[ExpectedComparison] = None


class ReverseRequest(BaseModel):
    formula: Literal[
        "single_proportion",
        "single_mean",
        "two_proportions",
        "two_means",
        "paired_means",
        "anova_means",
        "repeated_measures",
        "linear_regression",
        "prediction_model",
        "kappa_agreement",
        "roc_auc",
    ]
    parameters: Dict[str, Any]

    @field_validator("parameters")
    @classmethod
    def parameters_not_empty(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if not value:
            raise ValueError("parameters cannot be empty")
        return value


class HeadlineStat(BaseModel):
    label: str
    value: str
    sublabel: Optional[str] = None


class ReverseResponse(BaseModel):
    """Generic shape returned by every reverse-mode formula.

    ``headline`` is the 1-3 stats the UI shows at the top of the result
    panel; ``detectable`` carries the same values in raw form for callers
    that want to do further math.
    """

    formula: str
    mode: str
    formula_label: str
    formula_expression: str
    inputs: Dict[str, Any]
    constants: Dict[str, float]
    headline: List[HeadlineStat]
    detectable: Dict[str, Any]
    notes: List[str]
    warnings: List[str]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/analyze", response_model=AnalyzeResponse)
@limiter.limit("30/minute")
async def analyze_endpoint(payload: AnalyzeRequest, request: Request) -> AnalyzeResponse:
    """Classify the objective and suggest a sample-size formula."""
    try:
        result = analyze_objective(payload.objective)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    log.info(
        "sample_size.analyze",
        extra={
            "objective_length": len(payload.objective),
            "suggested_formula": result.suggested_formula,
            "source": result.source,
            "confidence": result.confidence,
        },
    )
    return AnalyzeResponse(**result.to_dict())


@router.post("/calculate", response_model=CalculateResponse)
@limiter.limit("60/minute")
async def calculate_endpoint(payload: CalculateRequest, request: Request) -> CalculateResponse:
    """Compute the minimum sample size for the selected formula."""
    if payload.formula not in VALID_FORMULAS:
        raise HTTPException(status_code=400, detail=f"Unknown formula: {payload.formula}")
    try:
        result = ss_engine.calculate(payload.formula, payload.parameters)
    except (TypeError, ValueError) as exc:
        # TypeError → wrong / extra parameter names; ValueError → out-of-range.
        raise HTTPException(status_code=400, detail=str(exc))

    expected_comparison: Optional[ExpectedComparison] = None
    if payload.expected_sample_size is not None:
        expected = payload.expected_sample_size
        meets = expected >= result.adjusted_n
        shortfall = max(0, result.adjusted_n - expected)
        expected_comparison = ExpectedComparison(
            expected_sample_size=expected,
            statistically_required_total=result.total_n,
            adjusted_required_total=result.adjusted_n,
            meets_requirement=meets,
            shortfall=shortfall,
            verdict=(
                "Your target sample size meets or exceeds the statistically "
                "required size."
                if meets
                else "Your target sample size is below the statistically "
                "required minimum — increase enrolment or accept reduced power."
            ),
        )

    log.info(
        "sample_size.calculate",
        extra={
            "formula": payload.formula,
            "n_per_group": result.n_per_group,
            "total_n": result.total_n,
            "adjusted_n": result.adjusted_n,
            "expected_provided": payload.expected_sample_size is not None,
        },
    )
    return CalculateResponse(
        **result.to_dict(),
        expected_comparison=expected_comparison,
    )


@router.post("/reverse", response_model=ReverseResponse)
@limiter.limit("60/minute")
async def reverse_endpoint(
    payload: ReverseRequest, request: Request
) -> ReverseResponse:
    """Back-calculate the smallest detectable effect for the chosen formula.

    Use this when the researcher knows how many participants they can recruit
    but does not have a pre-specified effect size (e.g. they don't know p₂,
    or the expected mean difference, or Cohen's f). The endpoint dispatches
    to the per-formula reverse function and returns a uniform shape with a
    ``headline`` array that the UI renders generically.
    """
    try:
        result = ss_engine.reverse_calculate(payload.formula, payload.parameters)
    except (TypeError, ValueError) as exc:
        # TypeError → wrong / extra parameter names; ValueError → out-of-range.
        raise HTTPException(status_code=400, detail=str(exc))

    log.info(
        "sample_size.reverse",
        extra={
            "formula": payload.formula,
            "warning_count": len(result.get("warnings", [])),
        },
    )
    return ReverseResponse(**result)
