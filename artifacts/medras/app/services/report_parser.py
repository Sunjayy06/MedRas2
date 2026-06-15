"""Parse plagiarism-checker reports into a section -> similarity-% map.

Reports vary wildly between Turnitin / Drillbit / iThenticate / etc., so
we use a small set of robust heuristics rather than per-vendor parsers:

  1. Extract plain text from the uploaded report (PDF / DOCX / TXT).
  2. Look for explicit "Section: NN%" or "Section ... NN%" lines.
  3. As a fallback, scan for known section keywords (Abstract,
     Introduction, Methods, Results, Discussion, Conclusion, etc.) and
     match each occurrence to the nearest percentage value within a
     small character window.

The output map keys are normalised lower-case section names. Callers
(see ``plagiarism_jobs``) join the map back to actual section labels
via :func:`match_intensity_for_label`.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

# Section keywords we know about. Order matters for the longest-first
# match (e.g. "Literature Review" must beat "Review").
KNOWN_SECTIONS: List[str] = [
    "Literature Review",
    "Materials and Methods",
    "Materials & Methods",
    "Results and Discussion",
    "Background",
    "Abstract",
    "Introduction",
    "Methodology",
    "Methods",
    "Findings",
    "Results",
    "Discussion",
    "Conclusion",
    "Conclusions",
    "Recommendations",
    "Acknowledgements",
    "Acknowledgments",
    "Summary",
    "Bibliography",
    "References",
    "Appendix",
    "Appendices",
]

# Character window used when looking for a percentage near a section
# heading match. 120 chars is roughly two short lines — generous enough
# for the typical "Introduction ............... 34%" report layout but
# tight enough not to bleed into the next section's number.
PROXIMITY_WINDOW = 120

# Phrases that, when present near a section name, bump our confidence
# that the section is flagged even if the percentage is missing.
FLAG_PHRASES = [
    "high similarity",
    "match found",
    "matches found",
    "plagiarised",
    "plagiarized",
    "flagged",
    "exact match",
    "highlighted",
]


def _normalise(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().lower()


def parse_report_text(text: str) -> Dict[str, Dict[str, Any]]:
    """Extract a {section: {similarity_percent, flagged}} map from text.

    Always returns a dict (possibly empty). Never raises — a malformed
    report just yields an empty map and the caller falls back to
    rewriting the whole document.
    """
    if not text or not text.strip():
        return {}

    # ----- Pass 1: explicit "Section: NN%" / "Section ......... NN%"
    # The label group permits spaces and ampersands so multi-word
    # headings are captured. The connector permits any mix of dots,
    # dashes, colons and whitespace (the "Section .......... 34%"
    # dotted-leader layout used by Turnitin / Drillbit / iThenticate).
    # We constrain the percent to 0-100.
    found: Dict[str, float] = {}
    explicit_rx = re.compile(
        r"\b(?P<label>[A-Z][A-Za-z& ]{2,40}?)\b[\s.:\-–—]{1,80}?"
        r"(?P<pct>\d{1,3}(?:\.\d{1,2})?)\s*%",
        re.MULTILINE,
    )
    for m in explicit_rx.finditer(text):
        raw = m.group("label").strip()
        pct = float(m.group("pct"))
        if pct > 100:
            continue  # almost certainly not a similarity number
        # Only keep matches whose label *contains* a known section
        # keyword — otherwise random text like "Page 1: 25%" would
        # pollute the map.
        for known in KNOWN_SECTIONS:
            if known.lower() in raw.lower():
                key = _normalise(known)
                # Keep the highest reported value if duplicates appear.
                if key not in found or pct > found[key]:
                    found[key] = pct
                break

    # ----- Pass 2: proximity match for any known section keyword
    # (catches "Introduction ........ 34" laid out in columns or with
    # the percent on the next line).
    pct_rx = re.compile(r"(\d{1,3}(?:\.\d{1,2})?)\s*%")
    pct_positions: List[Tuple[int, float]] = []
    for m in pct_rx.finditer(text):
        try:
            v = float(m.group(1))
            if 0 <= v <= 100:
                pct_positions.append((m.start(), v))
        except ValueError:
            continue

    for known in KNOWN_SECTIONS:
        key = _normalise(known)
        if key in found:
            continue
        # Find every occurrence of this section keyword and look
        # FORWARD for the nearest percentage. We deliberately ignore
        # percentages that sit *before* the keyword because reports
        # always lay out "Section <leader> NN%" — picking up the
        # number from the preceding section's row would systematically
        # mis-attribute every value by one row.
        for label_match in re.finditer(re.escape(known), text, re.IGNORECASE):
            lend = label_match.end()
            best: Optional[float] = None
            best_dist: Optional[int] = None
            for pos, val in pct_positions:
                if pos < lend:
                    continue
                dist = pos - lend
                if dist > PROXIMITY_WINDOW:
                    continue
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best = val
            if best is not None:
                if key not in found or best > found[key]:
                    found[key] = best
                break  # first hit per keyword is enough

    # ----- Pass 3: keyword-without-percentage flag detection
    # If a known section appears within 60 chars of a flag phrase but
    # we never found a percentage for it, mark it as flagged at a
    # conservative 15% (drops it into ORANGE intensity).
    lower = text.lower()
    for known in KNOWN_SECTIONS:
        key = _normalise(known)
        if key in found:
            continue
        kpos = lower.find(known.lower())
        if kpos < 0:
            continue
        window = lower[max(0, kpos - 60): kpos + len(known) + 60]
        if any(p in window for p in FLAG_PHRASES):
            found[key] = 15.0

    return {
        key: {"similarity_percent": round(pct, 1), "flagged": pct >= 10.0}
        for key, pct in found.items()
    }


# --------------------------------------------------------------------------
# Public helpers used by the job/route layer
# --------------------------------------------------------------------------

INTENSITY_SKIP = "skip"          # < 10%   — leave verbatim
INTENSITY_LIGHT = "light"        # 10-15%  — stages A + B only
INTENSITY_NORMAL = "normal"      # 15-30%  — all 3 stages
INTENSITY_AGGRESSIVE = "aggressive"  # > 30%   — all 3 stages, max effort


def intensity_for_percent(pct: Optional[float]) -> str:
    """Bucket a similarity % into one of four rewrite-intensity levels."""
    if pct is None:
        return INTENSITY_NORMAL  # no data → safe default
    if pct < 10:
        return INTENSITY_SKIP
    if pct < 15:
        return INTENSITY_LIGHT
    if pct <= 30:
        return INTENSITY_NORMAL
    return INTENSITY_AGGRESSIVE


def match_intensity_for_label(
    label: str,
    flagged_map: Dict[str, Dict[str, Any]],
) -> Tuple[str, Optional[float]]:
    """Pick an intensity for a section label by fuzzy-matching the map.

    The caller's section labels come from the original document's
    heading text ("Materials and Methods", "1. Introduction") while the
    map keys are normalised report names ("methods", "introduction").
    We do case-insensitive substring matching in both directions and
    fall back to NORMAL intensity if nothing matches.
    """
    if not label:
        return INTENSITY_NORMAL, None
    nlabel = _normalise(label)

    # References / Bibliography are ALWAYS skipped, regardless of
    # report contents — our pipeline treats them as verbatim. Done in
    # process_one_section already, but mirror it here for clarity.
    if "reference" in nlabel or "bibliograph" in nlabel:
        return INTENSITY_SKIP, None

    # 1. Exact normalised match
    if nlabel in flagged_map:
        pct = flagged_map[nlabel].get("similarity_percent")
        return intensity_for_percent(pct), pct

    # 2. Substring match either direction (e.g. "1. Introduction" ↔ "introduction",
    #    "Materials and Methods" ↔ "methods").
    for key, info in flagged_map.items():
        if key in nlabel or nlabel in key:
            pct = info.get("similarity_percent")
            return intensity_for_percent(pct), pct

    # 3. No match found → don't have data, treat as normal rewrite
    return INTENSITY_NORMAL, None


def _parse_with_gemini(text: str, software: str = "Other") -> Dict[str, Dict[str, Any]]:
    """LLM fallback: ask OpenRouter to extract a section→similarity map.

    Called when the regex parser finds 0 sections — covers complex table
    layouts, colour-coded PDFs, and vendor-specific formats that regex
    can't reliably parse.

    Returns the same {normalised_label: {"similarity_percent", "flagged"}}
    dict as parse_report_text(), or {} on any failure.
    """
    try:
        from app.services.llm_client import openrouter_chat, openrouter_is_configured
        if not openrouter_is_configured():
            return {}

        # Use the first 8000 characters — the section overview is almost
        # always in the first few pages of a report PDF.
        snippet = (text or "")[:8000].strip()
        if not snippet:
            return {}

        prompt = (
            f"The following is extracted text from a plagiarism report generated by "
            f"{software}. Your task: find every section name and its similarity "
            f"percentage and return a JSON object.\n\n"
            "Rules:\n"
            "- Keys are normalised, lowercase section names "
            '  (e.g. "introduction", "methods", "results and discussion").\n'
            "- Each value is an object with:\n"
            '    "similarity_percent": <number 0-100>,\n'
            '    "flagged": <true if similarity_percent >= 10, else false>\n'
            "- Only include sections that have an explicit similarity percentage.\n"
            "- If you cannot find any section percentages, return {}.\n"
            "- Respond with ONLY valid JSON, no explanation, no code fences.\n\n"
            f"Report text:\n{snippet}"
        )

        raw = openrouter_chat(
            task="reasoning",
            system="Extract structured fields from a plagiarism report.",
            user=prompt,
            max_tokens=800,
            temperature=0.1,
            json_mode=True,
        )
        raw = (raw or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw.strip())
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return {}

        result: Dict[str, Dict[str, Any]] = {}
        for key, val in parsed.items():
            if not isinstance(val, dict):
                continue
            pct = val.get("similarity_percent")
            if pct is None:
                continue
            try:
                pct = float(pct)
            except (TypeError, ValueError):
                continue
            if not (0 <= pct <= 100):
                continue
            norm_key = _normalise(str(key))
            if norm_key:
                result[norm_key] = {
                    "similarity_percent": round(pct, 1),
                    "flagged": pct >= 10.0,
                }
        return result
    except Exception:  # noqa: BLE001
        return {}


def summarise_report(flagged_map: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    """Quick counts for the Path-A summary box on the results page."""
    needs = sum(1 for v in flagged_map.values() if v.get("similarity_percent", 0) >= 10)
    acceptable = sum(1 for v in flagged_map.values() if 0 <= v.get("similarity_percent", 0) < 10)
    return {
        "total_sections_in_report": len(flagged_map),
        "needs_rewriting": needs,
        "already_acceptable": acceptable,
    }
