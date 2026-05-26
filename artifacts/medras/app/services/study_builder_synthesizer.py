"""Study Builder — distillation-based RAG synthesis pipeline.

Pipeline per question
─────────────────────
1. Per-paper sentence distillation  (keyword overlap, no API call)
2. GRADE-style evidence quality grade
3. Structured Gemini / OpenAI synthesis  (JSON, strict schema)
4. Raw-source fallback if both AI providers fail

The AI only ever sees distilled sentences, never full abstracts.
Every sentence in the answer must trace to a real sentence in a real paper.

PDF chunks (evidence_type == "uploaded_pdf") receive special treatment in
the evidence block: they are wrapped with === UPLOADED PAPER (PRIMARY SOURCE)
=== markers so the AI treats them as the researcher's primary evidence and
explicitly notes when the uploaded paper agrees with or conflicts against
the retrieved database papers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections import Counter

log = logging.getLogger(__name__)

# ── Stop words for sentence scoring ─────────────────────────────────────────
_SW: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "of", "in", "is", "are", "for", "to",
    "with", "on", "at", "by", "from", "be", "was", "were", "this", "that",
    "which", "it", "its", "as", "we", "our", "their", "there", "these",
    "those", "but", "not", "no", "has", "have", "had", "been", "were",
    "also", "than", "however", "between", "among", "after", "before",
    "results", "methods", "conclusions", "background", "objective",
    "patients", "patient", "study", "studies", "found", "showed",
})

# Statistical signal patterns — boost sentences that contain hard numbers
_STAT_PAT = re.compile(
    r"(p\s*[<=>]\s*0\.\d+|"
    r"\d+\.?\d*\s*%|"
    r"\bOR\b|\bRR\b|\bHR\b|\bNNT\b|\bARR\b|\bRRR\b|"
    r"95\s*%\s*CI|confidence interval|"
    r"odds ratio|relative risk|hazard ratio|"
    r"mean\s+difference|effect size|"
    r"significant(ly)?|p[\s-]?value)",
    re.IGNORECASE,
)

# ── Sentence distillation ────────────────────────────────────────────────────

def _question_keywords(question: str) -> frozenset[str]:
    clean = re.sub(r"[^\w\s]", " ", question.lower())
    return frozenset(w for w in clean.split() if w not in _SW and len(w) > 2)


def _distill(question: str, abstract: str, top_n: int = 4) -> list[str]:
    """Extract the *top_n* most relevant sentences from *abstract*.

    Scoring: keyword overlap with question + statistical-signal boost.
    Sentences shorter than 20 characters are skipped.

    For uploaded PDFs, the "abstract" field contains pre-retrieved chunk text
    (~2,000 words).  We apply the same scoring to surface the strongest
    sentences from those chunks rather than returning them verbatim.
    """
    if not abstract or not abstract.strip():
        return []

    q_kw = _question_keywords(question)
    raw_sents = re.split(r"(?<=[.!?])\s+(?=[A-Z])", abstract.strip())
    # secondary split on semicolons that separate independent clauses
    sents: list[str] = []
    for s in raw_sents:
        if len(s) > 200:  # long run-on — try semicolon split
            sents.extend(p.strip() for p in s.split(";") if p.strip())
        else:
            sents.append(s.strip())

    scored: list[tuple[float, str]] = []
    for sent in sents:
        if len(sent) < 20:
            continue
        s_words = frozenset(
            re.sub(r"[^\w]", "", w).lower()
            for w in sent.split()
        )
        overlap = len(q_kw & s_words)
        stat_bonus = 2.0 if _STAT_PAT.search(sent) else 0.0
        scored.append((overlap + stat_bonus, sent))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:top_n] if s]


# ── GRADE evidence quality ───────────────────────────────────────────────────

def _grade(papers: list[dict]) -> tuple[str, str]:
    """Return *(grade, explanation)* using GRADE-like logic.

    uploaded_pdf and uploaded papers do not contribute to the grade because
    they are researcher-provided and their evidence level is unknown.
    """
    counts: Counter[str] = Counter(
        p.get("evidence_type", "observational")
        for p in papers
        if p.get("evidence_type") not in ("uploaded", "uploaded_pdf")
    )
    sr  = counts["systematic_review"]
    rct = counts["rct"]
    gl  = counts["guideline"]
    obs = counts["observational"]

    if sr >= 1:
        label = "HIGH"
        n_desc = f"{sr} systematic review{'s' if sr > 1 else ''}"
        if rct:
            n_desc += f" and {rct} RCT{'s' if rct > 1 else ''}"
        expl = f"Evidence graded HIGH — based on {n_desc}."
    elif rct >= 2:
        label = "HIGH"
        expl  = f"Evidence graded HIGH — based on {rct} randomised controlled trials."
    elif rct == 1:
        label = "MODERATE"
        expl  = "Evidence graded MODERATE — 1 RCT found; supplemented by observational data."
    elif gl >= 1:
        label = "MODERATE"
        expl  = f"Evidence graded MODERATE — based on {gl} clinical guideline(s)."
    elif obs >= 3:
        label = "LOW"
        expl  = f"Evidence graded LOW — {obs} observational studies; no RCTs or reviews found."
    else:
        label = "VERY LOW"
        expl  = "Evidence graded VERY LOW — fewer than 3 relevant studies retrieved."

    return label, expl


# ── Structured synthesis ─────────────────────────────────────────────────────

_SYNTH_SYSTEM = """\
You are a brilliant medical research companion — think of yourself as Claude \
with access to verified research papers. You combine two things at once: \
(1) the warmth and clarity of a knowledgeable friend who explains things in \
plain language, and (2) the precision of a senior clinician who also gives \
the correct technical definition. Never sacrifice one for the other.

