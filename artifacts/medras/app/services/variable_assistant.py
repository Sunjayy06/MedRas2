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
* ``suggest``            — informational only; the API layer answers with a
  context-aware recommendation built from the actual dataset (see
  ``suggest_message`` below).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from app.services import variable_classifier


_VALID_TYPES = {
    "scale", "ordinal", "nominal", "discrete", "date", "id", "exclude",
    # Per spec Rule 5: pseudo-types that mean "leave the variable as
    # scale, just flip the descriptive sub-type". The API layer turns
    # these into a `scale_subtype` mutation rather than a full retype.
    "scale_discrete", "scale_continuous",
}
_LEADING_PREFIX_RE = re.compile(r"^\s*([A-Za-z]+)\s+")
_TRAILING_NUM_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*$")
_ROMAN_RE = re.compile(r"^\s*([A-Za-z]+)\s+([IVXLCDM]+)\s*$", re.IGNORECASE)
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_ORIGINAL_SUFFIX_RE = re.compile(r"(?:_original)+$", re.IGNORECASE)


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


_SUGGEST_RE = re.compile(
    r"\b("
    r"suggest(?:ion|ions)?|recommend(?:ation|ations)?|"
    r"what (?:should|do|would|could|can) (?:i|we|you)|"
    r"what(?:'s| is) your (?:suggestion|recommendation|advice|opinion|take)|"
    r"what next|what now|any (?:idea|ideas|tip|tips|advice)|"
    r"help me|how (?:do|should|can) i|how to|"
    r"give me (?:a |an )?(?:suggestion|recommendation|advice|hint)|"
    r"should (?:i|we)|do you think|is it (?:a )?good idea"
    r")\b",
    re.IGNORECASE,
)


