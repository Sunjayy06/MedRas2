"""Sigma Chapter V AI narration polish, built on top of openrouter_client.

This module only polishes *prose wording* for deterministic narrative that
has already been computed elsewhere (study summary, section introductions,
table/figure interpretation paragraphs, Results Synthesis, final caution
wording). It never computes statistics and never accepts AI output that
appears to add, remove, or change a fact.

Model routing (per task, free-model-only — see openrouter_client):
    "writing"             -> OPENROUTER_WRITING_MODEL   (Chapter V narrative polish)
    "proposal_understanding" -> OPENROUTER_PROPOSAL_MODEL (objective/outcome extraction)
    "reasoning_audit"     -> OPENROUTER_REASONING_MODEL  (optional internal QA review)

OPENROUTER_CODING_MODEL and OPENROUTER_VISION_MODEL are intentionally never
referenced here — coding assistance and vision/image interpretation are out
of scope for Chapter V narrative polish.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.core.config import settings
from app.services import openrouter_client

log = logging.getLogger(__name__)

_TASK_MODEL_FIELDS = {
    "writing": "openrouter_writing_model",
    "proposal_understanding": "openrouter_proposal_model",
    "reasoning_audit": "openrouter_reasoning_model",
}


def model_for_task(task: str) -> str:
    """Resolve the free-model id configured for `task`, falling back to the
    configured fallback model if the task-specific model is not a free model."""
    field_name = _TASK_MODEL_FIELDS.get(task, "openrouter_default_model")
    configured = getattr(settings, field_name, None) or settings.openrouter_default_model
    return openrouter_client.resolve_model(configured)


# ---------------------------------------------------------------------------
# Evidence pack — structured computed facts sent to the AI, never raw rows
# ---------------------------------------------------------------------------


@dataclass
class EvidencePack:
    category: str
    title: str
    text: str
    study_design: str = ""
    sample_size: str = ""
    primary_outcome: str = ""
    test_name: str = ""
    p_value: str = ""
    adjusted_p_value: str = ""
    effect_size: str = ""
    significance_status: str = ""
    cautions: List[str] = field(default_factory=list)


def build_evidence_pack(category: str, title: str, text: str, **facts) -> EvidencePack:
    return EvidencePack(category=category, title=title, text=text, **facts)


# ---------------------------------------------------------------------------
# Validation — reject anything that adds, removes, or changes a fact
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(
    r"""
    (?:p\s*[<>=≤≥]\s*)?
    \b\d+(?:[.,]\d+)?(?:\s*%)?
    |[<>≤≥]\s*0\.\d+
    """,
    re.VERBOSE,
)

_TEST_NAME_TOKENS = (
    "chi-square", "chi square", "fisher's exact", "fisher exact",
    "welch's t-test", "welch t-test", "student's t-test", "independent t-test",
    "paired t-test", "mann-whitney", "wilcoxon", "kruskal-wallis", "anova",
    "mcnemar", "spearman", "pearson", "cochran", "z-test",
)

_EFFECT_SIZE_TOKENS = (
    "cramér's v", "cramer's v", "cohen's d", "odds ratio", "hazard ratio",
    "relative risk", "phi coefficient", "eta squared",
)

_SIGNIFICANCE_TOKENS = (
    "statistically significant", "not statistically significant",
    "not significant", "significant association", "no significant association",
)

_CITATION_RE = re.compile(
    r"\bet al\b|\(\s*(?:19|20)\d{2}\s*\)|\[\s*\d+\s*\]|\bdoi\s*:|https?://|\breferences?\s*:",
    re.IGNORECASE,
)

# Verbatim per the Sigma AI narration policy — any of these appearing in AI
# output is a hard rejection, regardless of surrounding context.
FORBIDDEN_CLAIM_PHRASES = (
    "proves", "prove", "proven",
    "causes", "caused by", "causal", "causality",
    "predicts", "prediction",
    "prognostic significance",
    "independent association", "independently associated",
    "survival benefit", "survival advantage",
    "mortality",
    "risk factor",
)


def contains_forbidden_claim(text: str) -> Optional[str]:
    lowered = (text or "").lower()
    for phrase in FORBIDDEN_CLAIM_PHRASES:
        if phrase in lowered:
            return phrase
    return None


def contains_citation(text: str) -> bool:
    return bool(_CITATION_RE.search(text or ""))


def _tokens_present(text: str, tokens) -> set:
    lowered = (text or "").lower()
    return {token for token in tokens if token in lowered}


def validate_polish(original: str, proposed: str) -> bool:
    """Return True only if `proposed` is safe to substitute for `original`.

    Rejects AI output that: is empty, introduces or drops any numeric token
    (counts, percentages, means/SD, p-values, adjusted p-values, effect
    sizes), drops a test-name/effect-size/significance-status mention that
    was present in the original, uses a forbidden causal/prognostic claim
    phrase, or adds a citation/reference.
    """
    if not proposed or not proposed.strip():
        return False
    if proposed.strip() == (original or "").strip():
        return True

    forbidden = contains_forbidden_claim(proposed)
    if forbidden:
        log.debug("ai_narrative: rejected - forbidden claim phrase %r", forbidden)
        return False
    if contains_citation(proposed):
        log.debug("ai_narrative: rejected - citation/reference detected")
        return False

    orig_numbers = set(_NUMBER_RE.findall(original or ""))
    prop_numbers = set(_NUMBER_RE.findall(proposed))
    if orig_numbers != prop_numbers:
        log.debug("ai_narrative: rejected - numeric content changed")
        return False

    for tokens, label in (
        (_TEST_NAME_TOKENS, "test name"),
        (_EFFECT_SIZE_TOKENS, "effect size"),
        (_SIGNIFICANCE_TOKENS, "significance status"),
    ):
        orig_present = _tokens_present(original, tokens)
        if orig_present and not orig_present <= _tokens_present(proposed, tokens):
            log.debug("ai_narrative: rejected - %s token dropped or changed", label)
            return False

    return True


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

_WRITING_SYSTEM_PROMPT = (
    "You are a medical-thesis Chapter V copy editor. You polish the wording of "
    "already-computed results narration. You must follow these rules exactly:\n"
    "1. Preserve every number, percentage, p-value, adjusted p-value, effect size, "
    "test name, and significance status exactly as given. Never add, remove, or "
    "change any of them.\n"
    "2. Never state or imply causation, prognosis, prediction, survival benefit, "
    "mortality risk, or that a variable is a risk factor.\n"
    "3. Never add citations, references, or literature of any kind.\n"
    "4. Keep every caution or limitation sentence from the original.\n"
    "5. Do not add new analyses, graphs, or clinical claims.\n"
    "6. Return ONLY the rewritten paragraph text — no preamble, no commentary."
)

_QA_SYSTEM_PROMPT = (
    "You are a QA reviewer for a medical thesis results chapter. You will be given "
    "computed facts and a candidate paragraph. Reply with exactly one word: "
    "'OK' if the candidate does not contradict the facts, invent a number, or imply "
    "causation/prognosis/prediction/risk-factor status; otherwise reply 'REJECT'."
)


def _facts_block(evidence: EvidencePack) -> str:
    lines = []
    if evidence.study_design:
        lines.append(f"Study design: {evidence.study_design}")
    if evidence.sample_size:
        lines.append(f"Sample size: {evidence.sample_size}")
    if evidence.primary_outcome:
        lines.append(f"Primary outcome: {evidence.primary_outcome}")
    if evidence.test_name:
        lines.append(f"Test applied: {evidence.test_name}")
    if evidence.p_value:
        lines.append(f"p-value: {evidence.p_value}")
    if evidence.adjusted_p_value:
        lines.append(f"Adjusted p-value: {evidence.adjusted_p_value}")
    if evidence.effect_size:
        lines.append(f"Effect size: {evidence.effect_size}")
    if evidence.significance_status:
        lines.append(f"Significance status: {evidence.significance_status}")
    if evidence.cautions:
        lines.append("Required cautions to keep (verbatim): " + "; ".join(evidence.cautions))
    return "\n".join(lines)


def _user_prompt(evidence: EvidencePack) -> str:
    facts = _facts_block(evidence)
    parts = [f"Section/table/figure title: {evidence.title}"]
    if facts:
        parts.append("Known facts (do not alter any of these):\n" + facts)
    parts.append("Paragraph to polish:\n" + evidence.text)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def polish_writing(evidence: EvidencePack) -> Optional[str]:
    """Attempt an OpenRouter-polished rewrite of evidence.text.

    Returns the polished text only if AI polish is enabled, configured,
    routed to a validated free model, and the output passes validate_polish.
    Returns None (deterministic fallback) in every other case, and never
    raises — export must not be blocked by an AI failure.
    """
    if not settings.sigma_ai_polish_enabled:
        return None
    if not openrouter_client.is_configured():
        return None
    model = model_for_task("writing")
    if not openrouter_client.is_free_model(model):
        return None
    try:
        proposed = openrouter_client.chat_completion(
            model=model, system=_WRITING_SYSTEM_PROMPT, user=_user_prompt(evidence)
        )
    except Exception:
        log.warning("ai_narrative: polish_writing request failed")
        return None
    if not proposed:
        return None
    if not validate_polish(evidence.text, proposed):
        return None
    return proposed


def review_with_reasoning_model(evidence: EvidencePack, candidate_text: str) -> Optional[bool]:
    """Optional secondary QA pass using the reasoning model: checks whether a
    candidate polished paragraph contradicts the computed facts or overclaims.

    Returns True/False, or None if AI polish/QA is unavailable — callers
    must treat None as "no opinion" and rely on validate_polish alone."""
    if not settings.sigma_ai_polish_enabled:
        return None
    if not openrouter_client.is_configured():
        return None
    model = model_for_task("reasoning_audit")
    if not openrouter_client.is_free_model(model):
        return None
    user = f"{_user_prompt(evidence)}\n\nCandidate polished paragraph:\n{candidate_text}"
    try:
        verdict = openrouter_client.chat_completion(model=model, system=_QA_SYSTEM_PROMPT, user=user)
    except Exception:
        log.warning("ai_narrative: review_with_reasoning_model request failed")
        return None
    if verdict is None:
        return None
    return verdict.strip().upper().startswith("OK")


def audit_label(status: str) -> str:
    """Return the metadata/audit line for a Chapter V export.

    status must be one of:
      "applied"      -> AI polish was requested and at least one chunk was
                        accepted after validation.
      "fallback"     -> AI polish was requested (consent given, enabled,
                        key configured) but failed, timed out, or every
                        chunk was rejected by validation.
      "deterministic" (or anything else) -> AI polish was never requested.
    """
    if status == "applied":
        return "AI polish: OpenRouter narration polish applied."
    if status == "fallback":
        return "AI polish: deterministic fallback used."
    return "AI polish: deterministic only."
