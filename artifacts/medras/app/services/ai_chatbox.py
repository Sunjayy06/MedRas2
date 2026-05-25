"""AI-powered chatboxes for Sigma — Variables / Normality / Plan / Results.

Gemini 2.5 Flash is the PRIMARY model (via asyncio.to_thread so the sync
SDK call doesn't block the event loop).  OpenAI gpt-4o-mini is the secondary
fallback, and the rule-based chatboxes.py engine is the last-resort fallback.

Public API
──────────
  await chat(kind, message, context)  → {"role", "text", "action"}
  await opening_message(kind, context) → str

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
_OPENAI_MODEL = "gpt-4o-mini"
_MAX_TOKENS_GEMINI = 600
_MAX_TOKENS_OPENAI = 600

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
        f"3. COMPARE tests when asked.\n\n"
        f"For ADD/REMOVE append this JSON on its own line at the end:\n"
        f'  {{"action": "add_test" or "remove_test", "test_id": "<exact_id>", "reason": "<sentence>"}}\n'
        f"For explanations: plain prose only, no JSON."
    )


def _results_system(context: Dict[str, Any]) -> str:
    results = (context or {}).get("results") or {}
    test_lines = "\n".join(
        "  • {}: {}".format(
            t.get("title", "?"),
            "; ".join(
                f"{r.get('label','?')}={r.get('value','?')}"
                for r in (t.get("rows") or [])[:4]
            )
        )
        for t in (results.get("tests") or [])[:10]
    ) or "  (results not yet available)"
    methods = (results.get("methods_md") or "")[:400]

    return (
        f"You are the Results Assistant in MedRAS Sigma.\n"
        f"Results summary:\n{test_lines}\n"
        f"Methods used:\n{methods if methods else '  (not available)'}\n\n"
        f"Your role:\n"
        f"1. Explain results in plain clinical language.\n"
        f"2. Help interpret p-values, effect sizes, ORs, HRs, CIs.\n"
        f"3. Explain test limitations.\n"
        f"4. If the researcher wants to ADD/REMOVE a test, append:\n"
        f'   {{"action": "rerun", "add_test_ids": [...], "remove_test_ids": [...]}}\n'
        f"   Valid add IDs: ttest_independent, mann_whitney, anova_oneway, kruskal_wallis, "
        f"chi_square, linear_regression, logistic_regression, pb_km, pb_cox, "
        f"pb_paired_t, pb_wilcoxon, pb_rm_anova, pb_kappa, ancova\n"
        f"Never change or challenge calculated values — only explain.\n"
        f"Plain prose for explanations (2–5 sentences), no JSON."
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
        "plan": _plan_system,
        "results": _results_system,
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
# Gemini 2.5 Flash (PRIMARY) — called in a thread pool via asyncio.to_thread
# ---------------------------------------------------------------------------

def _gemini_call_sync(system_prompt: str, message: str) -> Optional[str]:
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
                max_output_tokens=_MAX_TOKENS_GEMINI,
                temperature=0.4,
            ),
        )
        text = (response.text or "").strip()
        return text if text else None
    except Exception as exc:
        logger.info("Gemini chatbox call failed (%s) — trying secondary.", exc)
        return None


# ---------------------------------------------------------------------------
# OpenAI gpt-4o-mini (SECONDARY) — pure urllib, no asyncio needed
# ---------------------------------------------------------------------------

def _openai_call_sync(system_prompt: str, message: str) -> Optional[str]:
    """Synchronous OpenAI call — runs inline (short network hop)."""
    if not openai_is_configured():
        return None
    body = json.dumps({
        "model": _OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        "max_tokens": _MAX_TOKENS_OPENAI,
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
        text = data["choices"][0]["message"]["content"].strip()
        return text if text else None
    except Exception as exc:
        logger.info("OpenAI chatbox call failed (%s) — using rule-based.", exc)
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

    # 1. Gemini 2.5 Flash — PRIMARY (run sync call in thread pool)
    raw = await asyncio.to_thread(_gemini_call_sync, system_prompt, message)

    # 2. OpenAI gpt-4o-mini — SECONDARY
    if raw is None:
        raw = await asyncio.to_thread(_openai_call_sync, system_prompt, message)

    # 3. Rule-based engine — LAST RESORT (always available, no API key needed)
    if raw is None:
        logger.warning("Both LLM providers unavailable for kind=%r — rule-based fallback", kind)
        result = chatboxes.reply(kind, message, context)
        return {
            "role": result.get("role", "ai"),
            "text": result.get("text", ""),
            "action": None,
        }

    action = _extract_action(raw, kind)
    prose = _strip_action_json(raw)

    # For plan chatbox: embed action JSON in text so the FIX-R9 frontend
    # regex can parse it even if the `action` key is not consumed by the caller.
    display_text = prose
    if action and kind == "plan":
        json_embed = json.dumps({
            "action": action["action"],
            "test_id": action["test_id"],
            "reason": action.get("reason", ""),
        })
        display_text = (prose + "\n\n" + json_embed).strip() if prose else json_embed

    return {"role": "ai", "text": display_text, "action": action}


async def opening_message(kind: str, context: Dict[str, Any]) -> str:
    """Fast, context-aware opening message (uses rule-based path for speed)."""
    return chatboxes.opening_message(kind, context)
