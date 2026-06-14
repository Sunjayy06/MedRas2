"""Centralised runtime configuration for MedRAS.

All environment-variable access goes through this module so that route
handlers never touch ``os.environ`` directly. ``.env`` is loaded here, before
``Settings`` is instantiated, so that values from a project ``.env`` file are
available regardless of import ordering elsewhere.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()


def _split_csv(value: str | None, default: List[str]) -> List[str]:
    if not value:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    openai_api_key: str | None = field(default_factory=lambda: (
        os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    ))
    gemini_api_key: str | None = field(default_factory=lambda: (
        os.environ.get("AI_INTEGRATIONS_GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    ))
    openrouter_api_key: str | None = field(default_factory=lambda: os.environ.get("OPENROUTER_API_KEY"))
    openrouter_base_url: str = field(
        default_factory=lambda: os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    )
    openrouter_default_model: str = field(
        default_factory=lambda: os.environ.get("OPENROUTER_DEFAULT_MODEL", "openai/gpt-oss-120b:free")
    )
    openrouter_proposal_model: str = field(
        default_factory=lambda: os.environ.get("OPENROUTER_PROPOSAL_MODEL", "openai/gpt-oss-120b:free")
    )
    openrouter_reasoning_model: str = field(
        default_factory=lambda: os.environ.get(
            "OPENROUTER_REASONING_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free"
        )
    )
    openrouter_writing_model: str = field(
        default_factory=lambda: os.environ.get("OPENROUTER_WRITING_MODEL", "openai/gpt-oss-120b:free")
    )
    openrouter_coding_model: str = field(
        default_factory=lambda: os.environ.get("OPENROUTER_CODING_MODEL", "poolside/laguna-m.1:free")
    )
    openrouter_vision_model: str = field(
        default_factory=lambda: os.environ.get("OPENROUTER_VISION_MODEL", "google/gemma-4-31b-it:free")
    )
    openrouter_fallback_model: str = field(
        default_factory=lambda: os.environ.get("OPENROUTER_FALLBACK_MODEL", "openrouter/free")
    )
    copyleaks_email: str | None = field(default_factory=lambda: os.environ.get("COPYLEAKS_EMAIL"))
    copyleaks_api_key: str | None = field(default_factory=lambda: os.environ.get("COPYLEAKS_API_KEY"))
    cors_allow_origins: List[str] = field(
        default_factory=lambda: _split_csv(os.environ.get("MEDRAS_CORS_ORIGINS"), ["*"])
    )
    cors_allow_credentials: bool = field(
        default_factory=lambda: os.environ.get("MEDRAS_CORS_CREDENTIALS", "false").lower() == "true"
    )
    max_upload_bytes: int = 50 * 1024 * 1024  # 50MB
    max_document_words: int = 80_000          # ~200 pages

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def has_openrouter(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def has_copyleaks(self) -> bool:
        return bool(self.copyleaks_email and self.copyleaks_api_key)


settings = Settings()
