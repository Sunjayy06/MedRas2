# MedRAS

MedRAS is a structured Research Operating System that guides medical and academic researchers from objectives to submission-ready manuscripts.

## Run & Operate

*   `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`: Run the FastAPI application.
*   `python -m pytest`: Run tests.
*   **Required Env Vars:** `OPENAI_API_KEY`, `GEMINI_API_KEY`, `COPALEAKS_API_KEY`.

## Stack

*   **Backend:** Python 3.11, FastAPI, Uvicorn
*   **Frontend:** HTML, CSS, JavaScript (no frameworks)
*   **ORM:** _Populate as you build_
*   **Validation:** Pydantic
*   **Build Tool:** _Populate as you build_

## Where things live

*   `/app`: Backend Python source code (API endpoints, services).
*   `/public`: Frontend static files (HTML, CSS, JS) for various modules.
*   `/artifacts/medras`: Files that should not be modified.
*   **DB Schema:** _Populate as you build_
*   **API Contracts:** Implicitly defined by FastAPI Pydantic models.
*   **Theme Files:** `/public/css/style.css`.

## Architecture decisions

*   **No Frontend Frameworks:** Intentional choice for simplicity and direct control.
*   **In-Memory Processing:** All uploaded files are processed in-memory for security and performance.
*   **LLMs for Planning/Writing Only:** LLMs are strictly used for planning and textual tasks; numerical computations are library-backed.
*   **Dual LLM Provider Fallback:** Plagiarism & AI Reduction module uses an `auto` provider strategy, falling back between OpenAI and Google Gemini for resilience.
*   **Smart RAG Infrastructure:** Includes services for domain routing, guideline retrieval, and asynchronous fan-out external database querying for research papers.
*   **Proposal Writing Module State Management:** Uses `sessionStorage` mirrored to `localStorage` for auto-save, mobile responsiveness, and a `beforeunload` guard for in-flight operations.
*   **Plagiarism Pipeline Job Management:** Uses a `JobManager` for daemon thread processing, per-stage timeouts, and circuit breakers, replacing NDJSON streaming with polling.

## Product

*   **Study Builder:** Translates research objectives into methodologies.
*   **Sample Size Calculator:** Provides formula-driven sample size estimations.
*   **Statistical Analysis Engine:** Guided wizard for data input, variable classification, quality checks, and statistical analysis.
*   **Proposal Writing Module:** Guided 8-step intake (Role → Language → Format → Outline → References → Generate → Preview → Download) supporting various academic formats.
*   **Thesis & Article Writer:** Assists in compiling structured manuscripts.
*   **Plagiarism & AI Reduction:** Offers originality scoring, AI likelihood detection, and a 3-stage rewrite pipeline.

## User preferences

*   I want iterative development.
*   Ask before making major changes.
*   Do not make changes to files outside the `artifacts/medras/` directory.
*   Do not make changes to `.replit-artifact/artifact.toml`.

## Gotchas

*   Uploaded files are subject to 100 MB byte cap and 200-page PDF cap.
*   Plagiarism module's rewrite pipeline automatically skips References/Bibliography sections.
*   Quota exhaustion for LLM providers will lead to temporary service unavailability for plagiarism rewrites.

## Pointers

*   [FastAPI Documentation](https://fastapi.tiangolo.com/)
*   [Pandas Documentation](https://pandas.pydata.org/docs/)
*   [OpenAI API Documentation](https://platform.openai.com/docs/)
*   [Google Gemini API Documentation](https://ai.google.dev/docs)
*   [Uvicorn Documentation](https://www.uvicorn.org/)