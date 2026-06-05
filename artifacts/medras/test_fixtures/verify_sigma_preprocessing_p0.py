import math

import pandas as pd

from app.services import variable_classifier


def _by_col(classifications):
    return {c["column"]: c for c in classifications}


def main():
    df = pd.DataFrame({
        "Marker status": [" Positive ", "Negative", "NA", "  Not done  "],
        "Her2Neu": ["0", "1+", "2+", "3+"],
        "pT": ["T1b", "T2", "T3", "mT2"],
        "Grade": ["Grade I", "Grade II", "Grade III", "Grade II"],
        "Severity": ["Mild", "Moderate", "Severe", "Mild"],
        "No of nodes involved": ["0/13", "2/18", "7/20", "1 / 5"],
    })

    cleaned, string_notes = variable_classifier.normalize_string_columns(df)
    assert cleaned.loc[0, "Marker status"] == "Positive"
    assert pd.isna(cleaned.loc[2, "Marker status"])
    assert pd.isna(cleaned.loc[3, "Marker status"])
    assert "Marker status" in string_notes

    derived, node_notes, derived_by_source = variable_classifier.derive_node_fraction_columns(cleaned)
    assert derived_by_source["No of nodes involved"] == [
        "positive_nodes",
        "total_nodes",
        "node_ratio",
    ]
    assert "No of nodes involved" in node_notes
    assert float(derived.loc[1, "positive_nodes"]) == 2.0
    assert float(derived.loc[1, "total_nodes"]) == 18.0
    assert math.isclose(float(derived.loc[1, "node_ratio"]), 2 / 18)

    classes = _by_col(variable_classifier.classify_dataframe(derived))
    assert classes["Her2Neu"]["detected_type"] == "ordinal"
    assert classes["pT"]["detected_type"] == "ordinal"
    assert classes["Grade"]["detected_type"] == "ordinal"
    assert classes["Severity"]["detected_type"] == "ordinal"
    assert classes["positive_nodes"]["detected_type"] == "scale"
    assert classes["total_nodes"]["detected_type"] == "scale"
    assert classes["node_ratio"]["detected_type"] == "scale"

    print("sigma preprocessing P0 verification passed")


if __name__ == "__main__":
    main()
