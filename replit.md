# MedRAS — Medical Research Acceleration System

## Overview

MedRAS is a structured Research Operating System designed to support medical, biomedical, and academic researchers throughout the entire research lifecycle. Its primary purpose is to guide users from initial research objectives to submission-ready manuscripts through a series of integrated modules. Key capabilities include study design, sample size determination, statistical analysis, proposal generation, manuscript writing, and plagiarism/compliance checks. The project aims to accelerate medical research by providing a comprehensive, user-friendly platform that streamlines complex processes and ensures scientific rigor.

## User Preferences

*   I want iterative development.
*   Ask before making major changes.
*   Do not make changes to files outside the `artifacts/medras/` directory.
*   Do not make changes to `.replit-artifact/artifact.toml`.
*   Ensure all statistical computations are library-backed and never rely on LLMs for numerical results.
*   Prioritize in-memory processing for all uploaded files; never write them to disk.
*   Restrict logging to operational metadata only (route, status, duration, sizes, error types); never log document content.
*   Never expose API keys to the frontend.

## System Architecture

MedRAS employs a minimalist architecture for robustness and performance.

**UI/UX Decisions:**
The frontend is built using plain HTML, CSS, and JavaScript, intentionally avoiding complex frameworks for simplicity and direct control. UI components are designed for clarity and ease of navigation, particularly in multi-step wizards. Design elements include structured forms, intuitive result displays, and clear calls to action for report generation. The landing page features an interactive circle-and-spoke "orbit" infographic for the six core modules: small node circles that expand on hover/focus to reveal title, description, and CTA, then click navigates to the module. Available modules glow blue; planned modules are inert (anchor activation blocked via JS). On touch / coarse-pointer devices and screens ≤ 720px, the orbit collapses into an always-expanded stacked card list to avoid hover dependency.

**Technical Implementations:**
The backend is powered by Python 3.11 with FastAPI, served by Uvicorn. Static files are served directly by FastAPI. Routing distinguishes API endpoints (`/api/*`) from static content (`artifacts/medras/public/`). All numerical computations leverage validated Python statistical libraries (`scipy.stats`, `statsmodels`, `lifelines`, pandas, numpy, etc.). LLMs are strictly used for planning and writing tasks, not for quantitative analysis.

**Feature Specifications:**

*   **Study Builder:** Translates research objectives into structured methodologies.
*   **Sample Size Calculator:** Provides formula-driven sample size estimations with 14 supported formulas (descriptive, comparative, longitudinal, correlation, survival, modeling, agreement/diagnostic). Features objective analysis (LLM-assisted or rule-based), reverse mode calculations, client-side HTML report generation, and advanced UX features like a three-tier entry chooser, client-side objective parser, traffic-light verdict card, complex-trial layered pipeline adjustments (composite outcomes, repeated measures, multicentre design effects, adaptive α-spending), and a genetic study engine with specialized sub-types. The Step 3 result page uses a clean two-card hero ("Expected sample size" vs "Significant sample size", side by side and bold), a single Formula breakdown card (formula expression + inputs + constants tables), a slim verdict banner, all secondary panels (recommended formula, comparison, auto-filled defaults, notes, genetic checklist, detected chips) collapsed inside a single `<details class="result-advanced">` disclosure, and a clean action bar with a "Back to MedRAS home" link on the left and a primary blue download-icon button on the right. When the researcher leaves Expected n blank, the Expected card shows a friendly "Not provided" + hint instead of a bare em-dash. The hero's expected_sample_size is stamped onto the result inside `postProcess()` so it survives both the client-compute and server-fetch paths.
*   **Statistical Analysis Engine:** A 12-screen guided wizard at `/analysis.html`. The top step navigator shows all 12 numbered circles with concise labels (Start, Data input, Variables, Quality, Missing, Objective, Assign, Normality, Plan, Run, Results, Export); future steps are visually muted but no longer carry a "soon" badge. Pass 1 ships screens 1 (entry chooser: "I have an Excel file" or "I want to generate practice sheet"), a 5-step branching intake wizard (Q1 = choice cards "study proposal" vs "objective + sample size", Q2 = either a file dropzone that uploads PDF/DOCX/PPTX/TXT to `/api/stats/upload-proposal` returning a `proposal_id`, or paired objective + numeric sample-size inputs, Q3 = outcome variable(s) in plain English, Q4 = independent variable(s) in plain English, Q5 = optional special instructions; the choice + payload is persisted on the dataset entry and re-synced into client state by `ingestDataset`), 2A (Excel/CSV upload up to 8 MB), 2C (practice templates: anaemia / diabetes / hypertension / RCT), file-preview confirmation (redesigned into 4 stacked zones: **Zone 1** file-summary metric cards (rows / variables / sheets / filename), **Zone 2** "How is your data arranged?" — two big choice cards "One sheet only" vs "Combine sheets" (auto-hidden for single-sheet files), **Zone 3** merge configuration (only visible when "Combine sheets" is picked) with one checkbox per sheet, an amber warning that auto-unchecks blank sheets when the backend reports them, and a "Merge selected sheets" button hitting `/api/stats/combine-sheets` (which stacks rows and optionally adds a `Group` column whose cells render as small coloured chips in the preview), and **Zone 4** the preview table itself with header-numeric warning, repeated-ID follow-up prompt, and a green "Ready" banner; the Confirm button stays disabled until a preview is actually showing. The merge choice is auto-selected when the intake instructions hint at merging.), 3 (variable classification with 7 types: scale, ordinal, nominal, discrete, date, id, exclude), and 4 (data quality: clinical-bound checks, exact/ID duplicates, logical consistency). Screens 2B (form builder) and 5+ are stubbed for later passes. The Excel loader auto-falls-forward to the first non-empty sheet on upload, returns named errors ("Sheet 'X' looks blank") for blank sheets, silently skips blanks during merge, and surfaces `skipped_blank_sheets` on the response. The page exposes a self-test mode at `/analysis.html?autotest=1` that walks the full Pass 1 flow end-to-end. Backend supports parametric/non-parametric tests (t-test, Mann-Whitney U, ANOVA, Kruskal-Wallis, chi-square, correlation) returning descriptives, effect sizes, variance tests, achieved power, and plain-English interpretations.
*   **Proposal Generator:** Facilitates drafting research proposals for various institutions.
*   **Thesis & Article Writer:** Assists in compiling structured manuscripts and dissertation chapters.
*   **Plagiarism & Compliance:** Offers originality scoring and citation verification.

**System Design Choices:**
Each module is designed with its own API router and UI components for modularity. An in-memory LRU cache is used for dataset storage in the Statistical Analysis Engine, ensuring efficient processing without disk I/O. Configuration is managed via environment variables for flexibility.

## External Dependencies

*   **OpenAI API:** Used for LLM-driven planning and writing tasks in Modules 1, 4, 5, and for objective analysis in the Sample Size Calculator (if `OPENAI_API_KEY` is set).
*   **Copyleaks API:** Integrated for plagiarism scoring in Module 6 (requires `COPYLEAKS_EMAIL` and `COPYLEAKS_API_KEY`).
*   **Python Libraries:**
    *   `FastAPI`, `Uvicorn`: Backend web framework and server.
    *   `pandas`, `numpy`, `scipy`, `statsmodels`, `scikit-learn`, `lifelines`, `pingouin`, `scikit-posthocs`, `missingno`: Core statistical and data manipulation libraries.
    *   `reportlab`, `xlrd`: For report generation and Excel file handling.
    *   `slowapi`: For rate limiting API requests.
*   **Frontend Libraries:** No external JavaScript frameworks are used; utilizes standard browser APIs.