"""Trusted, permanent guidelines bundled with MedRAS.

These are stable academic / regulatory standards that do not need to be
fetched from the live web. Including them as static text keeps prompts
deterministic, reproducible, and offline-capable.

Public surface
--------------
* ``TRUSTED_GUIDELINES`` — nested dict {domain: {guideline_id: {title, summary}}}
* ``get_guidelines_for_domain(domain, task=None)`` -> str
        Returns a single newline-joined block of guideline text suitable
        for splicing into an LLM system prompt. ``task`` (optional) is a
        short hint such as "proposal_writing", "study_design",
        "statistical_analysis" or "plagiarism_reduction"; when given, the
        function ALSO appends the matching cross-cutting bundle.

Each guideline summary is intentionally short (≤350 words) — long enough
to give an LLM the structure it needs, short enough to fit alongside the
user's actual content in a typical 32k-token prompt window.
"""

from __future__ import annotations

from typing import Optional

# ---------------------------------------------------------------------------
# medical_clinical — core ethical and reporting standards
# ---------------------------------------------------------------------------

_MEDICAL = {
    "icmr_2017": {
        "title": "ICMR National Ethical Guidelines for Biomedical and Health Research Involving Human Participants (2017)",
        "summary": (
            "Mandatory framework for any biomedical or health research involving human "
            "participants in India. Core requirements:\n"
            "1. Independent IEC review and approval BEFORE recruitment begins; protocol "
            "   amendments must be re-approved.\n"
            "2. Voluntary, written informed consent in a language and format the "
            "   participant fully understands. Use re-consent for protocol changes that "
            "   affect risk-benefit. For illiterate participants: read aloud + thumb "
            "   impression + impartial witness signature.\n"
            "3. Special protections for vulnerable populations — children (require "
            "   parental consent + age-appropriate assent ≥7y), pregnant women, "
            "   prisoners, terminally ill, mentally ill, economically/socially "
            "   disadvantaged groups. Justify their inclusion.\n"
            "4. Privacy and confidentiality: code-link identifiers, restrict access, "
            "   secure storage for ≥3 years post-publication (longer for clinical "
            "   trials per CDSCO).\n"
            "5. Risk minimisation and benefit maximisation; risks must be reasonable "
            "   relative to anticipated benefits.\n"
            "6. Compensation for research-related injury; reimbursement (not "
            "   inducement) for time and travel.\n"
            "7. Conflict-of-interest declaration by all investigators.\n"
            "8. Trial registration (CTRI) BEFORE first participant enrolment.\n"
            "9. Data and Safety Monitoring Board for trials with significant risk.\n"
            "10. Plagiarism, fabrication and falsification are research misconduct."
        ),
    },
    "helsinki_2013": {
        "title": "Declaration of Helsinki (WMA, 2013 revision)",
        "summary": (
            "Foundational ethical principles for medical research involving human "
            "subjects:\n"
            "• Well-being of the individual research subject takes precedence over all "
            "  other interests.\n"
            "• Research must conform to generally accepted scientific principles, be "
            "  based on a thorough knowledge of the literature, and adequate laboratory "
            "  and, where appropriate, animal experimentation.\n"
            "• Protocols must describe ethical considerations and indicate compliance "
            "  with this Declaration; submitted to a research ethics committee for "
            "  consideration, comment, guidance and approval before study begins.\n"
            "• Vulnerable groups should receive specifically considered protection.\n"
            "• Voluntary informed consent, preferably in writing, after full disclosure "
            "  of aims, methods, sources of funding, conflicts, institutional "
            "  affiliations, anticipated benefits, potential risks, and right to "
            "  abstain or withdraw.\n"
            "• Use of placebo only when no proven intervention exists or for "
            "  compelling methodologic reasons; subjects must not be subject to "
            "  serious or irreversible harm.\n"
            "• Post-trial provisions: identify post-trial access to interventions in "
            "  the protocol.\n"
            "• Mandatory registration of every clinical trial in a publicly accessible "
            "  database before first subject recruitment.\n"
            "• Researchers, authors, sponsors, editors and publishers all have ethical "
            "  obligations regarding publication and dissemination of results — "
            "  including negative and inconclusive results."
        ),
    },
    "consort_2010": {
        "title": "CONSORT 2010 — Reporting of Randomised Controlled Trials",
        "summary": (
            "25-item checklist + flow diagram required for transparent RCT reporting. "
            "Critical items:\n"
            "Title & abstract: identify as RCT; structured abstract.\n"
            "Introduction: scientific background, rationale, specific objectives & "
            "hypotheses.\n"
            "Methods: trial design (parallel/factorial/cluster/cross-over), changes "
            "after commencement; eligibility criteria for participants; settings & "
            "locations; interventions for each group with sufficient detail to "
            "replicate; pre-specified primary and secondary outcomes; sample size "
            "calculation including assumptions; method used to generate the random "
            "allocation sequence; type of randomisation (blocking, stratification); "
            "allocation concealment mechanism; who generated/enrolled/assigned; "
            "blinding (who was blinded — participants, providers, outcome assessors); "
            "statistical methods including methods for additional analyses (subgroup, "
            "adjusted).\n"
            "Results: participant flow diagram (enrolled, allocated, followed up, "
            "analysed, with reasons for exclusion at each stage); recruitment dates "
            "and follow-up; baseline demographics by group; numbers analysed in each "
            "group (ITT vs PP); estimated effect size, precision (95% CI), p-values "
            "for primary and secondary outcomes; harms and unintended effects.\n"
            "Discussion: limitations; generalisability; interpretation balanced with "
            "evidence.\n"
            "Other: registration number; protocol availability; funding source and "
            "role of funder."
        ),
    },
    "strobe": {
        "title": "STROBE — Strengthening the Reporting of Observational Studies in Epidemiology",
        "summary": (
            "22-item checklist for cohort, case-control and cross-sectional studies. "
            "Mandatory elements:\n"
            "• State the study design with a commonly used term in the title or "
            "  abstract.\n"
            "• Background: scientific rationale; specific objectives including any "
            "  pre-specified hypotheses.\n"
            "• Methods: setting, locations, relevant dates (recruitment, exposure, "
            "  follow-up, data collection); eligibility criteria; sources and methods "
            "  of selection of participants; for matched studies, give matching "
            "  criteria and number of exposed/unexposed; for case-control, give "
            "  matching criteria and number of controls per case; clearly define ALL "
            "  outcomes, exposures, predictors, potential confounders and effect "
            "  modifiers; data sources / measurement; describe efforts to address "
            "  potential sources of bias; explain how quantitative variables were "
            "  handled; statistical methods including handling of missing data and "
            "  any sensitivity analyses; how loss to follow-up was addressed.\n"
            "• Results: numbers at each stage of study (eligible → examined → "
            "  confirmed eligible → included → completing follow-up → analysed); "
            "  unadjusted estimates and, if applicable, confounder-adjusted estimates "
            "  with 95% CIs; report category boundaries when continuous variables "
            "  were categorised; if relevant, translate estimates of relative risk "
            "  into absolute risk for a meaningful time period.\n"
            "• Discussion: key results; limitations including potential bias and "
            "  imprecision; generalisability; funding source."
        ),
    },
    "prisma_2020": {
        "title": "PRISMA 2020 — Preferred Reporting Items for Systematic Reviews and Meta-Analyses",
        "summary": (
            "27-item checklist + flow diagram. Mandatory items:\n"
            "Title: identify as a systematic review.\n"
            "Abstract: structured summary including objectives, eligibility criteria, "
            "information sources, risk-of-bias assessment, synthesis method, "
            "results, limitations, registration.\n"
            "Methods: protocol registration (PROSPERO ID where available); "
            "eligibility criteria using PICOS; information sources searched with "
            "dates; full search strategy for at least one database; selection "
            "process (independent reviewers, deduplication); data collection "
            "process; data items collected; risk-of-bias assessment per study using "
            "an appropriate tool (RoB 2 for RCTs, ROBINS-I for non-randomised); "
            "synthesis methods (meta-analysis vs narrative); summary measures "
            "(RR, OR, MD, SMD); methods for exploring heterogeneity (I², τ², "
            "subgroup, meta-regression); methods for assessing reporting biases "
            "(funnel plot, Egger test); certainty assessment (GRADE).\n"
            "Results: study selection flow diagram with counts at each stage with "
            "reasons for exclusion; characteristics of included studies; "
            "risk-of-bias results; results of individual studies and syntheses; "
            "reporting bias and certainty of evidence.\n"
            "Discussion: interpretation in context of other evidence; limitations "
            "of the evidence and of the review process; implications.\n"
            "Other: registration; protocol; support; conflicts of interest; data "
            "availability."
        ),
    },
    "spirit_2013": {
        "title": "SPIRIT 2013 — Standard Protocol Items for Clinical Trial Protocols",
        "summary": (
            "33-item checklist for clinical trial protocols. Required content:\n"
            "Administrative: title; trial registration; protocol version; funding; "
            "roles & responsibilities; sponsor & PI contacts.\n"
            "Introduction: background and rationale; objectives with PICO; trial "
            "design (parallel, crossover, factorial, single-arm; allocation ratio; "
            "framework — superiority, equivalence, non-inferiority, exploratory).\n"
            "Methods — Participants, interventions, outcomes: study setting; "
            "eligibility criteria; interventions with sufficient detail to allow "
            "replication, including how/when administered, modifications, "
            "adherence, concomitant care; primary, secondary and other outcomes "
            "with measurement metric, method of aggregation and time point; "
            "participant timeline (schematic); sample size calculation; "
            "recruitment strategies.\n"
            "Methods — Assignment of interventions: allocation sequence generation "
            "and concealment; implementation; blinding (who, how, emergency "
            "unblinding procedures).\n"
            "Methods — Data collection, management, analysis: data collection "
            "methods and instruments; data management and quality; statistical "
            "methods for primary and secondary outcomes, additional analyses, and "
            "missing data.\n"
            "Methods — Monitoring: data monitoring committee; interim analyses and "
            "stopping guidelines; auditing.\n"
            "Ethics & dissemination: research ethics approval; protocol "
            "amendments; consent; confidentiality; declarations of interest; "
            "access to data; ancillary care; dissemination policy."
        ),
    },
    "ich_gcp_e6_r2": {
        "title": "ICH-GCP E6(R2) — Good Clinical Practice",
        "summary": (
            "International quality standard for designing, conducting, recording "
            "and reporting clinical trials involving human subjects. Pillars:\n"
            "1. Trials should be conducted in accordance with the ethical principles "
            "   that have their origin in the Declaration of Helsinki, and that are "
            "   consistent with GCP and applicable regulatory requirements.\n"
            "2. Foreseeable risks and inconveniences should be weighed against the "
            "   anticipated benefit. Trial should be initiated and continued only if "
            "   benefits justify risks.\n"
            "3. Rights, safety and well-being of trial subjects are paramount and "
            "   prevail over interests of science and society.\n"
            "4. Available non-clinical and clinical information on an investigational "
            "   product should be adequate to support the proposed trial.\n"
            "5. Trials should be scientifically sound and described in a clear, "
            "   detailed protocol.\n"
            "6. A trial should be conducted in compliance with the protocol that has "
            "   received prior IEC/IRB approval/favourable opinion.\n"
            "7. Medical decisions and care should always be the responsibility of a "
            "   qualified physician.\n"
            "8. Each individual involved in conducting a trial should be qualified "
            "   by education, training and experience.\n"
            "9. Freely-given informed consent obtained from every subject prior to "
            "   clinical-trial participation.\n"
            "10. All clinical-trial information should be recorded, handled and "
            "    stored in a way that allows accurate reporting, interpretation and "
            "    verification — ALCOA-C principle (attributable, legible, "
            "    contemporaneous, original, accurate, complete).\n"
            "11. Confidentiality of records protected per regulatory requirements.\n"
            "12. Investigational products manufactured per applicable GMP and used "
            "    per approved protocol.\n"
            "13. Systems with procedures that assure the quality of every aspect of "
            "    the trial. Risk-based quality management (R2 addition)."
        ),
    },
    "cpcsea": {
        "title": "CPCSEA — Committee for the Purpose of Control and Supervision of Experiments on Animals (India)",
        "summary": (
            "Statutory body under the Ministry of Environment, Forest and Climate "
            "Change governing animal experimentation in India. Compliance "
            "requirements:\n"
            "• All institutions using animals for experimentation must register with "
            "  CPCSEA and constitute an Institutional Animal Ethics Committee (IAEC).\n"
            "• Every project must obtain IAEC approval BEFORE procurement of "
            "  animals; protocol must justify species, strain, age, sex and number of "
            "  animals using the 3Rs (Replacement, Reduction, Refinement).\n"
            "• Sample size justification using statistical methods (e.g. resource "
            "  equation, power analysis); avoid underpowered studies that waste "
            "  animals.\n"
            "• Housing per CPCSEA standards: cage size, temperature 22±3°C, "
            "  humidity 30-70%, 12-h light cycle, food and water ad libitum unless "
            "  protocol specifies otherwise.\n"
            "• Anaesthesia and analgesia: appropriate to species and procedure; pain "
            "  must be minimised; humane endpoints defined a priori.\n"
            "• Personnel handling animals must be trained; veterinarian oversight "
            "  required.\n"
            "• Euthanasia by approved methods only (CO₂, overdose of anaesthetic, "
            "  cervical dislocation under anaesthesia); confirm death.\n"
            "• Form B is the standard project application; Form D is the annual "
            "  report; Form M for breeders.\n"
            "• Records of all procurement, breeding, experimentation and disposal "
            "  must be maintained for at least 3 years."
        ),
    },
}

