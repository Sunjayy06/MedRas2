"""Auto-classify dataset columns into MedRAS variable types.

Each classification record carries two layers:

1. The **legacy verdict** (``detected_type``, ``reason``) used everywhere
   downstream — Step 3 dropdowns, Step 4 quality checks, the analysis
   engine, and recoding presets.

2. The **MedRAS Variable Intelligence Layer** — a four-axis description
   of the variable that mirrors how a real biostatistician thinks about
   raw data before touching a single test. The four axes are:

     * ``storage_type`` — how the value physically lives in the dataset
       (``numeric`` / ``text`` / ``date`` / ``boolean``).
     * ``statistical_nature`` — its measurement-theory class
       (``continuous`` / ``discrete`` / ``ordinal`` / ``nominal`` /
       ``binary`` / ``datetime`` / ``identifier`` / ``free_text`` /
       ``empty``).
     * ``interpretation`` — what the variable IS clinically
       (``measurement`` / ``count`` / ``validated_score`` / ``grading`` /
       ``binary_indicator`` / ``category`` / ``identifier`` / ``date`` /
       ``free_text`` / ``empty``).
     * ``analytical_flexibility`` — the test families it can legitimately
       feed (e.g. ``["continuous", "ordinal", "categorical"]`` for a
       clinical score).

   A short ``reasoning`` string puts the verdict into plain language so
   the UI can show users *why* the classifier decided what it decided.

Legacy ``detected_type`` values (matching SPSS conventions used by
clinical researchers):

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
# Continuous clinical / demographic measurements. These are conceptually scale
# variables even when a small dataset happens to contain only a handful of
# distinct integer values (e.g. an Age column with 7 unique values like
# 18,22,30,45,52,60,67). Without this list the cardinality-based heuristic
# below would incorrectly call them "ordinal".
_CONTINUOUS_NAME_RE = re.compile(
    r"(?:^|[\W_])("
    r"age|years?|yrs|"
    r"weight|wt|kg|"
    r"height|ht|cm|stature|"
    r"bmi|"
    r"sbp|dbp|systolic|diastolic|map|pulse|heart[_ ]?rate|hr|"
    r"temp|temperature|"
    r"haemoglobin|hemoglobin|hb|hgb|"
    r"glucose|fbs|rbs|hba1c|"
    r"cholesterol|ldl|hdl|tg|triglycerides?|"
    r"creatinine|urea|bun|egfr|gfr|"
    r"sodium|potassium|na|k|"
    r"albumin|protein|bilirubin|"
    r"wbc|rbc|platelets?|hct|haematocrit|hematocrit|"
    r"duration|"
    r"income|salary|cost|price|amount"
    r")(?:$|[\W_])",
    re.IGNORECASE,
)

# Validated clinical scores / instruments. When a column name matches one
# of these the classifier marks the variable's interpretation as
# ``validated_score`` and applies the spec rule:
#   "Score-based variable with ordinal foundation and potential
#   continuous-style analysis depending on range, distribution, and
#   research objective."
# Generic terms ``score|index|scale`` are intentionally included — if the
# researcher named the column "score", treat it as a score for
# interpretation purposes (analytical flexibility still depends on the
# storage shape).
_VALIDATED_SCORE_NAME_RE = re.compile(
    r"(?:^|[\W_])("
    r"score|index|scale|"
    r"harris|hhs|hip[_ ]?score|"
    r"sf[_ -]?(?:36|12|8)|"
    r"qol|quality[_ ]?of[_ ]?life|"
    r"womac|oxford|kss|"
    r"barthel|adl|iadl|"
    r"hads|phq|gad|moca|mmse|"
    r"edss|asia|tlics|frankel|ais|"
    r"vas|nrs|likert|"
    r"odi|ndi|"
    r"radiological[_ ]?union|rus|rasanen|"
    r"charlson|apache|sofa|gcs|"
    r"disability|function|outcome"
    r")(?:$|[\W_])",
    re.IGNORECASE,
)

# Grading / stage / severity / class — ordered categories that are *not*
# validated scores (no continuous-style analysis offered, only ordinal /
# categorical).
_GRADING_NAME_RE = re.compile(
    r"(?:^|[\W_])(grade|stage|severity|class|tier)(?:$|[\W_])",
    re.IGNORECASE,
)
# A standalone literal "grade" token. Used to distinguish unambiguous
# grading columns ("Pain_score_grade", "Tumor_grade") from broader
# grading keywords (severity/stage/class/tier) that often co-occur with
# score/instrument names ("Severity_score") and should defer to the
# score interpretation in those mixed cases.
_LITERAL_GRADE_RE = re.compile(
    r"(?:^|[\W_])grade(?:$|[\W_])",
    re.IGNORECASE,
)

# Sex / gender / yes-no style binary names — used to mark the
# interpretation as ``binary_indicator`` even when ``unique_count`` could
# theoretically allow a different reading.
_BINARY_NAME_RE = re.compile(
    r"(?:^|[\W_])(sex|gender|alive|dead|deceased|smoker|diabetic|hypertensive|pregnant)(?:$|[\W_])",
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
    """Return a classification record for one column.

    The record contains both the legacy ``detected_type`` field and the
    four-axis Variable Intelligence Layer (storage_type,
    statistical_nature, interpretation, analytical_flexibility,
    reasoning). The latter is added by ``_enrich`` so every entry point
    (``classify_column``, ``classify_dataframe``) gets the richer view.
    """
    record = _classify_core(series, name)
    return _enrich(record, series, name)


def _classify_core(series: pd.Series, name: str) -> Dict[str, Any]:
    """Legacy classifier — produces ``detected_type`` + ``reason``."""
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
        # Continuous clinical/demographic measurement by name (Age, BMI, Hb,
        # SBP, Glucose, ...). These are conceptually scale even when the
        # dataset happens to have few distinct integer values, so this rule
        # has to beat the cardinality-based ordinal heuristic below.
        if _CONTINUOUS_NAME_RE.search(name):
            return _record(
                name, "scale",
                "Continuous clinical/demographic measurement — treated as scale.",
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


# ---------------------------------------------------------------------------
# Variable Intelligence Layer — adds the four theory-aware axes onto the
# legacy classification record. Centralised here so the verdict and the
# reasoning can never drift apart.
# ---------------------------------------------------------------------------

def _enrich(record: Dict[str, Any], series: pd.Series, name: str) -> Dict[str, Any]:
    """Add ``storage_type``, ``statistical_nature``, ``interpretation``,
    ``analytical_flexibility`` and a plain-English ``reasoning`` string
    to a classification record produced by ``_classify_core``."""
    detected = record.get("detected_type", "exclude")
    unique = int(record.get("unique_count") or 0)

    # --- Storage type: how the value physically lives in the dataset.
    if pd.api.types.is_datetime64_any_dtype(series):
        storage = "date"
    elif pd.api.types.is_bool_dtype(series):
        storage = "boolean"
    elif pd.api.types.is_numeric_dtype(series):
        storage = "numeric"
    elif _looks_like_date(series):
        storage = "date"
    else:
        storage = "text"

    # Integer-ness signal: used for the "count vs continuous" reasoning.
    all_int = False
    if storage == "numeric":
        try:
            vals = series.dropna()
            if len(vals):
                all_int = bool(np.all(np.equal(np.mod(vals, 1), 0)))
        except Exception:
            all_int = False

    # --- Theoretical interpretation: what the variable IS clinically.
    interp = _interpret(name, detected, storage, unique, all_int)

    # --- Statistical nature: measurement-theory class.
    nature = _statistical_nature(detected, storage, unique, interp)

    # --- Analytical flexibility: which test families it can feed.
    flex = _analytical_flexibility(interp, nature, unique)

    # --- Reasoning: short prose, written in statistician voice.
    reasoning = _reasoning_text(interp, nature, unique, all_int, record.get("reason", ""))

    record["storage_type"] = storage
    record["statistical_nature"] = nature
    record["interpretation"] = interp
    record["analytical_flexibility"] = flex
    record["reasoning"] = reasoning
    return record


def _interpret(name: str, detected: VarType, storage: str, unique: int, all_int: bool) -> str:
    """Return one of: measurement, count, validated_score, grading,
    binary_indicator, category, identifier, date, free_text, empty."""
    if detected == "id":
        return "identifier"
    if detected == "date" or storage == "date":
        return "date"
    if detected == "exclude":
        # Distinguish empty/single-value from free-text rejection.
        if storage == "text" and unique > 20:
            return "free_text"
        return "empty"
    # Mixed grading + score names need careful precedence. Rules:
    #   1. A literal "grade" token (suffix or standalone) is the most
    #      specific clinical signal — it always wins, even over "score"
    #      (e.g. "Pain_score_grade", "Tumor_grade", "Severity_grade").
    #   2. Other grading keywords (stage / severity / class / tier) are
    #      generic descriptors — they defer to a score/instrument token
    #      when both are present (e.g. "Severity_score" stays a
    #      validated score, "Severity_class" becomes grading).
    has_grade_word = bool(_LITERAL_GRADE_RE.search(name))
    has_score_token = bool(_VALIDATED_SCORE_NAME_RE.search(name))
    has_other_grading = bool(_GRADING_NAME_RE.search(name)) and not has_grade_word
    if detected == "ordinal":
        if has_grade_word:
            return "grading"
        if has_score_token:
            return "validated_score"
        if has_other_grading:
            return "grading"
    elif detected in ("scale", "discrete") and has_score_token:
        return "validated_score"
    # Sex / yes-no / alive-dead → binary indicator regardless of detected.
    if _BINARY_NAME_RE.search(name) and unique <= 2 and detected in ("nominal",):
        return "binary_indicator"
    if detected == "discrete":
        return "count"
    if detected == "scale":
        # Named count column that the core classifier let through as scale
        # (e.g. cardinality > 30) is still conceptually a count.
        if _COUNT_NAME_RE.search(name) and all_int:
            return "count"
        return "measurement"
    if detected == "ordinal":
        # Numeric-coded ordinal that isn't a known instrument is a grading.
        return "grading"
    if detected == "nominal":
        if unique <= 2:
            return "binary_indicator"
        return "category"
    return "category"


def _statistical_nature(detected: VarType, storage: str, unique: int, interp: str) -> str:
    """Return the measurement-theory class. Stays in lock-step with the
    interpretation axis — an ``interpretation == "empty"`` column always
    has ``statistical_nature == "empty"`` even if its raw dtype is text."""
    if interp == "empty":
        return "empty"
    if interp == "free_text":
        return "free_text"
    if detected == "id":
        return "identifier"
    if detected == "date" or storage == "date":
        return "datetime"
    if detected == "exclude":
        return "free_text" if storage == "text" else "empty"
    if detected == "scale":
        return "continuous"
    if detected == "discrete":
        return "discrete"
    if detected == "ordinal":
        return "ordinal"
    if detected == "nominal":
        return "binary" if unique <= 2 else "nominal"
    return "nominal"


def _analytical_flexibility(interp: str, nature: str, unique: int) -> List[str]:
    """Return the test families the variable can legitimately feed."""
    if interp == "validated_score":
        # Spec rule: scores admit continuous-style, ordinal-style, OR
        # clinically-banded categorical analysis depending on range,
        # distribution and research objective.
        return ["continuous", "ordinal", "categorical"]
    if interp == "grading":
        return ["ordinal", "categorical"]
    if interp == "measurement":
        return ["continuous", "categorical_after_binning"]
    if interp == "count":
        # Counts can be analysed as continuous when sufficiently spread,
        # ordinal when low-cardinality, or grouped categorically.
        return ["continuous", "ordinal", "categorical"]
    if interp == "binary_indicator":
        return ["binary", "categorical"]
    if interp == "category":
        return ["categorical"]
    if interp == "date":
        return ["time_index"]
    if interp == "identifier":
        return ["exclude"]
    return ["exclude"]


def _reasoning_text(
    interp: str, nature: str, unique: int, all_int: bool, fallback: str
) -> str:
    """Plain-English reasoning a researcher can act on."""
    if interp == "validated_score":
        return (
            "Score-based variable with ordinal foundation and potential "
            "continuous-style analysis depending on range, distribution, "
            "and research objective."
        )
    if interp == "grading":
        return (
            f"Ordered grading / stage variable ({unique} levels). Best "
            "summarised by counts and percentages and tested with rank-based "
            "or chi-square methods."
        )
    if interp == "measurement":
        return (
            "Direct clinical or demographic measurement — analyse as a "
            "continuous variable, with optional clinical banding for "
            "descriptive grouping."
        )
    if interp == "count":
        shape = "approximately symmetric" if all_int else "non-integer"
        return (
            f"Integer count variable ({unique} distinct values). Reported as "
            f"median (IQR) when skewed, mean (SD) when {shape} and roughly "
            "symmetric; can also be grouped into clinically meaningful bands."
        )
    if interp == "binary_indicator":
        return (
            "Two-level indicator — analyse as a binary categorical variable "
            "(chi-square / Fisher's exact, proportion comparisons, odds "
            "ratios)."
        )
    if interp == "category":
        return (
            f"Unordered categorical variable with {unique} levels — analyse "
            "with frequency counts and chi-square / Fisher's exact tests."
        )
    if interp == "identifier":
        return "Per-record identifier — excluded from statistical analysis."
    if interp == "date":
        return (
            "Date / time field — used as a time index for survival or "
            "longitudinal analyses, not as a primary outcome on its own."
        )
    if interp == "free_text":
        return (
            f"Free-text field ({unique} unique values) — excluded from "
            "quantitative analysis; recode into categories first if needed."
        )
    if interp == "empty":
        return "Empty or constant column — excluded from analysis."
    return fallback or ""


def reenrich_after_override(record: Dict[str, Any], series: pd.Series, name: str) -> Dict[str, Any]:
    """Public wrapper around ``_enrich`` for callers that mutate the
    legacy ``detected_type`` field after classification (manual dropdown
    override or variable-assistant action). Without this, the four
    theory-aware axes (``storage_type`` / ``statistical_nature`` /
    ``interpretation`` / ``analytical_flexibility`` / ``reasoning``)
    would drift out of sync with the new verdict and the UI would show
    contradictory information."""
    return _enrich(record, series, name)


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
