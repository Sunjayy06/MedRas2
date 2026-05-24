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
    def has_copyleaks(self) -> bool:
        return bool(self.copyleaks_email and self.copyleaks_api_key)


settings = Settings()