# ---------------------------------------------------------------------------
# statistics — test selection, assumptions, effect sizes
# ---------------------------------------------------------------------------

_STATISTICS = {
    "test_selection": {
        "title": "Statistical Test Selection — Decision Framework",
        "summary": (
            "Choose the test that matches the data, NOT the other way round.\n\n"
            "STEP 1 — Outcome variable type:\n"
            "  Continuous (height, BP, score)        → t-test / ANOVA / regression family\n"
            "  Ordinal (Likert, stage)               → non-parametric or ordinal regression\n"
            "  Binary (yes/no, dead/alive)           → chi-square, Fisher, logistic regression\n"
            "  Categorical >2 (ABO, ethnicity)        → chi-square, multinomial logistic\n"
            "  Time-to-event (survival)               → Kaplan-Meier, log-rank, Cox regression\n"
            "  Count (admissions/year)                → Poisson, negative binomial\n\n"
            "STEP 2 — Number of groups & pairing:\n"
            "  1 sample vs known value      → one-sample t / Wilcoxon signed rank\n"
            "  2 independent groups          → independent t / Mann-Whitney U / chi-square\n"
            "  2 paired/matched groups       → paired t / Wilcoxon signed rank / McNemar\n"
            "  ≥3 independent groups         → one-way ANOVA + Tukey / Kruskal-Wallis + Dunn\n"
            "  ≥3 repeated/related groups    → repeated-measures ANOVA / Friedman\n"
            "  Two-factor design             → two-way ANOVA / aligned-rank\n\n"
            "STEP 3 — Parametric vs non-parametric:\n"
            "  Parametric requires: approximate normality of residuals, homogeneity "
            "  of variance, independence of observations, reasonable sample size "
            "  (n≥30 per group invokes CLT for means).\n"
            "  If assumptions violated AND n is small → use non-parametric equivalent.\n"
            "  If n is large → parametric is generally robust; report both as a "
            "  sensitivity analysis if doubtful.\n\n"
            "STEP 4 — Adjustment & confounders:\n"
            "  If you need to adjust for covariates or quantify an effect, prefer a "
            "  regression model (linear, logistic, Cox, mixed) over a simple test."
        ),
    },
    "assumption_checklists": {
        "title": "Assumption Checklists for Major Tests",
        "summary": (
            "INDEPENDENT t-TEST:\n"
            "  • Outcome continuous; groups independent.\n"
            "  • Approx normality of outcome in each group (Shapiro-Wilk; or visual "
            "    check via Q-Q plot if n>50).\n"
            "  • Equal variances (Levene's test). If violated → Welch's t-test.\n"
            "  • No major outliers — investigate; sensitivity analysis with/without.\n\n"
            "PAIRED t-TEST:\n"
            "  • Pairs naturally matched (before/after, twin pairs).\n"
            "  • Differences (post-pre) are approximately normally distributed.\n\n"
            "ONE-WAY ANOVA:\n"
            "  • Independence; normality within each group; homogeneity of variance "
            "    (Levene). If unequal variances → Welch ANOVA + Games-Howell post-hoc.\n"
            "  • Always pair with a planned post-hoc (Tukey HSD for equal n, "
            "    Bonferroni for any contrasts).\n\n"
            "CHI-SQUARE TEST OF INDEPENDENCE:\n"
            "  • All expected cell frequencies ≥5 (for 2×2: 80% of cells ≥5 and "
            "    none <1). If violated → Fisher's exact test.\n"
            "  • Independence of observations (one observation per subject).\n\n"
            "PEARSON CORRELATION:\n"
            "  • Both variables continuous and approximately normal.\n"
            "  • Linear relationship (visual scatter plot first).\n"
            "  • No major outliers. Otherwise → Spearman rank correlation.\n\n"
            "LINEAR REGRESSION:\n"
            "  • Linearity, independence of residuals (Durbin-Watson ≈2), normality "
            "    of residuals, homoscedasticity (residual vs fitted plot), no "
            "    multicollinearity (VIF<5), no influential outliers (Cook's distance).\n\n"
            "LOGISTIC REGRESSION:\n"
            "  • Binary outcome; independent observations; linearity in the logit "
            "    for continuous predictors (Box-Tidwell); ≥10 events per predictor; "
            "    no extreme multicollinearity; no separation."
        ),
    },
    "effect_size_benchmarks": {
        "title": "Effect Size Interpretation Benchmarks",
        "summary": (
            "Always report effect sizes alongside p-values. Cohen's conventional "
            "benchmarks (treat as guidance, not gospel; field-specific norms vary):\n\n"
            "COHEN'S d (mean difference / pooled SD):\n"
            "  0.2 = small | 0.5 = medium | 0.8 = large | ≥1.2 = very large\n\n"
            "ETA-SQUARED (η²) and PARTIAL η² for ANOVA:\n"
            "  0.01 = small | 0.06 = medium | 0.14 = large\n\n"
            "OMEGA-SQUARED (ω²) — less biased alternative to η²:\n"
            "  0.01 = small | 0.06 = medium | 0.14 = large\n\n"
            "CRAMÉR'S V for chi-square (function of df):\n"
            "  df=1: 0.10/0.30/0.50  | df=2: 0.07/0.21/0.35 | df=3: 0.06/0.17/0.29 "
            "  (small / medium / large)\n\n"
            "ODDS RATIO (logistic regression, case-control):\n"
            "  1.5 = small | 2.5 = medium | 4.0 = large (Chen et al., 2010, "
            "  for outcome prevalence ~10%).\n\n"
            "RISK RATIO / RELATIVE RISK:\n"
            "  Interpret in absolute terms — convert to NNT/NNH for clinical "
            "  meaning: NNT = 1 / absolute risk reduction.\n\n"
            "PEARSON r:\n"
            "  0.10 = small | 0.30 = medium | 0.50 = large (Cohen 1988).\n\n"
            "ALWAYS REPORT: effect size + 95% confidence interval, not just p<0.05."
        ),
    },
}

