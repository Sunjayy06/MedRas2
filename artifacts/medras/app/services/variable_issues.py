"""Variable-level issue detection and auto-coding plan for Step 3.

This module is intentionally additive: ``variable_classifier`` keeps its
existing behaviour, and we layer issue detection plus a structured
auto-coding plan on top. The Step 3 UI uses these to surface amber issue
sub-lines and the Zone D info box.

Five issue types are supported:

* ``text_in_numeric``    — a column the classifier flagged as ordinal/scale
  but where the raw values still contain non-numeric characters
  (e.g. ``"Grade 4"``). Blocks Confirm until resolved.
* ``low_unique_nominal`` — a nominal column with only 1-2 unique levels and
  no obvious yes/no / sex coding (often means the column is constant or
  an excluded id slipped through).
* ``high_missing``       — > 30% missing values.
* ``duplicate_values``   — labels in a nominal column that differ only by
  whitespace (``"Positive"`` and ``" Positive "``).
* ``numeric_as_id``      — a numeric column whose values are unique enough
  to look like a row identifier even though the name doesn't match the id
  pattern.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

import pandas as pd

from app.services import variable_classifier


_NUMERIC_TOKEN_RE = re.compile(r"-?\d+(?:\.\d+)?")
_LETTER_RE = re.compile(r"[A-Za-z]")


def detect_issues(df: pd.DataFrame, classifications: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Walk every classified column and return a flat list of issues."""
    out: List[Dict[str, Any]] = []
    n_rows = len(df) if df is not None else 0

    for c in classifications or []:
        col = c.get("column")
        if col is None or col not in df.columns:
            continue
        kind = c.get("detected_type")
        series = df[col]

        cleanup_note = str(c.get("cleanup_note") or "")
        if "Excel-corrupted" in cleanup_note or "were not created safely" in cleanup_note:
            out.append({
                "column": col,
                "type": "node_fraction_corruption",
                "severity": "warning",
                "message": cleanup_note,
            })

        # 1) text_in_numeric — column expected to be numeric but raw values
        # carry letters that prevent coercion (e.g. "Grade 4", "10 mg").
        if (
            kind in ("scale", "ordinal", "discrete")
            and not variable_classifier.is_known_categorical_clinical_marker(col)
        ):
            if not pd.api.types.is_numeric_dtype(series):
                non_null = series.dropna().astype(str)
                if len(non_null):
                    has_letters = non_null.str.contains(_LETTER_RE).any()
                    if has_letters:
                        sample = next((v for v in non_null.tolist() if _LETTER_RE.search(v)), "")
                        out.append({
                            "column": col,
                            "type": "text_in_numeric",
                            "severity": "blocking",
                            "message": f"Contains text like “{sample}”. Cannot run mean/SD until cleaned.",
                        })

        # 2) numeric_as_id — high-cardinality numeric that looks like a row id.
        if kind in ("scale", "discrete") and pd.api.types.is_numeric_dtype(series):
            present = int(series.dropna().shape[0])
            unique = int(series.dropna().nunique())
            if present >= 20 and unique / present >= 0.95:
                out.append({
                    "column": col,
                    "type": "numeric_as_id",
                    "severity": "warning",
                    "message": "Looks like a row identifier — every value is unique. Consider Exclude.",
                })

        # 3) low_unique_nominal — nominal columns that won't yield useful
        # comparison groups. Two cases:
        #   a) single value (constant column)
        #   b) two values where one dominates >95% of rows (near-constant —
        #      not enough variation for chi-square / group comparisons)
        # Skip recognisable yes/no and sex/gender binaries — those *are*
        # useful comparison variables and the auto-coding plan covers them.
        if kind == "nominal":
            non_null = series.dropna()
            unique = int(non_null.nunique())
            present = int(non_null.shape[0])
            if unique <= 1:
                out.append({
                    "column": col,
                    "type": "low_unique_nominal",
                    "severity": "warning",
                    "message": "Only one value present — column has no comparison groups.",
                })
            elif unique == 2 and present >= 20:
                lowered = {str(v).strip().lower() for v in non_null.tolist()}
                is_yes_no = lowered <= {"yes", "no", "y", "n", "true", "false", "0", "1"}
                is_sex = bool(re.fullmatch(r"(?i)sex|gender", str(col).strip()))
                if not (is_yes_no or is_sex):
                    counts = non_null.astype(str).str.strip().value_counts()
                    if not counts.empty:
                        top_share = counts.iloc[0] / present
                        if top_share > 0.95:
                            out.append({
                                "column": col,
                                "type": "low_unique_nominal",
                                "severity": "warning",
                                "message": (
                                    f"Two levels but {top_share * 100:.0f}% are "
                                    f"“{counts.index[0]}” — too little variation "
                                    "for group comparisons."
                                ),
                            })

        # 4) high_missing — > 30% missing.
        if n_rows:
            missing_pct = float(c.get("missing_pct") or 0.0)
            if missing_pct > 30.0:
                out.append({
                    "column": col,
                    "type": "high_missing",
                    "severity": "warning",
                    "message": f"{missing_pct:.1f}% of rows are missing.",
                })

        # 5) duplicate_values — whitespace-only label differences in nominal
        # columns. Casing differences belong in the category-merge workflow.
        if kind == "nominal" and series.dtype == object:
            non_null = series.dropna().astype(str)
            if len(non_null):
                whitespace_normalised = non_null.map(lambda v: " ".join(v.split()))
                groups = (
                    pd.DataFrame({"orig": non_null.values, "normalised": whitespace_normalised.values})
                    .drop_duplicates()
                    .groupby("normalised")["orig"]
                    .apply(list)
                )
                dup_pairs = [labels for labels in groups if len(labels) > 1]
                if dup_pairs:
                    sample = dup_pairs[0]
                    out.append({
                        "column": col,
                        "type": "duplicate_values",
                        "severity": "warning",
                        "message": f"Same value contains inconsistent whitespace: {', '.join(repr(s) for s in sample[:3])}.",
                    })
    return out


