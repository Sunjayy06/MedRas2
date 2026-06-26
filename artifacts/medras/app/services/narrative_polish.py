"""Free-model-only OpenRouter narrative polish for Chapter V exports.

Collects polishable prose chunks (section introductions, table/figure
interpretation sentences, Results Synthesis) and routes them through
``app.services.ai_narrative`` (which in turn uses ``app.services.openrouter_client``
for the actual free-model-only request). Statistical values are stripped
before a chunk is sent, and ``ai_narrative.validate_polish`` plus this
module's own ``_is_safe`` both reject any AI output that slips in new
numeric content, causality claims, or removes a caution — falling back to
the deterministic text in every such case.

Usage
-----
Call ``polish_results(results)`` to get a ``NarrativeOverrides`` dict.
Pass that dict to ``generate_docx(results, polish_overrides=overrides)`` or
``generate_pdf(results, polish_overrides=overrides)``.

If ``SIGMA_AI_POLISH_ENABLED`` is not set, OpenRouter is not configured, or
the caller opts out, the functions are no-ops that return an empty dict (so
exports fall through to deterministic text unchanged).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safety patterns — AI output that matches any of these is rejected outright
# ---------------------------------------------------------------------------

# Any token that looks like a number, percentage, ratio, or p-value
_NUMBER_RE = re.compile(
    r"""
    (?:p\s*[<>=≤≥]\s*)?           # p-value prefix optional
    \b\d+(?:[.,]\d+)?(?:\s*%)?    # integer / decimal / percentage
    |[<>≤≥]\s*0\.\d+              # < 0.001 style
    """,
    re.VERBOSE | re.IGNORECASE,
)

_CAUSALITY_RE = re.compile(
    r"\b(causes?|caused\s+by|leads?\s+to|responsible\s+for|due\s+to\s+the\s+effect"
    r"|causal(?:ly|ity)?|definitively\s+associated|proves?)\b",
    re.IGNORECASE,
)

_CAUTION_REMOVAL_RE = re.compile(
    r"\b(should\s+be\s+interpreted\s+cautiously|interpret(?:ed)?\s+with\s+caution"
    r"|sparse\s+cells?|small\s+sample|limited\s+generali[sz]ability)\b",
    re.IGNORECASE,
)

_ARTIFACT_RE = re.compile(
    r"domain\s*[■�]\s*profile|domain\s+profile\s+grouping|selected\s+domain\s+profile"
    r"|the\s+table\s+is\s+organi[sz]ed\s+by|selected\s+outcome\s+variable|■|�",
    re.IGNORECASE,
)

_GENERIC_TEMPLATE_RE = re.compile(
    r"\b(the\s+table\s+presents\s+the\s+characteristics\s+of\s+the\s+analy[sz]ed\s+sample"
    r"|this\s+table\s+presents\s+a\s+comprehensive\s+overview"
    r"|the\s+figure\s+shows\s+the\s+distribution\s+of\s+the\s+selected\s+variables)\b",
    re.IGNORECASE,
)

MAX_PROSE_CHARS = 1200


def _is_safe(original: str, proposed: str) -> bool:
    """Return True if the AI-proposed text is safe to use."""
    if not proposed or not proposed.strip():
        return False
    if _ARTIFACT_RE.search(proposed) or _GENERIC_TEMPLATE_RE.search(proposed):
        log.debug("narrative_polish: rejected – artifact or generic template phrase")
        return False
    lowered_original = (original or "").lower()
    lowered_proposed = proposed.lower()
    if "p27 expression status" in lowered_original:
        forbidden_p27_labels = (
            "positive/negative", "positive / negative",
            "positive/ negative", "positive/negative-positive",
            "positive/negative-negative", "positive / negative positivity",
        )
        if any(label in lowered_proposed for label in forbidden_p27_labels):
            log.debug("narrative_polish: rejected – p27 outcome label changed")
            return False
        if "p27 expression status" not in lowered_proposed and not any(
            token in lowered_proposed for token in ("p27-positive", "p27-negative", "p27 positive", "p27 negative")
        ):
            log.debug("narrative_polish: rejected – p27 outcome label omitted")
            return False
    # Must not introduce new numeric tokens absent from original
    orig_nums = set(_NUMBER_RE.findall(original))
    prop_nums = set(_NUMBER_RE.findall(proposed))
    new_nums = prop_nums - orig_nums
    if new_nums:
        log.debug("narrative_polish: rejected – new numbers %r", new_nums)
        return False
    # Must not contain causality language
    if _CAUSALITY_RE.search(proposed):
        log.debug("narrative_polish: rejected – causality claim")
        return False
    # Must not remove existing caution phrases from the source
    orig_cautions = _CAUTION_REMOVAL_RE.findall(original)
    prop_cautions_lower = proposed.lower()
    for phrase in orig_cautions:
        if phrase.lower() not in prop_cautions_lower:
            log.debug("narrative_polish: rejected – removed caution phrase %r", phrase)
            return False
    return True


# ---------------------------------------------------------------------------
# Key builders — stable identifiers for each polishable prose chunk
# ---------------------------------------------------------------------------

def _section_key(section_id: str) -> str:
    return f"section:{section_id}"


def _table_key(table_id: str) -> str:
    return f"table:{table_id}"


def _figure_key(figure_id: str) -> str:
    return f"figure:{figure_id}"


# ---------------------------------------------------------------------------
# Prose extraction — text only, no numbers
# ---------------------------------------------------------------------------

def _strip_numbers(text: str) -> str:
    """Replace numeric tokens with '[N]' so the LLM never sees raw stats."""
    return _NUMBER_RE.sub("[N]", text)


def _collect_chunks(blueprint: Dict[str, Any]) -> List[Dict[str, str]]:
    """Collect all polishable prose chunks from the blueprint.

    Each chunk is {'key': str, 'text': str} where text has been stripped of
    numbers (the LLM must not reproduce numbers we didn't give it).
    """
    chunks: List[Dict[str, str]] = []

    results_synthesis = str(blueprint.get("results_synthesis") or "").strip()
    if results_synthesis and len(results_synthesis) > 20:
        chunks.append({
            "key": "results_synthesis",
            "text": _strip_numbers(results_synthesis[:MAX_PROSE_CHARS]),
        })

    for section in blueprint.get("analysis_sections") or []:
        section_id = str(section.get("section_id") or "")
        interp = str(section.get("interpretation") or "").strip()
        if interp and len(interp) > 20:
            chunks.append({
                "key": _section_key(section_id),
                "text": _strip_numbers(interp[:MAX_PROSE_CHARS]),
            })

        for table in section.get("tables") or []:
            table_id = str(table.get("table_id") or "")
            t_interp = str(table.get("interpretation") or "").strip()
            if table_id and t_interp and len(t_interp) > 20:
                chunks.append({
                    "key": _table_key(table_id),
                    "text": _strip_numbers(t_interp[:MAX_PROSE_CHARS]),
                })

        for fig in section.get("figures") or []:
            fig_id = str(fig.get("figure_id") or "")
            f_interp = str(fig.get("interpretation") or "").strip()
            if fig_id and f_interp and len(f_interp) > 20:
                chunks.append({
                    "key": _figure_key(fig_id),
                    "text": _strip_numbers(f_interp[:MAX_PROSE_CHARS]),
                })

    return chunks


# ---------------------------------------------------------------------------
# OpenRouter call
# ---------------------------------------------------------------------------


def _polish_one(text: str) -> Optional[str]:
    """Call Sigma's free-model-only OpenRouter narration polish for a single
    prose chunk. Returns None on failure (missing key, disabled polish,
    timeout, rate limit, invalid response, network/API error, or output
    that fails ai_narrative's evidence-pack validation)."""
    try:
        from app.services import ai_narrative
        evidence = ai_narrative.build_evidence_pack("section_intro", "", text)
        return ai_narrative.polish_writing(evidence)
    except Exception as exc:
        log.debug("narrative_polish: AI narration polish call failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

NarrativeOverrides = Dict[str, str]


def polish_results(results: Dict[str, Any]) -> NarrativeOverrides:
    """Return a dict of {key: polished_text} for all prose chunks in results.

    Keys are produced by _section_key / _table_key / _figure_key, plus the
    top-level "results_synthesis" key. Only chunks where the AI produces
    safe output (per ai_narrative.validate_polish and this module's own
    _is_safe check) are included. Returns an empty dict if AI polish is
    disabled (SIGMA_AI_POLISH_ENABLED), OpenRouter is not configured, or
    every call fails or is rejected — callers always fall through to
    deterministic text in that case.
    """
    from app.core.config import settings
    from app.services import openrouter_client
    if not settings.sigma_ai_polish_enabled or not openrouter_client.is_configured():
        return {}

    blueprint = (results or {}).get("thesis_analysis_blueprint") or {}
    chunks = _collect_chunks(blueprint)
    if not chunks:
        return {}

    overrides: NarrativeOverrides = {}
    for chunk in chunks:
        original_text = chunk["text"]
        proposed = _polish_one(original_text)
        if proposed and _is_safe(original_text, proposed):
            overrides[chunk["key"]] = proposed.strip()
        else:
            log.debug("narrative_polish: chunk %r kept deterministic", chunk["key"])

    return overrides
