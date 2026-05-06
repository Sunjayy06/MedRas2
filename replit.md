# MedRAS

MedRAS is a structured Research Operating System that guides medical and academic researchers from objectives to submission-ready manuscripts.

## Run & Operate

*   `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`: Run the FastAPI application.
*   `python -m pytest`: Run tests.
*   **Required Env Vars:** `OPENAI_API_KEY`, `GEMINI_API_KEY`, `COPALEAKS_API_KEY` (for plagiarism checks).

## Stack

*   **Backend:** Python 3.11, FastAPI, Uvicorn
*   **Frontend:** HTML, CSS, JavaScript (no frameworks)
*   **ORM:** _Populate as you build_
*   **Validation:** Pydantic (implicitly via FastAPI)
*   **Build Tool:** _Populate as you build_
*   **Key Libraries:** `pandas`, `numpy`, `scipy`, `statsmodels`, `scikit-learn`, `lifelines`, `pingouin`, `scikit-posthocs`, `pypdf`, `python-docx`.

## Where things live

*   `/app`: Backend Python source code.
    *   `/app/api`: API endpoints (e.g., `plagiarism.py`).
    *   `/app/services`: Core business logic and statistical services (e.g., `variable_classifier.py`, `data_quality.py`, `text_analyzer.py`, `plagiarism_analyzer.py`).
*   `/public`: Frontend static files (HTML, CSS, JS).
    *   `/public/index.html`: Main landing page.
    *   `/public/analysis.html`: Statistical Analysis Engine UI.
    *   `/public/plagiarism-module`: Plagiarism & AI Reduction module UI (`intake.html` → `reduce-results.html`; `checker.html` for score-only).
    *   `/public/proposal-module`: Proposal Writing Module UI. `index.html` is the module homepage. `role.html` (Step 1) and `language.html` (Step 2) share `js/intake.js`; `format.html` (Step 3) uses `js/format.js`; `outline.html` (Step 4) uses `js/outline.js`. All share `css/style.css` (navy theme, `.prop-*` namespace). SessionStorage key `medras.proposal.intake` stores `{role, roleLabel, langMode, secondLang, secondLangLabel, secondLangOther, format:{id,label,group,country,fundingBody,wordLimit,citation,sections:[{name,included}]}, outline:{sections:{name:text}, updatedAt}}`. Each step self-redirects backwards if its prerequisite state is missing. Steps 5–6 (Draft / Export) are stubbed placeholders in the stepper for the next iteration.
*   `/artifacts/medras`: Files outside this directory should not be modified.
*   **DB Schema:** _Populate as you build_
*   **API Contracts:** Defined implicitly by FastAPI Pydantic models.
*   **Theme Files:** `/public/css/style.css` (primary styling).

## Architecture decisions

