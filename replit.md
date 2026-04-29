# MedRAS — Medical Research Acceleration System

## Overview

MedRAS is a structured Research Operating System for medical, biomedical, and academic researchers. It guides users from research objective to submission-ready manuscript through six core modules:

1. **Study Builder** — translates a research objective into a structured methodology
2. **Sample Size Calculator** — formula-driven sample size estimation
3. **Statistical Analysis Engine** — Excel data ingestion and parametric/non-parametric testing
4. **Proposal Generator** — ICMR / institutional / university proposal drafting
5. **Thesis & Article Writer** — structured manuscript and dissertation chapter compilation
6. **Plagiarism & Compliance** — originality scoring and citation verification

## Architecture

- **Backend:** Python 3.11 + FastAPI, served by Uvicorn on port 8000.
- **Frontend:** Plain HTML / CSS / JavaScript served as static files by FastAPI itself. No React, Vite, or other framework — kept intentionally simple per the product brief.
- **Routing:** `/api/*` paths are handled by FastAPI route handlers; everything else is served from `artifacts/medras/public/`.
- **Statistics:** All numerical computation is done by validated Python libraries (`scipy.stats`, `statsmodels`, `lifelines` planned). LLMs are used for planning and writing only — never for numerical results.

## Project Structure

```
artifacts/medras/
├── .replit-artifact/artifact.toml   # service config (do not edit directly)
├── main.py                          # FastAPI entry point
├── requirements.txt                 # Python deps
├── app/
│   ├── api/                         # API routers, one file per module
│   │   ├── __init__.py              # aggregate router
│   │   └── health.py                # /healthz, /readyz
│   └── core/
│       ├── config.py                # env-backed settings
│       ├── limiter.py               # slowapi rate limiter
│       └── logging.py               # structured logging setup
└── public/
    ├── index.html                   # landing page
    ├── css/style.css
    └── js/app.js
```

Each new module gets its own router file under `app/api/<module>.py` and is mounted in `app/api/__init__.py`. Each new module's UI gets its own HTML file under `public/<module>.html`.

## Modules Implemented

- **Foundation only.** Landing page, health endpoints, and architectural scaffolding for all six modules. No module-specific functionality has been built yet.

## Environment Variables

Configured via Replit Secrets. The app starts even without these but the corresponding modules will be disabled.

- `OPENAI_API_KEY` — required for Modules 1, 4, 5 (LLM-driven planning and writing)
- `COPYLEAKS_EMAIL` and `COPYLEAKS_API_KEY` — required for Module 6 (plagiarism scoring)

## Running

The artifact runs automatically via the `MedRAS Web` workflow. It can be reached at the workspace preview root (`/`).

- Local API: `http://localhost:80/api/healthz`
- Local UI: `http://localhost:80/`

## Operational Rules

- **Never log document content.** Logging is restricted to operational metadata only (route, status, duration, sizes, error types).
- **Never expose API keys to the frontend.** `/api/readyz` returns booleans only.
- **Statistical computation is library-backed.** No statistics may be computed by LLMs.
- **Files are processed in memory.** No uploaded document is written to disk.
