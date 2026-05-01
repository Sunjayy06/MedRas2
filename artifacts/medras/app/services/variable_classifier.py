"""Auto-classify dataset columns into MedRAS variable types.

Behaves like an expert biostatistician handling raw clinical data:

  - **Numeric values default to scale** (continuous measurements, raw
    scores, lab values, counts, durations, dimensions) so analytical
    precision is preserved before any grouping.
  - **Ordinal is assigned only when the data SHAPE supports it** — a
    small, contiguous integer set starting at 0/1/2 with ≤7 levels and
    range ≤10 (Likert 1-5, severity grade 1-3, etc.).
  - **Variable names never promote a column to ordinal.** They may
    *demote* an ordinal-shaped numeric back to scale (named counts,
    named continuous measurements) — that direction preserves precision
    in line with the spec.
  - **Numeric-like text is auto-cleaned.** Cells like ``"2mm"``,
    ``"12 kg"``, ``"Grade 3"``, ``"7.5%"``, ``"Score 85"`` are detected
    via :func:`clean_numeric_like_columns` and converted to numeric so
    the column lands in the scale bucket.

Each classification record carries two layers:

1. The **legacy verdict** (``detected_type``, ``reason``) used
   everywhere downstream — Step 3 dropdowns, Step 4 quality checks,
   the analysis engine, and recoding presets.

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
       (``measurement`` / ``count`` / ``grading`` / ``binary_indicator``
       / ``category`` / ``identifier`` / ``date`` / ``free_text`` /
       ``empty``).
     * ``analytical_flexibility`` — the test families it can legitimately
       feed (e.g. ``["continuous", "categorical_after_binning"]`` for a
       raw measurement, ``["ordinal", "categorical"]`` for a grading
       code).

   A short ``reasoning`` string puts the verdict into plain language so
   the UI can show users *why* the classifier decided what it decided.
   When :func:`clean_numeric_like_columns` modified a column, an
   additional ``cleanup_note`` field describes what was extracted.

Legacy ``detected_type`` values (matching SPSS conventions used by
clinical researchers):

* ``id``       — Identifier column (Patient_ID, MRN). Excluded from analysis.
* ``date``     — Date / datetime column. Used for survival or time-series only.
* ``scale``    — Continuous numeric (age, Hb, BP, raw scores, counts,
  durations, dimensions). Mean / SD / t-test eligible. The spec's
  default bucket for any numeric data with meaningful arithmetic.
* ``ordinal``  — Ordered categorical codes with very small cardinality
  (Likert 1-5, severity grade 1-3). Assigned only when the data shape
  shows a contiguous small integer set — never from a name pattern.
* ``nominal``  — Unordered categories (sex, treatment arm, blood group).
  Frequency / chi-square tests.
* ``discrete`` — Legacy. Never auto-assigned — counts go to ``scale``
  per spec. Kept as a valid value so user overrides still round-trip.
* ``exclude``  — Free text or columns the user has explicitly removed.
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
# Note: Python regex treats "_" as a word character so \b will NOT match
# between "_" and a letter. We use (?:^|[\W_]) / (?:$|[\W_]) so snake_case
# columns like "Hospital_visits" are recognised.
#
# Per the MedRAS biostatistician spec: variable names NEVER promote a
# column to ordinal. They may only DEMOTE an ordinal-shaped numeric back
# to scale (a named count column with values 0..5 stays scale to
# preserve analytical precision). The next two regexes are therefore
# used only as scale-preserving overrides on top of the data-shape
# ordinal heuristic — they are never used to assign ordinal/discrete
# directly.
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

# Per-spec Rule 1: clinical scoring systems / quantitative measurements
# named with these words are SCALE by definition, regardless of how few
# unique values the dataset happens to contain. This rule fires BEFORE
# the small-integer-set ordinal heuristic so a Harris Hip Score with
# 6 observed values in a tiny pilot dataset does not collapse to ordinal.
#
# Pattern matches whole-word substrings (case-insensitive) anywhere in
# the column name. We deliberately include short tokens like "vas", "nrs"
# and "hhs" because biomedical column names abbreviate aggressively.
_SCORE_NAME_RE = re.compile(
    r"(?:^|[\W_])("
    r"score|index|scale|"
    r"vas|nrs|nps|"
    r"hhs|harris|"
    r"union|"
    r"time|times|duration|"
    r"days?|weeks?|months?|minutes?|hours?|seconds?|"
    r"length|distance|volume|dose|dosage|"
    r"rate|level|count|counts|"
    r"pressure|"
    r"oswestry|odi|womac|kss|sf[_ ]?36|sf[_ ]?12|"
    r"gcs|apache|sofa|charlson|"
    r"asa|"
    r"hba1c|"
    r"recovery"
    r")(?:$|[\W_])",
    re.IGNORECASE,
)

# Sex / gender / yes-no style binary names — used to mark the
# interpretation as ``binary_indicator`` even when ``unique_count`` could
# theoretically allow a different reading.
_BINARY_NAME_RE = re.compile(
    r"(?:^|[\W_])(sex|gender|alive|dead|deceased|smoker|diabetic|hypertensive|pregnant)(?:$|[\W_])",
    re.IGNORECASE,
)

# Numeric-like text extraction. Matches a single numeric component
# embedded in a cell, optionally surrounded by category labels and/or
# unit suffixes. Examples that match: ``"2mm"``, ``"12 kg"``,
# ``"7.5cm"``, ``"Grade 3"``, ``"Score 85"``, ``"42"``, ``"-3.5"``,
# ``"100%"``, ``"45 °C"``. Examples that do NOT match (intentionally):
# ``"1 to 5"`` (two numbers), ``"Stable"`` (no number), ``"<18"`` /
# ``"≥40"`` (relational operators — these are recoding inputs, not
# data values), ``"1.2.3"`` (multiple decimals).
_NUMERIC_EMBED_RE = re.compile(
    r"^\s*[A-Za-z\s]*([+-]?\d+(?:\.\d+)?|\.\d+)\s*[A-Za-z%/°²³µ]*\s*$"
)
_NUMERIC_LABEL_RE = re.compile(
    r"^\s*([A-Za-z]+(?:\s[A-Za-z]+)*)\s+[+-]?\d+(?:\.\d+)?"
)
_NUMERIC_UNIT_RE = re.compile(
    r"^\s*[A-Za-z\s]*[+-]?\d+(?:\.\d+)?\s*([A-Za-z%/°²³µ]+)\s*$"
)


def _extract_numeric(value: Any) -> float | None:
    """Try to extract a single numeric value from a text cell.

    Accepts numbers with leading category labels (``"Grade 3"``,
    ``"Score 85"``) or trailing unit suffixes (``"2mm"``, ``"12 kg"``,
    ``"7.5%"``). Returns the parsed float or ``None`` when no clean
    single numeric component exists.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if pd.isna(value):
            return None
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    m = _NUMERIC_EMBED_RE.match(text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except (ValueError, TypeError):
        return None


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
    """Legacy classifier — produces ``detected_type`` + ``reason``.

    Per the MedRAS biostatistician spec:

      - Numeric values default to **scale** (raw scores, lab values,
        counts, measurements, durations, dimensions). This preserves
        analytical precision before any user-driven grouping.
      - **Ordinal** is assigned only when the *data shape* shows a
        small set of contiguous integer codes — Likert 1-5, severity
        grade 1-3 etc. Names never trigger ordinal.
      - Names *can* keep an ordinal-shaped numeric in the scale bucket
        (a count column with values 0..5, or an Age column with very
        few unique values) — that direction preserves precision.
    """
    n_total = len(series)
    n_missing = int(series.isna().sum())
    n_present = n_total - n_missing
    unique_count = _safe_unique_count(series)
    sample_values = (
        series.dropna().astype(str).head(5).tolist() if n_present else []
    )

    # 1) Empty / degenerate.
    if n_present == 0 or unique_count <= 1:
        return _record(
            name, "exclude", "Column is empty or has only one unique value.",
            unique_count, sample_values, n_missing, n_total,
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

    # 4) Numeric — default to scale. Inspect actual values to decide.
    if pd.api.types.is_numeric_dtype(series):
        try:
            vals = series.dropna()
            all_int = bool(np.all(np.equal(np.mod(vals, 1), 0))) if len(vals) else False
            min_v = float(vals.min()) if len(vals) else 0.0
            max_v = float(vals.max()) if len(vals) else 0.0
        except Exception:
            all_int = False
            min_v = 0.0
            max_v = 0.0

        # 4a) Continuous clinical/demographic measurement by name keeps
        # scale even when cardinality is small (e.g. an Age column with
        # only 2 observed integer values in a tiny sample). Per spec:
        # names can demote ordinal/binary-collapse to scale, never the
        # other way. This rule has to run BEFORE the binary-nominal
        # fallback so a 2-row Age sample doesn't collapse to nominal.
        if _CONTINUOUS_NAME_RE.search(name):
            return _record(
                name, "scale",
                "Continuous clinical / demographic measurement — treated as scale.",
                unique_count, sample_values, n_missing, n_total,
            )

        # 4a-bis) Per spec Rule 1: clinical scoring systems and other
        # quantitative names (Harris Hip Score, VAS, NRS, time-to-union,
        # operating time, length, dose, etc.) are SCALE regardless of
        # how few unique values are observed. Without this an HHS column
        # showing 6 distinct integer scores in a small dataset would be
        # collapsed to ordinal by the small-integer-set heuristic below.
        if _SCORE_NAME_RE.search(name):
            return _record(
                name, "scale",
                "Quantitative score / measurement (by name) — treated as scale.",
                unique_count, sample_values, n_missing, n_total,
            )

        # 4b) Named count column (Hospital_visits, parity, days_admitted).
        # Per spec these are SCALE — counts remain scale unless intentionally
        # grouped. The "count" semantics are preserved on the interpretation
        # axis; the legacy detected_type stays scale to preserve precision.
        # Same rule-order rationale: must protect against 4c collapsing a
        # small-sample count column to nominal binary.
        if all_int and _COUNT_NAME_RE.search(name):
            return _record(
                name, "scale",
                "Integer count variable — treated as scale (preserves precision; "
                "interpreted as count for descriptive reasoning).",
                unique_count, sample_values, n_missing, n_total,
            )

        # 4c) Two-level numeric (0/1, 1/2) → nominal binary coding.
        # Runs after the continuous/count-name protection so genuine
        # measurements with only 2 observed values are not miscoded.
        if all_int and unique_count <= 2:
            return _record(
                name, "nominal",
                "Binary numeric coding — treated as nominal.",
                unique_count, sample_values, n_missing, n_total,
            )

        # 4d) Genuine ordinal coding — ONLY by data shape: a small,
        # contiguous integer set starting at 0 or 1 with ≤7 levels and a
        # range ≤6. This catches Likert 1-5, satisfaction 0-4, severity
        # grade 1-3, ASIA A-E coded 1-5 reliably while letting raw
        # measurements (e.g. a tumor size of 2-8 mm) stay scale.
        # Restricting min to {0, 1} is deliberate: the spec biases toward
        # scale to preserve precision, and real ordinal codes
        # overwhelmingly start at 0 or 1. The rare "Stage 2-4" coding can
        # still be set ordinal via user override.
        if (
            all_int
            and unique_count <= 7
            and (max_v - min_v + 1) == unique_count
            and (max_v - min_v) <= 6
            and min_v in (0.0, 1.0)
        ):
            return _record(
                name, "ordinal",
                f"Small ordered integer set ({int(min_v)}-{int(max_v)}, "
                f"{unique_count} levels) — treated as ordinal.",
                unique_count, sample_values, n_missing, n_total,
            )

        # 4e) Default: scale. Includes raw scores, lab values, durations,
        # dimensions, counts, and any other numeric data with meaningful
        # arithmetic.
        return _record(
            name, "scale",
            "Numeric variable — treated as scale (default; preserve "
            "measurement precision).",
            unique_count, sample_values, n_missing, n_total,
        )

    # 5) String / object — non-numeric text. (Numeric-like text such as
    # "2mm" / "Grade 3" should already have been converted to numeric by
    # ``clean_numeric_like_columns`` before classification.)
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

    # Per spec Rule 3: surface "continuous" vs "discrete" as an
    # info-only sub-type so the user sees how their scale variable is
    # being summarised. This NEVER changes which tests run — both
    # subtypes feed the same parametric / non-parametric machinery.
    if detected == "scale":
        record["scale_subtype"] = "discrete" if all_int else "continuous"
    else:
        record["scale_subtype"] = None

    record["storage_type"] = storage
    record["statistical_nature"] = nature
    record["interpretation"] = interp
    record["analytical_flexibility"] = flex
    record["reasoning"] = reasoning
    return record


def _interpret(name: str, detected: VarType, storage: str, unique: int, all_int: bool) -> str:
    """Return one of: measurement, count, grading, binary_indicator,
    category, identifier, date, free_text, empty.

    Per the MedRAS spec the interpretation reflects what the variable
    IS clinically, NOT how the column was named. The only place where
    names matter here is to distinguish a count column from a
    continuous measurement (both are scale, but their descriptive
    summaries differ) and to mark obvious binary indicators (sex,
    diabetic, alive/dead).
    """
    if detected == "id":
        return "identifier"
    if detected == "date" or storage == "date":
        return "date"
    if detected == "exclude":
        # Distinguish empty/single-value from free-text rejection.
        if storage == "text" and unique > 20:
            return "free_text"
        return "empty"
    if detected == "scale":
        # Counts are conceptually distinct from continuous measurements
        # for descriptive-statistics reasoning even though both go
        # through the same scale machinery.
        if all_int and _COUNT_NAME_RE.search(name):
            return "count"
        return "measurement"
    if detected == "discrete":
        # Legacy / user-override path. Treat the same as a count.
        return "count"
    if detected == "ordinal":
        # Per spec, ordinal-detected always means a small ordered
        # category set — i.e. a grading.
        return "grading"
    if detected == "nominal":
        if _BINARY_NAME_RE.search(name) and unique <= 2:
            return "binary_indicator"
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
    if interp == "measurement":
        # Raw scores, lab values, durations, dimensions — analyse as
        # continuous; clinical bands available for descriptive grouping.
        return ["continuous", "categorical_after_binning"]
    if interp == "count":
        # Counts retain scale-style continuous analysis but can also be
        # treated ordinally when low-cardinality or grouped categorically.
        return ["continuous", "ordinal", "categorical"]
    if interp == "grading":
        return ["ordinal", "categorical"]
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
    if interp == "measurement":
        return (
            "Numeric variable analysed as a continuous scale — default "
            "summaries are mean (SD) and median (IQR), with optional "
            "clinical banding available for descriptive grouping."
        )
    if interp == "grading":
        return (
            f"Small ordered integer set ({unique} levels). Best summarised "
            "by counts and percentages and tested with rank-based or "
            "chi-square methods."
        )
    if interp == "count":
        return (
            f"Integer count variable ({unique} distinct values). Analysed "
            "as scale to preserve precision; reported with median (IQR) "
            "when skewed and mean (SD) when symmetric. Can also be grouped "
            "into clinically meaningful bands."
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


def clean_numeric_like_columns(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, Dict[str, str]]:
    """Auto-extract numeric values from text columns whose entries are
    numbers with attached unit/category labels (``"2mm"``, ``"12 kg"``,
    ``"Grade 3"``, ``"Score 85"``, ``"7.5%"``, ``"45 °C"``).

    For each text column where ≥80% of non-null values yield a clean
    single-numeric extraction, the column is replaced with the parsed
    floats so the classifier subsequently treats it as scale (per the
    spec rule: "default to scale when arithmetic is meaningful").

    Returns ``(modified_df, notes)`` where ``notes`` maps each affected
    column name to a short human-readable cleanup note describing what
    was extracted (sample label / unit). Columns that don't qualify
    (insufficient match rate, date-like, or where the extraction
    collapses many text labels into a tiny set of numbers) are left
    untouched.
    """
    notes: Dict[str, str] = {}
    out = df.copy()
    for col in df.columns:
        s = df[col]
        # Only process object/string columns; numeric columns are
        # already in their analytical form.
        if not (s.dtype == object or pd.api.types.is_string_dtype(s)):
            continue
        if pd.api.types.is_datetime64_any_dtype(s):
            continue
        non_null = s.dropna()
        if non_null.empty:
            continue
        # Skip obvious date columns to avoid mauling timestamps.
        if _looks_like_date(s):
            continue
        # Skip ID-looking columns: even if "P001"/"P002" matches the
        # numeric-with-prefix pattern, the values are identifiers, not
        # measurements — extracting the numeric part would just replace
        # nice readable IDs with raw integers.
        if _ID_NAME_RE.search(col):
            continue
        non_null_str = non_null.astype(str)
        extracted = non_null_str.apply(_extract_numeric)
        match_rate = float(extracted.notna().mean())
        if match_rate < 0.8:
            continue
        # Skip when the extraction collapses many text labels into a
        # tiny set of numbers — likely a true categorical column with
        # incidental embedded numbers, not a measurement.
        unique_extracted = int(extracted.dropna().nunique())
        unique_text = int(non_null_str.nunique())
        if unique_extracted < 3 and unique_text > unique_extracted + 1:
            continue
        # Skip multi-label coded categories: ``"Group A 1"`` /
        # ``"Group B 2"`` / ``"Group C 3"`` would otherwise be
        # auto-extracted to 1/2/3 and incorrectly promoted to ordinal.
        # A genuine measurement column has at most ONE distinct leading
        # label ("Score 85" / "Score 72") — multiple distinct labels
        # signal a category coding scheme, not a unit-tagged number.
        labels_for_guard = (
            non_null_str.str.extract(_NUMERIC_LABEL_RE)[0]
            .dropna()
            .map(lambda x: str(x).strip().lower())
        )
        if labels_for_guard.nunique() > 1:
            continue
        # Replace the column with extracted numerics, preserving NaNs.
        new_values = [
            _extract_numeric(str(v)) if pd.notna(v) else np.nan
            for v in s
        ]
        out[col] = pd.Series(new_values, index=s.index, dtype="float64")
        # Build a note describing what was stripped.
        sample = non_null_str.head(50)
        labels = (
            sample.str.extract(_NUMERIC_LABEL_RE)[0]
            .dropna()
            .map(lambda x: str(x).strip())
            .replace("", np.nan)
            .dropna()
            .unique()
            .tolist()
        )
        units = (
            sample.str.extract(_NUMERIC_UNIT_RE)[0]
            .dropna()
            .map(lambda x: str(x).strip())
            .replace("", np.nan)
            .dropna()
            .unique()
            .tolist()
        )
        bits: List[str] = []
        if labels:
            bits.append(f"label \u2018{labels[0]}\u2019")
        if units:
            bits.append(f"unit \u2018{units[0]}\u2019")
        suffix = " (" + ", ".join(bits) + ")" if bits else ""
        notes[col] = (
            f"Auto-extracted numeric values from text{suffix}; "
            "converted to numeric and treated as scale."
        )
    return out, notes


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
