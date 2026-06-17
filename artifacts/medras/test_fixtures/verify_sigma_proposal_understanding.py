"""Verify Sigma proposal understanding and Excel-column mapping."""

from __future__ import annotations

import asyncio
import json
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from app.api import stats
from app.services import dataset_store
from app.services import plan
from main import app


P27_PROPOSAL = """
Title: Prognostic significance of IHC expression of p27 in invasive mammary carcinoma

Aim and objective: To study p27 expression in invasive mammary carcinoma and
to assess its association with clinicopathological parameters including age,
histological grade, pT, nodal status, ER, PR, HER2, AR, EGFR, Ki67 and
molecular subtype.

Study design: Retrospective observational prognostic association study.
Sample size: 116 cases.
"""


P27_COLUMNS = [
    "Age", "Laterality", "Tumour site", "Tumour size", "Histological grade",
    "pT", "Nodal status", "DCIS", "LVI", "Necrosis", "ER", "PR", "HER2",
    "AR", "EGFR", "Ki67", "Molecular subtype", "Positive/ Negative",
    "Interpretation Site", "Staining Result",
]


def _p27_fixture() -> pd.DataFrame:
    return pd.DataFrame({
        "Age": [44, 52, 61, 49, 58, 66, 37, 73, 55, 47, 69, 60],
        "Laterality": ["Left", "Right", "Left", "Right", "Left", "Right", "Left", "Right", "Left", "Right", "Left", "Right"],
        "Tumour site": ["Upper outer", "Lower inner", "Upper outer", "Central", "Upper outer", "Lower inner", "Central", "Upper outer", "Lower inner", "Central", "Upper outer", "Central"],
        "Histological grade": ["I", "II", "III", "II", "I", "III", "II", "III", "I", "II", "III", "II"],
        "pT": ["T1c", "T2", "T3", "T2", "T1c", "T4b", "T2", "T3", "T1c", "T2", "T4b", "T3"],
        "Nodal status": ["N0", "N1a", "N2a", "N0", "N1a", "N3a", "N0", "N2a", "N1a", "N0", "N3a", "N2a"],
        "ER": ["Positive", "Positive", "Negative", "Positive", "Negative", "Positive", "Negative", "Positive", "Positive", "Negative", "Positive", "Negative"],
        "PR": ["Positive", "Negative", "Positive", "Positive", "Negative", "Positive", "Negative", "Positive", "Negative", "Positive", "Negative", "Positive"],
        "HER2": ["Negative", "1+", "2+", "3+", "Negative", "1+", "2+", "3+", "Negative", "1+", "2+", "3+"],
        "AR": ["Positive", "Negative", "Positive", "Negative", "Positive", "Negative", "Positive", "Negative", "Positive", "Negative", "Positive", "Negative"],
        "Molecular subtype": ["Luminal A", "Luminal B", "HER2neu", "Triple negative", "Luminal A", "Luminal B", "HER2neu", "Triple negative", "Luminal A", "Luminal B", "HER2neu", "Triple negative"],
        "Positive/ Negative": ["Positive", "Negative", "Positive", "Negative", "Positive", "Negative", "Positive", "Negative", "Positive", "Negative", "Positive", "Negative"],
    })


def _mock_openrouter_payload() -> str:
    return json.dumps({
        "study_title": "Prognostic significance of IHC expression of p27 in invasive mammary carcinoma",
        "study_design": "retrospective observational association/prognostic study",
        "study_type": "association",
        "sample_size": 116,
        "domain_profile": "breast_pathology",
        "objectives": {
            "primary": "Assess p27 expression in invasive mammary carcinoma.",
            "secondary": ["Assess association with receptor and pathology variables."],
        },
        "main_marker": "p27",
        "main_outcome_concept": "p27 expression status",
        "candidate_outcomes": ["p27 expression status", "Positive/Negative"],
        "candidate_predictors": ["Age", "ER", "PR", "HER2", "Molecular subtype", "Nodal status"],
        "candidate_covariates": ["Age"],
        "analysis_intent": "association/prognostic analysis",
        "recommended_analysis_layers": ["descriptive", "bivariate", "multivariate_if_eligible"],
        "confidence": {
            "overall": "high",
            "title": "high",
            "sample_size": "high",
            "main_outcome": "high",
            "domain": "high",
        },
        "requires_confirmation": True,
    })


