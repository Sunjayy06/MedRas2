"""Verify categorical association plans reach Sigma Step 7 results."""

from pathlib import Path

import pandas as pd

from app.services import plan, results


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    api_source = (root / "app/api/stats.py").read_text(encoding="utf-8")
    js_source = (root / "public/js/analysis.js").read_text(encoding="utf-8")
    chat_source = (root / "app/services/chatboxes.py").read_text(encoding="utf-8")
    assert 'entry.meta["ai_study"] = result' in api_source
    assert '"analysis_predictors": analysis_predictors' in api_source
    assert "state.outcomeCol || (state.aiStudy && state.aiStudy.outcome_col)" in js_source
    assert "state.setupGroupCol || hint" in js_source
    assert 'if r.get("plan_mismatch")' in chat_source

    df = pd.DataFrame({
        "PR": ["Positive", "Negative", "Positive", "Negative"] * 8,
        "ER": ["Positive", "Negative", "Positive", "Negative"] * 8,
        "HER2": ["3+", "1+", "2+", "Negative"] * 8,
        "Molecular subtype": ["Luminal A", "Triple negative", "Luminal B", "HER2 enriched"] * 8,
        "Age": [42, 61, 53, 48] * 8,
    })
    classifications = [
        {"column": "PR", "detected_type": "nominal"},
        {"column": "ER", "detected_type": "nominal"},
        {"column": "HER2", "detected_type": "nominal"},
        {"column": "Molecular subtype", "detected_type": "nominal"},
        {"column": "Age", "detected_type": "scale"},
    ]
    assignment = {"outcome": "PR", "group": None, "covariates": []}
    session = {
        "study_type": "association",
        "analysis_predictors": ["ER", "HER2", "Molecular subtype", "Age"],
    }

    sigma_plan = plan.generate_plan(df, classifications, assignment, {}, session)
    assert sigma_plan["tests"]
    assert all(test["id"] != "descriptive_only" for test in sigma_plan["tests"])
    assert any(test["columns"] == ["ER", "PR"] for test in sigma_plan["tests"])
    assert any(test["columns"] == ["HER2", "PR"] for test in sigma_plan["tests"])
    assert any(test["columns"] == ["Molecular subtype", "PR"] for test in sigma_plan["tests"])

    output = results.run_plan(df, classifications, assignment, sigma_plan, session=session)
    assert len(output["tests"]) == len(sigma_plan["tests"])
    assert not output["plan_mismatch"]
    assert all("no numeric values to summarise" not in test["narrative"] for test in output["tests"])
    assert "Kolmogorov-Smirnov (50" not in output["methods_md"]
    assert "Normality of PR" not in output["methods_md"]
    assert "chi-square or Fisher's exact test as appropriate" in output["methods_md"]

    descriptive = results.run_plan(
        df, classifications, assignment,
        {"tests": [{"id": "descriptive_only", "title": "Descriptive summary"}], "graphs": []},
        session={},
    )
    assert "summarised categorically" in descriptive["tests"][0]["narrative"]
    assert descriptive["tests"][0]["rows"]

    scale_assignment = {"outcome": "Age", "group": None, "covariates": []}
    scale_output = results.run_plan(
        df, classifications, scale_assignment,
        {"tests": [{"id": "descriptive_only", "title": "Descriptive summary"}], "graphs": []},
        session={},
    )
    assert "Lilliefors" in scale_output["methods_md"]
    assert "Kolmogorov-Smirnov (50" not in scale_output["methods_md"]

    mismatch_plan = {
        "tests": [{
            "id": "association_bad",
            "title": "Invalid categorical comparison",
            "columns": ["ER", "PR"],
            "_phase_b": {
                "function": "run_chi_or_fisher",
                "test_type": "chi_square",
                "args": {"col1": "ER", "col2": "missing_column"},
            },
        }],
        "graphs": [],
    }
    mismatch = results.run_plan(df, classifications, assignment, mismatch_plan, session=session)
    assert mismatch["plan_mismatch"]
    assert "did not produce valid statistical results" in mismatch["results_md"]

    print("Sigma Step 7 categorical-results verification passed.")


if __name__ == "__main__":
    main()