def auto_coding_plan(
    df: pd.DataFrame, classifications: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Return structured auto-coding entries the Step 3 UI shows in Zone D.

    Each entry: ``{column, kind, mapping: [{from, to}], note}``. ``kind``
    is ``sex_binary`` / ``yes_no`` / ``excluded`` so the front end can pick
    an appropriate icon / phrasing.
    """
    out: List[Dict[str, Any]] = []

    for c in classifications or []:
        col = c.get("column")
        if col is None or col not in df.columns:
            continue
        kind = c.get("detected_type")

        # Sex / Gender binary.
        if kind == "nominal" and re.fullmatch(r"(?i)sex|gender", str(col).strip()):
            sample = " ".join(str(v).lower() for v in (c.get("sample_values") or []))
            if "male" in sample or "female" in sample:
                out.append({
                    "column": col,
                    "kind": "sex_binary",
                    "mapping": [
                        {"from": "Male", "to": 1},
                        {"from": "Female", "to": 2},
                    ],
                    "note": "Standard SPSS coding for sex.",
                })
                continue

        # Yes / No nominal.
        if kind == "nominal":
            sample = [str(v).strip().lower() for v in (c.get("sample_values") or [])]
            if any(v in ("yes", "no") for v in sample):
                out.append({
                    "column": col,
                    "kind": "yes_no",
                    "mapping": [
                        {"from": "Yes", "to": 1},
                        {"from": "No", "to": 0},
                    ],
                    "note": "Binary Yes/No coding.",
                })
                continue

    # Excluded columns — single combined entry for clarity.
    excluded = [
        c["column"] for c in classifications
        if c.get("detected_type") in ("exclude", "id")
        and c.get("column") in df.columns
    ]
    if excluded:
        out.append({
            "column": None,
            "kind": "excluded",
            "mapping": [],
            "note": "Will not enter the analysis: " + ", ".join(excluded) + ".",
            "columns": excluded,
        })

    return out


def has_blocking_issues(issues: List[Dict[str, Any]]) -> bool:
    """True when any issue has ``severity == 'blocking'`` (text_in_numeric)."""
    return any((i or {}).get("severity") == "blocking" for i in (issues or []))
