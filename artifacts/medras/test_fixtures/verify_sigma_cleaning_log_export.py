from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
EXPORT_PATH = ROOT / "app/services/export.py"


def _load_cleaning_log_builder():
    source = EXPORT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_build_cleaning_log"
    )
    module = ast.Module(body=[function], type_ignores=[])
    namespace = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "clean_display_name": lambda value: str(value),
    }
    exec(compile(module, str(EXPORT_PATH), "exec"), namespace)
    return namespace["_build_cleaning_log"], source


def main() -> None:
    build_log, source = _load_cleaning_log_builder()
    meta = {
        "cleanup_notes": {
            "nodes": (
                "Derived lymph-node fields from fraction values: positive_nodes, "
                "total_nodes, node_ratio. Warning: 1 value looks Excel-corrupted."
            ),
            "status": (
                "String cleanup: trimmed/collapsed whitespace in 2 cell(s); "
                "normalised 1 missing marker(s)."
            ),
        },
        "cleaning_actions": [
            'Merged 1 near-duplicate label(s) in "status" to canonical "Yes".',
            "Trimmed whitespace in 1 column(s): status. 2 cell(s) standardised.",
        ],
        "quality_log": {"removed_rows": 1, "capped_values": 0, "kept": 0, "reviewed": 1},
        "yesno_cleaning_notes": {
            "status": "Standardised yes/no values to Yes and No.",
        },
        "missing_decision_actions": [
            "Imputed missing status with mode (Yes).",
        ],
        "variable_issues": [
            {
                "column": "nodes",
                "type": "node_fraction_warning",
                "message": "Review one likely Excel-corrupted node fraction.",
            },
        ],
    }
    log = build_log(meta, [])
    categories = {item["category"] for item in log}
    expected = {
        "Automatic normalization",
        "Category merge",
        "Missing-data decision",
        "Node-fraction derivation",
        "Quality review",
        "Quality warning",
        "Whitespace cleanup",
        "Yes/no standardization",
    }
    assert expected <= categories
    assert all(set(item) == {"category", "scope", "details"} for item in log)

    assert '_render_cleaning_log_docx(doc, session.get("cleaning_log") or [])' in source
    assert 'flow.append(Paragraph("Data Cleaning Log", h2))' in source
    assert 'wb.create_sheet("Data Cleaning Log")' in source
    assert "_build_cleaning_log(entry.meta or {}" in source
    stats_source = (ROOT / "app/api/stats.py").read_text(encoding="utf-8")
    stats_tree = ast.parse(stats_source)
    trim_endpoint = next(
        node
        for node in ast.walk(stats_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "trim_all_whitespace_endpoint"
    )
    trim_source = ast.get_source_segment(stats_source, trim_endpoint) or ""
    assert 'entry.meta["cleaning_actions"] = cleaning_actions' in trim_source

    print("Sigma cleaning-log export verification passed.")


if __name__ == "__main__":
    main()
