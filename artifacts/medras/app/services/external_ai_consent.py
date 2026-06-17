"""Shared request-boundary guard for routes that require external AI."""

from fastapi import HTTPException, Request


def require_external_ai_consent(request: Request) -> None:
    if request.headers.get("X-External-AI-Consent", "").lower() != "true":
        raise HTTPException(
            status_code=409,
            detail=(
                "External AI is not enabled for this session. Grant consent before "
                "sending text to OpenRouter, or use a feature with a local fallback."
            ),
        )
