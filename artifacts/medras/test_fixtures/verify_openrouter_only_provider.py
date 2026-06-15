"""Verify OpenRouter is the only external LLM path without making network calls."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

from app.api import stats
from app.services import ai_chatbox, llm_client, proposal_generator, thesis_section_writer


ROOT = Path(__file__).resolve().parents[1]


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        has_openrouter=True,
        openrouter_api_key="verification-secret",
        openrouter_base_url="https://openrouter.example/v1",
        openrouter_default_model="model/default",
        openrouter_proposal_model="model/proposal",
        openrouter_reasoning_model="model/reasoning",
        openrouter_writing_model="model/writing",
        openrouter_coding_model="model/coding",
        openrouter_vision_model="model/vision",
        openrouter_fallback_model="model/fallback",
    )


class _FakeCompletions:
    def __init__(self) -> None:
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
        )


def verify_client_and_model_routing() -> None:
    fake = _FakeCompletions()
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    configured = _settings()
    expected = {
        "proposal_parse": "model/proposal",
        "study_setup": "model/reasoning",
        "variable_mapping": "model/reasoning",
        "cleanup_suggestions": "model/reasoning",
        "report_writing": "model/writing",
        "thesis_writing": "model/writing",
        "proposal_generation": "model/writing",
        "chat": "model/default",
        "coding": "model/coding",
        "vision": "model/vision",
        "fallback": "model/fallback",
    }
    with patch.object(llm_client, "settings", configured):
        for task, model in expected.items():
            assert llm_client.openrouter_model_for_task(task) == model
        assert llm_client.openrouter_chat_url() == "https://openrouter.example/v1/chat/completions"
        assert llm_client.openrouter_auth_header() == "Bearer verification-secret"
        constructor_args = {}

        def fake_constructor(**kwargs):
            constructor_args.update(kwargs)
            return fake_client

        with patch.dict(
            sys.modules,
            {"openai": SimpleNamespace(OpenAI=fake_constructor, AsyncOpenAI=fake_constructor)},
        ):
            assert llm_client.get_openrouter_client() is fake_client
        assert constructor_args == {
            "api_key": "verification-secret",
            "base_url": "https://openrouter.example/v1",
        }
        with patch.object(llm_client, "get_openrouter_client", return_value=fake_client):
            text = llm_client.openrouter_chat(
                task="proposal_parse",
                system="system",
                user="user",
                json_mode=True,
            )
    assert text == '{"ok": true}'
    assert fake.kwargs["model"] == "model/proposal"
    assert fake.kwargs["messages"][1]["content"] == "user"
    assert fake.kwargs["response_format"] == {"type": "json_object"}


def verify_proposal_parse_consent_and_phi_guards() -> None:
    calls = []

    def fake_chat(**kwargs):
        calls.append(kwargs)
        return '{"objective":"Assess outcome","outcomes":"Outcome","study_type":"association"}'

    with (
        patch.object(stats, "_openrouter_is_configured", return_value=True),
        patch.object(stats, "_openrouter_chat", side_effect=fake_chat),
    ):
        result = asyncio.run(stats._ai_extract("A safe proposal", external_ai_consent=True))
        assert result[1] == "openrouter"
        assert calls[0]["task"] == "proposal_parse"

        calls.clear()
        result = asyncio.run(stats._ai_extract("A safe proposal", external_ai_consent=False))
        assert result[0] is None
        assert not calls

        calls.clear()
        with patch.object(stats, "_openrouter_is_configured", return_value=False):
            result = asyncio.run(stats._ai_extract("A safe proposal", external_ai_consent=True))
        assert result[0] is None
        assert not calls

        calls.clear()
        with patch.object(
            stats,
            "_screen_external_ai_payload",
            return_value=SimpleNamespace(
                blocked=True, redaction_applied=True, value="[BLOCKED]"
            ),
        ):
            result = asyncio.run(stats._ai_extract("MRN 123456789", external_ai_consent=True))
        assert result[0] is None and result[3] is True
        assert not calls


def verify_chat_consent_and_fallback() -> None:
    async def fake_llm(kind, system, message):
        return "OpenRouter response", "openrouter"

    with patch.object(ai_chatbox, "_call_llm", side_effect=fake_llm):
        response = asyncio.run(
            ai_chatbox.chat("variables", "Explain Age", {}, external_ai_consent=True)
        )
        assert response["provider_status"] == "openrouter"

    with patch.object(ai_chatbox, "_call_llm", side_effect=AssertionError("must not call")):
        response = asyncio.run(
            ai_chatbox.chat("variables", "Explain Age", {}, external_ai_consent=False)
        )
        assert response["provider_status"] == "local_fallback"

    with patch.object(ai_chatbox, "openrouter_is_configured", return_value=False):
        response = asyncio.run(
            ai_chatbox.chat("variables", "Explain Age", {}, external_ai_consent=True)
        )
        assert response["provider_status"] == "local_fallback"


def verify_writing_task_routing() -> None:
    calls = []

    def fake_chat(**kwargs):
        calls.append(kwargs)
        return '{"sections":{},"suggestions":[]}'

    with patch.object(llm_client, "openrouter_chat", side_effect=fake_chat):
        proposal_generator._call_openai_json("system", "user")
        thesis_section_writer._call_openai_json("system", "user")
    assert calls[0]["task"] == "proposal_generation"
    assert calls[1]["task"] == "thesis_writing"


def verify_no_direct_provider_configuration() -> None:
    forbidden = (
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "AI_INTEGRATIONS_OPENAI_API_KEY",
        "AI_INTEGRATIONS_GEMINI_API_KEY",
        "api.openai.com",
        "generativelanguage.googleapis.com",
    )
    for path in (ROOT / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text, f"Direct-provider marker remains in {path}: {marker}"

    payload = llm_client.provider_status_payload("openai", True)
    assert payload["provider_status"] == "openrouter"
    assert "OpenRouter" in payload["provider_message"]
    assert "verification-secret" not in repr(payload)


def verify_openrouter_only_provider() -> None:
    verify_client_and_model_routing()
    verify_proposal_parse_consent_and_phi_guards()
    verify_chat_consent_and_fallback()
    verify_writing_task_routing()
    verify_no_direct_provider_configuration()


if __name__ == "__main__":
    verify_openrouter_only_provider()
    print("OpenRouter-only provider verification passed.")
