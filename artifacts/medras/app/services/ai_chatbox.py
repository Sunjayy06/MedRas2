"""AI-powered chatboxes for Sigma — Normality / Plan / Results screens.

Uses OpenAI (gpt-4o-mini) as primary with rich context-aware system prompts.
Falls back to Gemini, then the rule-based chatboxes.py.

Return value: ``{"role": "ai", "text": str, "action": dict | None}``

Action shapes
─────────────
Plan:
  ``{"action": "add_test"|"remove_test", "test_id": str, "reason": str}``
Results:
  ``{"action": "rerun", "add_test_ids": [str], "remove_test_ids": [str]}``
Normality / Variables: always ``None`` (explanation only).
"""

from __future__ import annotations

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

_OPENAI_MODEL = "gpt-4o-mini"
_GEMINI_MODEL = "gemini-2.5-flash"
_MAX_TOKENS = 600

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
# System prompts (rich, context-injected)
# ---------------------------------------------------------------------------

def _normality_system(context: Dict[str, Any]) -> str:
    cols = (context or {}).get("columns") or []
    n = len(cols)
    normal = sum(1 for c in cols if c.get("decision") == "normal")
    nonnormal = n - normal

    col_lines = []
    for c in cols:
        p = c.get("p_value")
        p_str = "—" if p is None else ("<0.001" if p < 0.001 else f"{p:.3f}")
        col_lines.append(
            f"  • {c.get('column','?')}: {c.get('test','—')} p={p_str}, "
            f"skew={c.get('skewness','—')}, verdict={c.get('decision','—')}"
        )

    summary = "\n".join(col_lines) if col_lines else "  (no scale variables)"

    return f"""You are a biostatistics explainer embedded in MedRAS Sigma.
Your role: help medical researchers understand normality test results in plain English.

Dataset normality results ({n} scale variables, {normal} normal, {nonnormal} non-normal):
{summary}

Rules:
- Reply in 2–4 plain sentences. No bullet lists unless asked.
- Never perform calculations yourself — the engine calculated them.
- Do not override normality decisions; tell users to use the toggle in the table.
- Explain practical impact: which test family will be used as a result.
- If asked about a specific variable, reference its actual result above.
- Supportive tone for clinicians who are not statisticians.
- Reply with plain prose only — no markdown, no JSON.
"""


def _plan_system(context: Dict[str, Any]) -> str:
    plan = (context or {}).get("plan") or {}
    tests = plan.get("tests") or []
    test_lines = "\n".join(
        f"  • {t.get('id','?')}: {t.get('title','?')} — {t.get('why','')}"
        for t in tests
    )
    test_ids_in_plan = [t.get("id", "") for t in tests]

    return f"""You are the Plan Assistant in MedRAS Sigma, a statistical analysis engine for medical researchers.

Current analysis plan:
{test_lines if test_lines else "  (no tests yet)"}

Tests currently in plan: {", ".join(test_ids_in_plan) if test_ids_in_plan else "none"}
Valid test IDs you can add: {", ".join(sorted(_VALID_PLAN_TEST_IDS))}

Your role:
1. EXPLAIN what tests do in plain language for clinicians (2–4 sentences).
2. ADD or REMOVE tests from the plan on user request.
3. COMPARE two tests when asked.

For ADD or REMOVE requests you MUST append exactly this JSON on its own line at the end:
{{"action": "add_test" or "remove_test", "test_id": "<exact_valid_id>", "reason": "<one sentence>"}}

Use only IDs from the valid list. If the user's request maps to no valid ID, say so and omit JSON.
For pure explanations: reply with plain prose — no JSON at all.
Keep replies concise (3–5 sentences max).
"""


def _results_system(context: Dict[str, Any]) -> str:
    results = (context or {}).get("results") or {}
    tests_run = results.get("tests") or []
    test_lines = []
    for t in tests_run[:10]:
        rows = t.get("rows") or []
        key_stats = "; ".join(
            f"{r.get('label','?')}={r.get('value','?')}"
            for r in rows[:4]
        )
        test_lines.append(f"  • {t.get('title','?')}: {key_stats}")

    summary = "\n".join(test_lines) if test_lines else "  (results not yet available)"
    methods = (results.get("methods_md") or "")[:400]

    return f"""You are the Results Assistant in MedRAS Sigma.

Results summary:
{summary}

Methods used:
{methods if methods else "  (not available)"}

Your role:
1. Explain what results mean in plain clinical language.
2. Help interpret p-values, effect sizes, ORs, HRs, confidence intervals.
3. Explain limitations or assumptions of tests that were run.
4. If the researcher wants to ADD a new test or change the analysis, append on its own line:
   {{"action": "rerun", "add_test_ids": ["test_id"], "remove_test_ids": []}}
   Valid IDs: ttest_independent, mann_whitney, anova_oneway, kruskal_wallis,
   chi_square, linear_regression, logistic_regression, pb_km, pb_cox,
   pb_paired_t, pb_wilcoxon, pb_rm_anova, pb_kappa, ancova

Never change or challenge calculated values — only explain them.
For pure explanations: plain prose, 2–5 sentences, no JSON.
"""


