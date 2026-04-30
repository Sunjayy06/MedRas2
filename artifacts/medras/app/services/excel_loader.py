"""Read Excel / CSV uploads into a pandas DataFrame.

We accept .xlsx, .xls and .csv. Multi-sheet Excels return the first sheet
by default but expose the sheet list so the UI can offer a sheet picker.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


# Hard cap on file size we will parse (8 MB). Anything larger should be
# subsampled or chunked at the source.
MAX_BYTES = 8 * 1024 * 1024


class UploadError(ValueError):
    """Raised for any user-facing upload problem (size, format, parse)."""


def parse_upload(
    *,
    filename: str,
    raw: bytes,
    sheet_name: Optional[str] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Parse an upload and return ``(df, meta)``.

    ``meta`` contains: ``filename``, ``size_bytes``, ``rows``, ``cols``,
    ``sheet_names`` (list, empty for CSV), ``selected_sheet``.
    """
    if not raw:
        raise UploadError("Uploaded file is empty.")
    if len(raw) > MAX_BYTES:
        raise UploadError(
            f"File is {len(raw) // 1024} KB — limit is {MAX_BYTES // 1024} KB. "
            "Please upload a smaller dataset or take a representative sample."
        )

    name = (filename or "").lower()
    sheet_names: List[str] = []
    selected_sheet: Optional[str] = None

    try:
        if name.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(raw))
        elif name.endswith(".xls") or name.endswith(".xlsx"):
            engine = "openpyxl" if name.endswith(".xlsx") else "xlrd"
            xls = pd.ExcelFile(io.BytesIO(raw), engine=engine)
            sheet_names = list(xls.sheet_names)
            selected_sheet = sheet_name if sheet_name in sheet_names else sheet_names[0]
            df = pd.read_excel(xls, sheet_name=selected_sheet)
        else:
            raise UploadError(
                "Unsupported file type. Please upload an .xlsx, .xls or .csv file."
            )
    except UploadError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface library errors as user message
        raise UploadError(f"Could not read file: {exc}") from exc

    # Normalise column names (strip whitespace) but keep original spelling.
    df.columns = [str(c).strip() for c in df.columns]
    # Drop fully empty columns and rows.
    df = df.dropna(axis=1, how="all").dropna(axis=0, how="all").reset_index(drop=True)

    if df.empty:
        raise UploadError("File contains no usable rows after removing empty rows/columns.")
    if df.shape[1] < 2:
        raise UploadError("Need at least 2 columns to run any meaningful analysis.")

    meta: Dict[str, Any] = {
        "filename": filename,
        "size_bytes": len(raw),
        "rows": int(df.shape[0]),
        "cols": int(df.shape[1]),
        "sheet_names": sheet_names,
        "selected_sheet": selected_sheet,
    }
    return df, meta


def preview_records(df: pd.DataFrame, n: int = 5) -> List[Dict[str, Any]]:
    """Return the first ``n`` rows as JSON-safe records (NaN → None)."""
    head = df.head(n).where(pd.notnull(df.head(n)), None)
    return head.to_dict(orient="records")
