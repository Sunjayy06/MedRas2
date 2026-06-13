"""Focused verification for breast-pathology category resolution and stage labels.

Run:
    python -m test_fixtures.verify_sigma_breast_category_resolution
"""

from io import BytesIO
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from app.services import category_merger, dataset_store, plan, results, variable_classifier
from main import app


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
    classes = variable_classifier.classify_dataframe(cleaned, profile=PROFILE)
    samples = {item["column"]: item["sample_values"] for item in classes}
    assert samples["pT"][0].startswith("T")
    assert samples["Nodal status"][0].startswith("N")
    table_one = results.build_table_one(cleaned, classes, group=None)
    table_rows = {row["variable"]: row for row in table_one["rows"]}
    assert "T1c" in table_rows["pT"]["cells"][0]
    assert "N0" in table_rows["Nodal status"]["cells"][0]

    generic_cleaned, _ = variable_classifier.clean_numeric_like_columns(df, profile="generic")
    assert not any(col.endswith(("positive_nodes", "total_nodes", "node_ratio")) for col in generic_cleaned)


def verify_ui_and_endpoint_guards_are_wired() -> None:
    root = Path(__file__).resolve().parents[1]
    js = (root / "public/js/analysis.js").read_text(encoding="utf-8")
    api = (root / "app/api/stats.py").read_text(encoding="utf-8")
    assert 'data-merge-accept="' in js
    assert 'data-merge-reject="' in js
    assert "applyMerge([proposal]" in js
    assert 'form.append("profile", selectedDomainProfile())' in js
    assert 'profile: selectedDomainProfile()' in js
    assert 'if (state.currentScreen === "plan") await loadPlan()' in js
    assert "is_protected_merge(" in api
    assert "Protected clinical categories cannot be merged" in api


def verify_real_api_profile_and_individual_merge_chain() -> None:
    payload = BytesIO()
    _fixture().to_excel(payload, index=False)
    payload.seek(0)
    with TestClient(app) as client:
        upload = client.post(
            "/api/stats/upload",
            files={"file": ("breast_fixture.xlsx", payload.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"profile": PROFILE},
        )
        assert upload.status_code == 200, upload.text
        uploaded = upload.json()
        job_id = uploaded["job_id"]
        assert uploaded["domain_profile"] == PROFILE

        classified = client.post(
            "/api/stats/classify",
            json={"job_id": job_id, "overrides": [], "profile": "generic"},
        )
        assert classified.status_code == 200, classified.text
        classified_body = classified.json()
        assert classified_body["domain_profile"] == PROFILE
        by_column = {item["column"]: item for item in classified_body["classifications"]}
        assert by_column["pT"]["sample_values"][0].startswith("T")
        assert by_column["Nodal status"]["sample_values"][0].startswith("N")
        assert not by_column["pT"].get("cleanup_note")
        assert not by_column["Nodal status"].get("cleanup_note")

        detected = client.post(
            "/api/stats/detect-category-dupes",
            json={"job_id": job_id, "profile": "generic"},
        )
        assert detected.status_code == 200, detected.text
        columns = detected.json()["columns"]
        subtype = columns.get("Molecular subtype", {})
        subtype_suggestions = subtype.get("obvious", []) + subtype.get("borderline", [])
        assert not any(
            {"Luminal A", "Luminal B"} <= set(item["members"])
            for item in subtype_suggestions
        )
        pr_review = next(
            item for item in columns["PR"]["borderline"]
            if {"Positive", "Postive"} <= set(item["members"])
        )

        blocked_assign = client.post(
            "/api/stats/assign",
            json={"job_id": job_id, "outcome": "PR", "group": None, "covariates": ["Age"]},
        )
        assert blocked_assign.status_code == 200
        blocked_plan = client.get(f"/api/stats/generate-plan/{job_id}").json()["plan"]
        assert any(item.get("blocking") for item in blocked_plan["suggestions"])

        accepted = client.post(
            "/api/stats/apply-category-merge",
            json={
                "job_id": job_id,
                "profile": PROFILE,
                "merges": [{
                    "column": "PR",
                    "canonical": pr_review["canonical"],
                    "members": pr_review["members"],
                }],
            },
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["n_merges"] == 1
        refreshed = client.post(
            "/api/stats/classify",
            json={"job_id": job_id, "overrides": [], "profile": "generic"},
        )
        assert refreshed.status_code == 200
        resolved_plan = client.get(f"/api/stats/generate-plan/{job_id}").json()["plan"]
        assert not any(item.get("blocking") for item in resolved_plan["suggestions"])
        age_test = next(test for test in resolved_plan["tests"] if "Age" in test.get("columns", []))
        assert age_test["_phase_b"]["function"] in {
            "run_pairwise_welch", "run_pairwise_mann_whitney",
        }

        protected = client.post(
            "/api/stats/apply-category-merge",
            json={
                "job_id": job_id,
                "profile": PROFILE,
                "merges": [{
                    "column": "Molecular subtype",
                    "canonical": "Luminal B",
                    "members": ["Luminal A", "Luminal B"],
                }],
            },
        )
        assert protected.status_code == 400


def verify_legacy_stage_extraction_is_repaired() -> None:
    legacy_job = dataset_store.put(
        _fixture(),
        {"filename": "legacy.xlsx", "domain_profile": "generic"},
    )
    with TestClient(app) as client:
        generic = client.post(
            "/api/stats/classify",
            json={"job_id": legacy_job, "overrides": [], "profile": "generic"},
        )
        assert generic.status_code == 200
        generic_by_col = {item["column"]: item for item in generic.json()["classifications"]}
        assert generic_by_col["pT"].get("cleanup_note")
        assert generic_by_col["Nodal status"].get("cleanup_note")

        repaired = client.post(
            "/api/stats/classify",
            json={"job_id": legacy_job, "overrides": [], "profile": PROFILE},
        )
        assert repaired.status_code == 200
        repaired_by_col = {item["column"]: item for item in repaired.json()["classifications"]}
        assert repaired_by_col["pT"]["sample_values"][0].startswith("T")
        assert repaired_by_col["Nodal status"]["sample_values"][0].startswith("N")
        assert not repaired_by_col["pT"].get("cleanup_note")
        assert not repaired_by_col["Nodal status"].get("cleanup_note")


if __name__ == "__main__":
    verify_review_merge_and_planning()
    verify_protected_labels_and_stage_preservation()
    verify_ui_and_endpoint_guards_are_wired()
    verify_real_api_profile_and_individual_merge_chain()
    verify_legacy_stage_extraction_is_repaired()
    print("Sigma breast category resolution verification passed.")
