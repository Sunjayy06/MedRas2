from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_JS = ROOT / "public" / "js" / "analysis.js"
ANALYSIS_HTML = ROOT / "public" / "analysis.html"


def _read_js() -> str:
    return ANALYSIS_JS.read_text(encoding="utf-8")


def _read_html() -> str:
    return ANALYSIS_HTML.read_text(encoding="utf-8")


def test_doctor_facing_eight_step_order() -> None:
    html = _read_html()
    expected = [
        "Objective",
        "Dataset",
        "Clean variables",
        "Choose analysis variables",
        "Review plan",
        "Run analysis",
        "Review results",
        "Download reports",
    ]
    labels = []
    for i in range(1, 9):
        marker = f'data-testid="dot-step-{i}"'
        assert marker in html
        fragment = html.split(marker, 1)[1].split("</li>", 1)[0]
        for label in expected:
            if label in fragment:
                labels.append(label)
                break
    assert labels == expected
    tracker = html.split('data-testid="step-tracker"', 1)[1].split("</ol>", 1)[0]
    assert "Normality" not in tracker


def test_missing_screen_is_resumable_and_step4_scoped() -> None:
    js = _read_js()
    assert '"missing"' in js
    assert '"missing": 3' in js
    assert '"analysis-vars": 4' in js
    assert '"normality": 5' in js
    assert '"plan": 5' in js
    assert '"run": 6' in js
    assert '"results": 7' in js
    assert '"export": 8' in js
    assert "missing_decisions: state.missingDecisions" in js
    assert "state.missingDecisions = saved.missing_decisions || {}" in js
    assert "selected_predictors: state.selectedPredictors" in js
    assert "subgroup_variables: state.subgroupVariables" in js


def test_show_screen_restores_saved_state() -> None:
    js = _read_js()
    assert "function restoreWizardScreenState" in js
    assert "restoreWizardScreenState(id)" in js
    assert 'if (id === "missing")' in js
    assert "renderMissingScreen()" in js
    assert "updateMissingScreenReadiness()" in js
    assert 'else if (id === "analysis-vars")' in js
    assert "renderAnalysisVariablesScreen()" in js
    assert 'else if (id === "plan" && state.plan)' in js
    assert 'else if (id === "results" && state.results)' in js
    assert "updateWizardTracker(id)" in js


def test_analysis_variable_selection_is_explicit_and_persisted() -> None:
    js = _read_js()
    html = _read_html()
    assert 'id="screen-analysis-vars"' in html
    assert "Choose one primary outcome" in js
    assert "Candidate predictors" in html
    assert "Subgroup / grouping variables" in html
    assert "function renderAnalysisVariablesScreen" in js
    assert "data-analysis-predictor" in js
    assert "data-analysis-subgroup" in js
    assert "predictors: state.selectedPredictors" in js
    assert "subgroup_variables: state.subgroupVariables" in js
    assert "Select at least one predictor" in js
    assert 'id="screen-run"' in html
    assert "showScreen(\"run\")" in js


def test_p27_workflow_uses_clinical_outcome_label_and_full_defaults() -> None:
    js = _read_js()
    html = _read_html()
    assert "function _p27ContextDetected" in js
    assert "p27 expression status" in js
    assert "function outcomeDisplayLabel" in js
    assert "_positiveNegativeOutcomeColumnName(column)" in js
    assert "Outcome: ${escapeHtml(displayOutcome)}" in js
    assert "Mapped from proposal concept" not in js
    assert "function doctorFacingStudyTypeLabel" in js
    assert "Cross-sectional association study" in js
    assert "function doctorFacingSetupReason" in js
    assert "text.includes(\"diagnostic\")" in js
    assert "text.includes(\"stale\")" in js
    assert "_p27DefaultPredictors(candidates)" in js
    assert "current.length < Math.min(8, expanded.length)" in js
    assert "selectedPredictorsTouched" in js
    assert "_isP27MarkerComponentColumn(c.column)" in js
    assert "p27 staining localization" in js
    assert "p27 staining score pattern" in js
    assert 'id="setup-study-type-display"' in html
    assert 'id="setup-outcome-display"' in html


def test_p27_subgroup_suggestions_do_not_use_outcome() -> None:
    js = _read_js()
    assert "function _defaultSubgroupSelection" in js
    assert "\"molecularsubtype\", \"nodalstatus\", \"histologicaltype\", \"histologicalgrade\", \"laterality\"" in js
    assert "\"er\", \"pr\", \"ar\", \"her2\", \"her2neu\", \"ki67\"" in js
    assert "!_positiveNegativeOutcomeColumnName(c.column)" in js
    assert "!(_p27ContextDetected() && _isP27MarkerComponentColumn(c.column))" in js
    assert "subgroupVariablesTouched" in js


def test_plan_preview_is_structured_with_collapsible_details() -> None:
    js = _read_js()
    html = _read_html()
    assert 'class="se-plan-summary"' in html
    assert "function _planSummaryHtml" in js
    assert 'data-testid="plan-structured-summary"' in js
    for label in [
        "Primary outcome:",
        "Study design:",
        "Sample size:",
        "Predictors selected:",
        "Subgroup variables:",
        "Descriptive outputs planned:",
        "Continuous predictors:",
        "Categorical predictors:",
        "Multiple testing:",
        "Graphs planned:",
    ]:
        assert label in js
    assert "summary.innerHTML = _planSummaryHtml(p)" in js
    assert "<details class=\"se-plan-section\" data-testid=\"plan-tests-section\">" in html
    assert "View detailed test list" in html
    assert "View detailed test list" in js
    assert "_displayAnalysisText(p.summary || \"\")" not in js


def test_normality_is_internal_to_plan_flow() -> None:
    js = _read_js()
    html = _read_html()
    assert "Internal test-choice rationale" in html
    assert "showScreen(\"normality\")" not in js
    assert "loadNormality();" not in js.split("function bindNormality", 1)[0]
    assert "showScreen(\"analysis-vars\")" in js
    assert "Parametric" in js and "Non-parametric" in js


def test_results_and_export_labels_are_doctor_facing() -> None:
    js = _read_js()
    html = _read_html()
    assert "Results chapter preview" in js
    assert "Thesis blueprint" not in js
    assert "Download Word Report" in html
    assert "Download PDF Report" in html
    assert "Download Cleaned Excel" in html
    chapter_block = html.split("button-chapter-v-word", 1)[0].rsplit('<div class="se-export-feature', 1)[-1]
    assert "is-hidden" in chapter_block and "hidden" in chapter_block
    assert 'id="ai-polish-consent-checkbox"' in html
    assert "checked" not in html.split('id="ai-polish-consent-checkbox"', 1)[0][-120:]


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
    test_doctor_facing_eight_step_order()
    test_missing_screen_is_resumable_and_step4_scoped()
    test_show_screen_restores_saved_state()
    test_analysis_variable_selection_is_explicit_and_persisted()
    test_p27_workflow_uses_clinical_outcome_label_and_full_defaults()
    test_p27_subgroup_suggestions_do_not_use_outcome()
    test_plan_preview_is_structured_with_collapsible_details()
    test_normality_is_internal_to_plan_flow()
    test_results_and_export_labels_are_doctor_facing()
    test_missing_decisions_are_persistent_and_idempotent()
    print("sigma wizard navigation state checks passed")
