"""Category near-duplicate detection and auto-merge for MedRAS (Step 3 data quality).

Given a nominal/ordinal column, detects values that are likely the same
category entered inconsistently (e.g. "Left", "Left :", "Postive", "Positive",
"male", "Male", "MALE") and proposes or silently applies merges.

Strategy
--------
Two values are "near-duplicates" when at least ONE of the following is true:

1. **Suffix/prefix noise** — identical after stripping common trailing noise
   characters (spaces, colons, full-stops, hyphens, slashes, parentheses).
2. **Case fold** — identical after lowercasing + whitespace normalisation.
3. **Edit-distance** — Levenshtein distance ≤ 1 for strings ≥ 4 chars,
   OR distance ≤ 2 for strings ≥ 8 chars (catches "Positive"/"Positvie").

Classification of detected pairs
---------------------------------
* **obvious** — case/punctuation/whitespace only → auto-merged silently.
* **borderline** — edit-distance merge → flagged for user review.

The ``canonical`` form for a merge group is the most frequent clean value;
ties are broken alphabetically.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_basic(v: str) -> str:
    """Strip trailing/leading noise characters and normalise whitespace."""
    v = v.strip()
    v = re.sub(r"[\s:.\-/()]+$", "", v)   # trailing punctuation
    v = re.sub(r"^[\s:.\-/()]+", "", v)   # leading punctuation
    v = re.sub(r"\s+", " ", v).strip()
    return v


def _normalise(v: str) -> str:
    """Lowercase + basic clean for grouping."""
    return _clean_basic(v).lower()


def _levenshtein(a: str, b: str) -> int:
    """Pure-Python Levenshtein distance (fast for short strings)."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    if la < lb:
        a, b, la, lb = b, a, lb, la
    row = list(range(lb + 1))
    for i in range(1, la + 1):
        prev = row[0]
        row[0] = i
        for j in range(1, lb + 1):
            old = prev
            prev = row[j]
            row[j] = (
                old if a[i - 1] == b[j - 1]
                else 1 + min(old, row[j - 1], prev)
            )
    return row[lb]


def _is_obvious_dup(a_raw: str, b_raw: str) -> bool:
    """True when the difference is only casing / punctuation / whitespace."""
    return _normalise(a_raw) == _normalise(b_raw)


def _is_borderline_dup(a_raw: str, b_raw: str) -> bool:
    """True when edit-distance suggests a typo (but not an obvious dup)."""
    if _is_obvious_dup(a_raw, b_raw):
        return False
    a = _normalise(a_raw)
    b = _normalise(b_raw)
    min_len = min(len(a), len(b))
    if min_len < 4:
        return False
    dist = _levenshtein(a, b)
    if min_len >= 8 and dist <= 2:
        return True
    if min_len >= 4 and dist <= 1:
        return True
    return False


def _canonical(values: List[str], freq: Dict[str, int]) -> str:
    """Pick the canonical label: most-frequent clean form, ties → alphabetical."""
    clean_vals = [(_clean_basic(v), v) for v in values]
    best = max(clean_vals, key=lambda cv: (freq.get(cv[1], 0), -ord(cv[0][0].lower() if cv[0] else "z")))[0]
    return best


# ---------------------------------------------------------------------------
# Union-Find for merge groups
# ---------------------------------------------------------------------------


