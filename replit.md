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
The frontend is built using plain HTML, CSS, and JavaScript, intentionally avoiding complex frameworks for simplicity and direct control. UI components are designed for clarity and ease of navigation, particularly in multi-step wizards. Design elements include structured forms, intuitive result displays, and clear calls to action for report generation. The landing page (`public/index.html`) features a premium product home with a warm off-white background, purple accent, and primary blue, with specific section flows for Hero, Modules, Lifecycle, Workspace, Testimonials, and About. It includes a polished 6-slide hero slider, a horizontal 6-card modules carousel with glass-effect cards, a 6-card horizontal lifecycle rail with `scroll-snap`, a Workspace section with 5 sample mockup cards, a testimonials marquee with 10 sample quotes, and a redesigned premium About section with a single-column editorial flow and a single-line tagline. Responsive design principles are applied for various screen sizes.

**Technical Implementations:**
The backend is powered by Python 3.11 with FastAPI, served by Uvicorn. Static files are served directly by FastAPI. Routing distinguishes API endpoints (`/api/*`) from static content (`artifacts/medras/public/`). All numerical computations leverage validated Python statistical libraries. LLMs are strictly used for planning and writing tasks, not for quantitative analysis.

**Feature Specifications:**

*   **Study Builder:** Translates research objectives into structured methodologies.
*   **Sample Size Calculator:** Provides formula-driven sample size estimations with 14 supported formulas, featuring objective analysis, reverse mode calculations, client-side HTML report generation, advanced UX with a three-tier entry chooser, client-side objective parser, traffic-light verdict card, complex-trial layered pipeline adjustments, and a genetic study engine.
*   **Statistical Analysis Engine:** A 12-screen guided wizard at `/analysis.html` covering data input, variable classification, quality checks, and statistical analysis. It supports Excel/CSV upload, sheet merging, detailed variable classification with issue detection and an AI-assisted Variable Assistant (no LLM). The classifier (`app/services/variable_classifier.py`) implements a four-axis **Variable Intelligence Layer** that mirrors how a real biostatistician thinks about raw data: every column is described by its `storage_type` (numeric / text / date / boolean), `statistical_nature` (continuous / discrete / ordinal / nominal / binary / datetime / identifier / free_text / empty), `interpretation` (measurement / count / validated_score / grading / binary_indicator / category / identifier / date / free_text / empty), and `analytical_flexibility` (the test families it can legitimately feed, e.g. `["continuous", "ordinal", "categorical"]` for a clinical score), plus a plain-English `reasoning` string. Validated clinical instruments (Harris Hip Score, SF-36, WOMAC, Oxford, MMSE, MoCA, PHQ, GAD, EDSS, ASIA, TLICS, GCS, Charlson, APACHE, SOFA, ODI, NDI, VAS, NRS, Likert, etc.) are recognised by name and tagged with the spec phrasing — *"Score-based variable with ordinal foundation and potential continuous-style analysis depending on range, distribution, and research objective."* Step 3 surfaces all four axes in the type cell: the legacy SPSS-style badge (Scale / Ordinal / …) sits on top, with the interpretation label and flexibility chips stacked below; the full reasoning is available on hover. The legacy `detected_type` and `reason` fields are preserved verbatim so all downstream consumers (test selection, recoding presets, Step 4 quality checks, encoder) keep working unchanged. On Step 3 the OPTIONAL RECODING editor for Age/BMI/Hb uses a single natural-language "Enter desired groups" text input that accepts comma-separated ranges in any common format — `<18`, `≤18`, `>40`, `≥40`, `18–30`, `18-30`, `18 to 30` — and renders a live preview of the resulting category labels. When the parsed ranges exactly match a preset's clinical defaults (e.g. BMI `<18.5, 18.5–25, 25–30, >30`), the preview restores clinical labels (Underweight / Normal / Overweight / Obese; Severe / Moderate / Mild / Normal for Hb). The Variable Assistant supports a `suggest` intent that returns dataset-aware recommendations (referencing the user's actual columns and known clinical bands) for open-ended prompts like "what should I do?" or "should I add an age coded column"; concrete actions in question form (e.g. "how do I rename age to age_yrs") still resolve to the underlying action because action intents are matched before the suggest fallback. The backend supports parametric/non-parametric tests (t-test, Mann-Whitney U, ANOVA, Kruskal-Wallis, chi-square, correlation) returning descriptives, effect sizes, variance tests, achieved power, and plain-English interpretations.
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