/* ============================================================
   Proposal Writing Module — Step 3: Format selection + preview
   ============================================================ */
(function () {
  "use strict";

  var STORAGE_KEY = "medras.proposal.intake";

  // ===================== Format catalog =====================
  // Each entry: id, label, group, country, fundingBody, wordLimit, citation,
  // description, sections[]
  var FORMATS = [
    // ---------- Indian formats ----------
    {
      id: "icmr", label: "ICMR — Indian Council of Medical Research", group: "indian",
      country: "India", fundingBody: "Indian Council of Medical Research (ICMR)",
      wordLimit: "5,000–8,000 words", citation: "Vancouver",
      description: "Extramural research grant from India's apex biomedical research agency. Use for medical, public-health, epidemiology and laboratory studies needing ICMR funding.",
      sections: ["Title", "Summary / Abstract", "Background & Rationale", "Review of Literature", "Research Question", "Aims & Objectives", "Hypothesis", "Methodology", "Sample Size & Statistical Analysis", "Ethical Considerations", "Work Plan & Timeline", "Budget", "References", "Investigator Bio-data", "Facilities Available"]
    },
    {
      id: "icmr-tf", label: "ICMR Task Force Project", group: "indian",
      country: "India", fundingBody: "ICMR Task Force",
      wordLimit: "8,000–12,000 words", citation: "Vancouver",
      description: "Multi-centre, mission-mode ICMR project — typically nationally networked studies on priority health themes.",
      sections: ["Title", "Executive Summary", "National Health Priority & Justification", "Background & Literature Review", "Aims & Specific Objectives", "Hypotheses", "Multicentric Study Design", "Participating Centres", "Methodology", "Quality Assurance & Monitoring", "Statistical Analysis Plan", "Data Management Plan", "Ethical Considerations", "Timeline & Milestones", "Budget (per centre)", "Coordinating PI Bio-data", "References"]
    },
    {
      id: "iec-human", label: "IEC — Human Studies (Institutional Ethics)", group: "indian",
      country: "India", fundingBody: "Institutional Ethics Committee",
      wordLimit: "3,000–5,000 words", citation: "Vancouver",
      description: "Ethics committee submission for human-subject research per ICMR National Ethical Guidelines (2017) and New Drugs & Clinical Trials Rules.",
      sections: ["Title", "Type of Study", "Background & Rationale", "Objectives", "Methodology", "Inclusion & Exclusion Criteria", "Sample Size", "Risks & Benefits to Participants", "Informed Consent Process", "Confidentiality & Data Protection", "Conflict of Interest", "Compensation for Injury", "Investigator CVs", "Participant Information Sheet", "Informed Consent Form", "References"]
    },
    {
      id: "iec-animal", label: "IEC — Animal Studies (CPCSEA / IAEC)", group: "indian",
      country: "India", fundingBody: "Institutional Animal Ethics Committee",
      wordLimit: "2,500–4,000 words", citation: "Vancouver",
      description: "CPCSEA / IAEC submission for any study involving experimental animals. Required before any in-vivo work in India.",
      sections: ["Title", "Background & Rationale", "Objectives", "Animal Species, Strain & Justification (3Rs)", "Number of Animals & Sample Size", "Source of Animals", "Housing & Husbandry", "Experimental Design", "Procedures & Anaesthesia", "Pain & Distress Categorisation", "Humane Endpoints", "Euthanasia Method", "Carcass Disposal", "Investigator Qualifications", "References"]
    },
    {
      id: "ugc-major", label: "UGC Major Research Project", group: "indian",
      country: "India", fundingBody: "University Grants Commission",
      wordLimit: "8,000–10,000 words", citation: "APA / Vancouver (discipline-specific)",
      description: "Multi-year university research project funded by UGC. Suited to faculty in higher-education institutions.",
      sections: ["Title", "Abstract", "Introduction", "Origin of the Proposal", "Objectives", "Review of Literature", "Methodology", "Year-wise Plan of Work", "Budget Justification", "Outcome & Utilisation", "Bibliographical References", "PI Bio-data", "Departmental Endorsement"]
    },
    {
      id: "ugc-minor", label: "UGC Minor Research Project", group: "indian",
      country: "India", fundingBody: "University Grants Commission",
      wordLimit: "3,000–5,000 words", citation: "APA / Vancouver",
      description: "Smaller-scale UGC project (typically 1–2 years) for faculty in colleges and smaller universities.",
      sections: ["Title", "Abstract", "Introduction", "Objectives", "Brief Literature Review", "Methodology", "Plan of Work", "Budget", "Expected Outcomes", "References", "PI Bio-data"]
    },
    {
      id: "dst-crg", label: "DST-SERB Core Research Grant (CRG)", group: "indian",
      country: "India", fundingBody: "Science & Engineering Research Board (DST)",
      wordLimit: "5,000–8,000 words", citation: "Vancouver / IEEE",
      description: "Flagship DST-SERB grant for individual-PI research in basic sciences and engineering, including biomedical engineering.",
      sections: ["Title", "Project Summary", "Origin of the Proposal", "Objectives", "Review of Status of R&D", "Work Plan & Methodology", "Time Schedule (Bar Diagram)", "Sample Size / Statistical Plan", "Budget — Equipment", "Budget — Consumables", "Budget — Travel & Contingencies", "Budget — Manpower", "Outcomes & Deliverables", "Investigator CV", "References"]
    },
    {
      id: "dst-ecr", label: "DST-SERB Early Career Research (ECR / SRG)", group: "indian",
      country: "India", fundingBody: "Science & Engineering Research Board (DST)",
      wordLimit: "3,000–5,000 words", citation: "Vancouver / IEEE",
      description: "Start-up Research Grant for early-career investigators (within 7 years of PhD).",
      sections: ["Title", "Project Summary", "Background & Rationale", "Objectives", "Methodology", "Work Plan & Timeline", "Budget", "Expected Outcomes", "Career Plan", "Investigator CV", "References"]
    },
    {
      id: "dbt", label: "DBT — Department of Biotechnology Grant", group: "indian",
      country: "India", fundingBody: "Department of Biotechnology, Government of India",
      wordLimit: "6,000–10,000 words", citation: "Vancouver",
      description: "Extramural grant for biotechnology, life-sciences and translational research, including BIRAC-linked schemes.",
      sections: ["Title", "Abstract", "Background & Rationale", "Hypothesis & Specific Aims", "Preliminary Data", "Detailed Methodology", "Statistical Plan", "Translational Potential", "Bio-safety Considerations", "Bio-ethics Considerations", "Work Plan & Milestones", "Budget", "Outcome Indicators", "Investigator CV & Publications", "References"]
    },
    {
      id: "csir", label: "CSIR — EMR Scheme", group: "indian",
      country: "India", fundingBody: "Council of Scientific & Industrial Research",
      wordLimit: "4,000–7,000 words", citation: "Vancouver",
      description: "CSIR's Extramural Research scheme — supports scientific R&D in chemistry, biology and applied sciences.",
      sections: ["Title", "Project Summary", "Background", "Objectives", "Methodology", "Work Plan", "Equipment & Infrastructure", "Budget", "Expected Outcomes", "Investigator CV", "References"]
    },
    {
      id: "ayush", label: "AYUSH Grant (Ministry of AYUSH)", group: "indian",
      country: "India", fundingBody: "Ministry of AYUSH, Government of India",
      wordLimit: "5,000–8,000 words", citation: "Vancouver",
      description: "Research grant for Ayurveda, Yoga, Naturopathy, Unani, Siddha and Homoeopathy studies. Includes traditional-medicine clinical evaluation.",
      sections: ["Title", "Abstract", "Background — Classical & Modern Literature", "Rationale within AYUSH framework", "Objectives", "Methodology", "Standardisation of AYUSH Intervention", "Sample Size & Statistical Plan", "Outcome Measures", "Safety Monitoring", "Ethical Considerations", "Work Plan", "Budget", "Investigator CV", "References"]
    },
    {
      id: "ctri", label: "CTRI — Clinical Trials Registry of India", group: "indian",
      country: "India", fundingBody: "ICMR — National Institute of Medical Statistics",
      wordLimit: "Structured form (no narrative)", citation: "N/A",
      description: "Mandatory prospective registration of all clinical trials conducted in India before first participant enrolment.",
      sections: ["Public Title", "Scientific Title", "Trial Acronym", "Trial Sponsor", "Source of Monetary Support", "Primary Sponsor Address", "Secondary Sponsors", "Countries of Recruitment", "Sites of Study", "Health Condition / Problem Studied", "Intervention(s)", "Inclusion Criteria", "Exclusion Criteria", "Method of Generating Randomisation Sequence", "Method of Allocation Concealment", "Blinding & Masking", "Primary Outcomes", "Secondary Outcomes", "Target Sample Size", "Phase of Trial", "Date of First Enrolment", "Recruitment Status", "Publication Details (post-trial)"]
    },
    {
      id: "phd-syn", label: "PhD Synopsis (University)", group: "indian",
      country: "India", fundingBody: "University / Doctoral Committee",
      wordLimit: "3,000–6,000 words", citation: "APA / Vancouver / Chicago (discipline-specific)",
      description: "Pre-registration synopsis submitted to a doctoral committee before commencing PhD research.",
      sections: ["Title", "Introduction", "Statement of the Problem", "Review of Literature", "Research Gap", "Research Questions", "Aims & Objectives", "Hypotheses", "Methodology", "Scope & Limitations", "Tentative Chapter Plan", "Time-line", "Expected Contribution", "References", "Candidate Bio-data", "Supervisor Endorsement"]
    },
    {
      id: "md-ms-syn", label: "MD / MS / DNB Thesis Synopsis", group: "indian",
      country: "India", fundingBody: "Medical University / NMC / NBE",
      wordLimit: "2,500–4,000 words", citation: "Vancouver",
      description: "Mandatory thesis synopsis for postgraduate medical residents (MD / MS / DNB / DM / MCh) per NMC / NBE regulations.",
      sections: ["Title", "Introduction", "Review of Literature", "Lacunae in Existing Knowledge", "Research Question", "Aims & Objectives", "Null & Alternate Hypotheses", "Methodology", "Inclusion & Exclusion Criteria", "Sample Size Calculation", "Statistical Analysis", "Ethical Considerations", "Informed Consent Process", "Plan of Work / Time-line", "Budget (if any)", "Annexures (Proforma, ICF, PIS)", "References"]
    },
    {
      id: "inst-diss", label: "Institutional Dissertation (UG / PG)", group: "indian",
      country: "India", fundingBody: "Institution / Department",
      wordLimit: "3,000–6,000 words", citation: "APA / Vancouver",
      description: "Generic institutional dissertation for UG electives, PG short projects and professional-course dissertations.",
      sections: ["Title", "Abstract", "Introduction", "Aims & Objectives", "Review of Literature", "Methodology", "Expected Results", "Limitations", "Time-line", "Budget", "References", "Annexures"]
    },

    // ---------- Global formats ----------
    {
      id: "nih-r01", label: "NIH R01 — Research Project Grant (USA)", group: "global",
      country: "USA", fundingBody: "National Institutes of Health",
      wordLimit: "12 pages (Research Strategy)", citation: "AMA / NLM",
      description: "NIH's flagship investigator-initiated research project grant. Typically 4–5 years, ~$250K direct costs/year.",
      sections: ["Project Summary / Abstract", "Project Narrative", "Specific Aims", "Research Strategy — Significance", "Research Strategy — Innovation", "Research Strategy — Approach", "Bibliography & References Cited", "Protection of Human Subjects", "Inclusion of Women, Minorities & Children", "Vertebrate Animals", "Resource Sharing Plan", "Authentication of Key Biological Resources", "Budget Justification", "Biographical Sketches", "Letters of Support", "Facilities & Other Resources", "Equipment"]
    },
    {
      id: "nih-r21", label: "NIH R21 — Exploratory / Developmental Grant (USA)", group: "global",
      country: "USA", fundingBody: "National Institutes of Health",
      wordLimit: "6 pages (Research Strategy)", citation: "AMA / NLM",
      description: "NIH grant for high-risk / high-reward exploratory work. Up to 2 years, ~$275K total direct costs.",
      sections: ["Project Summary / Abstract", "Project Narrative", "Specific Aims", "Research Strategy — Significance", "Research Strategy — Innovation", "Research Strategy — Approach", "Bibliography & References Cited", "Protection of Human Subjects", "Vertebrate Animals", "Resource Sharing Plan", "Budget Justification", "Biographical Sketches", "Facilities & Other Resources"]
    },
    {
      id: "who", label: "WHO Research Grant", group: "global",
      country: "International", fundingBody: "World Health Organization",
      wordLimit: "5,000–8,000 words", citation: "Vancouver",
      description: "WHO-administered research grant — typically global health, infectious disease, public-health systems and implementation research.",
      sections: ["Title", "Executive Summary", "Background & Public-Health Significance", "Alignment with WHO Strategic Priorities", "Research Question & Objectives", "Methodology", "Country / Site Selection", "Stakeholder Engagement", "Ethical Considerations", "Risk Management", "Work Plan & Milestones", "Monitoring & Evaluation", "Knowledge-Translation Plan", "Budget", "Investigator CVs", "References"]
    },
    {
      id: "ich-gcp", label: "ICH-GCP Clinical Trial Protocol (E6 R3)", group: "global",
      country: "International", fundingBody: "ICH Member Authorities",
      wordLimit: "20,000–40,000 words", citation: "Vancouver",
      description: "ICH-GCP E6(R3)–compliant clinical trial protocol for drug, device or biologic trials. Required globally for regulatory-grade trials.",
      sections: ["Protocol Identification & Version", "Sponsor Information", "Investigator & Site Information", "Background", "Trial Rationale & Risk-Benefit Assessment", "Trial Objectives & Endpoints", "Trial Design", "Trial Population", "Eligibility Criteria", "Investigational Product(s)", "Concomitant Medications", "Randomisation & Blinding", "Trial Procedures Schedule", "Efficacy Assessments", "Safety Assessments & Adverse Event Reporting", "Statistical Considerations", "Data Management Plan", "Quality Control & Quality Assurance", "Ethics & Informed Consent", "Data Protection & Confidentiality", "Trial Monitoring", "Protocol Deviations", "Premature Termination / Suspension", "Publication Policy", "References", "Appendices"]
    },
    {
      id: "horizon", label: "Horizon Europe (EU Framework Programme)", group: "global",
      country: "European Union", fundingBody: "European Commission",
      wordLimit: "45–70 pages (Part B)", citation: "Vancouver / APA",
      description: "EU's flagship research and innovation framework. Typically multi-partner consortia across multiple member states.",
      sections: ["Excellence — Objectives & Ambition", "Excellence — Methodology", "Impact — Pathways to Impact", "Impact — Measures to Maximise Impact", "Impact — Communication & Dissemination", "Implementation — Work Plan & Work Packages", "Implementation — Consortium Description", "Implementation — Resources (Budget & Effort)", "Ethics Self-Assessment", "Security Issues", "Open Science Practices", "Gender Equality Plan", "Data Management Plan", "References"]
    },
    {
      id: "wellcome", label: "Wellcome Trust Grant (UK)", group: "global",
      country: "United Kingdom", fundingBody: "Wellcome Trust",
      wordLimit: "Varies by scheme (typ. 2,500–5,000 words)", citation: "Vancouver",
      description: "Independent UK biomedical foundation funding global health, discovery research, mental health and climate-and-health.",
      sections: ["Title", "Lay Summary", "Vision & Aims", "Research Question", "Background", "Approach & Methodology", "Outputs & Outcomes", "Equity, Diversity & Inclusion", "Open Research & Data Sharing Plan", "Career Development (if applicable)", "Ethics & Governance", "Resources Requested", "References", "Applicant Biography"]
    },
    {
      id: "gates", label: "Bill & Melinda Gates Foundation Grant", group: "global",
      country: "International", fundingBody: "Bill & Melinda Gates Foundation",
      wordLimit: "5–10 pages (concept) / 20+ (full)", citation: "Vancouver",
      description: "Private foundation funding global health, agricultural development and global growth & opportunity. Strong focus on measurable impact.",
      sections: ["Title", "Executive Summary", "Strategic Alignment with Foundation Priorities", "Problem Statement", "Theory of Change", "Proposed Solution", "Implementation Plan", "Target Population & Geography", "Equity & Gender Considerations", "Risks & Mitigation", "Measurement, Learning & Evaluation", "Sustainability Plan", "Partnerships", "Budget & Budget Narrative", "Key Personnel", "References"]
    },
    {
      id: "nihr", label: "NIHR — National Institute for Health Research (UK)", group: "global",
      country: "United Kingdom", fundingBody: "National Institute for Health & Care Research",
      wordLimit: "Varies by programme (typ. 6,000–10,000 words)", citation: "Vancouver",
      description: "UK government-funded research arm of the NHS — applied health, social-care and public-health research.",
      sections: ["Title", "Plain English Summary", "Research Question", "Background & Rationale", "Aims & Objectives", "Research Plan / Methods", "Patient & Public Involvement (PPI)", "Outcome Measures", "Sample Size & Statistical Plan", "Health Economics", "Equality, Diversity & Inclusion", "Project / Research Timetable", "Project Management", "Ethics & Research Governance", "Dissemination & Knowledge Mobilisation", "Resources Required", "Justification of Costs", "References"]
    },
    {
      id: "mrc", label: "MRC — Medical Research Council (UK)", group: "global",
      country: "United Kingdom", fundingBody: "Medical Research Council, UKRI",
      wordLimit: "8 pages (Case for Support)", citation: "Vancouver",
      description: "UKRI's MRC supports discovery and translational biomedical research across the UK.",
      sections: ["Title", "Lay Summary", "Aims & Hypothesis", "Background", "Track Record of Applicants", "Research Plan", "Timeliness, Importance & Novelty", "Strategic Relevance", "Ethics & Regulatory Considerations", "Data Management & Sharing Plan", "Resources & Justification of Costs", "References"]
    },
    {
      id: "nhmrc", label: "NHMRC — National Health & Medical Research Council (AU)", group: "global",
      country: "Australia", fundingBody: "National Health & Medical Research Council",
      wordLimit: "Scheme-dependent (typ. 5,000–8,000 words)", citation: "Vancouver",
      description: "Australia's primary biomedical and health research funder.",
      sections: ["Title", "Synopsis / Plain Language Summary", "Aims", "Significance", "Innovation", "Approach / Research Plan", "Track Record Relative to Opportunity", "Investigator Roles & Contributions", "Ethics & Governance", "Statistical Considerations", "Translation & Impact Pathway", "Budget & Justification", "References"]
    },
    {
      id: "cihr", label: "CIHR — Canadian Institutes of Health Research", group: "global",
      country: "Canada", fundingBody: "Canadian Institutes of Health Research",
      wordLimit: "10 pages (Project Grant Summary of Research Proposal)", citation: "Vancouver",
      description: "Canada's federal health research funder — covers four CIHR pillars (biomedical, clinical, health systems & population health).",
      sections: ["Title", "Lay Abstract", "Scientific Abstract", "Specific Aims & Hypothesis", "Background & Rationale", "Research Approach / Methodology", "Sex & Gender-Based Analysis Plus (SGBA+)", "Knowledge Translation Plan", "Indigenous Health Research Considerations (if applicable)", "Equity, Diversity & Inclusion", "Timeline", "Team Expertise & Environment", "References"]
    },
    {
      id: "amed", label: "AMED — Japan Agency for Medical R&D", group: "global",
      country: "Japan", fundingBody: "Japan Agency for Medical Research & Development",
      wordLimit: "Programme-dependent", citation: "Vancouver",
      description: "Japan's central agency funding integrated medical R&D — basic, clinical and translational.",
      sections: ["Title", "Project Outline (Japanese & English)", "Research Background", "Objectives & Hypothesis", "Research Plan / Methodology", "Expected Outcomes & Social Implementation", "International Collaboration", "Ethical & Regulatory Compliance", "Project Management Structure", "Annual Plan & Milestones", "Budget Justification", "Investigator Track Record", "References"]
    },
    {
      id: "generic", label: "Generic International Format", group: "global",
      country: "International", fundingBody: "Generic / Other",
      wordLimit: "Flexible", citation: "Vancouver / APA / Discipline-specific",
      description: "Use this when your funder doesn't match a listed template — gives you a clean, conventional academic structure to adapt.",
      sections: ["Title", "Abstract", "Background & Significance", "Research Question", "Aims & Objectives", "Hypothesis", "Methodology", "Statistical / Analytical Plan", "Ethical Considerations", "Timeline", "Budget", "Expected Outcomes", "Limitations", "References", "Investigator CV"]
    },
  ];

  var FORMAT_BY_LABEL = {};
  var FORMAT_BY_ID = {};
  FORMATS.forEach(function (f) {
    FORMAT_BY_LABEL[f.label] = f;
    FORMAT_BY_ID[f.id] = f;
  });

  // ===================== State helpers =====================
  function readState() {
    try {
      var raw = sessionStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (e) { return {}; }
  }

  function writeState(patch) {
    var cur = readState();
    var next = Object.assign({}, cur, patch);
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch (e) { /* ignore */ }
    return next;
  }

  // ===================== DOM refs =====================
  var input, datalist, hint, descCard, descTitle, descGroup, descBody, descCountry,
      descWords, descCite, descText, layout, emptyState, doc, docTitle, docList,
      docSummary, chat, chatLog, chatForm, chatInput, nextBtn;

  var current = null;       // selected FORMAT object
  var sections = [];        // [{name, included}]
  var renaming = null;      // currently-renaming index

  // ===================== Rendering =====================
  function renderDatalist() {
    datalist.innerHTML = "";
    FORMATS.forEach(function (f) {
      var opt = document.createElement("option");
      opt.value = f.label;
      datalist.appendChild(opt);
    });
  }

  function renderDescription() {
    if (!current) {
      descCard.hidden = true;
      hint.hidden = false;
      return;
    }
    hint.hidden = true;
    descCard.hidden = false;
    descTitle.textContent = current.label;
    descGroup.textContent = current.group === "indian" ? "Indian format" : "Global format";
    descGroup.dataset.group = current.group;
    descBody.textContent = current.fundingBody;
    descCountry.textContent = current.country;
    descWords.textContent = current.wordLimit;
    descCite.textContent = current.citation;
    descText.textContent = current.description;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }

  function renderDoc() {
    if (!current) {
      doc.hidden = true;
      emptyState.hidden = false;
      return;
    }
    emptyState.hidden = true;
    doc.hidden = false;
    docTitle.textContent = "Your " + current.label.split(" — ")[0] + " proposal — preview structure";
    docList.innerHTML = "";

    sections.forEach(function (sec, idx) {
      var li = document.createElement("li");
      li.className = "prop-doc-section" + (sec.included ? "" : " is-excluded");
      li.dataset.idx = String(idx);

      var num = document.createElement("span");
      num.className = "prop-doc-num";
      num.textContent = String(idx + 1);

      var checkWrap = document.createElement("label");
      checkWrap.className = "prop-doc-check";
      checkWrap.title = "Include / exclude this section";
      var check = document.createElement("input");
      check.type = "checkbox";
      check.checked = !!sec.included;
      check.setAttribute("data-testid", "checkbox-section-" + idx);
      check.addEventListener("change", function () {
        sections[idx].included = check.checked;
        renderDoc();
        updateSummary();
      });
      checkWrap.appendChild(check);

      var nameWrap = document.createElement("div");
      nameWrap.className = "prop-doc-name";
      if (renaming === idx) {
        var inp = document.createElement("input");
        inp.type = "text";
        inp.className = "prop-doc-rename-input";
        inp.value = sec.name;
        inp.setAttribute("data-testid", "input-rename-" + idx);
        inp.addEventListener("keydown", function (ev) {
          if (ev.key === "Enter") { ev.preventDefault(); commitRename(idx, inp.value); }
          if (ev.key === "Escape") { ev.preventDefault(); renaming = null; renderDoc(); }
        });
        inp.addEventListener("blur", function () { commitRename(idx, inp.value); });
        nameWrap.appendChild(inp);
        setTimeout(function () { inp.focus(); inp.select(); }, 0);
      } else {
        var span = document.createElement("span");
        span.textContent = sec.name;
        nameWrap.appendChild(span);
      }

      var actions = document.createElement("div");
      actions.className = "prop-doc-actions";

      var renameBtn = document.createElement("button");
      renameBtn.type = "button";
      renameBtn.className = "prop-doc-iconbtn";
      renameBtn.title = "Rename section";
      renameBtn.setAttribute("aria-label", "Rename " + sec.name);
      renameBtn.setAttribute("data-testid", "button-rename-" + idx);
      renameBtn.textContent = "✎";
      renameBtn.addEventListener("click", function () { renaming = idx; renderDoc(); });

      var delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "prop-doc-iconbtn prop-doc-iconbtn--danger";
      delBtn.title = "Delete section";
      delBtn.setAttribute("aria-label", "Delete " + sec.name);
      delBtn.setAttribute("data-testid", "button-delete-" + idx);
      delBtn.textContent = "✕";
      delBtn.addEventListener("click", function () {
        sections.splice(idx, 1);
        if (renaming === idx) renaming = null;
        renderDoc();
        updateSummary();
        chatSay("system", "Removed: " + sec.name);
      });

      actions.appendChild(renameBtn);
      actions.appendChild(delBtn);

      li.appendChild(num);
      li.appendChild(checkWrap);
      li.appendChild(nameWrap);
      li.appendChild(actions);
      docList.appendChild(li);
    });

    updateSummary();
  }

  function commitRename(idx, value) {
    var v = (value || "").trim();
    if (v && sections[idx]) {
      var old = sections[idx].name;
      sections[idx].name = v;
      if (old !== v) chatSay("system", "Renamed “" + old + "” → “" + v + "”.");
    }
    renaming = null;
    renderDoc();
  }

  function updateSummary() {
    if (!current) { docSummary.textContent = ""; return; }
    var inc = sections.filter(function (s) { return s.included; }).length;
    var total = sections.length;
    docSummary.textContent = inc + " of " + total + " sections included.";
    nextBtn.disabled = !current || inc === 0;
  }

  // ===================== Chat =====================
  function chatSay(who, text) {
    var row = document.createElement("div");
    row.className = "prop-chat-msg prop-chat-msg--" + who;
    row.textContent = text;
    chatLog.appendChild(row);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  function findSectionIndex(query) {
    var q = (query || "").trim().toLowerCase();
    if (!q) return -1;
    var exact = sections.findIndex(function (s) { return s.name.toLowerCase() === q; });
    if (exact !== -1) return exact;
    var partial = sections.findIndex(function (s) { return s.name.toLowerCase().indexOf(q) !== -1; });
    return partial;
  }

  function handleChat(raw) {
    var msg = (raw || "").trim();
    if (!msg) return;
    chatSay("user", msg);
    if (!current) {
      chatSay("system", "Pick a format on the left first, then I can help you tweak its sections.");
      return;
    }
    var lower = msg.toLowerCase();

    if (lower === "reset" || lower === "restart") {
      sections = current.sections.map(function (n) { return { name: n, included: true }; });
      renderDoc();
      chatSay("system", "Restored the standard " + current.label.split(" — ")[0] + " structure.");
      return;
    }

    var m;
    // rename X to Y
    m = msg.match(/^rename\s+(.+?)\s+(?:to|->|→|as)\s+(.+)$/i);
    if (m) {
      var idx = findSectionIndex(m[1]);
      if (idx === -1) { chatSay("system", "I couldn't find a section matching “" + m[1].trim() + "”."); return; }
      var oldName = sections[idx].name;
      sections[idx].name = m[2].trim();
      renderDoc();
      chatSay("system", "Renamed “" + oldName + "” → “" + sections[idx].name + "”.");
      return;
    }

    // remove / delete X
    m = msg.match(/^(?:remove|delete|drop)\s+(?:the\s+)?(.+?)(?:\s+section)?$/i);
    if (m) {
      var ridx = findSectionIndex(m[1]);
      if (ridx === -1) { chatSay("system", "I couldn't find a section matching “" + m[1].trim() + "”."); return; }
      var removed = sections.splice(ridx, 1)[0];
      renderDoc();
      chatSay("system", "Removed “" + removed.name + "”.");
      return;
    }

    // exclude / include X
    m = msg.match(/^(exclude|include|untick|tick|check|uncheck)\s+(?:the\s+)?(.+?)(?:\s+section)?$/i);
    if (m) {
      var iidx = findSectionIndex(m[2]);
      if (iidx === -1) { chatSay("system", "I couldn't find a section matching “" + m[2].trim() + "”."); return; }
      var verb = m[1].toLowerCase();
      var on = (verb === "include" || verb === "tick" || verb === "check");
      sections[iidx].included = on;
      renderDoc();
      chatSay("system", (on ? "Included " : "Excluded ") + "“" + sections[iidx].name + "”.");
      return;
    }

    // add X (after Y) | add X
    m = msg.match(/^add\s+(?:a\s+|an\s+|the\s+)?(.+?)(?:\s+section)?(?:\s+after\s+(.+))?$/i);
    if (m) {
      var name = m[1].trim().replace(/\s+/g, " ");
      // Title-case the first letter of each word for niceness
      name = name.replace(/\b\w/g, function (c) { return c.toUpperCase(); });
      var insertAt = sections.length;
      if (m[2]) {
        var aidx = findSectionIndex(m[2]);
        if (aidx !== -1) insertAt = aidx + 1;
      }
      sections.splice(insertAt, 0, { name: name, included: true });
      renderDoc();
      var afterName = (m[2] && sections[insertAt - 1]) ? sections[insertAt - 1].name : "";
      chatSay("system", "Added “" + name + "”" + (afterName ? " after “" + afterName + "”" : "") + ".");
      return;
    }

    chatSay("system", "I didn't understand. Try: “remove budget”, “add conflicts of interest”, “rename methodology to methods”, or “reset”.");
  }

  // ===================== Selection flow =====================
  function selectFormat(format, opts) {
    opts = opts || {};
    current = format;
    sections = format.sections.map(function (n) { return { name: n, included: true }; });
    renaming = null;
    layout.dataset.state = "ready";
    chat.hidden = false;
    if (!opts.silent) {
      chatLog.innerHTML = "";
      chatSay("system",
        "This is the standard structure for " + format.label.split(" — ")[0] +
        ". Want to add, remove or rename any section? Just type below."
      );
    }
    renderDescription();
    renderDoc();
  }

  function onInput() {
    var v = input.value.trim();
    var match = FORMAT_BY_LABEL[v];
    if (match) {
      if (!current || current.id !== match.id) selectFormat(match);
    }
  }

  // ===================== Init =====================
  function init() {
    input = document.getElementById("prop-format-input");
    datalist = document.getElementById("prop-format-list");
    hint = document.getElementById("prop-format-hint");

    descCard = document.getElementById("prop-format-desc");
    descTitle = document.getElementById("prop-format-desc-title");
    descGroup = document.getElementById("prop-format-desc-group");
    descBody = document.getElementById("prop-format-desc-body");
    descCountry = document.getElementById("prop-format-desc-country");
    descWords = document.getElementById("prop-format-desc-words");
    descCite = document.getElementById("prop-format-desc-cite");
    descText = document.getElementById("prop-format-desc-text");

    layout = document.getElementById("prop-format-layout");
    emptyState = document.getElementById("prop-format-empty");
    doc = document.getElementById("prop-doc");
    docTitle = document.getElementById("prop-doc-title");
    docList = document.getElementById("prop-doc-sections");
    docSummary = document.getElementById("prop-doc-summary");

    chat = document.getElementById("prop-chat");
    chatLog = document.getElementById("prop-chat-log");
    chatForm = document.getElementById("prop-chat-form");
    chatInput = document.getElementById("prop-chat-input");

    nextBtn = document.getElementById("prop-format-next");

    if (!input || !nextBtn) return;

    // Gate: must have role + langMode set.
    var saved = readState();
    if (!saved.role) { window.location.replace("/proposal-module/role.html"); return; }
    if (!saved.langMode) { window.location.replace("/proposal-module/language.html"); return; }

    renderDatalist();

    // Restore previously-saved selection (if any).
    if (saved.format && FORMAT_BY_ID[saved.format.id]) {
      input.value = FORMAT_BY_ID[saved.format.id].label;
      selectFormat(FORMAT_BY_ID[saved.format.id], { silent: true });
      // Restore custom section list if compatible.
      if (Array.isArray(saved.format.sections) && saved.format.sections.length) {
        sections = saved.format.sections.map(function (s) {
          return { name: String(s.name || ""), included: s.included !== false };
        });
        renderDoc();
      }
    }

    input.addEventListener("input", onInput);
    input.addEventListener("change", onInput);

    chatForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var v = chatInput.value;
      chatInput.value = "";
      handleChat(v);
    });

    nextBtn.addEventListener("click", function () {
      if (!current) return;
      var inc = sections.filter(function (s) { return s.included; }).length;
      if (inc === 0) return;
      writeState({
        format: {
          id: current.id,
          label: current.label,
          group: current.group,
          country: current.country,
          fundingBody: current.fundingBody,
          wordLimit: current.wordLimit,
          citation: current.citation,
          sections: sections.map(function (s) { return { name: s.name, included: !!s.included }; }),
        },
      });
      window.location.href = "/proposal-module/outline.html";
    });

    updateSummary();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
