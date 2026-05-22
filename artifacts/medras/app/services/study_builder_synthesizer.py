"""Study Builder — AI answer synthesiser (GPT-4o-mini → Gemini → raw fallback)."""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_SYSTEM = """\
You are a medical research assistant for MedRAS.
Answer the user's question using ONLY the research papers provided below.

STRICT RULES:
1. Cite every factual statement with square-bracket source numbers, e.g. [1] or [1,3].
2. Never add information not present in the provided documents.
3. If the documents are insufficient to answer reliably, respond with this sentence only:
   "The available published evidence is insufficient to answer this question reliably. \
Please consult a qualified clinical specialist or conduct a targeted database search."
4. Keep your answer under 400 words.
5. End with a "References" section: [N] Authors. Title. Journal. Year. URL
6. Use calm, precise academic English.
7. Never fabricate p-values, effect sizes, dosages, or clinical conclusions.

=== BEGIN UNTRUSTED RESEARCH EVIDENCE ===
{evidence}
=== END UNTRUSTED RESEARCH EVIDENCE ===
"""


def _evidence_block(papers: list[dict]) -> str:
    lines = []
    for i, p in enumerate(papers, 1):
        authors  = ", ".join(p.get("authors") or []) or "Authors unknown"
        abstract = (p.get("abstract") or "No abstract available.")[:700]
        lines.append(
            f"[{i}] {authors}. \"{p.get('title', 'Untitled')}\". "
            f"{p.get('journal', '')} ({p.get('year', '')}).\n"
            f"    URL: {p.get('url', '')}\n"
            f"    Abstract: {abstract}"
        )
    return "\n\n".join(lines)


async def synthesize_answer(question: str, papers: list[dict]) -> dict:
    if not papers:
        return {
            "answer": ("No relevant published papers were found for this question. "
                       "Please refine your search terms or consult a specialist database directly."),
            "method": "no_papers", "error": None,
        }

    evidence = _evidence_block(papers)
    system   = _SYSTEM.format(evidence=evidence)

    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        try:
            from openai import AsyncOpenAI
            oai  = AsyncOpenAI(api_key=openai_key)
            resp = await oai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": system},
                          {"role": "user",   "content": question}],
                max_tokens=800, temperature=0.15,
            )
            answer = (resp.choices[0].message.content or "").strip()
            if answer:
                return {"answer": answer, "method": "gpt-4o-mini", "error": None}
        except Exception as exc:
            log.warning("OpenAI synthesis failed: %s", exc)

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        try:
            from google import genai
            from google.genai import types as gtypes
            gc   = genai.Client(api_key=gemini_key)
            resp = gc.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"{system}\n\nQuestion: {question}",
                config=gtypes.GenerateContentConfig(max_output_tokens=800, temperature=0.15),
            )
            answer = (resp.text or "").strip()
            if answer:
                return {"answer": answer, "method": "gemini", "error": None}
        except Exception as exc:
            log.warning("Gemini synthesis failed: %s", exc)

    lines = ["AI synthesis is temporarily unavailable. Most relevant sources retrieved:\n"]
    for i, p in enumerate(papers[:6], 1):
        authors = ", ".join(p.get("authors") or [])
        lines.append(f"[{i}] {authors}. {p.get('title', '')}. "
                     f"{p.get('journal', '')} ({p.get('year', '')}). {p.get('url', '')}")
    return {"answer": "\n".join(lines), "method": "raw_sources",
            "error": "AI providers unavailable"}
