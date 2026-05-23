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
_TYPE_WORDS: Dict[str, List[str]] = {
    "correlation": [
        "correlat", "associat", "relat", "factor", "predictor", "risk factor",
        "effect of", "influence of", "impact of", "relate to", "related to",
        "regression", "logistic", "linear model",
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
            # Gemini hallucinated a column name — fall back to fuzzy
            outcome_col = _fuzzy_match_column(outcome_col, columns)
        if not outcome_col:
            outcome_col = _fuzzy_match_column(outcome_hint, columns)
        confidence = float(result.get("confidence") or 0.8)
        reasoning = str(result.get("reasoning") or "")
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