class _UF:
    def __init__(self) -> None:
        self._parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        self._parent.setdefault(x, x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra

    def groups(self, items: List[str]) -> List[List[str]]:
        buckets: Dict[str, List[str]] = defaultdict(list)
        for item in items:
            buckets[self.find(item)].append(item)
        return [g for g in buckets.values() if len(g) > 1]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_category_duplicates(
    series: "pd.Series",
    max_categories: int = 200,
) -> Dict[str, Any]:
    """Detect near-duplicate category labels in a nominal/ordinal column.

    Parameters
    ----------
    series:
        The raw column Series (dtype object / string).
    max_categories:
        Skip detection on columns with more distinct values than this
        (likely free text, not categories).

    Returns
    -------
    dict with keys:
        ``obvious``   — list of merge proposals that are safe to auto-apply
                        (case/punctuation differences only).
        ``borderline`` — list of merge proposals that need user review
                         (edit-distance matches).
        ``n_dirty``   — total number of dirty values (before merging).

    Each proposal is::

        {
          "canonical": "Positive",         # the clean target label
          "members":   ["Postive", "positive", "Positive :"],
          "kind":      "obvious" | "borderline",
          "counts":    {"Postive": 3, "positive": 12, "Positive :": 1},
        }
    """
    raw = series.dropna().astype(str)
    freq: Dict[str, int] = raw.value_counts().to_dict()
    distinct = list(freq.keys())

    if len(distinct) > max_categories or len(distinct) < 2:
        return {"obvious": [], "borderline": [], "n_dirty": 0}

    uf_obvious = _UF()
    uf_all = _UF()

    for i, a in enumerate(distinct):
        for b in distinct[i + 1:]:
            if _is_obvious_dup(a, b):
                uf_obvious.union(a, b)
                uf_all.union(a, b)
            elif _is_borderline_dup(a, b):
                uf_all.union(a, b)

    obvious_groups = uf_obvious.groups(distinct)
    all_groups = uf_all.groups(distinct)

    obvious_roots: Set[str] = set()
    for g in obvious_groups:
        roots = {uf_all.find(v) for v in g}
        obvious_roots.update(roots)

    obvious_props: List[Dict[str, Any]] = []
    borderline_props: List[Dict[str, Any]] = []

    for group in all_groups:
        canon = _canonical(group, freq)
        counts = {v: freq.get(v, 0) for v in group}
        root = uf_all.find(group[0])
        prop: Dict[str, Any] = {
            "canonical": canon,
            "members": sorted(group, key=lambda v: -freq.get(v, 0)),
            "counts": counts,
        }
        if root in obvious_roots:
            prop["kind"] = "obvious"
            obvious_props.append(prop)
        else:
            prop["kind"] = "borderline"
            borderline_props.append(prop)

    n_dirty = sum(
        sum(counts.values())
        for p in (obvious_props + borderline_props)
        for counts in [p["counts"]]
        if len(p["members"]) > 1
    ) - sum(
        p["counts"].get(p["canonical"], 0)
        for p in (obvious_props + borderline_props)
    )

    return {
        "obvious": obvious_props,
        "borderline": borderline_props,
        "n_dirty": max(n_dirty, 0),
    }


def detect_all_columns(
    df: "pd.DataFrame",
    classifications: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Run duplicate detection on every nominal/ordinal column.

    Returns a dict keyed by column name, value = ``detect_category_duplicates()``
    result.  Only columns where at least one proposal is found are included.
    """
    nominal_cols = {
        c["column"]
        for c in classifications
        if c.get("detected_type") in ("nominal", "ordinal")
        and c.get("column") in df.columns
    }
    out: Dict[str, Any] = {}
    for col in nominal_cols:
        result = detect_category_duplicates(df[col])
        if result["obvious"] or result["borderline"]:
            out[col] = result
    return out


def apply_merges(
    df: "pd.DataFrame",
    merges: List[Dict[str, Any]],
) -> Tuple["pd.DataFrame", List[str]]:
    """Apply a list of merge decisions to the DataFrame.

    Parameters
    ----------
    df:
        The dataset to modify (copied internally — original is untouched).
    merges:
        List of dicts, each with ``column``, ``canonical``, and ``members``
        (the full list of labels to replace with canonical).

    Returns
    -------
    (new_df, actions)
        ``actions`` — human-readable strings for the Methods section.
    """
    new_df = df.copy()
    actions: List[str] = []

    for m in merges:
        col = m.get("column")
        canon = m.get("canonical", "")
        members = m.get("members") or []
        if not col or col not in new_df.columns or not canon:
            continue
        to_replace = [v for v in members if str(v) != str(canon)]
        if not to_replace:
            continue
        replace_map = {str(v): str(canon) for v in to_replace}
        new_df[col] = new_df[col].astype(str).replace(replace_map)
        merged_list = ", ".join(f'"{v}"' for v in to_replace)
        actions.append(
            f'Merged {len(to_replace)} near-duplicate label(s) in "{col}" '
            f'→ canonical "{canon}" (replaced: {merged_list}).'
        )

    return new_df, actions
