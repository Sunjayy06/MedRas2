"""Static and mocked-network verification for MedRAS external-AI entry points."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services import llm_client, study_builder_pico, study_design_advisor


ROOT = Path(__file__).resolve().parents[1]

ENTRYPOINTS = {
    "sigma_proposal_parser": ("app/api/stats.py", "/parse-proposal", "proposal_parse"),
    "sigma_chat_assistants": ("app/api/stats.py", "/chat/{kind}", "chat"),
    "sigma_ai_bridge": ("app/api/stats.py", "/ai-bridge", "study_setup"),
    "sigma_research_assistant": ("app/api/stats.py", "/ai-chat", "chat"),
    "helix_chat": ("app/api/study_builder.py", "/ask", "reasoning"),
    "helix_design_recommend": ("app/api/study_design.py", "/recommend", "reasoning"),
    "helix_methodology": ("app/api/study_design.py", "/methodology", "reasoning"),
    "proposal_generation": ("app/api/proposal.py", "/generate-rag-sections", "proposal_generation"),
    "proposal_section_generation": ("app/api/outline.py", "/generate", "proposal_generation"),
    "reference_suggestions": ("app/api/references.py", "/generate", "proposal_generation"),
    "thesis_drafting": ("app/api/thesis.py", "/draft-section", "thesis_writing"),
    "thesis_improvement": ("app/api/thesis.py", "/improve-section", "thesis_writing"),
    "thesis_abstract": ("app/api/thesis.py", "/draft-abstract", "thesis_writing"),
    "plagiarism_check_rewrite": ("app/api/plagiarism.py", "/check", "report_writing"),
    "plagiarism_citation_suggestions": ("app/api/plagiarism.py", "/suggest-citations", "reasoning"),
    "folio_feedback_parser": ("app/api/folio.py", "/parse-feedback", "reasoning"),
    "sample_size_objective_analyzer": ("app/api/sample_size.py", "/analyze", "reasoning"),
}


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def verify_entrypoint_registry() -> None:
    for name, (route_file, route, task) in ENTRYPOINTS.items():
        source = _text(route_file)
        assert route in source, f"{name}: route {route!r} is not registered"
        assert task in llm_client._TASK_MODEL_FIELDS, f"{name}: unknown model task {task!r}"


def verify_no_direct_provider_calls() -> None:
    forbidden = (
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "AI_INTEGRATIONS_OPENAI",
        "AI_INTEGRATIONS_GEMINI",
        "api.openai.com",
        "generativelanguage.googleapis.com",
        "api.anthropic.com",
        "from google.genai",
        "get_gemini_client(",
        "get_openai_client(",
        "openai_chat_url(",
    )
    allowed = {"app/services/llm_client.py"}
    violations = []
    for path in (ROOT / "app").rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        if relative in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in source:
                violations.append(f"{relative}: {token}")
    assert not violations, "Direct provider paths remain:\n" + "\n".join(violations)


def verify_model_routing_is_explicit() -> None:
    expected = {
        "app/services/study_builder_pico.py": 'task="reasoning"',
        "app/services/study_design_advisor.py": 'task="reasoning"',
        "app/services/citation_suggester.py": 'task="reasoning"',
        "app/services/report_parser.py": 'task="reasoning"',
        "app/services/doc_correction.py": 'task="reasoning"',
        "app/services/objective_analyzer.py": 'task="reasoning"',
        "app/services/proposal_generator.py": 'task="proposal_generation"',
        "app/services/proposal_export.py": 'task="proposal_generation"',
        "app/services/thesis_section_writer.py": 'task="thesis_writing"',
        "app/services/plagiarism_analyzer.py": 'task="report_writing"',
    }
    for filename, marker in expected.items():
        assert marker in _text(filename), f"{filename} lacks explicit {marker}"


def verify_frontend_safety_and_visible_failures() -> None:
    frontend = "\n".join(
        _text(path)
        for path in (
            "public/js/analysis.js",
            "public/js/medras-nav.js",
            "public/study-builder/js/sb.js",
            "public/study-builder/js/design.js",
            "public/study-builder/js/ra-drawer.js",
        )
    )
    assert "X-External-AI-Consent" in frontend
    assert "OpenRouter" in frontend
    assert "Request failed" in frontend or "unavailable" in frontend
    for secret_name in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        assert secret_name not in frontend


def verify_backend_consent_boundaries() -> None:
    fallback_routes = {
        "app/api/stats.py": "X-External-AI-Consent",
        "app/api/study_builder.py": "X-External-AI-Consent",
        "app/api/study_design.py": "X-External-AI-Consent",
    }
    required_routes = (
        "app/api/proposal.py",
        "app/api/outline.py",
        "app/api/references.py",
        "app/api/thesis.py",
        "app/api/plagiarism.py",
        "app/api/folio.py",
    )
    for filename, marker in fallback_routes.items():
        assert marker in _text(filename), f"{filename} does not read external-AI consent"
    for filename in required_routes:
        assert "require_external_ai_consent" in _text(filename), f"{filename} lacks a consent gate"


def verify_mocked_openrouter_and_fallbacks() -> None:
    captured = {}

    def fake_chat(**kwargs):
        captured.update(kwargs)
        return '{"population":"Adults","intervention":"A","comparison":"B","outcome":"C","search_queries":["safe query"]}'

    with patch.object(llm_client, "openrouter_is_configured", return_value=True), patch.object(
        llm_client, "openrouter_chat", side_effect=fake_chat
    ):
        # The service imports the function inside decompose, so patch the central gateway.
        result = asyncio.run(study_builder_pico.decompose("Compare A and B", [], True))
    assert result["search_queries"] == ["safe query"]
    assert captured["task"] == "reasoning"

    with patch.object(llm_client, "openrouter_is_configured", return_value=False):
        result = asyncio.run(study_builder_pico.decompose("Compare A and B", [], True))
    assert result["search_queries"], "No-key PICO fallback returned an empty result"

    result = asyncio.run(
        study_design_advisor.recommend_designs(
            "Describe prevalence", {}, "descriptive", external_ai_consent=False
        )
    )
    assert result["recommendations"], "No-consent design fallback returned no recommendations"


def verify_no_key_in_provider_payload() -> None:
    payload = llm_client.provider_status_payload("ai_unavailable", False)
    rendered = repr(payload)
    assert "API_KEY" not in rendered
    assert "OPENROUTER" not in rendered
    assert payload["provider_status"] == "ai_unavailable"


def verify_central_phi_guard() -> None:
    source = _text("app/services/llm_client.py")
    assert "screen_external_ai_payload" in source
    assert "if screening.blocked:" in source


def main() -> None:
    verify_entrypoint_registry()
    verify_no_direct_provider_calls()
    verify_model_routing_is_explicit()
    verify_frontend_safety_and_visible_failures()
    verify_backend_consent_boundaries()
    verify_mocked_openrouter_and_fallbacks()
    verify_no_key_in_provider_payload()
    verify_central_phi_guard()
    print(f"OpenRouter AI entry-point verification passed ({len(ENTRYPOINTS)} registered features).")


if __name__ == "__main__":
    main()
