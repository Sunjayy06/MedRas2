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
from app.services.objective_analyzer import (
    VALID_FORMULAS,
    VALID_STUDY_TYPES,
    analyze_objective,
)

log = get_logger(__name__)

router = APIRouter(prefix="/sample-size", tags=["sample-size"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


FormulaName = Literal[
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
    "correlation",
    "repeated_measures_anova",
    "survival_logrank",
]


class AnalyzeRequest(BaseModel):
    objective: str = Field(..., min_length=10, max_length=4000)
    # Optional explicit override from the Step 1 study-type dropdown.
    # "auto" or omitted = let the analyser decide.
    study_type: Optional[str] = Field(default=None, max_length=32)

    @field_validator("study_type")
    @classmethod
    def _check_study_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if value not in VALID_STUDY_TYPES:
            raise ValueError(f"Invalid study_type: {value}")
        return value


class StudyTypeRecommendation(BaseModel):
    """Built-in non-formulaic recommendation (qualitative/FGD/pilot/etc)."""

    label: str
    recommended_n: Optional[int] = None
    range: str
    rationale: str
    guidance: List[str]
    fallback_formula: Optional[str] = None


class AnalyzeResponse(BaseModel):
    objective: str
    detected_groups: int
    outcome_type: str
    study_design: str
    suggested_formula: str
    confidence: str
    rationale: str
    source: str
    study_type: str = "quantitative"
    suggested_dropout: float = 0.0
    study_type_recommendation: Optional[StudyTypeRecommendation] = None
    warnings: List[str]


class CalculateRequest(BaseModel):
    formula: FormulaName
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
    formula: FormulaName
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


def _apply_study_type_override(
    result, override: Optional[str]
):
    """If the user picked a non-auto study_type on Step 1, force-route accordingly."""
    if not override or override == "auto":
        return result
    if override == result.study_type:
        return result

    result.study_type = override
    if override == "qualitative":
        result.study_design = "qualitative"
        result.suggested_formula = ""
        result.suggested_dropout = 0.0
        result.rationale = (
            "Researcher selected a qualitative study — sample size is judged "
            "by thematic saturation; no power calculation required."
        )
    elif override == "focus_group":
        result.study_design = "qualitative"
        result.suggested_formula = ""
        result.suggested_dropout = 0.0
        result.rationale = "Researcher selected focus-group discussions."
    elif override == "pilot":
        result.study_design = "descriptive"
        result.suggested_formula = ""
        result.suggested_dropout = 0.0
        result.rationale = (
            "Researcher selected a pilot / feasibility study — "
            "recommend ~25 participants for SD estimation."
        )
    elif override == "questionnaire":
        # Questionnaire / KAP route — recommendation panel only (no formula).
        result.study_design = "descriptive"
        result.suggested_formula = ""
        result.outcome_type = "proportion"
        result.suggested_dropout = 0.0
        result.rationale = (
            "Researcher selected a questionnaire survey — recommend "
            "n ≈ 384 (Cochran, p=0.5, d=±5%, 95% CI). Use "
            "single_proportion manually if you have a known prevalence."
        )
    elif override == "in_vitro":
        # Keep whatever formula was inferred (or fall back to two_means).
        if not result.suggested_formula:
            result.suggested_formula = "two_means"
        result.suggested_dropout = 0.0
    elif override == "in_vivo":
        if not result.suggested_formula:
            result.suggested_formula = "two_means"
        result.suggested_dropout = max(result.suggested_dropout, 0.10)
    elif override == "quantitative":
        # Researcher overrode a special detection back to quantitative —
        # normalise any leftover qualitative/special metadata so the
        # response is internally consistent.
        if result.study_design in {"qualitative", "unknown"}:
            result.study_design = "descriptive"
        if not result.suggested_formula:
            result.suggested_formula = "two_means"
            result.outcome_type = "mean"
        result.rationale = (
            "Researcher overrode the auto-detection back to a quantitative "
            f"study — using {result.suggested_formula}."
        )
    return result


@router.post("/analyze", response_model=AnalyzeResponse)
@limiter.limit("30/minute")
async def analyze_endpoint(payload: AnalyzeRequest, request: Request) -> AnalyzeResponse:
    """Classify the objective and suggest a sample-size formula."""
    try:
        consent = request.headers.get("X-External-AI-Consent", "").lower() == "true"
        result = analyze_objective(payload.objective, external_ai_consent=consent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    result = _apply_study_type_override(result, payload.study_type)

    # Attach the built-in recommendation block for non-formulaic types so
    # the frontend can render it without a second round-trip.
    rec_dict: Optional[Dict[str, Any]] = ss_engine.get_study_type_recommendation(
        result.study_type
    )
    rec_model: Optional[StudyTypeRecommendation] = (
        StudyTypeRecommendation(**rec_dict) if rec_dict else None
    )

    log.info(
        "sample_size.analyze",
        extra={
            "objective_length": len(payload.objective),
            "suggested_formula": result.suggested_formula,
            "source": result.source,
            "confidence": result.confidence,
            "study_type": result.study_type,
            "study_type_override": payload.study_type or "auto",
        },
    )
    response_dict = result.to_dict()
    response_dict["study_type_recommendation"] = (
        rec_model.model_dump() if rec_model else None
    )
    return AnalyzeResponse(**response_dict)


@router.get(
    "/study-type-recommendation/{study_type}",
    response_model=StudyTypeRecommendation,
)
async def study_type_recommendation_endpoint(study_type: str) -> StudyTypeRecommendation:
    """Return the built-in recommendation block for a non-formulaic study type."""
    rec = ss_engine.get_study_type_recommendation(study_type)
    if rec is None:
        raise HTTPException(
            status_code=404,
            detail=f"No built-in recommendation for study_type={study_type!r}",
        )
    return StudyTypeRecommendation(**rec)


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
