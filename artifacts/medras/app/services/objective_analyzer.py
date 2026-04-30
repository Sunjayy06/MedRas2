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
    "correlation",
    "repeated_measures_anova",
    "survival_logrank",
}

VALID_OUTCOME_TYPES = {"proportion", "mean", "time_to_event", "unknown"}
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
    "correlation",
    "survival",
    "qualitative",
    "unknown",
}

# "auto" = let the heuristic decide; the rest are explicit overrides.
VALID_STUDY_TYPES = {
    "auto",
    "quantitative",
    "qualitative",
    "focus_group",
    "pilot",
    "questionnaire",
    "in_vitro",
    "in_vivo",
}


@dataclass
class ObjectiveAnalysis:
    objective: str
    detected_groups: int
    outcome_type: str          # "proportion" | "mean" | "time_to_event" | "unknown"
    study_design: str          # one of VALID_DESIGNS
    suggested_formula: str     # one of VALID_FORMULAS, or "" for non-formulaic types
    confidence: str            # "high" | "medium" | "low"
    rationale: str
    source: str                # "heuristic" | "llm" | "llm+heuristic_fallback"
    study_type: str = "quantitative"   # one of VALID_STUDY_TYPES (excluding "auto")
    suggested_dropout: float = 0.0     # 0.0 – 0.30 — heuristic recommendation
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
# Pearson correlation (continuous–continuous association, no causal claim).
_CORRELATION_HINTS = re.compile(
    r"\b(pearson\s+correlation|spearman\s+correlation|"
    r"correlat(e|ed|ion|ions)\s+(between|with|of)|"
    r"(strength|degree)\s+of\s+(the\s+)?association|"
    r"linear\s+correlation|fisher'?s\s+z|"
    r"correlation\s+coefficient)\b",
    re.IGNORECASE,
)
# Repeated-measures ANOVA (k groups × m timepoints, mixed design).
_RM_ANOVA_HINTS = re.compile(
    r"\b(repeated[ -]?measures\s+anova|rm[ -]?anova|"
    r"mixed[ -]?design\s+anova|"
    r"(group|arm)\s*(\u00d7|x|by)\s*time(\s+interaction)?|"
    r"time\s*(\u00d7|x|by)\s*(group|treatment|arm)(\s+interaction)?|"
    r"three[ -]?way\s+anova\s+with\s+repeated\s+measures)\b",
    re.IGNORECASE,
)
# Survival analysis / log-rank / time-to-event / hazard ratio.
_SURVIVAL_HINTS = re.compile(
    r"\b(survival\s+(analysis|study|curve|time)|log[ -]?rank|"
    r"time[ -]?to[ -]?event|time\s+to\s+(death|recurrence|progression|failure)|"
    r"hazard\s+ratio|kaplan[ -]?meier|"
    r"overall\s+survival|progression[ -]?free\s+survival|disease[ -]?free\s+survival|"
    r"censored?\s+(data|outcome|event))\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Study-type detection (qualitative, FGD, pilot, questionnaire, in-vitro/vivo)
# ---------------------------------------------------------------------------

_QUALITATIVE_HINTS = re.compile(
    r"\b(qualitative\s+(study|research|interview)|"
    r"in[ -]?depth\s+interview|semi[ -]?structured\s+interview|"
    r"thematic\s+analysis|grounded\s+theory|phenomenolog(y|ical)|"
    r"narrative\s+analysis|ethnograph(y|ic)|"
    r"lived\s+experience|saturation)\b",
    re.IGNORECASE,
)
_FGD_HINTS = re.compile(
    r"\b(focus[ -]?group(s)?(\s+discussion)?|fgd|nominal\s+group)\b",
    re.IGNORECASE,
)
_PILOT_HINTS = re.compile(
    r"\b(pilot\s+(study|trial|test)|feasibility\s+(study|trial)|"
    r"proof[ -]?of[ -]?concept(\s+study)?)\b",
    re.IGNORECASE,
)
_QUESTIONNAIRE_HINTS = re.compile(
    r"\b(questionnaire(\s+based)?\s+(study|survey)?|"
    r"\bsurvey(\s+study|\s+based)?\b|"
    r"kap\s+(study|survey)|knowledge[, ]?\s*attitude(s)?\s*(and\s+)?"
    r"practice(s)?(\s+(study|survey))?|"
    r"household\s+survey|cross[ -]?sectional\s+survey)\b",
    re.IGNORECASE,
)
_IN_VITRO_HINTS = re.compile(
    r"\b(in[ -]?vitro|cell\s+culture|cell[ -]?line|"
    r"laboratory\s+experiment|petri\s+dish|"
    r"biological\s+replicates?)\b",
    re.IGNORECASE,
)
_IN_VIVO_HINTS = re.compile(
    r"\b(in[ -]?vivo|animal\s+(study|model|experiment)|"
    r"mouse\s+model|murine\s+model|rat\s+model|rodent\s+model|"
    r"\bzebrafish\b|preclinical\s+(study|model))\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Smart-dropout heuristic — which study designs warrant attrition padding?
# ---------------------------------------------------------------------------

# Designs that follow subjects over time (RCT / cohort / longitudinal / FU).
_DROPOUT_LONG_HINTS = re.compile(
    r"\b(randomi[sz]ed\s+controlled\s+trial|\brct\b|"
    r"phase\s+(i{1,3}|iv|[1-4])(\s+(trial|study))?|"
    r"longitudinal|cohort\s+study|prospective\s+cohort|"
    r"follow[ -]?up\s+(at|over|for)|"
    r"\d+[ -]?(week|month|year)\s+follow[ -]?up|"
    r"intervention\s+(study|trial))\b",
    re.IGNORECASE,
)
# Designs that complete in a single visit / archive — no attrition.
_DROPOUT_NONE_HINTS = re.compile(
    r"\b(cross[ -]?sectional|retrospective|chart\s+review|"
    r"record\s+review|archival|registry\s+(study|analysis)|"
    r"single[ -]?visit|case\s+series|secondary\s+analysis)\b",
    re.IGNORECASE,
)


def _suggest_dropout(text: str, study_type: str, design: str) -> float:
    """Heuristic recommendation for the dropout adjustment.

    Returns 0.0 (no padding), 0.10, or 0.15 depending on study design.
    The user can always override on Step 2.
    """
    if study_type in {"qualitative", "focus_group", "in_vitro", "questionnaire"}:
        return 0.0
    if _DROPOUT_NONE_HINTS.search(text):
        return 0.0
    if design in {"survival", "longitudinal"}:
        return 0.15
    if _DROPOUT_LONG_HINTS.search(text):
        return 0.10
    if study_type == "in_vivo":
        return 0.10
    return 0.0


def _detect_study_type(text: str) -> Optional[str]:
    """Return a non-quantitative study type if matched, else None."""
    if _FGD_HINTS.search(text):
        return "focus_group"
    if _QUALITATIVE_HINTS.search(text):
        return "qualitative"
    if _PILOT_HINTS.search(text):
        return "pilot"
    if _QUESTIONNAIRE_HINTS.search(text):
        return "questionnaire"
    if _IN_VITRO_HINTS.search(text):
        return "in_vitro"
    if _IN_VIVO_HINTS.search(text):
        return "in_vivo"
    return None


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


def _heuristic_classify(objective: str) -> ObjectiveAnalysis:
    """Inner heuristic — determines design + formula, not study_type/dropout."""
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
    is_survival = bool(_SURVIVAL_HINTS.search(text))
    is_rm_anova = bool(_RM_ANOVA_HINTS.search(text))
    is_correlation = bool(_CORRELATION_HINTS.search(text))
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
    if is_survival:
        groups = 2 if (is_two_group or explicit_count == 2) else 2
        return ObjectiveAnalysis(
            objective=text,
            detected_groups=groups,
            outcome_type="time_to_event",
            study_design="survival",
            suggested_formula="survival_logrank",
            confidence="high",
            rationale="Detected survival / time-to-event / hazard-ratio wording.",
            source="heuristic",
            warnings=warnings,
        )
    if is_rm_anova:
        groups = explicit_count if (explicit_count and explicit_count >= 2) else 2
        return ObjectiveAnalysis(
            objective=text,
            detected_groups=groups,
            outcome_type="mean",
            study_design="longitudinal",
            suggested_formula="repeated_measures_anova",
            confidence="high",
            rationale=(
                "Detected repeated-measures ANOVA wording "
                "(group × time interaction across multiple timepoints)."
            ),
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
    if is_correlation and not is_two_group and not is_anova_hint:
        return ObjectiveAnalysis(
            objective=text,
            detected_groups=1,
            outcome_type="mean",
            study_design="correlation",
            suggested_formula="correlation",
            confidence="high",
            rationale="Detected Pearson/Spearman correlation wording.",
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
# Public heuristic wrapper — adds study_type + suggested_dropout
# ---------------------------------------------------------------------------


def heuristic_analyze(objective: str) -> ObjectiveAnalysis:
    """Heuristic with study-type + dropout augmentation.

    Special non-formulaic study types (qualitative, focus_group, pilot,
    questionnaire) short-circuit the formula classifier and return a
    ``study_design`` of "qualitative" / "descriptive" with an empty
    ``suggested_formula``. Frontend reads ``study_type`` and shows the
    built-in recommendation panel from ``STUDY_TYPE_RECOMMENDATIONS``.
    """
    text = objective.strip()
    detected_type = _detect_study_type(text)

    # ── Non-formulaic study types: route to the recommendations panel ──
    if detected_type == "qualitative":
        return ObjectiveAnalysis(
            objective=text,
            detected_groups=1,
            outcome_type="unknown",
            study_design="qualitative",
            suggested_formula="",
            confidence="high",
            rationale=(
                "Detected qualitative-research wording — sample size is "
                "judged by thematic saturation, not a power calculation."
            ),
            source="heuristic",
            study_type="qualitative",
            suggested_dropout=0.0,
        )
    if detected_type == "focus_group":
        return ObjectiveAnalysis(
            objective=text,
            detected_groups=1,
            outcome_type="unknown",
            study_design="qualitative",
            suggested_formula="",
            confidence="high",
            rationale="Detected focus-group / FGD wording.",
            source="heuristic",
            study_type="focus_group",
            suggested_dropout=0.0,
        )
    if detected_type == "pilot":
        return ObjectiveAnalysis(
            objective=text,
            detected_groups=1,
            outcome_type="unknown",
            study_design="descriptive",
            suggested_formula="",
            confidence="high",
            rationale=(
                "Detected pilot / feasibility study — recommend ~25 "
                "participants for SD estimation; do not power for effect."
            ),
            source="heuristic",
            study_type="pilot",
            suggested_dropout=0.0,
        )
    if detected_type == "questionnaire":
        # Questionnaire / KAP surveys: route to the recommendation panel
        # (Cochran n ≈ 384). The user can still drop into single_proportion
        # via "Open the calculator manually" if they have a known prevalence.
        return ObjectiveAnalysis(
            objective=text,
            detected_groups=1,
            outcome_type="proportion",
            study_design="descriptive",
            suggested_formula="",
            confidence="high",
            rationale=(
                "Detected questionnaire / KAP-style survey — recommend "
                "n ≈ 384 (Cochran, p=0.5, d=±5%, 95% CI). Refine with a "
                "known prevalence using single_proportion if available."
            ),
            source="heuristic",
            study_type="questionnaire",
            suggested_dropout=0.0,
        )

    # ── Otherwise, run the formula classifier and augment ──
    result = _heuristic_classify(text)

    # Force study_type for in-vitro/in-vivo (these still use a formula).
    if detected_type == "in_vitro":
        result.study_type = "in_vitro"
    elif detected_type == "in_vivo":
        result.study_type = "in_vivo"
    else:
        result.study_type = "quantitative"

    result.suggested_dropout = _suggest_dropout(text, result.study_type, result.study_design)
    return result


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

- detected_groups: integer number of comparison groups
- outcome_type: one of "proportion", "mean", "time_to_event", "unknown"
- study_design: one of "descriptive", "comparative", "paired", "anova",
  "longitudinal", "regression", "prediction", "agreement", "diagnostic",
  "correlation", "survival", "qualitative", "unknown"
- suggested_formula: one of:
    "single_proportion", "single_mean", "two_proportions",
    "two_means", "paired_means", "anova_means",
    "repeated_measures", "linear_regression", "prediction_model",
    "kappa_agreement", "roc_auc",
    "correlation", "repeated_measures_anova", "survival_logrank"
- confidence: "high" | "medium" | "low"
- rationale: one short sentence explaining the choice.
- study_type: one of "quantitative", "qualitative", "focus_group",
  "pilot", "questionnaire", "in_vitro", "in_vivo"
  (default to "quantitative" unless wording clearly indicates otherwise)
- suggested_dropout: number in [0, 0.30] — 0.0 for cross-sectional /
  retrospective / in-vitro / qualitative; 0.10 for short-term RCTs and
  cohorts; 0.15 for long-term follow-up or survival studies.

Decision guidance:
- "Estimate prevalence of X" → single_proportion
- "Estimate mean X in population" → single_mean
- "Compare two proportions/rates" → two_proportions
- "Compare two means/scores" → two_means
- "Pre vs post / before vs after / matched pairs" → paired_means
- "Compare 3 or more groups (means)" → anova_means
- "Two groups followed over time" → repeated_measures
- "Group × time interaction / RM-ANOVA / mixed-design ANOVA" →
   repeated_measures_anova
- "Multivariable linear regression / R² / multiple predictors of a
   continuous outcome" → linear_regression
- "Pearson / Spearman correlation between two continuous variables" →
   correlation
- "Develop / validate a clinical prediction model / risk score / EPV" →
   prediction_model
- "Inter-rater / intra-rater agreement / Cohen's κ / concordance" →
   kappa_agreement
- "Diagnostic test accuracy / sensitivity & specificity / AUC / ROC" →
   roc_auc
- "Survival / time-to-event / hazard ratio / log-rank / Kaplan-Meier" →
   survival_logrank
- "Qualitative interviews / FGD / pilot / KAP / questionnaire survey" →
   set study_type accordingly; suggested_formula must be "" for
   qualitative / focus_group / pilot / questionnaire (these route to a
   built-in recommendation panel, not a power calculation).

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
            max_tokens=500,
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
        formula = str(data.get("suggested_formula") or "")
        confidence = str(data.get("confidence", "medium"))
        rationale = str(data.get("rationale", ""))
        study_type = str(data.get("study_type", "quantitative"))
        try:
            suggested_dropout = float(data.get("suggested_dropout", 0.0))
        except (TypeError, ValueError):
            suggested_dropout = 0.0
    except (KeyError, TypeError, ValueError):
        log.warning("objective_analyzer.llm_bad_shape")
        return None

    if (
        (formula and formula not in VALID_FORMULAS)
        or outcome not in VALID_OUTCOME_TYPES
        or design not in VALID_DESIGNS
        or groups < 1
        or confidence not in {"high", "medium", "low"}
        or study_type not in VALID_STUDY_TYPES
        or study_type == "auto"
    ):
        log.warning("objective_analyzer.llm_bad_values")
        return None

    suggested_dropout = max(0.0, min(0.30, suggested_dropout))

    return ObjectiveAnalysis(
        objective=objective.strip(),
        detected_groups=groups,
        outcome_type=outcome,
        study_design=design,
        suggested_formula=formula,
        confidence=confidence,
        rationale=rationale or "Suggested by language model.",
        source="llm",
        study_type=study_type,
        suggested_dropout=suggested_dropout,
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