*   **No Frontend Frameworks:** Intentional choice for simplicity, direct control, and robustness.
*   **In-Memory Processing:** All uploaded files are processed in-memory and never written to disk for security and performance.
*   **LLMs for Planning/Writing Only:** LLMs are strictly used for planning and textual tasks; numerical computations are library-backed.
*   **Dual LLM Provider Fallback:** Plagiarism & AI Reduction module uses an `auto` provider strategy, falling back between OpenAI and Google Gemini for resilience and quota management.
*   **Proposal Writing Module — Step 4 Outline (upload + AI section-fill):** Frontend is `public/proposal-module/outline.html` + `js/outline.js`. Flow: pre-flight ("do you have docs?") → bulk upload zone (PDF/DOCX/PPTX/TXT/MD; ≤10 files, 100 MB each, 200 MB total) → vertical accordion of sections (status icon green/amber/red, textarea, three buttons: per-section upload / Sample Size Calculator [only on `/sample\s*size|statistical\s+(analysis|plan)/i` matches, links to `/sample-size.html`] / Study Builder [disabled, "soon"]) → audit panel with overall % bar + per-row "Let MedRAS Generate This" on red rows. Status thresholds: ≥200 chars=full(green), ≥1=short(amber), 0=empty(red); progress = (full + 0.5·short)/total. Bulk extract NEVER overwrites already-typed content. Backend: `app/services/outline_extractor.py` wraps `plagiarism_analyzer.extract_text_from_upload` and adds `.pptx` (python-pptx, slides+tables+notes; rejects `.ppt`); `app/services/section_classifier.py` calls Gemini 2.5-flash via `_pa._call_gemini_json` (classify, max 30k corpus chars, 8k chars/section cap) and `_pa._call_gemini_text` (generate, 200-400 words, uses placeholders for unknowns). Endpoints: `POST /api/outline/extract` (multi-file + sections JSON), `POST /api/outline/extract-section` (single file appends to existing), `POST /api/outline/generate` (JSON body). New runtime dep: `python-pptx>=1.0`.
*   **Proposal Writing Module — Format catalog lives in `js/format.js`:** All 28 supported formats (15 Indian + 13 global) are defined as a `FORMATS` array of `{id, label, group, country, fundingBody, wordLimit, citation, description, sections[]}`. Step 3's split-screen layout reads from this single source. Section list is mutable per session; the chatbox parser supports five intents — `remove/delete/drop X`, `add X (after Y)?`, `rename X to Y`, `include/exclude/tick/untick X`, and `reset`. Section matching is case-insensitive substring (exact match wins). All chat output uses `textContent` (no innerHTML on user input). Continue is gated on at least one section being included.
*   **Plagiarism Reducer — 3-step intake (Path A vs Path B):** `/plagiarism-module/intake.html` is the front door for "Reduce plagiarism". Step 1 asks whether the user already has a plagiarism-checker report. Path A (with report) uploads original + report + software dropdown; report is parsed by `app/services/report_parser.py` into a `{section: {similarity_percent, flagged}}` map and forwarded into `POST /api/plagiarism/jobs` as `report.flagged_map`. Per-section intensity buckets: `<10%`=skip-verbatim (green badge "Already within acceptable limits"), `10-15%`=light (stages A+B only), `15-30%`=normal (all 3), `>30%`=aggressive (all 3, tagged). Path B is a single upload that omits `report` and behaves exactly as before. References are ALWAYS skipped regardless of report. Results page renders a Path-A summary box ("Based on your Turnitin report: X needed rewriting…") and a per-card "Was X% similar" badge colour-banded to the intensity bucket.
*   **Plagiarism Pipeline — Job + Polling (replaces NDJSON streaming):** The reducer now uses `POST /api/plagiarism/jobs` → `GET /api/plagiarism/jobs/{id}` (polled every 5s). A singleton `JobManager` (`app/services/plagiarism_jobs.py`) runs each job in a daemon thread, processing one section at a time. Per-stage 60s wall-clock timeout (with the SDK request timeout set 2s tighter so the socket actually closes — no orphaned token burn). Caps: 3 concurrent jobs, 500MB total in-memory across all jobs, 30-min TTL with lazy cleanup on every create/get. After each section completes, `original` and stage-A/B intermediates are dropped and `bytes_tracked` is recomputed from the actual retained strings. Circuit breaker: 2 consecutive timeouts abort the rest of the job. `POST /jobs/{id}/retry` re-queues only failed/timed-out sections without re-uploading. All error strings are sanitized at the serialize_job boundary defensively (never leak provider keys).
*   **Robust File Upload Handling:** Comprehensive pre-processing and error handling for uploaded documents (size caps, PDF type checks, password protection).

## Product

*   **Study Builder:** Translates research objectives into methodologies.
*   **Sample Size Calculator:** Provides formula-driven sample size estimations with advanced UX and reporting.
*   **Statistical Analysis Engine:** Guided 12-screen wizard for data input, variable classification, quality checks, and statistical analysis with client-side state persistence.
*   **Proposal Writing Module:** Guided 6-step intake (Role → Language → Format → Outline → Draft → Export) for ICMR, IEC, UGC, DST-SERB, PhD Synopsis, CTRI, AYUSH, DBT, CSIR, NIH, WHO, ICH-GCP, Horizon Europe, Wellcome Trust, Gates, NIHR, NHMRC, CIHR. Steps 1-4 (Role / Language / Format / Outline) are live; Outline supports multi-file upload, Gemini auto-classification of content into the chosen format's sections, per-section editing with "Let MedRAS Generate This" for missing sections, and a green/amber/red completion audit. Draft/Export are upcoming.
*   **Thesis & Article Writer:** Assists in compiling structured manuscripts.
*   **Plagiarism & AI Reduction:** Offers originality scoring, AI likelihood detection, and a 3-stage rewrite pipeline to reduce plagiarism while preserving academic integrity.

## User preferences

*   I want iterative development.
*   Ask before making major changes.
*   Do not make changes to files outside the `artifacts/medras/` directory.
*   Do not make changes to `.replit-artifact/artifact.toml`.

## Gotchas

*   Uploaded files are subject to 100 MB byte cap and 200-page PDF cap; ensure files meet these limits.
*   Plagiarism module's rewrite pipeline automatically skips References/Bibliography sections; do not include them if you want them paraphrased.
*   Quota exhaustion for LLM providers will lead to temporary service unavailability for plagiarism rewrites; a fallback mechanism is in place, but prolonged exhaustion will require topping up accounts or waiting.

## Pointers

*   [FastAPI Documentation](https://fastapi.tiangolo.com/){:target="_blank"}
*   [Pandas Documentation](https://pandas.pydata.org/docs/){:target="_blank"}
*   [OpenAI API Documentation](https://platform.openai.com/docs/){:target="_blank"}
*   [Google Gemini API Documentation](https://ai.google.dev/docs){:target="_blank"}
*   [Uvicorn Documentation](https://www.uvicorn.org/){:target="_blank"}