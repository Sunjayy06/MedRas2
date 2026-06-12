"""Data quality checks for the Statistical Analysis Engine — Screen 4.

Three check categories run on the dataset:

1. **Impossible values**: clinical bounds per common medical variable
   (Age 0-120, Hb 1-25 g/dL, SBP 50-300 mmHg, etc).
2. **Duplicates**: exact row duplicates (auto-removable) and partial
   duplicates on a single Patient_ID column (flagged for user review).
3. **Logical consistency**: discharge before admission, male+pregnant.

Each check produces a list of flag dicts with a row index, variable, value,
issue type, and a recommended action. The UI lets the user choose
``keep`` / ``remove`` / ``cap`` / ``review`` per flag, and the apply step
mutates a copy of the DataFrame accordingly.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.services import domain_profiles


# -----------------------------------------------------------------------------
# Clinical bounds — name pattern → (min, max, unit, label).
# Pattern is matched case-insensitively against the column header. The first
# pattern that matches wins.
# -----------------------------------------------------------------------------
_BOUNDS: List[Tuple[re.Pattern, float, float, str, str]] = [
    (re.compile(r"^age\b|\bage\b", re.I), 0, 120, "years", "Age"),
    (re.compile(r"\bhb\b|haemoglob|hemoglob", re.I), 1, 25, "g/dL", "Haemoglobin"),
    (re.compile(r"\bsbp\b|systolic", re.I), 50, 300, "mmHg", "Systolic BP"),
    (re.compile(r"\bdbp\b|diastolic", re.I), 20, 200, "mmHg", "Diastolic BP"),
    (re.compile(r"\bbmi\b|body[_ ]?mass", re.I), 10, 80, "kg/m²", "BMI"),
    (re.compile(r"\bspo2\b|oxygen[_ ]?sat", re.I), 50, 100, "%", "SpO₂"),
    (re.compile(r"\bhr\b|heart[_ ]?rate|pulse", re.I), 20, 300, "bpm", "Heart rate"),
    (re.compile(r"\btemp\b|temperature", re.I), 30, 45, "°C", "Temperature"),
    (re.compile(r"\bhba1c\b", re.I), 3, 20, "%", "HbA1c"),
    (re.compile(r"\bfbs\b|fasting[_ ]?blood", re.I), 30, 600, "mg/dL", "FBS"),
    (re.compile(r"\bferritin\b", re.I), 1, 2000, "ng/mL", "Ferritin"),
    (re.compile(r"\bweight\b", re.I), 1, 300, "kg", "Weight"),
    (re.compile(r"\bheight\b", re.I), 30, 250, "cm", "Height"),
]


def _bound_for(col_name: str) -> Optional[Tuple[float, float, str, str]]:
    for pat, lo, hi, unit, label in _BOUNDS:
        if pat.search(col_name):
            return (lo, hi, unit, label)
    return None


def _safe_value(v: Any) -> Any:
    """Make NumPy / pandas scalars JSON-safe."""
    if v is None:
        return None
    if isinstance(v, float) and np.isnan(v):
        return None
    if isinstance(v, (np.floating,)):
        f = float(v)
        return None if np.isnan(f) else f
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    return v


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def check_impossible_values(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Flag values that fall outside accepted clinical bounds."""
    flags: List[Dict[str, Any]] = []
    for col in df.columns:
        bound = _bound_for(str(col))
        if bound is None:
            continue
        lo, hi, unit, label = bound
        s = pd.to_numeric(df[col], errors="coerce")
        bad_mask = s.notna() & ((s < lo) | (s > hi))
        if not bad_mask.any():
            continue
        for idx in df.index[bad_mask]:
            v = float(s.loc[idx])
            flags.append(
                {
                    "row": int(idx),
                    "variable": col,
                    "value": v,
                    "issue": (
                        f"{label} value {v:g} {unit} is outside the accepted "
                        f"range ({lo:g}–{hi:g} {unit})."
                    ),
                    "issue_type": "impossible_value",
                    "bound_low": lo,
                    "bound_high": hi,
                    "unit": unit,
                    "recommended_action": "cap" if (v < lo * 0.5 or v > hi * 1.5) else "review",
                }
            )
    return flags


