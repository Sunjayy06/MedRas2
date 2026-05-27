"""Thesis & article chapter spines.

Two kinds of writing are supported:

1. **Thesis** — one canonical Indian MD / DNB / PhD spine (``CHAPTER_SPINE``)
   that matches the four sample theses the user uploaded (NBEMS-style).
   University-specific rules (page count, font, line spacing, margins,
   reference minimum, citation style, declarations) are layered on top
   via ``thesis_guidelines_parser``.

2. **Article** — eight reporting-checklist spines (``ARTICLE_SPINES``)
   keyed by checklist (``care``, ``consort``, ``strobe``, ``prisma``,
   ``moose``, ``coreq``, ``imrad``, ``narrative``). The right spine is
   resolved from ``(article_type, design)`` via ``resolve_checklist``.
   Per-section word budgets are derived at request-time from the
   journal-tier the researcher targets (``JOURNAL_TIERS``: T1-T4).

Public surface
--------------
* ``CHAPTER_SPINE``     — ordered list[Chapter] for Indian MD/DNB/PhD
* ``DEFAULT_RULES``     — NBEMS-derived defaults (used when no uni PDF)
* ``ARTICLE_SPINES``    — {checklist: list[Chapter]}
* ``JOURNAL_TIERS``     — {tier_id: {body_words_min/max, abstract_words, …}}
* ``resolve_checklist(article_type, design)`` -> checklist id
* ``get_article_spine(article_type, design)`` -> list[Chapter]
* ``get_tier_targets(tier)``  -> dict (with sensible default for unknowns)
* ``apply_tier_to_spine(spine, tier_targets)`` -> spine with per-section
  ``target_words`` injected from each chapter's ``share`` fraction.
* ``apply_rules(spine, rules)`` -> thesis spine with uni-rule overrides.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class Chapter(TypedDict, total=False):
    id: str              # stable slug for keying state
    label: str           # display name
    group: str           # "front" | "body" | "back"
    target_words: int    # default word target; overridden by uni rules / tier
    word_budget: List[int]  # [min, max] word range for the editor word-count badge
    share: float         # fraction of body word budget (article spines only)
    helpers: List[str]   # which Helper-Strip buttons to show in the editor
    description: str     # one-line guidance for the dashboard tooltip


# ===========================================================================
# Thesis spine (Indian MD / DNB / PhD) — unchanged
# ===========================================================================
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
     "target_words": 280, "word_budget": [250, 300],
     "helpers": ["ai_draft", "rag_cite"],
     "description": "Background · Methods · Results · Conclusion · Keywords (250-300 w)."},
    {"id": "introduction", "label": "Chapter I — Introduction", "group": "body",
     "target_words": 1800, "word_budget": [1500, 2200],
     "helpers": ["ai_draft", "rag_cite", "plagiarism"],
     "description": "Set the clinical / scientific stage; problem burden; gaps; rationale."},
    {"id": "aims", "label": "Chapter II — Aims & Objectives", "group": "body",
     "target_words": 200, "word_budget": [150, 300],
     "helpers": ["study_builder"],
     "description": "Single aim + 2-4 specific measurable objectives."},
    {"id": "literature_review", "label": "Chapter III — Review of Literature", "group": "body",
     "target_words": 6500, "word_budget": [5500, 7500],
     "helpers": ["ai_draft", "draft_by_section", "rag_cite", "summarise_refs", "plagiarism"],
     "description": "Synthesise prior work — agreements, disagreements, gaps."},
    {"id": "methods", "label": "Chapter IV — Materials & Methods", "group": "body",
     "target_words": 2200, "word_budget": [1800, 2400],
     "helpers": ["sample_size", "study_builder", "ai_draft", "rag_cite"],
     "description": "Design · setting · participants · sampling · variables · stats plan."},
    {"id": "results", "label": "Chapter V — Observations & Results", "group": "body",
     "target_words": 2500, "word_budget": [2000, 3000],
     "helpers": ["stats_engine", "import_stats", "ai_draft"],
     "description": "Tables, graphs and prose — locked numbers from your data."},
    {"id": "discussion", "label": "Chapter VI — Discussion", "group": "body",
     "target_words": 2800, "word_budget": [2400, 3200],
     "helpers": ["ai_draft", "rag_cite", "compare_lit", "plagiarism"],
     "description": "Interpret your findings in the light of prior literature."},
    {"id": "summary", "label": "Chapter VII — Summary", "group": "body",
     "target_words": 600, "word_budget": [500, 700],
     "helpers": ["ai_draft"],
     "description": "Crisp recap of the entire thesis (≤1 page)."},
    {"id": "conclusion", "label": "Chapter VIII — Conclusion", "group": "body",
     "target_words": 400, "word_budget": [300, 500],
     "helpers": ["ai_draft"],
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


# ===========================================================================
# Article spines — one per ICMJE-aligned reporting checklist
# ===========================================================================
# Each section's ``share`` is its slice of the *body* word budget (sum of
# shares in each spine ≈ 1.00). ``abstract`` chapters are sized from the
# tier's ``abstract_words`` and don't carry a share. ``title``, ``keywords``,
# ``funding``, ``registration`` and ``references`` use small fixed defaults.

# --- CARE: Case Report -----------------------------------------------------
ARTICLE_SPINES: Dict[str, List[Chapter]] = {
"care": [
    {"id": "title", "label": "Title", "group": "front", "target_words": 25, "helpers": [],
     "description": "Include the words 'case report' and the area of focus."},
    {"id": "abstract", "label": "Abstract (unstructured ≤ 250 w)", "group": "front",
     "helpers": ["ai_draft"],
     "description": "Introduction · main symptoms / clinical findings · main diagnoses, interventions & outcomes · conclusion."},
    {"id": "keywords", "label": "Keywords (3–5)", "group": "front", "target_words": 15, "helpers": [],
     "description": "MeSH terms preferred."},
    {"id": "introduction", "label": "Introduction", "group": "body", "share": 0.10,
     "helpers": ["ai_draft", "rag_cite"],
     "description": "Why this case matters — context and brief literature note."},
    {"id": "patient_information", "label": "Patient Information", "group": "body", "share": 0.10,
     "helpers": ["ai_draft"],
     "description": "De-identified demographics, primary concerns and symptoms, medical/family/psychosocial history, relevant past interventions."},
    {"id": "clinical_findings", "label": "Clinical Findings", "group": "body", "share": 0.10,
     "helpers": ["ai_draft"],
     "description": "Relevant physical examination and other clinical findings."},
    {"id": "timeline", "label": "Timeline", "group": "body", "share": 0.05,
     "helpers": [],
     "description": "Key dates and events of the episode of care, organised as a table or narrative."},
    {"id": "diagnostic_assessment", "label": "Diagnostic Assessment", "group": "body", "share": 0.15,
     "helpers": ["ai_draft", "rag_cite"],
     "description": "Diagnostic methods, challenges, reasoning, prognostic characteristics and differentials considered."},
    {"id": "therapeutic_intervention", "label": "Therapeutic Intervention", "group": "body", "share": 0.10,
     "helpers": ["ai_draft", "rag_cite"],
     "description": "Type, administration, dosage, duration; changes with rationale."},
    {"id": "follow_up_outcomes", "label": "Follow-up & Outcomes", "group": "body", "share": 0.10,
     "helpers": ["ai_draft"],
     "description": "Clinician-assessed and patient-reported outcomes; intervention adherence/tolerability; adverse events."},
    {"id": "discussion", "label": "Discussion", "group": "body", "share": 0.25,
     "helpers": ["ai_draft", "rag_cite", "compare_lit", "plagiarism"],
     "description": "Strengths and limitations · relevant medical literature · rationale for conclusions · primary 'take-away' lessons."},
    {"id": "patient_perspective", "label": "Patient Perspective", "group": "body", "share": 0.05,
     "helpers": [],
     "description": "Where applicable — share the patient's experience or perspective in a brief paragraph."},
    {"id": "informed_consent", "label": "Informed Consent Statement", "group": "back",
     "target_words": 60, "helpers": ["consent_translate"],
     "description": "Mandatory under CARE — written informed consent obtained from the patient (or guardian) for publication."},
    {"id": "references", "label": "References", "group": "back",
     "target_words": 0, "helpers": ["rag_cite"],
     "description": "Vancouver / journal-specified style."},
],

# --- CONSORT: Randomised Controlled Trial ---------------------------------
"consort": [
    {"id": "title", "label": "Title (must say 'randomised')", "group": "front",
     "target_words": 25, "helpers": [],
     "description": "Identification as a randomised trial in the title."},
    {"id": "abstract", "label": "Structured Abstract", "group": "front",
     "helpers": ["ai_draft"],
     "description": "Background · Methods (design, participants, interventions, outcomes, randomisation, blinding) · Results · Conclusions · Trial registration."},
    {"id": "keywords", "label": "Keywords", "group": "front", "target_words": 15, "helpers": []},
    {"id": "introduction", "label": "Introduction (background, rationale, objectives)", "group": "body",
     "share": 0.12, "helpers": ["ai_draft", "rag_cite"],
     "description": "Scientific background and explanation of rationale; specific objectives or hypotheses."},
    {"id": "methods_design_participants", "label": "Methods · Trial Design & Participants", "group": "body",
     "share": 0.10, "helpers": ["ai_draft", "study_builder"],
     "description": "Description of trial design (parallel/crossover, allocation ratio); important changes after start; eligibility criteria; settings and locations."},
    {"id": "methods_interventions", "label": "Methods · Interventions", "group": "body",
     "share": 0.06, "helpers": ["ai_draft"],
     "description": "Interventions for each group with sufficient detail to allow replication, including how and when administered."},
    {"id": "methods_outcomes", "label": "Methods · Outcomes", "group": "body",
     "share": 0.05, "helpers": ["ai_draft"],
     "description": "Completely defined pre-specified primary and secondary outcomes; any changes after trial start."},
    {"id": "methods_sample_size", "label": "Methods · Sample Size", "group": "body",
     "share": 0.05, "helpers": ["sample_size", "ai_draft"],
     "description": "How sample size was determined; if applicable, any interim analyses and stopping guidelines."},
    {"id": "methods_randomisation_blinding", "label": "Methods · Randomisation & Blinding", "group": "body",
     "share": 0.07, "helpers": ["ai_draft"],
     "description": "Sequence generation; allocation concealment mechanism; implementation; blinding (who and how)."},
    {"id": "methods_statistics", "label": "Methods · Statistical Methods", "group": "body",
     "share": 0.05, "helpers": ["stats_engine", "ai_draft"],
     "description": "Statistical methods for primary and secondary outcomes; subgroup and adjusted analyses."},
    {"id": "results_flow", "label": "Results · Participant Flow (CONSORT diagram)", "group": "body",
     "share": 0.05, "helpers": [],
     "description": "Flow of participants through each stage (randomised, received intended treatment, analysed for primary outcome). Diagram strongly recommended."},
    {"id": "results_recruitment_baseline", "label": "Results · Recruitment & Baseline", "group": "body",
     "share": 0.05, "helpers": ["import_stats"],
     "description": "Dates defining recruitment and follow-up; baseline demographic and clinical characteristics for each group."},
    {"id": "results_outcomes", "label": "Results · Outcomes & Estimation", "group": "body",
     "share": 0.15, "helpers": ["stats_engine", "import_stats", "ai_draft"],
     "description": "For each outcome: results for each group, estimated effect size, precision (95 % CI). Locked numbers from Sigma."},
    {"id": "results_harms", "label": "Results · Harms / Adverse Events", "group": "body",
     "share": 0.05, "helpers": ["ai_draft"],
     "description": "All important harms or unintended effects in each group (per CONSORT-Harms extension)."},
    {"id": "discussion", "label": "Discussion (limitations, generalisability, interpretation)", "group": "body",
     "share": 0.20, "helpers": ["ai_draft", "rag_cite", "compare_lit", "plagiarism"],
     "description": "Trial limitations · generalisability · interpretation consistent with results balancing benefits and harms."},
    {"id": "registration", "label": "Trial Registration & Protocol", "group": "back",
     "target_words": 80, "helpers": [],
     "description": "Registration number and name of trial registry (CTRI / ClinicalTrials.gov). Where the full trial protocol can be accessed."},
    {"id": "funding", "label": "Funding & Conflicts of Interest", "group": "back",
     "target_words": 60, "helpers": [],
     "description": "Sources of funding and other support; role of funders."},
    {"id": "references", "label": "References", "group": "back",
     "target_words": 0, "helpers": ["rag_cite"],
     "description": "Vancouver / journal-specified style."},
],

# --- STROBE: Observational (cohort, case-control, cross-sectional) --------
"strobe": [
    {"id": "title", "label": "Title (state the study design)", "group": "front",
     "target_words": 25, "helpers": [],
     "description": "Indicate the study's design with a commonly used term (cohort / case-control / cross-sectional)."},
    {"id": "abstract", "label": "Structured Abstract", "group": "front",
     "helpers": ["ai_draft"],
     "description": "Informative and balanced summary of what was done and what was found."},
    {"id": "keywords", "label": "Keywords", "group": "front", "target_words": 15, "helpers": []},
    {"id": "introduction", "label": "Introduction (background, objectives/hypotheses)", "group": "body",
     "share": 0.12, "helpers": ["ai_draft", "rag_cite"],
     "description": "Scientific background and rationale; specific objectives, including any pre-specified hypotheses."},
    {"id": "methods_design_setting", "label": "Methods · Study Design & Setting", "group": "body",
     "share": 0.06, "helpers": ["ai_draft", "study_builder"],
     "description": "Key elements of design early in the paper. Setting, locations, relevant dates (recruitment, exposure, follow-up, data collection)."},
    {"id": "methods_participants", "label": "Methods · Participants", "group": "body",
     "share": 0.08, "helpers": ["ai_draft"],
     "description": "Eligibility criteria, sources and methods of selection; for matched studies, matching criteria and number per case."},
    {"id": "methods_variables", "label": "Methods · Variables & Data Sources", "group": "body",
     "share": 0.07, "helpers": ["ai_draft"],
     "description": "Define all outcomes, exposures, predictors, potential confounders, effect modifiers. Data sources / measurement methods."},
    {"id": "methods_bias_size", "label": "Methods · Bias Control & Study Size", "group": "body",
     "share": 0.05, "helpers": ["sample_size", "ai_draft"],
     "description": "Efforts to address potential sources of bias; how sample size was arrived at."},
    {"id": "methods_statistics", "label": "Methods · Statistical Methods", "group": "body",
     "share": 0.07, "helpers": ["stats_engine", "ai_draft"],
     "description": "Statistical methods including those used to control for confounding; subgroup/sensitivity analyses; missing data handling."},
    {"id": "results_participants", "label": "Results · Participants (with flow diagram)", "group": "body",
     "share": 0.07, "helpers": [],
     "description": "Numbers of individuals at each stage (eligible, examined for eligibility, included, analysed). Flow diagram suggested."},
    {"id": "results_descriptive", "label": "Results · Descriptive Data", "group": "body",
     "share": 0.07, "helpers": ["import_stats"],
     "description": "Characteristics of study participants; information on exposures and potential confounders; missing data per variable."},
    {"id": "results_outcome", "label": "Results · Outcome Data", "group": "body",
     "share": 0.05, "helpers": ["import_stats"],
     "description": "Numbers of outcome events or summary measures over time."},
    {"id": "results_main", "label": "Results · Main Results (with 95 % CIs)", "group": "body",
     "share": 0.10, "helpers": ["stats_engine", "import_stats", "ai_draft"],
     "description": "Unadjusted and confounder-adjusted estimates with precision (95 % CI). Locked numbers from Sigma."},
    {"id": "results_other", "label": "Results · Other Analyses (subgroups, sensitivity)", "group": "body",
     "share": 0.05, "helpers": ["ai_draft"],
     "description": "Any other analyses done — e.g. subgroups, interactions, sensitivity analyses."},
    {"id": "discussion", "label": "Discussion (key results · limitations · interpretation · generalisability)", "group": "body",
     "share": 0.21, "helpers": ["ai_draft", "rag_cite", "compare_lit", "plagiarism"],
     "description": "Summary of key results · limitations (sources of bias and imprecision) · cautious overall interpretation · generalisability (external validity)."},
    {"id": "funding", "label": "Funding & Conflicts of Interest", "group": "back",
     "target_words": 60, "helpers": [],
     "description": "Sources of funding and the role of funders."},
    {"id": "references", "label": "References", "group": "back",
     "target_words": 0, "helpers": ["rag_cite"]},
],

# --- PRISMA: Systematic Review --------------------------------------------
"prisma": [
    {"id": "title", "label": "Title (identified as a systematic review)", "group": "front",
     "target_words": 25, "helpers": [],
     "description": "Identify the report as a systematic review."},
    {"id": "abstract", "label": "Structured Abstract (PRISMA-A)", "group": "front",
     "helpers": ["ai_draft"],
     "description": "Background · Objectives · Data sources · Study eligibility · Participants · Interventions · Synthesis · Results · Limitations · Conclusions · Funding · Registration."},
    {"id": "keywords", "label": "Keywords", "group": "front", "target_words": 15, "helpers": []},
    {"id": "introduction", "label": "Introduction (rationale + PICO objectives)", "group": "body",
     "share": 0.10, "helpers": ["ai_draft", "rag_cite"],
     "description": "Rationale for review in context of what is already known; explicit statement of objectives with PICOS components."},
    {"id": "methods_protocol", "label": "Methods · Protocol, Registration & Eligibility", "group": "body",
     "share": 0.06, "helpers": ["ai_draft"],
     "description": "Existence of a protocol (PROSPERO ID) and where it can be accessed; eligibility criteria (PICOS)."},
    {"id": "methods_search", "label": "Methods · Information Sources & Search Strategy", "group": "body",
     "share": 0.07, "helpers": ["ai_draft"],
     "description": "All information sources (databases with dates, contact with authors); full electronic search strategy for at least one database."},
    {"id": "methods_selection", "label": "Methods · Study Selection & Data Extraction", "group": "body",
     "share": 0.06, "helpers": ["ai_draft"],
     "description": "Process for selecting studies (screening, eligibility, included in synthesis); method of data extraction; processes for obtaining and confirming data."},
    {"id": "methods_rob", "label": "Methods · Risk of Bias Assessment", "group": "body",
     "share": 0.05, "helpers": ["ai_draft"],
     "description": "Methods used for assessing risk of bias of individual studies and across studies (e.g. publication bias)."},
    {"id": "methods_synthesis", "label": "Methods · Synthesis & Summary Measures", "group": "body",
     "share": 0.06, "helpers": ["ai_draft"],
     "description": "Principal summary measures (e.g. risk ratio, mean difference); methods of handling data and combining results."},
    {"id": "results_selection", "label": "Results · Study Selection (PRISMA flow diagram)", "group": "body",
     "share": 0.05, "helpers": [],
     "description": "Numbers of studies screened, assessed for eligibility, and included with reasons for exclusions at each stage. PRISMA flow diagram required."},
    {"id": "results_chars", "label": "Results · Study Characteristics", "group": "body",
     "share": 0.10, "helpers": ["import_stats"],
     "description": "Characteristics for each study from which data were extracted (study size, PICOS, follow-up). Provide citations."},
    {"id": "results_rob", "label": "Results · Risk of Bias Within Studies", "group": "body",
     "share": 0.05, "helpers": [],
     "description": "Data on risk of bias of each study and any outcome-level assessment."},
    {"id": "results_synthesis", "label": "Results · Synthesis of Results (forest plots if applicable)", "group": "body",
     "share": 0.10, "helpers": ["stats_engine", "ai_draft"],
     "description": "For each meta-analysis: confidence intervals and measures of consistency. Locked numbers from Sigma."},
    {"id": "results_additional", "label": "Results · Additional Analyses", "group": "body",
     "share": 0.05, "helpers": ["ai_draft"],
     "description": "Subgroup analyses, sensitivity analyses, meta-regression, publication-bias assessment."},
    {"id": "discussion", "label": "Discussion (summary of evidence · limitations · conclusions)", "group": "body",
     "share": 0.20, "helpers": ["ai_draft", "rag_cite", "compare_lit", "plagiarism"],
     "description": "Summary of main findings including strength of evidence; limitations at study and review level; conclusions and implications for future research."},
    {"id": "registration", "label": "Protocol Registration (PROSPERO)", "group": "back",
     "target_words": 60, "helpers": [],
     "description": "PROSPERO registration number / protocol DOI."},
    {"id": "funding", "label": "Funding & Conflicts of Interest", "group": "back",
     "target_words": 60, "helpers": []},
    {"id": "references", "label": "References", "group": "back",
     "target_words": 0, "helpers": ["rag_cite"]},
],

# --- MOOSE: Meta-analysis of Observational Studies (PRISMA + MOOSE adds) -
"moose": [
    {"id": "title", "label": "Title (identified as meta-analysis of observational studies)",
     "group": "front", "target_words": 25, "helpers": []},
    {"id": "abstract", "label": "Structured Abstract", "group": "front", "helpers": ["ai_draft"],
     "description": "Background · Objectives · Data sources · Study selection · Data extraction · Synthesis · Results · Conclusions."},
    {"id": "keywords", "label": "Keywords", "group": "front", "target_words": 15, "helpers": []},
    {"id": "introduction", "label": "Introduction (problem definition, hypotheses)", "group": "body",
     "share": 0.10, "helpers": ["ai_draft", "rag_cite"],
     "description": "Problem definition; hypothesis statement; description of study outcomes; type of exposure; type of study designs used; study population."},
    {"id": "methods_search", "label": "Methods · Search Strategy", "group": "body",
     "share": 0.08, "helpers": ["ai_draft"],
     "description": "Qualifications of searchers; databases and registries; search software; effort to include all available studies; databases and registries searched; search terms; restrictions; methods to address publications in languages other than English."},
    {"id": "methods_selection", "label": "Methods · Study Selection & Data Extraction", "group": "body",
     "share": 0.06, "helpers": ["ai_draft"],
     "description": "Inclusion / exclusion criteria; rationale for selection; methods of extraction (independent, dual); training of extractors; reliability of extraction."},
    {"id": "methods_observational", "label": "Methods · Observational-Specific Items (MOOSE)", "group": "body",
     "share": 0.07, "helpers": ["ai_draft"],
     "description": "Confounding assessment; quality assessment of observational studies; assessment of heterogeneity of exposure measurement; rationale for choice of summary measures."},
    {"id": "methods_synthesis", "label": "Methods · Statistical Synthesis", "group": "body",
     "share": 0.06, "helpers": ["ai_draft"],
     "description": "Statistical synthesis (fixed vs random effects); heterogeneity assessment (I², Cochran's Q); subgroup analyses; sensitivity analyses; publication bias."},
    {"id": "results_selection", "label": "Results · Study Selection (PRISMA-style flow diagram)",
     "group": "body", "share": 0.05, "helpers": [],
     "description": "Graphic summarising individual study estimates and overall estimate; PRISMA-style flow diagram."},
    {"id": "results_chars", "label": "Results · Study Characteristics", "group": "body",
     "share": 0.10, "helpers": ["import_stats"],
     "description": "Table giving descriptive information for each study; results of sensitivity testing."},
    {"id": "results_synthesis", "label": "Results · Synthesis (forest, funnel, heterogeneity)",
     "group": "body", "share": 0.12, "helpers": ["stats_engine", "ai_draft"],
     "description": "Pooled estimates with 95 % CI; heterogeneity (I²); forest and funnel plots. Locked numbers from Sigma."},
    {"id": "discussion", "label": "Discussion (bias, applicability, future research)", "group": "body",
     "share": 0.21, "helpers": ["ai_draft", "rag_cite", "compare_lit", "plagiarism"],
     "description": "Quantitative assessment of bias (e.g. publication bias); justification for exclusion; assessment of quality of included studies; applicability of findings; suggestions for future research."},
    {"id": "registration", "label": "Protocol Registration (PROSPERO)", "group": "back",
     "target_words": 60, "helpers": []},
    {"id": "funding", "label": "Funding & Conflicts of Interest", "group": "back",
     "target_words": 60, "helpers": []},
    {"id": "references", "label": "References", "group": "back",
     "target_words": 0, "helpers": ["rag_cite"]},
],

# --- COREQ: Qualitative ---------------------------------------------------
"coreq": [
    {"id": "title", "label": "Title", "group": "front", "target_words": 25, "helpers": []},
    {"id": "abstract", "label": "Abstract", "group": "front", "helpers": ["ai_draft"]},
    {"id": "keywords", "label": "Keywords", "group": "front", "target_words": 15, "helpers": []},
    {"id": "introduction", "label": "Introduction (background, research question)", "group": "body",
     "share": 0.12, "helpers": ["ai_draft", "rag_cite"],
     "description": "Background and research question framed in qualitative paradigm."},
    {"id": "methods_team", "label": "Methods · Research Team & Reflexivity", "group": "body",
     "share": 0.08, "helpers": ["ai_draft"],
     "description": "Personal characteristics (interviewer, credentials, occupation, gender, experience, training); relationship with participants (established prior, interviewer characteristics, reasons/interests known)."},
    {"id": "methods_design", "label": "Methods · Study Design (theoretical framework, sampling)",
     "group": "body", "share": 0.08, "helpers": ["ai_draft"],
     "description": "Theoretical framework (grounded theory, ethnography, phenomenology, content analysis); participant selection (sampling, approach, sample size, non-participation); setting (data collection setting, presence of non-participants, description of sample)."},
    {"id": "methods_data_collection", "label": "Methods · Data Collection", "group": "body",
     "share": 0.10, "helpers": ["ai_draft"],
     "description": "Interview guide (provided, pilot tested); repeat interviews; audio/visual recording; field notes; duration; data saturation; transcripts returned."},
    {"id": "methods_analysis", "label": "Methods · Analysis & Findings", "group": "body",
     "share": 0.10, "helpers": ["ai_draft"],
     "description": "Number of data coders; description of coding tree; derivation of themes; software; participant checking."},
    {"id": "results", "label": "Findings (themes with participant-attributed quotes)", "group": "body",
     "share": 0.30, "helpers": ["ai_draft", "import_stats"],
     "description": "Quotations to illustrate themes/findings (each quotation identified by participant code); description of diverse cases or minor themes; consistency of data and findings."},
    {"id": "discussion", "label": "Discussion (interpretation, transferability)", "group": "body",
     "share": 0.22, "helpers": ["ai_draft", "rag_cite", "compare_lit", "plagiarism"],
     "description": "Interpretation in light of existing theory; transferability rather than statistical generalisability; limitations."},
    {"id": "funding", "label": "Funding & Conflicts of Interest", "group": "back",
     "target_words": 60, "helpers": []},
    {"id": "references", "label": "References", "group": "back",
     "target_words": 0, "helpers": ["rag_cite"]},
],

# --- IMRaD generic (Original Research catch-all when design unknown) -----
"imrad": [
    {"id": "title", "label": "Title", "group": "front", "target_words": 25, "helpers": []},
    {"id": "abstract", "label": "Structured Abstract (Background · Methods · Results · Conclusions)",
     "group": "front", "helpers": ["ai_draft"]},
    {"id": "keywords", "label": "Keywords (3–6, MeSH preferred)", "group": "front",
     "target_words": 15, "helpers": []},
    {"id": "introduction", "label": "Introduction", "group": "body", "share": 0.15,
     "helpers": ["ai_draft", "rag_cite"],
     "description": "Background, gap in knowledge, study aim and hypothesis."},
    {"id": "methods", "label": "Methods", "group": "body", "share": 0.20,
     "helpers": ["sample_size", "study_builder", "ai_draft"],
     "description": "Design, setting, participants, variables, data sources, sample size, statistical methods."},
    {"id": "results", "label": "Results", "group": "body", "share": 0.25,
     "helpers": ["stats_engine", "import_stats", "ai_draft"],
     "description": "Findings in a logical sequence with tables and figures; locked numbers from Sigma."},
    {"id": "discussion", "label": "Discussion", "group": "body", "share": 0.25,
     "helpers": ["ai_draft", "rag_cite", "compare_lit", "plagiarism"],
     "description": "Interpretation, comparison with literature, limitations, generalisability."},
    {"id": "conclusion", "label": "Conclusion", "group": "body", "share": 0.05,
     "helpers": ["ai_draft"],
     "description": "Single-paragraph take-home message and implications."},
    {"id": "acknowledgements", "label": "Acknowledgements", "group": "back",
     "target_words": 60, "helpers": []},
    {"id": "funding", "label": "Funding & Conflicts of Interest", "group": "back",
     "target_words": 60, "helpers": []},
    {"id": "references", "label": "References", "group": "back",
     "target_words": 0, "helpers": ["rag_cite"]},
    {"id": "tables", "label": "Tables", "group": "back",
     "target_words": 0, "helpers": ["import_stats"]},
    {"id": "figures", "label": "Figures & Legends", "group": "back",
     "target_words": 0, "helpers": []},
],

# --- Narrative Review ------------------------------------------------------
"narrative": [
    {"id": "title", "label": "Title", "group": "front", "target_words": 25, "helpers": []},
    {"id": "abstract", "label": "Abstract (unstructured)", "group": "front",
     "helpers": ["ai_draft"]},
    {"id": "keywords", "label": "Keywords", "group": "front", "target_words": 15, "helpers": []},
    {"id": "introduction", "label": "Introduction (rationale, scope, framework)", "group": "body",
     "share": 0.12, "helpers": ["ai_draft", "rag_cite"]},
    {"id": "body_section_1", "label": "Thematic Section 1", "group": "body", "share": 0.18,
     "helpers": ["ai_draft", "rag_cite", "plagiarism"],
     "description": "Rename to your first major theme."},
    {"id": "body_section_2", "label": "Thematic Section 2", "group": "body", "share": 0.18,
     "helpers": ["ai_draft", "rag_cite", "plagiarism"],
     "description": "Rename to your second major theme."},
    {"id": "body_section_3", "label": "Thematic Section 3", "group": "body", "share": 0.18,
     "helpers": ["ai_draft", "rag_cite", "plagiarism"],
     "description": "Rename to your third major theme."},
    {"id": "synthesis", "label": "Conceptual Synthesis", "group": "body", "share": 0.14,
     "helpers": ["ai_draft"],
     "description": "Integrate the themes into a model or framework."},
    {"id": "discussion", "label": "Discussion / Future Directions", "group": "body",
     "share": 0.20, "helpers": ["ai_draft", "compare_lit"]},
    {"id": "funding", "label": "Funding & Conflicts of Interest", "group": "back",
     "target_words": 60, "helpers": []},
    {"id": "references", "label": "References", "group": "back",
     "target_words": 0, "helpers": ["rag_cite"]},
],
}


# ===========================================================================
# Article-type → checklist mapping
# ===========================================================================
CHECKLIST_BY_ARTICLE_TYPE: Dict[str, str] = {
    "case_report":       "care",
    "case_series":       "strobe",
    "narrative_review":  "narrative",
    "systematic_review": "prisma",
    "meta_analysis":     "moose",
    "original_research": "imrad",
    "monograph":         "imrad",
}

# Original Research → checklist override based on study design
CHECKLIST_BY_DESIGN: Dict[str, str] = {
    "rct":                       "consort",
    "cohort_prospective":        "strobe",
    "cohort_retrospective":      "strobe",
    "case_control":              "strobe",
    "cross_sectional":           "strobe",
    "qualitative":               "coreq",
    "quasi_experimental":        "strobe",
    "kap_survey":                "strobe",
    "community_survey":          "strobe",
    "diagnostic_accuracy":       "imrad",   # STARD spine could be added later
    "economic_evaluation":       "imrad",   # CHEERS spine could be added later
    "mixed_methods":             "imrad",
}


def resolve_checklist(article_type: str, design: str = "") -> str:
    """Return the checklist id for a given (article_type, design).

    For ``original_research`` the design routes between CONSORT / STROBE /
    COREQ. For all other article types the article-type itself decides.
    Falls back to ``imrad`` for anything we don't recognise so the editor
    always has a usable spine.
    """
    article_type = (article_type or "").strip().lower()
    design = (design or "").strip().lower()
    if article_type == "original_research" and design in CHECKLIST_BY_DESIGN:
        return CHECKLIST_BY_DESIGN[design]
    return CHECKLIST_BY_ARTICLE_TYPE.get(article_type, "imrad")


def get_article_spine(article_type: str, design: str = "") -> List[Chapter]:
    """Return a deep-enough copy of the right article spine."""
    checklist = resolve_checklist(article_type, design)
    raw = ARTICLE_SPINES.get(checklist) or ARTICLE_SPINES["imrad"]
    return [dict(ch) for ch in raw]


# ===========================================================================
# Journal tiers (T1-T4) — body / abstract / reference targets
# ===========================================================================
JOURNAL_TIERS: Dict[str, Dict[str, Any]] = {
    "t1": {
        "id": "t1",
        "label": "Tier 1 — Top medical journals",
        "examples": "NEJM · Lancet · JAMA · BMJ · Annals Int Med",
        "abstract_words": 250,
        "abstract_structured": True,
        "body_words_min": 2700,
        "body_words_max": 3500,
        "ref_min": 30, "ref_max": 40,
        "figures_max": 5,
        "default_citation_style": "vancouver",
        "default_plag_cap": 8,
        "default_ai_cap": 5,
    },
    "t2": {
        "id": "t2",
        "label": "Tier 2 — High-impact specialty",
        "examples": "Cell · Nature Med · Circulation · JCO · Lancet sub-specialties",
        "abstract_words": 250,
        "abstract_structured": True,
        "body_words_min": 3500,
        "body_words_max": 4500,
        "ref_min": 40, "ref_max": 60,
        "figures_max": 8,
        "default_citation_style": "vancouver",
        "default_plag_cap": 10,
        "default_ai_cap": 8,
    },
    "t3": {
        "id": "t3",
        "label": "Tier 3 — Mid-impact Scopus / Elsevier / Springer",
        "examples": "BMC · PLOS · BMJ Open · Frontiers · most society journals",
        "abstract_words": 300,
        "abstract_structured": True,
        "body_words_min": 4000,
        "body_words_max": 5000,
        "ref_min": 40, "ref_max": 60,
        "figures_max": 10,
        "default_citation_style": "vancouver",
        "default_plag_cap": 10,
        "default_ai_cap": 10,
    },
    "t4": {
        "id": "t4",
        "label": "Tier 4 — Low-impact Scopus / regional",
        "examples": "Cureus · Indian J Med Res · regional society journals",
        "abstract_words": 300,
        "abstract_structured": False,
        "body_words_min": 5000,
        "body_words_max": 6000,
        "ref_min": 30, "ref_max": None,
        "figures_max": None,
        "default_citation_style": "vancouver",
        "default_plag_cap": 15,
        "default_ai_cap": 15,
    },
}


def get_tier_targets(tier: str) -> Dict[str, Any]:
    """Return tier targets dict; falls back to T3 (the broadest fit)."""
    return JOURNAL_TIERS.get((tier or "").strip().lower()) or JOURNAL_TIERS["t3"]


def apply_tier_to_spine(
    spine: List[Chapter],
    tier_targets: Dict[str, Any],
) -> List[Chapter]:
    """Inject ``target_words`` into each chapter using its ``share`` of the
    tier's body-word budget. Sections that already have a ``target_words``
    set (title, keywords, abstract, funding, references) are preserved;
    abstract gets the tier's ``abstract_words``.
    """
    body_mid = (
        int(tier_targets.get("body_words_min", 4000)) +
        int(tier_targets.get("body_words_max", 5000))
    ) // 2
    abstract_words = int(tier_targets.get("abstract_words", 280))
    out: List[Chapter] = []
    for ch in spine:
        copy = dict(ch)
        if copy.get("id") == "abstract":
            copy["target_words"] = abstract_words
        elif "share" in copy:
            copy["target_words"] = max(80, int(round(copy["share"] * body_mid)))
        # else: target_words already set on the chapter
        out.append(copy)  # type: ignore[arg-type]
    return out


# ===========================================================================
# Thesis-side helpers (unchanged)
# ===========================================================================
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
    """Every chapter id we know about (thesis + every article spine).

    Used by ``thesis_export`` so figures attached to article-only chapters
    aren't silently dropped from the export bundle.
    """
    seen: List[str] = [c["id"] for c in CHAPTER_SPINE]
    seen_set = set(seen)
    for spine in ARTICLE_SPINES.values():
        for ch in spine:
            if ch["id"] not in seen_set:
                seen.append(ch["id"])
                seen_set.add(ch["id"])
    return seen
