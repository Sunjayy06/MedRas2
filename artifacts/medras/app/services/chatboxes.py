"""Rule-based explainer chatboxes for screens 5/6/7.

Per spec PART 5 (CHATBOX 2/3/4) plus FIX R9 (chatbox 3 JSON action format).

Design rules:
* Each chatbox only knows about its own screen's content.
* Chatboxes NEVER calculate. Any calculation request is refused with the
  exact spec phrase so the user understands the boundary.
* Chatbox 3 may emit an ACTION JSON (add_test / remove_test) that the
  frontend parses with the FIX R9 safety-net regex.
* Pure rule-based; no external LLM call required. The catalog of curated
  explanations covers every "what it can do" item from the spec.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


REFUSE_CALCULATION = (
    "I cannot calculate that. The statistical engine handles all calculations. "
    "I can explain what the test does or what the result means."
)

REFUSE_OVERRIDE_NORMALITY = (
    "I cannot override the normality decision. Use the override toggle on the "
    "row itself if you have a strong reason — the formal test result stands "
    "until you do."
)

REFUSE_RESULT_CHANGE = (
    "The calculations are done by our statistical engine and are validated. "
    "I can help you understand or explain them but cannot change them."
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


_CALC_PATTERNS = [
    r"\bcalcul",          # calculate, calculation
    r"\bcompute\b",
    r"\bre[\s-]?run\b",
    r"\brecalc",
    r"\bp[\s-]?value\s+(of|for)\b",
    r"\bwhat\s+is\s+the\s+p\b",
    r"\bgive\s+me\s+the\s+(p|t|f|chi|hr|or)\b",
    r"\brun\s+(the\s+)?(t-?test|anova|chi|fisher|regression|mann)",
]


def _is_calculation_request(msg: str) -> bool:
    low = msg.lower()
    return any(re.search(p, low) for p in _CALC_PATTERNS)


def _msg(text: str, role: str = "ai") -> Dict[str, Any]:
    return {"role": role, "text": text}


def _action_msg(action: str, test_id: str, reason: str = "") -> Dict[str, Any]:
    """Emit a structured action the frontend can parse via FIX R9 regex.

    The visible text always includes the JSON block so the safety-net
    regex `/\\{[\\s\\S]*"action"[\\s\\S]*\\}/` finds it. We also include a
    short prose preamble per FIX R9's `handleAIResponse` text-extraction.
    """
    verb = "Adding" if action == "add_test" else "Removing"
    payload = (
        '{"action": "' + action + '", "test_id": "' + test_id +
        '", "reason": "' + reason.replace('"', "'") + '"}'
    )
    text = f"{verb} {test_id}. {reason}\n\n{payload}"
    return {"role": "action", "text": text, "action": action, "test_id": test_id}


# ===========================================================================
# CHATBOX 2 — Normality screen
# ===========================================================================


_CB2_TOPICS: List[Tuple[List[str], str]] = [
    (
        ["non-normal", "non normal", "not normal", "skewed distribution"],
        "A non-normal distribution means the values do not form the classic bell "
        "curve. The data may be skewed (long tail on one side), have heavy tails, "
        "or be bounded. For test selection this matters because parametric tests "
        "(t-test, ANOVA, Pearson) assume normality of the outcome within each "
        "group. When normality fails we switch to a rank-based equivalent "
        "(Mann-Whitney, Kruskal-Wallis, Spearman) which makes no distributional "
        "assumption.",
    ),
    (
        ["why does it matter", "why does normality matter", "why normality"],
        "Normality matters because it decides which test we run. If the outcome "
        "is approximately normal in each group we use parametric tests (t-test, "
        "ANOVA) which have more power. If it is not, we use non-parametric tests "
        "(Mann-Whitney, Kruskal-Wallis) which are robust but slightly less "
        "powerful. Picking the wrong family can inflate false positives.",
    ),
    (
        ["qq plot", "q-q plot", "qqplot", "quantile-quantile"],
        "A QQ plot compares the quantiles of your data against the quantiles "
        "of a perfect normal distribution. If the points fall on a straight "
        "diagonal line the data is approximately normal. Curving away at the "
        "ends means heavy or light tails; an S-shape means skewness.",
    ),
    (
        ["skewness", "skew"],
        "Skewness measures asymmetry. A value near 0 is symmetric. Positive "
        "skew (right-skewed) means a long tail on the right — most values are "
        "small with a few large outliers (e.g. hospital stay length). Negative "
        "skew is the mirror image. As a thumb rule, |skew| above 1 is a "
        "noticeable departure from normality.",
    ),
    (
        ["kurtosis"],
        "Kurtosis measures tail heaviness. A normal distribution has kurtosis "
        "near 0 (excess kurtosis). Positive kurtosis means heavier tails and a "
        "sharper peak — outliers are more common. Negative kurtosis means "
        "lighter tails. |kurtosis| above 3 is a strong departure from normal.",
    ),
    (
        ["transform", "log transform", "transformation"],
        "When a positive, right-skewed variable fails normality we try a "
        "log transformation (log of the values). If the transformed values "
        "pass Shapiro-Wilk we proceed parametrically on the log scale and "
        "back-transform the means for reporting. If the transform does not "
        "fix normality we fall back to non-parametric tests on the original "
        "scale.",
    ),
    (
        ["shapiro", "shapiro-wilk", "shapiro wilk"],
        "Shapiro-Wilk is the gold-standard normality test for samples up to "
        "about 50. The null hypothesis is 'the data are normal', so a p-value "
        "below 0.05 means we reject normality.",
    ),
    (
        ["kolmogorov", "ks test", "k-s test"],
        "Kolmogorov-Smirnov compares the empirical distribution to the normal "
        "CDF. We use it for samples between 50 and 2000 because Shapiro-Wilk "
        "becomes overly sensitive at large n. Above n=2000 we rely on shape "
        "thumb-rules (skewness and kurtosis) instead because any test will "
        "flag tiny deviations as significant.",
    ),
]


def _opening_normality(context: Dict[str, Any]) -> str:
    cols = (context or {}).get("columns") or []
    n = len(cols)
    if not n:
        summary = "No scale variables to test."
    else:
        normal = sum(1 for c in cols if c.get("decision") == "normal")
        nonnormal = sum(1 for c in cols if c.get("decision") == "non_normal")
        bits = []
        if normal:
            bits.append(f"{normal} normal")
        if nonnormal:
            bits.append(f"{nonnormal} non-normal")
        insuff = n - normal - nonnormal
        if insuff:
            bits.append(f"{insuff} insufficient data")
        summary = "Tested " + str(n) + " scale variable(s): " + ", ".join(bits) + "."
    return (
        "I have completed the normality check. " + summary +
        " Ask me what any result means."
    )


def chatbox2_reply(message: str, context: Dict[str, Any]) -> Dict[str, Any]:
    msg = (message or "").strip()
    if not msg:
        return _msg("Ask me about normality results — skewness, QQ plots, why a "
                    "transformation was applied, or what 'non-normal' means.")
    low = msg.lower()
    if any(w in low for w in ("override", "change the decision", "force normal")):
        return _msg(REFUSE_OVERRIDE_NORMALITY)
    if _is_calculation_request(msg):
        return _msg(REFUSE_CALCULATION)
    # Variable-specific question? Mention the actual decision if we have it.
    cols = (context or {}).get("columns") or []
    for c in cols:
        name = c.get("column", "")
        if name and name.lower() in low:
            verdict = c.get("decision", "—")
            test = c.get("test", "—")
            p = c.get("p_value")
            p_txt = "—" if p is None else ("<0.001" if p < 0.001 else f"{p:.3f}")
            note = c.get("note") or ""
            base = (f"For '{name}' the engine ran {test} (p = {p_txt}) and "
                    f"called it {verdict.replace('_', '-')}. ")
            if c.get("decision") == "non_normal":
                base += (
                    "That means the values are not bell-shaped, so any test on "
                    "this variable will use a non-parametric equivalent."
                )
            elif c.get("decision") == "normal":
                base += "That means parametric tests (t-test, ANOVA) are appropriate."
            else:
                base += (
                    "Insufficient data — fewer than ~3 valid observations, so we "
                    "cannot reliably assess normality."
                )
            if note:
                base += f" Note: {note}"
            return _msg(base)
    for keys, answer in _CB2_TOPICS:
        if any(k in low for k in keys):
            return _msg(answer)
    return _msg(
        "I can explain non-normal distributions, why normality matters, what a "
        "QQ plot shows, skewness, kurtosis, transformations, or what the result "
        "for any specific variable means. What would you like to know?"
    )


# ===========================================================================
# CHATBOX 3 — Plan and Run screen (with FIX R9 action JSON)
# ===========================================================================


# Map natural-language test keywords to plan ids. Keys are lowercase
# fragments; first match wins. For survival we add BOTH KM and Cox via
# the multi-id form.
_TEST_ALIASES: List[Tuple[List[str], List[str], str]] = [
    (["survival", "kaplan", "log-rank", "log rank", "time to event"],
     ["pb_km", "pb_cox"],
     "Survival analysis — Kaplan-Meier curves with log-rank test, plus Cox "
     "regression for adjusted hazard ratios."),
    (["cox"], ["pb_cox"], "Cox proportional hazards regression for adjusted hazard ratios."),
    (["paired t", "paired t-test"], ["pb_paired_t"], "Paired t-test for before/after on the same subjects."),
    (["wilcoxon"], ["pb_wilcoxon"], "Wilcoxon signed-rank for paired non-normal data."),
    (["mcnemar"], ["pb_mcnemar"], "McNemar test for paired binary outcomes."),
    (["repeated measures", "rm anova", "rm-anova"], ["pb_rm_anova"], "Repeated-measures ANOVA across timepoints."),
    (["friedman"], ["pb_friedman"], "Friedman test — non-parametric repeated measures."),
    (["kappa", "agreement", "inter-rater", "interrater"], ["pb_kappa"], "Cohen's Kappa for rater agreement."),
    (["icc", "bland-altman", "bland altman"], ["pb_icc_ba"], "ICC and Bland-Altman for continuous rater agreement."),
    (["chi-square", "chi square", "chi2"], ["pb_chi_or_fisher"], "Chi-square (auto-falls-back to Fisher's exact)."),
    (["fisher"], ["pb_chi_or_fisher"], "Fisher's exact for sparse contingency tables."),
    (["mann-whitney", "mann whitney"], ["mann_whitney"], "Mann-Whitney U for two-group non-normal comparison."),
    (["kruskal"], ["kruskal_wallis"], "Kruskal-Wallis for 3+ group non-normal comparison."),
    (["anova", "one-way anova"], ["anova_oneway"], "One-way ANOVA for 3+ group means."),
    (["tukey"], ["tukey_hsd"], "Tukey HSD post-hoc after ANOVA."),
    (["t-test", "t test", "ttest", "independent t"], ["ttest_independent"], "Independent samples t-test."),
    (["ancova"], ["ancova"], "ANCOVA — covariate-adjusted mean comparison."),
    (["linear regression"], ["linear_regression"], "Linear regression for continuous outcomes."),
    (["logistic", "logistic regression"], ["logistic_regression"], "Logistic regression for binary outcomes."),
    # Generic 'regression' fallback — resolves to whichever regression is
    # actually in the plan when the user asks about "regression" alone.
    (["regression"], ["linear_regression", "logistic_regression"], "Regression analysis."),
]


_TEST_EXPLANATIONS: Dict[str, str] = {
    "ttest_independent":
        "Independent t-test compares the mean of a continuous outcome between "
        "two independent groups. Assumes normality and (with Welch's correction) "
        "no longer assumes equal variance.",
    "mann_whitney":
        "Mann-Whitney U is the non-parametric counterpart of the independent "
        "t-test. It compares the distributions/medians of two groups using "
        "ranks and makes no normality assumption.",
    "anova_oneway":
        "One-way ANOVA tests whether the means of 3 or more groups differ. A "
        "significant F-test is followed by Tukey HSD post-hoc to identify which "
        "pairs differ.",
    "kruskal_wallis":
        "Kruskal-Wallis is the non-parametric ANOVA — it compares 3+ groups "
        "without assuming normality. Significant results are followed by Dunn's "
        "post-hoc with Bonferroni correction.",
    "chi_square":
        "Chi-square tests whether two categorical variables are associated. The "
        "null is independence; a small p-value means the variables are related.",
    "pb_chi_or_fisher":
        "Smart contingency test: runs chi-square, but if any expected cell count "
        "drops below 5 it switches automatically to Fisher's exact test, which "
        "remains valid in sparse tables.",
    "linear_regression":
        "Linear regression models a continuous outcome as a linear combination "
        "of predictors. Reports adjusted R-squared, coefficients, and "
        "Breusch-Pagan / Durbin-Watson diagnostics.",
    "logistic_regression":
        "Logistic regression models a binary outcome. Reports odds ratios with "
        "95% CI plus Hosmer-Lemeshow goodness-of-fit and Nagelkerke R-squared.",
    "pb_paired_t":
        "Paired t-test compares two measurements on the same subjects (e.g. "
        "pre vs post). Assumes the differences are normally distributed.",
    "pb_wilcoxon":
        "Wilcoxon signed-rank test compares paired measurements without "
        "assuming normality of the differences.",
    "pb_mcnemar":
        "McNemar test compares paired binary outcomes — for example, did a "
        "treatment change yes/no status in the same subjects.",
    "pb_rm_anova":
        "Repeated-measures ANOVA tests for change across 3+ timepoints in the "
        "same subjects, accounting for within-subject correlation.",
    "pb_friedman":
        "Friedman test is the non-parametric repeated-measures ANOVA — it ranks "
        "values within subjects across 3+ timepoints.",
    "pb_kappa":
        "Cohen's Kappa quantifies agreement between two raters on categorical "
        "ratings, correcting for chance agreement.",
    "pb_icc_ba":
        "Intraclass Correlation (ICC) and Bland-Altman together describe "
        "agreement between two raters on continuous measurements — ICC for "
        "reliability, Bland-Altman for systematic bias and limits of agreement.",
    "pb_km":
        "Kaplan-Meier estimates survival curves over time and the log-rank "
        "test compares them between groups.",
    "pb_cox":
        "Cox proportional hazards regression estimates adjusted hazard ratios "
        "for time-to-event outcomes, controlling for covariates.",
    "ancova":
        "ANCOVA compares group means while adjusting for one or more "
        "continuous covariates — useful when groups differ on a baseline "
        "variable that also affects the outcome.",
}


_T_VS_MW = (
    "Both compare two independent groups on a continuous outcome. The t-test "
    "compares means and assumes the outcome is normally distributed in each "
    "group; it has more statistical power when that assumption holds. "
    "Mann-Whitney compares the distributions using ranks, makes no normality "
    "assumption, and is the right choice whenever Shapiro-Wilk rejects "
    "normality or sample size is small."
)


def _opening_plan(context: Dict[str, Any]) -> str:
    plan = (context or {}).get("plan") or {}
    n_tests = len(plan.get("tests") or [])
    n_graphs = len(plan.get("graphs") or [])
    return (
        f"Here is your analysis plan. {n_tests} test(s) and {n_graphs} graph(s) "
        "queued. You can add or remove any test. Ask me what any test does."
    )


def _match_alias(low: str) -> Tuple[Optional[List[str]], Optional[str]]:
    for keys, ids, reason in _TEST_ALIASES:
        if any(k in low for k in keys):
            return ids, reason
    return None, None


def chatbox3_reply(message: str, context: Dict[str, Any]) -> Dict[str, Any]:
    msg = (message or "").strip()
    if not msg:
        return _msg("Ask me to add or remove a test, or explain what any "
                    "specific test does.")
    low = msg.lower()
    if _is_calculation_request(msg):
        return _msg(REFUSE_CALCULATION)

    plan = (context or {}).get("plan") or {}
    plan_ids = {t.get("id") for t in (plan.get("tests") or [])}

    # ---- difference / comparison questions ----
    if "difference between" in low and ("t-test" in low or "t test" in low) and "mann" in low:
        return _msg(_T_VS_MW)

    # ---- intent: REMOVE test ----
    if any(w in low for w in ("remove", "drop", "don't need", "do not need",
                              "skip", "without", "delete")):
        ids, reason = _match_alias(low)
        if ids:
            target = next((i for i in ids if i in plan_ids), ids[0])
            return _action_msg(
                "remove_test", target,
                f"Removed from the plan as requested.",
            )
        return _msg(
            "Tell me which test to remove — e.g. 'I don't need regression' or "
            "'remove ANOVA'. You can also click the tick on a test card."
        )

    # ---- intent: ADD test ----
    if any(w in low for w in ("also run", "also add", "add ", "include ",
                              "i want ", "please run", "i'd like")):
        ids, reason = _match_alias(low)
        if ids:
            new_id = next((i for i in ids if i not in plan_ids), ids[0])
            return _action_msg("add_test", new_id, reason or "Added to the plan.")
        return _msg(
            "Tell me which test to add — e.g. 'also run survival analysis' or "
            "'add Cox regression'."
        )

    # ---- intent: explain a specific test ----
    ids, reason = _match_alias(low)
    if ids:
        explanations = []
        for tid in ids:
            exp = _TEST_EXPLANATIONS.get(tid)
            if exp:
                explanations.append(f"• {tid}: {exp}")
        body = "\n".join(explanations) if explanations else (reason or "")
        in_plan = [tid for tid in ids if tid in plan_ids]
        suffix = ""
        if in_plan:
            suffix = (
                "\n\nThis test is already in your plan because the engine "
                "matched your data shape and normality results to it."
            )
        return _msg(body + suffix)

    # ---- "why was X chosen" ----
    if "why" in low and ("chosen" in low or "selected" in low or "picked" in low):
        return _msg(
            "Each test in the plan was chosen by matching your assignment "
            "(outcome + grouping variable), the variable types, the normality "
            "result, and the study design hints from your objective. Ask me "
            "about a specific test — e.g. 'why ANOVA' — for the exact reason."
        )

    return _msg(
        "I can add or remove a test (say 'also run survival analysis' or "
        "'remove regression'), explain what a specific test does, or compare "
        "two tests. What would you like?"
    )


# ===========================================================================
# CHATBOX 4 — Results screen
# ===========================================================================


_CB4_TOPICS: List[Tuple[List[str], str]] = [
    (
        ["what does p", "p value mean", "p-value mean", "interpret p"],
        "A p-value is the probability of seeing a difference at least as large "
        "as the one observed if there were truly no effect. Small p (<0.05) "
        "means the data would be unusual under the null hypothesis, so we "
        "reject it. p does NOT measure the size of the effect — for that look "
        "at the mean difference, OR, HR, or correlation coefficient.",
    ),
    (
        ["odds ratio", "what does or", "or mean", "interpret or"],
        "An odds ratio (OR) compares the odds of an outcome between two groups. "
        "OR = 1 means no difference; OR > 1 means the outcome is more likely in "
        "the exposed group; OR < 1 means less likely. The 95% CI tells you the "
        "plausible range — if it crosses 1, the effect is not statistically "
        "significant.",
    ),
    (
        ["hazard ratio", "what does hr", "hr mean", "interpret hr"],
        "A hazard ratio (HR) compares the instantaneous risk of an event "
        "between two groups over time. HR = 1 means equal risk; HR = 2 means "
        "the event happens twice as fast in one group at any given moment. "
        "Like OR, the 95% CI is what tells you whether the difference is "
        "statistically meaningful.",
    ),
    (
        ["practically significant", "practical significance", "clinical significance",
         "clinically significant", "clinically meaningful"],
        "A result can be statistically significant (small p) but practically "
        "trivial if the effect size is tiny. Always look at the magnitude — a "
        "1 mmHg blood pressure drop with p<0.001 in a huge sample is real but "
        "may not change patient care. Conversely, a clinically meaningful "
        "effect can fail significance in a small sample. Report both.",
    ),
    (
        ["limitation", "weakness", "caveat"],
        "Common limitations to mention: sample size, missing-data handling, "
        "single-centre design, retrospective vs prospective, residual "
        "confounding, reliance on self-report, and the assumptions of each "
        "test (e.g. proportional hazards for Cox, linearity for regression). "
        "The Methods section already lists which assumptions were checked.",
    ),
    (
        ["write a sentence", "write for the paper", "for my paper",
         "for the manuscript", "write up", "draft a sentence"],
        "Use the auto-generated Results paragraph in the Methods + Results tab "
        "as a starting point — it follows APA conventions (test name, df, "
        "statistic, exact p, effect size, 95% CI). Edit the wording for your "
        "journal and add the clinical context.",
    ),
    (
        ["what does this mean for my patients", "for patients", "clinical meaning"],
        "Translate the effect size into something a clinician can act on: "
        "absolute risk difference, number needed to treat, mean change in the "
        "outcome on its original scale. Statistical significance only says the "
        "effect is unlikely to be chance — clinical relevance is your call.",
    ),
    (
        ["confidence interval", "what does ci", "95% ci", "ci mean"],
        "A 95% confidence interval is the range of values the true effect is "
        "plausibly in. If you repeated the study many times, 95% of such "
        "intervals would contain the true value. Wide CI = imprecise estimate "
        "(usually small sample). If the CI for a difference includes 0, or for "
        "an OR/HR includes 1, the effect is not statistically significant.",
    ),
]


def _opening_results(context: Dict[str, Any]) -> str:
    r = (context or {}).get("results") or {}
    n_tests = len(r.get("tests") or [])
    n_graphs = len(r.get("graphs") or [])
    correction = (r.get("correction_info") or {}).get("method")
    bits = [f"{n_tests} test(s)", f"{n_graphs} graph(s)"]
    if correction:
        bits.append(f"{correction} correction applied")
    return (
        "Your analysis is complete — " + ", ".join(bits) + ". "
        "Ask me what any result means for your research."
    )


def chatbox4_reply(message: str, context: Dict[str, Any]) -> Dict[str, Any]:
    msg = (message or "").strip()
    if not msg:
        return _msg("Ask me what a p-value, OR, HR, or confidence interval "
                    "means for your specific result.")
    low = msg.lower()
    if any(w in low for w in ("change the result", "redo the", "recalc",
                              "rerun", "fix the number", "different number",
                              "wrong p", "the p-value is wrong")):
        return _msg(REFUSE_RESULT_CHANGE)
    if _is_calculation_request(msg):
        return _msg(REFUSE_RESULT_CHANGE)
    # Look up a specific test by id or title from the results context.
    r = (context or {}).get("results") or {}
    for t in (r.get("tests") or []):
        title = (t.get("title") or "").lower()
        tid = (t.get("id") or "").lower()
        if (title and title in low) or (tid and tid in low):
            p = t.get("p_value") if "p_value" in t else (t.get("p") if "p" in t else None)
            p_txt = (
                "" if p is None else
                (" (p < 0.001)" if p < 0.001 else f" (p = {p:.3f})")
            )
            sig = "" if p is None else (
                " The result is statistically significant at α = 0.05."
                if p < 0.05 else
                " The result is NOT statistically significant at α = 0.05."
            )
            base = f"For '{t.get('title')}'{p_txt}.{sig} "
            extra = _TEST_EXPLANATIONS.get(t.get("id") or "", "")
            if extra:
                base += extra
            return _msg(base.strip())
    for keys, answer in _CB4_TOPICS:
        if any(k in low for k in keys):
            return _msg(answer)
    return _msg(
        "I can explain what a p-value, odds ratio, hazard ratio, or 95% CI "
        "means for your result, help you write a sentence for the paper, or "
        "talk through limitations. Which one would you like?"
    )


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Gemini AI layer (optional) — wraps the rule-based engine.
#
# Behaviour:
# * Calculation requests are still refused at the gate BEFORE any LLM call,
#   so the boundary holds even if Gemini misbehaves.
# * If GEMINI_API_KEY is set we try Gemini 1.5 Flash with a screen-specific
#   system prompt + a short context summary built from the live session.
# * For chatbox 3 we look for an action JSON in the response and convert it
#   to the same `_action_msg` shape the rule-based path emits.
# * Any failure (no key, network error, malformed response) silently falls
#   back to the rule-based reply so the UI keeps working.
# ---------------------------------------------------------------------------


from app.services.llm_client import openai_chat_url, openai_auth_header, openai_is_configured, gemini_is_configured, get_gemini_client


_SYSTEM_PROMPTS: Dict[str, str] = {
    "normality": (
        "You are a normality explanation assistant for a medical research "
        "platform. Explain in plain English only. Never produce any number "
        "or calculation. Never change the normality decision made by the "
        "engine. If asked to calculate say: 'The statistical engine handles "
        "all calculations. I can only explain.' Keep replies under 120 words."
    ),
    "plan": (
        "You are an analysis planning assistant. Help researchers understand "
        "and modify their plan. When the user asks to ADD a test respond with "
        'EXACTLY this JSON on its own line: '
        '{"action":"add_test","test_id":"<snake_case_id>","reason":"<short>"}. '
        "When REMOVING a test: "
        '{"action":"remove_test","test_id":"<snake_case_id>","reason":"<short>"}. '
        "For all other questions respond with plain text only. Never produce "
        "any p-value, OR, HR, or any statistical number. Keep replies under "
        "120 words. Valid test_id values include: ttest_independent, "
        "mann_whitney, anova_oneway, kruskal_wallis, tukey_hsd, chi_square, "
        "linear_regression, logistic_regression, ancova, pb_km, pb_cox, "
        "pb_paired_t, pb_wilcoxon, pb_mcnemar, pb_rm_anova, pb_friedman, "
        "pb_kappa, pb_icc_ba, pb_chi_or_fisher."
    ),
    "results": (
        "You are a results interpretation assistant. The results were "
        "calculated by validated Python libraries and are correct. Never "
        "recalculate. Never dispute any result. Never produce a new number. "
        "If asked to recalculate say exactly: 'These results were produced "
        "by validated statistical libraries and cannot be changed. I can "
        "help you understand them.' Explain in plain English suitable for a "
        "clinician with no statistics background. Keep replies under 120 words."
    ),
}


def _build_gemini_context(kind: str, context: Dict[str, Any]) -> str:
    if kind == "normality":
        cols = context.get("columns") or []
        normal = [c.get("column", "") for c in cols if c.get("decision") == "normal"]
        non_normal = [
            c.get("column", "") for c in cols if c.get("decision") == "non_normal"
        ]
        return (
            f"Normality context: {len(normal)} normal, {len(non_normal)} "
            f"non-normal. Non-normal columns: "
            f"{', '.join(non_normal) or 'none'}."
        )
    if kind == "plan":
        plan = context.get("plan") or {}
        tests = plan.get("tests") or []
        names = [t.get("title") or t.get("id", "") for t in tests]
        return (
            f"Plan context: {len(tests)} test(s) currently planned: "
            f"{', '.join(names) or 'none'}."
        )
    if kind == "results":
        res = context.get("results") or {}
        tests = res.get("tests") or []
        names = [t.get("title") or t.get("id", "") for t in tests]
        return (
            f"Results context: {len(tests)} test(s) completed: "
            f"{', '.join(names) or 'none'}."
        )
    return ""


def _try_gemini(kind: str, message: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Call Gemini; return a reply dict on success, None on any failure."""
    if not gemini_is_configured():
        return None

    system = _SYSTEM_PROMPTS.get(kind)
    if not system:
        return None

    prompt = (
        system
        + "\n\n"
        + _build_gemini_context(kind, context)
        + "\n\nUser question: "
        + message
    )

    try:
        from google.genai import types as gtypes
        client = get_gemini_client()
        resp = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
            config=gtypes.GenerateContentConfig(
                max_output_tokens=400,
                temperature=0.3,
            ),
        )
        text = (resp.text or "").strip()
        if not text:
            return None
    except Exception as exc:  # noqa: BLE001 - never let LLM kill the request
        logger.info("Gemini call failed (%s); falling back to rule-based.", exc)
        return None

    if kind == "plan":
        match = re.search(r'\{[^{}]*"action"[^{}]*\}', text, re.DOTALL)
        if match:
            try:
                action = json.loads(match.group())
                act = action.get("action")
                tid = action.get("test_id")
                if act in ("add_test", "remove_test") and isinstance(tid, str) and tid:
                    reason = action.get("reason") or action.get("message") or ""
                    return _action_msg(act, tid, reason)
            except (ValueError, TypeError):
                pass

    return _msg(text)


