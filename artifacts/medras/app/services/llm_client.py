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
        return genai.Client(api_key=key, http_options={"base_url": base_url})
    return genai.Client(api_key=key)
