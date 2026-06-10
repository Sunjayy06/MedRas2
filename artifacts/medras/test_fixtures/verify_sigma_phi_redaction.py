"""Focused verification for Sigma external-AI PHI screening and fallback."""

import asyncio
from pathlib import Path

from app.services import ai_chatbox
from app.services.llm_client import provider_status_payload
from app.services.phi_redaction import screen_external_ai_payload


def verify_identifier_redaction() -> None:
    payload = {
        "description": (
            "Email: patient@example.com; phone +91 98765 43210; "
            "MRN: HOSP-778899; DOB: 01/02/1980; "
            "Aadhaar 1234 5678 9012; PAN ABCDE1234F; ID 1234567890."
        ),
        "columns": ["Age", "HER2 Score", "Tumor Stage", "MRN"],
    }
    result = screen_external_ai_payload(payload)
    rendered = result.value["description"]
    assert result.redaction_applied is True
    assert result.blocked is False
    assert "patient@example.com" not in rendered
    assert "98765 43210" not in rendered
    assert "HOSP-778899" not in rendered
    assert "01/02/1980" not in rendered
    assert "1234 5678 9012" not in rendered
    assert "ABCDE1234F" not in rendered
    assert "1234567890" not in rendered
    assert result.value["columns"] == payload["columns"]


def verify_high_risk_block() -> None:
    result = screen_external_ai_payload(
        "Patient name: Jane Example\nPatient address: 10 Main Street, Chennai"
    )
    assert result.redaction_applied is True
    assert result.blocked is True
    assert "Jane Example" not in result.value
    assert "10 Main Street" not in result.value

    status = provider_status_payload(
        "local_fallback", True, result.redaction_applied, result.blocked
    )
    assert status["phi_blocked"] is True
    assert status["redaction_applied"] is True
    assert "External AI was blocked" in status["provider_message"]


async def verify_chat_redacts_and_blocks_before_provider() -> None:
    original = ai_chatbox._call_llm
    captured = {}

    async def fake_call(kind: str, system: str, message: str):
        captured.update(kind=kind, system=system, message=message)
        return "Safe provider answer", "openai"

    async def must_not_call(*_args, **_kwargs):
        raise AssertionError("External provider called for blocked PHI")

    try:
        ai_chatbox._call_llm = fake_call
        reply = await ai_chatbox.chat(
            "normality",
            "Contact patient@example.com about Age.",
            {"columns": [{"column": "Age", "decision": "normal"}]},
            external_ai_consent=True,
        )
        assert "patient@example.com" not in captured["message"]
        assert reply["provider_status"] == "openai"
        assert reply["redaction_applied"] is True
        assert "redacted before external AI" in reply["provider_message"]

        ai_chatbox._call_llm = must_not_call
        blocked = await ai_chatbox.chat(
            "normality",
            "Patient name: Jane Example",
            {"columns": []},
            external_ai_consent=True,
        )
        assert blocked["provider_status"] == "local_fallback"
        assert blocked["phi_blocked"] is True
        assert "External AI was blocked" in blocked["provider_message"]
    finally:
        ai_chatbox._call_llm = original


def verify_scoped_routes_use_screening() -> None:
    root = Path(__file__).resolve().parents[1]
    sources = {
        "proposal": (root / "app/api/stats.py").read_text(encoding="utf-8"),
        "bridge": (root / "app/services/ai_bridge.py").read_text(encoding="utf-8"),
        "chat": (root / "app/services/ai_chatbox.py").read_text(encoding="utf-8"),
        "research_assistant": (
            root / "app/api/study_builder.py"
        ).read_text(encoding="utf-8"),
    }
    for source in sources.values():
        assert "screen_external_ai_payload" in source
    assert "log.info(prompt" not in "\n".join(sources.values())
    assert "log.info(message" not in "\n".join(sources.values())


async def main() -> None:
    verify_identifier_redaction()
    verify_high_risk_block()
    await verify_chat_redacts_and_blocks_before_provider()
    verify_scoped_routes_use_screening()
    print("Sigma PHI redaction verification passed.")


if __name__ == "__main__":
    asyncio.run(main())
