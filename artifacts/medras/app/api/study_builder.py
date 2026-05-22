"""Study Builder API — Medical Knowledge Assistant (POST /api/study-builder/ask)."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.study_builder_search import multi_source_search
from app.services.study_builder_synthesizer import synthesize_answer

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/study-builder", tags=["study-builder"])

_DISCLAIMER = (
    "This information is for educational and research purposes only and is based on "
    "published literature. Clinical decisions must involve a qualified healthcare professional."
)

_STATS_KW    = {"sample size", "power", "statistical", "regression", "p-value",
                "confidence interval", "odds ratio", "anova", "t-test"}
_RESEARCH_KW = {"study", "studies", "evidence", "trial", "efficacy", "effectiveness",
                "outcome", "compare", "association", "risk", "systematic", "meta-analysis",
                "cohort", "rct", "prevalence", "incidence", "published", "literature", "review"}
_CLINICAL_KW = {"treatment", "manage", "management", "dose", "drug", "prescribe",
                "patient", "diagnosis", "therapy", "clinical", "symptoms",
                "guidelines", "protocol", "medication"}


def _classify(q: str) -> str:
    lower = q.lower()
    if any(k in lower for k in _STATS_KW):
        return "statistics"
    words = set(lower.split())
    if words & _RESEARCH_KW:
        return "research"
    if words & _CLINICAL_KW:
        return "clinical"
    return "research"


def _suggestions(qtype: str) -> list[str]:
    if qtype == "research":
        return [
            "What are the methodological limitations of existing studies on this topic?",
            "What outcome measures are most commonly used in this research area?",
            "Are there India-specific studies or ICMR guidelines on this topic?",
        ]
    if qtype == "clinical":
        return [
            "What are the latest guideline recommendations for this condition?",
            "What does the Cochrane evidence say about this intervention?",
            "Are there recent RCTs from low- or middle-income countries?",
        ]
    return [
        "What sample size is needed for a study on this topic?",
        "What statistical tests are appropriate for this design?",
        "What validated outcome instruments are used in this area?",
    ]


def _buttons(qtype: str) -> list[dict]:
    btns: list[dict] = [{"label": "Calculate sample size", "action": "sample_size",
                          "url": "/sample-size.html", "external": False}]
    if qtype == "research":
        btns.insert(0, {"label": "Design a study on this", "action": "design_study",
                         "url": "/study-builder/#design", "external": False})
    elif qtype == "clinical":
        btns.insert(0, {"label": "Search ClinicalTrials.gov", "action": "find_trials",
                         "url": "https://clinicaltrials.gov/search", "external": True})
    return btns


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)


class AskResponse(BaseModel):
    answer:              str
    synthesis_method:    str
    question_type:       str
    papers:              list[dict]
    sources_searched:    list[str]
    total_found:         int
    suggested_questions: list[str]
    action_buttons:      list[dict]
    disclaimer:          str = _DISCLAIMER


@router.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest) -> AskResponse:
    question = body.question.strip()
    qtype    = _classify(question)
    result   = await multi_source_search(question, top_n=8)
    synth    = await synthesize_answer(question, result["papers"])
    return AskResponse(
        answer=synth["answer"], synthesis_method=synth["method"],
        question_type=qtype, papers=result["papers"],
        sources_searched=result["sources_searched"],
        total_found=result["total_found"],
        suggested_questions=_suggestions(qtype),
        action_buttons=_buttons(qtype),
    )