def _variables_system(context: Dict[str, Any]) -> str:
    classifications = (context or {}).get("classifications") or []
    issues = (context or {}).get("issues") or []

    col_lines = "\n".join(
        f"  • {c.get('column','?')}: {c.get('detected_type','?')} "
        f"({c.get('unique_count','?')} unique, {c.get('missing_pct',0):.1f}% missing)"
        for c in classifications[:20]
    )
    issue_lines = "\n".join(
        f"  ⚠ {i.get('column','?')}: {i.get('message','')}"
        for i in issues[:8]
    ) if issues else "  (no issues)"

    return f"""You are the Variable Assistant in MedRAS Sigma.

Dataset columns:
{col_lines if col_lines else "  (none)"}

Detected issues:
{issue_lines}

Your role:
1. Suggest how to handle messy variables.
2. Explain what variable types mean (scale, ordinal, nominal, id, etc.).
3. Recommend which variables to exclude or recode.
4. For actionable changes, suggest the exact command the user should type.

Reply in plain, practical prose (2–4 sentences). No JSON output needed.
"""


def _build_system_prompt(kind: str, context: Dict[str, Any]) -> str:
    if kind == "normality":
        return _normality_system(context)
    if kind == "plan":
        return _plan_system(context)
    if kind == "results":
        return _results_system(context)
    if kind == "variables":
        return _variables_system(context)
    return "You are a helpful medical statistics assistant."


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
        action_val = obj.get("action")
        test_id = obj.get("test_id", "")
        if action_val in ("add_test", "remove_test") and test_id in _VALID_PLAN_TEST_IDS:
            return {"action": action_val, "test_id": test_id, "reason": obj.get("reason", "")}
        if action_val in ("add_test", "remove_test") and test_id:
            logger.warning("AI suggested invalid test_id %r — ignored", test_id)

    if kind == "results":
        if obj.get("action") == "rerun":
            return {
                "action": "rerun",
                "add_test_ids": obj.get("add_test_ids") or [],
                "remove_test_ids": obj.get("remove_test_ids") or [],
            }

    return None


def _strip_action_json(text: str) -> str:
    cleaned = re.sub(r'\n?\{[^{}]*"action"[^{}]*\}', '', text, flags=re.DOTALL)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# OpenAI call (primary)
# ---------------------------------------------------------------------------

def _openai_call(system_prompt: str, message: str) -> Optional[str]:
    """Call OpenAI gpt-4o-mini. Returns text on success, None on failure."""
    if not openai_is_configured():
        return None

    body = json.dumps({
        "model": _OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        "max_tokens": _MAX_TOKENS,
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
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.warning("OpenAI chatbox call failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Gemini call (secondary)
# ---------------------------------------------------------------------------

def _gemini_call(system_prompt: str, message: str) -> Optional[str]:
    """Call Gemini. Returns text on success, None on failure."""
    if not gemini_is_configured():
        return None
    try:
        from google.genai import types as genai_types
        client = get_gemini_client()
        full_prompt = system_prompt + f"\n\nUser: {message}\n\nAssistant:"
        response = client.models.generate_content(
            model=_GEMINI_MODEL,
            contents=full_prompt,
            config=genai_types.GenerateContentConfig(
                max_output_tokens=_MAX_TOKENS,
                temperature=0.4,
            ),
        )
        return (response.text or "").strip() or None
    except Exception as exc:
        logger.info("Gemini chatbox call failed: %s", exc)
        return None


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

    # Try OpenAI first (fastest and most reliable in this environment).
    raw = _openai_call(system_prompt, message)

    # Try Gemini as secondary.
    if raw is None:
        raw = _gemini_call(system_prompt, message)

    # Last resort: rule-based engine (always works, no API required).
    if raw is None:
        logger.warning("Both LLM providers failed for kind=%r — using rule-based fallback", kind)
        result = chatboxes.reply(kind, message, context)
        return {
            "role": result.get("role", "ai"),
            "text": result.get("text", ""),
            "action": None,
        }

    action = _extract_action(raw, kind)
    prose = _strip_action_json(raw)

    # For plan chatbox: also embed action JSON in the text so the existing
    # FIX R9 frontend regex can parse it even if `action` key is ignored.
    display_text = prose
    if action and kind == "plan":
        json_embed = json.dumps({
            "action": action["action"],
            "test_id": action["test_id"],
            "reason": action.get("reason", ""),
        })
        display_text = (prose + "\n\n" + json_embed).strip() if prose else json_embed

    return {
        "role": "ai",
        "text": display_text,
        "action": action,
    }


async def opening_message(kind: str, context: Dict[str, Any]) -> str:
    """Return a short context-aware opening message (uses fast rule-based path)."""
    return chatboxes.opening_message(kind, context)
