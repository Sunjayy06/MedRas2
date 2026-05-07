/* Shared catalogue of writing modes (Thesis vs Article), researcher
   roles, and per-deliverable targets. Used by index.html (picker),
   setup.html (display + adaptive fields), and — in a future iteration
   — compliance.html and export.html so plagiarism caps, AI-text caps,
   word-count and citation targets all flow from one source of truth.

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

  // Article-type catalogue. word_min/max are word counts; citation_min/max
  // are reference counts; plag_cap / ai_cap are percentages. guideline is
  // the reporting-checklist the AI prompts and the export validator must
  // honour (CARE, STROBE, PRISMA, …). delivery_days is informational
  // (a hint of typical scope, not a hard deadline).
  var ARTICLE_TYPES = [
    {
      id: 'case_report',
      label: 'Case Report',
      blurb: 'A single, instructive clinical case — diagnosis, management, learning point.',
      guideline: 'CARE',
      word_min: 6000, word_max: 6000,
      citation_min: 10, citation_max: 15,
      plag_cap: 10, ai_cap: 10,
      delivery_days: '3–4 days',
    },
    {
      id: 'case_series',
      label: 'Case Series',
      blurb: 'A small set of related cases with summary tables / clinical pattern charts.',
      guideline: 'STROBE',
      word_min: 8000, word_max: 8000,
      citation_min: 15, citation_max: 20,
      plag_cap: 10, ai_cap: 10,
      delivery_days: '4–5 days',
    },
    {
      id: 'narrative_review',
      label: 'Narrative Review',
      blurb: 'A thematic synthesis with a conceptual model — no formal search protocol.',
      guideline: 'Narrative (no checklist)',
      word_min: 8000, word_max: 8000,
      citation_min: 20, citation_max: 25,
      plag_cap: 10, ai_cap: 10,
      delivery_days: '5–6 days',
    },
    {
      id: 'systematic_review',
      label: 'Systematic Review',
      blurb: 'Search strategy, PRISMA flow diagram, risk-of-bias assessment, formal synthesis.',
      guideline: 'PRISMA',
      word_min: 12000, word_max: 15000,
      citation_min: 40, citation_max: 60,
      plag_cap: 10, ai_cap: 10,
      delivery_days: '7–10 days',
    },
    {
      id: 'meta_analysis',
      label: 'Meta-analysis',
      blurb: 'Forest / funnel plots, heterogeneity (I²), pooled effect estimates.',
      guideline: 'PRISMA + MOOSE',
      word_min: 12000, word_max: 15000,
      citation_min: 40, citation_max: 70,
      plag_cap: 10, ai_cap: 10,
      delivery_days: '10–12 days',
    },
    {
      id: 'original_research',
      label: 'Original Research Article',
      blurb: 'Cross-sectional · case–control · cohort · RCT · quasi-experimental · KAP · qualitative · community surveys.',
      guideline: 'STROBE / CONSORT / COREQ (per design)',
      word_min: 12000, word_max: 15000,
      citation_min: 25, citation_max: 40,
      plag_cap: 10, ai_cap: 10,
      delivery_days: '7–10 days',
    },
    {
      id: 'monograph',
      label: 'Monograph',
      blurb: 'A focused 70–80-page treatise on a defined topic — design customised to scope.',
      guideline: 'Custom (topic-driven)',
      page_min: 70, page_max: 80,
      citation_min: 40, citation_max: 50,
      plag_cap: 10, ai_cap: 15,
      delivery_days: '15–20 days',
    },
  ];

  // Thesis catalogue. Indian PG thesis deliverables baked in once so the
  // compliance pre-flight has the same numbers the welcome page promises.
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

  function byId(id) {
    var all = [].concat(THESIS_TYPES, ARTICLE_TYPES);
    for (var i = 0; i < all.length; i++) if (all[i].id === id) return all[i];
    return null;
  }
  function roleById(id) {
    for (var i = 0; i < ROLES.length; i++) if (ROLES[i].id === id) return ROLES[i];
    return null;
  }

  window.WritingModes = {
    ROLES: ROLES,
    THESIS_TYPES: THESIS_TYPES,
    ARTICLE_TYPES: ARTICLE_TYPES,
    byId: byId,
    roleById: roleById,
  };
})();
