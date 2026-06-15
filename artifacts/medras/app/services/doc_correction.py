"""Document correction service — plain-English instruction parser and applicator.

Task 2: Lets users describe changes to their report in plain English on the
Export screen.  Flow:
  1. get_document_inventory()  — build a summary of what's in the document
  2. parse_correction_instructions() — call OpenAI to turn instructions into actions
  3. apply_correction_actions()  — write overrides into entry.meta
  4. record_correction_version()  — snapshot for version history

The export functions in export.py read entry.meta["correction_overrides"] and
apply variable renames, section hiding, and custom notes automatically.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from app.services.llm_client import openrouter_chat, openrouter_is_configured
_TIMEOUT = 25.0

_SYSTEM_PROMPT = (
    "You are a document correction parser for a medical statistics report generator. "
    "Parse the user's plain-English correction instructions into a JSON object with "
    "key 'actions' containing an array of action objects.\n\n"
    "Valid actions:\n"
    '  {"action": "rename_variable", "old_name": "<raw_col_name>", "new_name": "<display_name>"}\n'
    '  {"action": "hide_section", "section": "<one of: data_summary | normality | '
    "primary_analysis | secondary_analyses | figures | results_narrative | methods | "
    'limitations>"}\n'
    '  {"action": "add_note", "location": "<one of: after_cover | after_primary_analysis | '
    'after_secondary | after_methods>", "text": "<note text>"}\n'
    '  {"action": "unsupported", "original_instruction": "<verbatim quote>", '
    '"reason": "<brief explanation>"}\n\n'
    "Rules:\n"
    "- Match variable names to the closest entry in the provided variable inventory "
    "(case-insensitive, partial matching allowed).\n"
    "- Section names must be one of the valid values above.\n"
    "- If an instruction cannot be mapped to a valid action, use the 'unsupported' action.\n"
    "- Respond ONLY with a valid JSON object whose top-level key is 'actions'."
)


# ---------------------------------------------------------------------------
# OpenAI call
# ---------------------------------------------------------------------------


def _parse_actions_from_text(text: str) -> Optional[List[Dict[str, Any]]]:
    """Extract an actions list from raw JSON text returned by any LLM."""
    try:
        parsed = json.loads(text)
        actions = parsed.get("actions")
        if isinstance(actions, list):
            return actions
        for v in parsed.values():
            if isinstance(v, list):
                return v
        return []
    except (json.JSONDecodeError, AttributeError):
        return None


def _call_gemini_correction(
    instructions: str,
    inventory: Dict[str, Any],
) -> Optional[List[Dict[str, Any]]]:
    """Compatibility wrapper for OpenRouter correction-intent parsing."""
    if not openrouter_is_configured():
        return None
    var_list = ", ".join(inventory.get("variables") or [])
    context = (
        f"Available variable names: {var_list or '(none)'}\n"
        "Available sections: data_summary, normality, primary_analysis, "
        "secondary_analyses, figures, results_narrative, methods, limitations"
    )
    full_prompt = (
        f"{_SYSTEM_PROMPT}\n\n"
        f"Document context:\n{context}\n\n"
        f"Correction instructions:\n{instructions}"
    )
    try:
        text = openrouter_chat(
            task="reasoning",
            system=_SYSTEM_PROMPT,
            user=full_prompt,
            temperature=0.1,
            max_tokens=600,
            json_mode=True,
        )
        text = (text or "").strip()
        import re as _re
        text = _re.sub(r"^```(?:json)?\s*", "", text, flags=_re.IGNORECASE)
        text = _re.sub(r"\s*```$", "", text.strip())
        return _parse_actions_from_text(text)
    except Exception as exc:
        logger.warning("OpenRouter correction call failed (%s).", exc)
        return None


def _call_openai_correction(
    instructions: str,
    inventory: Dict[str, Any],
) -> Optional[List[Dict[str, Any]]]:
    """Parse correction instructions into a list of action dicts."""
    var_list = ", ".join(inventory.get("variables") or [])
    context = (
        f"Available variable names: {var_list or '(none)'}\n"
        "Available sections: data_summary, normality, primary_analysis, "
        "secondary_analyses, figures, results_narrative, methods, limitations"
    )

    if openrouter_is_configured():
        try:
            text = openrouter_chat(
                task="reasoning",
                system=_SYSTEM_PROMPT,
                user=(
                    f"Document context:\n{context}\n\n"
                    f"Correction instructions:\n{instructions}"
                ),
                max_tokens=500,
                temperature=0.1,
                json_mode=True,
            )
            result = _parse_actions_from_text(text)
            if result is not None:
                return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenRouter correction parsing failed (%s).", exc)

    logger.warning("OpenRouter unavailable for correction parsing.")
    return None


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


def get_document_inventory(entry: Any, results: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return a summary of what is in the document for the AI context."""
    meta = entry.meta or {}
    classifications = meta.get("classifications") or []
    variables: List[str] = [
        str(c.get("column", "")) for c in classifications if c.get("column")
    ]
    # Include any DataFrame columns not captured in classifications
    if entry.df is not None:
        seen = set(variables)
        for col in entry.df.columns:
            if str(col) not in seen:
                variables.append(str(col))

    test_titles: List[str] = []
    if results:
        for t in results.get("tests") or []:
            title = t.get("title") or t.get("id") or ""
            if title:
                test_titles.append(title)

    return {
        "variables": variables,
        "sections": [
            "data_summary", "normality", "primary_analysis", "secondary_analyses",
            "figures", "results_narrative", "methods", "limitations",
        ],
        "test_titles": test_titles,
    }


