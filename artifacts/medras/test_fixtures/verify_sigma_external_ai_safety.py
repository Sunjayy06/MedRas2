"""Focused verification for Sigma external-AI consent and provider transparency."""

import asyncio
import os
from pathlib import Path

from app.services import ai_bridge, ai_chatbox, chatboxes, study_builder_synthesizer
from app.services.llm_client import provider_status_message


def _must_not_call(*_args, **_kwargs):
    raise AssertionError("External provider was called without consent")


async def verify_no_consent_uses_local_fallback() -> None:
    original_call_llm = ai_chatbox._call_llm
    original_gemini = ai_chatbox._gemini_call_sync
    original_openai = ai_chatbox._openai_call_sync
    original_legacy_gemini = chatboxes._try_gemini
    original_legacy_openai = chatboxes._try_openai
    try:
        ai_chatbox._call_llm = _must_not_call
        chatboxes._try_gemini = _must_not_call
        chatboxes._try_openai = _must_not_call
        reply = await ai_chatbox.chat("normality", "Explain this", {}, False)
        assert reply["provider_status"] == "local_fallback"
        assert "not enabled" in reply["provider_message"]

        ai_chatbox._gemini_call_sync = _must_not_call
        ai_chatbox._openai_call_sync = _must_not_call
        plan = await ai_chatbox.plan_study_setup(
            "Compare groups", ["outcome"], [], 20, False
        )
        assert plan["provider_status"] == "local_fallback"
    finally:
        ai_chatbox._call_llm = original_call_llm
        ai_chatbox._gemini_call_sync = original_gemini
        ai_chatbox._openai_call_sync = original_openai
        chatboxes._try_gemini = original_legacy_gemini
        chatboxes._try_openai = original_legacy_openai


def verify_bridge_no_consent_and_provenance() -> None:
    original_openai = ai_bridge._call_openai
    original_gemini = ai_bridge._call_gemini
    try:
        ai_bridge._call_openai = _must_not_call
        ai_bridge._call_gemini = _must_not_call
        result = ai_bridge.identify_study(
            "Compare outcome between groups", "outcome", ["group", "outcome"],
            external_ai_consent=False,
        )
        assert result["provider_status"] == "local_fallback"
        assert result["source"] != "gemini"

        ai_bridge._call_openai = lambda *_args, **_kwargs: {
            "study_type": "comparison",
            "outcome_col": "outcome",
            "confidence": 0.9,
            "reasoning": "OpenAI result",
        }
        ai_bridge._call_gemini = _must_not_call
        result = ai_bridge.identify_study(
            "Compare outcome between groups", "outcome", ["group", "outcome"],
            external_ai_consent=True,
        )
        assert result["source"] == "openai"
        assert result["provider_status"] == "openai"
    finally:
        ai_bridge._call_openai = original_openai
        ai_bridge._call_gemini = original_gemini


async def verify_proposal_and_research_assistant_no_consent() -> None:
    root = Path(__file__).resolve().parents[1]
    stats_source = (root / "app/api/stats.py").read_text(encoding="utf-8")
    assert "async def _ai_extract(text: str, external_ai_consent: bool = False)" in stats_source
    assert "if not external_ai_consent:\n        return None, None" in stats_source

    original_gemini = study_builder_synthesizer._call_gemini_sync
    original_openai = study_builder_synthesizer._call_openai_sync
    try:
        study_builder_synthesizer._call_gemini_sync = _must_not_call
        study_builder_synthesizer._call_openai_sync = _must_not_call
        synth = await study_builder_synthesizer.synthesize(
            "What is the evidence?",
            [{"title": "Paper", "abstract": "A short abstract.", "year": 2024}],
            [],
            external_ai_consent=False,
        )
        assert synth["method"] == "raw_sources"
    finally:
        study_builder_synthesizer._call_gemini_sync = original_gemini
        study_builder_synthesizer._call_openai_sync = original_openai


async def verify_provider_status_is_reported() -> None:
    original_call_llm = ai_chatbox._call_llm
    try:
        async def fake_call(*_args, **_kwargs):
            return "Provider-backed answer", "openai"

        ai_chatbox._call_llm = fake_call
        reply = await ai_chatbox.chat("results", "Explain", {}, True)
        assert reply["provider_status"] == "openai"
        assert reply["provider_message"] == "Answered using OpenAI."
    finally:
        ai_chatbox._call_llm = original_call_llm


def verify_missing_key_message_and_no_frontend_keys() -> None:
    names = (
        "OPENAI_API_KEY", "GEMINI_API_KEY",
        "AI_INTEGRATIONS_OPENAI_API_KEY", "AI_INTEGRATIONS_GEMINI_API_KEY",
    )
    saved = {name: os.environ.pop(name, None) for name in names}
    try:
        message = provider_status_message("local_fallback", True)
        assert "no server API key is configured" in message
    finally:
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value

    root = Path(__file__).resolve().parents[1]
    frontend = (
        (root / "public/js/analysis.js").read_text(encoding="utf-8")
        + (root / "public/analysis.html").read_text(encoding="utf-8")
    )
    assert "OPENAI_API_KEY" not in frontend
    assert "GEMINI_API_KEY" not in frontend
    assert "X-External-AI-Consent" in frontend


async def main() -> None:
    await verify_no_consent_uses_local_fallback()
    verify_bridge_no_consent_and_provenance()
    await verify_proposal_and_research_assistant_no_consent()
    await verify_provider_status_is_reported()
    verify_missing_key_message_and_no_frontend_keys()
    print("Sigma external-AI safety verification passed.")


if __name__ == "__main__":
    asyncio.run(main())
