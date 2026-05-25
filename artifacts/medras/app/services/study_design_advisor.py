"""Study Builder Part 2 — AI-powered study design advisor."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

DESIGN_CATALOGUE: list[dict] = [
    {
        "id": "rct",
        "name": "Randomized Controlled Trial (RCT)",
        "category": "Experimental",
        "icon": "⚖",
        "description": "Participants randomly allocated to intervention or control group.",
        "evidence_level": "I",
        "pros": ["Highest internal validity", "Controls confounding via randomization",
                 "Gold standard for causal inference"],
        "cons": ["Expensive and time-consuming", "Ethical constraints on randomization",
                 "May have poor external validity"],
        "when_to_use": "Testing efficacy/effectiveness of an intervention or treatment",
        "complexity": "high",
        "requires_comparison": True,
        "requires_intervention": True,
        "suitable_objectives": ["experimental", "analytical"],
    },
    {
        "id": "cohort_prospective",
        "name": "Prospective Cohort Study",
        "category": "Observational",
        "icon": "→",
        "description": "Follow exposed and unexposed groups forward in time to measure outcomes.",
        "evidence_level": "II",
        "pros": ["Temporal sequence establishes exposure before outcome", "Multiple outcomes measurable",
                 "Good for rare exposures"],
        "cons": ["Long follow-up needed", "Loss to follow-up bias", "Expensive"],
        "when_to_use": "Studying incidence, risk factors, or prognosis over time",
        "complexity": "high",
        "requires_comparison": True,
        "requires_intervention": False,
        "suitable_objectives": ["analytical"],
    },
    {
        "id": "cohort_retrospective",
        "name": "Retrospective Cohort Study",
        "category": "Observational",
        "icon": "←",
        "description": "Uses existing records to identify past exposure and subsequent outcomes.",
        "evidence_level": "III",
        "pros": ["Faster and cheaper than prospective", "No loss to follow-up during study",
                 "Suitable for rare diseases with long latency"],
        "cons": ["Relies on record quality", "Cannot control unmeasured confounders",
                 "Recall and information bias"],
        "when_to_use": "When prospective follow-up is impractical; existing data available",
        "complexity": "medium",
        "requires_comparison": True,
        "requires_intervention": False,
        "suitable_objectives": ["analytical"],
    },
    {
        "id": "case_control",
        "name": "Case-Control Study",
        "category": "Observational",
        "icon": "⇄",
        "description": "Compare past exposure between cases (disease) and controls (no disease).",
        "evidence_level": "III",
        "pros": ["Efficient for rare diseases", "Relatively quick and inexpensive",
                 "Multiple exposures studied simultaneously"],
        "cons": ["Retrospective — susceptible to recall bias", "Cannot calculate incidence",
                 "Control selection is critical"],
        "when_to_use": "Studying rare diseases or conditions with long latency",
        "complexity": "medium",
        "requires_comparison": True,
        "requires_intervention": False,
        "suitable_objectives": ["analytical"],
    },
    {
        "id": "cross_sectional",
        "name": "Cross-Sectional Study",
        "category": "Observational",
        "icon": "📸",
        "description": "Measure exposure and outcome simultaneously at one point in time.",
        "evidence_level": "IV",
        "pros": ["Quick, inexpensive", "Good for prevalence estimation",
                 "No loss to follow-up"],
        "cons": ["Cannot establish temporal sequence", "Susceptible to prevalence-incidence bias",
                 "Cannot study rare diseases"],
        "when_to_use": "Estimating prevalence; hypothesis generation; screening surveys",
        "complexity": "low",
        "requires_comparison": False,
        "requires_intervention": False,
        "suitable_objectives": ["descriptive", "analytical"],
    },
    {
        "id": "diagnostic_accuracy",
        "name": "Diagnostic Accuracy Study",
        "category": "Observational",
        "icon": "🔎",
        "description": "Evaluate sensitivity, specificity, and predictive values of a diagnostic test.",
        "evidence_level": "II",
        "pros": ["Direct measurement of test performance", "Clinically actionable results",
                 "STARD reporting standard available"],
        "cons": ["Requires a reference standard (gold standard)", "Spectrum bias",
                 "Threshold effects"],
        "when_to_use": "Evaluating a new diagnostic test, biomarker, or screening tool",
        "complexity": "medium",
        "requires_comparison": True,
        "requires_intervention": False,
        "suitable_objectives": ["analytical", "diagnostic"],
    },
    {
        "id": "systematic_review",
        "name": "Systematic Review / Meta-analysis",
        "category": "Secondary",
        "icon": "📚",
        "description": "Systematically identify, appraise, and synthesise all relevant evidence.",
        "evidence_level": "I",
        "pros": ["Highest level of synthesised evidence", "Resolves conflicting findings",
                 "PRISMA guideline available"],
        "cons": ["Time-intensive", "Requires adequate primary studies",
                 "Publication bias risk"],
        "when_to_use": "Summarising existing evidence on a well-defined question",
        "complexity": "high",
        "requires_comparison": False,
        "requires_intervention": False,
        "suitable_objectives": ["exploratory", "analytical"],
    },
    {
        "id": "case_series",
        "name": "Case Series / Case Report",
        "category": "Descriptive",
        "icon": "📋",
        "description": "Detailed description of one or more cases of an unusual condition.",
        "evidence_level": "V",
        "pros": ["Cheap, fast", "Hypothesis-generating", "Useful for rare/novel conditions"],
        "cons": ["No control group", "Cannot establish causality",
                 "High risk of selection bias"],
        "when_to_use": "Novel/rare disease; unusual presentation; hypothesis generation",
        "complexity": "low",
        "requires_comparison": False,
        "requires_intervention": False,
        "suitable_objectives": ["descriptive", "exploratory"],
    },
    {
        "id": "qualitative",
        "name": "Qualitative Research",
        "category": "Qualitative",
        "icon": "💬",
        "description": "Explore experiences, perceptions, or processes through non-numerical data.",
        "evidence_level": "—",
        "pros": ["Rich, contextual insights", "Exploratory — no prior hypothesis needed",
                 "Captures patient perspectives"],
        "cons": ["Not generalisable", "Subjective interpretation",
                 "Time-intensive analysis"],
        "when_to_use": "Understanding 'why' or 'how'; patient experience; health behaviour",
        "complexity": "medium",
        "requires_comparison": False,
        "requires_intervention": False,
        "suitable_objectives": ["exploratory", "descriptive"],
    },
]

_RECOMMEND_PROMPT = """\
You are a senior biostatistician and medical researcher at a top academic hospital.

