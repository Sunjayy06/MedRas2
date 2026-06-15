"""Health and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> dict:
    """Reports which optional integrations are configured.

    Never returns the secret values themselves, only booleans.
    """
    return {
        "status": "ok",
        "integrations": {
            "openrouter_available": settings.has_openrouter,
            "copyleaks": settings.has_copyleaks,
        },
    }
