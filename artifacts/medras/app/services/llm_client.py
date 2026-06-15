"""OpenRouter-only external LLM gateway for MedRAS.

All external LLM traffic must pass through this module. Legacy OpenAI/Gemini
factory names remain as compatibility adapters, but they use only OpenRouter
configuration and never read direct-provider API keys.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.core.config import settings


_TASK_MODEL_FIELDS = {
    "proposal_parse": "openrouter_proposal_model",
    "study_setup": "openrouter_reasoning_model",
    "variable_mapping": "openrouter_reasoning_model",
    "cleanup_suggestions": "openrouter_reasoning_model",
    "reasoning": "openrouter_reasoning_model",
    "report_writing": "openrouter_writing_model",
    "thesis_writing": "openrouter_writing_model",
    "proposal_generation": "openrouter_writing_model",
    "chat": "openrouter_default_model",
    "coding": "openrouter_coding_model",
    "vision": "openrouter_vision_model",
    "fallback": "openrouter_fallback_model",
}


def openrouter_is_configured() -> bool:
    return settings.has_openrouter


def openrouter_model_for_task(task: str) -> str:
    field = _TASK_MODEL_FIELDS.get(task, "openrouter_default_model")
    return str(getattr(settings, field))


def openrouter_chat_url() -> str:
    return f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"


def openrouter_auth_header() -> str:
    return f"Bearer {settings.openrouter_api_key or ''}"


def get_openrouter_client(*, async_client: bool = False):
    """Return a fresh OpenAI-compatible client configured for OpenRouter."""
    if not openrouter_is_configured():
        raise RuntimeError("OpenRouter is not configured. Set OPENROUTER_API_KEY.")
    if async_client:
        from openai import AsyncOpenAI

        return AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
        )
    from openai import OpenAI

    return OpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
    )


def openrouter_chat(
    *,
    task: str,
    system: str,
    user: str,
    max_tokens: int = 1000,
    temperature: float = 0.2,
    json_mode: bool = False,
) -> str:
    """Run one synchronous OpenRouter chat-completions request."""
    client = get_openrouter_client()
    kwargs: dict[str, Any] = {
        "model": openrouter_model_for_task(task),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Deprecated compatibility adapters
# ---------------------------------------------------------------------------

class _CompletionsAdapter:
    def __init__(self, completions):
        self._completions = completions

    def create(self, **kwargs):
        kwargs["model"] = openrouter_model_for_task("fallback")
        return self._completions.create(**kwargs)


class _AsyncCompletionsAdapter:
    def __init__(self, completions):
        self._completions = completions

    async def create(self, **kwargs):
        kwargs["model"] = openrouter_model_for_task("fallback")
        return await self._completions.create(**kwargs)


def get_openai_client():
    """Deprecated compatibility adapter backed exclusively by OpenRouter."""
    client = get_openrouter_client()
    return SimpleNamespace(
        chat=SimpleNamespace(completions=_CompletionsAdapter(client.chat.completions))
    )


def get_async_openai_client():
    """Deprecated async compatibility adapter backed exclusively by OpenRouter."""
    client = get_openrouter_client(async_client=True)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=_AsyncCompletionsAdapter(client.chat.completions))
    )


def openai_is_configured() -> bool:
    return openrouter_is_configured()


def openai_chat_url() -> str:
    return openrouter_chat_url()


def openai_auth_header() -> str:
    return openrouter_auth_header()


class _GeminiModelsAdapter:
    def generate_content(self, *, model: str, contents: Any, config: Any = None):
        del model
        max_tokens = int(getattr(config, "max_output_tokens", 1000) or 1000)
        temperature = float(getattr(config, "temperature", 0.2) or 0.2)
        mime = str(getattr(config, "response_mime_type", "") or "")
        text = openrouter_chat(
            task="fallback",
            system="Follow the user's instructions accurately.",
            user=str(contents),
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=mime == "application/json",
        )
        return SimpleNamespace(text=text)


class _GeminiCompatibilityAdapter:
    def __init__(self):
        self.models = _GeminiModelsAdapter()


def get_gemini_client():
    """Deprecated Gemini-shaped adapter backed exclusively by OpenRouter."""
    if not openrouter_is_configured():
        raise RuntimeError("OpenRouter is not configured. Set OPENROUTER_API_KEY.")
    return _GeminiCompatibilityAdapter()


def gemini_is_configured() -> bool:
    return openrouter_is_configured()


def any_external_ai_configured() -> bool:
    return openrouter_is_configured()


def provider_status_message(
    provider_status: str,
    external_ai_consent: bool,
    redaction_applied: bool = False,
    phi_blocked: bool = False,
) -> str:
    if phi_blocked:
        message = (
            "External AI was blocked because high-risk sensitive identifiers were detected. "
            "Local fallback was used."
        )
    elif provider_status in {"openrouter", "openai", "gemini"}:
        message = "Answered using OpenRouter."
    elif not external_ai_consent:
        message = "External AI is not enabled for this dataset/session. Local fallback was used."
    elif not any_external_ai_configured():
        message = (
            "External AI is unavailable because no server API key is configured. "
            "Local fallback was used."
        )
    elif provider_status == "ai_unavailable":
        message = "External AI was unavailable and no local fallback could complete the request."
    else:
        message = "External AI was unavailable. Local fallback was used."
    if redaction_applied and phi_blocked:
        message += " Sensitive identifiers were redacted before local processing."
    elif redaction_applied:
        message += " Sensitive identifiers were redacted before external AI."
    return message


def provider_status_payload(
    provider_status: str,
    external_ai_consent: bool,
    redaction_applied: bool = False,
    phi_blocked: bool = False,
) -> dict:
    normalized = "openrouter" if provider_status in {"openrouter", "openai", "gemini"} else provider_status
    return {
        "provider_status": normalized,
        "provider_message": provider_status_message(
            normalized, external_ai_consent, redaction_applied, phi_blocked
        ),
        "redaction_applied": redaction_applied,
        "phi_blocked": phi_blocked,
    }
