"""Lightweight PHI screening for payloads sent to external AI providers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScreeningResult:
    value: Any
    redaction_applied: bool
    blocked: bool
    categories: tuple[str, ...]


_REDACTIONS = (
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    (
        "phone",
        re.compile(
            r"(?<!\w)(?:\+?91[\s.-]?)?[6-9]\d{4}[\s.-]?\d{5}(?!\w)|"
            r"\b(?:phone|mobile|contact)\s*(?:number|no\.?)?\s*[:#-]?\s*"
            r"(?:\+?\d[\d\s().-]{7,}\d)\b",
            re.I,
        ),
    ),
    (
        "medical_record_id",
        re.compile(
            r"\b(?:mrn|medical\s*record|hospital\s*id|patient\s*id|uhid|"
            r"accession(?:\s*(?:id|no|number))?)\s*[:#-]?\s*[A-Z0-9][A-Z0-9/-]{3,}\b",
            re.I,
        ),
    ),
    (
        "date_of_birth",
        re.compile(
            r"\b(?:dob|date\s*of\s*birth|born\s*on)\s*[:#-]?\s*"
            r"(?:\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2})\b",
            re.I,
        ),
    ),
    ("aadhaar", re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.I)),
    ("long_numeric_id", re.compile(r"(?<!\d)\d{9,}(?!\d)")),
)

_HIGH_RISK = (
    (
        "patient_name",
        re.compile(
            r"\b(?:patient\s*name|name\s*of\s*patient|full\s*name)\s*[:#-]\s*"
            r"[^\n,;]{2,80}",
            re.I,
        ),
    ),
    (
        "patient_address",
        re.compile(
            r"\b(?:patient\s*address|residential\s*address|home\s*address)\s*[:#-]\s*"
            r"[^\n]{5,160}",
            re.I,
        ),
    ),
)


def _screen_text(text: str) -> ScreeningResult:
    redacted = text
    categories: list[str] = []
    blocked = False

    for category, pattern in _HIGH_RISK:
        redacted, count = pattern.subn(f"[REDACTED {category.upper()}]", redacted)
        if count:
            categories.append(category)
            blocked = True

    for category, pattern in _REDACTIONS:
        redacted, count = pattern.subn(f"[REDACTED {category.upper()}]", redacted)
        if count:
            categories.append(category)

    return ScreeningResult(
        value=redacted,
        redaction_applied=redacted != text,
        blocked=blocked,
        categories=tuple(dict.fromkeys(categories)),
    )


def screen_external_ai_payload(value: Any) -> ScreeningResult:
    """Redact supported identifiers recursively without changing non-string values."""
    if isinstance(value, str):
        return _screen_text(value)

    if isinstance(value, dict):
        output = {}
        applied = False
        blocked = False
        categories: list[str] = []
        for key, item in value.items():
            result = screen_external_ai_payload(item)
            output[key] = result.value
            applied = applied or result.redaction_applied
            blocked = blocked or result.blocked
            categories.extend(result.categories)
        return ScreeningResult(output, applied, blocked, tuple(dict.fromkeys(categories)))

    if isinstance(value, (list, tuple)):
        output = []
        applied = False
        blocked = False
        categories: list[str] = []
        for item in value:
            result = screen_external_ai_payload(item)
            output.append(result.value)
            applied = applied or result.redaction_applied
            blocked = blocked or result.blocked
            categories.extend(result.categories)
        converted = tuple(output) if isinstance(value, tuple) else output
        return ScreeningResult(converted, applied, blocked, tuple(dict.fromkeys(categories)))

    return ScreeningResult(value, False, False, ())
