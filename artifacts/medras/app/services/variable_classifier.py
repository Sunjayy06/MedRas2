"""Auto-classify dataset columns into MedRAS variable types.

MedRAS variable types (matching SPSS conventions used by clinical researchers):

* ``id``       — Identifier column (Patient_ID, MRN). Excluded from analysis.
* ``date``     — Date / datetime column. Used for survival or time-series only.
* ``scale``    — Continuous numeric (age, Hb, BP). Mean / SD / t-test eligible.
* ``ordinal``  — Ordered categories with small cardinality (Pain score 1-10,
  Likert 1-5, severity grade 1-3). Median / IQR / non-parametric tests.
* ``nominal``  — Unordered categories (sex, treatment arm, blood group).
  Frequency / chi-square tests.
* ``discrete`` — Integer count variable (number of hospital visits, parity,
  number of children). Treated like scale for descriptives, but reported as
  median/IQR rather than mean/SD when skewed.
* ``exclude``  — Free text or columns the user has explicitly removed.

Classification rules — applied in order, first match wins:

1. Empty / single-value column → ``exclude``.
2. Column name matches an ID pattern AND uniqueness ≥ 0.9 → ``id``.
3. Pandas datetime dtype OR column name matches a date pattern → ``date``.
4. Numeric dtype:
     * unique ≤ 10 AND values look ordinal-coded → ``ordinal``
     * else → ``scale``
5. Object / string dtype:
     * unique ≤ 20 → ``nominal``
     * else → ``exclude`` (likely free-text)

The classifier returns a list of dicts, one per column, that can be sent
directly to the front-end for the Step 2 review table.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

import numpy as np
import pandas as pd


VarType = str  # one of: id, date, scale, ordinal, nominal, exclude

_ID_NAME_RE = re.compile(
    r"(?:^|[\W_])(id|uid|uuid|patient[_ ]?id|subject[_ ]?id|study[_ ]?id|"
    r"mrn|enrol|enroll|sno|s\.?no|pt[_ ]?id|record[_ ]?id)(?:$|[\W_])",
    re.IGNORECASE,
)


def column_name_looks_like_id(name: str) -> bool:
    """True when the column name strongly suggests it is an identifier,
    regardless of uniqueness. Used to surface follow-up prompts on
    longitudinal data where the ID column has many repeats by design."""
    return bool(_ID_NAME_RE.search(str(name or "")))
_DATE_NAME_RE = re.compile(r"\b(date|dob|admission|discharge|visit|timestamp|onset)\b", re.IGNORECASE)
_SCORE_NAME_RE = re.compile(
    r"\b(score|index|scale|grade|stage|severity|vas|nrs|gcs|mmse|likert)\b",
    re.IGNORECASE,
)
# Note: Python regex treats "_" as a word character so \b will NOT match
# between "_" and a letter. We use (?:^|[\W_]) / (?:$|[\W_]) so snake_case
# columns like "Hospital_visits" are recognised.
_COUNT_NAME_RE = re.compile(
    r"(?:^|[\W_])(count|number|num|no_of|times|visits|episodes|admissions|"
    r"children|parity|gravida|siblings|cigarettes|drinks|days|hospitalisations|"
    r"hospitalizations)(?:$|[\W_])",
    re.IGNORECASE,
)


def _safe_unique_count(series: pd.Series) -> int:
    try:
        return int(series.dropna().nunique())
    except Exception:
        return 0


def _looks_like_date(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if series.dtype == object:
        sample = series.dropna().astype(str).head(20).tolist()
        if not sample:
            return False
        # Try parsing — if >70% parse, treat as date.
        parsed = pd.to_datetime(pd.Series(sample), errors="coerce", format="mixed")
        return parsed.notna().mean() >= 0.7
    return False


def classify_column(series: pd.Series, name: str) -> Dict[str, Any]:
    """Return a classification record for one column."""
    n_total = len(series)
    n_missing = int(series.isna().sum())
    n_present = n_total - n_missing
    unique_count = _safe_unique_count(series)
    sample_values = (
        series.dropna().astype(str).head(5).tolist() if n_present else []
    )

    # 1) Empty / degenerate.
    if n_present == 0 or unique_count <= 1:
        detected: VarType = "exclude"
        reason = "Column is empty or has only one unique value."
        return _record(
            name, detected, reason, unique_count, sample_values, n_missing, n_total
        )

    uniqueness = unique_count / n_present

    # 2) ID column.
    if _ID_NAME_RE.search(name) and uniqueness >= 0.9:
        return _record(
            name, "id", "Looks like a unique identifier (excluded from stats).",
            unique_count, sample_values, n_missing, n_total,
        )

    # 3) Date column.
    if _looks_like_date(series) or _DATE_NAME_RE.search(name):
        return _record(
            name, "date", "Detected as date / time column.",
            unique_count, sample_values, n_missing, n_total,
        )

    # 4) Numeric.
    if pd.api.types.is_numeric_dtype(series):
        # Score / index / Likert columns are ordinal even if numeric.
        if _SCORE_NAME_RE.search(name) and unique_count <= 11:
            return _record(
                name, "ordinal",
                "Score-like column with limited values — treated as ordinal.",
                unique_count, sample_values, n_missing, n_total,
            )
        # Detect integer values (no fractional part).
        try:
            vals = series.dropna()
            all_int = bool(np.all(np.equal(np.mod(vals, 1), 0)))
            min_v = float(vals.min()) if len(vals) else 0.0
        except Exception:
            all_int = False
            min_v = 0.0
        # Discrete count by name wins over the ordinal heuristic — a column
        # called "Hospital_visits" is a count even if it happens to have only
        # 10 distinct values.
        if all_int and min_v >= 0 and _COUNT_NAME_RE.search(name) and unique_count <= 30:
            return _record(
                name, "discrete",
                "Integer count variable — treated as discrete.",
                unique_count, sample_values, n_missing, n_total,
            )
        # Few unique integer values → ordinal coded category (e.g. 0/1/2).
        if unique_count <= 10 and all_int:
            # 0/1 → nominal binary (sex coded as 1/2 etc.). 0/1/2/3 → ordinal.
            if unique_count <= 2:
                return _record(
                    name, "nominal",
                    "Binary numeric coding — treated as nominal.",
                    unique_count, sample_values, n_missing, n_total,
                )
            return _record(
                name, "ordinal",
                "Few integer values — treated as ordinal.",
                unique_count, sample_values, n_missing, n_total,
            )
        # Discrete count by shape: small integer cardinality, non-negative.
        if all_int and min_v >= 0 and unique_count <= 15:
            return _record(
                name, "discrete",
                "Integer count variable — treated as discrete.",
                unique_count, sample_values, n_missing, n_total,
            )
        return _record(
            name, "scale",
            "Continuous numeric — treated as scale.",
            unique_count, sample_values, n_missing, n_total,
        )

    # 5) String / object.
    if unique_count <= 20:
        return _record(
            name, "nominal",
            f"Categorical text ({unique_count} unique values).",
            unique_count, sample_values, n_missing, n_total,
        )

    return _record(
        name, "exclude",
        f"Looks like free text ({unique_count} unique values) — excluded.",
        unique_count, sample_values, n_missing, n_total,
    )


def _record(
    name: str,
    detected: VarType,
    reason: str,
    unique_count: int,
    sample_values: List[Any],
    n_missing: int,
    n_total: int,
) -> Dict[str, Any]:
    return {
        "column": name,
        "detected_type": detected,
        "reason": reason,
        "unique_count": unique_count,
        "sample_values": sample_values,
        "missing": n_missing,
        "missing_pct": round(100.0 * n_missing / n_total, 1) if n_total else 0.0,
    }


def classify_dataframe(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Classify every column in ``df``."""
    return [classify_column(df[col], col) for col in df.columns]


def encode_for_analysis(df: pd.DataFrame, classifications: List[Dict[str, Any]]) -> pd.DataFrame:
    """Apply user-confirmed classifications to a copy of the DataFrame.

    For now this only coerces numeric / datetime types where the classifier
    insists. We deliberately do NOT label-encode nominal columns: tests like
    chi-square work directly on string labels, and keeping labels makes the
    output tables human-readable.
    """
    out = df.copy()
    for c in classifications:
        col = c["column"]
        kind = c.get("detected_type")
        if col not in out.columns:
            continue
        try:
            if kind in ("scale", "ordinal", "discrete"):
                out[col] = pd.to_numeric(out[col], errors="coerce")
            elif kind == "date":
                out[col] = pd.to_datetime(out[col], errors="coerce", format="mixed")
        except Exception:
            # If coercion fails, leave the column as-is and let the test layer
            # deal with it (or skip the variable).
            continue
    return out
