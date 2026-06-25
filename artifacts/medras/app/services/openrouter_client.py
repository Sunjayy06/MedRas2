"""Sigma-specific, free-model-only OpenRouter client.

This is deliberately independent of ``app.services.llm_client`` (the
Scriptorium-wide external-AI gateway used by proposal/thesis/plagiarism
features). Sigma's Chapter V AI narration polish has its own narrow,
auditable contract:

* Only OpenRouter ``:free`` models (or the literal ``openrouter/free``
  catch-all) may ever be requested — never a paid model.
* Timeout and max-token limits come from ``SIGMA_AI_POLISH_*`` settings,
  not the generic OpenRouter defaults used elsewhere.
* Every failure mode (missing key, disabled polish, timeout, rate limit,
  invalid response, network error, API error) returns ``None`` rather than
  raising, so callers always have a safe, uniform fallback path.
* The API key is read from settings and used only to build the
  Authorization header for the outgoing request — it is never logged,
  never included in an exception message, and never returned to a caller.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.core.config import settings

log = logging.getLogger(__name__)

_FREE_CATCH_ALL = "openrouter/free"


def is_free_model(model: Any) -> bool:
    """True only for the ``openrouter/free`` catch-all or a ``...:free`` model id."""
    text = str(model or "").strip()
    if not text:
        return False
    return text == _FREE_CATCH_ALL or text.endswith(":free")


def resolve_model(model: Any) -> str:
    """Return ``model`` if it passes free-model validation, else the configured
    fallback model (or the hardcoded ``openrouter/free`` catch-all if even the
    configured fallback is somehow not a free model)."""
    candidate = str(model or "").strip()
    if is_free_model(candidate):
        return candidate
    fallback = str(getattr(settings, "openrouter_fallback_model", "") or "")
    if is_free_model(fallback):
        return fallback
    return _FREE_CATCH_ALL


def is_configured() -> bool:
    return bool(settings.openrouter_api_key) and bool(settings.sigma_ai_polish_enabled)


def chat_completion(*, model: str, system: str, user: str) -> Optional[str]:
    """Run one OpenRouter chat-completions request and return plain text.

    Returns ``None`` (never raises) when AI polish is disabled, no API key
    is configured, the request times out, is rate-limited, fails on the
    network, returns an API error, or returns a response with no usable
    text content.
    """
    if not settings.sigma_ai_polish_enabled:
        return None
    if not settings.openrouter_api_key:
        return None

    resolved_model = resolve_model(model)

    try:
        from openai import OpenAI
    except ImportError:
        log.warning("openrouter_client: the 'openai' package is not installed")
        return None

    try:
        client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            timeout=float(settings.sigma_ai_polish_timeout_seconds),
        )
        response = client.chat.completions.create(
            model=resolved_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=settings.sigma_ai_polish_max_tokens,
            temperature=0.2,
        )
    except Exception:
        # Deliberately do not log the exception object/message: SDK and
        # transport-level errors can echo request details (including the
        # Authorization header) in their string representation.
        log.warning("openrouter_client: chat completion request failed")
        return None

    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError):
        return None
    if not isinstance(content, str) or not content.strip():
        return None
    return content.strip()
