"""Verify Sigma Missing Data Assistant context and conservative guidance."""

from pathlib import Path

from app.services import chatboxes


CONTEXT = {
    "columns": [
        {
            "column": "Age",
            "missing_count": 12,
            "missing_pct": 24.0,
            "detected_type": "scale",
            "selected_decision": "impute_median",
        },
        {
            "column": "Tumor Stage",
            "missing_count": 4,
            "missing_pct": 8.0,
            "detected_type": "ordinal",
            "selected_decision": "leave",
        },
    ],
    "supported_actions": [
        "drop_rows",
        "impute_mean",
        "impute_median",
        "impute_mode",
        "leave",
    ],
    "guidance_only": True,
}


def _reply(message: str) -> str:
    result = chatboxes.reply(
        "missing",
        message,
        CONTEXT,
        external_ai_consent=False,
    )
    assert result.get("action") is None
    return result["text"].lower()


def verify_column_context_and_guidance() -> None:
    text = _reply("What should I do about Age?")
    assert "12 missing value" in text
    assert "24.0%" in text
    assert "scale" in text
    assert "impute_median" in text
    assert "sensitivity analysis" in text
    assert "report it clearly" in text
    assert "chat will not apply" in text
    assert "exclude" not in text


def verify_supported_actions_only() -> None:
    text = _reply("What choices are supported?")
    for action in CONTEXT["supported_actions"]:
        assert action in text
    assert "exclude" not in text
    assert "do not impute automatically" in text
    assert "explicitly select and apply" in text


def verify_frontend_dedicated_route() -> None:
    source = Path("public/js/analysis.js").read_text(encoding="utf-8")
    assert 'kind: "missing"' in source
    assert "selected_decisions: state.missingDecisions || {}" in source
    assert 'kind: "variables", message: msg' not in source


def verify_backend_context_contract() -> None:
    source = Path("app/api/stats.py").read_text(encoding="utf-8")
    for field in (
        '"missing_count"',
        '"missing_pct"',
        '"detected_type"',
        '"selected_decision"',
        '"supported_actions"',
        '"guidance_only"',
    ):
        assert field in source


def main() -> None:
    verify_column_context_and_guidance()
    verify_supported_actions_only()
    verify_frontend_dedicated_route()
    verify_backend_context_contract()
    print("Sigma Missing Data Assistant verification passed.")


if __name__ == "__main__":
    main()
