"""Verify partial node-fraction detection and Excel-corruption warnings."""

import math

import pandas as pd

from app.services import variable_classifier, variable_issues


def _quality_issues(df, notes):
    classifications = variable_classifier.classify_dataframe(
        df, profile="breast_pathology"
    )
    for classification in classifications:
        note = notes.get(classification["column"])
        if note:
            classification["cleanup_note"] = note
    return variable_issues.detect_issues(df, classifications)


def verify_partial_derivation() -> None:
    df = pd.DataFrame(
        {
            "No of nodes involved": [
                "0/13",
                "2/18",
                "7/20",
                "1/5",
                "3/14",
                46043.0,
                46039.0,
                46035.0,
                "0/0",
                "unreadable",
            ]
        }
    )

    derived, notes, derived_by_source = variable_classifier.derive_node_fraction_columns(
        df, profile="breast_pathology"
    )

    assert derived_by_source["No of nodes involved"] == [
        "positive_nodes",
        "total_nodes",
        "node_ratio",
    ]
    assert float(derived.loc[1, "positive_nodes"]) == 2.0
    assert float(derived.loc[1, "total_nodes"]) == 18.0
    assert math.isclose(float(derived.loc[1, "node_ratio"]), 2 / 18)
    assert derived.loc[5:7, "positive_nodes"].notna().all()
    assert "/" in str(derived.loc[5, "No of nodes involved"])
    assert derived.loc[8:9, "positive_nodes"].isna().all()
    assert "Excel-corrupted" in notes["No of nodes involved"]
    assert "Recovered" in notes["No of nodes involved"]
    issues = _quality_issues(derived, notes)
    assert any(i["type"] == "node_fraction_corruption" for i in issues)


def verify_unsafe_partial_column_warns_without_deriving() -> None:
    df = pd.DataFrame(
        {
            "Positive lymph nodes": [
                "0/13",
                "2/18",
                46043.0,
                46039.0,
                46035.0,
                "unreadable",
            ]
        }
    )

    derived, notes, derived_by_source = variable_classifier.derive_node_fraction_columns(
        df, profile="breast_pathology"
    )

    assert list(derived.columns) == ["Positive lymph nodes"]
    assert "Positive lymph nodes" not in derived_by_source
    assert "were not created safely" in notes["Positive lymph nodes"]
    assert "Excel-corrupted" in notes["Positive lymph nodes"]
    issues = _quality_issues(derived, notes)
    assert any(i["type"] == "node_fraction_corruption" for i in issues)


def main() -> None:
    verify_partial_derivation()
    verify_unsafe_partial_column_warns_without_deriving()
    print("Sigma partial node-fraction verification passed.")


if __name__ == "__main__":
    main()
