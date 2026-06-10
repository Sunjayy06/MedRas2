"""Static verification for critical Sigma preprocessing routing fixes."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def verify_frontend_routing() -> None:
    source = (ROOT / "public/js/analysis.js").read_text(encoding="utf-8")

    assert "fetchAndRenderClassifications" not in source
    assert "await loadVariablesData();" in source
    assert 'keep: "leave"' in source
    assert "decisions: missingDecisions" in source
    assert "decisions: state.missingDecisions" not in source
    assert "!actionMap[action]" in source
    assert "overrides: {}" not in source
    assert "async function refreshClassifications(overrides = []" in source
    assert "reclassify failure is non-fatal" not in source
    assert source.count("state.missingDecisions = {};") >= 4
    assert "${escapeHtml(c.cleanup_note)}" in source
    assert "We stripped text from this column and kept the numbers" not in source
    assert "c.cleanup_undo_available" in source
    assert "async function refreshClassifications(" in source
    assert "state.columns = state.classifications.map((c) => c.column);" in source
    assert "await refreshClassifications(overrides, { render: false, detectCategoryDupes: false });" in source
    assert "_detectCategoryDupes().catch(() => {})" not in source
    assert "Merge applied, but refresh failed" in source
    assert "Non-critical — fail silently" not in source
    assert source.count("await refreshClassifications(") >= 7


def verify_backend_invalidation() -> None:
    source = (ROOT / "app/api/stats.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    required = {
        "apply_quality",
        "classify",
        "variable_assistant_endpoint",
        "trim_all_whitespace_endpoint",
        "cleanup_undo",
        "confirm_study",
        "apply_missing_decisions",
        "apply_category_merge",
    }
    for name in required:
        segment = ast.get_source_segment(source, functions[name]) or ""
        assert "_invalidate_downstream(" in segment, f"{name} does not invalidate caches"

    helper = ast.get_source_segment(source, functions["_invalidate_downstream"]) or ""
    for key in ("normality", "plan", "results", "correlation_plan", "correlation_results"):
        assert key in helper, f"invalidation helper does not clear {key}"

    classify = ast.get_source_segment(source, functions["classify"]) or ""
    assert "for col in applied_cleanup_cols:" in classify
    assert 'c["cleanup_undo_available"] = c["column"] in cleanup_backups' in classify

    merge = ast.get_source_segment(source, functions["apply_category_merge"]) or ""
    for key in ("classifications", "variable_issues", "auto_coding_plan"):
        assert key in merge, f"category merge does not clear stale {key}"


def verify_whitespace_routing() -> None:
    source = (ROOT / "app/services/variable_issues.py").read_text(encoding="utf-8")
    merger_source = (ROOT / "app/services/category_merger.py").read_text(encoding="utf-8")
    assert "whitespace_normalised" in source
    assert "Same value contains inconsistent whitespace" in source
    assert ".str.strip().str.lower()" not in source
    assert "return _clean_basic(v).lower()" in merger_source


def main() -> None:
    verify_frontend_routing()
    verify_backend_invalidation()
    verify_whitespace_routing()
    print("Sigma preprocessing UI routing verification passed.")


if __name__ == "__main__":
    main()
