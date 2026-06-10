"""Verify rule-based Sigma normality guidance matches the normality engine."""

from app.services import chatboxes


def _reply(message: str, context: dict | None = None) -> str:
    result = chatboxes.reply(
        "normality",
        message,
        context or {"columns": []},
        external_ai_consent=False,
    )
    return result["text"]


def verify_medium_sample_guidance() -> None:
    text = _reply("Which KS test is used?").lower()
    assert "does not use a plain kolmogorov-smirnov" in text
    assert "lilliefors-corrected" in text
    assert "shapiro-wilk as a fallback" in text
    assert "we use it for samples between 50 and 2000" not in text


def verify_small_sample_guidance() -> None:
    text = _reply("Explain Shapiro-Wilk").lower()
    assert "under 50 observations" in text
    assert "50 to 2000" in text
    assert "lilliefors" in text


def verify_large_sample_guidance() -> None:
    context = {
        "columns": [{
            "column": "Age",
            "decision": "skipped",
            "test": "Skipped (n > 2000)",
            "p_value": None,
        }]
    }
    text = _reply("What does the Age result mean?", context).lower()
    assert "does not confirm normality" in text
    assert "qq plot" in text
    assert "skewness" in text
    assert "kurtosis" in text
    assert "researcher judgment" in text
    assert "insufficient data" not in text


def verify_transform_guidance() -> None:
    text = _reply("Explain log transformation").lower()
    assert "same sample-size-based normality checks" in text
    assert "pass shapiro-wilk" not in text


def main() -> None:
    verify_medium_sample_guidance()
    verify_small_sample_guidance()
    verify_large_sample_guidance()
    verify_transform_guidance()
    print("Sigma normality assistant guidance verification passed.")


if __name__ == "__main__":
    main()
