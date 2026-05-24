"""PICO query decomposer for Study Builder.

Breaks a research question into Population / Intervention / Comparison /
Outcome components and generates 2–3 optimised database search queries.
Falls back to keyword extraction when Gemini is unavailable.
"""

from __future__ import annotations

import json
import logging
import os
import re

log = logging.getLogger(__name__)

_STOP_WORDS: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "of", "in", "is", "are", "for", "to",
    "with", "on", "at", "by", "from", "be", "was", "were", "this", "that",
    "what", "which", "how", "does", "do", "can", "will", "should", "would",
    "it", "its", "about", "between", "than", "as", "vs", "versus", "has",
    "have", "had", "any", "all", "also", "most", "some", "more", "less",
    "there", "their", "when", "where", "who", "why", "effect", "role",
    "impact", "use", "used", "using", "study", "studies", "research",
    "evidence", "literature", "review", "patients", "patient",
})

_SYSTEM = """\
You are a medical research librarian specialising in systematic search strategy.

Given a research question and any prior conversation context, you must:

1. Identify PICO components (write "N/A" when a component is absent):
   - population: the patient group or subjects
   - intervention: treatment, exposure, or factor under study
   - comparison: what it is compared against (control, placebo, alternative)
   - outcome: the measured endpoint

2. Generate exactly 2–3 independent PubMed-style search queries using
   Boolean operators (AND / OR) and MeSH-equivalent terminology.
   Each query should explore a slightly different angle of the question.

IMPORTANT: Return ONLY valid JSON — no markdown fences, no commentary:
{
  "population": "...",
  "intervention": "...",
  "comparison": "...",
  "outcome": "...",
  "search_queries": ["query_1", "query_2", "optional_query_3"]
}
"""


def _keyword_fallback(question: str, history: list[dict]) -> dict:
    """Pure-Python fallback when AI is unavailable."""
    clean  = re.sub(r"[^\w\s]", " ", question.lower())
    words  = [w for w in clean.split() if w not in _STOP_WORDS and len(w) > 2]
    base   = " AND ".join(words[:5]) if words else question
    queries: list[str] = [base]
    if history:
        prev = history[-1].get("question", "")
        pwords = [
            w for w in re.sub(r"[^\w\s]", " ", prev.lower()).split()
            if w not in _STOP_WORDS and len(w) > 3
        ][:3]
        if pwords:
            queries.append(f"({base}) AND ({' AND '.join(pwords)})")
    return {
        "population": "N/A", "intervention": "N/A",
        "comparison": "N/A", "outcome": "N/A",
        "search_queries": queries,
    }


async def decompose(question: str, history: list[dict]) -> dict:
    """Decompose *question* with *history* context.

    Returns a dict with keys: ``population``, ``intervention``,
    ``comparison``, ``outcome``, ``search_queries`` (list of 1–3 strings).
    Never raises — falls back to keyword extraction on any failure.
    """
    from app.services.llm_client import get_gemini_client, gemini_is_configured
    if not gemini_is_configured():
        return _keyword_fallback(question, history)

    history_text = (
        "\n".join(
            f"Q: {t['question']}\nA: {t['answer_summary']}"
            for t in history
        )
        if history else "No prior conversation."
    )
    user_msg = (
        f"Conversation history:\n{history_text}\n\n"
        f"Current research question: {question}"
    )

    try:
        from google.genai import types as gtypes

        gc   = get_gemini_client()
        resp = gc.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{_SYSTEM}\n\n{user_msg}",
            config=gtypes.GenerateContentConfig(
                max_output_tokens=512,
                temperature=0.05,
            ),
        )
        raw  = (resp.text or "").strip()
        raw  = re.sub(r"^```(?:json)?\s*", "", raw)
        raw  = re.sub(r"\s*```\s*$",        "", raw)
        data = json.loads(raw)

        queries = [
            str(q).strip()
            for q in (data.get("search_queries") or [])
            if str(q).strip()
        ]
        if not queries:
            queries = [question]

        return {
            "population":    str(data.get("population",   "N/A")),
            "intervention":  str(data.get("intervention", "N/A")),
            "comparison":    str(data.get("comparison",   "N/A")),
            "outcome":       str(data.get("outcome",      "N/A")),
            "search_queries": queries[:3],
        }
    except Exception as exc:
        log.warning("PICO decomposer error (%s) — keyword fallback", exc)
        return _keyword_fallback(question, history)
