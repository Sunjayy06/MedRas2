"""Dependency-free verification for Sigma correlation normalized results."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List, Tuple


ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = ROOT / "app/services/results.py"


def _load_pair_adapter():
    source = RESULTS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_correlation_pair_presentation"
    )
    module = ast.Module(body=[function], type_ignores=[])
    namespace = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Tuple": Tuple,
        "_display_value": lambda value: "-" if value is None else f"{value:.3f}" if isinstance(value, float) else str(value),
        "_ci_from_row": lambda row: (
            f"{row['ci_lo']:.3f} to {row['ci_hi']:.3f}"
            if row.get("ci_lo") is not None and row.get("ci_hi") is not None
            else "-"
        ),
        "fmt_p": lambda value: f"{value:.3f}",
    }
    exec(compile(module, str(RESULTS_PATH), "exec"), namespace)
    return namespace["_correlation_pair_presentation"], source


def main() -> None:
    adapter, source = _load_pair_adapter()
    pair = {
        "predictor": "age",
        "test_result": {
            "test_name": "Pearson correlation",
            "method": "pearson",
            "stat": 0.81234,
            "ci_lo": 0.65,
            "ci_hi": 0.90,
            "p": 0.002,
            "n": 42,
        },
        "graph_uri": "data:image/png;base64,association",
        "desc_graph_uri": "data:image/png;base64,distribution",
        "png_data_uri": "data:image/png;base64,association",
        "interpretation": "Strong positive correlation.",
    }
    table, figures = adapter(pair, "score")
    assert table["title"] == "age vs score"
    assert table["headers"] == [
        "Variable 1", "Variable 2", "Test used", "Correlation coefficient",
        "95% CI", "p-value", "n", "Interpretation / strength",
    ]
    assert table["rows"][0][0:4] == [
        "age", "score", "Pearson correlation", "0.812",
    ]
    assert table["rows"][0][4] == "0.650 to 0.900"
    assert table["rows"][0][7] == "Strong positive correlation."
    assert len(figures) == 2
    assert all(figure["png_data_uri"].startswith("data:image/png;base64,") for figure in figures)

    categorical, _ = adapter({
        "predictor": "grade",
        "test_result": {
            "test_name": "Chi-square",
            "stat": 7.1,
            "cramers_v": 0.35,
            "p": 0.01,
            "n": 80,
        },
        "interpretation": "Moderate association.",
    }, "status")
    assert categorical["rows"][0][3] == "0.350"

    run_function = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "run_correlation_plan"
    )
    run_source = ast.get_source_segment(source, run_function) or ""
    assert '"pairs": pair_results' in run_source
    assert '"tables": normalized_tables' in run_source
    assert '"figures": normalized_figures' in run_source

    print("Sigma correlation normalized result verification passed.")


if __name__ == "__main__":
    main()
