"""Verify normalized diagnostic accuracy tables and ROC figure.

Run from artifacts/medras:
    python -m test_fixtures.verify_sigma_diagnostic_normalized
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import results  # noqa: E402


def verify_diagnostic_normalized_result() -> None:
    df = pd.DataFrame(
        {
            "disease": ["Positive"] * 20 + ["Negative"] * 20,
            "score": [0.70 + i * 0.01 for i in range(20)]
            + [0.10 + i * 0.01 for i in range(20)],
        }
    )

    raw = results.run_diagnostic_accuracy("disease", "score", {}, df)
    assert "error" not in raw
    original_auc = raw["auc"]
    original_auc_ci = raw["auc_ci"]
    original_confusion = dict(raw["confusion_matrix"])

    normalized = results.normalize_result_for_rendering(raw)
    tables = {table["title"]: table for table in normalized["tables"]}

    assert "Diagnostic Metrics" in tables
    assert "Confusion Matrix" in tables

    metrics = {row[0]: row[1:] for row in tables["Diagnostic Metrics"]["rows"]}
    for metric in (
        "AUC", "Sensitivity", "Specificity", "PPV", "NPV", "Accuracy",
        "LR+", "LR-", "Diagnostic odds ratio",
    ):
        assert metric in metrics
    assert metrics["AUC"][1] != "-"

    confusion = tables["Confusion Matrix"]
    assert confusion["headers"] == [
        "Actual / Predicted", "Predicted positive", "Predicted negative", "Total"
    ]
    assert confusion["rows"][0][1] == f"TP: {original_confusion['TP']}"
    assert confusion["rows"][0][2] == f"FN: {original_confusion['FN']}"
    assert confusion["rows"][1][1] == f"FP: {original_confusion['FP']}"
    assert confusion["rows"][1][2] == f"TN: {original_confusion['TN']}"

    figures = normalized["figures"]
    assert any(
        fig.get("title") == "ROC curve"
        and str(fig.get("png_data_uri", "")).startswith("data:image/png;base64,")
        for fig in figures
    )

    assert normalized["auc"] == original_auc
    assert normalized["auc_ci"] == original_auc_ci
    assert normalized["confusion_matrix"] == original_confusion


if __name__ == "__main__":
    verify_diagnostic_normalized_result()
    print("Sigma diagnostic normalized result verification passed.")
