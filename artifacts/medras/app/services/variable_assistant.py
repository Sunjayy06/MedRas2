"""Rule-based Variable Assistant for Step 3.

There is no LLM here. The user types a short natural-language instruction,
we pattern-match it against a small intent vocabulary, and either apply
the change directly to the in-memory DataFrame or return a clarification
message asking the user to be more specific.

Supported intents (anything else returns ``clarify``):

* ``strip_prefix``       — strip an alphabetic prefix like "Grade 4" → 4
  and convert the column to numeric. Original values are kept in
  ``{col}_original`` so the user can always go back.
* ``add_numeric_column`` — derive a numeric companion column from a text
  column whose values look like ``"Grade 4"`` / ``"Stage III"``. Creates
  ``{col}_numeric`` (scale).
* ``rename``             — rename a column to a new identifier.
* ``change_type``        — change the classifier type of a column to one of
  the seven MedRAS types (scale / ordinal / nominal / discrete / date /
  id / exclude).
* ``exclude_column``     — convenience shorthand for change_type → exclude.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


_VALID_TYPES = {"scale", "ordinal", "nominal", "discrete", "date", "id", "exclude"}
_LEADING_PREFIX_RE = re.compile(r"^\s*([A-Za-z]+)\s+")
_TRAILING_NUM_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*$")
_ROMAN_RE = re.compile(r"^\s*([A-Za-z]+)\s+([IVXLCDM]+)\s*$", re.IGNORECASE)
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _roman_to_int(s: str) -> Optional[int]:
    s = s.upper()
    total = 0
    prev = 0
    for ch in reversed(s):
        v = _ROMAN_VALUES.get(ch)
        if v is None:
            return None
        if v < prev:
            total -= v
        else:
            total += v
            prev = v
    return total


# ---------------------------------------------------------------------------
# Intent parsing
# ---------------------------------------------------------------------------


def _find_column(message: str, columns: List[str]) -> Optional[str]:
    """Match a column name out of the message, longest-first to avoid
    matching ``"VAS"`` when the column is ``"VAS Score"``."""
    if not columns:
        return None
    msg_low = message.lower()
    # 1) exact (case-insensitive) phrase match, longest first.
    for col in sorted(columns, key=lambda c: -len(c)):
        if col.lower() in msg_low:
            return col
    # 2) quoted token.
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", message)
    for q in quoted:
        for col in columns:
            if col.lower() == q.lower():
                return col
    return None


def parse_intent(message: str, columns: List[str]) -> Dict[str, Any]:
    """Map ``message`` to one of the supported intents. Always returns a
    dict with at least ``action`` and ``column`` keys (column may be None
    when the action is ``clarify``)."""
    msg = (message or "").strip()
    msg_low = msg.lower()
    column = _find_column(msg, columns)

    # rename — "rename X to Y"
    m = re.search(r"rename\s+(.+?)\s+to\s+([A-Za-z0-9_ ]+)", msg, re.IGNORECASE)
    if m:
        old = m.group(1).strip().strip("'\"")
        new = m.group(2).strip().strip("'\"")
        col = next((c for c in columns if c.lower() == old.lower()), column)
        return {
            "action": "rename" if col else "clarify",
            "column": col,
            "params": {"new_name": new},
        }

    # exclude_column — "exclude X" / "remove X from analysis"
    if re.search(r"\bexclude\b|\bdrop\b|\bremove (?:from|from analysis)\b", msg_low):
        if column:
            return {"action": "exclude_column", "column": column, "params": {}}

    # change_type — "treat X as scale" / "set X to nominal"
    m = re.search(
        r"(?:treat|set|change|mark|make)\s+(.+?)\s+(?:as|to)\s+(scale|ordinal|nominal|discrete|date|id|exclude)",
        msg, re.IGNORECASE,
    )
    if m:
        target_col = next((c for c in columns if c.lower() == m.group(1).strip().lower()), column)
        new_type = m.group(2).lower()
        if target_col and new_type in _VALID_TYPES:
            return {
                "action": "change_type",
                "column": target_col,
                "params": {"new_type": new_type},
            }

    # add_numeric_column — "I want both mean and frequency", "add a numeric
    # version", "give me a numeric column"
    if re.search(r"\b(both|mean and frequency|numeric (?:column|version)|add a number|number column)\b", msg_low):
        if column:
            return {"action": "add_numeric_column", "column": column, "params": {}}

    # strip_prefix — "strip Grade", "remove the Grade prefix", "drop the
    # word Grade", "Grade in front"
    m = re.search(
        r"(?:strip|remove|drop|delete)\s+(?:the\s+)?(?:word\s+|prefix\s+)?['\"]?([A-Za-z]+)['\"]?\s+(?:prefix|in front|from)?",
        msg, re.IGNORECASE,
    )
    if m and column:
        return {
            "action": "strip_prefix",
            "column": column,
            "params": {"prefix": m.group(1)},
        }
    # Bare "strip prefix from VAS" / "strip the prefix"
    if re.search(r"strip.*prefix|remove.*prefix|drop.*prefix", msg_low) and column:
        return {"action": "strip_prefix", "column": column, "params": {}}

    return {"action": "clarify", "column": column, "params": {}}


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------


def _strip_prefix(
    df: pd.DataFrame, column: str, prefix: Optional[str]
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Strip a leading alphabetic token from values in ``column`` and
    coerce the result to numeric. Keeps original in ``{column}_original``."""
    if column not in df.columns:
        raise ValueError(f"Unknown column '{column}'.")
    new_df = df.copy()
    series = new_df[column].astype(str)

    backup = column + "_original"
    if backup not in new_df.columns:
        new_df[backup] = new_df[column]

    if prefix:
        pat = re.compile(rf"^\s*{re.escape(prefix)}\s+", re.IGNORECASE)
        cleaned = series.str.replace(pat, "", regex=True)
    else:
        cleaned = series.str.replace(_LEADING_PREFIX_RE, "", regex=True)

    numeric = pd.to_numeric(cleaned, errors="coerce")
    new_df[column] = numeric

    converted = int(numeric.notna().sum())
    return new_df, {
        "column": column,
        "backup_column": backup,
        "converted_rows": converted,
        "preview": numeric.dropna().head(3).tolist(),
    }


