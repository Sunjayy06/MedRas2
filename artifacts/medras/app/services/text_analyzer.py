"""Document structure & protected-term analyser.

Used by the Plagiarism & AI Reduction module to:

  * Split an uploaded paper into IMRaD sections (Abstract, Introduction,
    Methods, Results, Discussion, Conclusion, References, etc.).
  * Find technical strings that must NEVER be paraphrased — drug names,
    p-values, confidence intervals, percentages, dosages with units,
    citations, DOIs, gene symbols, and similar.

Both functions are pure-Python regex / string scanning. No LLM is used
here — the LLM only sees the text + the explicit list of protected
strings as a downstream prompt constraint.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------

# Each entry: (canonical key, display label, regex matched against a stripped
# line). Order matters only for tie-breaking when a line matches more than
# one pattern (rare). The regex must match the FULL stripped line — section
# headings live on their own line in nearly all PDF/DOCX extractions.
_SECTION_PATTERNS: List[Tuple[str, str, re.Pattern[str]]] = [
    ("abstract",        "Abstract",         re.compile(r"^(?:abstract|summary)\s*[:\.\-]?\s*$",                                                               re.IGNORECASE)),
    ("keywords",        "Keywords",         re.compile(r"^(?:key\s*words?|keywords?)\s*[:\.\-]?\s*$",                                                          re.IGNORECASE)),
    ("introduction",    "Introduction",     re.compile(r"^(?:\d+[\.\)]?\s*)?(?:introduction|background|overview)\s*[:\.\-]?\s*$",                              re.IGNORECASE)),
    ("methods",         "Methods",          re.compile(r"^(?:\d+[\.\)]?\s*)?(?:methods?|methodology|materials\s+and\s+methods|patients\s+and\s+methods|study\s+design|experimental\s+procedures?)\s*[:\.\-]?\s*$", re.IGNORECASE)),
    ("results",         "Results",          re.compile(r"^(?:\d+[\.\)]?\s*)?(?:results?|findings?|outcomes?)\s*[:\.\-]?\s*$",                                  re.IGNORECASE)),
    ("discussion",      "Discussion",       re.compile(r"^(?:\d+[\.\)]?\s*)?(?:discussion|interpretation)\s*[:\.\-]?\s*$",                                     re.IGNORECASE)),
    ("conclusion",      "Conclusion",       re.compile(r"^(?:\d+[\.\)]?\s*)?(?:conclusions?|concluding\s+remarks?)\s*[:\.\-]?\s*$",                            re.IGNORECASE)),
    ("limitations",     "Limitations",      re.compile(r"^(?:\d+[\.\)]?\s*)?(?:limitations?|study\s+limitations?)\s*[:\.\-]?\s*$",                             re.IGNORECASE)),
    ("acknowledgments", "Acknowledgments",  re.compile(r"^acknowledg(?:e?ments?)\s*[:\.\-]?\s*$",                                                              re.IGNORECASE)),
    ("funding",         "Funding",          re.compile(r"^(?:funding|financial\s+support|grant\s+support)\s*[:\.\-]?\s*$",                                     re.IGNORECASE)),
    ("conflicts",       "Conflicts of interest", re.compile(r"^(?:conflicts?\s+of\s+interest|competing\s+interests?|disclosures?)\s*[:\.\-]?\s*$",             re.IGNORECASE)),
    ("references",      "References",       re.compile(r"^(?:references?|bibliography|works\s+cited|literature\s+cited)\s*[:\.\-]?\s*$",                       re.IGNORECASE)),
    ("appendix",        "Appendix",         re.compile(r"^(?:appendix|appendices)\s*(?:[A-Z0-9]+)?\s*[:\.\-]?\s*$",                                            re.IGNORECASE)),
]

# Don't treat a line as a heading if it's longer than this — real headings
# are short ("Methods", "Materials and Methods", "3. Results"), whereas a
# line that *starts with* "Results" but runs on for 200 chars is a sentence.
_MAX_HEADING_LEN = 60

# Inline heading form: "Abstract: This study evaluates…" or
# "Methods. Patients were enrolled…" — a heading word followed by `:` or `.`
# or `—`/`-` and then real body text on the same line. Common when PDFs
# extract paragraphs without preserving the heading line break.
_INLINE_HEADING_NAMES = (
    r"abstract|summary|introduction|background|overview|"
    r"methods?|methodology|materials\s+and\s+methods|patients\s+and\s+methods|study\s+design|"
    r"results?|findings?|outcomes?|"
    r"discussion|interpretation|"
    r"conclusions?|concluding\s+remarks?|"
    r"limitations?|"
    r"references?|bibliography"
)
_INLINE_HEADING_RE = re.compile(
    rf"^\s*(?:\d+[\.\)]?\s*)?({_INLINE_HEADING_NAMES})\s*[:\.\u2014\-]\s+(\S.*)$",
    re.IGNORECASE,
)
# Map the word the user typed back onto a canonical (key, label) pair.
_INLINE_KEY_MAP = {
    "abstract": ("abstract", "Abstract"),
    "summary": ("abstract", "Abstract"),
    "introduction": ("introduction", "Introduction"),
    "background": ("introduction", "Introduction"),
    "overview": ("introduction", "Introduction"),
    "method": ("methods", "Methods"),
    "methods": ("methods", "Methods"),
    "methodology": ("methods", "Methods"),
    "materials and methods": ("methods", "Methods"),
    "patients and methods": ("methods", "Methods"),
    "study design": ("methods", "Methods"),
    "result": ("results", "Results"),
    "results": ("results", "Results"),
    "finding": ("results", "Results"),
    "findings": ("results", "Results"),
    "outcome": ("results", "Results"),
    "outcomes": ("results", "Results"),
    "discussion": ("discussion", "Discussion"),
    "interpretation": ("discussion", "Discussion"),
    "conclusion": ("conclusion", "Conclusion"),
    "conclusions": ("conclusion", "Conclusion"),
    "concluding remarks": ("conclusion", "Conclusion"),
    "limitation": ("limitations", "Limitations"),
    "limitations": ("limitations", "Limitations"),
    "reference": ("references", "References"),
    "references": ("references", "References"),
    "bibliography": ("references", "References"),
}


def _inline_heading_split(line: str) -> Tuple[str, str, str] | None:
    """If ``line`` is an inline heading (e.g. ``Abstract: ...``), return
    ``(key, label, remainder)`` with the heading classification and the
    body text that followed it on the same line. Else return None.
    """
    m = _INLINE_HEADING_RE.match(line)
    if not m:
        return None
    name = re.sub(r"\s+", " ", m.group(1)).strip().lower()
    info = _INLINE_KEY_MAP.get(name)
    if not info:
        return None
    return (info[0], info[1], m.group(2).strip())


@dataclass
class Section:
    key: str            # canonical id, e.g. "methods"
    label: str          # display label, e.g. "Methods"
    text: str           # the section body (heading line excluded)
    word_count: int
    char_count: int
    start_line: int     # 1-indexed line number where heading was found
    order: int          # index in the document (0-based)

    def to_dict(self) -> Dict:
        d = asdict(self)
        return d


def _classify_line(line: str) -> Tuple[str, str] | None:
    """Return (key, label) if ``line`` is a recognised section heading."""
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_HEADING_LEN:
        return None
    # Strip surrounding markdown/punct decoration so "## Methods ##" matches.
    cleaned = re.sub(r"^[\s#*•·\-=_]+|[\s#*•·\-=_]+$", "", stripped)
    if not cleaned:
        return None
    for key, label, pattern in _SECTION_PATTERNS:
        if pattern.match(cleaned):
            return (key, label)
    return None


def detect_sections(text: str) -> List[Section]:
    """Split ``text`` into IMRaD-style sections.

    The first section ("Preamble") covers everything before the first
    recognised heading — usually the title block, authors, and affiliations.
    If no headings are found, returns a single section labelled "Document".
    """
    if not text:
        return []

    # If we encounter an inline heading like "Abstract: This study…", we
    # rewrite the line in-place into TWO lines (the heading on its own,
    # then the remainder) so the existing line-based splitter Just Works.
    raw_lines = text.splitlines()
    lines: List[str] = []
    for raw in raw_lines:
        inline = _inline_heading_split(raw)
        if inline:
            _, label, remainder = inline
            lines.append(label)
            if remainder:
                lines.append(remainder)
        else:
            lines.append(raw)

    boundaries: List[Tuple[int, str, str]] = []  # (line_idx, key, label)
    for i, line in enumerate(lines):
        match = _classify_line(line)
        if match:
            boundaries.append((i, match[0], match[1]))

    sections: List[Section] = []
    if not boundaries:
        body = text.strip()
        if not body:
            return []
        return [Section(
            key="document",
            label="Document",
            text=body,
            word_count=_word_count(body),
            char_count=len(body),
            start_line=1,
            order=0,
        )]

    # Preamble (everything before the first heading) — only if it has content.
    first_heading_line = boundaries[0][0]
    preamble_lines = lines[:first_heading_line]
    preamble = "\n".join(preamble_lines).strip()
    if preamble:
        sections.append(Section(
            key="preamble",
            label="Title & front matter",
            text=preamble,
            word_count=_word_count(preamble),
            char_count=len(preamble),
            start_line=1,
            order=0,
        ))

    # Each heading → text up to next heading.
    for i, (line_idx, key, label) in enumerate(boundaries):
        end_idx = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(lines)
        body_lines = lines[line_idx + 1:end_idx]
        body = "\n".join(body_lines).strip()
        sections.append(Section(
            key=key,
            label=label,
            text=body,
            word_count=_word_count(body),
            char_count=len(body),
            start_line=line_idx + 1,
            order=len(sections),
        ))

    return sections


def _word_count(s: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", s))


# ---------------------------------------------------------------------------
# Protected-term detection
# ---------------------------------------------------------------------------

# Each entry: (type tag, regex). Order matters only because the first
# matching type wins for a given span — we de-duplicate by literal text
# afterwards.
_PROTECTED_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    # Statistical p-values: p<0.05, p = .001, p-value, P ≤ 0.01
    ("p_value", re.compile(r"\b[Pp]\s*(?:[-\u2010]?\s*value)?\s*[<>=≤≥]\s*0?\.\d+\b")),
    # Confidence intervals: 95% CI: 1.2-3.4, 95 % CI = [0.5, 0.9]
    ("confidence_interval", re.compile(r"\b\d{2}\s*%\s*C\.?I\.?\s*[:=]?\s*\[?\s*[-\d\.,\s%]+\]?")),
    # Effect sizes / test statistics: t(45)=2.31, F(2,30)=4.5, χ²=6.7, OR=1.5, HR=2.1, RR=0.8
    ("test_statistic", re.compile(r"\b(?:t|F|χ²|chi[-\s]?square|U|Z|r|R²|OR|HR|RR)\s*\(?[\d\.,\s]*\)?\s*[=≈]\s*[-\d\.,]+\b")),
    # Percentages: 12.5%, 100 %
    ("percentage", re.compile(r"\b\d+(?:\.\d+)?\s*%")),
    # Dosages and units: 500 mg, 2.5 mL, 40 IU, 10 mmol/L
    ("dose_unit", re.compile(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|µg|ug|g|kg|mL|ml|µL|uL|L|IU|U|mmol/L|mmol|nmol|µmol|umol|mol|ng/mL|pg/mL|mEq|cm|mm|µm|nm|min|hr|h|sec|s|day|week|wk|month|year|yr|bpm|mmHg|kPa|°C|°F)\b", re.IGNORECASE)),
    # Drug-name suffix heuristics. Restricted to DISTINCTIVE pharmacological
    # endings so we don't over-protect ordinary words ending in -in/-ine/-ide
    # (Machine, Protein, Baseline, Outside…). Case-insensitive so lowercase
    # generic names ("metformin", "aspirin", "amoxicillin") are caught too.
    # Stem must be ≥3 letters to avoid matching abbreviations.
    ("drug_name", re.compile(
        r"\b[A-Za-z]{3,}(?:mab|nib|tinib|prazole|olol|sartan|statin|cycline|cillin|mycin|asone|azole|pril|dipine|caine|formin|gliptin|glitazone|parin|sone|profen|coxib|setron|triptan|pam|zepam|zolam|barbital|phylline|fenac|cetin|mustine|platin|rubicin|virine|navir|ciclovir|fenadine)\b",
        re.IGNORECASE,
    )),
    # Common drugs that don't follow the suffix conventions above (older
    # brand-name origin, no class ending). Kept explicit so we don't have
    # to broaden the suffix regex and re-introduce false positives.
    ("drug_name", re.compile(
        r"\b(?:aspirin|warfarin|insulin|digoxin|heparin|enoxaparin|paracetamol|acetaminophen|codeine|morphine|tramadol|fentanyl|oxycodone|ketamine|propofol|midazolam|lorazepam|diazepam|alprazolam|clonazepam|sertraline|fluoxetine|paroxetine|citalopram|escitalopram|venlafaxine|duloxetine|bupropion|trazodone|amitriptyline|haloperidol|risperidone|olanzapine|quetiapine|clozapine|lithium|valproate|carbamazepine|phenytoin|gabapentin|pregabalin|topiramate|levothyroxine|liothyronine|methotrexate|cyclophosphamide|cyclosporine|tacrolimus|sirolimus|azathioprine|mycophenolate|hydroxychloroquine|chloroquine|sulfasalazine|leflunomide|allopurinol|colchicine|furosemide|hydrochlorothiazide|spironolactone|amiodarone|verapamil|diltiazem|clopidogrel|ticagrelor|prasugrel|rivaroxaban|apixaban|dabigatran|edoxaban|levodopa|carbidopa|donepezil|memantine|rivastigmine|galantamine|salbutamol|albuterol|tiotropium|ipratropium|montelukast|theophylline|prednisolone|hydrocortisone|methylprednisolone|fluticasone|budesonide|tamoxifen|anastrozole|letrozole|exemestane|raloxifene|bevacizumab|trastuzumab|rituximab|adalimumab|infliximab|etanercept|ustekinumab|secukinumab)\b",
        re.IGNORECASE,
    )),
    # In-text citations: (Smith, 2023), (Smith et al., 2021), [12], [3-5,7]
    ("citation", re.compile(r"\([A-Z][A-Za-z\u2019\u2018'\-]+(?:\s+(?:and|&)\s+[A-Z][A-Za-z\u2019\u2018'\-]+|\s+et\s+al\.?)?,\s*\d{4}[a-z]?\)|\[\d+(?:\s*[-,]\s*\d+)*\]")),
    # DOIs and PubMed IDs
    ("doi", re.compile(r"\b(?:doi:?\s*)?10\.\d{4,9}/[^\s\)\],]+", re.IGNORECASE)),
    ("pmid", re.compile(r"\bPMID:?\s*\d{4,9}\b", re.IGNORECASE)),
    # Gene/protein symbols: TP53, BRCA1, HER2, IL-6, CD4+
    ("gene_symbol", re.compile(r"\b(?:[A-Z]{2,5}[0-9]{1,3}|[A-Z]{2,4}-?\d+\+?|HLA-[A-Z0-9*]+)\b")),
    # ICD-10 codes: A00.1, K35.80
    ("icd_code", re.compile(r"\b[A-Z]\d{2}(?:\.\d{1,3})?\b")),
    # Standalone numbers with decimals (e.g. 3.14) — kept LOW PRIORITY so
    # they don't shadow more specific patterns above.
    ("statistic", re.compile(r"\b\d+\.\d+\b")),
]

# Hard cap so we don't ship huge payloads when the doc is enormous.
_MAX_PROTECTED_TERMS = 400


@dataclass
class ProtectedTerm:
    text: str
    type: str

    def to_dict(self) -> Dict:
        return asdict(self)


def find_protected_terms(text: str) -> List[ProtectedTerm]:
    """Return a deduplicated list of strings that must not be paraphrased.

    Earlier patterns win when two patterns match the same literal substring
    (so a span tagged as "p_value" is never re-tagged as a generic
    "statistic").
    """
    if not text:
        return []

    seen: Dict[str, str] = {}  # literal text -> type
    for type_tag, pattern in _PROTECTED_PATTERNS:
        for m in pattern.finditer(text):
            raw = m.group(0).strip()
            if not raw:
                continue
            # Normalise whitespace so duplicates collapse.
            key = re.sub(r"\s+", " ", raw)
            if key not in seen:
                seen[key] = type_tag
            if len(seen) >= _MAX_PROTECTED_TERMS:
                break
        if len(seen) >= _MAX_PROTECTED_TERMS:
            break

    return [ProtectedTerm(text=t, type=ty) for t, ty in seen.items()]


# ---------------------------------------------------------------------------
# High-level helper
# ---------------------------------------------------------------------------


def analyze_document(text: str) -> Dict:
    """Run section + protected-term detection, return a single payload.

    The returned dict shape is the contract the frontend consumes:

    {
      "total_word_count": int,
      "total_char_count": int,
      "sections": [
         {"key": "methods", "label": "Methods", "word_count": ...,
          "char_count": ..., "start_line": ..., "order": ...,
          "preview": "<first 240 chars>"}
      ],
      "protected_terms": [
         {"text": "p < 0.001", "type": "p_value"},
         ...
      ],
      "protected_term_counts": {"p_value": 4, "drug_name": 2, ...}
    }

    The full per-section text is NOT included — it's available via the
    underlying ``detect_sections()`` call, but is too bulky to round-trip
    over JSON for a 100 MB document. The frontend only needs counts and a
    short preview to render its breakdown panel.
    """
    text = text or ""
    sections = detect_sections(text)
    terms = find_protected_terms(text)

    type_counts: Dict[str, int] = {}
    for t in terms:
        type_counts[t.type] = type_counts.get(t.type, 0) + 1

    return {
        "total_word_count": _word_count(text),
        "total_char_count": len(text),
        "sections": [
            {
                "key": s.key,
                "label": s.label,
                "word_count": s.word_count,
                "char_count": s.char_count,
                "start_line": s.start_line,
                "order": s.order,
                "preview": s.text[:240].replace("\n", " ").strip(),
            }
            for s in sections
        ],
        "protected_terms": [t.to_dict() for t in terms],
        "protected_term_counts": type_counts,
    }
