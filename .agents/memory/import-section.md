---
name: Import section flow
description: How the Scriptorium editor's "Import existing content" feature works — modal stages, results-chapter gating, Sigma data key.
---

**Rule:** The import modal has 3 stages: (1) source (file upload / paste / Sigma card), (2) preview with table review, (3) polish spinner. Stage 1 shows the Sigma card only when `chapterId === 'results' || chapterId.startsWith('results_')` AND Sigma data is available in sessionStorage.

**Sigma data key:** Written by `analysis.js` bindResults → "Take to Scriptorium" button as `sessionStorage["medras.sigma.results"]`. The editor falls back to `sessionStorage["folio.import.from_sigma"]` (the older Folio key) when the Scriptorium-specific key is absent.

**Results chapter gating:** `renderHelpers()` filters out `ai_draft` from helpers for all results chapters and prepends `sigma_import` + `import` buttons, plus an amber notice banner.

**Backend:** `POST /api/thesis/import-section` (multipart file). Returns `{prose: str, tables: [{rows: [[str]], caption: str}]}`. DOCX walks `doc.element.body` children by tag (`w:p` → prose, `w:tbl` → structured rows). PDF uses pypdf (no table structure). TXT decoded as prose. Back-matter stripped by REFERENCES regex.

**Why:** Researchers always arrive with existing content. Force-typing from scratch loses their supervisor-approved drafts and Sigma-generated tables.

**How to apply:** When adding new chapter types that should be import-only (like Results), add the chapter id to the `chapterId === 'results' || chapterId.startsWith('results_')` check in both `renderHelpers()` and `_isResultsChapter()`.
