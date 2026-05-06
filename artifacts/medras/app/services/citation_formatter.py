"""Format reference dicts in common academic citation styles.

Supported styles: Vancouver, APA, AMA, IEEE, Chicago. Falls back to Vancouver
if the requested style is unknown. Style detection is permissive — many
formats list combined values like ``"Vancouver / APA"``; ``detect_styles``
returns the list in the order they appear so the UI can offer them as a
picker.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

SUPPORTED_STYLES = ["Vancouver", "APA", "AMA", "IEEE", "Chicago"]
DEFAULT_STYLE = "Vancouver"

_STYLE_PATTERNS = [
    ("Vancouver", re.compile(r"vancouver", re.I)),
    ("APA",       re.compile(r"\bAPA\b", re.I)),
    ("AMA",       re.compile(r"\bAMA\b|\bNLM\b", re.I)),
    ("IEEE",      re.compile(r"\bIEEE\b", re.I)),
    ("Chicago",   re.compile(r"chicago", re.I)),
]


def detect_styles(citation_field: str) -> List[str]:
    """Return ordered list of supported styles mentioned in `citation_field`."""
    found: List[str] = []
    for label, pat in _STYLE_PATTERNS:
        if pat.search(citation_field or ""):
            found.append(label)
    return found or [DEFAULT_STYLE]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(s: Any) -> str:
    return str(s or "").strip()


def _format_authors_vancouver(authors: List[str], max_listed: int = 6) -> str:
    """Last-name + initials, comma-separated, ', et al.' if more than max."""
    if not authors:
        return ""
    names = [_format_one_author_lastfirst(a) for a in authors if _clean(a)]
    if not names:
        return ""
    if len(names) > max_listed:
        return ", ".join(names[:max_listed]) + ", et al"
    return ", ".join(names)


def _format_one_author_lastfirst(name: str) -> str:
    """'John Q. Smith' → 'Smith JQ'.  'Smith, John Q.' → 'Smith JQ'."""
    n = _clean(name).replace(".", "")
    if not n:
        return ""
    if "," in n:
        last, _, rest = n.partition(",")
        last = last.strip()
        initials = "".join(p[0].upper() for p in rest.split() if p)
        return f"{last} {initials}".strip()
    parts = n.split()
    if len(parts) == 1:
        return parts[0]
    last = parts[-1]
    initials = "".join(p[0].upper() for p in parts[:-1] if p)
    return f"{last} {initials}".strip()


def _format_authors_apa(authors: List[str], max_listed: int = 20) -> str:
    """'Smith, J. Q., Jones, A., & Brown, R.' style."""
    if not authors:
        return ""
    formatted = []
    for a in authors:
        n = _clean(a).replace(".", "")
        if not n:
            continue
        if "," in n:
            last, _, rest = n.partition(",")
            last = last.strip()
            initials = " ".join(f"{p[0].upper()}." for p in rest.split() if p)
        else:
            parts = n.split()
            last = parts[-1]
            initials = " ".join(f"{p[0].upper()}." for p in parts[:-1] if p)
        formatted.append(f"{last}, {initials}".strip().rstrip(","))
    if not formatted:
        return ""
    if len(formatted) > max_listed:
        formatted = formatted[: max_listed - 1] + ["…", formatted[-1]]
    if len(formatted) == 1:
        return formatted[0]
    return ", ".join(formatted[:-1]) + ", & " + formatted[-1]


def _doi_link(doi: str) -> str:
    d = _clean(doi)
    if not d:
        return ""
    if d.lower().startswith("http"):
        return d
    if d.lower().startswith("doi:"):
        d = d[4:].strip()
    return f"https://doi.org/{d}"


# ---------------------------------------------------------------------------
# Per-style formatters
# ---------------------------------------------------------------------------

def _vancouver(ref: Dict[str, Any], idx: int) -> str:
    authors = _format_authors_vancouver(ref.get("authors") or [])
    title = _clean(ref.get("title")).rstrip(".")
    journal = _clean(ref.get("journal"))
    year = _clean(ref.get("year"))
    volume = _clean(ref.get("volume"))
    issue = _clean(ref.get("issue"))
    pages = _clean(ref.get("pages"))
    doi = _clean(ref.get("doi"))

    parts = []
    if authors: parts.append(authors + ".")
    if title: parts.append(title + ".")
    journal_block = journal
    if year:
        journal_block += f". {year}" if journal else year
        if volume:
            journal_block += f";{volume}"
            if issue: journal_block += f"({issue})"
        if pages: journal_block += f":{pages}"
        journal_block += "."
    elif journal:
        journal_block += "."
    if journal_block.strip(): parts.append(journal_block)
    if doi: parts.append(f"doi:{doi}")
    return f"{idx}. " + " ".join(parts).strip()


def _apa(ref: Dict[str, Any], idx: int) -> str:
    authors = _format_authors_apa(ref.get("authors") or [])
    year = _clean(ref.get("year"))
    title = _clean(ref.get("title")).rstrip(".")
    journal = _clean(ref.get("journal"))
    volume = _clean(ref.get("volume"))
    issue = _clean(ref.get("issue"))
    pages = _clean(ref.get("pages"))
    doi = _clean(ref.get("doi"))

    parts = []
    if authors: parts.append(f"{authors}")
    if year: parts.append(f"({year}).")
    if title: parts.append(f"{title}.")
    if journal:
        jb = f"*{journal}*"
        if volume:
            jb += f", *{volume}*"
            if issue: jb += f"({issue})"
        if pages: jb += f", {pages}"
        jb += "."
        parts.append(jb)
    if doi: parts.append(_doi_link(doi))
    return " ".join(parts).strip()


def _ama(ref: Dict[str, Any], idx: int) -> str:
    # Same shape as Vancouver in this codebase; small punctuation tweak
    return _vancouver(ref, idx)


def _ieee(ref: Dict[str, Any], idx: int) -> str:
    authors = _format_authors_apa(ref.get("authors") or [], max_listed=6)
    title = _clean(ref.get("title")).rstrip(".")
    journal = _clean(ref.get("journal"))
    year = _clean(ref.get("year"))
    volume = _clean(ref.get("volume"))
    issue = _clean(ref.get("issue"))
    pages = _clean(ref.get("pages"))
    doi = _clean(ref.get("doi"))

    parts = [f"[{idx}]"]
    if authors: parts.append(authors + ",")
    if title: parts.append(f'"{title},"')
    if journal: parts.append(f"*{journal}*,")
    if volume: parts.append(f"vol. {volume},")
    if issue: parts.append(f"no. {issue},")
    if pages: parts.append(f"pp. {pages},")
    if year: parts.append(f"{year}.")
    if doi: parts.append(f"doi: {doi}.")
    return " ".join(parts).strip()


def _chicago(ref: Dict[str, Any], idx: int) -> str:
    authors = _format_authors_apa(ref.get("authors") or [])
    year = _clean(ref.get("year"))
    title = _clean(ref.get("title")).rstrip(".")
    journal = _clean(ref.get("journal"))
    volume = _clean(ref.get("volume"))
    issue = _clean(ref.get("issue"))
    pages = _clean(ref.get("pages"))
    doi = _clean(ref.get("doi"))

    parts = []
    if authors: parts.append(authors + ".")
    if year: parts.append(f"{year}.")
    if title: parts.append(f'"{title}."')
    if journal:
        jb = f"*{journal}*"
        if volume: jb += f" {volume}"
        if issue: jb += f", no. {issue}"
        if pages: jb += f": {pages}"
        jb += "."
        parts.append(jb)
    if doi: parts.append(_doi_link(doi) + ".")
    return " ".join(parts).strip()


_FORMATTERS = {
    "Vancouver": _vancouver,
    "APA":       _apa,
    "AMA":       _ama,
    "IEEE":      _ieee,
    "Chicago":   _chicago,
}


def format_citation(ref: Dict[str, Any], style: str, index: int = 1) -> str:
    fn = _FORMATTERS.get(style) or _FORMATTERS[DEFAULT_STYLE]
    try:
        return fn(ref, index)
    except Exception:
        # Last-resort plaintext fallback so the UI never crashes on a bad ref.
        bits = [_clean(ref.get("authors") and ", ".join(ref["authors"])),
                _clean(ref.get("title")),
                _clean(ref.get("journal")),
                _clean(ref.get("year")),
                _clean(ref.get("doi"))]
        return f"{index}. " + ". ".join(b for b in bits if b)


def format_all(refs: List[Dict[str, Any]], style: str) -> List[str]:
    s = style if style in _FORMATTERS else DEFAULT_STYLE
    return [format_citation(r, s, i + 1) for i, r in enumerate(refs)]
