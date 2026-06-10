"""Dependency-free checks for Sigma AI action confirmation boundaries."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATS = (ROOT / "app/api/stats.py").read_text(encoding="utf-8")
JS = (ROOT / "public/js/analysis.js").read_text(encoding="utf-8")


def _section(text: str, start: str, end: str) -> str:
    return text[text.index(start):text.index(end, text.index(start))]


def verify_variable_assistant_preview_then_apply() -> None:
    section = _section(STATS, "class VariableAssistantRequest", "# Trim-all whitespace")
    assert "confirmed_action: Optional[Dict[str, Any]] = None" in section
    assert '"status": "preview"' in section
    assert '"confirmed_action": intent' in section
    assert 'entry.meta["pending_variable_assistant_action"] = intent' in section
    assert 'entry.meta.get("pending_variable_assistant_action") != intent' in section
    assert section.index('"status": "preview"') < section.index(
        "new_df, meta = variable_assistant.apply_action"
    )

    js_section = _section(JS, "async function sendAssistantMessage", "/* ----- Confirm validation")
    assert 'if (res.status === "preview")' in js_section
    assert "confirmAIStateChange(" in js_section
    assert "confirmed_action: res.confirmed_action" in js_section
    assert "Cancelled. No variable or preprocessing changes were made." in js_section


def verify_plan_and_result_actions_require_confirmation() -> None:
    plan = _section(JS, "function handlePlanChatResponse", "// Results chatbox handler")
    assert plan.index("confirmAIStateChange(") < plan.index("addTestToPlanLocal(")
    remove_confirm = plan.index("confirmAIStateChange(", plan.index('action.action === "remove_test"'))
    assert remove_confirm < plan.index("removeTestFromPlanLocal(")

    results = _section(JS, "async function handleResultsChatResponse", "function addTestToPlanLocal")
    assert results.index("confirmAIStateChange(") < results.index('api("/rerun-partial"')
    assert "Cancelled. Results were not re-run or replaced." in results


def verify_setup_suggestions_are_not_persisted_before_confirmation() -> None:
    assert 'entry.meta["ai_study"] = result' not in STATS
    confirm = _section(STATS, "async def confirm_study", "# Run Correlation")
    assert 'entry.meta["ai_study"] = {' in confirm
    assert '"source": "confirmed"' in confirm

    for label in (
        "AI suggested replacing the current study plan",
        "AI suggested revising the current study plan",
        "AI suggested changing the analysis setup",
        "AI suggested replacing the study setup",
        "AI suggested changing setup and re-running results",
    ):
        assert label in JS


def verify_syntax() -> None:
    ast.parse(STATS)
    ast.parse((ROOT / "test_fixtures/verify_sigma_ai_action_confirmation.py").read_text(encoding="utf-8"))


def main() -> None:
    verify_variable_assistant_preview_then_apply()
    verify_plan_and_result_actions_require_confirmation()
    verify_setup_suggestions_are_not_persisted_before_confirmation()
    verify_syntax()
    print("Sigma AI action confirmation verification passed.")


if __name__ == "__main__":
    main()