def parse_intent(message: str, columns: List[str]) -> Dict[str, Any]:
    """Map ``message`` to one of the supported intents. Always returns a
    dict with at least ``action`` and ``column`` keys (column may be None
    when the action is ``clarify`` or ``suggest``).

    Precedence: bare-greeting / question-mark short prompts → ``suggest``;
    then every concrete action intent (so question forms like "how do I
    rename age to age_yrs" still resolve to ``rename``); then a broader
    suggest fallback for open-ended requests; then ``clarify``."""
    msg = (message or "").strip()
    msg_low = msg.lower()
    column = _find_column(msg, columns)

    # Bare greeting / lone "?" / "help" — unambiguous suggest triggers.
    if msg_low in {"help", "?", "hi", "hello"}:
        return {"action": "suggest", "column": column, "params": {}}

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

    # treat_as_discrete / treat_as_continuous — Per spec Rule 5 these do
    # NOT change the variable type (it stays scale). They only flip the
    # info-only sub-type so summaries report integer counts vs floats.
    # Must run BEFORE the generic change_type branch so that "treat Age
    # as discrete" doesn't get captured as a full reclassification to
    # the legacy `discrete` (count) type.
    m = re.search(
        r"(?:treat|set|change|mark|make)\s+(.+?)\s+(?:as|to)\s+(discrete|continuous)\b",
        msg, re.IGNORECASE,
    )
    if m:
        target_col = next(
            (c for c in columns if c.lower() == m.group(1).strip().lower()),
            column,
        )
        which = m.group(2).lower()
        pseudo = "scale_discrete" if which == "discrete" else "scale_continuous"
        if target_col:
            return {
                "action": "change_type",
                "column": target_col,
                "params": {"new_type": pseudo},
            }

    # change_type — "treat X as scale" / "set X to nominal"
    m = re.search(
        r"(?:treat|set|change|mark|make)\s+(.+?)\s+(?:as|to)\s+(scale|ordinal|nominal|date|id|exclude)",
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

    # add_numeric_column — "I want both mean and frequency", "mean and
    # frequency for X", "add a numeric version", "give me a numeric column".
    # Per spec Rule 5 we accept the bare phrasing "mean and frequency for
    # [variable]" so users don't have to say "both".
    if re.search(
        r"\b(both|mean and frequency|frequency and mean|mean.*frequency|"
        r"numeric (?:column|version)|add a number|number column)\b",
        msg_low,
    ):
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

    # "{col} has text/letters/words" or "make {col} numeric/a number"
    # → strip_prefix so text-in-numeric columns get cleaned naturally
    if column and re.search(
        r"\b(has|contains|with|include)\s+(text|letters|words|characters|non.?numeric|prefix)\b"
        r"|\b(make|convert|turn)\b.{0,30}\b(numeric|a number|numbers?|continuous)\b",
        msg_low,
    ):
        return {"action": "strip_prefix", "column": column, "params": {}}

    # trim_whitespace — "trim whitespace from X", "fix spaces in X",
    # "clean X values", "standardize X" — must run BEFORE the broad
    # "fix/correct → suggest" fallback so "fix spaces in ER" resolves
    # to a concrete action rather than a generic AI explanation.
    if re.search(
        r"\b(trim|strip|clean|standardize|standardise)\b.{0,30}"
        r"\b(space|spaces|whitespace|trailing|leading|values?)\b"
        r"|\bclean\s+(up\s+)?(?:the\s+)?values?\b"
        r"|\bfix\s+(?:the\s+)?(?:space|spaces|whitespace|trailing|leading)\b",
        msg_low,
    ) and column:
        return {"action": "trim_whitespace", "column": column, "params": {}}

    # "fix {col}" / "correct {col}" / "what's wrong with {col}" /
    # "help with {col}" / "i can't proceed" / bare column name alone
    # → surface a targeted suggestion for that column (or globally)
    if re.search(
        r"\b(fix|correct|repair|help with|what.?s wrong|what is wrong"
        r"|i can.?t proceed|cannot proceed|can.?t continue|cannot continue"
        r"|something.{0,10}wrong|not working|blocked|stuck)\b",
        msg_low,
    ):
        return {"action": "suggest", "column": column, "params": {}}

    # Bare column name (or column name + "?") as the entire message
    if column and msg_low.strip().rstrip("?") == column.lower():
        return {"action": "suggest", "column": column, "params": {}}

    # "{col} should be scale/nominal/ordinal" — type correction in natural form
    m = re.search(
        r"(.+?)\s+(?:should|must|needs? to)\s+be\s+(scale|ordinal|nominal|date|id|exclude)",
        msg, re.IGNORECASE,
    )
    if m:
        target_col = next(
            (c for c in columns if c.lower() == m.group(1).strip().lower()), column
        )
        new_type = m.group(2).lower()
        if target_col and new_type in _VALID_TYPES:
            return {
                "action": "change_type",
                "column": target_col,
                "params": {"new_type": new_type},
            }

    # "change {col} to/as nominal" with reversed word order
    # (covers "change Grade to nominal" which the earlier regex may miss
    # when the column name contains extra words)
    m = re.search(
        r"(?:change|set|make|mark)\s+(.+?)\s+(?:to|as|into)\s+(scale|ordinal|nominal|date|id|exclude)",
        msg, re.IGNORECASE,
    )
    if m:
        raw = m.group(1).strip().strip("'\"")
        target_col = next(
            (c for c in columns if raw.lower() in c.lower() or c.lower() in raw.lower()),
            column,
        )
        new_type = m.group(2).lower()
        if target_col and new_type in _VALID_TYPES:
            return {
                "action": "change_type",
                "column": target_col,
                "params": {"new_type": new_type},
            }

    # Open-ended "what should I do?" / "should I add X" / "any
    # recommendation?" — checked LAST so phrasings like "how do I rename
    # X to Y" still resolve to the concrete action above instead of
    # being downgraded to a generic suggestion.
    if _SUGGEST_RE.search(msg):
        return {"action": "suggest", "column": column, "params": {}}

    return {"action": "clarify", "column": column, "params": {}}


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------


def _trim_whitespace(
    df: pd.DataFrame, column: str
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Strip leading/trailing whitespace (and collapse internal runs) from
    every string value in ``column``.  Leaves numeric dtypes untouched."""
    if column not in df.columns:
        raise ValueError(f"Unknown column '{column}'.")
    new_df = df.copy()
    original = new_df[column].copy()
    if new_df[column].dtype == object:
        def _clean(v: Any) -> Any:
            if pd.isna(v):
                return v
            s = str(v)
            return " ".join(s.split())  # strips + collapses internal spaces
        new_df[column] = new_df[column].map(_clean)
    changed = int((new_df[column].astype(str) != original.astype(str)).sum())
    sample = [str(v) for v in new_df[column].dropna().unique()[:3].tolist()]
    return new_df, {"changed_rows": changed, "sample_after": sample}


def trim_all_whitespace(
    df: pd.DataFrame, columns: Optional[List[str]] = None
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Trim leading/trailing whitespace (and collapse internal runs) from
    every string cell across all *columns* in a single DataFrame pass.

    Args:
        df:      Source DataFrame (not mutated).
        columns: Explicit list of columns to clean.  When ``None`` every
                 object-dtype column is targeted.

    Returns:
        ``(new_df, {"changed_cols": [...], "total_changed": int})``
    """
    target = columns if columns is not None else [
        col for col in df.columns if df[col].dtype == object
    ]
    new_df = df.copy()
    changed_cols: List[str] = []
    total_changed = 0

    def _clean(v: Any) -> Any:
        if pd.isna(v):
            return v
        return " ".join(str(v).split())

    for col in target:
        if col not in new_df.columns or new_df[col].dtype != object:
            continue
        original = new_df[col].copy()
        new_df[col] = new_df[col].map(_clean)
        n = int((new_df[col].astype(str) != original.astype(str)).sum())
        if n > 0:
            changed_cols.append(col)
            total_changed += n

    return new_df, {"changed_cols": changed_cols, "total_changed": total_changed}


def _strip_prefix(
    df: pd.DataFrame, column: str, prefix: Optional[str]
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Strip a leading alphabetic token from values in ``column`` and
    coerce the result to numeric. Keeps original in ``{column}_original``."""
    if column not in df.columns:
        raise ValueError(f"Unknown column '{column}'.")
    if _ORIGINAL_SUFFIX_RE.search(column):
        raise ValueError(
            f"'{column}' is already an original-value backup and cannot be cleaned again."
        )
    if variable_classifier.is_known_categorical_clinical_marker(column):
        raise ValueError(
            f"'{column}' is a categorical clinical marker; use Nominal or Ordinal "
            "classification instead of stripping text."
        )
    new_df = df.copy()
    series = new_df[column].astype(str)

    backup = _ORIGINAL_SUFFIX_RE.sub("", column) + "_original"
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

    if action == "trim_whitespace":
        new_df, meta = _trim_whitespace(df, column)
        n = meta["changed_rows"]
        sample = ", ".join(repr(s) for s in meta["sample_after"][:3])
        msg = (
            f"Trimmed whitespace from \"{column}\". "
            f"{n} value(s) standardised. Values now: {sample}."
            if n else
            f"\"{column}\" already had no extra whitespace — no changes made."
        )
        return new_df, {**meta, "confirmation_message": msg}

    if action == "suggest":
        # Informational only. The API layer rebuilds a context-aware message
        # via ``suggest_message`` because ``apply_action`` doesn't see the
        # classifications/issues snapshot. We return an empty placeholder
        # here so the dispatch table is complete.
        return None, {"confirmation_message": ""}

    # clarify — leave the message empty; the API layer fills it in with
    # ``generic_clarify`` so the example commands reference the user's
    # actual columns instead of canned dummy names like "VAS Score".
    return None, {"confirmation_message": ""}


# ---------------------------------------------------------------------------
# Suggestion / clarification text builders (dataset-aware)
# ---------------------------------------------------------------------------


def _pick_columns(classifications: List[Dict[str, Any]], *kinds: str) -> List[str]:
    out: List[str] = []
    for c in classifications or []:
        if not kinds or c.get("detected_type") in kinds:
            out.append(c.get("column"))
    return [c for c in out if c]


# Same recoding presets the frontend uses; mirrored here so the assistant
# can give concrete grouping advice (e.g. "group Age into 18–30 / 31–45 /
# 46–60 / >60") instead of telling the user to invent their own bands.
_BAND_PRESETS: List[Tuple[str, "re.Pattern[str]", str]] = [
    ("age", re.compile(r"^age$", re.IGNORECASE), "18–30 / 31–45 / 46–60 / >60"),
    ("bmi", re.compile(r"^bmi$", re.IGNORECASE),
        "Underweight (<18.5) / Normal (18.5–25) / Overweight (25–30) / Obese (≥30)"),
    ("hb",  re.compile(r"^(haemoglobin|hemoglobin|hb)$", re.IGNORECASE),
        "Severe (<7) / Moderate (7–10) / Mild (10–12) / Normal (≥12)"),
]


def suggest_message(
    columns: List[str],
    classifications: List[Dict[str, Any]],
    issues: List[Dict[str, Any]],
) -> str:
    """Build a concrete, dataset-aware recommendation. The user typed
    something like "what should I do?" or "any suggestions?" — they want a
    specific next action, not a list of generic example commands."""

    suggestions: List[str] = []

    issues_by_col: Dict[str, List[Dict[str, Any]]] = {}
    for i in issues or []:
        issues_by_col.setdefault(i.get("column"), []).append(i)

    # --- Priority 1: blocking text-in-numeric → strip prefix ----------------
    for c in classifications or []:
        col = c.get("column")
        col_issues = issues_by_col.get(col, [])
        if (
            any(i.get("type") == "text_in_numeric" for i in col_issues)
            and not variable_classifier.is_known_categorical_clinical_marker(col)
        ):
            suggestions.append(
                f"• “{col}” looks numeric but has text in front (e.g. “Grade 4”). "
                f"Send: “strip the prefix from {col}”. "
                f"That converts it to numbers and keeps the original text safely backed up."
            )
            break  # one strip-prefix tip is enough

    # --- Priority 2: well-known clinical bands → recoding suggestion --------
    scale_cols_lower = {
        c.get("column", "").lower(): c.get("column")
        for c in classifications or []
        if c.get("detected_type") == "scale"
    }
    for _key, pattern, band_label in _BAND_PRESETS:
        for low, original in scale_cols_lower.items():
            if pattern.match(low):
                suggestions.append(
                    f"• Group “{original}” into {band_label}. "
                    f"Look at the OPTIONAL RECODING panel on the right — "
                    f"tick the “Group {original} into …” checkbox, then click "
                    f"“Edit cutoffs” if you want to change the boundaries."
                )
                break

    # --- Priority 3: high-missing columns → exclude or review ---------------
    high_missing = [
        c for c in (classifications or [])
        if (c.get("missing_pct") or 0) > 30
    ]
    if high_missing:
        first = high_missing[0]
        names = ", ".join(f"“{c['column']}”" for c in high_missing[:3])
        plural = len(high_missing) > 1
        suggestions.append(
            f"• {names} {'have' if plural else 'has'} more than 30% missing data. "
            f"Consider excluding {'them' if plural else 'it'}: "
            f"send “exclude {first['column']} from analysis”."
        )

    # --- Generic fallback that still references real columns ---------------
    if not suggestions:
        usable = _pick_columns(classifications, "scale", "ordinal", "nominal", "discrete")
        if usable:
            sample = usable[0]
            suggestions.append(
                f"• Your dataset looks clean. You can still rename, retype or "
                f"exclude columns — try “treat {sample} as nominal” or "
                f"“rename {sample} to something_clearer”."
            )
        else:
            return generic_clarify(columns)

    intro = (
        "Here’s what I’d suggest based on your data — pick whichever applies:\n\n"
    )
    return intro + "\n\n".join(suggestions)


def generic_clarify(columns: List[str]) -> str:
    """Fallback shown when the user's message couldn't be parsed at all.
    Uses real column names from the dataset so the example commands are
    actually runnable, instead of the old canned ``VAS Score`` / ``Hb`` /
    ``Notes`` placeholders that confused users on first contact."""
    cols = [c for c in (columns or []) if c]
    pick = lambda i: cols[i] if i < len(cols) else None
    a = pick(0) or "Age"
    b = pick(1) or a
    c = pick(2) or a
    return (
        "I’m not sure what to do with that yet. You can ask me to:\n"
        f"• “Strip the prefix from {a}” — clean up text like “Grade 4” → 4\n"
        f"• “I want both mean and frequency for {a}” — adds a numeric companion column\n"
        f"• “Treat {b} as discrete” — change a column’s type\n"
        f"• “Rename {c} to something_clearer”\n"
        f"• “Exclude {a} from analysis”\n\n"
        "Or just ask “what should I do?” for a tailored suggestion."
    )