def check_duplicates(df: pd.DataFrame, id_columns: Optional[List[str]] = None) -> Dict[str, Any]:
    """Detect exact row duplicates and (if an ID column is given) duplicate IDs.

    Returns ``{"exact_duplicate_rows": [...], "duplicate_id_groups": [...]}``.

    ``exact_duplicate_rows`` lists only the EXTRA rows (keep="first") so that
    the count matches what apply_quality_actions actually removes. The total
    rows in duplicate groups is reported separately for context.
    """
    extras_mask = df.duplicated(keep="first")
    exact_rows = [int(i) for i in df.index[extras_mask]]
    rows_in_groups = int(df.duplicated(keep=False).sum())
    dup_id_groups: List[Dict[str, Any]] = []
    if id_columns:
        for col in id_columns:
            if col not in df.columns:
                continue
            counts = df[col].value_counts(dropna=True)
            dup_ids = counts[counts > 1].index.tolist()
            for did in dup_ids:
                rows = [int(i) for i in df.index[df[col] == did]]
                dup_id_groups.append(
                    {
                        "id_column": col,
                        "id_value": _safe_value(did),
                        "row_count": len(rows),
                        "row_indices": rows,
                    }
                )
    return {
        "exact_duplicate_rows": exact_rows,
        "exact_duplicate_rows_total_in_groups": rows_in_groups,
        "duplicate_id_groups": dup_id_groups,
    }


