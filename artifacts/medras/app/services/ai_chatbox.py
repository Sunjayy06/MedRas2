"""AI-powered chatboxes for Sigma — Variables / Normality / Plan / Results.

Provider assignment (use what each section is best at):
  Results  → OpenAI GPT-4o PRIMARY   (narrative writing, table interpretation, effect-size commentary)
  Plan     → OpenAI GPT-4o PRIMARY   (structured test selection, reasoning)
  Variables→ Gemini 2.5 Flash PRIMARY (fast classification, JSON extraction)
  Normality→ Gemini 2.5 Flash PRIMARY (fast statistical explanation)
  Setup    → Gemini 2.5 Flash PRIMARY (planning/routing)
  parse_variable_intent → Gemini 2.5 Flash PRIMARY (fast JSON)

Each section falls back to the other provider, then to the rule-based engine.

Public API
──────────
  await chat(kind, message, context)       → {"role", "text", "action"}
  await opening_message(kind, context)     → str
  await parse_variable_intent(msg, ctx)    → dict | None
  await plan_study_setup(desc, cols, ...)  → dict

Action shapes
─────────────
  plan    → {"action": "add_test"|"remove_test", "test_id": str, "reason": str}
  results → {"action": "rerun", "add_test_ids": [str], "remove_test_ids": [str]}
  others  → None (explanation only)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

from . import chatboxes  # rule-based fallback (last resort)
from .llm_client import openrouter_chat, openrouter_is_configured, provider_status_payload
from .phi_redaction import screen_external_ai_payload
from . import domain_profiles

logger = logging.getLogger(__name__)

_OPENAI_MODEL_STANDARD = "gpt-4o-mini"   # Variables / Normality fallback
_OPENAI_MODEL_STRONG   = "gpt-4o"        # Results / Plan primary

# Per-kind token budgets — results needs more room for full interpretation
_MAX_TOKENS = {
    "results":   1200,
    "plan":       800,
    "normality":  500,
    "variables":  500,
    "setup":      700,
}
_DEFAULT_TOKENS = 600

_VALID_PLAN_TEST_IDS = {
    "ttest_independent", "mann_whitney", "anova_oneway", "kruskal_wallis",
    "chi_square", "fisher_exact_if_sparse", "pb_chi_or_fisher",
    "linear_regression", "logistic_regression",
    "pb_km", "pb_cox",
    "pb_paired_t", "pb_wilcoxon", "pb_mcnemar",
    "pb_rm_anova", "pb_friedman",
    "pb_kappa", "pb_icc_ba",
    "ancova", "tukey_hsd",
}


# ---------------------------------------------------------------------------
# System prompts — injected with live session context
# ---------------------------------------------------------------------------

def _normality_system(context: Dict[str, Any]) -> str:
    cols = (context or {}).get("columns") or []
    n = len(cols)
    normal = sum(1 for c in cols if c.get("decision") == "normal")
    def _fmt_p(c: Dict[str, Any]) -> str:
        p = c.get("p_value") or 1.0
        return "<0.001" if p < 0.001 else f"{p:.3f}"

    col_lines = "\n".join(
        f"  • {c.get('column','?')}: {c.get('test','—')} p={_fmt_p(c)}"
        f", skew={c.get('skewness','—')}, verdict={c.get('decision','—')}"
        for c in cols
    ) or "  (no scale variables)"

    return (
        f"You are a biostatistics explainer in MedRAS Sigma.\n"
        f"Dataset normality ({n} scale variables, {normal} normal, {n-normal} non-normal):\n"
        f"{col_lines}\n\n"
        f"Rules:\n"
        f"- Reply in 2–4 plain sentences suitable for clinicians.\n"
        f"- Never calculate values yourself — they were computed by the engine.\n"
        f"- Do not override decisions; tell users to use the override toggle.\n"
        f"- Explain which test family the result selects.\n"
        f"- If asked about a specific variable, reference its actual stats above.\n"
        f"- Plain prose only — no markdown, no JSON."
    )


def _plan_system(context: Dict[str, Any]) -> str:
    plan = (context or {}).get("plan") or {}
    tests = plan.get("tests") or []
    test_lines = "\n".join(
        f"  • {t.get('id','?')}: {t.get('title','?')} — {t.get('why','')}"
        for t in tests
    ) or "  (no tests yet)"
    in_plan = ", ".join(t.get("id", "") for t in tests) or "none"

    return (
        f"You are the Plan Assistant in MedRAS Sigma.\n"
        f"Current plan:\n{test_lines}\n"
        f"Tests in plan: {in_plan}\n"
        f"Valid test IDs you can add: {', '.join(sorted(_VALID_PLAN_TEST_IDS))}\n\n"
        f"Your role:\n"
        f"1. EXPLAIN what tests do in plain language (2–5 sentences).\n"
        f"2. ADD or REMOVE tests on request — ONLY IDs from the valid list above.\n"
        f"3. COMPARE tests when asked — explain parametric vs non-parametric trade-offs.\n"
        f"4. Recommend tests that fit the study design and variable types.\n\n"
        f"For ADD/REMOVE append this JSON on its own line at the end:\n"
        f'  {{"action": "add_test" or "remove_test", "test_id": "<exact_id>", "reason": "<sentence>"}}\n'
        f"For explanations: plain prose only, no JSON."
    )


def _results_system(context: Dict[str, Any]) -> str:
    results = (context or {}).get("results") or {}
    tests = results.get("tests") or []

    test_lines = "\n".join(
        "  • {title}: {rows}".format(
            title=t.get("title", "?"),
            rows="; ".join(
                "{label}={value}".format(
                    label=r.get("label", "?"), value=r.get("value", "?")
                )
                for r in (t.get("rows") or [])[:6]
            ),
        )
        for t in tests[:12]
    ) or "  (results not yet available)"

    methods = (results.get("methods_md") or "")[:600]
    narrative = (results.get("narrative_md") or "")[:400]

    return (
        f"You are the Results Interpreter in MedRAS Sigma — an expert medical statistician "
        f"and clinical writer.\n\n"
        f"Statistical results:\n{test_lines}\n\n"
        f"Methods section:\n{methods if methods else '  (not available)'}\n\n"
        f"Narrative:\n{narrative if narrative else '  (not available)'}\n\n"
        f"Your role:\n"
        f"1. Interpret results in precise, publication-ready clinical language.\n"
        f"2. Explain p-values, effect sizes, ORs, HRs, CIs in context — reference actual numbers.\n"
        f"3. Flag clinical vs statistical significance distinctions.\n"
        f"4. Suggest how to phrase results for journal submission (Methods / Results sections).\n"
        f"5. If the researcher wants a test added or removed, append:\n"
        f'   {{"action": "rerun", "add_test_ids": [...], "remove_test_ids": [...]}}\n'
        f"   Valid test IDs: ttest_independent, mann_whitney, anova_oneway, kruskal_wallis, "
        f"chi_square, linear_regression, logistic_regression, pb_km, pb_cox, "
        f"pb_paired_t, pb_wilcoxon, pb_rm_anova, pb_kappa, ancova\n\n"
        f"Rules:\n"
        f"- Never change or fabricate calculated values — interpret what is given.\n"
        f"- If a result looks unusual, say so and suggest a sanity check.\n"
        f"- Keep interpretations to 3–6 sentences unless the researcher asks for more.\n"
        f"- Plain prose for explanations. JSON only when triggering a rerun."
    )


def _variables_system(context: Dict[str, Any]) -> str:
    classifications = (context or {}).get("classifications") or []
    issues = (context or {}).get("issues") or []
    col_lines = "\n".join(
        f"  • {c.get('column','?')}: {c.get('detected_type','?')} "
        f"({c.get('unique_count','?')} unique, {c.get('missing_pct',0):.1f}% missing)"
        for c in classifications[:20]
    ) or "  (none)"
    issue_lines = "\n".join(
        f"  ⚠ {i.get('column','?')}: {i.get('message','')}"
        for i in issues[:8]
    ) if issues else "  (no issues)"
    profile_guidance = ""
    if domain_profiles.is_breast_pathology((context or {}).get("domain_profile")):
        profile_guidance = (
            "Never suggest stripping prefixes or numeric conversion for breast-pathology "
            "markers such as HER2, ER, PR, AR, LVI, ENE, Necrosis, or DCIS. "
            "HER2 Positive/Negative is nominal; pure 0/1+/2+/3+ HER2 scores are ordinal.\n"
        )

    return (
        f"You are the Variable Assistant in MedRAS Sigma.\n"
        f"Columns:\n{col_lines}\n"
        f"Issues:\n{issue_lines}\n\n"
        f"Your role:\n"
        f"1. Suggest how to handle problematic variables.\n"
        f"2. Explain what variable types mean (scale, ordinal, nominal, id).\n"
        f"3. Recommend which variables to exclude or recode.\n"
        f"4. For actionable changes, suggest the exact command for the assistant input.\n"
        f"{profile_guidance}"
        f"Plain, practical prose (2–4 sentences). No JSON."
    )


def _missing_system(context: Dict[str, Any]) -> str:
    columns = (context or {}).get("columns") or []
    actions = (context or {}).get("supported_actions") or []
    rows = "\n".join(
        f"  - {c.get('column','?')}: {c.get('missing_count',0)} missing "
        f"({c.get('missing_pct',0):.1f}%), type={c.get('detected_type','unknown')}, "
        f"selected={c.get('selected_decision','leave')}"
        for c in columns[:30]
    ) or "  (no columns with missing values)"
    return (
        "You are the Missing Data Assistant in MedRAS Sigma.\n"
        f"Missingness context:\n{rows}\n"
        f"Supported actions only: {', '.join(actions)}.\n\n"
        "Give conservative guidance for medical research. Explain how missingness "
        "can bias estimates and reduce power. Warn against automatic imputation "
        "without clinical/statistical justification, suggest sensitivity analysis "
        "when relevant, and recommend reporting high missingness rather than blind "
        "imputation. Mean/median imputation is only sensible for numeric variables; "
        "mode may be considered for categorical variables. Dropping rows can bias "
        "results and reduce sample size. Never suggest an action outside the "
        "supported list. Never return action JSON or claim a decision was applied. State "
        "that the researcher must explicitly select and apply a decision in the UI."
    )


def _build_system_prompt(kind: str, context: Dict[str, Any]) -> str:
    builders = {
        "normality": _normality_system,
        "plan":      _plan_system,
        "results":   _results_system,
        "variables": _variables_system,
        "missing":   _missing_system,
    }
    fn = builders.get(kind)
    return fn(context) if fn else "You are a helpful medical statistics assistant."


# ---------------------------------------------------------------------------
# Action extraction
# ---------------------------------------------------------------------------

def _extract_action(text: str, kind: str) -> Optional[Dict[str, Any]]:
    m = re.search(r'\{[^{}]*"action"[^{}]*\}', text, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None

    if kind == "plan":
        act = obj.get("action")
        tid = obj.get("test_id", "")
        if act in ("add_test", "remove_test"):
            if tid in _VALID_PLAN_TEST_IDS:
                return {"action": act, "test_id": tid, "reason": obj.get("reason", "")}
            logger.warning("AI suggested invalid plan test_id %r — ignored", tid)

    if kind == "results" and obj.get("action") == "rerun":
        return {
            "action": "rerun",
            "add_test_ids": obj.get("add_test_ids") or [],
            "remove_test_ids": obj.get("remove_test_ids") or [],
        }

    return None


def _strip_action_json(text: str) -> str:
    return re.sub(r'\n?\{[^{}]*"action"[^{}]*\}', '', text, flags=re.DOTALL).strip()


# ---------------------------------------------------------------------------
# Deprecated provider-shaped wrappers
# ---------------------------------------------------------------------------

def _gemini_call_sync(system_prompt: str, message: str, max_tokens: int = 600) -> Optional[str]:
    """Compatibility wrapper routed exclusively through OpenRouter."""
    return _openrouter_call_sync("chat", system_prompt, message, max_tokens)


# ---------------------------------------------------------------------------
# OpenRouter compatibility wrapper
# ---------------------------------------------------------------------------

def _openai_call_sync(
    system_prompt: str,
    message: str,
    max_tokens: int = 600,
    model: str = _OPENAI_MODEL_STANDARD,
) -> Optional[str]:
    """Compatibility wrapper routed exclusively through OpenRouter."""
    task = "reasoning" if model == _OPENAI_MODEL_STRONG else "chat"
    return _openrouter_call_sync(task, system_prompt, message, max_tokens)


def _openrouter_call_sync(
    task: str,
    system_prompt: str,
    message: str,
    max_tokens: int = 600,
) -> Optional[str]:
    if not openrouter_is_configured():
        return None


def _task_for_kind(kind: str) -> str:
    if kind == "variables":
        return "variable_mapping"
    if kind == "missing":
        return "cleanup_suggestions"
    if kind == "results":
        return "report_writing"
    if kind == "plan":
        return "reasoning"
    return "chat"
    try:
        return openrouter_chat(
            task=task,
            system=system_prompt,
            user=message,
            max_tokens=max_tokens,
            temperature=0.4,
        )
    except Exception as exc:
        logger.info("OpenRouter chatbox call failed (%s); using rule-based fallback.", exc)
        return None


# ---------------------------------------------------------------------------
# Provider dispatch — routes each kind to its optimal primary model
# ---------------------------------------------------------------------------

async def _call_llm(
    kind: str,
    system_prompt: str,
    message: str,
) -> tuple[Optional[str], Optional[str]]:
    """Call OpenRouter with the model assigned to this assistant task."""
    tokens = _MAX_TOKENS.get(kind, _DEFAULT_TOKENS)
    task = _task_for_kind(kind)
    raw = await asyncio.to_thread(
        _openrouter_call_sync, task, system_prompt, message, tokens
    )
    return raw, ("openrouter" if raw is not None else None)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def chat(
    kind: str,
    message: str,
    context: Dict[str, Any],
    external_ai_consent: bool = False,
) -> Dict[str, Any]:
    """Return ``{"role": "ai", "text": str, "action": dict|None}``."""
    system_prompt = _build_system_prompt(kind, context)
    screening = screen_external_ai_payload({
        "system_prompt": system_prompt,
        "message": message,
    })
    screened = screening.value
    external_allowed = external_ai_consent and not screening.blocked

    raw, provider = (
        await _call_llm(kind, screened["system_prompt"], screened["message"])
        if external_allowed else (None, None)
    )

    # Rule-based engine — last resort (no API key, always available)
    if raw is None:
        logger.warning("OpenRouter unavailable for kind=%r; using rule-based fallback", kind)
        result = chatboxes.reply(kind, message, context, external_ai_consent=False)
        return {
            "role": result.get("role", "ai"),
            "text": result.get("text", ""),
            "action": None,
            **provider_status_payload(
                "local_fallback",
                external_ai_consent,
                screening.redaction_applied,
                screening.blocked,
            ),
        }

    action = _extract_action(raw, kind)
    prose  = _strip_action_json(raw)

    # For plan chatbox: embed action JSON so the frontend regex can parse it
    display_text = prose
    if action and kind == "plan":
        json_embed = json.dumps({
            "action":  action["action"],
            "test_id": action["test_id"],
            "reason":  action.get("reason", ""),
        })
        display_text = (prose + "\n\n" + json_embed).strip() if prose else json_embed

    return {
        "role": "ai",
        "text": display_text,
        "action": action,
        **provider_status_payload(
            provider or "ai_unavailable",
            external_ai_consent,
            screening.redaction_applied,
            screening.blocked,
        ),
    }


async def opening_message(
    kind: str, context: Dict[str, Any], external_ai_consent: bool = False
) -> Dict[str, Any]:
    """AI-powered context-aware opening message for each chatbox screen.

    Generates a 1–2 sentence greeting that references specific details from the
    session data (e.g. how many variables are normal, which tests are planned,
    whether any results are significant) and invites the researcher to ask a
    question.  Falls back to the rule-based chatboxes.opening_message() if
    both LLM providers are unavailable.
    """
    system_prompt = _build_system_prompt(kind, context)

    user_msg = (
        "Write a 1–2 sentence opening message for this screen. "
        "Reference 1–2 specific details from the session data above "
        "(e.g. how many variables are normal, which tests are planned, "
        "or whether any results are statistically significant). "
        "End with a natural, open-ended invitation for the researcher to "
        "ask a question. "
        "Plain prose only — no bullet points, no markdown, no JSON."
    )
    screening = screen_external_ai_payload({
        "system_prompt": system_prompt,
        "message": user_msg,
    })
    system_prompt = screening.value["system_prompt"]
    user_msg = screening.value["message"]
    external_allowed = external_ai_consent and not screening.blocked

    # Small token budget — this is just a brief greeting
    tokens = 160

    provider = None
    if not external_allowed:
        raw = None
    else:
        task = _task_for_kind(kind)
        raw = await asyncio.to_thread(
            _openrouter_call_sync, task, system_prompt, user_msg, tokens
        )
        provider = "openrouter" if raw is not None else None

    if raw and len(raw.strip()) > 10:
        # Strip any accidental JSON or markdown the model may have emitted
        text = _strip_action_json(raw.strip())
        text = re.sub(r"^```[^\n]*\n?|```$", "", text, flags=re.MULTILINE).strip()
        if text:
            return {
                "role": "system",
                "text": text,
                **provider_status_payload(
                    provider or "ai_unavailable",
                    external_ai_consent,
                    screening.redaction_applied,
                    screening.blocked,
                ),
            }

    # Rule-based fallback — always available
    return {
        "role": "system",
        "text": chatboxes.opening_message(kind, context),
        **provider_status_payload(
            "local_fallback",
            external_ai_consent,
            screening.redaction_applied,
            screening.blocked,
        ),
    }


# ---------------------------------------------------------------------------
# Variable intent parser — natural language → structured action dict
# (Gemini primary — fast JSON extraction; OpenAI fallback)
# ---------------------------------------------------------------------------

_VALID_VA_ACTIONS = frozenset({"rename", "recode", "exclude", "include", "set_type", "trim_whitespace"})


async def parse_variable_intent(
    message: str,
    context: Dict[str, Any],
    external_ai_consent: bool = False,
) -> tuple[Optional[Dict[str, Any]], str, Dict[str, bool]]:
    """Parse a plain-English variable command into a structured intent dict.

    Returns ``{"action", "column", ...}`` on success, or ``None`` when the
    message is a question / not parseable as a mutation.
    """
    classifications = (context or {}).get("classifications") or []
    cols = [c.get("column", "") for c in classifications[:30] if c.get("column")]
    profile_guidance = ""
    if domain_profiles.is_breast_pathology((context or {}).get("domain_profile")):
        profile_guidance = (
            "Never suggest strip_prefix for breast-pathology markers such as HER2, "
            "ER, PR, AR, LVI, ENE, Necrosis, or DCIS.\n"
        )

    system = (
        f"You parse variable-management instructions for a statistical tool.\n"
        f"Available columns: {', '.join(cols) if cols else '(unknown)'}\n\n"
        f"If the input is an actionable mutation command, return ONLY this JSON:\n"
        f'{{"action":"rename"|"recode"|"exclude"|"include"|"set_type"|"trim_whitespace",'
        f'"column":"<exact column name from the list above>",'
        f'"new_name":"<str or null>",'
        f'"new_type":"scale"|"ordinal"|"nominal"|"id"|null,'
        f'"recode_map":{{}} }}\n'
        f"Use \"trim_whitespace\" when the user wants to clean/standardise string values "
        f"(e.g. remove trailing spaces, fix 'Positive ' vs 'Positive').\n"
        f"{profile_guidance}"
        f"If the input is a question or explanation request, return exactly: null\n"
        f"Return ONLY the JSON object or null — no prose, no markdown."
    )
    screening = screen_external_ai_payload({"system": system, "message": message})
    system = screening.value["system"]
    message = screening.value["message"]
    external_allowed = external_ai_consent and not screening.blocked
    screening_meta = {
        "redaction_applied": screening.redaction_applied,
        "phi_blocked": screening.blocked,
    }

    tokens = _MAX_TOKENS.get("variables", _DEFAULT_TOKENS)
    raw = await asyncio.to_thread(
        _openrouter_call_sync, "variable_mapping", system, message, tokens
    ) if external_allowed else None
    provider = "openrouter" if raw is not None else None
    if not raw:
        return None, "local_fallback", screening_meta

    raw = raw.strip()
    if raw.lower() in ("null", "none", ""):
        return None, "local_fallback", screening_meta

    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$",          "", raw, flags=re.MULTILINE).strip()

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and obj.get("action") in _VALID_VA_ACTIONS and obj.get("column"):
            return {
                "action":     obj["action"],
                "column":     obj["column"],
                "new_name":   obj.get("new_name"),
                "new_type":   obj.get("new_type"),
                "recode_map": obj.get("recode_map") or {},
            }, provider or "ai_unavailable", screening_meta
    except (json.JSONDecodeError, ValueError):
        pass
    return None, "local_fallback", screening_meta


# ---------------------------------------------------------------------------
# Study plan generator — description → rich plan JSON for screen-setup
# (Gemini primary — planning/routing; OpenAI fallback)
# ---------------------------------------------------------------------------

async def plan_study_setup(
    description: str,
    columns: List[str],
    classifications: List[Dict[str, Any]],
    n_rows: int = 0,
    external_ai_consent: bool = False,
    profile: str = domain_profiles.DEFAULT_PROFILE,
) -> Dict[str, Any]:
    """Generate a rich study plan from a plain-English description.

    Returns:
        {
            study_type, outcome_col, objective, sample_size, predictors,
            test_pairs: [{"col_a", "col_b", "test_name", "reason"}],
            reasoning, confidence, source
        }
    """
    col_summary = ", ".join(
        f"{c.get('column','?')} ({c.get('detected_type','?')})"
        for c in (classifications or [])[:20]
    ) or ", ".join((columns or [])[:20])

    profile_guidance = ""
    if domain_profiles.is_breast_pathology(profile):
        profile_guidance = (
            "\nBreast-pathology profile: treat HER2, ER, PR, AR, LVI, ENE, DCIS, "
            "molecular subtype, pT, and nodal status using their clinical meanings. "
            "Routine markers are usually predictors unless explicitly named as outcomes.\n"
        )
    system = (
        f"You are a biostatistics planning assistant. Dataset: {n_rows} rows.\n"
        f"Columns: {col_summary}\n\n"
        f"Return ONLY this JSON schema — no markdown, no prose:\n"
        f"{{\n"
        f'  "study_type": "comparison"|"correlation"|"association"|"regression"|"survival"|"diagnostic"|"reliability"|"descriptive",\n'
        f'  "outcome_col": "<exact column name or null>",\n'
        f'  "predictors": ["<col>", ...],\n'
        f'  "objective": "<one clear plain-English sentence>",\n'
        f'  "sample_size": <integer or null>,\n'
        f'  "test_pairs": [\n'
        f'    {{"col_a":"<col>","col_b":"<col>","test_name":"<test>","reason":"<1 sentence>"}}\n'
        f'  ],\n'
        f'  "reasoning": "<2–3 sentence explanation>"\n'
        f"}}"
        + profile_guidance
    )

    prompt = (description or "").strip() or "Suggest an appropriate study plan based on the columns."
    screening = screen_external_ai_payload({"system": system, "prompt": prompt})
    system = screening.value["system"]
    prompt = screening.value["prompt"]
    external_allowed = external_ai_consent and not screening.blocked

    tokens = _MAX_TOKENS.get("setup", _DEFAULT_TOKENS)
    raw = await asyncio.to_thread(
        _openrouter_call_sync, "study_setup", system, prompt, tokens
    ) if external_allowed else None
    provider = "openrouter" if raw is not None else None

    if not raw:
        return {
            "study_type": "descriptive",
            "outcome_col": None,
            "predictors": [],
            "objective":  "",
            "sample_size": n_rows or None,
            "test_pairs": [],
            "reasoning":  "",
            "confidence": 0,
            "source":     "rule_based",
            **provider_status_payload(
                "local_fallback", external_ai_consent,
                screening.redaction_applied, screening.blocked,
            ),
        }

    clean = raw.strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.MULTILINE)
    clean = re.sub(r"```\s*$",          "", clean, flags=re.MULTILINE).strip()

    try:
        plan = json.loads(clean)
        return {
            "study_type":  plan.get("study_type", "descriptive"),
            "outcome_col": plan.get("outcome_col"),
            "predictors":  plan.get("predictors") or [],
            "objective":   plan.get("objective", ""),
            "sample_size": plan.get("sample_size"),
            "test_pairs":  plan.get("test_pairs") or [],
            "reasoning":   plan.get("reasoning", ""),
            "confidence":  0.85,
            "source":      provider or "ai",
            **provider_status_payload(
                provider or "ai_unavailable", external_ai_consent,
                screening.redaction_applied, screening.blocked,
            ),
        }
    except (json.JSONDecodeError, ValueError):
        return {
            "study_type":  "descriptive",
            "outcome_col": None,
            "predictors":  [],
            "objective":   "",
            "sample_size": None,
            "test_pairs":  [],
            "reasoning":   "",
            "confidence":  0,
            "source":      "rule_based",
            **provider_status_payload(
                "local_fallback", external_ai_consent,
                screening.redaction_applied, screening.blocked,
            ),
        }