# ---------------------------------------------------------------------------
# proposal_writing — section structures for major formats
# ---------------------------------------------------------------------------

_PROPOSAL = {
    "icmr_sections": {
        "title": "ICMR Project Proposal — Required Sections",
        "summary": (
            "1. Title (≤25 words; PICO + design).\n"
            "2. Investigators & Affiliations (PI, Co-PI, collaborators with roles).\n"
            "3. Summary / Abstract (250-300 words structured).\n"
            "4. Introduction & Background — magnitude in India + global, current "
            "   evidence, gaps, rationale.\n"
            "5. Hypothesis (single, testable, directional).\n"
            "6. Aims & Objectives — primary aim + 2-4 specific measurable objectives.\n"
            "7. Review of Literature (1500-2000 words; cite Indian work).\n"
            "8. Materials and Methods — study design + setting + period + population "
            "   + inclusion + exclusion + sample size with calculation + sampling "
            "   technique + data collection procedure + variables & operational "
            "   definitions + statistical analysis plan + quality assurance.\n"
            "9. Ethical Considerations — IEC approval, consent, confidentiality, "
            "   risks-benefits, conflict of interest. MANDATORY for ICMR.\n"
            "10. Work Plan & Timeline (Gantt or month-wise table).\n"
            "11. Expected Outcome & Implications (public-health relevance, "
            "    translational pathway).\n"
            "12. Budget Justification — year-wise: manpower, consumables, "
            "    equipment, travel, contingency.\n"
            "13. References (Vancouver style).\n"
            "14. Appendices (CRFs, questionnaires, consent forms, CVs)."
        ),
    },
    "iec_sections": {
        "title": "IEC / Ethics Committee Submission — Required Sections",
        "summary": (
            "1. Title and protocol number (version-controlled).\n"
            "2. Investigators with qualifications and contact info.\n"
            "3. Lay summary (≤300 words for non-clinical members).\n"
            "4. Background and rationale.\n"
            "5. Objectives (primary + secondary).\n"
            "6. Study design and methods — design, sample size, study procedures.\n"
            "7. Risk-benefit assessment (risks, benefits, mitigation).\n"
            "8. Informed consent process — English + local language(s); special "
            "   populations (minors, pregnant women, illiterate, unconscious).\n"
            "9. Confidentiality and data protection.\n"
            "10. Compensation (travel reimbursement + research-injury cover).\n"
            "11. Conflict of interest declaration.\n"
            "12. Publication policy.\n"
            "13. Trial registration plan (CTRI / clinicaltrials.gov).\n"
            "14. References and annexures (protocol, CRF, ICF, CVs)."
        ),
    },
    "ugc_major_sections": {
        "title": "UGC Major Research Project — Required Sections",
        "summary": (
            "1. Title of the project.\n"
            "2. Principal Investigator & Institution.\n"
            "3. Introduction — origin of problem, interdisciplinary relevance, "
            "   review of R&D status (national + international).\n"
            "4. Objectives — specific & measurable.\n"
            "5. Methodology — approach & hypothesis, methods & materials, "
            "   sampling/field-work, data analysis plan.\n"
            "6. Year-wise plan of work.\n"
            "7. Expected output and outcomes (publications, patents, books).\n"
            "8. Budget — year-wise: books & journals, equipment, contingency, "
            "   field work/travel, hiring services, honorarium, project fellow.\n"
            "9. Bibliographic references (APA)."
        ),
    },
    "dst_serb_sections": {
        "title": "DST-SERB Core Research Grant (CRG) — Required Sections",
        "summary": (
            "1. Project title.\n"
            "2. Investigators (PI, Co-PIs, mentor if applicable).\n"
            "3. Project summary (structured 500 words).\n"
            "4. Project details — origin of proposal, definition of problem, "
            "   objectives, hypothesis, methodology, time schedule, expected "
            "   outcome, plan for utilisation of research outcome.\n"
            "5. National & international status — what's done, gaps your work "
            "   addresses.\n"
            "6. Preliminary work done — pilot data, prior team publications.\n"
            "7. Infrastructure available.\n"
            "8. Budget — year-wise: manpower, consumables, equipment, travel, "
            "   contingency, overhead.\n"
            "9. Bio-data of investigators (last 5 years).\n"
            "10. References (Vancouver)."
        ),
    },
    "nih_r01_sections": {
        "title": "NIH R01 — Required Sections",
        "summary": (
            "1. Project Summary / Abstract (≈30 lines / 400 words).\n"
            "2. Project Narrative (2-3 sentences; lay relevance).\n"
            "3. Specific Aims (EXACTLY 1 page; 2-4 aims; impact statement).\n"
            "4. Research Strategy (12 pages) — Significance, Innovation, Approach. "
            "   Approach must include for each Aim: rationale, design, expected "
            "   outcomes, pitfalls and alternatives, statistical plan, rigor & "
            "   reproducibility.\n"
            "5. Bibliography & References Cited (AMA style; no page limit).\n"
            "6. Protection of Human Subjects (when applicable) — risks, adequacy "
            "   of protection, benefits, importance of knowledge.\n"
            "7. Inclusion of Women, Minorities and Children — justification + "
            "   recruitment plan.\n"
            "8. Vertebrate Animals (if applicable).\n"
            "9. Resource Sharing Plan.\n"
            "10. Authentication of Key Biological/Chemical Resources (≤1 page).\n"
            "11. Facilities and Other Resources.\n"
            "12. Equipment.\n"
            "13. Biographical Sketch (NIH 5-page format per Sr/Key person).\n"
            "14. Budget and Budget Justification (R&R; year-wise)."
        ),
    },
    "who_sections": {
        "title": "WHO Research Proposal — Required Sections",
        "summary": (
            "1. Title.\n"
            "2. Principal Investigator and Team (note WHO collaborating-centre "
            "   affiliation if any).\n"
            "3. Abstract (structured, ≤250 words).\n"
            "4. Background — global/regional health relevance + alignment with WHO "
            "   priorities (e.g. SDG 3, GPW13).\n"
            "5. Justification — why this study, why now, public-health value.\n"
            "6. Goal and objectives (programmatic goal + specific objectives).\n"
            "7. Methodology — standard methods PLUS capacity-building component "
            "   for LMIC partners.\n"
            "8. Ethical considerations — WHO-ERC + local IEC approval.\n"
            "9. Dissemination plan — policy briefs, peer-reviewed publications, "
            "   WHO reports.\n"
            "10. Work plan and timeline (Gantt).\n"
            "11. Budget — in USD, with currency conversion noted.\n"
            "12. References (Vancouver)."
        ),
    },
}

