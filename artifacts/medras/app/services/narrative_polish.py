"""OpenRouter-powered narrative polish for Chapter V exports.

Polishes the *prose* layer only — section introductions, table interpretation
sentences, and figure captions.  Statistical values (p-values, effect sizes,
sample sizes, percentages, raw numbers) are **never** supplied to the LLM and
**never** accepted back from it.  A safety validator rejects any AI output that
slips in new numeric content or causality claims, falling back to the
deterministic text.

Usage
-----
Call ``polish_results(results)`` to get a ``NarrativeOverrides`` dict.
Pass that dict to ``generate_docx(results, polish_overrides=overrides)`` or
``generate_pdf(results, polish_overrides=overrides)``.

If OpenRouter is not configured or the caller opts out, the functions are
no-ops that return an empty dict (so exports fall through to deterministic text
unchanged).
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

MAX_PROSE_CHARS = 1200


def _is_safe(original: str, proposed: str) -> bool:
    """Return True if the AI-proposed text is safe to use."""
    if not proposed or not proposed.strip():
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

_SYSTEM_PROMPT = """\
You are a medical thesis narrative editor. You will receive short prose
paragraphs from a thesis Chapter V (Observation and Results) and must
rephrase them to sound formal, precise, and suitable for a PG medical thesis.

Rules you MUST follow:
1. Do NOT introduce any numbers, percentages, fractions, or statistics of any kind.
2. Do NOT make causal claims (do not use "causes", "leads to", "responsible for").
3. Preserve every caution or limitation statement verbatim — do not soften or omit them.
4. Keep roughly the same length as the original.
5. Use formal academic English suitable for an Indian MD/MS thesis.
6. Return ONLY the rewritten paragraph — no preamble, no commentary.
"""


def _polish_one(text: str) -> Optional[str]:
    """Call OpenRouter to polish a single prose chunk. Returns None on failure."""
    try:
        from app.services.llm_client import openrouter_chat, openrouter_is_configured
        if not openrouter_is_configured():
            return None
        return openrouter_chat(
            task="thesis_writing",
            system=_SYSTEM_PROMPT,
            user=text,
            max_tokens=400,
            temperature=0.25,
        )
    except Exception as exc:
        log.debug("narrative_polish: OpenRouter call failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

NarrativeOverrides = Dict[str, str]


def polish_results(results: Dict[str, Any]) -> NarrativeOverrides:
    """Return a dict of {key: polished_text} for all prose chunks in results.

    Keys are produced by _section_key / _table_key / _figure_key.
    Only chunks where the AI produces safe output are included.
    Returns an empty dict if OpenRouter is not configured or all calls fail.
    """
    from app.services.llm_client import openrouter_is_configured
    if not openrouter_is_configured():
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
