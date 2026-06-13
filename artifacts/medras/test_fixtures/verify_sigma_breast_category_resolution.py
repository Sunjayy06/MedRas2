"""Focused verification for breast-pathology category resolution and stage labels.

Run:
    python -m test_fixtures.verify_sigma_breast_category_resolution
"""

from pathlib import Path

import pandas as pd

from app.services import category_merger, plan, variable_classifier


PROFILE = "breast_pathology"


def _fixture() -> pd.DataFrame:
    return pd.DataFrame({
        "PR": ["Positive"] * 18 + ["Postive"] + ["Negative"] * 11,
        "Age": list(range(35, 65)),
        "Molecular subtype": (
            ["Luminal A", "Luminal B", "Her2Neu", "Her2neu", "Triple negative"] * 6
        ),
        "pT": ["T1c", "T2", "T3", "T4b", "T2"] * 6,
        "Nodal status": ["N0", "N1a", "N2a", "N3a", "N0"] * 6,
    })


def verify_review_merge_and_planning() -> None:
    df = _fixture()
    classes = variable_classifier.classify_dataframe(df, profile=PROFILE)
    session = {
        "study_type": "association",
        "study_type_confirmed": True,
        "analysis_predictors": ["Age", "Molecular subtype"],
        "domain_profile": PROFILE,
    }

    unresolved = plan.generate_plan(
        df, classes, {"outcome": "PR", "group": None, "covariates": []},
        {"columns": []}, session=session,
    )
    assert any(item.get("blocking") for item in unresolved["suggestions"])

    pr_suggestions = category_merger.detect_category_duplicates(df["PR"], profile=PROFILE)
    review = next(
        item for item in pr_suggestions["borderline"]
        if {"Positive", "Postive"} <= set(item["members"])
    )
    resolved_df, actions = category_merger.apply_merges(
        df,
        [{"column": "PR", "canonical": review["canonical"], "members": review["members"]}],
        profile=PROFILE,
    )
    assert actions
    assert set(resolved_df["PR"]) == {"Positive", "Negative"}

    resolved_classes = variable_classifier.classify_dataframe(resolved_df, profile=PROFILE)
    resolved = plan.generate_plan(
        resolved_df, resolved_classes, {"outcome": "PR", "group": None, "covariates": []},
        {"columns": []}, session=session,
    )
    assert not any(item.get("blocking") for item in resolved["suggestions"])
    age_test = next(test for test in resolved["tests"] if "Age" in test.get("columns", []))
    assert age_test["_phase_b"]["function"] in {
        "run_pairwise_welch", "run_pairwise_mann_whitney",
    }


def verify_protected_labels_and_stage_preservation() -> None:
    df = _fixture()
    subtype = category_merger.detect_category_duplicates(
        df["Molecular subtype"], profile=PROFILE
    )
    suggestions = subtype["obvious"] + subtype["borderline"]
    assert not any({"Luminal A", "Luminal B"} <= set(item["members"]) for item in suggestions)
    assert any({"Her2Neu", "Her2neu"} <= set(item["members"]) for item in suggestions)

    protected_df, actions = category_merger.apply_merges(
        df,
        [{
            "column": "Molecular subtype",
            "canonical": "Luminal B",
            "members": ["Luminal A", "Luminal B"],
        }],
        profile=PROFILE,
    )
    assert not actions
    assert protected_df["Molecular subtype"].tolist() == df["Molecular subtype"].tolist()

    cleaned, notes = variable_classifier.clean_numeric_like_columns(df, profile=PROFILE)
    assert cleaned["pT"].tolist() == df["pT"].tolist()
    assert cleaned["Nodal status"].tolist() == df["Nodal status"].tolist()
    assert "pT" not in notes and "Nodal status" not in notes

    generic_cleaned, _ = variable_classifier.clean_numeric_like_columns(df, profile="generic")
    assert not any(col.endswith(("positive_nodes", "total_nodes", "node_ratio")) for col in generic_cleaned)


def verify_ui_and_endpoint_guards_are_wired() -> None:
    root = Path(__file__).resolve().parents[1]
    js = (root / "public/js/analysis.js").read_text(encoding="utf-8")
    api = (root / "app/api/stats.py").read_text(encoding="utf-8")
    assert 'data-merge-accept="' in js
    assert 'data-merge-reject="' in js
    assert "applyMerge([proposal]" in js
    assert "is_protected_merge(" in api
    assert "Protected clinical categories cannot be merged" in api


if __name__ == "__main__":
    verify_review_merge_and_planning()
    verify_protected_labels_and_stage_preservation()
    verify_ui_and_endpoint_guards_are_wired()
    print("Sigma breast category resolution verification passed.")
