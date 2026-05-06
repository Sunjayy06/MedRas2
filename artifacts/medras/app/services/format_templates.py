"""Authoritative section structure (with subsections) for every supported
proposal format.

This is the source of truth that Step 6 (Generate) will feed into the LLM
prompt and that Step 7/8 (Preview / Download) will use to build the table
of contents and section ordering. The lighter ``js/format.js`` catalog on
the frontend gives the user a checklist of *top-level* sections to
include; this file describes the *subsections* and writing guidance per
section so the AI knows exactly what to draft.

Public surface:
    TEMPLATES                              -> dict[format_id, FormatTemplate]
    get_template(format_id) -> FormatTemplate
    list_templates()        -> list of {id, label, group, sections}
    section_subsections(format_id, section_name) -> list[Subsection]

A ``FormatTemplate`` is a dict with keys::

    id          : machine id matching js/format.js
    label       : human label
    group       : one of "Indian", "International", "Trial / Regulatory"
    word_limit  : approximate word target for the full proposal
    citation    : preferred citation style label
    sections    : ordered list of Section dicts. Each Section is::
        name        : top-level section title (must match js/format.js)
        guidance    : 1-3 sentence brief telling the writer what belongs here
        subsections : ordered list of Subsection dicts. Each Subsection is::
            name      : subsection title (e.g. "Study Design")
            guidance  : 1-line writing brief
            required  : bool — must be present for proposal to be complete
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _sub(name: str, guidance: str, required: bool = True) -> Dict[str, Any]:
    return {"name": name, "guidance": guidance, "required": required}


def _sec(name: str, guidance: str, subs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {"name": name, "guidance": guidance, "subsections": subs or []}


# ---------------------------------------------------------------------------
# Re-usable subsection bundles
# ---------------------------------------------------------------------------

_M_AND_M_FULL = [
    _sub("Study Design",            "Type of study (e.g. randomised controlled trial, cohort, cross-sectional), justification for design choice."),
    _sub("Study Setting",           "Where the study will be conducted — institution, department, geography, level of care."),
    _sub("Study Period",            "Total project duration with start/end and timeline of phases."),
    _sub("Study Population",        "Target and source populations, sampling frame."),
    _sub("Inclusion Criteria",      "Bullet list of objective criteria for participant eligibility."),
    _sub("Exclusion Criteria",      "Bullet list of conditions/characteristics that disqualify a participant."),
    _sub("Sample Size",             "Calculation with assumptions (effect size, alpha, power, attrition); cite the formula and tool."),
    _sub("Sampling Technique",      "Random, stratified, consecutive, purposive — and rationale."),
    _sub("Data Collection Procedure", "Step-by-step protocol from recruitment to data capture; tools/instruments used."),
    _sub("Variables and Operational Definitions", "Primary outcome, secondary outcomes, exposures, confounders — with units and definitions."),
    _sub("Statistical Analysis Plan", "Software, descriptive and inferential tests, handling of missing data, pre-specified subgroup/sensitivity analyses."),
    _sub("Quality Assurance",       "Calibration of instruments, double data entry, training of investigators.", required=False),
]

_ETHICS_BLOCK = [
    _sub("Ethical Approval",        "Confirmation of IEC/IRB review and approval reference number (or that approval will be sought)."),
    _sub("Informed Consent Process","How consent will be obtained, language, witness requirement, special provisions for vulnerable groups."),
    _sub("Data Confidentiality",    "Storage, anonymisation, access controls, retention period."),
    _sub("Risks and Benefits",      "Risks to participants and how they are minimised; expected benefits.", required=True),
    _sub("Conflict of Interest",    "Declaration by all investigators."),
]


# ---------------------------------------------------------------------------
# Templates — Indian funders / regulators
# ---------------------------------------------------------------------------

_ICMR = {
    "id":         "icmr",
    "label":      "ICMR Project Proposal",
    "group":      "Indian",
    "word_limit": 8000,
    "citation":   "Vancouver",
    "sections": [
        _sec("Title",
             "Concise, informative title (≤25 words). Include population, intervention/exposure, comparator, outcome and design."),
        _sec("Investigators and Affiliations",
             "Principal Investigator, Co-Investigators, Collaborators with institutional affiliations and contributions."),
        _sec("Summary / Abstract",
             "Structured 250–300 word summary covering background, objectives, methods, expected outcomes."),
        _sec("Introduction and Background",
             "Magnitude of the problem in India, current evidence and gaps, and why ICMR should fund this work.",
             [_sub("Magnitude of the Problem", "Burden in India and globally with citations."),
              _sub("Current Evidence", "Brief literature review of what is known."),
              _sub("Gaps in Knowledge", "What this study will add."),
              _sub("Rationale for the Study", "Why now, why this design, why this team.")]),
        _sec("Hypothesis",
             "Single, testable, directional hypothesis statement."),
        _sec("Aims and Objectives",
             "Primary aim and 2–4 specific, measurable objectives.",
             [_sub("Primary Objective", "One sentence, measurable."),
              _sub("Secondary Objectives", "Bullet list, each measurable.", required=False)]),
        _sec("Review of Literature",
             "1500–2000 words synthesising the most relevant studies; cite Indian work prominently."),
        _sec("Materials and Methods",
             "Comprehensive methodology — every subsection below is mandatory unless flagged optional.",
             _M_AND_M_FULL),
        _sec("Ethical Considerations",
             "Mandatory section for ICMR; cover IEC approval, consent, confidentiality, and risk mitigation.",
             _ETHICS_BLOCK),
        _sec("Work Plan and Timeline",
             "Gantt chart or month-wise table mapping activities to project months."),
        _sec("Expected Outcome and Implications",
             "Likely findings, public-health relevance and translational pathway."),
        _sec("Budget Justification",
             "Year-wise budget with line-item justification (manpower, consumables, equipment, travel, contingency).",
             [_sub("Manpower",      "Salaries with grade and percentage of effort."),
              _sub("Consumables",   "Reagents, kits, stationery."),
              _sub("Equipment",     "One-time purchases ≥ ICMR threshold with quotations.", required=False),
              _sub("Travel",        "Field visits, conferences."),
              _sub("Contingency",   "5–10% buffer.")]),
        _sec("References",
             "Vancouver-style numbered references; cite recent Indian and global evidence."),
        _sec("Appendices",
             "Case record forms, questionnaires, consent forms, investigator CVs.", []),
    ],
}

_IEC = {
    "id":         "iec",
    "label":      "IEC / Ethics Committee Submission",
    "group":      "Indian",
    "word_limit": 5000,
    "citation":   "Vancouver",
    "sections": [
        _sec("Title and Protocol Number", "Full study title and version-controlled protocol number/date."),
        _sec("Investigators",             "PI, Co-PIs, contact information, qualifications."),
        _sec("Summary of the Study",      "Lay summary in ≤300 words for committee members from non-clinical backgrounds."),
        _sec("Background and Rationale",  "Brief problem statement, evidence gap, scientific justification."),
        _sec("Objectives",                "Primary and secondary objectives."),
        _sec("Study Design and Methods",  "Design, setting, sample, procedures.",
             [_sub("Study Design", "Type and rationale."),
              _sub("Sample Size and Sampling", "Calculation and method."),
              _sub("Study Procedures", "What participants will undergo, including tests, visits, time commitment.")]),
        _sec("Risk–Benefit Assessment",
             "Detailed analysis of physical, psychological, social and economic risks weighed against benefits.",
             [_sub("Risks",    "All foreseeable risks ranked by likelihood and severity."),
              _sub("Benefits", "Direct benefits to participants and societal benefits."),
              _sub("Mitigation", "How identified risks are minimised.")]),
        _sec("Informed Consent Process",
             "Mandatory ICMR-format consent in English + local language(s).",
             [_sub("Consent in English",       "Process and document version."),
              _sub("Consent in Local Language", "Languages used and translation/back-translation method."),
              _sub("Special Populations",       "Provisions for minors, pregnant women, illiterate participants, unconscious patients.", required=False)]),
        _sec("Confidentiality and Data Protection",
             "Storage, anonymisation, access, retention and destruction policies."),
        _sec("Compensation",
             "Reimbursement for travel/time and compensation for study-related injury."),
        _sec("Conflict of Interest",  "Declaration by all investigators."),
        _sec("Publication Policy",    "Plan for publication and authorship; data-sharing intent."),
        _sec("Trial Registration",    "CTRI / clinicaltrials.gov registration plan if applicable.", []),
        _sec("References",            "Vancouver style."),
        _sec("Annexures",             "Protocol, CRF, ICF, questionnaires, investigator CVs, IB if applicable.", []),
    ],
}

_UGC_MAJOR = {
    "id":         "ugc_major",
    "label":      "UGC Major Research Project",
    "group":      "Indian",
    "word_limit": 6000,
    "citation":   "APA",
    "sections": [
        _sec("Title of the Project",        "Concise, descriptive title."),
        _sec("Principal Investigator and Institution", "PI details, designation, department, university."),
        _sec("Introduction",                "Subject area, importance, current scenario.",
             [_sub("Origin of the Research Problem", "Historical and contextual background."),
              _sub("Interdisciplinary Relevance",    "Connections to other disciplines.", required=False),
              _sub("Review of Research and Development in the Subject", "International and national status, significant contributions in India.")]),
        _sec("Objectives",                  "Specific, measurable objectives of the project."),
        _sec("Methodology",
             "Detailed approach for each objective.",
             [_sub("Approach and Hypothesis", "Conceptual framework."),
              _sub("Methods and Materials",   "Tools, sources, instruments."),
              _sub("Sampling and Field Work", "If applicable.", required=False),
              _sub("Data Analysis Plan",      "Quantitative or qualitative techniques.")]),
        _sec("Year-wise Plan of Work",      "Activities and targets for each year."),
        _sec("Expected Output and Outcomes", "Publications, patents, books, dissertations expected."),
        _sec("Budget",                       "Year-wise breakdown.",
             [_sub("Books and Journals",    "One-time."),
              _sub("Equipment",             "Specifications and quotations.", required=False),
              _sub("Contingency",           "Including stationery, photocopying, postage."),
              _sub("Field Work / Travel",   "Inland travel for data collection.", required=False),
              _sub("Hiring of Services",    "Data entry, transcription, etc.", required=False),
              _sub("Honorarium to PI",      "As per UGC norms."),
              _sub("Project Fellow",        "JRF/SRF as applicable.", required=False)]),
        _sec("Bibliographic References",     "APA style."),
    ],
}

_UGC_MINOR = {
    **_UGC_MAJOR, "id": "ugc_minor", "label": "UGC Minor Research Project", "word_limit": 4000,
}

_DST_SERB_CRG = {
    "id":         "dst_serb_crg",
    "label":      "DST-SERB Core Research Grant (CRG)",
    "group":      "Indian",
    "word_limit": 7000,
    "citation":   "Vancouver",
    "sections": [
        _sec("Project Title",                       "Concise scientific title."),
        _sec("Investigators",                       "PI, Co-PIs, mentor (if applicable)."),
        _sec("Project Summary",                     "Structured 500-word summary."),
        _sec("Project Details",
             "Scientific narrative of the proposal.",
             [_sub("Origin of the Proposal",         "Lead-up work and current understanding."),
              _sub("Definition of the Problem",      "Specific scientific question."),
              _sub("Objectives",                     "2–5 specific, measurable objectives."),
              _sub("Hypothesis",                     "Testable hypothesis statement."),
              _sub("Methodology",                    "Detailed scientific methods, instrumentation, statistical analysis."),
              _sub("Time Schedule of Activities",    "Bar chart over project duration."),
              _sub("Expected Outcome",               "Tangible deliverables, manuscripts, IP."),
              _sub("Suggested Plan of Action for Utilisation of Research Outcome", "Translational pathway.")]),
        _sec("National and International Status",   "What's been done; gaps your work addresses."),
        _sec("Preliminary Work Done",                "Pilot data, prior publications by team."),
        _sec("Infrastructure Available",             "Equipment, facilities, lab capacity."),
        _sec("Budget",
             "Year-wise budget broken down.",
             [_sub("Manpower",   "Project staff with SERB norms."),
              _sub("Consumables","Chemicals, glassware, etc."),
              _sub("Equipment",  "≥ SERB threshold; provide quotations.", required=False),
              _sub("Travel",     "Inland and overseas (with justification)."),
              _sub("Contingency","≤10% of recurring."),
              _sub("Overhead",   "Institutional overhead.")]),
        _sec("Bio-data of Investigators",            "Last 5 years of publications and projects."),
        _sec("References",                           "Vancouver style."),
    ],
}

_DST_SERB_ECR = {
    **_DST_SERB_CRG, "id": "dst_serb_ecr", "label": "DST-SERB Early Career Research Award (ECR)", "word_limit": 6000,
}

_PHD_SYNOPSIS = {
    "id":         "phd_synopsis",
    "label":      "PhD Synopsis",
    "group":      "Indian",
    "word_limit": 5000,
    "citation":   "Vancouver",
    "sections": [
        _sec("Title of the Thesis",                 "Final or working title."),
        _sec("Candidate and Supervisor",            "Name, registration number, department, supervisor(s)."),
        _sec("Introduction",                        "Background and significance of the topic."),
        _sec("Review of Literature",                "Critical review identifying gaps that this thesis fills."),
        _sec("Statement of the Problem",            "What specific research question this thesis answers."),
        _sec("Aims and Objectives",
             "Aim plus 3–5 specific objectives.",
             [_sub("Primary Aim",        "One sentence."),
              _sub("Specific Objectives","Numbered list.")]),
        _sec("Hypothesis",                           "Null and alternative."),
        _sec("Materials and Methods",                "Full methodological detail.", _M_AND_M_FULL),
        _sec("Plan of Work",                         "Year-wise (typically 3–5 years)."),
        _sec("Expected Outcome",                     "Anticipated contributions to the field."),
        _sec("Limitations of the Study",             "Acknowledged constraints."),
        _sec("References",                           "Vancouver style."),
    ],
}

_AYUSH = {
    "id":         "ayush",
    "label":      "Ministry of AYUSH Research Grant",
    "group":      "Indian",
    "word_limit": 6000,
    "citation":   "Vancouver",
    "sections": [
        _sec("Title",                "Title with traditional system specified (Ayurveda / Yoga / Unani / Siddha / Homoeopathy)."),
        _sec("Investigators",         "PI/Co-PI with AYUSH credentials."),
        _sec("Background",            "Classical references, modern understanding, integrative perspective."),
        _sec("Rationale",             "Need from AYUSH and integrative-medicine standpoint."),
        _sec("Objectives",            "Primary and secondary."),
        _sec("Materials and Methods", "Standard methodology with AYUSH-specific elements.", _M_AND_M_FULL + [
            _sub("Drug / Intervention Standardisation", "Source, batch, quality control of classical formulations."),
            _sub("Outcome Measures",                    "Both modern and traditional assessment criteria.")]),
        _sec("Ethical Considerations","IEC + AYUSH-specific guidelines.", _ETHICS_BLOCK),
        _sec("Work Plan",              "Quarterly milestones."),
        _sec("Budget",                 "Year-wise as per AYUSH norms."),
        _sec("References",             "Mix of classical and modern references."),
    ],
}

_CTRI = {
    "id":         "ctri",
    "label":      "CTRI Trial Registration Protocol",
    "group":      "Indian",
    "word_limit": 4500,
    "citation":   "Vancouver",
    "sections": [
        _sec("Public and Scientific Titles",     "Both lay and scientific titles."),
        _sec("Trial Registration Identifiers",   "CTRI number, secondary IDs."),
        _sec("Sponsor and Contacts",              "Sponsor, monitor, PI contact."),
        _sec("Trial Design",                       "Phase, type, allocation, blinding, control."),
        _sec("Population",                          "Target population, inclusion/exclusion."),
        _sec("Interventions",                       "Test and comparator arms with dose, route, frequency, duration."),
        _sec("Outcomes",                            "Primary and secondary outcome definitions and timing of assessment.",
             [_sub("Primary Outcome",   "Single primary endpoint."),
              _sub("Secondary Outcomes","List with measurement methods.")]),
        _sec("Sample Size",                         "Justification."),
        _sec("Statistical Methods",                 "Analysis plan including interim analyses."),
        _sec("Ethical Considerations",              "IEC approval and consent.", _ETHICS_BLOCK),
        _sec("Data Monitoring Committee",           "Composition and stopping rules.", []),
        _sec("Adverse Event Reporting",             "Definitions, timelines and pathways."),
        _sec("References",                          "Vancouver style."),
    ],
}

_DBT = {
    "id":         "dbt",
    "label":      "DBT Research Grant",
    "group":      "Indian",
    "word_limit": 7000,
    "citation":   "Vancouver",
    "sections": [
        _sec("Title and Investigators",           "Title and team."),
        _sec("Project Summary",                    "Structured ≤500 words."),
        _sec("Background and Significance",        "Biotech-relevance and current state of the field."),
        _sec("Hypothesis and Objectives",          "Hypothesis plus 3–5 specific objectives."),
        _sec("Detailed Methodology",                "Wet-lab / dry-lab protocols.", _M_AND_M_FULL),
        _sec("Preliminary Data",                    "Supporting pilot work."),
        _sec("Expected Output",                     "Publications, IP, technology transfer."),
        _sec("Translational Potential",             "Scale-up and commercialisation roadmap.", []),
        _sec("Budget Justification",                 "Year-wise breakdown as per DBT norms."),
        _sec("Bio-data",                             "PI/Co-PI publications and grants."),
        _sec("References",                           "Vancouver style."),
    ],
}

_CSIR = {
    "id":         "csir",
    "label":      "CSIR Research Grant",
    "group":      "Indian",
    "word_limit": 6000,
    "citation":   "Vancouver",
    "sections": [
        _sec("Project Title",          "Concise scientific title."),
        _sec("Investigators",          "PI and Co-PIs."),
        _sec("Project Summary",        "Structured 300-word abstract."),
        _sec("Introduction",           "Scientific background."),
        _sec("Objectives",             "Specific objectives."),
        _sec("Methodology",            "Comprehensive methods.", _M_AND_M_FULL),
        _sec("Work Plan",              "Year-wise activities."),
        _sec("Expected Outcomes",      "Deliverables and impact."),
        _sec("Budget",                 "As per CSIR norms."),
        _sec("References",             "Vancouver style."),
    ],
}


# ---------------------------------------------------------------------------
# Templates — International / regulatory
# ---------------------------------------------------------------------------

_NIH_R01 = {
    "id":         "nih_r01",
    "label":      "NIH R01 Research Project Grant",
    "group":      "International",
    "word_limit": 8000,
    "citation":   "AMA",
    "sections": [
        _sec("Project Summary / Abstract",
             "30 lines (≈400 words) plain-language summary of significance, innovation and approach."),
        _sec("Project Narrative",
             "2–3 sentence relevance statement for the lay public."),
        _sec("Specific Aims",
             "1 page exactly. State 2–4 specific aims with brief approach and expected outcome for each. End with impact statement."),
        _sec("Research Strategy",
             "12 pages total for R01. Three required subsections.",
             [_sub("Significance",
                   "Importance of the problem, how it advances scientific knowledge, technical capability or clinical practice."),
              _sub("Innovation",
                   "How the project challenges current paradigms or develops/refines novel concepts, methods or technologies."),
              _sub("Approach",
                   "Detailed plan for each Specific Aim: rationale, design, expected outcomes, potential pitfalls and alternative strategies, statistical plan, rigor and reproducibility.")]),
        _sec("Bibliography and References Cited",
             "AMA style; no page limit but be selective."),
        _sec("Protection of Human Subjects",
             "Required when applicable.",
             [_sub("Risks to Human Subjects",  "Population, recruitment, study procedures and risks."),
              _sub("Adequacy of Protection",    "Informed consent, IRB review, data safety monitoring."),
              _sub("Potential Benefits",        "To participants and society."),
              _sub("Importance of Knowledge",   "Justification for research given the risks.")]),
        _sec("Inclusion of Women, Minorities and Children",
             "Justification for inclusion/exclusion and recruitment plan.", []),
        _sec("Vertebrate Animals",
             "If applicable: species, justification, minimisation of pain.", []),
        _sec("Resource Sharing Plan",
             "Data sharing, model organism sharing, genome-wide association data."),
        _sec("Authentication of Key Biological and / or Chemical Resources",
             "Up to 1 page; describe authentication methods.", []),
        _sec("Facilities and Other Resources",
             "Lab, clinical, animal, computer, office space available."),
        _sec("Equipment",
             "Major equipment available for the project."),
        _sec("Biographical Sketch",
             "5-page NIH-format biosketch for each Senior/Key person."),
        _sec("Budget and Budget Justification",
             "Detailed (R&R) budget with year-wise modular or detailed breakdown.",
             [_sub("Personnel",         "Person-months, salary, fringe."),
              _sub("Equipment",         ">$5,000 with justification.", required=False),
              _sub("Travel",            "Domestic and foreign with purpose."),
              _sub("Other Direct Costs","Supplies, publication, services."),
              _sub("Indirect Costs",    "Institutional rate.")]),
    ],
}

_WHO = {
    "id":         "who",
    "label":      "WHO Research Proposal",
    "group":      "International",
    "word_limit": 6000,
    "citation":   "Vancouver",
    "sections": [
        _sec("Title",                            "Concise, informative."),
        _sec("Principal Investigator and Team",  "WHO collaborating-centre affiliation if any."),
        _sec("Abstract",                          "Structured 250 words."),
        _sec("Background",                        "Global / regional health relevance and WHO priority alignment."),
        _sec("Justification",                     "Why this study, why now, public-health value."),
        _sec("Goal and Objectives",               "Programmatic goal plus specific objectives."),
        _sec("Methodology",
             "Standard methodological elements.",
             _M_AND_M_FULL + [_sub("Capacity Building Component", "Training and skill transfer to LMIC partners.", required=False)]),
        _sec("Ethical Considerations",            "WHO-ERC compliance + local IEC approval.", _ETHICS_BLOCK),
        _sec("Dissemination Plan",                 "Policy briefs, peer-reviewed publications, WHO reports."),
        _sec("Work Plan and Timeline",             "With Gantt chart."),
        _sec("Budget",                              "USD with currency conversion noted."),
        _sec("References",                          "Vancouver style."),
    ],
}

_ICH_GCP = {
    "id":         "ich_gcp",
    "label":      "ICH-GCP Clinical Trial Protocol",
    "group":      "Trial / Regulatory",
    "word_limit": 12000,
    "citation":   "Vancouver",
    "sections": [
        _sec("General Information",
             "Protocol title, identifying number, version date, sponsor, monitor, investigator, qualified physician."),
        _sec("Background Information",
             "Name and description of investigational product(s), summary of findings from non-clinical and clinical studies, summary of known and potential risks and benefits, route of administration, dose, dosage regimen, treatment period, statement that the trial will be conducted in compliance with the protocol, GCP and applicable regulatory requirements, description of the population, references to literature."),
        _sec("Trial Objectives and Purpose",
             "Detailed primary and secondary objectives."),
        _sec("Trial Design",
             "Endpoints, type of trial, schematic diagram, measures to minimise bias, description of trial treatment, expected duration of subject participation, stopping rules, source data accountability, randomisation and blinding maintenance."),
        _sec("Selection and Withdrawal of Subjects",
             "Inclusion/exclusion criteria; withdrawal criteria and procedures.",
             [_sub("Inclusion Criteria",   "Numbered list."),
              _sub("Exclusion Criteria",   "Numbered list."),
              _sub("Withdrawal Criteria",  "When and how subjects may be withdrawn; data collection after withdrawal.")]),
        _sec("Treatment of Subjects",
             "Treatments to be administered, names of all products, dose, dosage schedule, route, treatment period; permitted/prohibited concomitant medications; compliance monitoring."),
        _sec("Assessment of Efficacy",
             "Specification of efficacy parameters and methods/timing for assessment."),
        _sec("Assessment of Safety",
             "Specification of safety parameters; methods and timing for assessing/recording/analysing safety; AE/SAE reporting requirements; type and duration of follow-up after AEs.",
             [_sub("Adverse Event Reporting",       "Definitions, severity, causality assessment, timelines."),
              _sub("Serious Adverse Event Reporting","Expedited reporting requirements to sponsor and regulators.")]),
        _sec("Statistics",
             "Statistical methods, sample size, level of significance, criteria for trial termination, procedures for missing/spurious data, deviations from plan, selection of subjects in analyses (ITT, PP, safety)."),
        _sec("Direct Access to Source Data / Documents",
             "Investigators/institutions will permit monitoring, audits, IRB review, regulatory inspection."),
        _sec("Quality Control and Quality Assurance",
             "Description of QC/QA procedures."),
        _sec("Ethics",
             "Ethical considerations relating to the trial.", _ETHICS_BLOCK),
        _sec("Data Handling and Record Keeping",
             "CRF design, data management, storage, retention as per regulatory requirements."),
        _sec("Financing and Insurance",
             "If not in a separate agreement.", []),
        _sec("Publication Policy",
             "If not in a separate agreement.", []),
        _sec("Supplements / Appendices",
             "Investigator's brochure, CRFs, ICF, regulatory approvals.", []),
    ],
}

_HORIZON = {
    "id":         "horizon_europe",
    "label":      "Horizon Europe Research Proposal",
    "group":      "International",
    "word_limit": 8000,
    "citation":   "Vancouver",
    "sections": [
        _sec("Excellence",
             "Objectives, ambition and overall methodology — including beyond state-of-the-art, soundness of concept, methodology choices and gender dimension.",
             [_sub("Objectives and Ambition",     "Specific, measurable objectives."),
              _sub("Methodology",                  "Soundness of concept, interdisciplinary approach."),
              _sub("Gender Dimension",             "Integration in research content if applicable.", required=False)]),
        _sec("Impact",
             "Project's pathway to impact; expected outcomes and broader impacts.",
             [_sub("Expected Outcomes and Impacts","Aligned to call destination."),
              _sub("Measures to Maximise Impact",  "Dissemination, exploitation, communication."),
              _sub("Open Science Practices",        "Open access, FAIR data.")]),
        _sec("Implementation",
             "Quality and efficiency of implementation.",
             [_sub("Work Plan and Resources",     "Work packages, deliverables, milestones, Gantt."),
              _sub("Capacity of Participants and Consortium", "Roles and complementarity."),
              _sub("Ethics and Security",           "Self-assessment as per Horizon Europe ethics guidelines.")]),
        _sec("Members of the Consortium",
             "Beneficiaries, affiliated entities and roles."),
        _sec("Ethics Self-Assessment",
             "Mandatory section per Horizon Europe template.", []),
        _sec("Security",
             "If sensitive data or dual-use; otherwise mark N/A.", []),
    ],
}

_WELLCOME = {
    "id":         "wellcome",
    "label":      "Wellcome Trust Research Award",
    "group":      "International",
    "word_limit": 6000,
    "citation":   "Vancouver",
    "sections": [
        _sec("Vision and Aims",         "Big-picture vision plus 3–4 aims."),
        _sec("Research Plan",            "Detailed methodology and approach."),
        _sec("Importance",                "Why this matters scientifically and for health."),
        _sec("Risks and Mitigation",      "Scientific and operational risks."),
        _sec("Outputs and Outcomes",      "Publications, datasets, capacity built, policy impact."),
        _sec("Open Research Practices",   "Pre-registration, open data, open access."),
        _sec("Justification of Resources","Personnel, equipment, travel, consumables."),
        _sec("References",                 "Vancouver style."),
    ],
}

_GATES = {
    "id":         "gates",
    "label":      "Gates Foundation Grant",
    "group":      "International",
    "word_limit": 5000,
    "citation":   "Vancouver",
    "sections": [
        _sec("Project Overview",        "Plain-language description aligned to Gates strategy."),
        _sec("Problem Statement",        "Global-health problem and evidence of need."),
        _sec("Approach",                  "Solution and how it will be tested or deployed."),
        _sec("Equity and Inclusion",      "Reach to underserved populations."),
        _sec("Measurement and Evaluation","Indicators and learning agenda."),
        _sec("Risks and Mitigation",      "Top risks and contingency."),
        _sec("Sustainability and Scale",  "Pathway to scale beyond grant period."),
        _sec("Budget Summary",            "High-level budget."),
        _sec("References",                "Vancouver style."),
    ],
}

_NIHR = {
    "id":         "nihr",
    "label":      "NIHR Research Project (UK)",
    "group":      "International",
    "word_limit": 7000,
    "citation":   "Vancouver",
    "sections": [
        _sec("Plain English Summary",    "≤500 words for lay audience."),
        _sec("Scientific Abstract",       "Structured 300-word abstract."),
        _sec("Background and Rationale",  "NIHR / NHS relevance."),
        _sec("Aims and Objectives",       "Aim plus 3–5 objectives."),
        _sec("Research Plan",
             "Methodology with PPI integration.",
             _M_AND_M_FULL + [_sub("Patient and Public Involvement (PPI)", "Mandatory NIHR section: how patients/public shape the research.")]),
        _sec("Project / Research Timetable", "Gantt chart."),
        _sec("Project Outputs and Dissemination", "Plan including PPI co-production."),
        _sec("Budget",                       "Detailed costing with justification."),
        _sec("References",                    "Vancouver style."),
    ],
}

_NHMRC = {
    "id":         "nhmrc",
    "label":      "NHMRC Investigator / Ideas Grant (AU)",
    "group":      "International",
    "word_limit": 7000,
    "citation":   "Vancouver",
    "sections": [
        _sec("Synopsis",                 "Lay summary."),
        _sec("Significance",              "Importance to Australian and global health."),
        _sec("Innovation and Creativity", "Novelty of approach."),
        _sec("Approach",                   "Methodology and feasibility."),
        _sec("Research Environment",        "Institutional capacity."),
        _sec("Investigator Contributions",  "Track record relative to opportunity."),
        _sec("Translation Pathway",         "Plan for impact."),
        _sec("References",                  "Vancouver style."),
    ],
}

_CIHR = {
    "id":         "cihr",
    "label":      "CIHR Project Grant (Canada)",
    "group":      "International",
    "word_limit": 6000,
    "citation":   "Vancouver",
    "sections": [
        _sec("Summary of Research Proposal", "Plain-language summary."),
        _sec("Specific Aims and Objectives",  "List."),
        _sec("Background and Rationale",       "Including Canadian relevance."),
        _sec("Research Methods",                "Detailed methodology.", _M_AND_M_FULL),
        _sec("Sex- and Gender-Based Analysis", "Mandatory CIHR section: how SGBA is integrated.", []),
        _sec("Knowledge Translation Plan",       "Audience, message, channels."),
        _sec("Timeline",                          "Gantt."),
        _sec("Budget Justification",              "As per CIHR norms."),
        _sec("References",                        "Vancouver style."),
    ],
}


# ---------------------------------------------------------------------------
# Public registry
# ---------------------------------------------------------------------------

TEMPLATES: Dict[str, Dict[str, Any]] = {
    t["id"]: t for t in [
        _ICMR, _IEC, _UGC_MAJOR, _UGC_MINOR, _DST_SERB_CRG, _DST_SERB_ECR,
        _PHD_SYNOPSIS, _AYUSH, _CTRI, _DBT, _CSIR,
        _NIH_R01, _WHO, _ICH_GCP, _HORIZON, _WELLCOME, _GATES, _NIHR, _NHMRC, _CIHR,
    ]
}


def get_template(format_id: str) -> Optional[Dict[str, Any]]:
    return TEMPLATES.get((format_id or "").strip().lower())


def list_templates() -> List[Dict[str, Any]]:
    return [
        {"id": t["id"], "label": t["label"], "group": t["group"],
         "word_limit": t["word_limit"], "citation": t["citation"],
         "sections": [s["name"] for s in t["sections"]]}
        for t in TEMPLATES.values()
    ]


def section_subsections(format_id: str, section_name: str) -> List[Dict[str, Any]]:
    tpl = get_template(format_id)
    if not tpl: return []
    name_lower = (section_name or "").strip().lower()
    for s in tpl["sections"]:
        if s["name"].lower() == name_lower:
            return s.get("subsections", []) or []
    return []
