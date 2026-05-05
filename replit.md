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
    *   `/public/plagiarism-module`: Plagiarism & AI Reduction module UI.
*   `/artifacts/medras`: Files outside this directory should not be modified.
*   **DB Schema:** _Populate as you build_
*   **API Contracts:** Defined implicitly by FastAPI Pydantic models.
*   **Theme Files:** `/public/css/style.css` (primary styling).

## Architecture decisions

*   **No Frontend Frameworks:** Intentional choice for simplicity, direct control, and robustness.
*   **In-Memory Processing:** All uploaded files are processed in-memory and never written to disk for security and performance.
*   **LLMs for Planning/Writing Only:** LLMs are strictly used for planning and textual tasks; numerical computations are library-backed.
*   **Dual LLM Provider Fallback:** Plagiarism & AI Reduction module uses an `auto` provider strategy, falling back between OpenAI and Google Gemini for resilience and quota management.
*   **Plagiarism Pipeline — Job + Polling (replaces NDJSON streaming):** The reducer now uses `POST /api/plagiarism/jobs` → `GET /api/plagiarism/jobs/{id}` (polled every 5s). A singleton `JobManager` (`app/services/plagiarism_jobs.py`) runs each job in a daemon thread, processing one section at a time. Per-stage 60s wall-clock timeout (with the SDK request timeout set 2s tighter so the socket actually closes — no orphaned token burn). Caps: 3 concurrent jobs, 500MB total in-memory across all jobs, 30-min TTL with lazy cleanup on every create/get. After each section completes, `original` and stage-A/B intermediates are dropped and `bytes_tracked` is recomputed from the actual retained strings. Circuit breaker: 2 consecutive timeouts abort the rest of the job. `POST /jobs/{id}/retry` re-queues only failed/timed-out sections without re-uploading. All error strings are sanitized at the serialize_job boundary defensively (never leak provider keys).
*   **Robust File Upload Handling:** Comprehensive pre-processing and error handling for uploaded documents (size caps, PDF type checks, password protection).

## Product

*   **Study Builder:** Translates research objectives into methodologies.
*   **Sample Size Calculator:** Provides formula-driven sample size estimations with advanced UX and reporting.
*   **Statistical Analysis Engine:** Guided 12-screen wizard for data input, variable classification, quality checks, and statistical analysis with client-side state persistence.
*   **Proposal Generator:** Facilitates drafting research proposals.
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