You have been given distilled evidence — sentences extracted directly from \
real research papers. Your job is to synthesise these into a complete, \
reliable, and genuinely helpful answer.

HOW TO EXPLAIN EVERY CONCEPT:
When you use any medical, statistical, or research term, always give BOTH:
  a) The plain-language meaning first — what it means in everyday words, \
using an analogy or concrete example if helpful.
  b) The technical definition — the precise clinical or statistical meaning.
Example: "sensitivity (in plain terms: how good the test is at catching real \
cases — if 100 patients actually have the disease and the test catches 90 of \
them, sensitivity is 90%; technically: the proportion of true positives \
correctly identified by the test) was 85% [1]."
Do this naturally within the flow of the answer, not as a separate glossary.

TONE:
- Conversational, warm, and direct — like Claude explaining something.
- Never use academic hedging ("it may be suggested that..."). Say what the \
evidence shows, clearly.
- If the evidence is strong and clear, say so. If it is weak or conflicting, \
explain why in plain terms.
- Use concrete numbers and comparisons rather than abstract statements.

ACCURACY RULES — strictly enforced:
1. Every factual statement must cite at least one source by its number [N].
2. Never invent statistics, p-values, effect sizes, drug doses, or clinical \
conclusions. If the evidence does not support a claim, do not make it.
3. If evidence is conflicting, explicitly name both sides in contradictions[].
4. next_questions must be the natural next thing a curious clinician or \
researcher would actually want to know — not generic advice.
5. Keep summary to 2–3 sentences maximum.
6. Any source marked "=== UPLOADED PAPER (PRIMARY SOURCE) ===" is a paper \
the researcher directly provided. Treat it as primary evidence, cite it \
where relevant, and explicitly note when it agrees with or conflicts against \
the database sources.

=== BEGIN DISTILLED EVIDENCE ===
{evidence}
=== END DISTILLED EVIDENCE ===

Conversation history (for context only — do not cite from it):
{history}

