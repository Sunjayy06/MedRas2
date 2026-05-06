"""Generate plausible academic references when the user has none of their own.

IMPORTANT: every reference returned by this module is marked
``is_ai_generated=True``. The frontend MUST surface this prominently — these
are NOT verified citations and should be treated as stub suggestions to be
checked or replaced before submission.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.services import plagiarism_analyzer as _pa

MAX_GEN_COUNT = 50
MIN_GEN_COUNT = 5
DEFAULT_RECENCY_YEARS = 7


_GENERATE_SYSTEM_PROMPT = (
    "You are a research librarian helping a researcher seed their reference "
    "list before they search the literature. Given a research topic, propose "
    "plausible-sounding academic references — REAL-style metadata that the "
    "researcher can use as a starting point and then look up properly.\n\n"
    "OUTPUT — return EXACTLY this JSON shape:\n"
    "{\n"
    '  "references": [\n'
    "    {\n"
    '      "title":   "string",\n'
    '      "authors": ["Last F", "Last F"],\n'
    '      "journal": "string (well-known journal in the field)",\n'
    '      "year":    "YYYY",\n'
    '      "volume":  "string or empty",\n'
    '      "issue":   "string or empty",\n'
    '      "pages":   "string or empty",\n'
    '      "doi":     ""               // ALWAYS leave empty — do not invent DOIs\n'
    "    }, ...\n"
    "  ]\n"
    "}\n\n"
    "RULES:\n"
    "- Generate exactly the number of references the user asks for.\n"
    "- Use real, well-known journals appropriate for the field.\n"
    "- Author names should look realistic (initials format).\n"
    "- Years must respect the user's recency window.\n"
    "- Mix landmark older papers and recent work unless told otherwise.\n"
    "- NEVER invent DOI values. Always leave \"doi\" as an empty string.\n"
    "- Do NOT include any disclaimer text inside the JSON — just the data."
)


def _coerce(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict): return {}
    authors = raw.get("authors") or []
    if isinstance(authors, str):
        authors = [a.strip() for a in authors.split(",") if a.strip()]
    return {
        "title":   str(raw.get("title") or "").strip(),
        "authors": [str(a).strip() for a in authors if str(a).strip()][:8],
        "journal": str(raw.get("journal") or "").strip(),
        "year":    str(raw.get("year") or "").strip(),
        "volume":  str(raw.get("volume") or "").strip(),
        "issue":   str(raw.get("issue") or "").strip(),
        "pages":   str(raw.get("pages") or "").strip(),
        "doi":     "",  # always empty for generated refs
        "is_ai_generated": True,
    }


def generate_plausible_references(
    topic: str,
    count: int,
    recency_years: int = DEFAULT_RECENCY_YEARS,
    journals: Optional[List[str]] = None,
    year_now: int = 2026,
) -> List[Dict[str, Any]]:
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("`topic` is required.")
    n = max(MIN_GEN_COUNT, min(int(count or MIN_GEN_COUNT), MAX_GEN_COUNT))
    yrs = max(2, min(int(recency_years or DEFAULT_RECENCY_YEARS), 30))
    earliest = year_now - yrs

    journal_hint = ""
    if journals:
        cleaned = [j.strip() for j in journals if j and j.strip()][:10]
        if cleaned:
            journal_hint = (
                "\nPreferred journals (use these where appropriate, but you may "
                "also use other strong journals in the field): "
                + ", ".join(cleaned)
            )

    user_payload = (
        f"Research topic: {topic}\n"
        f"Number of references to generate: {n}\n"
        f"Recency window: {earliest}–{year_now} (years between {earliest} and {year_now} "
        f"only; you may include up to two landmark older citations if they are seminal)."
        f"{journal_hint}"
    )

    def _call() -> Dict[str, Any]:
        return _pa._call_gemini_json(  # noqa: SLF001
            system_prompt=_GENERATE_SYSTEM_PROMPT,
            user_text=user_payload,
            max_tokens=8192,
        )

    try:
        raw = _pa._with_retry(_call, attempts=2, base_delay=1.5)
    except _pa.ProviderQuotaExhausted:
        raise
    except json.JSONDecodeError:
        return []

    if not isinstance(raw, dict): return []
    items = raw.get("references")
    if not isinstance(items, list): return []
    out: List[Dict[str, Any]] = []
    for it in items[:MAX_GEN_COUNT]:
        ref = _coerce(it)
        if ref.get("title"):
            out.append(ref)
    return out[:n]