def check_logical_consistency(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Logical-error checks across pairs of columns."""
    flags: List[Dict[str, Any]] = []
    cols_lower = {c.lower(): c for c in df.columns}

    # Discharge before admission.
    adm = next((cols_lower[c] for c in cols_lower if "admission" in c and "date" in c), None)
    dis = next((cols_lower[c] for c in cols_lower if "discharge" in c and "date" in c), None)
    if adm and dis:
        a = pd.to_datetime(df[adm], errors="coerce", format="mixed")
        d = pd.to_datetime(df[dis], errors="coerce", format="mixed")
        bad = a.notna() & d.notna() & (d < a)
        for idx in df.index[bad]:
            flags.append(
                {
                    "row": int(idx),
                    "variable": f"{adm} / {dis}",
                    "value": f"{a.loc[idx].date()} → {d.loc[idx].date()}",
                    "issue": "Discharge date is before admission date.",
                    "issue_type": "logical_error",
                    "recommended_action": "review",
                }
            )

    # Male marked as pregnant.
    sex = next((cols_lower[c] for c in cols_lower if c in ("sex", "gender")), None)
    preg = next((cols_lower[c] for c in cols_lower if "pregnan" in c), None)
    if sex and preg:
        s = df[sex].astype(str).str.strip().str.lower()
        p = df[preg].astype(str).str.strip().str.lower()
        male_mask = s.isin({"m", "male", "1"})
        preg_mask = p.isin({"y", "yes", "true", "1"})
        bad = male_mask & preg_mask
        for idx in df.index[bad]:
            flags.append(
                {
                    "row": int(idx),
                    "variable": f"{sex} / {preg}",
                    "value": f"{df.loc[idx, sex]} + pregnant=Yes",
                    "issue": "Patient marked male and pregnant.",
                    "issue_type": "logical_error",
                    "recommended_action": "review",
                }
            )
    return flags


def empty_row_count(df: pd.DataFrame) -> int:
    """Count rows that are entirely NaN."""
    return int(df.isna().all(axis=1).sum())


# -----------------------------------------------------------------------------
# Section C extensions — categorical consistency on Nominal columns
# -----------------------------------------------------------------------------

# Common short-form ⇄ long-form pairs we treat as the same label when only
# one word differs between two unique values. Bidirectional: order does not
# matter when looking up.
_ABBREVIATIONS: Dict[str, str] = {
    "lt": "left",
    "rt": "right",
    "l": "left",
    "r": "right",
    "yrs": "years",
    "yr": "year",
    "mins": "minutes",
    "min": "minute",
    "hrs": "hours",
    "hr": "hour",
    "wks": "weeks",
    "wk": "week",
    "mos": "months",
    "mo": "month",
}

# A nominal column whose values look like "4", "7.5", "Grade 3", "Level 2"
# is almost certainly a numeric variable that landed in nominal because it
# was stored as text. We flag any column whose share of numeric-looking
# values is at or above this threshold.
_NUMERIC_AS_TEXT_THRESHOLD = 0.7
_NUMERIC_VAL_RE = re.compile(r"^-?\d+(\.\d+)?$")
_LABELLED_NUMERIC_RE = re.compile(
    r"^(grade|level|score|stage|class|category|type)\s+-?\d+(\.\d+)?$",
    re.I,
)


def _first_index_for(df: pd.DataFrame, col: str, predicate) -> int:
    """Return the first row index where `predicate(value)` is True."""
    s = df[col]
    for idx in df.index:
        v = s.loc[idx]
        if pd.isna(v):
            continue
        if predicate(str(v).strip()):
            return int(idx)
    return 0


def check_categorical_consistency(
    df: pd.DataFrame,
    classifications: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Run Nominal-column hygiene checks: case mismatches, near-duplicates,
    and numeric-stored-as-text. Returns flag dicts in the same shape as
    ``check_logical_consistency`` so they merge cleanly into Section C.
    """
    if not classifications:
        return []
    nominal_cols = [
        c["column"]
        for c in classifications
        if c.get("detected_type") == "nominal" and c.get("column") in df.columns
    ]
    flags: List[Dict[str, Any]] = []

    for col in nominal_cols:
        s = df[col].dropna().astype(str).str.strip()
        s = s[s != ""]
        if s.empty:
            continue
        uniques = list(dict.fromkeys(s.tolist()))  # preserve order, drop dupes

        # CHECK 1 — case-only inconsistency.
        # Group unique values by their lower-case form. Any group with >1
        # variant is a single label written in multiple casings.
        seen_case_keys: set = set()
        case_groups: Dict[str, List[str]] = {}
        for v in uniques:
            key = v.lower()
            case_groups.setdefault(key, [])
            if v not in case_groups[key]:
                case_groups[key].append(v)
        for key, variants in case_groups.items():
            if len(variants) <= 1:
                continue
            seen_case_keys.add(key)
            variant_list = sorted(variants)
            first_idx = _first_index_for(df, col, lambda x: x.lower() == key)
            flags.append(
                {
                    "row": first_idx,
                    "variable": col,
                    "value": " / ".join(variant_list),
                    "issue": (
                        f"Inconsistent capitalisation in '{col}': "
                        f"{', '.join(repr(v) for v in variant_list)}."
                    ),
                    "issue_type": "case_inconsistency",
                    "recommended_action": "review",
                }
            )

        # CHECK 2 — near-duplicate text (whitespace differences or one-word
        # abbreviation swap). We deliberately skip pairs whose ONLY difference
        # is letter case (already caught above).
        seen_pairs: set = set()
        norm_uniques = [(u, re.sub(r"\s+", " ", u.strip()).lower()) for u in uniques]
        for i, (a, na) in enumerate(norm_uniques):
            for b, nb in norm_uniques[i + 1 :]:
                if a == b:
                    continue
                if a.lower() == b.lower():
                    # already flagged by case check
                    continue
                pair_key = tuple(sorted([a.lower(), b.lower()]))
                if pair_key in seen_pairs:
                    continue
                # Whitespace-only difference (extra/double/trailing space).
                if na == nb:
                    seen_pairs.add(pair_key)
                    first_idx = _first_index_for(
                        df, col, lambda x, A=a, B=b: x == A or x == B
                    )
                    flags.append(
                        {
                            "row": first_idx,
                            "variable": col,
                            "value": f"{a!r} vs {b!r}",
                            "issue": (
                                f"Possible duplicate label in '{col}': "
                                f"'{a}' and '{b}' differ only by whitespace."
                            ),
                            "issue_type": "near_duplicate",
                            "recommended_action": "review",
                        }
                    )
                    continue
                # Single-word abbreviation difference, same word count.
                wa, wb = na.split(), nb.split()
                if len(wa) != len(wb) or len(wa) == 0:
                    continue
                diffs = [(x, y) for x, y in zip(wa, wb) if x != y]
                if len(diffs) != 1:
                    continue
                x, y = diffs[0]
                if _ABBREVIATIONS.get(x) == y or _ABBREVIATIONS.get(y) == x:
                    seen_pairs.add(pair_key)
                    first_idx = _first_index_for(
                        df, col, lambda v, A=a, B=b: v == A or v == B
                    )
                    flags.append(
                        {
                            "row": first_idx,
                            "variable": col,
                            "value": f"{a!r} vs {b!r}",
                            "issue": (
                                f"Possible duplicate label in '{col}': "
                                f"'{a}' looks like an abbreviation of '{b}'."
                            ),
                            "issue_type": "near_duplicate",
                            "recommended_action": "review",
                        }
                    )

        # CHECK 3 — numeric-stored-as-text. If most values are bare numbers
        # or "Grade 3" / "Level 2" patterns, the column was probably meant
        # to be numeric.
        numeric_like = sum(
            1
            for v in s
            if _NUMERIC_VAL_RE.match(v) or _LABELLED_NUMERIC_RE.match(v)
        )
        if numeric_like and numeric_like / len(s) >= _NUMERIC_AS_TEXT_THRESHOLD:
            sample_vals = ", ".join(uniques[:3])
            first_idx = _first_index_for(df, col, lambda _x: True)
            flags.append(
                {
                    "row": first_idx,
                    "variable": col,
                    "value": sample_vals,
                    "issue": (
                        f"Column '{col}' is classified as Nominal but values "
                        f"look numeric — may be a score or grade variable."
                    ),
                    "issue_type": "numeric_as_text",
                    "recommended_action": "review",
                }
            )

    return flags


def _missingness_by_column(df: pd.DataFrame) -> Dict[str, float]:
    """Return per-column missingness as a percentage in [0, 100]."""
    if df.empty or df.shape[0] == 0:
        return {}
    out: Dict[str, float] = {}
    n = float(df.shape[0])
    for col in df.columns:
        miss = float(df[col].isna().sum()) / n * 100.0
        out[str(col)] = round(miss, 2)
    return out


def _compute_quality_score(
    *,
    missingness: Dict[str, float],
    n_outliers: int,
    n_duplicate_rows: int,
    n_consistency: int,
) -> int:
    """Calculate the composite quality score per the Step 4 spec.

    Start at 100 and apply deductions:
      - >50%   missing column: -10 each
      - 20–50% missing column: -5 each
      - 5–20%  missing column: -2 each
      - each outlier flag:     -2
      - each duplicate row:    -3
      - each consistency error:-3
    Floor at 0.
    """
    score = 100
    for pct in missingness.values():
        if pct > 50:
            score -= 10
        elif pct >= 20:
            score -= 5
        elif pct >= 5:
            score -= 2
    score -= 2 * n_outliers
    score -= 3 * n_duplicate_rows
    score -= 3 * n_consistency
    return max(0, score)


def _score_band(score: int) -> str:
    """Map a quality score to its colour band: green / amber / red."""
    if score >= 90:
        return "green"
    if score >= 70:
        return "amber"
    return "red"


def quality_report(
    df: pd.DataFrame,
    *,
    classifications: Optional[List[Dict[str, Any]]] = None,
    profile: str = domain_profiles.DEFAULT_PROFILE,
) -> Dict[str, Any]:
    """Build the full quality report consumed by Screen 4."""
    id_columns: List[str] = []
    if classifications:
        id_columns = [c["column"] for c in classifications if c.get("detected_type") == "id"]
    clinical_checks = domain_profiles.is_clinical(profile)
    impossible = check_impossible_values(df) if clinical_checks else []
    dups = check_duplicates(df, id_columns=id_columns or None)
    logical = check_logical_consistency(df) if clinical_checks else []
    if clinical_checks:
        active_profile = domain_profiles.normalize_profile(profile)
        for item in impossible + logical:
            item["domain_profile"] = active_profile
            item["provenance"] = (
                f"Suggested by {active_profile} profile: clinical quality check."
            )
    consistency = check_categorical_consistency(df, classifications=classifications)
    # Section C surfaces both the cross-column logical errors and the
    # categorical-hygiene flags as a single list.
    section_c = list(logical) + list(consistency)
    n_outliers = len(impossible)
    n_dup_rows = len(dups["exact_duplicate_rows"])
    n_consistency = len(section_c)
    missingness = _missingness_by_column(df)
    score = _compute_quality_score(
        missingness=missingness,
        n_outliers=n_outliers,
        n_duplicate_rows=n_dup_rows,
        n_consistency=n_consistency,
    )
    return {
        "domain_profile": domain_profiles.normalize_profile(profile),
        "summary": {
            "total_records": int(df.shape[0]),
            "variables_checked": int(df.shape[1]),
            "issues_found": n_outliers,
            "exact_duplicate_rows": n_dup_rows,
            "consistency_errors": n_consistency,
            "empty_rows": empty_row_count(df),
            "quality_score": score,
            "score_band": _score_band(score),
            "missingness": missingness,
        },
        "impossible_values": impossible,
        "duplicates": dups,
        "logical_errors": section_c,
    }


def apply_actions(
    df: pd.DataFrame,
    *,
    actions: List[Dict[str, Any]],
    remove_exact_duplicates: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Apply user-chosen actions to a copy of ``df`` and return ``(new_df, log)``.

    ``actions`` is a list of ``{"row": int, "variable": str, "action": str,
    "bound_low": float, "bound_high": float}`` items.
    """
    out = df.copy()
    counts = {"removed_rows": 0, "capped_values": 0, "kept": 0, "reviewed": 0}

    rows_to_drop: set[int] = set()
    for a in actions:
        action = (a.get("action") or "keep").lower()
        row = a.get("row")
        var = a.get("variable")
        if action == "remove" and row is not None:
            rows_to_drop.add(int(row))
        elif action == "cap" and row is not None and var in out.columns:
            lo = a.get("bound_low")
            hi = a.get("bound_high")
            if lo is None or hi is None:
                continue
            try:
                v = float(out.at[row, var])
            except Exception:
                continue
            if v < lo:
                out.at[row, var] = lo
                counts["capped_values"] += 1
            elif v > hi:
                out.at[row, var] = hi
                counts["capped_values"] += 1
        elif action == "review":
            counts["reviewed"] += 1
        else:
            counts["kept"] += 1

    if rows_to_drop:
        out = out.drop(index=list(rows_to_drop), errors="ignore")
        counts["removed_rows"] += len(rows_to_drop)

    if remove_exact_duplicates:
        before = len(out)
        out = out.drop_duplicates(keep="first")
        counts["removed_rows"] += before - len(out)

    out = out.reset_index(drop=True)
    return out, counts
