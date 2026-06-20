from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_JS = ROOT / "public" / "js" / "analysis.js"


def _read_js() -> str:
    return ANALYSIS_JS.read_text(encoding="utf-8")


def test_missing_screen_is_resumable_and_step4_scoped() -> None:
    js = _read_js()
    assert '"missing"' in js
    assert '"missing": 4' in js
    assert '"normality": 4' in js
    assert '"plan": 5' in js
    assert '"results": 6' in js
    assert '"export": 7' in js
    assert "missing_decisions: state.missingDecisions" in js
    assert "state.missingDecisions = saved.missing_decisions || {}" in js


def test_show_screen_restores_saved_state() -> None:
    js = _read_js()
    assert "function restoreWizardScreenState" in js
    assert "restoreWizardScreenState(id)" in js
    assert 'if (id === "missing")' in js
    assert "renderMissingScreen()" in js
    assert "updateMissingScreenReadiness()" in js
    assert 'else if (id === "plan" && state.plan)' in js
    assert 'else if (id === "results" && state.results)' in js
    assert "updateWizardTracker(id)" in js


def test_missing_decisions_are_persistent_and_idempotent() -> None:
    js = _read_js()
    assert "function _missingDecisionSignature" in js
    assert "function _missingDecisionsAlreadyApplied" in js
    assert "function _rememberAppliedMissingDecisions" in js
    assert "state.missingAppliedSignature" in js
    assert "state.missingDecisions[col] = selected" in js
    assert "state.missingDecisions[colKey] = existing" in js
    assert "_missingDecisionsAlreadyApplied(decisions)" in js
    assert "Missing-data decisions were already applied" in js
    assert "_rememberAppliedMissingDecisions(decisions)" in js
    apply_region = js.split("async function _applyQualityHandler()", 1)[1].split("function _toggleStickyStep4Buttons", 1)[0]
    missing_region = js.split("function renderMissingScreen()", 1)[1].split("function _renderMissingThread", 1)[0]
    assert "state.missingDecisions = {};" not in apply_region
    assert "state.missingDecisions = {};" not in missing_region


if __name__ == "__main__":
    test_missing_screen_is_resumable_and_step4_scoped()
    test_show_screen_restores_saved_state()
    test_missing_decisions_are_persistent_and_idempotent()
    print("sigma wizard navigation state checks passed")