# ---------------------------------------------------------------------------
# study_design — choosing the right design + sample-size considerations + bias
# ---------------------------------------------------------------------------

_STUDY_DESIGN = {
    "design_choice": {
        "title": "Choosing a Study Design",
        "summary": (
            "RANDOMISED CONTROLLED TRIAL (RCT)\n"
            "  Use when: testing causal effect of an intervention, equipoise exists, "
            "  ethical to randomise, intervention can be standardised.\n"
            "  Strength: highest level of causal inference; minimises confounding "
            "  via randomisation.\n"
            "  Don't use when: intervention is harmful, randomisation is unethical "
            "  (e.g. smoking causes cancer), rare outcomes, very long follow-up "
            "  needed.\n\n"
            "COHORT STUDY (prospective preferred)\n"
            "  Use when: studying multiple outcomes from a common exposure; "
            "  estimating incidence; rare exposures; temporal relationship needed.\n"
            "  Strength: temporality clear, multiple outcomes, can compute incidence "
            "  rate ratios.\n"
            "  Limitation: expensive, long, loss to follow-up, not for rare outcomes.\n\n"
            "CASE-CONTROL STUDY\n"
            "  Use when: rare outcome, multiple exposures of interest, quick & "
            "  cheap exploration.\n"
            "  Strength: efficient for rare diseases, multiple exposures examined.\n"
            "  Limitation: recall bias, selection bias for controls, cannot compute "
            "  incidence directly (use OR as estimate of RR for rare outcomes).\n\n"
            "CROSS-SECTIONAL STUDY\n"
            "  Use when: estimating prevalence, surveying KAP, hypothesis-generation.\n"
            "  Strength: quick, cheap, no follow-up.\n"
            "  Limitation: cannot establish temporality; cannot estimate incidence; "
            "  prone to non-response bias.\n\n"
            "SYSTEMATIC REVIEW & META-ANALYSIS\n"
            "  Use when: synthesising existing evidence, resolving conflicting studies.\n"
            "  Strength: highest level in evidence pyramid for that question.\n"
            "  Requires: pre-registered protocol (PROSPERO), comprehensive search, "
            "  ≥2 independent reviewers for screening + data extraction, "
            "  risk-of-bias assessment, GRADE certainty.\n\n"
            "QUALITATIVE STUDY\n"
            "  Use when: understanding experiences, perceptions, mechanisms; "
            "  hypothesis generation for complex social phenomena.\n"
            "  Strength: rich contextual understanding.\n"
            "  Reporting standard: COREQ or SRQR."
        ),
    },
    "sample_size": {
        "title": "Sample Size Considerations by Design",
        "summary": (
            "RCT (two-arm parallel, continuous primary outcome):\n"
            "  n/group = 2·((Zα/2 + Zβ)·SD / Δ)²; commonly Zα/2=1.96, Zβ=0.84 "
            "  (80% power, two-sided 5%). Inflate by attrition rate (e.g. ÷0.85 "
            "  for 15% loss).\n\n"
            "RCT (binary outcome):\n"
            "  Use formulas based on p1, p2, with continuity correction; or use "
            "  R `pwr::pwr.2p.test` / G*Power. Always justify the clinically "
            "  meaningful difference (MCID).\n\n"
            "COHORT (binary outcome, exposed vs unexposed):\n"
            "  Plan for the smaller group; n per group depends on relative risk "
            "  to detect, baseline incidence, follow-up duration.\n\n"
            "CASE-CONTROL:\n"
            "  Number of cases drives precision. Typical: 1-4 controls per case "
            "  (matched on age, sex, source). OR detectable depends on exposure "
            "  prevalence in controls.\n\n"
            "CROSS-SECTIONAL (prevalence estimation):\n"
            "  n = Z²·p·(1-p) / d², where p is expected prevalence and d is "
            "  desired absolute precision (e.g. ±5%). Adjust for finite "
            "  population if N small. Add design effect (~1.5-2) for cluster "
            "  sampling.\n\n"
            "DIAGNOSTIC ACCURACY:\n"
            "  Power for sensitivity AND specificity separately; n_disease and "
            "  n_no-disease set independently. Use disease prevalence in target "
            "  population.\n\n"
            "QUALITATIVE:\n"
            "  Aim for thematic saturation. Typical 12-20 in-depth interviews, "
            "  4-6 focus groups; justify in protocol; revisit during fieldwork.\n\n"
            "ALWAYS REPORT: assumptions, formula/tool used, expected attrition, "
            "  final inflated n. Cite a software (G*Power, R `pwr`, OpenEpi, "
            "  PASS) so reviewers can reproduce."
        ),
    },
    "bias_risks": {
        "title": "Bias Risks per Design and How to Address Them",
        "summary": (
            "RCT — RISKS & FIXES:\n"
            "  • Selection bias → centralised randomisation + allocation "
            "    concealment (sequentially numbered opaque sealed envelopes or "
            "    web-based).\n"
            "  • Performance bias → blinding of participants & providers (or "
            "    sham/placebo control where ethical).\n"
            "  • Detection bias → blind outcome assessors; adjudication "
            "    committee for subjective endpoints.\n"
            "  • Attrition bias → ITT analysis; multiple imputation for missing "
            "    data; report withdrawals with reasons.\n"
            "  • Reporting bias → register protocol pre-trial; pre-specify "
            "    primary outcome.\n\n"
            "COHORT — RISKS & FIXES:\n"
            "  • Selection bias → define eligible population clearly; enrol "
            "    consecutively or randomly; report participation rate.\n"
            "  • Confounding → measure all known confounders + adjust in "
            "    multivariable model; consider propensity-score matching.\n"
            "  • Loss to follow-up → minimise via active tracing; sensitivity "
            "    analysis assuming worst case for those lost.\n"
            "  • Information bias → standardise data collection; train "
            "    assessors; use validated instruments.\n\n"
            "CASE-CONTROL — RISKS & FIXES:\n"
            "  • Selection bias for controls → controls should arise from the "
            "    same source population that gave rise to the cases; consider "
            "    multiple control groups for sensitivity.\n"
            "  • Recall bias → use medical records / registries where possible; "
            "    structured interviews; blind interviewers to case/control "
            "    status.\n"
            "  • Berkson's bias (hospital controls) → use community controls "
            "    when feasible.\n\n"
            "CROSS-SECTIONAL — RISKS & FIXES:\n"
            "  • Non-response bias → maximise response (reminders, incentives); "
            "    compare responders vs non-responders on available variables.\n"
            "  • Sampling bias → use probability sampling (simple random, "
            "    stratified, multi-stage cluster) over convenience sampling.\n"
            "  • Reverse causation → cannot fix in the design; explicitly "
            "    acknowledge in limitations.\n\n"
            "SYSTEMATIC REVIEW — RISKS & FIXES:\n"
            "  • Publication bias → search grey literature, conference "
            "    abstracts, trial registries; funnel plot + Egger test if "
            "    ≥10 studies.\n"
            "  • Selection bias in review → ≥2 independent reviewers; report "
            "    inter-rater agreement (κ).\n"
            "  • Risk of bias in primary studies → use RoB 2 (RCTs) or "
            "    ROBINS-I (non-randomised); reflect in GRADE certainty."
        ),
    },
}

