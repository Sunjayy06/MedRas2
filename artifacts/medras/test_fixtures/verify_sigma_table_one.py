"""Verify thesis-ready Sigma Table One summaries.

Run from artifacts/medras:
    python -m test_fixtures.verify_sigma_table_one
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.results import build_table_one  # noqa: E402


def _row(table_one: dict, variable: str) -> dict:
    return next(row for row in table_one["rows"] if row["variable"] == variable)


def verify_table_one() -> None:
    df = pd.DataFrame(
        {
            "group": ["A"] * 5 + ["B"] * 5,
            "status": ["Positive", "Negative", np.nan, "Positive", "nan",
                       "Negative", "Negative", "Positive", np.nan, "Positive"],
            "category": ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C1", np.nan],
            "age": [40, 42, np.nan, 44, 46, 50, 52, 54, 56, np.nan],
        }
    )
    classifications = [
        {"column": "group", "detected_type": "nominal"},
        {"column": "status", "detected_type": "nominal"},
        {"column": "category", "detected_type": "nominal"},
        {"column": "age", "detected_type": "scale"},
    ]

    table_one = build_table_one(df, classifications, "group")

    status = _row(table_one, "status")
    assert status["type"] == "n (%)"
    assert "Positive: 2 (40.0%)" in status["cells"][0]
    assert "Negative: 1 (20.0%)" in status["cells"][0]
    assert "Missing: 2 (40.0%)" in status["cells"][0]
    assert "nan" not in status["cells"][0].lower()

    category = _row(table_one, "category")
    category_text = " ".join(category["cells"])
    assert "C1:" in category_text
    assert "C8:" in category_text
    assert "Other categories not shown" not in category_text
    assert "Missing: 1 (20.0%)" in category["cells"][1]

    age = _row(table_one, "age")
    assert "Missing: 1 (20.0%)" in age["cells"][0]
    assert "Missing: 1 (20.0%)" in age["cells"][1]
    assert "nan" not in " ".join(age["cells"]).lower()


if __name__ == "__main__":
    verify_table_one()
    print("Sigma Table One verification passed.")
