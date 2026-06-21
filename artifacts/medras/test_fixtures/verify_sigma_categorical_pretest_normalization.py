"""Verify Sigma categorical pre-test normalization and chi/Fisher selection.

Run from artifacts/medras:
    python -m test_fixtures.verify_sigma_categorical_pretest_normalization
"""

from __future__ import annotations

import pandas as pd

from app.services.results import run_chi_or_fisher


def _session() -> dict:
    return {
        "assignment": {"outcome": "Positive/ Negative"},
        "main_outcome_concept": "p27 expression status",
        "main_marker": "p27",
        "category_merge_actions": [],
    }


def _binary_sparse_df() -> pd.DataFrame:
    return pd.DataFrame({
        "Positive/ Negative": ["Yes"] * 8 + ["No"] * 4,
        "ER": ["Postive"] * 2 + ["Positive"] * 4 + ["Negative"] * 6,
        "PR": ["Postive"] + ["Positive"] * 5 + ["Negative"] * 6,
        "AR": ["Postive"] + ["Positive"] * 5 + ["Negative"] * 6,
    })


def _assert_binary_fisher(marker: str) -> None:
    df = _binary_sparse_df()
    session = _session()
    result = run_chi_or_fisher(marker, "Positive/ Negative", session, df)
    assert result["test_type"] == "fisher_exact", result
    assert result["actual_test_used"] == "Fisher's exact test", result
    assert result["dof"] is None, result
    assert result["observed_table"] and len(result["observed_table"]) == 2, result["observed_table"]
    assert len(result["observed_table"][0]) == 2, result["observed_table"]
    assert result["row_labels"] == ["Negative", "Positive"], result["row_labels"]
    assert result["col_labels"] == ["Negative", "Positive"], result["col_labels"]
    assert "expected cell counts were below 5" in result["note"]
    assert any(
        item.get("variable") == marker
        and item.get("original_category") == "Postive"
        and item.get("cleaned_category") == "Positive"
        and item.get("decision_type") == "pretest_category_normalization"
        for item in session["category_merge_actions"]
    ), session["category_merge_actions"]


def test_binary_markers_use_fisher_after_normalization() -> None:
    for marker in ("ER", "PR", "AR"):
        _assert_binary_fisher(marker)


def test_non_sparse_2x2_chi_square_has_df_1() -> None:
    df = pd.DataFrame({
        "Outcome": ["Yes"] * 20 + ["No"] * 20,
        "Marker": ["Positive"] * 10 + ["Negative"] * 10 + ["Positive"] * 10 + ["Negative"] * 10,
    })
    session = {"assignment": {"outcome": "Outcome"}, "main_outcome_concept": "Marker status"}
    result = run_chi_or_fisher("Marker", "Outcome", session, df)
    assert result["test_type"] == "chi_square", result
    assert result["dof"] == 1, result
    assert result["observed_table"] == [[10, 10], [10, 10]], result["observed_table"]


def test_grade_and_molecular_subtype_keep_expected_df() -> None:
    df = pd.DataFrame({
        "Positive/ Negative": ["Yes", "Yes", "No", "No"] * 6,
        "Histological type": [1.0, 2.0, 3.0, 3.0] * 6,
        "Molecular subtype": ["Luminal A", "Luminal B", "HER2neu", "Triple negative"] * 6,
    })
    session = _session()
    grade = run_chi_or_fisher("Histological type", "Positive/ Negative", session, df)
    molecular = run_chi_or_fisher("Molecular subtype", "Positive/ Negative", session, df)
    assert grade["test_type"] == "chi_square", grade
    assert grade["dof"] == 2, grade
    assert grade["row_labels"] == ["Grade 1", "Grade 2", "Grade 3"], grade["row_labels"]
    assert molecular["test_type"] == "chi_square", molecular
    assert molecular["dof"] == 3, molecular


def main() -> None:
    test_binary_markers_use_fisher_after_normalization()
    test_non_sparse_2x2_chi_square_has_df_1()
    test_grade_and_molecular_subtype_keep_expected_df()
    print("Sigma categorical pre-test normalization checks passed.")


if __name__ == "__main__":
    main()
