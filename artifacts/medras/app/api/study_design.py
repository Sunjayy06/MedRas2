"""Study Builder Part 2 — Study Design & Proposal Builder API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.services.study_design_advisor import (
    DESIGN_CATALOGUE,
    generate_methodology,
    recommend_designs,
)
from app.services.phi_redaction import screen_external_ai_payload
from app.services.llm_client import openrouter_is_configured, provider_status_payload

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/study-builder/design", tags=["study-builder-design"])


class PICO(BaseModel):
    P: str = ""
    I: str = ""
    C: str = ""
    O: str = ""


class RecommendRequest(BaseModel):
    question:       str  = Field(..., min_length=5, max_length=1000)
    pico:           PICO = Field(default_factory=PICO)
    objective_type: str  = "analytical"


class MethodologyRequest(BaseModel):
    question:  str  = Field(..., min_length=5)
    pico:      PICO = Field(default_factory=PICO)
    design_id: str  = Field(..., min_length=1)
    extra:     dict = Field(default_factory=dict)


class ExportRequest(BaseModel):
    question:    str
    pico:        PICO = Field(default_factory=PICO)
    design_id:   str
    design_name: str
    methodology: dict = Field(default_factory=dict)
    stats_plan:  dict = Field(default_factory=dict)
    ethics:      dict = Field(default_factory=dict)
    title:       str  = ""


@router.get("/catalogue")
def get_catalogue() -> dict:
    return {"designs": DESIGN_CATALOGUE}


@router.post("/recommend")
async def recommend(request: Request, body: RecommendRequest) -> dict:
    screening = screen_external_ai_payload(body.model_dump())
    consent = request.headers.get("X-External-AI-Consent", "").lower() == "true"
    safe = screening.value
    result = await recommend_designs(
        safe["question"], safe["pico"], safe["objective_type"],
        external_ai_consent=consent and not screening.blocked,
    )
    result.update(provider_status_payload(
        "openrouter" if consent and not screening.blocked and openrouter_is_configured() else "local_fallback",
        consent, screening.redaction_applied, screening.blocked,
    ))
    return result


@router.post("/methodology")
async def methodology(request: Request, body: MethodologyRequest) -> dict:
    screening = screen_external_ai_payload(body.model_dump())
    consent = request.headers.get("X-External-AI-Consent", "").lower() == "true"
    safe = screening.value
    result = await generate_methodology(
        safe["question"], safe["pico"], safe["design_id"], safe["extra"],
        external_ai_consent=consent and not screening.blocked,
    )
    return {
        "methodology": result,
        **provider_status_payload(
            "openrouter" if consent and not screening.blocked and openrouter_is_configured() else "local_fallback",
            consent, screening.redaction_applied, screening.blocked,
        ),
    }


@router.post("/export-text")
def export_text(body: ExportRequest) -> dict:
    pico = body.pico
    m    = body.methodology
    s    = body.stats_plan
    e    = body.ethics
    title = body.title or f"Study Protocol: {body.question[:80]}"

    lines = [
        f"STUDY DESIGN PROTOCOL",
        f"{'='*60}",
        f"Title: {title}",
        f"Study Design: {body.design_name}",
        f"",
        f"RESEARCH QUESTION",
        f"{'-'*40}",
        body.question,
        f"",
        f"PICO FRAMEWORK",
        f"{'-'*40}",
        f"P (Population)       : {pico.P}",
        f"I (Intervention)     : {pico.I}",
        f"C (Comparison)       : {pico.C}",
        f"O (Outcome)          : {pico.O}",
        f"",
        f"METHODOLOGY",
        f"{'-'*40}",
        f"Study Setting   : {m.get('study_setting', '')}",
        f"Study Period     : {m.get('study_period', '')}",
        f"Study Population : {m.get('study_population', '')}",
        f"Sampling         : {m.get('sampling_technique', '')}",
        f"",
        f"Inclusion Criteria:",
    ]
    for ic in (m.get("inclusion_criteria") or []):
        lines.append(f"  • {ic}")
    lines.append("Exclusion Criteria:")
    for ec in (m.get("exclusion_criteria") or []):
        lines.append(f"  • {ec}")
    lines += [
        f"",
        f"Primary Outcome  : {m.get('primary_outcome', '')}",
        f"Secondary Outcomes:",
    ]
    for so in (m.get("secondary_outcomes") or []):
        lines.append(f"  • {so}")
    lines += [
        f"",
        f"Data Collection  : {m.get('data_collection_tool', '')}",
        f"",
        f"STATISTICAL PLAN",
        f"{'-'*40}",
        f"Software         : {m.get('software', s.get('software', 'SPSS'))}",
        f"Statistical Tests:",
    ]
    for t in (m.get("statistical_tests") or []):
        lines.append(f"  • {t}")
    if s.get("sample_size"):
        lines.append(f"Sample Size      : {s['sample_size']}")
    if s.get("alpha"):
        lines.append(f"Significance (α) : {s['alpha']}")
    if s.get("power"):
        lines.append(f"Power (1-β)      : {s['power']}")
    lines += [
        f"",
        f"ETHICAL CONSIDERATIONS",
        f"{'-'*40}",
        f"Risk Level       : {e.get('risk', m.get('ethical_risk', 'minimal'))}",
        f"IEC Required     : {'Yes' if m.get('iec_required', True) else 'No'}",
        f"Informed Consent : {'Yes' if m.get('consent_required', True) else 'No'}",
        f"Declaration of Helsinki : Adhered to",
        f"ICMR Guidelines         : Adhered to",
    ]
    if e.get("waiver_justification"):
        lines.append(f"Waiver Justification: {e['waiver_justification']}")
    lines += [
        f"",
        f"Bias Minimisation Strategies:",
    ]
    for b in (m.get("bias_minimisation") or []):
        lines.append(f"  • {b}")
    lines += [f"", f"{'='*60}",
              f"Generated by MedRAS Study Builder"]
    return {"text": "\n".join(lines), "title": title}
