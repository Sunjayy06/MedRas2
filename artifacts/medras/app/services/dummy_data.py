"""Generate realistic medical dummy datasets for practice / demo.

Values follow plausible clinical distributions (log-normal for lab markers
that must be positive; normal for age and anthropometrics; binomial for
categoricals). The shapes / SDs are tuned so common tests give meaningful
(not pathological) p-values, which makes the module easy to demonstrate.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd


def _rng(seed: int | None) -> np.random.Generator:
    return np.random.default_rng(seed if seed is not None else 42)


def _inject_missing(df: pd.DataFrame, pct: float, rng: np.random.Generator) -> pd.DataFrame:
    """Sprinkle ``pct`` percent missing values into non-ID, non-group columns."""
    if pct <= 0:
        return df
    skip = {"Patient_ID", "Group", "Treatment", "Sex", "Diagnosis"}
    for col in df.columns:
        if col in skip:
            continue
        mask = rng.random(len(df)) < (pct / 100.0)
        df.loc[mask, col] = np.nan
    return df


def _anaemia(n: int, n_groups: int, rng: np.random.Generator) -> pd.DataFrame:
    sex = rng.choice(["Male", "Female"], size=n, p=[0.45, 0.55])
    age = rng.normal(loc=42, scale=14, size=n).clip(18, 80).round(0)
    if n_groups <= 1:
        group = np.array(["Cohort"] * n)
    else:
        labels = (["Iron"] + (["Placebo"] if n_groups == 2 else ["B12", "Placebo"]))[:n_groups]
        group = rng.choice(labels, size=n)
    # Hb depends on group and sex (treatment arm slightly higher).
    base_hb = np.where(sex == "Male", 13.5, 12.0)
    treatment_lift = np.where(group == labels[0] if n_groups > 1 else False, 1.4, 0.0)
    hb = base_hb + treatment_lift + rng.normal(0, 1.4, size=n)
    ferritin = rng.lognormal(mean=3.0, sigma=0.7, size=n)  # log-normal, always positive
    severity = rng.choice([1, 2, 3, 4], size=n, p=[0.4, 0.3, 0.2, 0.1])
    return pd.DataFrame(
        {
            "Patient_ID": np.arange(1, n + 1),
            "Age": age.astype(int),
            "Sex": sex,
            "Group": group,
            "Hb": np.round(hb, 1),
            "Ferritin": np.round(ferritin, 1),
            "Severity": severity,
        }
    )


def _diabetes(n: int, n_groups: int, rng: np.random.Generator) -> pd.DataFrame:
    sex = rng.choice(["Male", "Female"], size=n, p=[0.5, 0.5])
    age = rng.normal(loc=55, scale=11, size=n).clip(28, 85).round(0)
    if n_groups <= 1:
        group = np.array(["Cohort"] * n)
    else:
        labels = (["Metformin"] + (["Placebo"] if n_groups == 2 else ["Insulin", "Placebo"]))[:n_groups]
        group = rng.choice(labels, size=n)
    bmi = rng.normal(loc=29, scale=5, size=n).clip(18, 50)
    base_hba1c = 8.5 - np.where(group == labels[0] if n_groups > 1 else False, 1.0, 0.0)
    hba1c = base_hba1c + rng.normal(0, 1.1, size=n)
    fbs = rng.lognormal(mean=4.85, sigma=0.25, size=n)  # ~120-180 mg/dL
    return pd.DataFrame(
        {
            "Patient_ID": np.arange(1, n + 1),
            "Age": age.astype(int),
            "Sex": sex,
            "Group": group,
            "BMI": np.round(bmi, 1),
            "HbA1c": np.round(hba1c, 1),
            "FBS": np.round(fbs, 0).astype(int),
        }
    )


def _hypertension(n: int, n_groups: int, rng: np.random.Generator) -> pd.DataFrame:
    sex = rng.choice(["Male", "Female"], size=n)
    age = rng.normal(loc=58, scale=12, size=n).clip(30, 88).round(0)
    if n_groups <= 1:
        group = np.array(["Cohort"] * n)
    else:
        labels = (["DrugA"] + (["Placebo"] if n_groups == 2 else ["DrugB", "Placebo"]))[:n_groups]
        group = rng.choice(labels, size=n)
    base_sbp = 150
    drug_drop = np.where(group == labels[0] if n_groups > 1 else False, 12, 0)
    sbp = base_sbp - drug_drop + rng.normal(0, 12, size=n)
    dbp = sbp - rng.normal(loc=55, scale=10, size=n)
    smoker = rng.choice(["Yes", "No"], size=n, p=[0.3, 0.7])
    return pd.DataFrame(
        {
            "Patient_ID": np.arange(1, n + 1),
            "Age": age.astype(int),
            "Sex": sex,
            "Group": group,
            "SBP": np.round(sbp, 0).astype(int),
            "DBP": np.round(np.clip(dbp, 50, 110), 0).astype(int),
            "Smoker": smoker,
        }
    )


_GENERATORS = {
    "anaemia": _anaemia,
    "diabetes": _diabetes,
    "hypertension": _hypertension,
}


def list_templates() -> List[Dict[str, str]]:
    return [
        {"id": "anaemia", "label": "Anaemia trial", "description": "Hb, Ferritin, Severity"},
        {"id": "diabetes", "label": "Diabetes trial", "description": "HbA1c, FBS, BMI"},
        {"id": "hypertension", "label": "Hypertension trial", "description": "SBP, DBP, smoking"},
    ]


def generate(
    *,
    template: str,
    n_patients: int = 150,
    n_groups: int = 2,
    missing_pct: float = 5.0,
    seed: int | None = None,
) -> pd.DataFrame:
    if template not in _GENERATORS:
        raise ValueError(f"Unknown template: {template}. Choose one of {list(_GENERATORS)}.")
    n_patients = max(10, min(n_patients, 5000))
    n_groups = max(1, min(n_groups, 3))
    rng = _rng(seed)
    df = _GENERATORS[template](n_patients, n_groups, rng)
    return _inject_missing(df, missing_pct, rng)
