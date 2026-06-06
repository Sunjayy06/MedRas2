"""Verify normalized chi-square/Fisher contingency tables.

Run from artifacts/medras:
    python test_fixtures/verify_sigma_chi_fisher_normalized.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import results  # noqa: E402


def _table_titles(result: dict) -> list[str]:
    return [t.get("title") for t in result.get("tables") or []]


def _summary_rows(result: dict) -> dict:
    summary = next(t for t in result["tables"] if t["title"] == "Test summary")
    return {row[0]: row[1] for row in summary["rows"]}


def verify_legacy_chi_square_adapter() -> None:
    df = pd.DataFrame(
        {
            "outcome": ["Alive"] * 20 + ["Dead"] * 20,
            "marker": ["Negative"] * 12 + ["Positive"] * 8 + ["Negative"] * 5 + ["Positive"] * 15,
        }
    )
    raw = results._chi_square(df, "outcome", "marker")
    raw.update({"id": "chi_square", "title": "Chi-square", "test_type": "chi_square"})

    normalized = results.normalize_result_for_rendering(raw)
    titles = _table_titles(normalized)

    assert "Observed counts" in titles
    assert "Expected counts" in titles
    assert "Row percentages" in titles
    assert "Column percentages" in titles
    assert "Test summary" in titles

    observed = next(t for t in normalized["tables"] if t["title"] == "Observed counts")
    assert observed["headers"] == ["Category", "Negative", "Positive", "Total"]
    assert observed["rows"][-1] == ["Total", "17", "23", "40"]

    summary = _summary_rows(normalized)
    assert summary["Test used"] == "Chi-square test"
    assert summary["df"] == "1"
    assert summary["Cramer's V / effect size"] != "-"


def verify_smart_fisher_adapter_sparse_warning() -> None:
    df = pd.DataFrame(
        {
            "disease": ["Yes"] * 4 + ["No"] * 6,
            "exposure": ["Positive", "Positive", "Positive", "Negative"] + ["Negative"] * 6,
        }
    )
    raw = results.run_chi_or_fisher("disease", "exposure", session={}, df=df)
    raw.update({"id": "pc_chi_fisher", "title": "Fisher exact", "plan_name": "Fisher exact"})

    normalized = results.normalize_result_for_rendering(raw)
    titles = _table_titles(normalized)

    assert normalized["test_type"] == "fisher_exact"
    assert "Observed counts" in titles
    assert "Expected counts" in titles
    assert "Row percentages" in titles
    assert "Column percentages" in titles

    summary = _summary_rows(normalized)
    assert summary["Test used"] == "Fisher's exact test"
    assert "< 5" in summary["Expected-count / sparse-cell warning"]
    assert summary["p-value"].startswith("p")


if __name__ == "__main__":
    verify_legacy_chi_square_adapter()
    verify_smart_fisher_adapter_sparse_warning()
    print("Sigma chi-square/Fisher normalized table verification passed.")