# ---------------------------------------------------------------------------
# Apply actions → entry.meta overrides
# ---------------------------------------------------------------------------

_VALID_SECTIONS = {
    "data_summary", "normality", "primary_analysis", "secondary_analyses",
    "figures", "results_narrative", "methods", "limitations",
}
_VALID_NOTE_LOCATIONS = {
    "after_cover", "after_primary_analysis", "after_secondary", "after_methods",
}


def apply_correction_actions(
    entry: Any,
    actions: List[Dict[str, Any]],
) -> Tuple[List[str], List[str]]:
    """Apply parsed actions to entry.meta as correction overrides.

    Returns (applied_messages, skipped_messages).
    """
    meta = entry.meta
    overrides: Dict[str, Any] = dict(meta.get("correction_overrides") or {})

    applied: List[str] = []
    skipped: List[str] = []

    for action in actions:
        act = (action.get("action") or "").strip()

        if act == "rename_variable":
            old_name = (action.get("old_name") or "").strip()
            new_name = (action.get("new_name") or "").strip()
            if old_name and new_name:
                renames: Dict[str, str] = dict(overrides.get("variable_renames") or {})
                renames[old_name] = new_name
                overrides["variable_renames"] = renames
                applied.append(f"Renamed \u2018{old_name}\u2019 \u2192 \u2018{new_name}\u2019")
            else:
                skipped.append("rename_variable: missing old_name or new_name")

        elif act == "hide_section":
            section = (action.get("section") or "").strip().lower().replace(" ", "_")
            if section in _VALID_SECTIONS:
                hidden: List[str] = list(overrides.get("hidden_sections") or [])
                if section not in hidden:
                    hidden.append(section)
                overrides["hidden_sections"] = hidden
                applied.append(f"Hidden section: {section.replace('_', ' ').title()}")
            else:
                skipped.append(
                    f"hide_section: unknown section \u2018{section}\u2019. "
                    f"Valid: {', '.join(sorted(_VALID_SECTIONS))}"
                )

        elif act == "add_note":
            location = (action.get("location") or "").strip().lower().replace(" ", "_")
            text = (action.get("text") or "").strip()
            if location not in _VALID_NOTE_LOCATIONS:
                skipped.append(
                    f"add_note: unknown location \u2018{location}\u2019. "
                    f"Valid: {', '.join(sorted(_VALID_NOTE_LOCATIONS))}"
                )
                continue
            if not text:
                skipped.append("add_note: note text is empty")
                continue
            custom_notes: Dict[str, List[str]] = dict(overrides.get("custom_notes") or {})
            notes_here: List[str] = list(custom_notes.get(location) or [])
            notes_here.append(text)
            custom_notes[location] = notes_here
            overrides["custom_notes"] = custom_notes
            preview = text[:60] + ("\u2026" if len(text) > 60 else "")
            applied.append(
                f"Added note at {location.replace('_', ' ')}: \u201c{preview}\u201d"
            )

        elif act == "unsupported":
            orig = (action.get("original_instruction") or "").strip()
            reason = (action.get("reason") or "").strip()
            preview = orig[:60] + ("\u2026" if len(orig) > 60 else "")
            skipped.append(
                f"Could not apply: \u201c{preview}\u201d"
                + (f" \u2014 {reason}" if reason else "")
            )

        else:
            skipped.append(f"Unknown action type: \u2018{act}\u2019")

    meta["correction_overrides"] = overrides
    return applied, skipped


# ---------------------------------------------------------------------------
# Version history
# ---------------------------------------------------------------------------


def record_correction_version(
    entry: Any,
    instructions: str,
    applied: List[str],
    skipped: List[str],
) -> int:
    """Snapshot the current overrides and return the new version number."""
    meta = entry.meta
    versions: List[Dict[str, Any]] = list(meta.get("correction_versions") or [])
    version_num = len(versions) + 1
    versions.append({
        "version": version_num,
        "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "instructions": instructions[:500],
        "applied": applied,
        "skipped": skipped,
        "overrides_snapshot": dict(meta.get("correction_overrides") or {}),
    })
    meta["correction_versions"] = versions
    return version_num


def get_correction_versions(entry: Any) -> List[Dict[str, Any]]:
    return list(entry.meta.get("correction_versions") or [])


def restore_version(entry: Any, version_num: int) -> bool:
    """Set active overrides back to those recorded in an earlier version."""
    versions: List[Dict[str, Any]] = entry.meta.get("correction_versions") or []
    target = next((v for v in versions if v.get("version") == version_num), None)
    if not target:
        return False
    entry.meta["correction_overrides"] = dict(target.get("overrides_snapshot") or {})
    return True
