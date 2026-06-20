# Sigma Chapter V Export Style Guide

This guide records generic rendering rules inferred from multiple thesis-style
Chapter V examples. It must remain study-agnostic: do not hardcode student
names, diagnoses, hospitals, variable names, or category values from reference
documents.

## Chapter Structure

Use a thesis-readable results chapter:

1. `CHAPTER V / OBSERVATION AND RESULTS` or a generic `RESULTS` heading.
2. Study summary with readable study design, sample size, and primary outcome.
3. Statistical analysis paragraph derived from tests actually executed or
   explicitly recommended-only.
4. Descriptive findings grouped by variable role/domain.
5. Inferential findings grouped by analysis family.
6. Final significant findings summary.
7. Warnings and interpretation notes.

Audit metadata such as dataset IDs, result IDs, generated timestamps, raw domain
profile tokens, and internal debug keys belongs in Excel/audit sheets, not in
the main thesis body.

## Table-Figure-Interpretation Cadence

For each thesis-ready result block, render:

1. Compact table.
2. Figure when an actual generated image is available.
3. Concise interpretation paragraph.

Do not render placeholder figures such as "Graph preview not generated yet" in
the main report. Optional, non-significant, high-cardinality, or detailed-only
graphs should be deferred to an appendix/detailed report.

## Descriptive Tables

Avoid repeating the same variable across multiple main descriptive tables.
Prefer non-overlapping sections:

- Baseline/demographic characteristics.
- Clinical or study-specific characteristics.
- Biomarker, immunophenotype, or measurement characteristics where relevant.
- Marker/outcome component descriptives where relevant.

Variables excluded from analysis may be described in audit metadata but should
not appear as inferential thesis variables.

## Inferential Tables

Use compact tables:

- Group/category summaries.
- Test statistic.
- Raw p-value.
- Adjusted p-value where available.
- Test applied.
- Effect size.

Move long warnings below tables as caution notes instead of forcing wide warning
columns. Keep raw and adjusted p-values in separate columns.

## Figures

Include only core thesis figures:

- Primary outcome distribution.
- Key significant associations/comparisons.
- Core descriptive figures where generated.

Use existing deterministic graph images from Sigma results. Do not fabricate
statistical graph content in the export layer.

## Interpretation Rules

Keep interpretations deterministic and cautious:

- Do not claim causality from association analyses.
- Do not claim independent prognostic value unless an adjusted model was run.
- Mention sparse-cell or high-cardinality cautions where applicable.
- Use thesis-facing labels, not raw internal labels, when display labels exist.

## Encoding and Labels

Decode HTML entities and preserve readable scientific symbols:

- `<`, `>`, `&`
- `±`
- `≤`, `≥`
- `Cramér's V`

For marker/status outcomes, use thesis-facing values such as
`Positive`/`Negative` instead of raw `Yes`/`No` in the report body.
