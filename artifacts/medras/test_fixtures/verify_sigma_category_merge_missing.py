"""Verify category merges preserve true missing values."""

import pandas as pd

from app.services.category_merger import apply_merges


def main() -> None:
    original = pd.DataFrame(
        {
            "ER status": [
                "Positive",
                "Postive",
                pd.NA,
                float("nan"),
                None,
                "Negative",
            ]
        }
    )

    merged, actions = apply_merges(
        original,
        [
            {
                "column": "ER status",
                "canonical": "Positive",
                "members": ["Positive", "Postive"],
            }
        ],
    )

    values = merged["ER status"]
    assert values.iloc[0] == "Positive"
    assert values.iloc[1] == "Positive"
    assert values.iloc[5] == "Negative"
    assert values.iloc[2:5].isna().all()
    assert "nan" not in values.dropna().astype(str).str.lower().tolist()
    assert int(values.isna().sum()) == int(original["ER status"].isna().sum())
    assert len(actions) == 1

    print("Sigma category merge missing-value verification passed.")


if __name__ == "__main__":
    main()
