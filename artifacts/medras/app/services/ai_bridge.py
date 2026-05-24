"""AI Bridge — Gemini-powered study-type detection and outcome column identification.

Called after a dataset is uploaded when the user provides a free-text study
description and an outcome column hint.  Returns:

  study_type   — "correlation" | "comparison" | "diagnostic" | "survival" | "descriptive"
  outcome_col  — exact column name from the dataset (or None if unknown)
  confidence   — 0.0 – 1.0
  reasoning    — one-sentence plain-English explanation
  all_predictors — list of all non-id/non-excluded column names that are not the outcome

Falls back gracefully to heuristics when the API key is missing or the quota
is exhausted.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import httpx

from app.services.llm_client import openai_chat_url, openai_auth_header, openai_is_configured, gemini_is_configured, get_gemini_client

log = logging.getLogger(__name__)
_TIMEOUT = 20.0

# Study-type keyword heuristics (used as fallback without Gemini)
# ---------------------------------------------------------------------------
# Standard clinical / IHC markers that are almost always PREDICTORS/grouping
# variables, NOT the primary study outcome — unless the user explicitly names
# one of these as their outcome variable.
# ---------------------------------------------------------------------------
# Markers whose NORMALIZED TOKEN SET must exactly match a column's token set
# (with allowed qualifier tokens) before we treat that column as a standard
# clinical/grouping variable rather than a novel primary study marker.
#
# DELIBERATELY excluded (because they are often the PRIMARY study variable):
#   p53, tp53, bcl2, bcl-2, bax, mlh1, pms2, msh2, msh6, s100, vimentin
_STANDARD_CLINICAL_MARKERS: frozenset = frozenset([
    # Steroid / nuclear receptors — almost always grouping variables
    "er", "estrogen receptor", "estrogen", "oestrogen", "oestrogen receptor",
    "pr", "progesterone receptor", "progesterone",
    "ar", "androgen receptor", "androgen",
    # Growth factor receptors — usually predictors in IHC studies
    "her2", "her 2", "erbb2", "c erbb2", "her2 neu",
    "egfr", "epidermal growth factor receptor",
    "vegf", "vegfr",
    # Proliferation marker — usually a predictor / grouping variable
    "ki67", "ki 67", "mib1", "mib 1", "mib",
    # Structural / panel markers
    "cytokeratin", "ck5", "ck6", "ck7", "ck20",
    "e cadherin", "ecadherin", "n cadherin",
    "hbme1", "tpo", "lca",
    # Molecular subtype (derived grouping variable, not a primary endpoint)
    "molecular subtype", "subtype",
])

_TYPE_WORDS: Dict[str, List[str]] = {
    # association = categorical↔categorical (chi-square / Fisher's / Cramér's V / OR)
    # correlation = continuous↔continuous (Pearson r / Spearman ρ)
    # Researchers often conflate the two; the validator enforces the distinction.
    "association": [
        "chi.square", "chi-square", "fisher", "odds ratio", "odd ratio",
        "cramer", "cramér", "categorical association", "cross.tab", "crosstab",
    ],
    "correlation": [
        "correlat", "pearson", "spearman", "linear model",
        "factor", "predictor", "risk factor",
        "effect of", "influence of", "impact of",
        "regression", "logistic",
    ],
    "comparison": [
        "compar", "difference", " vs ", " versus ", "between group",
        "treatment", "intervention", "control group", "arm", "trial",
        "randomis", "randomiz", "rct", "controlled trial",
        "case.control", "case control", "case-control",
    ],
    "diagnostic": [
        "sensitiv", "specific", "diagnostic", "accuracy", "roc", "auc",
        "screen", "test performance", "ppv", "npv",
    ],
    "survival": [
        "survival", "mortality", "time to", "kaplan", "death", "recurrence",
        "progression", "disease-free", "event-free",
    ],
    "descriptive": [
        "prevalence", "incidence", "frequenc", "distribution", "describe",
        "profile", "characteris", "cross.section", "cross-section",
        "cross sectional", "epidemiolog",
    ],
}


# ---------------------------------------------------------------------------
# Heuristic fallback helpers
# ---------------------------------------------------------------------------


def _detect_study_type_heuristic(description: str) -> str:
    dl = description.lower()
    for stype in ("diagnostic", "survival", "comparison", "correlation", "descriptive"):
        for word in _TYPE_WORDS[stype]:
            if word in dl:
                return stype
    return "correlation"


def _is_standard_marker(col: str) -> bool:
    """Return True if a column name maps to a routine clinical / IHC marker.

    Uses whole-token matching to avoid false positives like "p27 expression"
    matching the "pr" (progesterone receptor) abbreviation via substring.

    Logic:
      1. Normalized full-string match  →  "Ki-67" == "ki67"
      2. All marker tokens present in column tokens, with at most the
         column having a few known qualifier words (status, expression, etc.)
         as the only extras.
    """
    # Qualifiers that may legitimately follow a marker name in a column header
    _QUALIFIERS = frozenset([
        "status", "positive", "negative", "pos", "neg",
        "expression", "level", "score", "index", "result",
        "pct", "percent", "fraction", "staining", "stain",
        "ihc", "iihc", "group", "category", "pattern",
        "1", "2", "3", "0",
    ])

    def _tokens(s: str):
        return set(re.sub(r"[^a-z0-9]+", " ", s.lower()).split())

    def _norm(s: str):
        return re.sub(r"[^a-z0-9]", "", s.lower())

    col_tokens = _tokens(col)
    col_norm   = _norm(col)

    for marker in _STANDARD_CLINICAL_MARKERS:
        m_tokens = _tokens(marker)
        m_norm   = _norm(marker)

        if not m_tokens:
            continue

        # 1. Normalized full string (handles ki-67 ↔ ki67, her2/neu ↔ her2neu)
        if m_norm and m_norm == col_norm:
            return True

        # 2. All marker tokens appear in column tokens, and column has no
        #    unexpected extra tokens beyond the marker + known qualifiers.
        if m_tokens <= col_tokens:
            extra = col_tokens - m_tokens - _QUALIFIERS
            if not extra:
                return True

    return False


def _find_novel_marker(
    hint: str,
    description: str,
    columns: List[str],
) -> Optional[str]:
    """Find the best non-standard column that matches the hint or description.

    Used to override an LLM choice that landed on a standard clinical marker
    (e.g. PR, ER, HER2) when the study is about a novel/study-specific marker.
    Returns the best candidate only when there is a STRONG match; returns None
    if nothing clearly better is found, so the LLM choice is preserved.
    """
    non_standard = [c for c in columns if not _is_standard_marker(c)]
    if not non_standard:
        return None

    # 1. Direct fuzzy match on the hint against the non-standard subset.
    #    Only accept if the hint is non-trivial (≥ 4 chars) to avoid matching
    #    short words like "the", "and", "for".
    if hint and len(hint.strip()) >= 4:
        match = _fuzzy_match_column(hint, non_standard)
        if match:
            return match

    # 2. Token-scan the description against non-standard column names.
    #    Require a meaningful score (≥ 2 tokens overlap) so we don't redirect
    #    the outcome based on incidental word matches.
    desc_tokens = set(re.split(r"[\s,;./\-()]+", description.lower()))
    desc_tokens = {t for t in desc_tokens if len(t) >= 4}  # skip short words
    best_col, best_score = None, 0
    for col in non_standard:
        col_tokens = set(re.split(r"[\s_/\\.,-]+", col.lower()))
        col_tokens = {t for t in col_tokens if len(t) >= 4}
        score = len(desc_tokens & col_tokens)
        if score > best_score:
            best_score, best_col = score, col
    if best_score >= 2:  # require at least 2 meaningful overlapping tokens
        return best_col

    return None


def _fuzzy_match_column(hint: str, columns: List[str]) -> Optional[str]:
    """Find the column whose name best matches the user's hint.

    Tries exact → substring → token-overlap matching.
    """
    if not hint or not columns:
        return None
    hl = hint.lower().strip()
    # Exact
    for col in columns:
        if col.lower().strip() == hl:
            return col
    # Substring
    for col in columns:
        cl = col.lower().strip()
        if hl in cl or cl in hl:
            return col
    # Token overlap
    hint_tokens = set(re.split(r"[\s_/\\.,-]+", hl))
    best_col, best_score = None, 0
    for col in columns:
        col_tokens = set(re.split(r"[\s_/\\.,-]+", col.lower()))
        overlap = len(hint_tokens & col_tokens)
        if overlap > best_score:
            best_score, best_col = overlap, col
    if best_score > 0:
        return best_col
    return None


# ---------------------------------------------------------------------------
# Gemini call
# ---------------------------------------------------------------------------


def _call_openai(
    description: str,
    outcome_hint: str,
    columns: List[str],
) -> Optional[Dict[str, Any]]:
    """Call OpenAI GPT-4o-mini to identify study type and outcome column."""
    if not openai_is_configured():
        return None

    col_list = "\n".join(f"- {c}" for c in columns[:60])
    prompt = (
        f"You are a biostatistics assistant. A researcher uploaded an Excel dataset "
        f"with the following column names:\n{col_list}\n\n"
        f"They described their study as:\n\"{description}\"\n\n"
        f"They said their outcome column is (approximately): \"{outcome_hint}\"\n\n"
        "Return a JSON object with exactly these keys:\n"
        '{"study_type": "<one of: correlation | comparison | diagnostic | survival | descriptive>", '
        '"outcome_col": "<exact column name from the list above, or null>", '
        '"confidence": <float 0.0 to 1.0>, '
        '"reasoning": "<one plain English sentence explaining your choices>"}\n\n'
        "Rules:\n"
        "- outcome_col must be the EXACT column name string from the list, or null\n"
        "- The outcome column is the PRIMARY NOVEL marker or variable the study is\n"
        "  designed to examine (e.g. p27 expression, bcl-2 score, ALDH1 status).\n"
        "- Standard routine clinical/IHC markers — ER, PR, HER2, AR, EGFR, Ki-67,\n"
        "  p53, molecular subtype — are PREDICTORS (independent variables), NOT the\n"
        "  outcome, unless the user explicitly named one as their outcome variable.\n"
        "- If the outcome hint is blank or generic, choose the most study-specific\n"
        "  (novel) column — the one that is NOT a routine clinical marker.\n"
        "- Respond ONLY with valid JSON, nothing else."
    )

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 256,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = httpx.post(
            openai_chat_url(),
            json=payload,
            headers={"Authorization": openai_auth_header()},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
        return json.loads(text)
    except Exception:
        return None


def _call_gemini(
    description: str,
    outcome_hint: str,
    columns: List[str],
) -> Optional[Dict[str, Any]]:
    if not gemini_is_configured():
        return None

    col_list = "\n".join(f"- {c}" for c in columns[:60])
    prompt = f"""You are a biostatistics assistant. A researcher uploaded an Excel dataset 