Return ONLY valid JSON matching this exact schema — no markdown, no extra keys:
{{
  "summary": "2-3 sentence direct answer citing sources",
  "key_findings": [
    {{"finding": "specific finding", "sources": [1, 2]}}
  ],
  "what_agrees": "what all sources consistently show",
  "what_is_debated": "areas of uncertainty or conflicting findings (write N/A if none)",
  "contradictions": ["Paper [N] found X while paper [M] found Y"],
  "limitations": "key limitations of this body of evidence",
  "next_questions": ["specific follow-up question 1", "specific follow-up question 2", "specific follow-up question 3"]
}}
"""


def _evidence_block(papers: list[dict], distilled: dict[int, list[str]]) -> str:
    """Build the distilled evidence block for the synthesis prompt.

    Papers with evidence_type == "uploaded_pdf" are wrapped with
    === UPLOADED PAPER (PRIMARY SOURCE) === markers so the AI treats them
    as primary evidence and relates them explicitly to the database results.
    """
    lines: list[str] = []
    for i, p in enumerate(papers, 1):
        authors  = ", ".join(p.get("authors") or []) or "Authors unknown"
        journal  = p.get("journal", "")
        year     = p.get("year", "")
        url      = p.get("url", "")
        ev_type  = p.get("evidence_type", "")
        excerpts = distilled.get(i, [])

        is_pdf = (ev_type == "uploaded_pdf")

        if is_pdf:
            ev_label = "PRIMARY SOURCE — researcher-uploaded document"
        elif ev_type == "uploaded":
            ev_label = "researcher-uploaded document"
        else:
            ev_label = ev_type or "unknown"

        pages_str = ""
        if is_pdf and p.get("pages_used"):
            pages_str = " Source sections: " + ", ".join(p["pages_used"]) + "."

        header = (
            f"[{i}] {authors}. \"{p.get('title', 'Untitled')}\". "
            f"{journal} ({year}). URL: {url}. "
            f"Study type: {ev_label}.{pages_str}"
        )

        if excerpts:
            excerpt_text = " | ".join(excerpts)
            entry = f"{header}\n    Relevant excerpts: {excerpt_text}"
        else:
            fallback = (p.get("abstract") or "")[:300]
            entry = f"{header}\n    Abstract (truncated): {fallback}"

        if is_pdf:
            entry = (
                "=== UPLOADED PAPER (PRIMARY SOURCE) ===\n"
                + entry
                + "\n=== END UPLOADED PAPER ==="
            )

        lines.append(entry)

    return "\n\n".join(lines)


def _build_answer_text(structured: dict, papers: list[dict]) -> str:
    """Convert structured JSON into a readable markdown string (backward compat)."""
    parts: list[str] = []

    summary = structured.get("summary", "")
    if summary:
        parts.append(summary)

    findings = structured.get("key_findings") or []
    if findings:
        parts.append("\n**Key findings:**")
        for f in findings:
            srcs = f.get("sources") or []
            cite = "".join(f"[{s}]" for s in srcs)
            parts.append(f"- {f.get('finding', '')} {cite}")

    agrees = structured.get("what_agrees", "")
    if agrees and agrees.upper() != "N/A":
        parts.append(f"\n**Evidence agrees:** {agrees}")

    debated = structured.get("what_is_debated", "")
    if debated and debated.upper() != "N/A":
        parts.append(f"\n**Still debated:** {debated}")

    contradictions = structured.get("contradictions") or []
    if contradictions:
        parts.append("\n**Conflicting findings:**")
        for c in contradictions:
            parts.append(f"- {c}")

    limitations = structured.get("limitations", "")
    if limitations:
        parts.append(f"\n**Limitations of this evidence:** {limitations}")

    # Reference list
    if papers:
        parts.append("\n**References:**")
        for i, p in enumerate(papers, 1):
            authors = ", ".join(p.get("authors") or [])
            parts.append(
                f"[{i}] {authors}. {p.get('title', '')}. "
                f"{p.get('journal', '')} ({p.get('year', '')}). "
                f"{p.get('url', '')}"
            )

    return "\n".join(parts)


def _call_gemini_sync(system: str, user: str) -> dict | None:
    """Synchronous Gemini call — must be run via asyncio.to_thread."""
    try:
        from app.services.llm_client import get_gemini_client
        from google.genai import types as gtypes

        gc   = get_gemini_client()
        resp = gc.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{system}\n\nQuestion: {user}",
            config=gtypes.GenerateContentConfig(
                max_output_tokens=2000,
                temperature=0.1,
            ),
        )
        raw = (resp.text or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$",        "", raw)
        return json.loads(raw)
    except Exception as exc:
        log.warning("Gemini synthesis failed: %s", exc)
        return None


def _call_openai_sync(system: str, user: str) -> dict | None:
    """Synchronous OpenAI call — must be run via asyncio.to_thread.

    Uses GPT-4o for high-quality academic synthesis.
    """
    try:
        from app.services.llm_client import get_openai_client

        oai  = get_openai_client()
        resp = oai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": f"Question: {user}"},
            ],
            max_tokens=2000,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "").strip()
        return json.loads(raw)
    except Exception as exc:
        log.warning("OpenAI synthesis failed: %s", exc)
        return None


# ── Public entry point ───────────────────────────────────────────────────────

async def synthesize(
    question: str,
    papers: list[dict],
    history: list[dict],
) -> dict:
    """Full distillation → grading → synthesis pipeline.

    Returns a dict with keys:
    ``answer``, ``key_findings``, ``what_agrees``, ``what_is_debated``,
    ``contradictions``, ``limitations``, ``evidence_grade``,
    ``evidence_grade_explanation``, ``suggested_questions``, ``method``.
    """
    if not papers:
        return {
            "answer": (
                "No relevant published papers were found for this question. "
                "Please refine your search terms or consult a specialist database directly."
            ),
            "key_findings": [], "what_agrees": "", "what_is_debated": "",
            "contradictions": [], "limitations": "",
            "evidence_grade": "VERY LOW",
            "evidence_grade_explanation": "No papers retrieved.",
            "suggested_questions": [], "method": "no_papers",
        }

    # Step 1 — per-paper distillation (pure Python, fast)
    distilled: dict[int, list[str]] = {}
    kept_papers: list[dict] = []
    kept_index  = 0
    for p in papers:
        sents = _distill(question, p.get("abstract") or "", top_n=4)
        kept_index += 1
        distilled[kept_index] = sents
        kept_papers.append(p)

    # Step 2 — GRADE evidence quality (excludes uploaded papers)
    grade, grade_expl = _grade(kept_papers)

    # Step 3 — build evidence block and history string
    evidence_block = _evidence_block(kept_papers, distilled)
    history_text   = (
        "\n".join(f"Q: {t['question']}\nA: {t['answer_summary']}" for t in history)
        if history else "No prior conversation."
    )

    synth_system = _SYNTH_SYSTEM.format(
        evidence=evidence_block,
        history=history_text,
    )

    # Step 4 — structured AI synthesis
    # Gemini 2.5 Flash PRIMARY: excels at academic evidence synthesis with
    # long-context reading of distilled excerpts.
    # GPT-4o FALLBACK: strong structured JSON fidelity when Gemini is unavailable.
    structured = await asyncio.to_thread(_call_gemini_sync, synth_system, question)
    method = "gemini-2.5-flash"

    if not structured:
        log.info("Gemini synthesis unavailable — trying GPT-4o fallback")
        structured = await asyncio.to_thread(_call_openai_sync, synth_system, question)
        method = "gpt-4o"

    if not structured:
        # Both providers failed — return raw sources
        raw_lines = ["AI synthesis temporarily unavailable. Retrieved sources:\n"]
        for i, p in enumerate(kept_papers[:8], 1):
            authors = ", ".join(p.get("authors") or [])
            raw_lines.append(
                f"[{i}] {authors}. {p.get('title', '')}. "
                f"{p.get('journal', '')} ({p.get('year', '')}). {p.get('url', '')}"
            )
        return {
            "answer": "\n".join(raw_lines),
            "key_findings": [], "what_agrees": "", "what_is_debated": "",
            "contradictions": [], "limitations": "",
            "evidence_grade": grade,
            "evidence_grade_explanation": grade_expl,
            "suggested_questions": [], "method": "raw_sources",
        }

    answer_text = _build_answer_text(structured, kept_papers)

    # Normalise fields that AI occasionally returns as strings instead of lists
    def _to_list(val: object) -> list:
        if isinstance(val, list):
            return [v for v in val if v and str(v).strip().upper() not in ("N/A", "NONE")]
        if isinstance(val, str) and val.strip().upper() not in ("N/A", "NONE", ""):
            return [val.strip()]
        return []

    def _to_str(val: object) -> str:
        if isinstance(val, str):
            return val if val.strip().upper() not in ("N/A", "NONE") else ""
        return ""

    # key_findings: each item should be {finding, sources} — coerce plain strings too
    raw_kf = structured.get("key_findings") or []
    key_findings: list[dict] = []
    for item in (raw_kf if isinstance(raw_kf, list) else []):
        if isinstance(item, dict):
            key_findings.append(item)
        elif isinstance(item, str) and item.strip():
            key_findings.append({"finding": item.strip(), "sources": []})

    return {
        "answer":                   answer_text,
        "key_findings":             key_findings,
        "what_agrees":              _to_str(structured.get("what_agrees")),
        "what_is_debated":          _to_str(structured.get("what_is_debated")),
        "contradictions":           _to_list(structured.get("contradictions")),
        "limitations":              _to_str(structured.get("limitations")),
        "evidence_grade":           grade,
        "evidence_grade_explanation": grade_expl,
        "suggested_questions":      _to_list(structured.get("next_questions")),
        "method": method,
    }
