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
import os
import re
from typing import Any, Dict, List, Optional

import httpx


_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/gemini-2.0-flash:generateContent"
)
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
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
        # Study designs that are inherently group-comparison
        "retrospective", "prospective", "cohort", "case.control", "case control",
        "case-control", "randomis", "randomiz", "rct", "controlled trial",
        "observational", "longitudinal",
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
    Returns the best candidate, or None if nothing better is found.
    """
    non_standard = [c for c in columns if not _is_standard_marker(c)]
    if not non_standard:
        return None

    # 1. Direct fuzzy match on the non-standard subset
    match = _fuzzy_match_column(hint, non_standard)
    if match:
        return match

    # 2. Token-scan the description against non-standard column names
    desc_tokens = set(re.split(r"[\s,;./\-()]+", description.lower()))
    desc_tokens = {t for t in desc_tokens if len(t) >= 3}
    best_col, best_score = None, 0
    for col in non_standard:
        col_tokens = set(re.split(r"[\s_/\\.,-]+", col.lower()))
        score = len(desc_tokens & col_tokens)
        if score > best_score:
            best_score, best_col = score, col
    if best_col:
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
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
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
            _OPENAI_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
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
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
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

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 256},
    }
    try:
        resp = httpx.post(
            f"{_GEMINI_URL}?key={api_key}",
            json=payload,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        # Strip markdown code fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
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

    Rules applied in order:
    1. "diagnostic" without any continuous variable → downgrade.
    2. "survival" without any date/time variable → downgrade.
    3. "comparison" with no usable categorical grouping variable → "correlation".
    All other combinations are left unchanged.
    """
    dl = description.lower()

    # Build sets of detected types from the actual dataset
    type_counts: Dict[str, int] = {}
    for c in classifications:
        t = c.get("detected_type", "nominal")
        type_counts[t] = type_counts.get(t, 0) + 1

    has_continuous = type_counts.get("scale", 0) > 0
    has_date       = type_counts.get("date", 0) > 0

    # Also treat a column whose name contains time-fragment as a date proxy
    all_col_names = [c.get("column", "").lower() for c in classifications]
    has_time_col  = any(
        frag in col for col in all_col_names for frag in _TIME_COL_FRAGMENTS
    )

    # ── Rule 0: "correlation" with no continuous variables → "association" ─
    # "Correlation" (Pearson/Spearman) requires continuous measurements.
    # When all variables are categorical, the correct term is "association"
    # (chi-square / Fisher's exact / Cramér's V / odds ratio).
    if study_type == "correlation" and not has_continuous:
        note = (
            "'Correlation' (Pearson/Spearman) requires continuous measurements — "
            "your dataset has no continuous variables. "
            "Switched to 'association' (chi-square / Fisher's exact / Cramér's V / "
            "odds ratio), which is the correct analysis for categorical data."
        )
        return "association", f"{note} [{reasoning}]"

    # ── Rule 1: Diagnostic needs a continuous score ───────────────────────
    if study_type == "diagnostic" and not has_continuous:
        explicitly_diagnostic = any(kw in dl for kw in _DIAGNOSTIC_EXPLICIT)
        if not explicitly_diagnostic:
            # Downgrade: binary/nominal outcome → comparison; else correlation
            outcome_type = ""
            if outcome_col:
                for c in classifications:
                    if c.get("column") == outcome_col:
                        outcome_type = c.get("detected_type", "")
                        break
            if outcome_type in ("nominal", "binary", "ordinal") or not outcome_type:
                new_type = "comparison"
                note = (
                    "Diagnostic accuracy tests require a continuous test score "
                    "for AUC/ROC — your dataset has no continuous variables. "
                    "Switched to 'comparison' (chi-square / logistic regression) "
                    "which is appropriate for categorical data."
                )
            else:
                new_type = "correlation"
                note = (
                    "Diagnostic accuracy tests require a continuous test score "
                    "for AUC/ROC — your dataset has no continuous variables. "
                    "Switched to 'correlation' (association analysis)."
                )
            return new_type, f"{note} [{reasoning}]"

    # ── Rule 2: Survival needs a date or time-to-event variable ──────────
    if study_type == "survival" and not has_date and not has_time_col:
        # Only override if description also doesn't scream survival
        survival_explicit = any(
            kw in dl for kw in ("kaplan", "time to event", "time-to-event",
                                "censored", "hazard ratio", "cox")
        )
        if not survival_explicit:
            note = (
                "Survival/time-to-event analysis needs a date or time column "
                "— none was found in your dataset. "
                "Switched to 'comparison' (group difference analysis)."
            )
            return "comparison", f"{note} [{reasoning}]"

    # No override needed
    return study_type, reasoning


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


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
        if not (result and isinstance(result, dict) and "study_type" in result):
            result = _call_gemini(description, outcome_hint, columns)

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
        if (
            outcome_col
            and _is_standard_marker(outcome_col)
            and hint_lower not in outcome_col.lower()
            and outcome_col.lower() not in hint_lower
        ):
            novel = _find_novel_marker(outcome_hint, description, columns)
            if novel and novel != outcome_col:
                old_col = outcome_col
                outcome_col = novel
                reasoning = (
                    f"Auto-corrected: '{old_col}' is a standard clinical marker "
                    f"(predictor). Switched to '{novel}' as the study-specific "
                    f"outcome variable. [{reasoning}]"
                )

        source = "gemini"
    else:
        # Full heuristic fallback — also honour any proposal hint here
        study_type = hint_type or _detect_study_type_heuristic(description)
        outcome_col = _fuzzy_match_column(outcome_hint, columns)
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
