"""Verify breast-cancer preprocessing, association routing, and export coverage."""

from pathlib import Path

import pandas as pd

from app.services import category_merger, normality, plan, results, variable_classifier


ROOT = Path(__file__).resolve().parents[1]
REAL_WORKBOOK = Path.home() / "Downloads" / "Final masterchart.xlsx"


def _fixture() -> pd.DataFrame:
    return pd.DataFrame({
        "No of nodes involved": ["0/13", "2/18", "7/20", "1/11"] * 8,
        "PR": ["Positive", "Negative", "Positive", "Negative"] * 8,
        "ER": ["Positive", "Negative", "Positive", "Negative"] * 8,
        "Her2Neu": ["3+", "Negative", "2+", "1+"] * 8,
        "Molecular subtype": ["Luminal A", "Luminal B", "Her2neu", "Triple negative"] * 8,
        "LVI": ["Present", "Absent", "Present", "Absent"] * 8,
        "ENE": ["Absent", "Present", "Absent", "Present"] * 8,
        "Necrosis": ["Absent", "Present", "Present", "Absent"] * 8,
        "pT": ["T1c", "T2", "T3", "T4b"] * 8,
        "Nodal status": ["N0", "N1a", "N2a", "N3a"] * 8,
        "Age": [42, 61, 53, 48] * 8,
        "Histological grade": ["Grade I", "Grade II", "Grade III", "Grade II"] * 8,
        "DCIS": ["Present", "Absent", "Present", "Absent"] * 8,
        "Ki67 status": ["Low", "High", "Intermediate", "High"] * 8,
    })


def _verify(df: pd.DataFrame) -> None:
    # Simulate a session polluted by older repeated-classification behavior.
    df = df.copy()
    df["no_of_nodes_involved_positive_nodes_2"] = 99.0
    df["no_of_nodes_involved_total_nodes_2"] = 99.0
    df["no_of_nodes_involved_node_ratio_2"] = 1.0
    for _ in range(4):
        df, _, _ = variable_classifier.derive_node_fraction_columns(
            df, profile="breast_pathology"
        )
        df, _ = variable_classifier.clean_numeric_like_columns(
            df, profile="breast_pathology"
        )

    node_columns = [
        col for col in df.columns
        if col in {"positive_nodes", "total_nodes", "node_ratio"}
        or "nodes_involved_positive_nodes" in col
        or "nodes_involved_total_nodes" in col
        or "nodes_involved_node_ratio" in col
    ]
    assert node_columns == ["positive_nodes", "total_nodes", "node_ratio"]

    classifications = variable_classifier.classify_dataframe(
        df, profile="breast_pathology"
    )
    by_col = {row["column"]: row for row in classifications}
    assert by_col["pT"]["detected_type"] == "ordinal"
    assert by_col["Nodal status"]["detected_type"] == "ordinal"
    assert {"T1c", "T2", "T3", "T4b"} <= set(df["pT"].dropna().astype(str))
    assert {"N0", "N1a", "N2a", "N3a"} <= set(df["Nodal status"].dropna().astype(str))

    proposals = category_merger.detect_all_columns(
        df, classifications, profile="breast_pathology"
    )
    molecular = proposals.get("Molecular subtype") or {}
    all_groups = list(molecular.get("obvious") or []) + list(molecular.get("borderline") or [])
    assert not any(
        {"Luminal A", "Luminal B"} <= set(group.get("members") or [])
        for group in all_groups
    )

    predictors = [
        row["column"] for row in classifications
        if row["column"] != "PR"
        and row.get("detected_type") not in ("id", "date", "exclude")
    ]
    assert {"ER", "Her2Neu", "Molecular subtype", "LVI", "ENE", "Necrosis", "pT", "Nodal status", "Age"} <= set(predictors)
    assignment = {"outcome": "PR", "group": None, "covariates": []}
    session = {
        # Reproduces local setup fallback before the researcher explicitly
        # confirms a study type.
        "study_type": "descriptive",
        "study_type_confirmed": False,
        "analysis_predictors": predictors,
    }
    sigma_plan = plan.generate_plan(
        df, classifications, assignment,
        normality.normality_for_dataset(df, classifications, False),
        session,
    )
    assert len(sigma_plan["tests"]) > 10
    assert all(test["id"] != "descriptive_only" for test in sigma_plan["tests"])

    output = results.run_plan(df, classifications, assignment, sigma_plan, session=session)
    assert len(output["tests"]) == len(sigma_plan["tests"])
    assert len(output["tests"]) > 10
    assert not output["plan_mismatch"]
    assert sum(bool(test.get("tables")) for test in output["tests"]) > 5


def main() -> None:
    _verify(_fixture())

    # Exercise the supplied real-world pattern when the workbook is available.
    if REAL_WORKBOOK.exists():
        from app.services import excel_loader

        df, _ = excel_loader.parse_upload(
            filename=REAL_WORKBOOK.name,
            raw=REAL_WORKBOOK.read_bytes(),
        )
        _verify(df)

    export_source = (ROOT / "app/services/export.py").read_text(encoding="utf-8")
    js_source = (ROOT / "public/js/analysis.js").read_text(encoding="utf-8")
    assert "for table_num, primary in enumerate(primary_results, 3)" in export_source
    assert "for primary in primary_results:" in export_source
    assert "Lilliefors when available, with Shapiro-Wilk fallback" in export_source
    assert "if (!state.assignment || !state.assignment.outcome)" in js_source
    assert "autoAssignFromIntake();" in js_source

    print("Sigma breast preprocessing/results/export verification passed.")


if __name__ == "__main__":
    main()
