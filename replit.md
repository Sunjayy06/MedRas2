# MedRAS — Medical Research Acceleration System

## Overview
MedRAS is a structured Research Operating System designed to support medical, biomedical, and academic researchers throughout the entire research lifecycle. Its primary purpose is to guide users from initial research objectives to submission-ready manuscripts through a series of integrated modules. Key capabilities include study design, sample size determination, statistical analysis, proposal generation, manuscript writing, and plagiarism/compliance checks. The project aims to accelerate medical research by providing a comprehensive, user-friendly platform that streamlines complex processes and ensures scientific rigor.

## User Preferences
*   I want iterative development.
*   Ask before making major changes.
*   Do not make changes to files outside the `artifacts/medras/` directory.
*   Do not make changes to `.replit-artifact/artifact.toml`.

## System Architecture

MedRAS employs a minimalist architecture for robustness and performance.

**UI/UX Decisions:**
The frontend is built using plain HTML, CSS, and JavaScript, intentionally avoiding complex frameworks for simplicity and direct control. UI components are designed for clarity and ease of navigation, particularly in multi-step wizards. Design elements include structured forms, intuitive result displays, and clear calls to action for report generation. The landing page (`public/index.html`) features a premium product home with a warm off-white background, purple accent, and primary blue, with specific section flows for Hero, Modules, Lifecycle, Workspace, Testimonials, and About. It includes a polished 6-slide hero slider, a 6-card horizontal modules carousel with glass-effect cards, a 6-card horizontal lifecycle rail with `scroll-snap`, a Workspace section with 5 sample mockup cards, a testimonials marquee with 10 sample quotes, and a redesigned premium About section with a single-column editorial flow and a single-line tagline. Responsive design principles are applied for various screen sizes.

**Technical Implementations:**
The backend is powered by Python 3.11 with FastAPI, served by Uvicorn. Static files are served directly by FastAPI. Routing distinguishes API endpoints (`/api/*`) from static content (`artifacts/medras/public/`). All numerical computations leverage validated Python statistical libraries. LLMs are strictly used for planning and writing tasks, not for quantitative analysis. Statistical computations are library-backed and never rely on LLMs for numerical results. In-memory processing is prioritized for all uploaded files, which are never written to disk. Logging is restricted to operational metadata only; document content is never logged. API keys are never exposed to the frontend.

**Feature Specifications:**

*   **Study Builder:** Translates research objectives into structured methodologies.
*   **Sample Size Calculator:** Provides formula-driven sample size estimations with 14 supported formulas, featuring objective analysis, reverse mode calculations, client-side HTML report generation, advanced UX with a three-tier entry chooser, client-side objective parser, traffic-light verdict card, complex-trial layered pipeline adjustments, and a genetic study engine.
*   **Statistical Analysis Engine:** A 12-screen guided wizard at `/analysis.html` covering data input, variable classification, quality checks, and statistical analysis. It supports Excel/CSV upload, sheet merging, detailed variable classification with issue detection and an AI-assisted Variable Assistant (no LLM). The classifier (`app/services/variable_classifier.py`) behaves like an expert biostatistician handling raw clinical data. Variables are classified based on `storage_type`, `statistical_nature`, `interpretation`, and `analytical_flexibility`, with clear reasoning. Manual or assistant overrides re-enrich these four axes. An optional recoding editor for variables like Age/BMI/Hb accepts natural-language ranges and renders live previews. The Variable Assistant supports dataset-aware recommendations. The backend supports parametric/non-parametric tests (t-test, Mann-Whitney U, ANOVA, Kruskal-Wallis, chi-square, correlation) returning descriptives, effect sizes, variance tests, achieved power, and plain-English interpretations. A quality check (`app/services/data_quality.py`) combines logical/date errors with categorical-consistency checks, and provides a composite quality score based on missingness, outliers, duplicate rows, and consistency errors. Session state is persisted to `localStorage` for resumable sessions. The workflow is structured into 8 steps: Start, Data input, Variables, Review data, Normality, Plan and Run, Results, Export. Step 2 offers two practice-data paths in addition to file upload: ready-made templates (anaemia/etc.) and an inline 4-question "Build your own practice dataset" wizard (Q1 variables list → Q2 patient count → Q3 smart per-variable types/ranges → Q4 optional expected effect). The preview screen (Step 2) tracks `state.dataSource` ("upload" | "template" | "custom") and renders practice-only extras when the dataset is dummy/wizard-built: 10-row preview, a Step-3 reassurance note, "Download as Excel" button, and (for custom only) a "Regenerate with changes" shortcut back into the inline wizard.
*   **Proposal Generator:** Facilitates drafting research proposals for various institutions.
*   **Thesis & Article Writer:** Assists in compiling structured manuscripts and dissertation chapters.
*   **Plagiarism & Compliance:** Offers originality scoring and citation verification.

**System Design Choices:**
Each module is designed with its own API router and UI components for modularity. An in-memory LRU cache is used for dataset storage in the Statistical Analysis Engine, ensuring efficient processing without disk I/O. Configuration is managed via environment variables for flexibility.

## External Dependencies

*   **OpenAI API:** Used for LLM-driven planning and writing tasks in Study Builder, Thesis & Article Writer, Proposal Generator, and for objective analysis in the Sample Size Calculator.
*   **Copyleaks API:** Integrated for plagiarism scoring in Plagiarism & Compliance module.
*   **Python Libraries:**
    *   `FastAPI`, `Uvicorn`: Backend web framework and server.
    *   `pandas`, `numpy`, `scipy`, `statsmodels`, `scikit-learn`, `lifelines`, `pingouin`, `scikit-posthocs`, `missingno`: Core statistical and data manipulation libraries.
    *   `reportlab`, `xlrd`: For report generation and Excel file handling.
    *   `slowapi`: For rate limiting API requests.
*   **Frontend Libraries:** No external JavaScript frameworks are used; utilizes standard browser APIs.