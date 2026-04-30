"""Analyse a free-text research objective to suggest a sample-size formula.

Two paths:

1. **Heuristic (always available).** Lightweight keyword/regex pattern matching
   that is good enough for clear-cut objectives ("compare A and B", "estimate
   the prevalence of …", "compare three treatments …").

2. **LLM-assisted (optional).** When ``OPENAI_API_KEY`` is configured, we ask
   the model to return a strict JSON object with the same shape as the
   heuristic. The result is validated before being returned to the frontend so
   a malformed model response can never break the calculator.

In both cases the analyser only *suggests* — the researcher can override the
study type and group count on the next step. We never compute statistics from
the LLM; numbers come exclusively from the validated formulas in
``sample_size.py``.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


VALID_FORMULAS = {
    "single_proportion",
    "single_mean",
    "two_proportions",
    "two_means",
    "paired_means",
    "anova_means",
    "repeated_measures",
    "linear_regression",
    "prediction_model",
    "kappa_agreement",
    "roc_auc",
}

VALID_OUTCOME_TYPES = {"proportion", "mean", "unknown"}
VALID_DESIGNS = {
    "descriptive",
    "comparative",
    "paired",
    "anova",
    "longitudinal",
    "regression",
    "prediction",
    "agreement",
    "diagnostic",
    "unknown",
}


@dataclass
class ObjectiveAnalysis:
    objective: str
    detected_groups: int
    outcome_type: str          # "proportion" | "mean" | "unknown"
    study_design: str          # "descriptive" | "comparative" | "paired" | "anova" | "unknown"
    suggested_formula: str     # one of VALID_FORMULAS
    confidence: str            # "high" | "medium" | "low"
    rationale: str
    source: str                # "heuristic" | "llm" | "llm+heuristic_fallback"
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Heuristic
# ---------------------------------------------------------------------------


_PAIRED_KEYWORDS = re.compile(
    r"\b(pre[ -]?post|before[ -]and[ -]after|paired|matched|same\s+(patients?|subjects?|"
    r"participants?))\b",
    re.IGNORECASE,
)
_THREE_PLUS_HINTS = re.compile(
    r"\b(three|four|five|six|seven|eight|nine|ten|multiple|several|"
    r"\d+\s*(arms?|groups?|treatments?|interventions?|regimens?|cohorts?))\b",
    re.IGNORECASE,
)
_TWO_GROUP_HINTS = re.compile(
    r"\b(compare|comparison|versus|vs\.?|between\s+(two|2)\s+groups?|"
    r"(case[ -]control|treatment\s+(vs|versus|and)\s+control|intervention\s+"
    r"(vs|versus|and)\s+control)|"
    # two-arm RCT / 2-arm trial / two arms
    r"(two|2)[ -]arm(ed)?(\s+(rct|trial|study|design))?|"
    r"two\s+arms)\b",
    re.IGNORECASE,
)
_DESCRIPTIVE_HINTS = re.compile(
    r"\b(prevalence|incidence|proportion\s+of|estimate\s+the|describe|"
    r"frequency\s+of|determine\s+the\s+(rate|prevalence|incidence|proportion))\b",
    re.IGNORECASE,
)
_PROPORTION_OUTCOME = re.compile(
    r"\b(rate|prevalence|incidence|proportion|percentage|risk|odds|"
    r"recovery\s+rate|cure\s+rate|mortality|positivity)\b",
    re.IGNORECASE,
)
_MEAN_OUTCOME = re.compile(
    r"\b(mean|average|score|level|concentration|pressure|height|weight|"
    r"bmi|hba1c|cholesterol|reduction\s+in|change\s+in)\b",
    re.IGNORECASE,
)
# Longitudinal / repeated-measures: multiple timepoints per subject.
_LONGITUDINAL_HINTS = re.compile(
    r"\b(longitudinal|repeated[ -]?measures?|over\s+time|across\s+time|"
    r"multiple\s+timepoints?|repeated\s+visits?|follow[ -]?up\s+(at|over)|"
    r"timepoints?|trajector(y|ies)|"
    # "across N (monthly|weekly|...) visits/measurements/assessments/follow-ups"
    r"(across|over|at)\s+\d+\s+(daily|weekly|monthly|quarterly|annual|yearly|"
    r"baseline|consecutive)?\s*"
    r"(visits?|measurements?|assessments?|time[ -]?points?|follow[ -]?ups?|months?|weeks?|years?))\b",
    re.IGNORECASE,
)
# Linear / multiple regression context.
_REGRESSION_HINTS = re.compile(
    r"\b(linear\s+regression|multiple\s+regression|multivariable\s+regression|"
    r"regression\s+(model|analysis)|associat(ion|ed)\s+between|"
    r"predictors?\s+of(?!\s+(survival|outcome\s+in\s+a\s+prediction))|"
    r"explain\s+variance|r[ -]?squared|r²)\b",
    re.IGNORECASE,
)
# Clinical-prediction / diagnostic-prediction model.
_PREDICTION_HINTS = re.compile(
    r"\b(prediction\s+model|predictive\s+model|risk\s+(score|model|prediction)|"
    r"prognostic\s+model|clinical\s+prediction\s+rule|nomogram|"
    r"events?\s+per\s+variable|epv)\b",
    re.IGNORECASE,
)
# Inter-/intra-rater agreement (kappa).
_AGREEMENT_HINTS = re.compile(
    r"\b(inter[ -]?rater|intra[ -]?rater|inter[ -]?observer|intra[ -]?observer|"
    r"kappa|cohen'?s\s+k|agreement\s+between|concordance|reliability\s+of\s+"
    r"(rat(ing|er)s?|observer|measurement))\b",
    re.IGNORECASE,
)
# Diagnostic test accuracy / ROC / AUC.
_ROC_HINTS = re.compile(
    r"\b(roc(\s+curve)?|auc|c[ -]?statistic|diagnostic\s+(test|accuracy)|"
    r"sensitivity\s+and\s+specificity|discrimination\s+of\s+(a|the)\s+test|"
    r"area\s+under\s+the\s+curve)\b",
    re.IGNORECASE,
)


def _extract_group_count(text: str) -> Optional[int]:
    word_to_num = {
        "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    # "3 groups", "4 arms", "5 regimens"
    m = re.search(
        r"(\d+)\s*(arms?|groups?|treatments?|interventions?|regimens?|cohorts?)",
        text, re.IGNORECASE,
    )
    if m:
        return int(m.group(1))
    # "three groups", "four arms", "three regimens"
    m = re.search(
        r"\b(two|three|four|five|six|seven|eight|nine|ten)\s+"
        r"(arms?|groups?|treatments?|interventions?|regimens?|cohorts?)\b",
        text, re.IGNORECASE,
    )
    if m:
        return word_to_num[m.group(1).lower()]
    return None


def _detect_outcome(text: str) -> str:
    if _PROPORTION_OUTCOME.search(text):
        return "proportion"
    if _MEAN_OUTCOME.search(text):
        return "mean"
    return "unknown"


def heuristic_analyze(objective: str) -> ObjectiveAnalysis:
    text = objective.strip()
    warnings: List[str] = []

    explicit_count = _extract_group_count(text)
    is_paired = bool(_PAIRED_KEYWORDS.search(text))
    is_descriptive = bool(_DESCRIPTIVE_HINTS.search(text)) and not _TWO_GROUP_HINTS.search(text)
    is_two_group = bool(_TWO_GROUP_HINTS.search(text))
    is_anova_hint = bool(_THREE_PLUS_HINTS.search(text))
    is_longitudinal = bool(_LONGITUDINAL_HINTS.search(text))
    is_regression = bool(_REGRESSION_HINTS.search(text))
    is_prediction = bool(_PREDICTION_HINTS.search(text))
    is_agreement = bool(_AGREEMENT_HINTS.search(text))
    is_roc = bool(_ROC_HINTS.search(text))
    outcome = _detect_outcome(text)

    # Specialised designs win over generic comparison/descriptive paths.
    # Order matters: prediction & ROC mention "predictors"/"diagnostic"
    # which can also trigger regression/two-group, so we check them first.
    if is_roc:
        return ObjectiveAnalysis(
            objective=text,
            detected_groups=1,
            outcome_type="proportion",
            study_design="diagnostic",
            suggested_formula="roc_auc",
            confidence="high",
            rationale="Detected diagnostic-test / ROC / AUC wording.",
            source="heuristic",
            warnings=warnings,
        )
    if is_prediction:
        return ObjectiveAnalysis(
            objective=text,
            detected_groups=1,
            outcome_type="proportion",
            study_design="prediction",
            suggested_formula="prediction_model",
            confidence="high",
            rationale="Detected clinical-prediction / risk-model wording.",
            source="heuristic",
            warnings=warnings,
        )
    if is_agreement:
        return ObjectiveAnalysis(
            objective=text,
            detected_groups=1,
            outcome_type="proportion",
            study_design="agreement",
            suggested_formula="kappa_agreement",
            confidence="high",
            rationale="Detected inter-rater agreement / κ wording.",
            source="heuristic",
            warnings=warnings,
        )
    # Longitudinal repeated_measures is a 2-GROUP design — only route here
    # when the objective gives explicit evidence of two groups. Single-cohort
    # longitudinal studies fall through to single_mean / single_proportion.
    if is_longitudinal and (is_two_group or explicit_count == 2):
        groups = explicit_count if explicit_count == 2 else 2
        if outcome == "proportion":
            warnings.append(
                "Longitudinal calculator currently supports continuous "
                "outcomes (means). Confirm a mean-based outcome or override."
            )
        return ObjectiveAnalysis(
            objective=text,
            detected_groups=groups,
            outcome_type="mean",
            study_design="longitudinal",
            suggested_formula="repeated_measures",
            confidence="high" if not warnings else "medium",
            rationale="Detected longitudinal / repeated-measures design across timepoints.",
            source="heuristic",
            warnings=warnings,
        )
    if is_regression and not is_two_group and not is_anova_hint:
        return ObjectiveAnalysis(
            objective=text,
            detected_groups=1,
            outcome_type="mean",
            study_design="regression",
            suggested_formula="linear_regression",
            confidence="high",
            rationale="Detected regression / multivariable-association wording.",
            source="heuristic",
            warnings=warnings,
        )

    # Resolve the design / group count.
    if is_paired:
        groups = 1
        design = "paired"
        formula = "paired_means"
        if outcome != "mean":
            warnings.append(
                "Paired design assumed continuous outcome (paired-means formula). "
                "Override if your outcome is binary."
            )
            outcome = "mean"
    elif (explicit_count and explicit_count >= 3) or is_anova_hint:
        # A ≥3-group signal always wins over a generic "compare" hint:
        # "compare three regimens" is unambiguously ANOVA.
        groups = explicit_count if (explicit_count and explicit_count >= 3) else 3
        design = "anova"
        formula = "anova_means"
        if outcome == "proportion":
            warnings.append(
                "Detected ≥3 groups with a proportion outcome — the calculator "
                "currently supports k-group ANOVA on means only."
            )
        outcome = "mean"
    elif is_two_group or (explicit_count == 2):
        groups = 2
        design = "comparative"
        if outcome == "proportion":
            formula = "two_proportions"
        elif outcome == "mean":
            formula = "two_means"
        else:
            formula = "two_means"
            warnings.append(
                "Outcome type unclear — defaulting to means. Switch to "
                "two-proportions if your outcome is binary (e.g., cured / not "
                "cured)."
            )
            outcome = "mean"
    elif is_descriptive or explicit_count == 1:
        groups = 1
        design = "descriptive"
        if outcome == "mean":
            formula = "single_mean"
        else:
            formula = "single_proportion"
            outcome = "proportion"
    else:
        # Could not classify confidently.
        groups = 1
        design = "unknown"
        formula = "single_proportion"
        outcome = outcome if outcome in {"proportion", "mean"} else "unknown"
        warnings.append(
            "Could not detect study design from the objective text. Please "
            "select the design and outcome manually."
        )

    confidence = "high"
    if "unknown" in {design, outcome} or warnings:
        confidence = "low" if design == "unknown" else "medium"

    # Build a rationale that matches the actual decision (not every signal
    # that fired during scanning).
    rationale_parts = []
    if design == "paired":
        rationale_parts.append("Detected paired / before–after wording.")
    elif design == "anova":
        if explicit_count and explicit_count >= 3:
            rationale_parts.append(f"Found explicit group count: {explicit_count}.")
        else:
            rationale_parts.append("Detected ≥3 groups / multiple treatments.")
    elif design == "comparative":
        if explicit_count == 2:
            rationale_parts.append("Found explicit group count: 2.")
        else:
            rationale_parts.append("Detected comparison between two groups.")
    elif design == "descriptive":
        rationale_parts.append("Detected descriptive (prevalence/proportion) wording.")

    if outcome == "proportion":
        rationale_parts.append("Outcome wording suggests a proportion / rate.")
    elif outcome == "mean":
        rationale_parts.append("Outcome wording suggests a continuous mean.")
    rationale = " ".join(rationale_parts) or "No strong signals found in the objective text."

    return ObjectiveAnalysis(
        objective=text,
        detected_groups=groups,
        outcome_type=outcome,
        study_design=design,
        suggested_formula=formula,
        confidence=confidence,
        rationale=rationale,
        source="heuristic",
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


_LLM_SYSTEM_PROMPT = (
    "You are a biostatistics assistant for a medical-research platform. "
    "Given a researcher's objective, identify the most appropriate sample-size "
    "formula. Return STRICT JSON only — no prose, no markdown."
)

_LLM_INSTRUCTIONS = """\
Return a JSON object with exactly these keys:

- detected_groups: integer number of comparison groups in the study
  (1 for single-sample/prevalence/paired/regression/prediction/agreement/
  diagnostic, 2 for two-arm or two-group longitudinal, ≥3 for ANOVA)
- outcome_type: one of "proportion", "mean", "unknown"
- study_design: one of "descriptive", "comparative", "paired", "anova",
  "longitudinal", "regression", "prediction", "agreement", "diagnostic",
  "unknown"
- suggested_formula: one of:
    "single_proportion", "single_mean", "two_proportions",
    "two_means", "paired_means", "anova_means",
    "repeated_measures", "linear_regression", "prediction_model",
    "kappa_agreement", "roc_auc"
- confidence: "high" | "medium" | "low"
- rationale: one short sentence explaining the choice.

Decision guidance:
- "Estimate prevalence of X" → single_proportion
- "Estimate mean X in population" → single_mean
- "Compare two proportions/rates between A and B" → two_proportions
- "Compare two means/scores between A and B" → two_means
- "Pre vs post / before vs after / matched pairs" → paired_means
- "Compare 3 or more groups" → anova_means
- "Two groups followed over time / multiple timepoints / longitudinal /
   trajectory" → repeated_measures
- "Multiple/multivariable linear regression / association of several
   predictors with a continuous outcome / R²" → linear_regression
