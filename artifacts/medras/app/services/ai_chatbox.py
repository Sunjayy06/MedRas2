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
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from . import chatboxes  # rule-based fallback (last resort)
from .llm_client import (
    openai_chat_url,
    openai_auth_header,
    openai_is_configured,
    gemini_is_configured,
    get_gemini_client,
)

logger = logging.getLogger(__name__)

_GEMINI_MODEL = "gemini-2.5-flash"
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

# Kinds where OpenAI GPT-4o is the primary provider
_OPENAI_PRIMARY_KINDS = frozenset({"results", "plan"})
# Kinds where Gemini is the primary provider
_GEMINI_PRIMARY_KINDS = frozenset({"variables", "normality", "setup"})


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

    return (
        f"You are the Variable Assistant in MedRAS Sigma.\n"
        f"Columns:\n{col_lines}\n"
        f"Issues:\n{issue_lines}\n\n"
        f"Your role:\n"
        f"1. Suggest how to handle problematic variables.\n"
        f"2. Explain what variable types mean (scale, ordinal, nominal, id).\n"
        f"3. Recommend which variables to exclude or recode.\n"
        f"4. For actionable changes, suggest the exact command for the assistant input.\n"
        f"Plain, practical prose (2–4 sentences). No JSON."
    )


def _build_system_prompt(kind: str, context: Dict[str, Any]) -> str:
    builders = {
        "normality": _normality_system,
        "plan":      _plan_system,
        "results":   _results_system,
        "variables": _variables_system,
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
# Gemini 2.5 Flash — called in a thread pool (sync SDK)
# ---------------------------------------------------------------------------

def _gemini_call_sync(system_prompt: str, message: str, max_tokens: int = 600) -> Optional[str]:
    """Synchronous Gemini call — must run in a thread, not the event loop."""
    if not gemini_is_configured():
        return None
    try:
        from google.genai import types as genai_types
        client = get_gemini_client()
        full_prompt = f"{system_prompt}\n\nUser: {message}\n\nAssistant:"
        response = client.models.generate_content(
            model=_GEMINI_MODEL,
            contents=full_prompt,
            config=genai_types.GenerateContentConfig(
                max_output_tokens=max_tokens,
                temperature=0.4,
            ),
        )
        text = (response.text or "").strip()
        return text if text else None
    except Exception as exc:
        logger.info("Gemini chatbox call failed (%s) — trying secondary.", exc)
        return None


# ---------------------------------------------------------------------------
# OpenAI — pure urllib, no asyncio needed
# ---------------------------------------------------------------------------

def _openai_call_sync(
    system_prompt: str,
    message: str,
    max_tokens: int = 600,
    model: str = _OPENAI_MODEL_STANDARD,
) -> Optional[str]:
    """Synchronous OpenAI call — runs inline (short network hop)."""
    if not openai_is_configured():
        return None
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": message},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.4,
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
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"].strip()
        return text if text else None
    except Exception as exc:
        logger.info("OpenAI chatbox call failed (%s) — using rule-based.", exc)
        return None


# ---------------------------------------------------------------------------
# Provider dispatch — routes each kind to its optimal primary model
# ---------------------------------------------------------------------------

async def _call_llm(
    kind: str,
    system_prompt: str,
    message: str,
) -> Optional[str]:
    """Call the best LLM for this kind; fall back to the other; return None if both fail."""
    tokens = _MAX_TOKENS.get(kind, _DEFAULT_TOKENS)

    if kind in _OPENAI_PRIMARY_KINDS:
        # OpenAI GPT-4o primary → Gemini fallback
        raw = await asyncio.to_thread(
            _openai_call_sync, system_prompt, message, tokens, _OPENAI_MODEL_STRONG
        )
        if raw is None:
            logger.info("GPT-4o unavailable for kind=%r — trying Gemini fallback", kind)
            raw = await asyncio.to_thread(_gemini_call_sync, system_prompt, message, tokens)
    else:
        # Gemini primary → OpenAI gpt-4o-mini fallback
        raw = await asyncio.to_thread(_gemini_call_sync, system_prompt, message, tokens)
        if raw is None:
            logger.info("Gemini unavailable for kind=%r — trying OpenAI fallback", kind)
            raw = await asyncio.to_thread(
                _openai_call_sync, system_prompt, message, tokens, _OPENAI_MODEL_STANDARD
            )

    return raw


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def chat(
    kind: str,
    message: str,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Return ``{"role": "ai", "text": str, "action": dict|None}``."""
    system_prompt = _build_system_prompt(kind, context)

    raw = await _call_llm(kind, system_prompt, message)

    # Rule-based engine — last resort (no API key, always available)
    if raw is None:
        logger.warning("Both LLM providers unavailable for kind=%r — rule-based fallback", kind)
        result = chatboxes.reply(kind, message, context)
        return {
            "role": result.get("role", "ai"),
            "text": result.get("text", ""),
            "action": None,
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

    return {"role": "ai", "text": display_text, "action": action}


async def opening_message(kind: str, context: Dict[str, Any]) -> str:
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

    # Small token budget — this is just a brief greeting
    tokens = 160

    # Gemini primary for most kinds, OpenAI for results/plan
    if kind in _OPENAI_PRIMARY_KINDS:
        raw = await asyncio.to_thread(
            _openai_call_sync, system_prompt, user_msg, tokens, _OPENAI_MODEL_STANDARD
        )
        if raw is None:
            raw = await asyncio.to_thread(_gemini_call_sync, system_prompt, user_msg, tokens)
    else:
        raw = await asyncio.to_thread(_gemini_call_sync, system_prompt, user_msg, tokens)
        if raw is None:
            raw = await asyncio.to_thread(
                _openai_call_sync, system_prompt, user_msg, tokens, _OPENAI_MODEL_STANDARD
            )

    if raw and len(raw.strip()) > 10:
        # Strip any accidental JSON or markdown the model may have emitted
        text = _strip_action_json(raw.strip())
        text = re.sub(r"^```[^\n]*\n?|```$", "", text, flags=re.MULTILINE).strip()
        if text:
            return text

    # Rule-based fallback — always available
    return chatboxes.opening_message(kind, context)


# ---------------------------------------------------------------------------
# Variable intent parser — natural language → structured action dict
# (Gemini primary — fast JSON extraction; OpenAI fallback)
# ---------------------------------------------------------------------------

_VALID_VA_ACTIONS = frozenset({"rename", "recode", "exclude", "include", "set_type"})


async def parse_variable_intent(
    message: str,
    context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Parse a plain-English variable command into a structured intent dict.

    Returns ``{"action", "column", ...}`` on success, or ``None`` when the
    message is a question / not parseable as a mutation.
    """
    classifications = (context or {}).get("classifications") or []
    cols = [c.get("column", "") for c in classifications[:30] if c.get("column")]

    system = (
        f"You parse variable-management instructions for a statistical tool.\n"
        f"Available columns: {', '.join(cols) if cols else '(unknown)'}\n\n"
        f"If the input is an actionable mutation command, return ONLY this JSON:\n"
        f'{{"action":"rename"|"recode"|"exclude"|"include"|"set_type",'
        f'"column":"<exact column name from the list above>",'
        f'"new_name":"<str or null>",'
        f'"new_type":"scale"|"ordinal"|"nominal"|"id"|null,'
        f'"recode_map":{{}} }}\n'
        f"If the input is a question or explanation request, return exactly: null\n"
        f"Return ONLY the JSON object or null — no prose, no markdown."
    )

    # Gemini primary (fast JSON extraction)
    tokens = _MAX_TOKENS.get("variables", _DEFAULT_TOKENS)
    raw = await asyncio.to_thread(_gemini_call_sync, system, message, tokens)
    if raw is None:
        raw = await asyncio.to_thread(
            _openai_call_sync, system, message, tokens, _OPENAI_MODEL_STANDARD
        )
    if not raw:
        return None

    raw = raw.strip()
    if raw.lower() in ("null", "none", ""):
        return None

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
            }
    except (json.JSONDecodeError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# Study plan generator — description → rich plan JSON for screen-setup
# (Gemini primary — planning/routing; OpenAI fallback)
# ---------------------------------------------------------------------------

async def plan_study_setup(
    description: str,
    columns: List[str],
    classifications: List[Dict[str, Any]],
    n_rows: int = 0,
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

    system = (
        f"You are a biostatistics planning assistant. Dataset: {n_rows} rows.\n"
        f"Columns: {col_summary}\n\n"
        f"Return ONLY this JSON schema — no markdown, no prose:\n"
        f"{{\n"
        f'  "study_type": "comparison"|"correlation"|"association"|"survival"|"diagnostic"|"descriptive",\n'
        f'  "outcome_col": "<exact column name or null>",\n'
        f'  "predictors": ["<col>", ...],\n'
        f'  "objective": "<one clear plain-English sentence>",\n'
        f'  "sample_size": <integer or null>,\n'
        f'  "test_pairs": [\n'
        f'    {{"col_a":"<col>","col_b":"<col>","test_name":"<test>","reason":"<1 sentence>"}}\n'
        f'  ],\n'
        f'  "reasoning": "<2–3 sentence explanation>"\n'
        f"}}"
    )

    prompt = (description or "").strip() or "Suggest an appropriate study plan based on the columns."

    tokens = _MAX_TOKENS.get("setup", _DEFAULT_TOKENS)
    # Gemini primary for planning/routing
    raw = await asyncio.to_thread(_gemini_call_sync, system, prompt, tokens)
    if raw is None:
        raw = await asyncio.to_thread(
            _openai_call_sync, system, prompt, tokens, _OPENAI_MODEL_STANDARD
        )

    if not raw:
        return {
            "study_type": "descriptive",
            "outcome_col": None,
            "predictors": [],
            "objective":  "Describe the dataset variables.",
            "sample_size": n_rows or None,
            "test_pairs": [],
            "reasoning":  "AI service unavailable. Configure the analysis manually.",
            "confidence": 0,
            "source":     "fallback",
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
            "source":      "ai",
        }
    except (json.JSONDecodeError, ValueError):
        return {
            "study_type":  "descriptive",
            "outcome_col": None,
            "predictors":  [],
            "objective":   "Could not parse AI response.",
            "sample_size": None,
            "test_pairs":  [],
            "reasoning":   clean[:400] if clean else "",
            "confidence":  0,
            "source":      "parse_error",
        }