def verify_mocked_openrouter_success() -> dict:
    calls = []

    def fake_chat(**kwargs):
        calls.append(kwargs)
        return _mock_openrouter_payload()

    with (
        patch.object(stats, "_openrouter_is_configured", return_value=True),
        patch.object(stats, "_openrouter_model_for_task", return_value="test/proposal"),
        patch.object(stats, "_openrouter_chat", side_effect=fake_chat),
    ):
        raw, provider, redacted, blocked = asyncio.run(
            stats._ai_extract(P27_PROPOSAL, external_ai_consent=True)
        )
    assert provider == "openrouter"
    assert redacted is False
    assert blocked is False
    assert calls and calls[0]["task"] == "proposal_parse"
    result = stats._normalize_proposal_extract(
        raw, P27_PROPOSAL, provider=provider, model="test/proposal"
    )
    assert "p27" in result["study_title"].lower()
    assert result["sample_size"] == 116
    assert result["domain_profile"] == "breast_pathology"
    assert result["main_marker"].lower() == "p27"
    assert result["main_outcome_concept"] == "p27 expression status"
    assert any("positive" in c.lower() and "negative" in c.lower() for c in result["candidate_outcomes"])
    assert result["provider"] == "openrouter"
    assert result["model"] == "test/proposal"
    assert result["model_kind"] == "proposal"
    assert result["requires_confirmation"] is True
    assert result["outcomes"] != "PR"
    return result


def verify_diagnostic_misclassification_guardrail() -> None:
    raw = json.loads(_mock_openrouter_payload())
    raw["study_type"] = "diagnostic"
    raw["objectives"]["primary"] = (
        "p27 is discussed in many published background studies of cell cycle biology. "
        * 20
    )
    result = stats._normalize_proposal_extract(
        raw, P27_PROPOSAL, provider="openrouter", model="test/proposal"
    )
    assert result["study_type"] == "association"
    assert any("normalized this to an association study" in warning for warning in result["warnings"])
    assert len(result["objectives"]["primary"]) < 900
    assert "association with clinicopathological" in result["objectives"]["primary"].lower()


def verify_survival_misclassification_guardrail() -> None:
    raw = json.loads(_mock_openrouter_payload())
    raw["study_type"] = "survival"
    result = stats._normalize_proposal_extract(
        raw, P27_PROPOSAL, provider="openrouter", model="test/proposal"
    )
    assert result["study_type"] == "association"
    assert any("normalized this to an association study" in warning for warning in result["warnings"])

    survival_text = (
        "Primary objective: To compare overall survival and disease-free survival "
        "by p27 expression status using follow-up time, censoring, Kaplan-Meier "
        "curves and Cox regression hazard ratios."
    )
    survival = stats._normalize_proposal_extract(
        {"study_type": "survival", "objectives": {"primary": survival_text}},
        survival_text,
        provider="openrouter",
        model="test/proposal",
    )
    assert survival["study_type"] == "survival"


def verify_excel_mapping(proposal: dict) -> dict:
    mapping = stats._map_proposal_to_columns(proposal, P27_COLUMNS, "breast_pathology")
    assert mapping["mapped_outcome"] == "Positive/ Negative"
    assert "PR" in mapping["mapped_predictors"]
    assert mapping["mapping_confidence"] == "high"
    assert mapping["requires_confirmation"] is True
    return mapping


def verify_safe_fallbacks() -> None:
    raw, provider, redacted, blocked = asyncio.run(
        stats._ai_extract(P27_PROPOSAL, external_ai_consent=False)
    )
    assert raw is None and provider is None and redacted is False and blocked is False
    fallback = stats._heuristic_extract(P27_PROPOSAL)
    assert fallback["requires_confirmation"] is True
    assert fallback["fallback_used"] is True
    assert fallback["confidence"]["overall"] in {"low", "medium"}

    with (
        patch.object(stats, "_openrouter_is_configured", return_value=True),
        patch.object(stats, "_openrouter_chat", return_value="not json"),
    ):
        raw, provider, _, _ = asyncio.run(
            stats._ai_extract(P27_PROPOSAL, external_ai_consent=True)
        )
    assert raw is None and provider is None


