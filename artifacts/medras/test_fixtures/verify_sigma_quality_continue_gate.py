"""Static verification for Sigma Step 4 quality continue gating."""

from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "public/js/analysis.js").read_text(encoding="utf-8")
    html = (root / "public/analysis.html").read_text(encoding="utf-8")

    gate_start = source.index("function _updateQualityContinueGate()")
    gate_end = source.index("function _buildMissingDecisionPayload", gate_start)
    gate = source[gate_start:gate_end]

    assert "quality_score" not in gate
    assert "missingDecisions" not in gate
    assert "unresolvedActionable" in gate
    assert "btn.disabled = unresolvedActionable" in gate
    assert 'new Set(["keep", "remove", "cap", "review"])' in gate
    assert "Quality score is reduced due to missing data, but no blocking quality issues remain." in source
    assert "Quality score is reduced by non-blocking quality indicators; no blocking quality issues remain." in source
    assert 'data-testid="q-score-explanation"' in source
    assert "_updateQualityContinueGate();" in source
    assert 'data-testid="button-apply-quality"' in source
    assert 'data-testid="button-apply-quality-fallback"' in html
    assert 'data-testid="button-apply-quality"' not in html
    assert 'button-apply-quality-banner' not in source
    assert 'banner.querySelector(\'[data-action="apply-quality"]\')' in source
    assert 'btn.addEventListener("click", _applyQualityHandler)' in source
    assert "All decisions are required" not in html
    assert "defer the decision to the dedicated missing-data screen" in html

    print("Sigma Step 4 quality continue-gate verification passed.")


if __name__ == "__main__":
    main()