def opening_message(kind: str, context: Dict[str, Any]) -> str:
    if kind == "normality":
        return _opening_normality(context)
    if kind == "plan":
        return _opening_plan(context)
    if kind == "results":
        return _opening_results(context)
    return ""


def _rule_based_reply(kind: str, message: str, context: Dict[str, Any]) -> Dict[str, Any]:
    if kind == "normality":
        return chatbox2_reply(message, context)
    if kind == "plan":
        return chatbox3_reply(message, context)
    if kind == "results":
        return chatbox4_reply(message, context)
    return _msg("Unknown chatbox.")


def _try_openai(kind: str, message: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Call OpenAI GPT-4o-mini; return a reply dict on success, None on any failure."""
    if not openai_is_configured():
        return None

    system = _SYSTEM_PROMPTS.get(kind)
    if not system:
        return None

    user_content = (
        _build_gemini_context(kind, context)
        + "\n\nUser question: "
        + message
    )

    body = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 400,
        "temperature": 0.3,
    }).encode("utf-8")

    req = urllib.request.Request(
        openai_chat_url(),
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": openai_auth_header(),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"].strip()
        if not text:
            return None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, KeyError, IndexError) as exc:
        logger.info("OpenAI chatbox call failed (%s); trying Gemini.", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unexpected OpenAI chatbox error: %s", exc)
        return None

    if kind == "plan":
        match = re.search(r'\{[^{}]*"action"[^{}]*\}', text, re.DOTALL)
        if match:
            try:
                action = json.loads(match.group())
                act = action.get("action")
                tid = action.get("test_id")
                if act in ("add_test", "remove_test") and isinstance(tid, str) and tid:
                    reason = action.get("reason") or action.get("message") or ""
                    return _action_msg(act, tid, reason)
            except (ValueError, TypeError):
                pass

    return _msg(text)


def reply(kind: str, message: str, context: Dict[str, Any]) -> Dict[str, Any]:
    # Boundary refusal stays at the gate so the LLM cannot violate it.
    if _is_calculation_request(message):
        if kind == "results":
            return _msg(REFUSE_RESULT_CHANGE)
        return _msg(REFUSE_CALCULATION)

    # OpenAI GPT-4o-mini is primary; Gemini is fallback; rule-based is last resort.
    openai_reply = _try_openai(kind, message, context)
    if openai_reply is not None:
        return openai_reply

    gemini = _try_gemini(kind, message, context)
    if gemini is not None:
        return gemini

    return _rule_based_reply(kind, message, context)
