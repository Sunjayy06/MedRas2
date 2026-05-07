/* Shared catalogue of writing modes (Thesis vs Article), researcher
   roles, and per-deliverable targets. Used by index.html (picker),
   setup.html (display + adaptive fields), compliance.html and export.html
   so plagiarism caps, AI-text caps, word-count and citation targets all
   flow from one source of truth.

   Article spines themselves live server-side in
   `app/services/thesis_formats.py` (ARTICLE_SPINES, JOURNAL_TIERS) and
   are fetched via GET /api/thesis/spine?mode=article&article_type=…
   &design=…&tier=…&citation_style=… — this file only carries the
   metadata needed by the welcome / setup pages (labels, blurbs,
   reporting-checklist hint, plag/AI caps, default citation style by
   tier).

   Prices intentionally omitted — this module is the writer, not the
   billing system.
*/
(function () {
  'use strict';

  var ROLES = [
    { id: 'md_ms',       label: 'MD / MS candidate (Indian university)' },
    { id: 'dnb',         label: 'DNB candidate (NBEMS)' },
    { id: 'phd',         label: 'PhD candidate' },
    { id: 'faculty',     label: 'Faculty / Professor' },
    { id: 'chief',       label: 'Department Chief / HOD' },
    { id: 'researcher',  label: 'Independent researcher / fellow' },
    { id: 'student',     label: 'Undergraduate / intern' },
    { id: 'other',       label: 'Other' },
  ];

  // ---- Article-type catalogue ---------------------------------------
  // The frontend keeps the welcome-page metadata; the server owns the
  // chapter spine. word_min/max here are sane fallbacks for the picker —
  // the actual per-section word budget at the editor / compliance level
  // comes from the chosen journal tier (T1-T4) and is resolved server-
  // side in /api/thesis/spine.
  var ARTICLE_TYPES = [
    {
      id: 'case_report',
      label: 'Case Report',
      blurb: 'A single, instructive clinical case — diagnosis, management, learning point.',
      checklist: 'care',
      guideline: 'CARE',
      asks_design: false,
      typical_tier: 't4',
      citation_min: 10, citation_max: 15,
      delivery_days: '3–4 days',
    },
    {
      id: 'case_series',
      label: 'Case Series',
      blurb: 'A small set of related cases with summary tables / clinical pattern charts.',
      checklist: 'strobe',
      guideline: 'STROBE (case-series adaptation)',
      asks_design: false,
      typical_tier: 't3',
      citation_min: 15, citation_max: 20,
      delivery_days: '4–5 days',
    },
    {
      id: 'narrative_review',
      label: 'Narrative Review',
      blurb: 'A thematic synthesis with a conceptual model — no formal search protocol.',
      checklist: 'narrative',
      guideline: 'Narrative (no checklist)',
      asks_design: false,
      typical_tier: 't3',
      citation_min: 20, citation_max: 25,
      delivery_days: '5–6 days',
    },
    {
      id: 'systematic_review',
      label: 'Systematic Review',
      blurb: 'Search strategy, PRISMA flow diagram, risk-of-bias assessment, formal synthesis.',
      checklist: 'prisma',
      guideline: 'PRISMA 2020',
      asks_design: false,
      typical_tier: 't2',
      citation_min: 40, citation_max: 60,
      delivery_days: '7–10 days',
    },
    {
      id: 'meta_analysis',
      label: 'Meta-analysis',
      blurb: 'Forest / funnel plots, heterogeneity (I²), pooled effect estimates.',
      checklist: 'moose',
      guideline: 'PRISMA + MOOSE',
      asks_design: false,
      typical_tier: 't1',
      citation_min: 40, citation_max: 70,
      delivery_days: '10–12 days',
    },
    {
      id: 'original_research',
      label: 'Original Research Article',
      blurb: 'Cross-sectional · case–control · cohort · RCT · quasi-experimental · KAP · qualitative · community surveys.',
      checklist: 'imrad',  // overridden by the design picker below
      guideline: 'STROBE / CONSORT / COREQ (per design)',
      asks_design: true,
      typical_tier: 't2',
      citation_min: 25, citation_max: 40,
      delivery_days: '7–10 days',
    },
    {
      id: 'monograph',
      label: 'Monograph',
      blurb: 'A focused 70–80-page treatise on a defined topic — design customised to scope.',
      checklist: 'imrad',
      guideline: 'Custom (topic-driven)',
      asks_design: false,
      typical_tier: 't3',
      page_min: 70, page_max: 80,
      citation_min: 40, citation_max: 50,
      delivery_days: '15–20 days',
    },
  ];

  // ---- Original-research designs ------------------------------------
  // Chosen by the welcome page when the researcher picks Original Research,
  // routes to the right server-side spine (CONSORT / STROBE / COREQ / IMRaD).
  var ORIGINAL_RESEARCH_DESIGNS = [
    { id: 'rct',                  label: 'Randomised controlled trial (RCT)',     checklist: 'consort' },
    { id: 'cohort_prospective',   label: 'Prospective cohort',                    checklist: 'strobe' },
    { id: 'cohort_retrospective', label: 'Retrospective cohort',                  checklist: 'strobe' },
    { id: 'case_control',         label: 'Case–control',                          checklist: 'strobe' },
    { id: 'cross_sectional',      label: 'Cross-sectional / KAP / survey',        checklist: 'strobe' },
    { id: 'qualitative',          label: 'Qualitative (interviews, focus groups)',checklist: 'coreq' },
    { id: 'quasi_experimental',   label: 'Quasi-experimental / before-after',     checklist: 'strobe' },
    { id: 'mixed_methods',        label: 'Mixed methods',                         checklist: 'imrad' },
    { id: 'diagnostic_accuracy',  label: 'Diagnostic accuracy study',             checklist: 'imrad' },
    { id: 'economic_evaluation',  label: 'Economic / cost-effectiveness',         checklist: 'imrad' },
  ];

  // ---- Journal tiers (mirrors thesis_formats.JOURNAL_TIERS) ---------
  var JOURNAL_TIERS = [
    {
      id: 't1',
      label: 'Tier 1 — Top medical journals',
      examples: 'NEJM · Lancet · JAMA · BMJ · Annals Int Med',
      body_words_min: 2700, body_words_max: 3500,
      abstract_words: 250, abstract_structured: true,
      ref_min: 30, ref_max: 40,
      figures_max: 5,
      default_citation_style: 'vancouver',
      plag_cap: 8, ai_cap: 5,
    },
    {
      id: 't2',
      label: 'Tier 2 — High-impact specialty',
      examples: 'Cell · Nature Med · Circulation · JCO · Lancet sub-specialties',
      body_words_min: 3500, body_words_max: 4500,
      abstract_words: 250, abstract_structured: true,
      ref_min: 40, ref_max: 60,
      figures_max: 8,
      default_citation_style: 'vancouver',
      plag_cap: 10, ai_cap: 8,
    },
    {
      id: 't3',
      label: 'Tier 3 — Mid-impact Scopus / Elsevier / Springer',
      examples: 'BMC · PLOS · BMJ Open · Frontiers · most society journals',
      body_words_min: 4000, body_words_max: 5000,
      abstract_words: 300, abstract_structured: true,
      ref_min: 40, ref_max: 60,
      figures_max: 10,
      default_citation_style: 'vancouver',
      plag_cap: 10, ai_cap: 10,
    },
    {
      id: 't4',
      label: 'Tier 4 — Low-impact Scopus / regional',
      examples: 'Cureus · Indian J Med Res · regional society journals',
      body_words_min: 5000, body_words_max: 6000,
      abstract_words: 300, abstract_structured: false,
      ref_min: 30, ref_max: null,
      figures_max: null,
      default_citation_style: 'vancouver',
      plag_cap: 15, ai_cap: 15,
    },
  ];

  // ---- Citation styles ---------------------------------------------
  var CITATION_STYLES = [
    { id: 'vancouver', label: 'Vancouver / ICMJE (most medical journals)' },
    { id: 'apa',       label: 'APA 7 (psychology, social sciences)' },
    { id: 'harvard',   label: 'Harvard (BMJ family, some Elsevier)' },
    { id: 'ama',       label: 'AMA (JAMA family)' },
    { id: 'chicago',   label: 'Chicago' },
    { id: 'ieee',      label: 'IEEE (engineering)' },
  ];

  // ---- Reporting-checklist info (display only) ----------------------
  var CHECKLIST_INFO = {
    care:      { label: 'CARE',          desc: 'Case-report reporting checklist (Gagnier 2013).' },
    consort:   { label: 'CONSORT 2010',  desc: 'Reporting parallel-group RCTs.' },
    strobe:    { label: 'STROBE',        desc: 'Reporting cohort, case-control and cross-sectional studies.' },
    prisma:    { label: 'PRISMA 2020',   desc: 'Preferred Reporting Items for Systematic Reviews & Meta-Analyses.' },
    moose:     { label: 'PRISMA + MOOSE',desc: 'Meta-analysis of observational studies in epidemiology.' },
    coreq:     { label: 'COREQ',         desc: 'Consolidated criteria for reporting qualitative research.' },
    imrad:     { label: 'IMRaD',         desc: 'Generic Introduction · Methods · Results · Discussion.' },
    narrative: { label: 'Narrative',     desc: 'Thematic review (no formal checklist).' },
  };

  // ---- Thesis catalogue ---------------------------------------------
  var THESIS_TYPES = [
    {
      id: 'pg_thesis',
      label: 'Postgraduate thesis (MD / MS / DNB / PhD)',
      blurb: 'Full PG thesis — standard design (cross-sectional / cohort / case-control / qualitative / mixed methods).',
      guideline: 'University / NBEMS rules (Vancouver)',
      page_min: 80, page_max: 100,
      citation_min: 50, citation_max: 60,
      plag_cap: 10, ai_cap: 15,
      delivery_days: '20–25 days',
    },
  ];

  // ---- Helpers ------------------------------------------------------
  function byId(id) {
    var all = [].concat(THESIS_TYPES, ARTICLE_TYPES);
    for (var i = 0; i < all.length; i++) if (all[i].id === id) return all[i];
    return null;
  }
  function roleById(id) {
    for (var i = 0; i < ROLES.length; i++) if (ROLES[i].id === id) return ROLES[i];
    return null;
  }
  function designById(id) {
    for (var i = 0; i < ORIGINAL_RESEARCH_DESIGNS.length; i++)
      if (ORIGINAL_RESEARCH_DESIGNS[i].id === id) return ORIGINAL_RESEARCH_DESIGNS[i];
    return null;
  }
  function tierById(id) {
    for (var i = 0; i < JOURNAL_TIERS.length; i++)
      if (JOURNAL_TIERS[i].id === id) return JOURNAL_TIERS[i];
    return null;
  }
  // Resolve checklist id from (article_type, design) — same logic as
  // server-side resolve_checklist in thesis_formats.py.
  function resolveChecklist(article_type, design) {
    var t = byId(article_type);
    if (!t) return 'imrad';
    if (article_type === 'original_research') {
      var d = designById(design);
      if (d && d.checklist) return d.checklist;
    }
    return t.checklist || 'imrad';
  }
  // Build the query string for GET /api/thesis/spine from a setup blob.
  function spineQuery(setup) {
    setup = setup || {};
    if (setup.mode !== 'article') return '';
    var qs = ['mode=article'];
    if (setup.article_type)   qs.push('article_type=' + encodeURIComponent(setup.article_type));
    if (setup.design)         qs.push('design='       + encodeURIComponent(setup.design));
    if (setup.tier)           qs.push('tier='         + encodeURIComponent(setup.tier));
    if (setup.citation_style) qs.push('citation_style=' + encodeURIComponent(setup.citation_style));
    return '?' + qs.join('&');
  }

  window.WritingModes = {
    ROLES: ROLES,
    THESIS_TYPES: THESIS_TYPES,
    ARTICLE_TYPES: ARTICLE_TYPES,
    ORIGINAL_RESEARCH_DESIGNS: ORIGINAL_RESEARCH_DESIGNS,
    JOURNAL_TIERS: JOURNAL_TIERS,
    CITATION_STYLES: CITATION_STYLES,
    CHECKLIST_INFO: CHECKLIST_INFO,
    byId: byId,
    roleById: roleById,
    designById: designById,
    tierById: tierById,
    resolveChecklist: resolveChecklist,
    spineQuery: spineQuery,
  };
})();
