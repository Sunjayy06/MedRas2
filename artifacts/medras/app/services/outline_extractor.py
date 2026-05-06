"""Outline-step text extraction.

Wraps the existing extractor in `plagiarism_analyzer` and adds PowerPoint
(`.pptx`) support. All other formats (`.pdf`, `.docx`, `.txt`, `.md`) and all
error semantics are inherited unchanged.
"""

from __future__ import annotations

from io import BytesIO
from typing import Set

from app.services import plagiarism_analyzer as _pa

# Re-export for convenience so callers can `except outline_extractor.UploadExtractionError`.
UploadExtractionError = _pa.UploadExtractionError
UnsupportedFileError = _pa.UnsupportedFileError
PasswordProtectedError = _pa.PasswordProtectedError
ImageOnlyPdfError = _pa.ImageOnlyPdfError
DocumentTooLargeError = _pa.DocumentTooLargeError
CorruptedFileError = _pa.CorruptedFileError

SUPPORTED_EXTENSIONS: Set[str] = {".pdf", ".docx", ".pptx", ".txt", ".md"}


def _extract_pptx(content: bytes) -> str:
    """Extract concatenated text from a .pptx file using python-pptx."""
    try:
        from pptx import Presentation  # type: ignore
        from pptx.exc import PackageNotFoundError  # type: ignore
    except ImportError as exc:  # pragma: no cover — dep is pinned
        raise CorruptedFileError(
            "PowerPoint support is not installed on this server."
        ) from exc

    try:
        prs = Presentation(BytesIO(content))
    except PackageNotFoundError as exc:
        raise CorruptedFileError(
            "We could not open this PowerPoint file. It may be password-protected, "
            "an older .ppt format, or not actually a .pptx file. Please save it as a "
            "modern .pptx and try again."
        ) from exc
    except Exception as exc:
        raise CorruptedFileError(
            "We could not read this PowerPoint file. Please re-export it as .pptx and try again."
        ) from exc

    parts = []
    for idx, slide in enumerate(prs.slides, 1):
        slide_text_parts = []
        for shape in slide.shapes:
            try:
                # Title / body placeholders, text boxes
                if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        line = "".join(run.text or "" for run in para.runs).strip()
                        if line:
                            slide_text_parts.append(line)
                # Table cells
                if getattr(shape, "has_table", False) and shape.has_table:
                    for row in shape.table.rows:
                        for cell in row.cells:
                            cell_text = (cell.text or "").strip()
                            if cell_text:
                                slide_text_parts.append(cell_text)
            except Exception:
                continue
        # Notes
        try:
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                notes = (slide.notes_slide.notes_text_frame.text or "").strip()
                if notes:
                    slide_text_parts.append("[Notes] " + notes)
        except Exception:
            pass

        if slide_text_parts:
            parts.append(f"--- Slide {idx} ---\n" + "\n".join(slide_text_parts))

    return "\n\n".join(parts)


def extract_text(filename: str, content: bytes) -> str:
    """Extract text from any supported upload type for the outline step.

    Adds .pptx handling on top of the existing plagiarism extractor. Other
    extensions and error semantics are unchanged. May raise the same
    ``UploadExtractionError`` subclasses as ``plagiarism_analyzer``.
    """
    name = (filename or "").lower().strip()
    if name.endswith(".pptx"):
        return _extract_pptx(content)
    if name.endswith(".ppt"):
        raise UnsupportedFileError(
            "Old-format .ppt files aren't supported. Please open the file in PowerPoint "
            "and 'Save As' a .pptx, then try again."
        )
    # Delegate everything else to the existing extractor (.pdf/.docx/.txt/.md).
    return _pa.extract_text_from_upload(filename, content)
