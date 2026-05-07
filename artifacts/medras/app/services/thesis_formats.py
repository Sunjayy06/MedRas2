"""Thesis chapter spines.

One canonical Indian MD / DNB / PhD spine matches the four sample theses
the user uploaded (NBEMS-style). University-specific rules (page count,
font, line spacing, margins, reference minimum, citation style,
declarations) are layered on top via ``thesis_guidelines_parser``.

Public surface
--------------
* ``CHAPTER_SPINE`` — ordered list[Chapter] for Indian MD/DNB/PhD
* ``DEFAULT_RULES`` — NBEMS-derived defaults (used when the researcher
  does not upload their university's guidelines PDF)
* ``apply_rules(spine, rules)`` -> spine with target word counts injected
"""
from __future__ import annotations

from typing import Any, Dict, List, TypedDict


class Chapter(TypedDict, total=False):
    id: str            # stable slug for keying state
    label: str         # display name
    group: str         # "front" | "body" | "back"
    target_words: int  # default word target; can be overridden by uni rules
    helpers: List[str] # which Helper-Strip buttons to show in the editor
    description: str   # one-line guidance for the dashboard tooltip


# Indian MD / DNB / PhD spine — matches the four sample theses verbatim.
CHAPTER_SPINE: List[Chapter] = [
    {"id": "title_page", "label": "Title page & IEC committee", "group": "front",
     "target_words": 80, "helpers": [],
     "description": "Institution header, title in caps, PI / Guide / Co-Guide, IEC committee."},
    {"id": "certificates", "label": "Certificates & declarations", "group": "front",
     "target_words": 200, "helpers": [],
     "description": "Guide certificate, originality declaration, plagiarism certificate."},
    {"id": "abbreviations", "label": "List of abbreviations", "group": "front",
     "target_words": 120, "helpers": ["scan_text"],
     "description": "Auto-extract from your text — review and add."},
    {"id": "abstract", "label": "Abstract", "group": "front",
     "target_words": 280, "helpers": ["ai_draft", "rag_cite"],
     "description": "Background · Methods · Results · Conclusion · Keywords (250-300 w)."},
    {"id": "introduction", "label": "Chapter I — Introduction", "group": "body",
     "target_words": 1800, "helpers": ["ai_draft", "rag_cite", "plagiarism"],
     "description": "Set the clinical / scientific stage; problem burden; gaps; rationale."},
    {"id": "aims", "label": "Chapter II — Aims & Objectives", "group": "body",
     "target_words": 200, "helpers": ["study_builder"],
     "description": "Single aim + 2-4 specific measurable objectives."},
    {"id": "literature_review", "label": "Chapter III — Review of Literature", "group": "body",
     "target_words": 6500, "helpers": ["ai_draft", "rag_cite", "summarise_refs", "plagiarism"],
     "description": "Synthesise prior work — agreements, disagreements, gaps."},
    {"id": "methods", "label": "Chapter IV — Materials & Methods", "group": "body",
     "target_words": 2200, "helpers": ["sample_size", "study_builder", "ai_draft", "rag_cite"],
     "description": "Design · setting · participants · sampling · variables · stats plan."},
    {"id": "results", "label": "Chapter V — Observations & Results", "group": "body",
     "target_words": 2500, "helpers": ["stats_engine", "import_stats", "ai_draft"],
     "description": "Tables, graphs and prose — locked numbers from your data."},
    {"id": "discussion", "label": "Chapter VI — Discussion", "group": "body",
     "target_words": 2800, "helpers": ["ai_draft", "rag_cite", "compare_lit", "plagiarism"],
     "description": "Interpret your findings in the light of prior literature."},
    {"id": "summary", "label": "Chapter VII — Summary", "group": "body",
     "target_words": 600, "helpers": ["ai_draft"],
     "description": "Crisp recap of the entire thesis (≤1 page)."},
    {"id": "conclusion", "label": "Chapter VIII — Conclusion", "group": "body",
     "target_words": 400, "helpers": ["ai_draft"],
     "description": "Take-home message + actionable recommendations + future directions."},
    {"id": "proforma", "label": "Proforma / Case record form", "group": "back",
     "target_words": 0, "helpers": [],
     "description": "Data collection sheet — single line spacing."},
    {"id": "consent", "label": "Informed consent (multi-language)", "group": "back",
     "target_words": 0, "helpers": ["consent_translate"],
     "description": "Reuses MedRAS consent translator — English mandatory + Indian languages."},
    {"id": "references", "label": "References", "group": "back",
     "target_words": 0, "helpers": ["rag_cite"],
     "description": "Validated bibliography — minimum per university guidelines."},
    {"id": "annexures", "label": "Annexures", "group": "back",
     "target_words": 0, "helpers": [],
     "description": "IEC approval, plagiarism cert, publications, master chart."},
]


# NBEMS defaults from the user's uploaded "Thesis_protocol_&_thesis_submission_guidelines"
DEFAULT_RULES: Dict[str, Any] = {
    "max_pages":       80,
    "min_pages":       40,
    "font_family":     "Times New Roman",
    "font_alternates": ["Arial", "Garamond"],
    "font_size_pt":    12,
    "line_spacing":    1.5,
    "margin_inches":   1.0,
    "paper":           "A4",
    "citation_style":  "vancouver",   # ICMJE per NBEMS
    "min_references":  100,           # user-mandated; NBEMS guideline says 10-25 for the *protocol*
    "max_word_intro":  None,
    "section_word_caps": {            # rough per-chapter caps from NBEMS p.9
        "introduction": 1000,
        "literature_review": 7500,
        "discussion": 6000,
    },
    "declarations_required": [
        "Guide certificate",
        "Co-guide certificate",
        "Originality declaration",
        "Plagiarism certificate (UGC ≤10% rule)",
        "IEC approval letter",
    ],
    "iec_required": True,
    "consent_required": True,
    "consent_languages_default": ["English", "Hindi", "Tamil", "Telugu", "Kannada"],
}


def apply_rules(spine: List[Chapter], rules: Dict[str, Any]) -> List[Chapter]:
    """Return a copy of the spine with per-chapter ``target_words`` adjusted
    when the rules supply a ``section_word_caps`` map.
    """
    caps = (rules or {}).get("section_word_caps") or {}
    out: List[Chapter] = []
    for ch in spine:
        copy = dict(ch)
        if ch["id"] in caps:
            copy["target_words"] = int(caps[ch["id"]])
        out.append(copy)  # type: ignore[arg-type]
    return out


def all_chapter_ids() -> List[str]:
    return [c["id"] for c in CHAPTER_SPINE]