def verify_planner_integration(mapping: dict) -> None:
    df = pd.DataFrame({
        "Positive/ Negative": ["Positive", "Negative", "Positive", "Negative"],
        "PR": ["Positive", "Positive", "Negative", "Negative"],
        "Age": [55, 62, 49, 71],
    })
    classifications = [
        {"column": "Positive/ Negative", "detected_type": "nominal"},
        {"column": "PR", "detected_type": "nominal"},
        {"column": "Age", "detected_type": "scale"},
    ]
    generated = plan.generate_correlation_plan(
        df, classifications, mapping["mapped_outcome"]
    )
    assert generated["outcome_col"] == "Positive/ Negative"
    assert any(p["predictor"] == "PR" for p in generated["pairs"])
    assert any(p["predictor"] == "Age" and p["test_id"] in {"corr_ttest", "corr_mann_whitney"} for p in generated["pairs"])


def verify_confirmed_outcome_handoff(proposal: dict) -> None:
    payload = BytesIO()
    _p27_fixture().to_excel(payload, index=False)
    payload.seek(0)

    with TestClient(app) as client:
        upload = client.post(
            "/api/stats/upload",
            files={"file": ("p27_fixture.xlsx", payload.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"profile": "breast_pathology"},
        )
        assert upload.status_code == 200, upload.text
        job_id = upload.json()["job_id"]

        classified = client.post(
            "/api/stats/classify",
            json={"job_id": job_id, "overrides": [], "profile": "breast_pathology"},
        )
        assert classified.status_code == 200, classified.text

        setup = client.post(
            "/api/stats/setup-study",
            json={
                "job_id": job_id,
                "description": P27_PROPOSAL,
                "outcome_hint": "",
                "profile": "breast_pathology",
                "proposal_metadata": proposal,
            },
        )
        assert setup.status_code == 200, setup.text
        setup_body = setup.json()
        assert setup_body["domain_profile"] == "breast_pathology"
        assert setup_body["study_type"] == "association"
        assert setup_body["outcome_col"] == "Positive/ Negative"
        assert setup_body["proposal_mapping"]["mapped_outcome"] == "Positive/ Negative"
        assert "PR" in setup_body["proposal_mapping"]["mapped_predictors"]

        entry = dataset_store.get(job_id)
        assert entry is not None
        entry.meta["assignment"] = {"outcome": "PR", "group": "PR", "covariates": []}
        pending_classified = client.post(
            "/api/stats/classify",
            json={"job_id": job_id, "overrides": [], "profile": "breast_pathology"},
        )
        assert pending_classified.status_code == 200, pending_classified.text
        pending_body = pending_classified.json()
        assert pending_body["assignment"]["outcome"] == "Positive/ Negative"
        assert pending_body["assignment"]["group"] is None
        assert pending_body["assignment"]["source"] == "mapped_outcome"

        confirmed = client.post(
            "/api/stats/confirm-study",
            json={
                "job_id": job_id,
                "study_type": setup_body["study_type"],
                "outcome_col": "PR",  # stale hidden/browser value should not beat mapped outcome
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["outcome_col"] == "Positive/ Negative"
        assert confirmed.json()["assignment"]["outcome"] == "Positive/ Negative"
        assert confirmed.json()["assignment"]["group"] is None

        entry = dataset_store.get(job_id)
        assert entry is not None
        entry.meta["assignment"] = {"outcome": "PR", "group": None, "covariates": []}

        stale_assign = client.post(
            "/api/stats/assign",
            json={"job_id": job_id, "outcome": "PR", "group": None, "covariates": []},
        )
        assert stale_assign.status_code == 200, stale_assign.text
        stale_assign_body = stale_assign.json()
        assert stale_assign_body["status"] == "corrected"
        assert stale_assign_body["assignment"]["outcome"] == "Positive/ Negative"
        assert "refreshed it to Positive/ Negative" in stale_assign_body["warning"]
        entry = dataset_store.get(job_id)
        assert entry is not None
        assert entry.meta["confirmed_outcome_col"] == "Positive/ Negative"
        assert entry.meta["assignment"]["outcome"] == "Positive/ Negative"

        entry.meta["assignment"] = {"outcome": "PR", "group": None, "covariates": []}
        reclassified = client.post(
            "/api/stats/classify",
            json={"job_id": job_id, "overrides": [], "profile": "breast_pathology"},
        )
        assert reclassified.status_code == 200, reclassified.text
        reclassified_body = reclassified.json()
        assert reclassified_body["confirmed_outcome_col"] == "Positive/ Negative"
        assert reclassified_body["assignment"]["outcome"] == "Positive/ Negative"

        entry.meta["plan"] = {
            "tests": [{
                "id": "stale_pr_plan",
                "title": "Age by PR: Mann-Whitney U",
                "columns": ["Age", "PR"],
                "analysis_family": "bivariate",
                "_phase_b": {
                    "function": "run_pairwise_mann_whitney",
                    "test_type": "mann_whitney",
                    "args": {"predictor": "Age", "outcome": "PR"},
                },
            }],
            "graphs": [{
                "id": "stale_pr_graph",
                "title": "Age by PR",
                "columns": ["Age", "PR"],
                "outcome": "PR",
            }],
            "outputs": [],
            "summary": "stale PR plan",
        }

        generated = client.get(f"/api/stats/generate-plan/{job_id}")
        assert generated.status_code == 200, generated.text
        plan_body = generated.json()
        assert plan_body["assignment"]["outcome"] == "Positive/ Negative"
        titles = [test["title"] for test in plan_body["plan"]["tests"]]
        assert any("PR vs Positive/ Negative" in title for title in titles)
        assert any("Age by Positive/ Negative" in title for title in titles)
        assert not any(" by PR" in title or "vs PR" in title for title in titles)

        entry = dataset_store.get(job_id)
        assert entry is not None
        entry.meta["plan"] = {
            "tests": [{
                "id": "stale_pr_plan",
                "title": "Age by PR: Mann-Whitney U",
                "columns": ["Age", "PR"],
                "analysis_family": "bivariate",
                "_phase_b": {
                    "function": "run_pairwise_mann_whitney",
                    "test_type": "mann_whitney",
                    "args": {"predictor": "Age", "outcome": "PR"},
                },
            }],
            "graphs": [],
            "outputs": [],
            "summary": "stale PR plan",
        }

        run = client.post(
            "/api/stats/run-analysis",
            json={
                "job_id": job_id,
                "confirmed_test_ids": [test["id"] for test in plan_body["plan"]["tests"]],
                "confirmed_graph_ids": [graph["id"] for graph in plan_body["plan"].get("graphs", [])],
            },
        )
        assert run.status_code == 200, run.text
        results = run.json()["results"]
        result_titles = [test.get("title", "") for test in results.get("tests", [])]
        assert any("PR vs Positive/ Negative" in title for title in result_titles)
        assert any("Age by Positive/ Negative" in title for title in result_titles)
        assert not any(" by PR" in title or "vs PR" in title for title in result_titles)
        for graph in plan_body["plan"].get("graphs", []):
            assert graph.get("outcome") == "Positive/ Negative"
            assert "PR" not in str(graph.get("outcome"))


def verify_static_wiring() -> None:
    root = Path(__file__).resolve().parents[1]
    analysis_js = (root / "public/js/analysis.js").read_text(encoding="utf-8")
    stats_py = (root / "app/api/stats.py").read_text(encoding="utf-8")
    assert "proposal_metadata: proposalMetadataPayload()" in analysis_js
    assert "confirmedOutcomeFromState" in analysis_js
    assert "canonicalOutcomeFromPlan" in analysis_js
    assert "normalizeAiStudyPlan" in analysis_js
    assert "refreshStaleAssignmentIfNeeded" in analysis_js
    assert "MedRAS refreshed it to" in analysis_js
    assert 'api("/confirm-study"' in analysis_js
    assert "proposal_understanding" in analysis_js
    assert "proposal_metadata: Optional[Dict[str, Any]]" in stats_py
    assert "_map_proposal_to_columns" in stats_py
    assert "_canonical_assignment" in stats_py
    assert "confirmed_mapped_outcome" in stats_py
    assert "mapped_outcome" in stats_py


def main() -> None:
    proposal = verify_mocked_openrouter_success()
    verify_diagnostic_misclassification_guardrail()
    verify_survival_misclassification_guardrail()
    mapping = verify_excel_mapping(proposal)
    verify_safe_fallbacks()
    verify_planner_integration(mapping)
    verify_confirmed_outcome_handoff(proposal)
    verify_static_wiring()
    print("Sigma proposal understanding verification passed.")


if __name__ == "__main__":
    main()
