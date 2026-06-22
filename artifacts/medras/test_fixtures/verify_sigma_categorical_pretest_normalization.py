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
    # Issue 5: 2x2 Fisher's exact tests must use the test-specific sparse
    # wording, not the generic chi-square "interpret cautiously" phrasing.
    assert result["note"] == "Fisher's exact test was used because sparse expected cell counts were present.", result["note"]
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
    assert sorted(molecular["row_labels"]) == ["HER2-enriched", "Luminal A", "Luminal B", "Triple negative"], (
        molecular["row_labels"]
    )


def test_molecular_subtype_triple_negative_not_collapsed_to_negative() -> None:
    """'Triple negative' is a distinct molecular subtype category, not a
    binary Yes/No value. The pretest normalizer must never collapse it into
    a bare 'Negative' row in the contingency table feeding the chi-square
    test — "molecular subtype" contains "ar" and "negative" as substrings
    that previously triggered the generic binary-marker collapse."""
    df = pd.DataFrame({
        "Positive/ Negative": ["Yes", "Yes", "No", "No"] * 6,
        "Molecular subtype": ["Luminal A", "Luminal B", "HER2neu", "Triple negative"] * 6,
    })
    session = _session()
    molecular = run_chi_or_fisher("Molecular subtype", "Positive/ Negative", session, df)
    assert "Triple negative" in molecular["row_labels"], molecular["row_labels"]
    assert molecular["row_labels"].count("Negative") == 0, (
        f"Triple negative must not collapse to a standalone 'Negative' row: {molecular['row_labels']}"
    )


def test_sparse_rxc_chi_square_keeps_generic_sparse_wording() -> None:
    """Issue 5: larger RxC sparse tables stay on chi-square and must keep the
    existing 'interpreted cautiously' wording — only 2x2 Fisher tests get the
    test-specific 'Fisher's exact test was used because...' note."""
    df = pd.DataFrame({
        "Positive/ Negative": ["Yes"] * 3 + ["No"] * 6,
        "Histological type": ["Grade 1"] * 3 + ["Grade 2"] * 3 + ["Grade 3"] * 3,
    })
    session = _session()
    result = run_chi_or_fisher("Histological type", "Positive/ Negative", session, df)
    assert result["test_type"] == "chi_square", result
    assert result["note"] == "This finding should be interpreted cautiously because some expected cell counts were below 5.", result["note"]


def main() -> None:
    test_binary_markers_use_fisher_after_normalization()
    test_non_sparse_2x2_chi_square_has_df_1()
    test_grade_and_molecular_subtype_keep_expected_df()
    test_molecular_subtype_triple_negative_not_collapsed_to_negative()
    test_sparse_rxc_chi_square_keeps_generic_sparse_wording()
    print("Sigma categorical pre-test normalization checks passed.")


if __name__ == "__main__":
    main()
