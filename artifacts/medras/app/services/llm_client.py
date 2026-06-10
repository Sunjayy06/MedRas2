"""Central LLM client factory for MedRAS.

Automatically uses the Replit AI Integration proxy when managed env vars
(AI_INTEGRATIONS_OPENAI_BASE_URL / AI_INTEGRATIONS_GEMINI_BASE_URL) are
present, falling back to the user-supplied OPENAI_API_KEY / GEMINI_API_KEY.

IMPORTANT: Never cache the returned client objects — integration proxy
tokens can expire between requests.
"""

from __future__ import annotations

import os
from typing import Optional


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

def _openai_base_url() -> str:
    return os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL") or "https://api.openai.com/v1"


def _openai_api_key() -> str:
    return (
        os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")
        or os.environ.get("OPENAI_API_KEY", "")
    )


def openai_is_configured() -> bool:
    return bool(_openai_api_key())


def get_openai_client():
    """Return a fresh synchronous OpenAI SDK client."""
    from openai import OpenAI

    key = _openai_api_key()
    if not key:
        raise RuntimeError(
            "OpenAI is not configured. "
            "Set OPENAI_API_KEY or provision the AI Integrations for OpenAI."
        )
    return OpenAI(api_key=key, base_url=_openai_base_url())


def get_async_openai_client():
    """Return a fresh asynchronous AsyncOpenAI SDK client."""
    from openai import AsyncOpenAI

    key = _openai_api_key()
    if not key:
        raise RuntimeError(
            "OpenAI is not configured. "
            "Set OPENAI_API_KEY or provision the AI Integrations for OpenAI."
        )
    return AsyncOpenAI(api_key=key, base_url=_openai_base_url())


def openai_chat_url() -> str:
    """Full URL for the chat/completions endpoint (for raw httpx/urllib callers)."""
    return f"{_openai_base_url()}/chat/completions"


def openai_auth_header() -> str:
    """Authorization header value for raw httpx/urllib callers."""
    return f"Bearer {_openai_api_key()}"


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def _gemini_api_key() -> str:
    return (
        os.environ.get("AI_INTEGRATIONS_GEMINI_API_KEY")
        or os.environ.get("GEMINI_API_KEY", "")
    )


def _gemini_base_url() -> Optional[str]:
    return os.environ.get("AI_INTEGRATIONS_GEMINI_BASE_URL") or None


def gemini_is_configured() -> bool:
    return bool(_gemini_api_key())


def any_external_ai_configured() -> bool:
    """Return whether at least one supported external AI provider is configured."""
    return openai_is_configured() or gemini_is_configured()


def provider_status_message(
    provider_status: str,
    external_ai_consent: bool,
    redaction_applied: bool = False,
    phi_blocked: bool = False,
) -> str:
    """Return a consistent user-facing explanation of AI provider provenance."""
    if phi_blocked:
        message = (
            "External AI was blocked because high-risk sensitive identifiers were detected. "
            "Local fallback was used."
        )
    elif provider_status == "openai":
        message = "Answered using OpenAI."
    elif provider_status == "gemini":
        message = "Answered using Gemini."
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
    return {
        "provider_status": provider_status,
        "provider_message": provider_status_message(
            provider_status, external_ai_consent, redaction_applied, phi_blocked
        ),
        "redaction_applied": redaction_applied,
        "phi_blocked": phi_blocked,
    }


def get_gemini_client():
    """Return a fresh google-genai Client.

    Uses the Replit AI Integration proxy (AI_INTEGRATIONS_GEMINI_BASE_URL +
    AI_INTEGRATIONS_GEMINI_API_KEY) when available, otherwise falls back to
    the direct Gemini API with GEMINI_API_KEY.
    """
    from google import genai

    key = _gemini_api_key()
    if not key:
        raise RuntimeError(
            "Gemini is not configured. "
            "Set GEMINI_API_KEY or provision the AI Integrations for Gemini."
        )
    base_url = _gemini_base_url()
    if base_url:
        # Replit AI Integration proxy requires v1 (not the SDK default v1beta).
        return genai.Client(api_key=key, http_options={"api_version": "v1", "base_url": base_url})
    return genai.Client(api_key=key)
