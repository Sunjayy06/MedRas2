"""Verify OpenRouter configuration remains backend-only and secret-safe."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import patch

from app.api import health
from app.core.config import Settings


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_EXAMPLE = {
    "OPENROUTER_API_KEY": "",
    "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    "OPENROUTER_DEFAULT_MODEL": "openai/gpt-oss-120b:free",
    "OPENROUTER_PROPOSAL_MODEL": "openai/gpt-oss-120b:free",
    "OPENROUTER_REASONING_MODEL": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "OPENROUTER_WRITING_MODEL": "openai/gpt-oss-120b:free",
    "OPENROUTER_CODING_MODEL": "poolside/laguna-m.1:free",
    "OPENROUTER_VISION_MODEL": "google/gemma-4-31b-it:free",
    "OPENROUTER_FALLBACK_MODEL": "openrouter/free",
    "SIGMA_AI_POLISH_ENABLED": "false",
    "SIGMA_AI_POLISH_TIMEOUT_SECONDS": "20",
    "SIGMA_AI_POLISH_MAX_TOKENS": "800",
}


def _parse_example() -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        assert separator, f"Invalid .env.example line for {key!r}"
        parsed[key.strip()] = value.strip()
    return parsed


def verify_openrouter_config() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in gitignore
    assert ".env.*" in gitignore
    assert "!.env.example" in gitignore
    assert _parse_example() == EXPECTED_EXAMPLE

    env = {
        "OPENROUTER_API_KEY": "verification-secret-not-for-network-use",
        "OPENROUTER_BASE_URL": "https://example.invalid/openrouter/v1",
        "OPENROUTER_DEFAULT_MODEL": "test/default",
        "OPENROUTER_PROPOSAL_MODEL": "test/proposal",
        "OPENROUTER_REASONING_MODEL": "test/reasoning",
        "OPENROUTER_WRITING_MODEL": "test/writing",
        "OPENROUTER_CODING_MODEL": "test/coding",
        "OPENROUTER_VISION_MODEL": "test/vision",
        "OPENROUTER_FALLBACK_MODEL": "test/fallback",
    }
    with patch.dict(os.environ, env, clear=False):
        configured = Settings()
    assert configured.has_openrouter is True
    assert configured.openrouter_base_url == env["OPENROUTER_BASE_URL"]
    assert configured.openrouter_default_model == env["OPENROUTER_DEFAULT_MODEL"]
    assert configured.openrouter_proposal_model == env["OPENROUTER_PROPOSAL_MODEL"]
    assert configured.openrouter_reasoning_model == env["OPENROUTER_REASONING_MODEL"]
    assert configured.openrouter_writing_model == env["OPENROUTER_WRITING_MODEL"]
    assert configured.openrouter_coding_model == env["OPENROUTER_CODING_MODEL"]
    assert configured.openrouter_vision_model == env["OPENROUTER_VISION_MODEL"]
    assert configured.openrouter_fallback_model == env["OPENROUTER_FALLBACK_MODEL"]

    with patch.object(health, "settings", configured):
        readiness = asyncio.run(health.readyz())
    assert readiness["integrations"]["openrouter_available"] is True
    rendered = repr(readiness)
    assert env["OPENROUTER_API_KEY"] not in rendered
    assert env["OPENROUTER_BASE_URL"] not in rendered
    assert env["OPENROUTER_DEFAULT_MODEL"] not in rendered


if __name__ == "__main__":
    verify_openrouter_config()
    print("OpenRouter configuration verification passed.")