# ---------------------------------------------------------------------------
# Public registry
# ---------------------------------------------------------------------------

TRUSTED_GUIDELINES: dict[str, dict[str, dict[str, str]]] = {
    "medical_clinical": _MEDICAL,
    "statistics":       _STATISTICS,
    "proposal_writing": _PROPOSAL,
    "study_design":     _STUDY_DESIGN,
}

# Cross-cutting tags: which guideline bundles to include for a given task.
_TASK_BUNDLES: dict[str, tuple[str, ...]] = {
    "proposal_writing":     ("proposal_writing", "study_design", "statistics"),
    "study_design":         ("study_design", "statistics", "medical_clinical"),
    "statistical_analysis": ("statistics",),
    "plagiarism_reduction": (),  # trusted guidelines aren't relevant here
    "thesis_writing":       ("proposal_writing", "study_design", "statistics"),
}


def _render_bundle(bundle: dict[str, dict[str, str]]) -> str:
    parts: list[str] = []
    for gid, item in bundle.items():
        parts.append(f"### {item['title']}\n{item['summary'].rstrip()}")
    return "\n\n".join(parts)


def get_guidelines_for_domain(domain: str, task: Optional[str] = None) -> str:
    """Return a single text block with guidelines for the given domain (and
    optionally a cross-cutting task such as ``"proposal_writing"``).

    The output is meant to be spliced directly into an LLM system prompt.
    Returns an empty string if no guidelines apply.
    """
    chunks: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        if name in seen: return
        bundle = TRUSTED_GUIDELINES.get(name)
        if not bundle: return
        chunks.append(f"## Trusted standards: {name.replace('_', ' ').title()}\n\n"
                      + _render_bundle(bundle))
        seen.add(name)

    dom = (domain or "").strip().lower()
    if dom in TRUSTED_GUIDELINES:
        _add(dom)

    for extra in _TASK_BUNDLES.get((task or "").strip().lower(), ()):
        _add(extra)

    return "\n\n".join(chunks)
