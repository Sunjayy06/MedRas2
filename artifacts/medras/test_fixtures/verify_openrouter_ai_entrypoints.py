"""Static and mocked-network verification for MedRAS external-AI entry points."""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import settings
from app.services import (
    ai_narrative,
    llm_client,
    openrouter_client,
    study_builder_pico,
    study_design_advisor,
)


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


# ---------------------------------------------------------------------------
# Sigma AI narration polish (app.services.openrouter_client / ai_narrative)
# ---------------------------------------------------------------------------


def _settings_with(**overrides) -> SimpleNamespace:
    return dataclasses.replace(settings, **overrides)


def verify_missing_api_key_falls_back() -> None:
    """1. Missing API key -> deterministic fallback (chat_completion returns None)."""
    configured = _settings_with(sigma_ai_polish_enabled=True, openrouter_api_key=None)
    with patch.object(openrouter_client, "settings", configured):
        assert openrouter_client.chat_completion(model="openai/gpt-oss-120b:free", system="s", user="u") is None
        assert openrouter_client.is_configured() is False


def verify_polish_disabled_falls_back_even_with_key() -> None:
    """2. SIGMA_AI_POLISH_ENABLED=false -> deterministic fallback even if a key exists."""
    configured = _settings_with(sigma_ai_polish_enabled=False, openrouter_api_key="verification-secret")
    with patch.object(openrouter_client, "settings", configured):
        assert openrouter_client.chat_completion(model="openai/gpt-oss-120b:free", system="s", user="u") is None
        assert openrouter_client.is_configured() is False
    with patch.object(ai_narrative, "settings", configured):
        evidence = ai_narrative.build_evidence_pack("section_intro", "Title", "Some deterministic text.")
        assert ai_narrative.polish_writing(evidence) is None


def verify_writing_model_routes_chapter_v_polish() -> None:
    """3. OPENROUTER_WRITING_MODEL is used for Chapter V narrative polish."""
    configured = _settings_with(openrouter_writing_model="test/writing-model:free")
    with patch.object(ai_narrative, "settings", configured):
        assert ai_narrative.model_for_task("writing") == "test/writing-model:free"


def verify_proposal_model_routes_proposal_understanding_only() -> None:
    """4. OPENROUTER_PROPOSAL_MODEL is used for proposal-understanding paths only."""
    configured = _settings_with(openrouter_proposal_model="test/proposal-model:free")
    with patch.object(ai_narrative, "settings", configured):
        assert ai_narrative.model_for_task("proposal_understanding") == "test/proposal-model:free"
        assert ai_narrative.model_for_task("writing") != "test/proposal-model:free"
    # The existing Sigma proposal-parsing endpoint already routes through the
    # llm_client gateway's "proposal_parse" task, which maps to the same
    # OPENROUTER_PROPOSAL_MODEL field.
    assert llm_client._TASK_MODEL_FIELDS["proposal_parse"] == "openrouter_proposal_model"


def verify_reasoning_model_routes_audit_qa_only() -> None:
    """5. OPENROUTER_REASONING_MODEL is used for reasoning/audit QA only."""
    configured = _settings_with(openrouter_reasoning_model="test/reasoning-model:free")
    with patch.object(ai_narrative, "settings", configured):
        assert ai_narrative.model_for_task("reasoning_audit") == "test/reasoning-model:free"
        assert ai_narrative.model_for_task("writing") != "test/reasoning-model:free"


def verify_coding_and_vision_models_unused_in_chapter_v() -> None:
    """6 & 7. OPENROUTER_CODING_MODEL is never used in Sigma Chapter V export,
    and OPENROUTER_VISION_MODEL is never used unless a vision feature calls it."""
    assert "openrouter_coding_model" not in ai_narrative._TASK_MODEL_FIELDS.values()
    assert "openrouter_vision_model" not in ai_narrative._TASK_MODEL_FIELDS.values()
    for source_file in ("app/services/ai_narrative.py", "app/services/openrouter_client.py", "app/services/narrative_polish.py"):
        source = _text(source_file)
        assert "openrouter_coding_model" not in source
        assert "openrouter_vision_model" not in source
        assert "settings.openrouter_coding_model" not in source


