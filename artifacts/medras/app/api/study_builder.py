"""Study Builder API — Medical Knowledge Assistant.

POST /api/study-builder/ask
  1. PICO decomposition  → optimised search queries
  2. Multi-query parallel search across 16 databases
  3. Per-paper sentence distillation  (keyword overlap, no extra API call)
  4. GRADE evidence quality grade
  5. Structured AI synthesis  (JSON, every claim traced to a real sentence)
  6. Conversation session update

POST /api/study-builder/upload-paper
  Upload a PDF / DOCX / TXT paper to anchor in the conversation.
  The extracted text is stored in the session and injected into every
  subsequent synthesis call as a researcher-provided evidence source.

POST /api/study-builder/upload-pdf
  Upload a PDF with intelligent chunking (400 words/chunk, 50-word overlap).
  Only the top-5 most relevant chunks (TF-IDF keyword overlap) reach the AI
  per question — never the full document — so 40-page papers work correctly.

DELETE /api/study-builder/upload-pdf
  Remove the uploaded PDF from the session to free memory.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.services.plagiarism_analyzer import (
    UploadExtractionError,
    extract_text_from_upload,
)
from app.services.study_builder_pico        import decompose
from app.services.study_builder_search      import multi_source_search
from app.services.study_builder_synthesizer import synthesize
from app.services.study_builder_pdf_chunker import chunk_pdf, retrieve_top_chunks
from app.services import study_builder_session as sessions

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/study-builder", tags=["study-builder"])

_DISCLAIMER = (
    "This information is for educational and research purposes only and is "
    "based on published literature. Clinical decisions must involve a qualified "
    "healthcare professional."
)

_MAX_UPLOAD_BYTES  = 20 * 1024 * 1024   # 20 MB — general upload-paper
_MAX_PDF_BYTES     = 10 * 1024 * 1024   # 10 MB — upload-pdf (chunked)
_ALLOWED_EXTS      = {".pdf", ".docx", ".txt"}
_MAX_UPLOADED_TEXT = 6000               # chars sent to synthesis per general paper
_PDF_TOP_CHUNKS    = 5                  # chunks retrieved per question


# ── Request / Response models ────────────────────────────────────────────────

class AskRequest(BaseModel):
    question:   str            = Field(..., min_length=3, max_length=1500)
    session_id: Optional[str]  = Field(None, description="Omit to start a new session")


class KeyFinding(BaseModel):
    finding: str
    sources: list[int] = []


class AskResponse(BaseModel):
    # Core answer (structured)
    answer:               str
    key_findings:         list[KeyFinding]
    what_agrees:          str
    what_is_debated:      str
    contradictions:       list[str]
    limitations:          str

    # Evidence quality
    evidence_grade:             str   # HIGH | MODERATE | LOW | VERY LOW
    evidence_grade_explanation: str

    # Session
    session_id: str

    # Sources
    papers:           list[dict]
    sources_searched: list[str]
    total_found:      int

    # Follow-ups (AI-generated, not hardcoded)
    suggested_questions: list[str]
    action_buttons:      list[dict]

    # Meta
    synthesis_method:   str
    question_type:      str
    pico:               dict
    uploaded_count:     int = 0       # how many papers/PDFs were attached this session
    disclaimer:         str = _DISCLAIMER


class UploadResponse(BaseModel):
    session_id:  str
    filename:    str
    word_count:  int
    preview:     str   # first ~300 chars of extracted text
    paper_index: int   # 1-based index within this session


class PdfUploadResponse(BaseModel):
    session_id:  str
    filename:    str
    title:       str
    page_count:  int
    chunk_count: int


# ── Helpers ──────────────────────────────────────────────────────────────────

_STATS_KW    = {"sample size", "power", "statistical", "regression", "p-value",
                "confidence interval", "odds ratio", "anova", "t-test"}
_RESEARCH_KW = {"study", "studies", "evidence", "trial", "efficacy", "effectiveness",
                "outcome", "compare", "association", "risk", "systematic", "meta-analysis",
                "cohort", "rct", "prevalence", "incidence", "published", "literature", "review"}
_CLINICAL_KW = {"treatment", "manage", "management", "dose", "drug", "prescribe",
                "patient", "diagnosis", "therapy", "clinical", "symptoms",
                "guidelines", "protocol", "medication"}


def _classify(q: str) -> str:
    lower = q.lower()
    if any(k in lower for k in _STATS_KW):
        return "statistics"
    words = set(lower.split())
    if words & _RESEARCH_KW:
        return "research"
    if words & _CLINICAL_KW:
        return "clinical"
    return "research"


def _action_buttons(qtype: str) -> list[dict]:
    btns: list[dict] = [
        {"label": "Calculate sample size", "action": "sample_size",
         "url": "/sample-size.html", "external": False},
    ]
    if qtype == "research":
        btns.insert(0, {"label": "Design a study on this", "action": "design_study",
                        "url": "/study-builder/design.html", "external": False})
    elif qtype == "clinical":
        btns.insert(0, {"label": "Search ClinicalTrials.gov", "action": "find_trials",
                        "url": "https://clinicaltrials.gov/search", "external": True})
    btns.append({"label": "Take to Proposal Writer", "action": "proposal",
                 "url": "/proposal-module/", "external": False})
    return btns


async def _search_all_queries(queries: list[str], top_n: int = 12) -> dict:
    """Run each PICO query in parallel, merge and deduplicate results."""
    if len(queries) == 1:
        return await multi_source_search(queries[0], top_n=top_n)

    tasks   = [multi_source_search(q, top_n=8) for q in queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    merged_papers: list[dict]   = []
    seen_titles:   set[str]     = set()
    all_sources:   set[str]     = set()
    total_found    = 0

    for r in results:
        if isinstance(r, Exception):
            log.warning("Search query failed: %s", r)
            continue
        total_found += r.get("total_found", 0)
        all_sources.update(r.get("sources_searched", []))
        for p in r.get("papers", []):
            key = (p.get("title") or "").strip().lower()[:80]
            if key and key not in seen_titles:
                seen_titles.add(key)
                merged_papers.append(p)

    merged_papers.sort(key=lambda p: p.get("citation_count", 0), reverse=True)
    merged_papers = merged_papers[:top_n]

    return {
        "papers":           merged_papers,
        "sources_searched": sorted(all_sources),
        "total_found":      total_found,
    }


def _build_uploaded_paper_dict(up: dict) -> dict:
    """Convert a session-stored uploaded paper into a paper dict for synthesis."""
    text = up.get("text", "")
    return {
        "title":          up.get("filename", "Uploaded document"),
        "authors":        ["Researcher-provided"],
        "abstract":       text[:_MAX_UPLOADED_TEXT],
        "year":           "",
        "journal":        "Uploaded document",
        "url":            "",
        "source":         "uploaded",
        "evidence_type":  "uploaded",
        "open_access":    False,
        "citation_count": 0,
    }


def _build_pdf_paper_dict(meta: dict, top_chunks: list[dict]) -> dict:
    """Build a synthesis paper dict from the top-ranked PDF chunks.

    Chunks are sorted by their document position (chunk_idx) so the AI
    reads them coherently rather than in relevance order.
    Page ranges are attached so the frontend can display which sections
    of the paper were used.
    """
    ordered    = sorted(top_chunks, key=lambda c: c.get("chunk_idx", 0))
    chunk_text = "\n\n".join(c["text"] for c in ordered)

    pages_used: list[str] = []
    seen: set[tuple] = set()
    for c in ordered:
        sp, ep = c.get("start_page", 1), c.get("end_page", 1)
        key = (sp, ep)
        if key not in seen:
            seen.add(key)
            pages_used.append(f"pp. {sp}–{ep}" if sp != ep else f"p. {sp}")

    return {
        "title":          meta.get("title") or meta.get("filename", "Uploaded PDF"),
        "authors":        ["Researcher-provided"],
        "abstract":       chunk_text,
        "year":           "",
        "journal":        "Uploaded document",
        "url":            "",
        "source":         "uploaded",
        "evidence_type":  "uploaded_pdf",
        "open_access":    False,
        "citation_count": 0,
        "pages_used":     pages_used,
        "page_count":     meta.get("page_count", 0),
        "filename":       meta.get("filename", ""),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/upload-paper", response_model=UploadResponse)
async def upload_paper(
    session_id: str        = Form(...),
    file:       UploadFile = File(...),
) -> UploadResponse:
    """Extract text from a PDF / DOCX / TXT and store it in the session."""
    session_id, _ = sessions.get_or_create(session_id)

    filename = file.filename or "uploaded_paper"
    ext      = os.path.splitext(filename)[1].lower()

    if ext not in _ALLOWED_EXTS:
        raise HTTPException(
            415,
            f"Unsupported file type '{ext}'. Please upload a PDF, DOCX, or TXT file.",
        )

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            413,
            f"File exceeds the 20 MB limit for paper uploads "
            f"({len(content) // 1_048_576} MB received). "
            "Please upload a smaller document.",
        )

    try:
        text = await asyncio.to_thread(extract_text_from_upload, filename, content)
    except UploadExtractionError as exc:
        raise HTTPException(422, str(exc)) from exc

    if not text or not text.strip():
        raise HTTPException(422, "Could not extract any text from this file. "
                            "It may be image-only or password-protected.")

    word_count  = len(text.split())
    paper_meta  = {"filename": filename, "text": text, "word_count": word_count}
    paper_index = sessions.add_uploaded_paper(session_id, paper_meta)

    log.info(
        "Uploaded paper [session=%s] '%s' — %d words, index=%d",
        session_id[:8], filename, word_count, paper_index,
    )

    return UploadResponse(
        session_id  = session_id,
        filename    = filename,
        word_count  = word_count,
        preview     = text[:300].strip(),
        paper_index = paper_index,
    )


@router.post("/upload-pdf", response_model=PdfUploadResponse)
async def upload_pdf(
    session_id: str        = Form(...),
    file:       UploadFile = File(...),
) -> PdfUploadResponse:
    """Upload a PDF and store it as retrievable chunks in the session.

    Only the top-5 most relevant chunks (~2,000 words) are sent to the AI
    per question, so 40-page, 20,000-word papers work correctly without
    exceeding the AI context window.

    Specific error codes:
    - 413 — file exceeds 10 MB
    - 415 — not a PDF file
    - 422 — scanned/image-only PDF, corrupted PDF, or extraction failure
    """
    session_id, _ = sessions.get_or_create(session_id)

    filename = file.filename or "uploaded.pdf"
    ext      = os.path.splitext(filename)[1].lower()

    if ext != ".pdf":
        raise HTTPException(
            415,
            "Only PDF files are supported here. Please select a .pdf file.",
        )

    content = await file.read()

    if len(content) > _MAX_PDF_BYTES:
        size_mb = len(content) / 1_048_576
        raise HTTPException(
            413,
            f"This PDF is {size_mb:.1f} MB, which exceeds the 10 MB limit. "
            "Please use a smaller file or split the PDF into sections.",
        )

    try:
        result = await asyncio.to_thread(chunk_pdf, content, filename)
    except ValueError as exc:
        # chunk_pdf raises ValueError with user-friendly messages:
        # - scanned image PDF
        # - corrupted / unreadable PDF
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        log.warning("Unexpected PDF extraction error for '%s': %s", filename, exc)
        raise HTTPException(
            422,
            "Could not process this PDF. It may be corrupted or use an "
            "unsupported encoding. Please try a different file.",
        ) from exc

    meta = {
        "filename":    filename,
        "title":       result["title"],
        "page_count":  result["page_count"],
        "total_words": result["total_words"],
    }
    sessions.set_pdf(session_id, meta, result["chunks"])

    log.info(
        "PDF upload [session=%s] '%s' — %d pages, %d words, %d chunks",
        session_id[:8], filename,
        result["page_count"], result["total_words"], len(result["chunks"]),
    )

    return PdfUploadResponse(
        session_id  = session_id,
        filename    = filename,
        title       = result["title"],
        page_count  = result["page_count"],
        chunk_count = len(result["chunks"]),
    )


@router.delete("/upload-pdf", status_code=204)
async def delete_pdf(
    session_id: str = Query(..., description="Session ID whose PDF should be cleared"),
) -> None:
    """Remove the uploaded PDF from the session to free memory."""
    sessions.clear_pdf(session_id)
    log.info("PDF cleared for session %s", session_id[:8])


@router.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest) -> AskResponse:
    question = body.question.strip()

    # 1. Session — get history and any uploaded papers
    session_id, history = sessions.get_or_create(body.session_id)
    uploaded_papers     = sessions.get_uploaded_papers(session_id)

    # 2. PICO decomposition (fast single call)
    pico = await decompose(question, history)
    log.info(
        "PICO [session=%s] P=%s I=%s C=%s O=%s queries=%s",
        session_id[:8], pico["population"], pico["intervention"],
        pico["comparison"], pico["outcome"], pico["search_queries"],
    )

    # 3. Multi-query parallel database search
    search_result = await _search_all_queries(pico["search_queries"], top_n=12)

    # 4a. Inject general uploaded papers (prepended for lowest reference numbers)
    if uploaded_papers:
        up_dicts = [_build_uploaded_paper_dict(up) for up in uploaded_papers]
        search_result["papers"] = up_dicts + search_result["papers"]
        if "uploaded" not in search_result["sources_searched"]:
            search_result["sources_searched"] = (
                ["uploaded"] + search_result["sources_searched"]
            )

    # 4b. Inject chunked PDF evidence (highest priority — inserted at position 0)
    pdf_meta, pdf_chunks = sessions.get_pdf(session_id)
    has_pdf = bool(pdf_meta and pdf_chunks)
    if has_pdf:
        top_chunks = await asyncio.to_thread(
            retrieve_top_chunks, pdf_chunks, question, _PDF_TOP_CHUNKS
        )
        if top_chunks:
            pdf_paper = _build_pdf_paper_dict(pdf_meta, top_chunks)
            search_result["papers"].insert(0, pdf_paper)
            if "uploaded_pdf" not in search_result["sources_searched"]:
                search_result["sources_searched"].insert(0, "uploaded_pdf")
            log.info(
                "PDF evidence [session=%s] '%s' → %d chunks retrieved",
                session_id[:8], pdf_meta.get("filename", "?"), len(top_chunks),
            )

    # 5. Distillation + grading + structured synthesis
    synth = await synthesize(question, search_result["papers"], history)

    # 6. Persist this turn
    answer_summary = (synth["answer"] or "")[:200].replace("\n", " ")
    sessions.add_turn(session_id, question, answer_summary)

    qtype          = _classify(question)
    uploaded_count = len(uploaded_papers) + (1 if has_pdf else 0)

    return AskResponse(
        answer               = synth["answer"],
        key_findings         = [
            KeyFinding(**f) if isinstance(f, dict) else KeyFinding(finding=str(f))
            for f in (synth.get("key_findings") or [])
        ],
        what_agrees          = synth.get("what_agrees", ""),
        what_is_debated      = synth.get("what_is_debated", ""),
        contradictions       = synth.get("contradictions") or [],
        limitations          = synth.get("limitations", ""),
        evidence_grade             = synth.get("evidence_grade", "VERY LOW"),
        evidence_grade_explanation = synth.get("evidence_grade_explanation", ""),
        session_id           = session_id,
        papers               = search_result["papers"],
        sources_searched     = search_result["sources_searched"],
        total_found          = search_result["total_found"],
        suggested_questions  = synth.get("suggested_questions") or [],
        action_buttons       = _action_buttons(qtype),
        synthesis_method     = synth.get("method", "unknown"),
        question_type        = qtype,
        pico                 = pico,
        uploaded_count       = uploaded_count,
    )