with the following column names:
{col_list}

They described their study as:
"{description}"

They said their outcome column is (approximately): "{outcome_hint}"

Your task is to return a JSON object with exactly these keys:
{{
  "study_type": "<one of: correlation | comparison | diagnostic | survival | descriptive>",
  "outcome_col": "<exact column name from the list above, or null>",
  "confidence": <float 0.0 to 1.0>,
  "reasoning": "<one plain English sentence explaining your choices>"
}}

Rules:
- study_type "correlation" = researcher wants to find which variables are associated with the outcome
- study_type "comparison" = researcher wants to compare groups (RCT, case-control, cohort)
- outcome_col must be the EXACT column name string from the list, or null
- If the outcome hint matches a column name closely, pick that column
- CRITICAL: The outcome_col is the PRIMARY NOVEL marker or variable the study is designed
  to examine (e.g. p27 expression, bcl-2 score, ALDH1 status, PCNA index).
- Standard routine clinical/IHC markers (ER, PR, HER2, AR, EGFR, Ki-67, p53, molecular
  subtype, CD markers, cytokeratin) are PREDICTORS — do NOT pick them as outcome_col
  unless the outcome hint explicitly names one of them.
- If the outcome hint is blank or vague, identify the novel/study-specific column.
- Respond ONLY with valid JSON, nothing else.
"""

    try:
        from google.genai import types as gtypes
        client = get_gemini_client()
        resp = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=gtypes.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=256,
                response_mime_type="application/json",
            ),
        )
        text = (resp.text or "").strip()
        # Strip markdown code fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text.strip())
        return json.loads(text)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Statistician validation
# ---------------------------------------------------------------------------

# Keywords whose presence in the description means the researcher
# explicitly wants diagnostic accuracy (sensitivity/specificity/AUC).
# Only when these are present AND there is no continuous variable do we
# let the "diagnostic" label stand (the confirm screen will warn).
_DIAGNOSTIC_EXPLICIT = frozenset([
    "sensitiv", "specific", "roc", "auc", "ppv", "npv",
    "gold standard", "cut.off", "cutoff", "youden",
])

# Column-name fragments that suggest a time-to-event variable even when
# the detected_type is not "date" (e.g. "days_to_death", "followup_months").
_TIME_COL_FRAGMENTS = ("days", "months", "years", "time", "followup", "follow_up",
                       "duration", "survival", "event_time")


def _validate_study_type(
    study_type: str,
    outcome_col: Optional[str],
    classifications: List[Dict[str, Any]],
    description: str,
    reasoning: str,
) -> tuple:
    """Apply data-driven sanity checks and return (study_type, reasoning).

    The fundamental principle: the actual variable types in the dataset are
    the ground truth for test selection.  The study description / LLM guess
    is only a hint — it can be overridden by the data at any point.

    Decision matrix (data-first):
    ┌─────────────────────┬──────────────────────┬─────────────────────┐
    │ Outcome type        │ Predictor/group type │ Correct study_type  │
    ├─────────────────────┼──────────────────────┼─────────────────────┤
    │ categorical         │ any                  │ association         │
    │ continuous          │ categorical           │ comparison          │
    │ continuous          │ continuous            │ correlation         │
    │ any                 │ time-to-event col     │ survival            │
    │ continuous score    │ binary reference      │ diagnostic          │
    └─────────────────────┴──────────────────────┴─────────────────────┘

    Rules are applied in priority order; the first matching rule wins.
    """
    dl = description.lower()

    # ── Build dataset-level type inventory ───────────────────────────────
    type_counts: Dict[str, int] = {}
    for c in classifications:
        t = c.get("detected_type", "nominal")
        type_counts[t] = type_counts.get(t, 0) + 1

    has_continuous = type_counts.get("scale", 0) > 0
    has_date       = type_counts.get("date", 0) > 0

    all_col_names = [c.get("column", "").lower() for c in classifications]
    has_time_col  = any(
        frag in col for col in all_col_names for frag in _TIME_COL_FRAGMENTS
    )

    # ── Resolve outcome variable type ─────────────────────────────────────
    outcome_type: str = ""
    if outcome_col:
        for c in classifications:
            if c.get("column") == outcome_col:
                outcome_type = c.get("detected_type", "")
                break

    # Classify non-outcome, non-excluded predictors
    _SKIP_TYPES = {"id", "date", "exclude"}
    predictor_types = [
        c.get("detected_type", "nominal")
        for c in classifications
        if c.get("column") != outcome_col
        and c.get("detected_type") not in _SKIP_TYPES
    ]
    has_categorical_predictor = any(
        t in ("nominal", "ordinal", "binary") for t in predictor_types
    )
    has_continuous_predictor  = any(t == "scale" for t in predictor_types)

    # ── Description-derived explicit flags (override suppressors) ─────────
    survival_explicit = any(
        kw in dl for kw in ("kaplan", "time to event", "time-to-event",
                            "censored", "hazard ratio", "cox")
    )
    diagnostic_explicit = any(kw in dl for kw in _DIAGNOSTIC_EXPLICIT)

    # ═══════════════════════════════════════════════════════════════════════
    # RULE 1 — Survival needs a time-to-event column
    # ═══════════════════════════════════════════════════════════════════════
    if study_type == "survival" and not has_date and not has_time_col:
        if not survival_explicit:
            note = (
                "Survival/time-to-event analysis needs a date or time column "
                "— none was found in your dataset. "
                "Switched to 'comparison' (group difference analysis)."
            )
            return "comparison", f"{note} [{reasoning}]"

    # ═══════════════════════════════════════════════════════════════════════
    # RULE 2 — Diagnostic needs a continuous score
    # ═══════════════════════════════════════════════════════════════════════
    if study_type == "diagnostic" and not has_continuous and not diagnostic_explicit:
        if outcome_type in ("nominal", "binary", "ordinal") or not outcome_type:
            note = (
                "Diagnostic accuracy tests require a continuous test score "
                "for AUC/ROC — your dataset has no continuous variables. "
                "Switched to 'association' (chi-square / Fisher's exact / "
                "Cramér's V / odds ratio)."
            )
            return "association", f"{note} [{reasoning}]"
        note = (
            "Diagnostic accuracy tests require a continuous test score "
            "for AUC/ROC — your dataset has no continuous variables. "
            "Switched to 'correlation' (association analysis)."
        )
        return "correlation", f"{note} [{reasoning}]"

    # ═══════════════════════════════════════════════════════════════════════
    # RULE 3 — DATA-FIRST: Outcome variable type drives test family
    #
    # This is the core rule.  The outcome's measurement scale determines
    # which test family is valid — the study description is overridden
    # whenever it conflicts with the actual data.
    # ═══════════════════════════════════════════════════════════════════════
    if outcome_type and study_type not in ("survival", "diagnostic"):

        # 3a. Categorical outcome → must use association tests
        # (Chi-square / Fisher's exact / Cramér's V / odds ratio / logistic)
        # "Correlation" (Pearson/Spearman) and "comparison" (t-test/ANOVA)
        # require a CONTINUOUS outcome — they cannot be applied to categorical data.
        if outcome_type in ("nominal", "ordinal", "binary"):
            if study_type in ("correlation", "comparison"):
                note = (
                    f"Outcome '{outcome_col}' is categorical — "
                    f"'{study_type}' (Pearson/Spearman or t-test/ANOVA) cannot "
                    "be applied to categorical data. "
                    "Switched to 'association' (chi-square / Fisher's exact / "
                    "Cramér's V / odds ratio), which is the correct test for "
                    "a categorical outcome."
                )
                return "association", f"{note} [{reasoning}]"

        # 3b. Continuous outcome → cannot use chi-square (association)
        elif outcome_type == "scale":
            if study_type == "association":
                if has_categorical_predictor:
                    note = (
                        f"Outcome '{outcome_col}' is continuous — "
                        "chi-square / association tests require categorical outcomes. "
                        "Switched to 'comparison' (t-test / ANOVA) since categorical "
                        "predictors are present in your dataset."
                    )
                    return "comparison", f"{note} [{reasoning}]"
                elif has_continuous_predictor or has_continuous:
                    note = (
                        f"Outcome '{outcome_col}' is continuous — "
                        "chi-square / association tests require categorical outcomes. "
                        "Switched to 'correlation' (Pearson / Spearman)."
                    )
                    return "correlation", f"{note} [{reasoning}]"

            # 3c. Continuous outcome + no continuous predictors anywhere
            # → "correlation" (Pearson/Spearman) is impossible; use "comparison"
            if study_type == "correlation" and not has_continuous_predictor:
                note = (
                    f"Outcome '{outcome_col}' is continuous but all predictors are "
                    "categorical — Pearson/Spearman correlation requires continuous "
                    "predictors. "
                    "Switched to 'comparison' (t-test / ANOVA / Mann-Whitney)."
                )
                return "comparison", f"{note} [{reasoning}]"

    # ═══════════════════════════════════════════════════════════════════════
    # RULE 4 — Legacy rule: "correlation" with NO continuous variables at all
    # (catches the case where outcome_col was not identified)
    # ═══════════════════════════════════════════════════════════════════════
    if study_type == "correlation" and not has_continuous:
        note = (
            "'Correlation' (Pearson/Spearman) requires continuous measurements — "
            "your dataset has no continuous variables. "
            "Switched to 'association' (chi-square / Fisher's exact / Cramér's V / "
            "odds ratio), which is the correct analysis for categorical data."
        )
        return "association", f"{note} [{reasoning}]"

    # No override needed
    return study_type, reasoning


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _heuristic_outcome_from_description(
    description: str,
    columns: List[str],
) -> Optional[str]:
    """Scan the description for tokens that appear in non-standard column names.

    Used as a last-resort heuristic when both the outcome hint is empty and
    the LLM is unavailable. Prefers non-standard (novel) columns and returns
    the column with the highest token-overlap score, or None if nothing
    meaningful matches.
    """
    if not description or not columns:
        return None

    _SKIP_NAMES = frozenset(["sno", "id", "age", "sex", "gender", "no", "number",
                              "name", "date", "year", "serial", "reg", "mrn"])

    def _desc_token_set(text: str):
        """Split on whitespace and punctuation; also add normalised (no-sep) variants.

        E.g. "bcl-2" → {"bcl", "2", "bcl2"} so it matches a column "bcl2_score".
        """
        raw = set(re.split(r"[\s,;./\-()]+", text.lower()))
        toks = {t for t in raw if len(t) >= 2}
        # Add fused variants for pairs: "bcl" + "2" → "bcl2"
        raw_list = [t for t in re.split(r"[\s,;./\-()]+", text.lower()) if t]
        for i in range(len(raw_list) - 1):
            fused = raw_list[i] + raw_list[i + 1]
            if len(fused) >= 2:
                toks.add(fused)
        return toks

    def _col_base_tokens(col: str):
        toks = set(re.split(r"[\s_/\\.,-]+", col.lower()))
        # Also add normalised (no-separator) form of the whole column
        toks.add(re.sub(r"[^a-z0-9]", "", col.lower()))
        return {t for t in toks if len(t) >= 2 and t not in _SKIP_NAMES}

    desc_tokens = _desc_token_set(description)
    desc_lower  = description.lower()
    desc_norm   = re.sub(r"[^a-z0-9]", "", desc_lower)

    # Classifier suffixes — last part of a compound column that makes it a
    # categorical predictor, not the primary study outcome.
    # E.g. "Tumour_type", "Stage_CKD", "Lymph_node_status" → predictor.
    _CLASSIFIER_SUFFIXES = frozenset([
        "type", "grade", "status", "group", "category", "subtype", "class",
        "stage", "diagnosis", "histology", "laterality", "site", "location",
    ])

    # Generic words that are almost never the study outcome on their own.
    _GENERIC_DESCRIPTORS = frozenset([
        "type", "grade", "stage", "status", "group", "category",
        "subtype", "class", "size", "weight", "height", "bmi",
        "result", "outcome", "diagnosis", "histology", "laterality",
        "site", "location", "duration", "score", "index", "level",
        "count", "rate", "ratio", "value", "months", "days", "weeks",
        "tumour", "tumor", "cancer", "carcinoma",
    ])

    # Suffixes that follow a biomarker name (the subject is what matters).
    _BIOMARKER_SUFFIXES = frozenset([
        "expression", "positivity", "immunoreactivity", "staining",
        "score", "index", "level", "status",
    ])

    def _last_part(col: str) -> str:
        parts = re.split(r"[\s_]+", col.lower())
        return parts[-1] if parts else ""

    def _subject_tokens(non_skip: set) -> set:
        """Return the 'novel' tokens of a column after stripping generic suffixes.
        Also removes fused compound forms so 'tumourtype' or 'stageckd' don't
        masquerade as subject tokens."""
        toks = non_skip - _GENERIC_DESCRIPTORS - _BIOMARKER_SUFFIXES
        return {
            t for t in toks
            if not any(
                t == (a + b)
                for a in _GENERIC_DESCRIPTORS
                for b in _GENERIC_DESCRIPTORS | _CLASSIFIER_SUFFIXES
            )
        }

    # Score ALL columns — both standard and non-standard.
    # Non-standard columns get a head-start bonus so they win over standard
    # markers unless the standard marker is clearly a better textual match.
    best_col, best_score = None, 0.0
    for col in columns:
        ctoks = _col_base_tokens(col)
        non_skip = ctoks - _SKIP_NAMES
        if not non_skip:
            continue

        is_std = _is_standard_marker(col)

        # ---- Base score ----
        score = float(len(desc_tokens & ctoks))

        # Non-standard columns get a head-start: we prefer novel markers.
        if not is_std:
            score += 0.5

        # ---- Classifier-suffix penalty ----
        # Penalise if the LAST part is a classifier (e.g. "Tumour_type").
        if _last_part(col) in _CLASSIFIER_SUFFIXES:
            score -= 3.0

        # ---- Classifier-prefix penalty ----
        # Penalise compound columns whose FIRST part is a classifier and whose
        # remaining part is just a context noun (e.g. "Stage_CKD", "Grade_II").
        # These are staging/grading variables, never the primary study outcome.
        _first_part = re.split(r"[\s_]+", col.lower())[0] if col else ""
        if _first_part in _CLASSIFIER_SUFFIXES and len(re.split(r"[\s_]+", col)) > 1:
            score -= 2.0

        # ---- Subject-token bonus ----
        subject_toks = _subject_tokens(non_skip)
        if subject_toks:
            if any(len(t) >= 3 and t in desc_norm for t in subject_toks):
                score += 2.0
        else:
            # Pure generic name — small penalty
            score -= 0.5

        if score > best_score:
            best_score, best_col = score, col

    # Require a meaningful score before returning
    return best_col if best_score >= 1 else None


def identify_study(
    description: str,
    outcome_hint: str,
    columns: List[str],
    classifications: Optional[List[Dict[str, Any]]] = None,
    study_type_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """Identify study type and outcome column from free-text description.

    If *study_type_hint* is provided (e.g. extracted from an uploaded proposal)
    and is a recognised type, it is used directly — the LLM is only called to
    identify the outcome column, not to re-classify the design.

    Returns:
      {
        "study_type":   str,
        "outcome_col":  str | None,
        "confidence":   float,
        "reasoning":    str,
        "all_predictors": [str, ...],   # non-id/non-excluded columns minus outcome
        "source":       "gemini" | "heuristic" | "proposal",
      }
    """
    # Normalise and validate the hint coming from the proposal parser.
    hint_type: Optional[str] = None
    if study_type_hint:
        candidate = str(study_type_hint).strip().lower()
        if candidate in _TYPE_WORDS:
            hint_type = candidate

    # OpenAI GPT-4o-mini is primary; Gemini is fallback; heuristic is last resort.
    result = None
    if description.strip() or outcome_hint.strip():
        result = _call_openai(description, outcome_hint, columns)
        log.info(
            "AI bridge OpenAI raw result: %s",
            json.dumps(result) if result else "None",
        )
        if not (result and isinstance(result, dict) and "study_type" in result):
            result = _call_gemini(description, outcome_hint, columns)
            log.info(
                "AI bridge Gemini raw result: %s",
                json.dumps(result) if result else "None",
            )

    # If the proposal already told us the study type, trust it over the LLM.
    # We still use the LLM result for outcome_col / confidence / reasoning.
    if hint_type and result and isinstance(result, dict):
        result["study_type"] = hint_type
        result["reasoning"] = (
            f"Study type '{hint_type}' taken from your uploaded proposal. "
            + str(result.get("reasoning", ""))
        )

    if result and isinstance(result, dict) and "study_type" in result:
        study_type = str(result.get("study_type") or "correlation").strip().lower()
        if study_type not in _TYPE_WORDS:
            study_type = "correlation"
        outcome_col = result.get("outcome_col")
        if outcome_col and outcome_col not in columns:
            # LLM hallucinated a column name — fall back to fuzzy
            outcome_col = _fuzzy_match_column(outcome_col, columns)
        if not outcome_col:
            outcome_col = _fuzzy_match_column(outcome_hint, columns)

        confidence = float(result.get("confidence") or 0.8)
        reasoning = str(result.get("reasoning") or "")

        # ── Override guard: if the LLM picked a standard clinical marker and
        # the user's hint did NOT explicitly name that marker, look for a
        # novel/study-specific column instead.  This prevents common mistakes
        # like selecting "PR" instead of "p27 expression" in IHC studies.
        hint_lower = outcome_hint.lower().strip()
        is_std = outcome_col and _is_standard_marker(outcome_col)
        hint_names_it = (
            hint_lower
            and outcome_col
            and (hint_lower in outcome_col.lower() or outcome_col.lower() in hint_lower)
        )
        if is_std and not hint_names_it:
            log.info(
                "Override guard: LLM chose standard marker '%s'; searching for novel column",
                outcome_col,
            )
            novel = _find_novel_marker(outcome_hint, description, columns)
            if novel and novel != outcome_col:
                old_col = outcome_col
                outcome_col = novel
                reasoning = (
                    f"Auto-corrected: '{old_col}' is a standard clinical marker "
                    f"(predictor). Switched to '{novel}' as the study-specific "
                    f"outcome variable. [{reasoning}]"
                )
                log.info("Override guard: swapped '%s' → '%s'", old_col, novel)
            else:
                log.info(
                    "Override guard: no strong novel alternative found; keeping '%s'",
                    outcome_col,
                )

        source = "gemini"
        log.info(
            "AI bridge final (LLM path): study_type=%s outcome_col=%s source=%s",
            study_type, outcome_col, source,
        )
    else:
        # Full heuristic fallback — also honour any proposal hint here
        study_type = hint_type or _detect_study_type_heuristic(description)
        outcome_col = _fuzzy_match_column(outcome_hint, columns)

        # If no outcome column found yet, try scanning the description
        # against non-standard columns (works even with an empty hint).
        if not outcome_col:
            outcome_col = _heuristic_outcome_from_description(description, columns)

        confidence = 0.7 if hint_type else (0.6 if outcome_col else 0.4)
        if hint_type:
            reasoning = (
                f"Study type '{study_type}' taken from your uploaded proposal "
                f"(AI service unavailable)."
            )
            source = "proposal"
        else:
            reasoning = (
                f"Detected study type '{study_type}' from keywords in your description."
            )
            source = "heuristic"
        log.info(
            "AI bridge final (heuristic path): study_type=%s outcome_col=%s",
            study_type, outcome_col,
        )

    # -----------------------------------------------------------------------
    # Statistician validation — override study type when the actual data
    # makes the suggestion statistically impossible or nonsensical.
    # This runs regardless of whether the type came from LLM / proposal /
    # heuristic so we never present an unrunnable analysis path.
    # -----------------------------------------------------------------------
    study_type, reasoning = _validate_study_type(
        study_type=study_type,
        outcome_col=outcome_col,
        classifications=classifications or [],
        description=description,
        reasoning=reasoning,
    )

    # Build predictor list — exclude id/date/exclude types plus the outcome
    excluded_types = {"id", "date", "exclude"}
    if classifications:
        cls_map = {c["column"]: c.get("detected_type", "") for c in classifications}
        all_predictors = [
            col for col in columns
            if col != outcome_col
            and cls_map.get(col, "nominal") not in excluded_types
        ]
    else:
        all_predictors = [col for col in columns if col != outcome_col]

    return {
        "study_type": study_type,
        "outcome_col": outcome_col,
        "confidence": round(confidence, 2),
        "reasoning": reasoning,
        "all_predictors": all_predictors,
        "source": source,
    }