def verify_free_model_validation() -> None:
    """8, 9, 10. Invalid paid models fall back to openrouter/free; ':free' models
    and the literal 'openrouter/free' catch-all are accepted as-is."""
    assert openrouter_client.is_free_model("openrouter/free") is True
    assert openrouter_client.is_free_model("openai/gpt-oss-120b:free") is True
    assert openrouter_client.is_free_model("openai/gpt-4") is False
    assert openrouter_client.is_free_model("anthropic/claude-3-opus") is False

    assert openrouter_client.resolve_model("openrouter/free") == "openrouter/free"
    assert openrouter_client.resolve_model("openai/gpt-oss-120b:free") == "openai/gpt-oss-120b:free"

    configured = _settings_with(openrouter_fallback_model="openrouter/free")
    with patch.object(openrouter_client, "settings", configured):
        assert openrouter_client.resolve_model("openai/gpt-4-paid") == "openrouter/free"

    # Even an (incorrectly) misconfigured fallback model must not let a paid
    # model id through — the hardcoded "openrouter/free" catch-all wins.
    misconfigured_fallback = _settings_with(openrouter_fallback_model="openai/gpt-4-paid")
    with patch.object(openrouter_client, "settings", misconfigured_fallback):
        assert openrouter_client.resolve_model("openai/gpt-4-paid") == "openrouter/free"


def verify_api_key_never_logged_or_exported() -> None:
    """11. API key never appears in logs, Word, PDF, Excel, frontend, or audit output."""
    secret = "verification-secret-sk-or-not-for-network-use"
    configured = _settings_with(sigma_ai_polish_enabled=True, openrouter_api_key=secret)

    class _FailingCompletions:
        def create(self, **kwargs):
            raise RuntimeError(f"simulated failure for key {secret}")

    class _FailingClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=_FailingCompletions())

    import logging

    logged_messages = []

    class _CapturingHandler(logging.Handler):
        def emit(self, record):
            logged_messages.append(record.getMessage())

    handler = _CapturingHandler()
    openrouter_client.log.addHandler(handler)
    try:
        with patch.object(openrouter_client, "settings", configured), patch("openai.OpenAI", _FailingClient):
            result = openrouter_client.chat_completion(model="openai/gpt-oss-120b:free", system="s", user="u")
    finally:
        openrouter_client.log.removeHandler(handler)
    assert result is None
    assert not any(secret in message for message in logged_messages), "API key leaked into a log message"

    # Export/audit/frontend code must never reference the key field at all —
    # only the narrow openrouter_client/llm_client gateways read it.
    for source_file in ("app/services/chapter_v_export.py", "app/services/export.py", "public/js/analysis.js"):
        assert "openrouter_api_key" not in _text(source_file)


