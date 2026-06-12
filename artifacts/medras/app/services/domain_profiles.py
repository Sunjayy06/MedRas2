"""Domain-profile helpers for Sigma preprocessing and study setup."""

from typing import Literal


DomainProfile = Literal["generic", "clinical_general", "breast_pathology"]
SUPPORTED_PROFILES = frozenset({"generic", "clinical_general", "breast_pathology"})
DEFAULT_PROFILE: DomainProfile = "generic"


def normalize_profile(value: str | None) -> DomainProfile:
    candidate = str(value or "").strip().lower()
    if candidate in SUPPORTED_PROFILES:
        return candidate  # type: ignore[return-value]
    return DEFAULT_PROFILE


def is_clinical(profile: str | None) -> bool:
    return normalize_profile(profile) in {"clinical_general", "breast_pathology"}


def is_breast_pathology(profile: str | None) -> bool:
    return normalize_profile(profile) == "breast_pathology"


def provenance(profile: str, message: str) -> str:
    return f"Suggested by {normalize_profile(profile)} profile: {message}"
