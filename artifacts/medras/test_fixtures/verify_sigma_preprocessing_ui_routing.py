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
    }
    for name in required:
        segment = ast.get_source_segment(source, functions[name]) or ""
        assert "_invalidate_downstream(" in segment, f"{name} does not invalidate caches"

    helper = ast.get_source_segment(source, functions["_invalidate_downstream"]) or ""
    for key in ("normality", "plan", "results", "correlation_plan", "correlation_results"):
        assert key in helper, f"invalidation helper does not clear {key}"


def main() -> None:
    verify_frontend_routing()
    verify_backend_invalidation()
    print("Sigma preprocessing UI routing verification passed.")


if __name__ == "__main__":
    main()