A researcher has provided this research question and PICO framework. Recommend the 3 most
appropriate study designs from the provided catalogue and explain your reasoning.

Research Question: {question}

PICO:
  Population: {P}
  Intervention/Exposure: {I}
  Comparison: {C}
  Outcome: {O}
  Objective type: {objective_type}

Available designs (by id): {design_ids}

Reply with ONLY valid JSON matching this exact schema — no markdown, no extra text:
{{
  "recommendations": [
    {{
      "design_id": "<id from catalogue>",
      "rank": 1,
      "rationale": "<2-3 sentence explanation of why this design fits>",
      "key_consideration": "<single most important practical point for this specific study>",
      "feasibility": "high|medium|low",
      "timeline_estimate": "<realistic duration e.g. '12-18 months'>"
    }}
  ],
  "general_advice": "<1-2 sentences of overall methodological guidance>"
}}
"""

_METHODOLOGY_PROMPT = """\
You are an expert medical research methodologist.

Generate a detailed methodology plan for this study. Be specific and practical.

Research Question: {question}
Study Design: {design_name}
PICO:
  P: {P}
  I: {I}
  C: {C}
  O: {O}

Reply with ONLY valid JSON — no markdown, no extra text:
{{
  "study_setting": "<specific setting e.g. tertiary care hospital OPD>",
  "study_period": "<realistic duration>",
  "study_population": "<precise definition>",
  "sample_size_note": "<brief note on what determines sample size for this design>",
  "sampling_technique": "<technique name and brief justification>",
  "inclusion_criteria": ["<criterion 1>", "<criterion 2>", "<criterion 3>"],
  "exclusion_criteria": ["<criterion 1>", "<criterion 2>", "<criterion 3>"],
  "primary_outcome": "<clearly defined primary outcome with measurement unit>",
  "secondary_outcomes": ["<outcome 1>", "<outcome 2>"],
  "data_collection_tool": "<instrument/tool name and validation status>",
  "variables": [
    {{"name": "<var>", "type": "independent|dependent|confounding", "scale": "nominal|ordinal|interval|ratio"}},
    {{"name": "<var>", "type": "independent|dependent|confounding", "scale": "nominal|ordinal|interval|ratio"}}
  ],
  "statistical_tests": ["<test 1 with brief indication>", "<test 2>"],
  "software": "SPSS|R|Stata|JASP",
  "bias_minimisation": ["<strategy 1>", "<strategy 2>"],
  "ethical_risk": "minimal|greater_than_minimal",
  "iec_required": true,
  "consent_required": true
}}
"""


def _design_by_id(did: str) -> dict | None:
    return next((d for d in DESIGN_CATALOGUE if d["id"] == did), None)


async def recommend_designs(
    question: str, pico: dict[str, str], objective_type: str
) -> dict:
    design_ids = [d["id"] for d in DESIGN_CATALOGUE]
    prompt = _RECOMMEND_PROMPT.format(
        question=question,
        P=pico.get("P", ""), I=pico.get("I", ""),
        C=pico.get("C", ""), O=pico.get("O", ""),
        objective_type=objective_type,
        design_ids=", ".join(design_ids),
    )

    raw: dict[str, Any] | None = None

    from app.services.llm_client import get_gemini_client, gemini_is_configured, get_async_openai_client, openai_is_configured
    if gemini_is_configured():
        def _gemini_recommend() -> dict | None:
            from google.genai import types as gtypes
            gc = get_gemini_client()
            resp = gc.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=gtypes.GenerateContentConfig(
                    max_output_tokens=1200, temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            return json.loads(resp.text or "{}")

        try:
            raw = await asyncio.to_thread(_gemini_recommend)
        except Exception as exc:
            log.warning("Gemini recommend failed: %s", exc)

    if raw is None:
        if openai_is_configured():
            try:
                oai  = get_async_openai_client()
                resp = await oai.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1200, temperature=0.1,
                    response_format={"type": "json_object"},
                )
                raw = json.loads(resp.choices[0].message.content or "{}")
            except Exception as exc:
                log.warning("OpenAI recommend failed: %s", exc)

    recs = (raw or {}).get("recommendations", [])
    advice = (raw or {}).get("general_advice", "")

    enriched = []
    for rec in recs[:3]:
        d = _design_by_id(rec.get("design_id", ""))
        if d:
            enriched.append({**d, **rec})

    if not enriched:
        enriched = _heuristic_recommendations(pico, objective_type)

    return {"recommendations": enriched, "general_advice": advice,
            "all_designs": DESIGN_CATALOGUE}


def _heuristic_recommendations(pico: dict, objective_type: str) -> list[dict]:
    has_i  = bool(pico.get("I", "").strip())
    has_c  = bool(pico.get("C", "").strip())
    obj    = (objective_type or "analytical").lower()
    picks  = []
    if "experimental" in obj and has_i and has_c:
        picks = ["rct", "cohort_prospective", "cross_sectional"]
    elif "descriptive" in obj:
        picks = ["cross_sectional", "case_series", "cohort_retrospective"]
    elif "diagnostic" in obj:
        picks = ["diagnostic_accuracy", "cross_sectional", "cohort_prospective"]
    elif has_i and has_c:
        picks = ["cohort_prospective", "case_control", "rct"]
    else:
        picks = ["cross_sectional", "cohort_prospective", "case_control"]
    result = []
    for i, pid in enumerate(picks[:3]):
        d = _design_by_id(pid)
        if d:
            result.append({**d, "rank": i+1,
                           "rationale": "Selected based on your study objectives and PICO framework.",
                           "key_consideration": "Confirm feasibility with your institution.",
                           "feasibility": "medium", "timeline_estimate": "6-18 months"})
    return result


async def generate_methodology(
    question: str, pico: dict[str, str], design_id: str, extra: dict
) -> dict:
    design = _design_by_id(design_id)
    design_name = design["name"] if design else design_id
    prompt = _METHODOLOGY_PROMPT.format(
        question=question, design_name=design_name,
        P=pico.get("P", ""), I=pico.get("I", ""),
        C=pico.get("C", ""), O=pico.get("O", ""),
    )

    raw: dict | None = None

    from app.services.llm_client import get_gemini_client, gemini_is_configured, get_async_openai_client, openai_is_configured
    if gemini_is_configured():
        def _gemini_methodology() -> dict | None:
            from google.genai import types as gtypes
            gc = get_gemini_client()
            resp = gc.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=gtypes.GenerateContentConfig(
                    max_output_tokens=1500, temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            return json.loads(resp.text or "{}")

        try:
            raw = await asyncio.to_thread(_gemini_methodology)
        except Exception as exc:
            log.warning("Gemini methodology failed: %s", exc)

    if raw is None:
        if openai_is_configured():
            try:
                oai  = get_async_openai_client()
                resp = await oai.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1500, temperature=0.1,
                    response_format={"type": "json_object"},
                )
                raw = json.loads(resp.choices[0].message.content or "{}")
            except Exception as exc:
                log.warning("OpenAI methodology failed: %s", exc)

    return raw or _fallback_methodology(design_id)


def _fallback_methodology(design_id: str) -> dict:
    return {
        "study_setting": "Tertiary care teaching hospital",
        "study_period": "12 months",
        "study_population": "Define based on your PICO",
        "sample_size_note": "Use Cohort calculator for formal sample size estimation",
        "sampling_technique": "Consecutive sampling",
        "inclusion_criteria": ["Age 18-65 years", "Diagnosis confirmed by standard criteria",
                                "Willing to give informed consent"],
        "exclusion_criteria": ["Pregnant or lactating women", "Severe comorbidities",
                                "Unable to give consent"],
        "primary_outcome": "Define your primary endpoint with measurement scale",
        "secondary_outcomes": ["Secondary endpoint 1", "Secondary endpoint 2"],
        "data_collection_tool": "Structured proforma (design your own)",
        "variables": [
            {"name": "Primary exposure", "type": "independent", "scale": "nominal"},
            {"name": "Primary outcome", "type": "dependent", "scale": "ratio"},
        ],
        "statistical_tests": ["Descriptive statistics (mean, SD, frequency)",
                              "Appropriate inferential test based on data distribution"],
        "software": "SPSS",
        "bias_minimisation": ["Standardised data collection", "Blinded outcome assessment"],
        "ethical_risk": "minimal",
        "iec_required": True,
        "consent_required": True,
    }