def _add_numeric_column(
    df: pd.DataFrame, column: str
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Derive ``{column}_numeric`` from a text column. Best-effort: handles
    "Grade 4" style, plain integers, and Roman numerals ("Stage III")."""
    if column not in df.columns:
        raise ValueError(f"Unknown column '{column}'.")
    new_df = df.copy()
    series = new_df[column].astype(str)

    def _coerce(value: str) -> Optional[float]:
        s = value.strip()
        if not s or s.lower() == "nan":
            return None
        try:
            return float(s)
        except ValueError:
            pass
        m = _TRAILING_NUM_RE.search(s)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
        m = _ROMAN_RE.match(s)
        if m:
            r = _roman_to_int(m.group(2))
            if r is not None:
                return float(r)
        return None

    derived = series.map(_coerce)
    new_col = column + "_numeric"
    new_df[new_col] = pd.to_numeric(derived, errors="coerce")
    return new_df, {
        "column": column,
        "new_column": new_col,
        "converted_rows": int(new_df[new_col].notna().sum()),
        "preview": new_df[new_col].dropna().head(3).tolist(),
    }


def _rename(
    df: pd.DataFrame, column: str, new_name: str
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("New name is empty.")
    if new_name in df.columns and new_name != column:
        raise ValueError(f"A column called '{new_name}' already exists.")
    new_df = df.rename(columns={column: new_name})
    return new_df, {"old_column": column, "new_column": new_name}


# ---------------------------------------------------------------------------
# Dispatch + summary phrasing
# ---------------------------------------------------------------------------


def apply_action(
    df: pd.DataFrame, intent: Dict[str, Any]
) -> Tuple[Optional[pd.DataFrame], Dict[str, Any]]:
    """Run the action and return ``(new_df_or_None, result_meta)``.

    ``new_df_or_None`` is None for actions that don't mutate the DataFrame
    (currently only ``clarify``). All other actions return a new DataFrame
    so the caller can swap it into the dataset_store atomically."""
    action = intent.get("action")
    column = intent.get("column")
    params = intent.get("params") or {}

    if action == "strip_prefix":
        new_df, meta = _strip_prefix(df, column, params.get("prefix"))
        return new_df, {
            **meta,
            "type_after": "scale",
            "confirmation_message": (
                f"Stripped the prefix from “{column}”. "
                f"{meta['converted_rows']} values are now numeric "
                f"(e.g. {meta['preview'][:3]}). "
                f"The original text is kept in “{meta['backup_column']}”."
            ),
        }

    if action == "add_numeric_column":
        new_df, meta = _add_numeric_column(df, column)
        return new_df, {
            **meta,
            # The newly created `_numeric` column is the one we want flagged as
            # scale; the original text column stays as-is (ordinal/nominal).
            "target_column": meta["new_column"],
            "type_after": "scale",
            "confirmation_message": (
                f"Added “{meta['new_column']}” as a numeric companion to "
                f"“{column}”. {meta['converted_rows']} rows converted "
                f"(e.g. {meta['preview']}). “{column}” stays as the "
                f"original ordinal column for frequency tables."
            ),
        }

    if action == "rename":
        new_name = params.get("new_name", "")
        new_df, meta = _rename(df, column, new_name)
        return new_df, {
            **meta,
            "confirmation_message": (
                f"Renamed “{meta['old_column']}” → “{meta['new_column']}”."
            ),
        }

    if action == "change_type":
        # No DataFrame mutation; the caller updates classifications.
        new_type = params.get("new_type")
        return None, {
            "column": column,
            "new_type": new_type,
            "confirmation_message": (
                f"Marked “{column}” as {new_type}."
            ),
        }

    if action == "exclude_column":
        return None, {
            "column": column,
            "new_type": "exclude",
            "confirmation_message": (
                f"Excluded “{column}” from analysis."
            ),
        }

    # clarify
    return None, {
        "confirmation_message": (
            "I’m not sure what to do with that yet. Try something like:\n"
            "• “Strip the Grade prefix from VAS Score”\n"
            "• “I want both mean and frequency for VAS Score”\n"
            "• “Treat Hospital_visits as discrete”\n"
            "• “Rename Hb to Haemoglobin”\n"
            "• “Exclude Notes from analysis”"
        ),
    }
