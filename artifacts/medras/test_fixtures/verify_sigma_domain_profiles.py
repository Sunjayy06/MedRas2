"""Verify Sigma's generic default and optional domain profiles."""

import pandas as pd

from app.services import ai_bridge, category_merger, data_quality, variable_classifier


def _types(df: pd.DataFrame, profile: str = "generic") -> dict[str, str]:
    return {
        row["column"]: row["detected_type"]
        for row in variable_classifier.classify_dataframe(df, profile=profile)
    }


def verify_generic_non_medical_datasets() -> None:
    software = pd.DataFrame({
        "PR": [3, 5, 8, 13],
        "ER": ["open", "closed", "open", "merged"],
        "AR": [10.0, 12.0, 15.0, 18.0],
        "node": ["2/18", "3/20", "1/12", "4/25"],
        "status": ["open", "closed", "open", "closed"],
        "stage": ["backlog", "build", "test", "release"],
        "pt": ["part time", "full time", "part time", "full time"],
    })
    finance = pd.DataFrame({
        "AR": [1000, 2200, 3400, 4600],
        "PR": [2.1, 2.4, 2.7, 3.0],
        "age_of_account": [130, 145, 160, 175],
        "price": [500, 510, 520, 530],
        "grade": ["A", "B", "A", "C"],
    })
    network = pd.DataFrame({
        "node": ["2/18", "3/20", "1/12", "4/25"],
        "source_node": ["A", "B", "C", "D"],
    })
    education = pd.DataFrame({
        "grade": ["Freshman", "Sophomore", "Junior", "Senior"],
        "stage": ["entry", "mid", "mid", "exit"],
        "level": ["basic", "intermediate", "advanced", "advanced"],
    })

    for df in (software, finance, network, education):
        original = df.copy(deep=True)
        derived, notes, sources = variable_classifier.derive_node_fraction_columns(df)
        assert list(derived.columns) == list(df.columns)
        assert not notes and not sources
        pd.testing.assert_frame_equal(df, original)
        assert not {"positive_nodes", "total_nodes", "node_ratio"} & set(derived.columns)

    software_types = _types(software)
    assert software_types["PR"] == "scale"
    assert software_types["AR"] == "scale"
    assert software_types["pt"] == "nominal"
    assert not variable_classifier.is_known_categorical_clinical_marker("ER")
    assert not variable_classifier.is_known_categorical_clinical_marker("PR")
    assert not variable_classifier.is_known_categorical_clinical_marker("AR")
    assert not variable_classifier.is_known_categorical_clinical_marker("pt")
    assert not ai_bridge._is_standard_marker("PR")

    quality_df = pd.DataFrame({
        "temperature": [500.0, 600.0],
        "gender": ["male", "male"],
        "pregnant": [True, True],
    })
    generic_quality = data_quality.quality_report(quality_df, profile="generic")
    assert generic_quality["impossible_values"] == []
    assert not any(
        item.get("issue_type") == "logical_error"
        for item in generic_quality["logical_errors"]
    )


def verify_breast_pathology_profile() -> None:
    breast = pd.DataFrame({
        "HER2": ["0", "1+", "2+", "3+"],
        "ER": ["Positive", "Negative", "Positive", "Negative"],
        "No of nodes involved": ["0/13", "2/18", "7/20", "1/15"],
        "pT": ["T1c", "T2", "T3", "T4b"],
    })
    derived, notes, sources = variable_classifier.derive_node_fraction_columns(
        breast, profile="breast_pathology"
    )
    assert {"positive_nodes", "total_nodes", "node_ratio"} <= set(derived.columns)
    assert sources["No of nodes involved"] == [
        "positive_nodes", "total_nodes", "node_ratio"
    ]
    assert notes["No of nodes involved"].startswith(
        "Suggested by breast_pathology profile:"
    )

    types = _types(breast, profile="breast_pathology")
    assert types["HER2"] == "ordinal"
    assert types["ER"] == "nominal"
    assert types["pT"] == "ordinal"
    assert variable_classifier.is_known_categorical_clinical_marker(
        "PR", profile="breast_pathology"
    )
    assert ai_bridge._is_standard_marker("PR", profile="breast_pathology")

    molecular = pd.Series(["Luminal A", "Luminal B", "Luminal A"])
    protected = category_merger.detect_category_duplicates(
        molecular, profile="breast_pathology"
    )
    assert not protected["borderline"]

    clinical_quality = data_quality.quality_report(
        pd.DataFrame({"temperature": [500.0, 36.8]}),
        profile="breast_pathology",
    )
    assert clinical_quality["impossible_values"]


def main() -> None:
    verify_generic_non_medical_datasets()
    verify_breast_pathology_profile()
    print("Sigma domain profile verification passed.")


if __name__ == "__main__":
    main()
