"""Verify HER2 classification, cleanup gating, and stable backup naming."""

from pathlib import Path

try:
    import pandas as pd
    from app.services import variable_assistant, variable_classifier, variable_issues
except ModuleNotFoundError:
    pd = None
    variable_assistant = variable_classifier = variable_issues = None


def verify_her2_classification() -> None:
    status = variable_classifier.classify_column(
        pd.Series(["Negative", "Positive", "Negative"]),
        "Her2Neu",
        profile="breast_pathology",
    )
    assert status["detected_type"] == "nominal"

    constant_status = variable_classifier.classify_column(
        pd.Series(["Negative", "Negative"]),
        "HER2",
        profile="breast_pathology",
    )
    assert constant_status["detected_type"] == "nominal"

    score = variable_classifier.classify_column(
        pd.Series(["0", "1+", "2+", "3+"]),
        "HER2 Score",
        profile="breast_pathology",
    )
    assert score["detected_type"] == "ordinal"

    numeric_score = variable_classifier.classify_column(
        pd.Series([0, 1, 2, 3]),
        "HER2 Score",
        profile="breast_pathology",
    )
    assert numeric_score["detected_type"] == "ordinal"

    mixed = variable_classifier.classify_column(
        pd.Series(["Negative", "Positive", "1+", "2+", "3+"]),
        "Her2Neu",
        profile="breast_pathology",
    )
    assert mixed["detected_type"] == "nominal"


def verify_no_numeric_cleanup_or_blocking_issue() -> None:
    df = pd.DataFrame({
        "Her2Neu": ["Negative", "Positive", "1+", "2+", "3+"],
        "ER": ["Positive", "Negative", "Positive", "Negative", "Positive"],
    })
    cleaned, notes = variable_classifier.clean_numeric_like_columns(
        df, profile="breast_pathology"
    )
    assert cleaned.equals(df)
    assert "Her2Neu" not in notes

    forced_numeric = [
        {"column": "Her2Neu", "detected_type": "scale", "missing_pct": 0},
        {"column": "ER", "detected_type": "scale", "missing_pct": 0},
    ]
    issues = variable_issues.detect_issues(
        df, forced_numeric, profile="breast_pathology"
    )
    assert not any(i["type"] == "text_in_numeric" for i in issues)


def verify_assistant_does_not_strip_markers_or_chain_backups() -> None:
    her2 = pd.DataFrame({"Her2Neu": ["Negative", "Positive", "1+"]})
    try:
        variable_assistant.apply_action(
            her2,
            {"action": "strip_prefix", "column": "Her2Neu", "params": {}},
            profile="breast_pathology",
        )
    except ValueError as exc:
        assert "categorical clinical marker" in str(exc)
    else:
        raise AssertionError("HER2 strip-prefix action should be rejected")

    grade = pd.DataFrame({"Grade": ["Grade 1", "Grade 2", "Grade 3"]})
    once, _ = variable_assistant.apply_action(
        grade, {"action": "strip_prefix", "column": "Grade", "params": {}}
    )
    twice, _ = variable_assistant.apply_action(
        once, {"action": "strip_prefix", "column": "Grade", "params": {}}
    )
    assert "Grade_original" in twice.columns
    assert not any("_original_original" in c for c in twice.columns)

    try:
        variable_assistant.apply_action(
            twice,
            {"action": "strip_prefix", "column": "Grade_original", "params": {}},
        )
    except ValueError as exc:
        assert "already an original-value backup" in str(exc)
    else:
        raise AssertionError("Backup column cleanup should be rejected")


def verify_ui_and_pending_failure_guards() -> None:
    root = Path(__file__).resolve().parents[1]
    js = (root / "public/js/analysis.js").read_text(encoding="utf-8")
    stats = (root / "app/api/stats.py").read_text(encoding="utf-8")
    assert "_isCategoricalClinicalMarkerName(i.column)" in js
    assert "No confirmed action remains pending." in js
    assert "entry.meta.pop(\"pending_variable_assistant_action\", None)" in stats
    assert "Variable Assistant action failed:" in stats


def verify_static_classification_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    classifier = (root / "app/services/variable_classifier.py").read_text(encoding="utf-8")
    assistant = (root / "app/services/variable_assistant.py").read_text(encoding="utf-8")
    assert "_HER2_STATUS_VALUES" in classifier
    assert "_looks_like_her2_status_or_mixed" in classifier
    assert "HER2 score categories - treated as ordinal." in classifier
    assert "is_known_categorical_clinical_marker(col, profile=profile)" in classifier
    assert "_ORIGINAL_SUFFIX_RE" in assistant
    assert "already an original-value backup" in assistant
    assert "profile=profile" in assistant


def main() -> None:
    verify_static_classification_contract()
    if pd is not None:
        verify_her2_classification()
        verify_no_numeric_cleanup_or_blocking_issue()
        verify_assistant_does_not_strip_markers_or_chain_backups()
    verify_ui_and_pending_failure_guards()
    suffix = "" if pd is not None else " (runtime pandas checks skipped)"
    print(f"Sigma HER2 cleaning-loop verification passed.{suffix}")


if __name__ == "__main__":
    main()
