"""Study Builder API — Medical Knowledge Assistant.

POST /api/study-builder/ask
  1. PICO decomposition  → optimised search queries
  2. Multi-query parallel search across 16 databases
  3. Per-paper sentence distillation  (keyword overlap, no extra API call)
  4. GRADE evidence quality grade
  5. Structured AI synthesis  (JSON, every claim traced to a real sentence)
  6. Conversation session update
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.study_builder_search      import multi_source_search
from app.services.study_builder_synthesizer import synthesize
from app.services.study_builder_pico        import decompose
from app.services import study_builder_session as sessions

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/study-builder", tags=["study-builder"])

_DISCLAIMER = (
    "This information is for educational and research purposes only and is "
    "based on published literature. Clinical decisions must involve a qualified "
    "healthcare professional."
)


# ── Request / Response models ────────────────────────────────────────────────

class AskRequest(BaseModel):
    question:   str            = Field(..., min_length=3, max_length=1500)
    session_id: Optional[str]  = Field(None, description="Omit to start a new session")


class KeyFinding(BaseModel):
    finding: str
    sources: list[int] = []


class AskResponse(BaseModel):
    # Core answer (structured)
    answer:               str
    key_findings:         list[KeyFinding]
    what_agrees:          str
    what_is_debated:      str
    contradictions:       list[str]
    limitations:          str

    # Evidence quality
    evidence_grade:             str   # HIGH | MODERATE | LOW | VERY LOW
    evidence_grade_explanation: str

    # Session
    session_id: str

    # Sources
    papers:           list[dict]
    sources_searched: list[str]
    total_found:      int

    # Follow-ups (AI-generated, not hardcoded)
    suggested_questions: list[str]
    action_buttons:      list[dict]

    # Meta
    synthesis_method: str
    question_type:    str
    pico:             dict
    disclaimer:       str = _DISCLAIMER


# ── Helpers ──────────────────────────────────────────────────────────────────

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


def _action_buttons(qtype: str) -> list[dict]:
    btns: list[dict] = [
        {"label": "Calculate sample size", "action": "sample_size",
         "url": "/sample-size.html", "external": False},
    ]
    if qtype == "research":
        btns.insert(0, {"label": "Design a study on this", "action": "design_study",
                        "url": "/study-builder/design.html", "external": False})
    elif qtype == "clinical":
        btns.insert(0, {"label": "Search ClinicalTrials.gov", "action": "find_trials",
                        "url": "https://clinicaltrials.gov/search", "external": True})
    btns.append({"label": "Take to Proposal Writer", "action": "proposal",
                 "url": "/proposal-module/", "external": False})
    return btns


async def _search_all_queries(queries: list[str], top_n: int = 12) -> dict:
    """Run each PICO query in parallel, merge and deduplicate results."""
    if len(queries) == 1:
        return await multi_source_search(queries[0], top_n=top_n)

    tasks   = [multi_source_search(q, top_n=8) for q in queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    merged_papers: list[dict]   = []
    seen_titles:   set[str]     = set()
    all_sources:   set[str]     = set()
    total_found    = 0

    for r in results:
        if isinstance(r, Exception):
            log.warning("Search query failed: %s", r)
            continue
        total_found += r.get("total_found", 0)
        all_sources.update(r.get("sources_searched", []))
        for p in r.get("papers", []):
            key = (p.get("title") or "").strip().lower()[:80]
            if key and key not in seen_titles:
                seen_titles.add(key)
                merged_papers.append(p)

    # Sort by citation count desc, take top_n
    merged_papers.sort(key=lambda p: p.get("citation_count", 0), reverse=True)
    merged_papers = merged_papers[:top_n]

    return {
        "papers":           merged_papers,
        "sources_searched": sorted(all_sources),
        "total_found":      total_found,
    }


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest) -> AskResponse:
    question = body.question.strip()

    # 1. Session — get history for PICO and synthesis context
    session_id, history = sessions.get_or_create(body.session_id)

    # 2. PICO decomposition (runs concurrently with nothing yet — fast single call)
    pico = await decompose(question, history)
    log.info(
        "PICO [session=%s] P=%s I=%s C=%s O=%s queries=%s",
        session_id[:8], pico["population"], pico["intervention"],
        pico["comparison"], pico["outcome"], pico["search_queries"],
    )

    # 3. Multi-query parallel search
    search_result = await _search_all_queries(pico["search_queries"], top_n=12)

    # 4. Distillation + grading + structured synthesis
    synth = await synthesize(question, search_result["papers"], history)

    # 5. Persist this turn (use summary = first 200 chars of answer)
    answer_summary = (synth["answer"] or "")[:200].replace("\n", " ")
    sessions.add_turn(session_id, question, answer_summary)

    qtype = _classify(question)

    return AskResponse(
        answer               = synth["answer"],
        key_findings         = [
            KeyFinding(**f) if isinstance(f, dict) else KeyFinding(finding=str(f))
            for f in (synth.get("key_findings") or [])
        ],
        what_agrees          = synth.get("what_agrees", ""),
        what_is_debated      = synth.get("what_is_debated", ""),
        contradictions       = synth.get("contradictions") or [],
        limitations          = synth.get("limitations", ""),
        evidence_grade             = synth.get("evidence_grade", "VERY LOW"),
        evidence_grade_explanation = synth.get("evidence_grade_explanation", ""),
        session_id           = session_id,
        papers               = search_result["papers"],
        sources_searched     = search_result["sources_searched"],
        total_found          = search_result["total_found"],
        suggested_questions  = synth.get("suggested_questions") or [],
        action_buttons       = _action_buttons(qtype),
        synthesis_method     = synth.get("method", "unknown"),
        question_type        = qtype,
        pico                 = pico,
    )
