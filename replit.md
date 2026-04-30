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
*   **Sample Size Calculator:** Provides formula-driven sample size estimations with 14 supported formulas (descriptive, comparative, longitudinal, correlation, survival, modeling, agreement/diagnostic). Features objective analysis (LLM-assisted or rule-based), reverse mode calculations, client-side HTML report generation, and advanced UX features like a three-tier entry chooser, client-side objective parser, traffic-light verdict card, complex-trial layered pipeline adjustments (composite outcomes, repeated measures, multicentre design effects, adaptive α-spending), and a genetic study engine with specialized sub-types.
*   **Statistical Analysis Engine:** Supports Excel/CSV data ingestion (up to 8 MB), variable classification, dummy data generation, and various parametric/non-parametric tests (t-test, Mann-Whitney U, ANOVA, Kruskal-Wallis, chi-square, correlation). Returns descriptives, effect sizes, variance tests, achieved power, and plain-English interpretations.
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