- "Develop / validate a clinical prediction model / risk score / EPV /
   prognostic model" → prediction_model
- "Inter-rater / intra-rater agreement / Cohen's κ / concordance between
   raters" → kappa_agreement
- "Diagnostic test accuracy / sensitivity & specificity / AUC / ROC /
   c-statistic" → roc_auc

Output JSON only. No markdown. No commentary.
"""


def _llm_analyze(objective: str) -> Optional[ObjectiveAnalysis]:
    if not settings.has_openai:
        return None
    try:
        # Imported lazily so the app starts even if `openai` is missing.
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"{_LLM_INSTRUCTIONS}\n\nObjective:\n{objective.strip()}",
                },
            ],
            temperature=0.1,
            max_tokens=400,
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
    except Exception as exc:  # pragma: no cover — network/parse failures
        log.warning("objective_analyzer.llm_failed", extra={"error": type(exc).__name__})
        return None

    # Validate shape.
    try:
        groups = int(data["detected_groups"])
        outcome = str(data["outcome_type"])
        design = str(data["study_design"])
        formula = str(data["suggested_formula"])
        confidence = str(data.get("confidence", "medium"))
        rationale = str(data.get("rationale", ""))
    except (KeyError, TypeError, ValueError):
        log.warning("objective_analyzer.llm_bad_shape")
        return None

    if (
        formula not in VALID_FORMULAS
        or outcome not in VALID_OUTCOME_TYPES
        or design not in VALID_DESIGNS
        or groups < 1
        or confidence not in {"high", "medium", "low"}
    ):
        log.warning("objective_analyzer.llm_bad_values")
        return None

    return ObjectiveAnalysis(
        objective=objective.strip(),
        detected_groups=groups,
        outcome_type=outcome,
        study_design=design,
        suggested_formula=formula,
        confidence=confidence,
        rationale=rationale or "Suggested by language model.",
        source="llm",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def analyze_objective(objective: str) -> ObjectiveAnalysis:
    """Run the LLM if available, otherwise fall back to the heuristic."""
    if not objective or not objective.strip():
        raise ValueError("Objective text is empty.")
    if len(objective) > 4000:
        raise ValueError("Objective text is too long (max 4000 characters).")

    llm_result = _llm_analyze(objective)
    if llm_result:
        return llm_result
    result = heuristic_analyze(objective)
    if settings.has_openai:
        # LLM was attempted but failed validation/network — note the fallback.
        result.source = "llm+heuristic_fallback"
        result.warnings.append(
            "Language-model classification was unavailable; falling back to "
            "rule-based analysis."
        )
    return result
