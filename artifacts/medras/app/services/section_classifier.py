"""Gemini-backed proposal-section classifier and section-draft generator.

Two public entry points:

* ``classify_corpus_into_sections(corpus, section_names, format_label)`` —
  given the concatenated text of one or more uploaded documents and the
  ordered list of section names a user has chosen for their format, return
  a ``{section_name: extracted_verbatim_text}`` map. Sections that the
  classifier could not find in the corpus return ``""``.

* ``generate_missing_section(section_name, format_label, filled)`` —
  given the format and what the user has already written in other
  sections, draft the missing section. Used by the "Let MedRAS Generate
  This" button in the outline step.

Both helpers reuse the same Gemini client + retry/timeout helpers as the
plagiarism module so we get the same error sanitisation, transient-error
retry behaviour, and provider-quota propagation.
"""

from __future__ import annotations

import json
from typing import Dict, List

from app.services import plagiarism_analyzer as _pa


# ---------------------------------------------------------------------------
# Caps
# ---------------------------------------------------------------------------

# Hard cap on corpus size handed to the LLM. ~30k chars ≈ ~7-8k tokens which
# fits comfortably inside gemini-2.5-flash's window with room for the response.
MAX_CORPUS_CHARS = 30_000

# Per-section response cap. Trim before returning to the client.
MAX_SECTION_CHARS = 8_000

# Hard wall-clock timeout for a single Gemini call (seconds).
LLM_TIMEOUT_SECONDS = 45.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate(text: str, cap: int) -> str:
    if not text:
        return ""
    if len(text) <= cap:
        return text
    return text[:cap].rsplit(" ", 1)[0] + " …"


def _normalise_section_name(name: str) -> str:
    return " ".join((name or "").split()).strip()


# ---------------------------------------------------------------------------
# Classify corpus → sections
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM_PROMPT = (
    "You are a research-proposal section classifier. The researcher has "
    "uploaded one or more existing documents (drafts, notes, papers). Your "
    "job is to identify which sentences and paragraphs from the uploaded "
    "corpus belong to each named section of their target proposal format, "
    "and return that text VERBATIM.\n\n"
    "STRICT RULES:\n"
    "1. Return only sentences/paragraphs that actually appear in the corpus. "
    "Do NOT paraphrase, summarise, expand, or invent any text.\n"
    "2. Multiple paragraphs may map to the same section — concatenate them "
    "with double newlines, in the order they appear in the corpus.\n"
    "3. If a section is not present in the corpus, return an empty string \"\" "
    "for that key. Never make something up.\n"
    "4. The same paragraph may appear in at most one section. Pick the best fit.\n"
    "5. Use the EXACT section names provided as JSON keys (case-sensitive).\n"
    "6. Output valid JSON only — a single object whose keys are the section "
    "names and whose values are strings."
)


def classify_corpus_into_sections(
    corpus: str,
    section_names: List[str],
    format_label: str,
) -> Dict[str, str]:
    """Map a corpus of free text onto the named sections of a proposal format.

    Returns a dict ``{section_name: verbatim_text_or_empty}`` covering every
    name in ``section_names``. Raises the same ``ProviderQuotaExhausted`` /
    runtime errors as the plagiarism analyzer when the LLM fails.
    """
    cleaned = (corpus or "").strip()
    cleaned_names = [_normalise_section_name(n) for n in section_names if _normalise_section_name(n)]

    # Empty corpus or no sections → return an all-empty map without an LLM call.
    if not cleaned or not cleaned_names:
        return {n: "" for n in cleaned_names}

    corpus_for_llm = _truncate(cleaned, MAX_CORPUS_CHARS)

    user_payload = (
        f"Target proposal format: {format_label or 'Generic'}\n\n"
        "Sections to fill (use these EXACT strings as JSON keys, in this order):\n"
        + "\n".join(f"{i + 1}. {name}" for i, name in enumerate(cleaned_names))
        + "\n\n--- UPLOADED CORPUS ---\n"
        + corpus_for_llm
    )

    def _call() -> Dict[str, str]:
        raw = _pa._call_gemini_json(  # noqa: SLF001 — reuse the canonical helper
            system_prompt=_CLASSIFY_SYSTEM_PROMPT,
            user_text=user_payload,
            max_tokens=8192,
        )
        if not isinstance(raw, dict):
            return {}
        out: Dict[str, str] = {}
        for name in cleaned_names:
            val = raw.get(name)
            if isinstance(val, str):
                out[name] = _truncate(val.strip(), MAX_SECTION_CHARS)
            else:
                out[name] = ""
        return out

    try:
        return _pa._with_retry(_call, attempts=2, base_delay=1.5)
    except _pa.ProviderQuotaExhausted:
        raise
    except json.JSONDecodeError:
        # Model returned malformed JSON — degrade gracefully so the user can
        # still proceed with empty sections rather than a hard error.
        return {n: "" for n in cleaned_names}


# ---------------------------------------------------------------------------
# Generate a missing section
# ---------------------------------------------------------------------------

_GENERATE_SYSTEM_PROMPT = (
    "You are a senior medical-research proposal writing assistant. The "
    "researcher has filled in several sections of their proposal but one is "
    "still empty. Draft a coherent, well-structured first version of the "
    "missing section that is consistent with what they have already written.\n\n"
    "RULES:\n"
    "- Write in formal academic English appropriate for a research proposal.\n"
    "- Do NOT include the section heading itself — return only the body text.\n"
    "- Do NOT invent specific numbers, citations, statistics or institution "
    "names that aren't supported by the other sections. Use placeholders like "
    "\"[insert sample size]\" or \"[add citation]\" where specifics are needed.\n"
    "- Aim for roughly 200-400 words unless the section is structurally short "
    "(e.g. Title, Abstract).\n"
    "- Match the tone and terminology of the existing sections."
)


def generate_missing_section(
    section_name: str,
    format_label: str,
    filled: Dict[str, str],
) -> str:
    """Draft the named section based on what the user has filled elsewhere."""
    target = _normalise_section_name(section_name)
    if not target:
        raise ValueError("section_name is required")

    # Build a context block from the filled sections, excluding any that are
    # empty or whitespace-only.
    context_parts: List[str] = []
    for name, content in (filled or {}).items():
        clean_name = _normalise_section_name(name)
        clean_content = (content or "").strip()
        if not clean_name or not clean_content or clean_name == target:
            continue
        context_parts.append(f"## {clean_name}\n{_truncate(clean_content, 4_000)}")

    if not context_parts:
        context_block = "(The researcher has not filled in any other sections yet — write a sensible first draft based on the format alone.)"
    else:
        context_block = "\n\n".join(context_parts)
        context_block = _truncate(context_block, MAX_CORPUS_CHARS)

    user_payload = (
        f"Target proposal format: {format_label or 'Generic'}\n"
        f"Section to draft: {target}\n\n"
        "--- WHAT THE RESEARCHER HAS WRITTEN SO FAR ---\n"
        + context_block
        + "\n\n--- TASK ---\n"
        f"Write the body of the \"{target}\" section now."
    )

    def _call() -> str:
        return _pa._call_gemini_text(  # noqa: SLF001
            system_prompt=_GENERATE_SYSTEM_PROMPT,
            user_text=user_payload,
            max_tokens=2048,
            temperature=0.4,
            timeout=LLM_TIMEOUT_SECONDS,
        )

    try:
        text = _pa._with_retry(_call, attempts=2, base_delay=1.5)
    except _pa.ProviderQuotaExhausted:
        raise

    return _truncate((text or "").strip(), MAX_SECTION_CHARS)