def verify_validation_rejects_unsafe_ai_output() -> None:
    """12-16. AI polish output is rejected when it invents a number, changes a
    p-value/significance status, makes a forbidden causal/prognostic/risk-factor
    claim, or adds a literature citation."""
    original = (
        "ER showed a statistically significant association with the primary outcome. "
        "A chi-square test was used. The effect had a Cramér's V of 0.65, p = 0.002."
    )

    # 12. Invented number not present in the original.
    invented_number = original.replace("0.65", "0.65") + " A total of 42 additional cases were excluded."
    assert ai_narrative.validate_polish(original, invented_number) is False

    # 13. Changed p-value.
    changed_pvalue = original.replace("p = 0.002", "p = 0.04")
    assert ai_narrative.validate_polish(original, changed_pvalue) is False

    # 14. Changed significance status.
    changed_significance = original.replace(
        "showed a statistically significant association", "showed no statistically significant association"
    ).replace("statistically significant association", "association")
    flipped = (
        "ER was not statistically significant in its association with the primary outcome. "
        "A chi-square test was used. The effect had a Cramér's V of 0.65, p = 0.002."
    )
    assert ai_narrative.validate_polish(original, flipped) is False

    # 15. Forbidden causal/prognostic/independent/risk-factor claims.
    for forbidden_sentence in (
        original + " This proves ER drives outcomes.",
        "ER causes the observed outcome difference, with a Cramér's V of 0.65, p = 0.002.",
        "ER predicts the primary outcome, with a Cramér's V of 0.65, p = 0.002.",
        "ER carries prognostic significance for the primary outcome (Cramér's V 0.65, p = 0.002).",
        "ER showed an independent association with the primary outcome (Cramér's V 0.65, p = 0.002).",
        "ER conferred a survival benefit (Cramér's V 0.65, p = 0.002).",
        "ER was linked to increased mortality (Cramér's V 0.65, p = 0.002).",
        "ER is a risk factor for the primary outcome (Cramér's V 0.65, p = 0.002).",
    ):
        assert ai_narrative.validate_polish(original, forbidden_sentence) is False, forbidden_sentence

    # 16. Added literature/citation.
    with_citation = original + " (Smith et al., 2021)."
    assert ai_narrative.validate_polish(original, with_citation) is False

    # Sanity check: a genuinely safe rewording (same facts, same numbers) is accepted.
    safe_rewrite = (
        "A statistically significant association was observed between ER and the primary outcome. "
        "A chi-square test was used. The effect had a Cramér's V of 0.65, p = 0.002."
    )
    assert ai_narrative.validate_polish(original, safe_rewrite) is True


def verify_export_succeeds_when_openrouter_fails_or_times_out() -> None:
    """17. Export succeeds (falls back to deterministic text) when OpenRouter
    fails outright or times out."""
    configured = _settings_with(sigma_ai_polish_enabled=True, openrouter_api_key="verification-secret")

    class _TimeoutCompletions:
        def create(self, **kwargs):
            raise TimeoutError("simulated timeout")

    class _TimeoutClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=_TimeoutCompletions())

    with patch.object(openrouter_client, "settings", configured), patch("openai.OpenAI", _TimeoutClient):
        assert openrouter_client.chat_completion(model="openai/gpt-oss-120b:free", system="s", user="u") is None

    with patch.object(ai_narrative, "settings", configured), patch.object(
        openrouter_client, "settings", configured
    ), patch("openai.OpenAI", _TimeoutClient):
        evidence = ai_narrative.build_evidence_pack("section_intro", "Title", "Deterministic narration text.")
        assert ai_narrative.polish_writing(evidence) is None

    from app.services import chapter_v_export
    blob = chapter_v_export.generate_docx(
        {"thesis_analysis_blueprint": {
            "study_design": "Cross-sectional",
            "results_synthesis": "Overall, no significant association was detected.",
            "analysis_sections": [],
            "warnings": [],
        }, "tests": []},
        polish_overrides={},
    )
    assert blob[:2] == b"PK", "DOCX export must still succeed when AI polish is unavailable"


def main() -> None:
    from test_fixtures._network_guard import block_real_openrouter_calls
    with block_real_openrouter_calls():
        _run_all_checks()


def _run_all_checks() -> None:
    verify_entrypoint_registry()
    verify_no_direct_provider_calls()
    verify_model_routing_is_explicit()
    verify_frontend_safety_and_visible_failures()
    verify_backend_consent_boundaries()
    verify_mocked_openrouter_and_fallbacks()
    verify_no_key_in_provider_payload()
    verify_central_phi_guard()
    verify_missing_api_key_falls_back()
    verify_polish_disabled_falls_back_even_with_key()
    verify_writing_model_routes_chapter_v_polish()
    verify_proposal_model_routes_proposal_understanding_only()
    verify_reasoning_model_routes_audit_qa_only()
    verify_coding_and_vision_models_unused_in_chapter_v()
    verify_free_model_validation()
    verify_api_key_never_logged_or_exported()
    verify_validation_rejects_unsafe_ai_output()
    verify_export_succeeds_when_openrouter_fails_or_times_out()
    print(f"OpenRouter AI entry-point verification passed ({len(ENTRYPOINTS)} registered features).")


if __name__ == "__main__":
    main()
