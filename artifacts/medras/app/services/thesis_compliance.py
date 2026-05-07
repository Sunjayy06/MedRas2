"""Pre-flight compliance checks for the thesis dashboard / export.

Pure-function — receives the full thesis state JSON from the client and
returns a list of pass/warn/fail items the UI can render.

Checks are stateless and self-contained so they can be re-run from any
point in the flow.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from app.services.thesis_formats import CHAPTER_SPINE, DEFAULT_RULES


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def _est_pages(total_words: int, words_per_page: int = 280) -> int:
    """Rough page estimate at 1.5 spacing TNR 12 (~280 wpp)."""
    return max(1, round(total_words / max(1, words_per_page)))


def check(thesis: Dict[str, Any]) -> Dict[str, Any]:
    """Run every compliance check and return ``{items, summary}``.

    ``thesis`` shape (mirrors the client store):
      ``{setup, rules, references: [...], chapters: {<id>: {text, ...}},
         locked_numbers, plagiarism: {pct, ai_pct}, assets: {pictures, certificates}}``
    """
    rules = {**DEFAULT_RULES, **(thesis.get("rules") or {})}
    chapters = thesis.get("chapters") or {}
    setup = thesis.get("setup") or {}
    refs = thesis.get("references") or []
    plag = thesis.get("plagiarism") or {}
    assets = thesis.get("assets") or {}
    items: List[Dict[str, Any]] = []

    # Total word + page estimate
    total_words = sum(_word_count((c or {}).get("text", "")) for c in chapters.values())
    pages = _est_pages(total_words)
    max_pages = int(rules.get("max_pages") or 80)
    items.append({
        "id": "page_count",
        "label": "Page count within university limit",
        "status": "pass" if pages <= max_pages else "warn",
        "detail": f"~{pages} pages estimated · limit {max_pages}",
        "fix":    "/thesis-module/dashboard.html",
    })

    # Reference minimum
    min_refs = int(rules.get("min_references") or 0)
    n_refs = sum(1 for r in refs if isinstance(r, dict))
    items.append({
        "id": "ref_count",
        "label": "Reference count",
        "status": "pass" if n_refs >= min_refs else "fail",
        "detail": f"{n_refs} of minimum {min_refs}",
        "fix":    "/thesis-module/references.html",
    })

    # Verified DOIs (defensive — every ref should have either a DOI or be marked verified=False)
    unverified = sum(1 for r in refs if isinstance(r, dict)
                     and not r.get("verified") and not (r.get("doi") or "").strip())
    if unverified:
        items.append({
            "id": "ref_unverified",
            "label": "All references verified",
            "status": "warn",
            "detail": f"{unverified} references could not be DOI-verified",
            "fix":    "/thesis-module/references.html",
        })

    # Every chapter at least started
    started = 0
    for ch in CHAPTER_SPINE:
        c = chapters.get(ch["id"]) or {}
        if (c.get("text") or "").strip():
            started += 1
    items.append({
        "id": "chapters_started",
        "label": "Every chapter started",
        "status": "pass" if started == len(CHAPTER_SPINE) else "warn",
        "detail": f"{started} of {len(CHAPTER_SPINE)} chapters",
        "fix":    "/thesis-module/dashboard.html",
    })

    # Every required body chapter at >=60% of target
    body_short: List[str] = []
    for ch in CHAPTER_SPINE:
        if ch.get("group") != "body":
            continue
        target = int(ch.get("target_words") or 0)
        if target <= 0:
            continue
        c = chapters.get(ch["id"]) or {}
        wc = _word_count(c.get("text", ""))
        if wc < int(target * 0.6):
            body_short.append(f"{ch['label']}: {wc}/{target}")
    items.append({
        "id": "body_chapters_full",
        "label": "Body chapters at sufficient length",
        "status": "pass" if not body_short else "warn",
        "detail": ", ".join(body_short) if body_short else "All body chapters at target length",
        "fix":    "/thesis-module/dashboard.html",
    })

    # Plagiarism
    pct = plag.get("pct")
    cap = float(rules.get("max_plagiarism_pct") or 10.0)
    if pct is None:
        items.append({
            "id": "plagiarism",
            "label": f"Plagiarism ≤ {cap:g}%",
            "status": "warn",
            "detail": "Not yet checked — open the Plagiarism Checker",
            "fix":    "/plagiarism-module/checker.html",
        })
    else:
        items.append({
            "id": "plagiarism",
            "label": f"Plagiarism ≤ {cap:g}%",
            "status": "pass" if float(pct) <= cap else "warn",
            "detail": f"{float(pct):.1f}%",
            "fix":    "/plagiarism-module/reduce-results.html",
        })

    # AI score
    ai_pct = plag.get("ai_pct")
    if ai_pct is None:
        items.append({
            "id": "ai_score",
            "label": "AI-generated text ≈ 0%",
            "status": "warn",
            "detail": "Not yet checked",
            "fix":    "/plagiarism-module/checker.html",
        })
    else:
        items.append({
            "id": "ai_score",
            "label": "AI-generated text ≈ 0%",
            "status": "pass" if float(ai_pct) <= 5.0 else "warn",
            "detail": f"{float(ai_pct):.1f}%",
            "fix":    "/plagiarism-module/reduce-results.html",
        })

    # Required declarations present (string match in the front-matter)
    cert_text = ((chapters.get("certificates") or {}).get("text") or "").lower()
    req_decls = rules.get("declarations_required") or []
    missing_decls = [d for d in req_decls
                     if not any(tok in cert_text for tok in d.lower().split() if len(tok) > 3)]
    items.append({
        "id": "declarations",
        "label": "Required declarations & certificates",
        "status": "pass" if not missing_decls else "warn",
        "detail": ("All present" if not missing_decls
                   else f"Missing tokens for: {', '.join(missing_decls)}"),
        "fix":    "/thesis-module/dashboard.html#certificates",
    })

    # IEC mandatory (Indian formats)
    if rules.get("iec_required"):
        title_text = ((chapters.get("title_page") or {}).get("text") or "").lower()
        has_iec = "iec" in title_text or "ethics committee" in title_text or "iec" in cert_text
        items.append({
            "id": "iec",
            "label": "IEC committee block present on title page",
            "status": "pass" if has_iec else "warn",
            "detail": "IEC details detected" if has_iec else "Add IEC committee block",
            "fix":    "/thesis-module/dashboard.html#title_page",
        })

    # Title page metadata sanity
    setup_missing = [k for k in ("title", "researcher", "guide", "institution")
                     if not (setup.get(k) or "").strip()]
    items.append({
        "id": "setup_complete",
        "label": "Title-page metadata complete",
        "status": "pass" if not setup_missing else "warn",
        "detail": ("All filled" if not setup_missing
                   else "Missing: " + ", ".join(setup_missing)),
        "fix":    "/thesis-module/setup.html",
    })

    # Asset placement
    pics = (assets.get("pictures") or [])
    unplaced_pics = [p for p in pics if isinstance(p, dict) and not p.get("place_chapter")]
    if pics:
        items.append({
            "id": "pictures_placed",
            "label": "All figures placed",
            "status": "pass" if not unplaced_pics else "warn",
            "detail": (f"{len(pics)} figures, all placed" if not unplaced_pics
                       else f"{len(unplaced_pics)} figures still need a chapter"),
            "fix":    "/thesis-module/dashboard.html#assets",
        })

    # Summary counts
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for it in items:
        counts[it.get("status", "warn")] = counts.get(it.get("status", "warn"), 0) + 1
    return {
        "items": items,
        "summary": {
            "total":  len(items),
            "pass":   counts["pass"],
            "warn":   counts["warn"],
            "fail":   counts["fail"],
            "ready":  counts["fail"] == 0,
            "pages_estimated": pages,
            "words_total":     total_words,
            "references":      n_refs,
        },
    }
