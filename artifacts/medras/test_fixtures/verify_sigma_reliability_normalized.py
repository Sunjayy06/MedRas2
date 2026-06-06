"""Verify normalized reliability tables and Bland-Altman figure.

Run from artifacts/medras:
    python -m test_fixtures.verify_sigma_reliability_normalized
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import results  # noqa: E402


def _tables_by_title(normalized: dict) -> dict:
    return {table["title"]: table for table in normalized["tables"]}


def verify_kappa_adapter() -> None:
    raw = {
        "test": "Weighted Kappa",
        "test_type": "kappa",
        "kappa": 0.72,
        "ci": (0.61, 0.82),
        "p": 0.002,
        "interpretation": "substantial",
    }
    normalized = results.normalize_result_for_rendering(raw)
    table = _tables_by_title(normalized)["Kappa Reliability"]
    values = {row[0]: row[1] for row in table["rows"]}

    assert values["Method"] == "Weighted Kappa"
    assert values["Kappa value"] == "0.720"
    assert values["95% CI"] == "0.610 to 0.820"
    assert values["p-value"] == "p = 0.002"
    assert values["Interpretation"] == "substantial"
    assert normalized["kappa"] == raw["kappa"]


def verify_icc_bland_altman_adapter() -> None:
    raw = {
        "test": "ICC and Bland-Altman",
        "test_type": "icc",
        "icc": 0.91,
        "icc_ci": (0.84, 0.96),
        "icc_model": "ICC(C,1)",
        "icc_p": 0.0002,
        "icc_interpretation": "excellent",
        "bland_altman": {
            "mean_bias": 0.25,
            "loa_lower": -1.20,
            "loa_upper": 1.70,
        },
        "bland_altman_plot_data": {
            "means": [10.0, 11.0, 12.0, 13.0],
            "differences": [0.1, 0.4, -0.2, 0.7],
        },
    }
    normalized = results.normalize_result_for_rendering(raw)
    tables = _tables_by_title(normalized)

    icc_values = {row[0]: row[1] for row in tables["ICC Reliability"]["rows"]}
    assert icc_values["ICC value"] == "0.910"
    assert icc_values["95% CI"] == "0.840 to 0.960"
    assert icc_values["Model used"] == "ICC(C,1)"
    assert icc_values["Interpretation"] == "excellent"

    ba_values = {row[0]: row[1] for row in tables["Bland-Altman Agreement"]["rows"]}
    assert ba_values["Mean bias"] == "0.250"
    assert ba_values["Lower limit of agreement"] == "-1.200"
    assert ba_values["Upper limit of agreement"] == "1.700"

    assert any(
        figure.get("title") == "Bland-Altman plot"
        and str(figure.get("png_data_uri", "")).startswith("data:image/png;base64,")
        for figure in normalized["figures"]
    )
    assert normalized["icc"] == raw["icc"]
    assert normalized["bland_altman"] == raw["bland_altman"]


if __name__ == "__main__":
    verify_kappa_adapter()
    verify_icc_bland_altman_adapter()
    print("Sigma reliability normalized result verification passed.")
