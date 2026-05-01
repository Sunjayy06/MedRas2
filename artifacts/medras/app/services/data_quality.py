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


def quality_report(
    df: pd.DataFrame,
    *,
    classifications: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build the full quality report consumed by Screen 4."""
    id_columns: List[str] = []
    if classifications:
        id_columns = [c["column"] for c in classifications if c.get("detected_type") == "id"]
    impossible = check_impossible_values(df)
    dups = check_duplicates(df, id_columns=id_columns or None)
    logical = check_logical_consistency(df)
    n_issues = len(impossible) + len(logical)
    n_dup_rows = len(dups["exact_duplicate_rows"])
    # Score: 100 baseline, deduct for each issue, bottom out at 0.
    score = 100
    score -= min(60, n_issues * 4)
    score -= min(20, n_dup_rows * 2)
    score = max(0, score)
    return {
        "summary": {
            "total_records": int(df.shape[0]),
            "variables_checked": int(df.shape[1]),
            "issues_found": n_issues,
            "exact_duplicate_rows": n_dup_rows,
            "empty_rows": empty_row_count(df),
            "quality_score": score,
        },
        "impossible_values": impossible,
        "duplicates": dups,
        "logical_errors": logical,
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
