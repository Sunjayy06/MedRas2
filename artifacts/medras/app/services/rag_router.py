"""RAG domain detection + database routing.

This module decides *which* academic databases the retriever should query
for a given user task. It does **not** perform the search — that's
``rag_retriever.py``. It does **not** ship trusted local guidelines —
that's ``rag_guidelines.py``.

Public surface
--------------
* ``DOMAIN_DATABASE_MAP``        — dict[domain] -> list[database_id]
* ``detect_domain(role, fmt, topic)`` -> domain str
* ``get_databases_for_domain(domain)`` -> list[database_id]
* ``route(role, fmt, topic)``    -> {"domain": ..., "databases": [...]}
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional

# ---------------------------------------------------------------------------
# Domain → database map
# ---------------------------------------------------------------------------

DOMAIN_DATABASE_MAP: dict[str, list[str]] = {
    "medical_clinical":     ["pubmed", "europe_pmc", "cochrane", "crossref", "openalex"],
    "pharmacology":         ["pubmed", "europe_pmc", "crossref", "openalex"],
    "nursing":              ["pubmed", "europe_pmc", "cinahl_open", "crossref"],
    "engineering":          ["semantic_scholar", "crossref", "openalex", "ieee_open"],
    "computer_science":     ["semantic_scholar", "crossref", "openalex", "arxiv"],
    "social_sciences":      ["semantic_scholar", "openalex", "crossref", "doaj"],
    "psychology":           ["semantic_scholar", "openalex", "crossref", "pubmed"],
    "business_economics":   ["openalex", "crossref", "semantic_scholar", "doaj"],
    "law":                  ["openalex", "crossref", "doaj", "semantic_scholar"],
    "education":            ["openalex", "semantic_scholar", "crossref", "doaj"],
    "humanities":           ["openalex", "crossref", "doaj", "semantic_scholar"],
    "general":              ["crossref", "openalex", "semantic_scholar"],
}

ALL_DOMAINS: tuple[str, ...] = tuple(DOMAIN_DATABASE_MAP.keys())

# ---------------------------------------------------------------------------
# Format-id → domain hint (uses the ids from ``app/services/format_templates``
# and ``public/proposal-module/js/format.js``).
# ---------------------------------------------------------------------------

_FORMAT_DOMAIN: dict[str, str] = {
    # Medical / health funders & regulators (ids match public/proposal-module/js/format.js)
    "icmr":          "medical_clinical",
    "icmr-tf":       "medical_clinical",
    "iec-human":     "medical_clinical",
    "iec-animal":    "medical_clinical",
    "ich-gcp":       "medical_clinical",
    "ctri":          "medical_clinical",
    "ayush":         "medical_clinical",
    "who":           "medical_clinical",
    "nih-r01":       "medical_clinical",
    "nih-r21":       "medical_clinical",
    "nihr":          "medical_clinical",
    "mrc":           "medical_clinical",
    "nhmrc":         "medical_clinical",
    "wellcome":      "medical_clinical",
    "gates":         "medical_clinical",
    "md-ms-syn":     "medical_clinical",
    # Biotech (lean medical/pharma)
    "dbt":           "pharmacology",
    # Generic science funders — depend on topic
    "dst-crg":       "general",
    "dst-ecr":       "general",
    "csir":          "general",
    "horizon":       "general",
    # University / institutional — depend on topic
    "ugc-major":     "general",
    "ugc-minor":     "general",
    "phd-syn":       "general",
    "inst-diss":     "general",
}

# ---------------------------------------------------------------------------
# Topic-keyword → domain. Order matters only for ties; the scorer below
# simply counts hits and picks the highest-scoring domain.
# ---------------------------------------------------------------------------

_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "medical_clinical": (
        "patient", "patients", "clinical", "clinic", "disease", "diagnosis",
        "treatment", "therapy", "therapeutic", "hospital", "icu", "outpatient",
        "inpatient", "surgery", "surgical", "doctor", "physician", "nurse",
        "epidemiology", "morbidity", "mortality", "incidence", "prevalence",
        "syndrome", "symptom", "comorbidity", "trial", "rct", "cohort",
        "case-control", "biopsy", "biomarker", "vaccine", "covid", "cancer",
        "diabetes", "hypertension", "tuberculosis", "tb", "hiv", "stroke",
        "cardiac", "renal", "hepatic", "pulmonary", "neurological",
    ),
    "pharmacology": (
        "drug", "drugs", "pharmacokinetic", "pharmacodynamic", "dose", "dosage",
        "molecule", "compound", "ic50", "receptor", "agonist", "antagonist",
        "inhibitor", "formulation", "bioavailability", "adverse event",
        "side effect", "ade", "adr", "pharmacology", "pharmaceutical",
        "ayurveda", "herbal", "phytochemical",
    ),
    "nursing": (
        "nursing", "nurse", "care plan", "patient care", "bedside",
        "ward", "icu nurse", "midwifery", "midwife",
    ),
    "engineering": (
        "engineering", "mechanical", "civil", "electrical", "electronic",
        "circuit", "material", "alloy", "concrete", "structural", "robotic",
        "manufacturing", "fabrication", "thermal", "fluid", "aerospace",
        "biomedical engineering",
    ),
    "computer_science": (
        "algorithm", "algorithms", "software", "machine learning", "ml",
        "deep learning", "neural network", "ai", "artificial intelligence",
        "computer vision", "nlp", "natural language", "data structure",
        "compiler", "operating system", "cybersecurity", "cryptography",
        "blockchain", "cloud", "distributed system", "database", "iot",
        "computer science", "programming",
    ),
    "social_sciences": (
        "society", "social", "sociology", "anthropology", "community",
        "demograph", "ethnograph", "qualitative interview", "policy",
        "governance", "public administration",
    ),
    "psychology": (
        "psychology", "psychological", "cognitive", "behaviour", "behavior",
        "mental health", "depression", "anxiety", "stress", "trauma", "ptsd",
        "personality", "perception", "memory", "learning theory",
        "psychiatric", "psychotherapy",
    ),
    "business_economics": (
        "business", "management", "marketing", "finance", "economic",
        "economics", "macroeconomic", "microeconomic", "supply chain",
        "consumer", "market", "trade", "stock", "valuation", "entrepreneur",
        "startup", "hr ", "human resource",
    ),
    "law": (
        "law", "legal", "constitution", "statute", "tort", "contract law",
        "criminal", "jurisprudence", "judgment", "court", "litigation",
        "intellectual property", "patent law",
    ),
    "education": (
        "education", "pedagogy", "curriculum", "classroom", "teacher",
        "student learning", "learning outcome", "school", "university",
        "teaching method", "e-learning", "edtech",
    ),
    "humanities": (
        "history", "historical", "philosophy", "literature", "literary",
        "linguistic", "linguistics", "religion", "cultural studies", "art",
        "music", "theatre",
    ),
}

_WORD = re.compile(r"[A-Za-z][A-Za-z\-]+")


def _topic_scores(topic: str) -> dict[str, int]:
    """Return {domain: hit_count} from keyword matching against the topic."""
    if not topic:
        return {}
    blob = " " + topic.lower() + " "
    scores: dict[str, int] = {}
    for dom, kws in _DOMAIN_KEYWORDS.items():
        score = 0
        for kw in kws:
            # Multi-word phrase: substring match.
            if " " in kw or "-" in kw:
                if kw in blob:
                    score += 1
            else:
                # Whole-word match to avoid e.g. "law" hitting "lawful".
                if re.search(r"\b" + re.escape(kw) + r"\b", blob):
                    score += 1
        if score:
            scores[dom] = score
    return scores


def detect_domain(
    role: Optional[str] = None,
    selected_format: Optional[str] = None,
    topic: Optional[str] = None,
) -> str:
    """Return the best-fit domain for the given user context.

    Strategy
    --------
    1. Score the topic against keyword sets.
    2. If the format gives a strong domain hint (e.g. ICMR → medical), and
       the topic does NOT strongly disagree, prefer the format hint.
    3. Otherwise pick the top-scoring topic domain.
    4. Fall back to ``"general"`` if nothing matches.

    The role string is currently advisory only — it is preserved in the
    signature for future heuristics (e.g. UG vs PhD wording weight).
    """
    _ = role  # reserved for future
    fmt_hint = _FORMAT_DOMAIN.get((selected_format or "").strip().lower())
    scores = _topic_scores(topic or "")

    # If the topic strongly indicates a non-medical domain, let it win even
    # over a medical format hint (e.g. an ICMR call about an ML diagnostic
    # tool should still route to CS adjacent databases as well — but here
    # we still keep the medical hint for proposal/grant work because that's
    # what the funder will be reading).
    if fmt_hint and fmt_hint != "general":
        # Only override if topic shows ≥3 hits in a clearly different
        # domain AND zero hits in the format's own domain.
        if scores:
            top_dom, top_score = max(scores.items(), key=lambda kv: kv[1])
            if top_score >= 3 and scores.get(fmt_hint, 0) == 0 and top_dom != fmt_hint:
                return top_dom
        return fmt_hint

    if scores:
        # Pick highest-scoring; tie-break by DOMAIN_DATABASE_MAP iteration order.
        top_dom = max(scores.items(), key=lambda kv: (kv[1], -list(DOMAIN_DATABASE_MAP).index(kv[0])))
        return top_dom[0]

    return "general"


def get_databases_for_domain(domain: str) -> List[str]:
    """Return the ordered list of database ids for the given domain."""
    return list(DOMAIN_DATABASE_MAP.get((domain or "").strip().lower(),
                                        DOMAIN_DATABASE_MAP["general"]))


def route(
    role: Optional[str] = None,
    selected_format: Optional[str] = None,
    topic: Optional[str] = None,
    extra_databases: Optional[Iterable[str]] = None,
) -> dict:
    """One-shot helper combining detection + lookup.

    Returns ``{"domain": <domain>, "databases": [...]}``. Pass
    ``extra_databases`` to append always-on sources without changing the
    domain mapping (deduplicated, order preserved).
    """
    dom = detect_domain(role, selected_format, topic)
    dbs = get_databases_for_domain(dom)
    if extra_databases:
        seen = set(dbs)
        for d in extra_databases:
            if d and d not in seen:
                dbs.append(d); seen.add(d)
    return {"domain": dom, "databases": dbs}
