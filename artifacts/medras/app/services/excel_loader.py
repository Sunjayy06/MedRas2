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

    # Header sanity: if every cell in row 0 (now the column names) parses as a
    # number, the file probably has no real header row. We surface this so the
    # UI can ask the user.
    numeric_header = all(_looks_numeric(str(c)) for c in df.columns)

    meta: Dict[str, Any] = {
        "filename": filename,
        "size_bytes": len(raw),
        "rows": int(df.shape[0]),
        "cols": int(df.shape[1]),
        "sheet_names": sheet_names,
        "selected_sheet": selected_sheet,
        "raw_bytes": raw,  # kept in process memory so /select-sheet can re-parse
        "header_looks_numeric": numeric_header,
    }
    return df, meta


def combine_sheets(
    *,
    filename: str,
    raw: bytes,
    sheet_names: List[str],
    add_group_column: bool = True,
    group_column_name: str = "Group",
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Concatenate the rows of multiple sheets into one DataFrame.

    Sheets that share columns line up; columns missing from a given sheet are
    filled with NaN (pandas default). When ``add_group_column`` is True, an
    extra column (default name "Group") is prepended to record which sheet
    each row came from — that's the common "two groups in two sheets" pattern.

    Returns ``(df, meta)`` shaped like :func:`parse_upload`.
    """
    if not raw:
        raise UploadError("Uploaded file is empty.")
    if len(raw) > MAX_BYTES:
        raise UploadError(
            f"File is {len(raw) // 1024} KB — limit is {MAX_BYTES // 1024} KB."
        )
    if len(sheet_names) < 2:
        raise UploadError("Pick at least two sheets to merge.")

    name = (filename or "").lower()
    if not (name.endswith(".xls") or name.endswith(".xlsx")):
        raise UploadError("Sheet merging only applies to Excel files.")

    engine = "openpyxl" if name.endswith(".xlsx") else "xlrd"
    try:
        xls = pd.ExcelFile(io.BytesIO(raw), engine=engine)
    except Exception as exc:  # noqa: BLE001
        raise UploadError(f"Could not read file: {exc}") from exc

    available = list(xls.sheet_names)
    missing = [s for s in sheet_names if s not in available]
    if missing:
        raise UploadError(
            f"These sheets are not in the file: {', '.join(missing)}."
        )

    # Read each sheet first, then pick a group-column name that doesn't collide
    # with ANY of the union of columns across all sheets. (Checking only the
    # first sheet would crash later if a later sheet already had "Group".)
    raw_pieces: List[Tuple[str, pd.DataFrame]] = []
    union_cols: set = set()
    for sheet in sheet_names:
        try:
            piece = pd.read_excel(xls, sheet_name=sheet)
        except Exception as exc:  # noqa: BLE001
            raise UploadError(f"Could not read sheet '{sheet}': {exc}") from exc
        piece.columns = [str(c).strip() for c in piece.columns]
        # Drop fully empty rows/cols *per sheet* before concat so blank trailing
        # rows in one sheet don't poison the union with NaN noise.
        piece = piece.dropna(axis=1, how="all").dropna(axis=0, how="all")
        union_cols.update(piece.columns)
        raw_pieces.append((sheet, piece))

    safe_group_col = group_column_name
    if add_group_column:
        bumped = group_column_name
        i = 2
        while bumped in union_cols:
            bumped = f"{group_column_name}_{i}"
            i += 1
        safe_group_col = bumped

    pieces: List[pd.DataFrame] = []
    for sheet, piece in raw_pieces:
        if add_group_column:
            piece.insert(0, safe_group_col, sheet)
        pieces.append(piece.reset_index(drop=True))

    df = pd.concat(pieces, axis=0, ignore_index=True, sort=False)
    df = df.dropna(axis=1, how="all").dropna(axis=0, how="all").reset_index(drop=True)
    if df.empty:
        raise UploadError("Merged sheets contained no usable rows.")
    if df.shape[1] < 2:
        raise UploadError("Merged sheets need at least 2 columns to analyse.")

    numeric_header = all(_looks_numeric(str(c)) for c in df.columns)
    selected_label = " + ".join(sheet_names)
    meta: Dict[str, Any] = {
        "filename": filename,
        "size_bytes": len(raw),
        "rows": int(df.shape[0]),
        "cols": int(df.shape[1]),
        "sheet_names": available,
        "selected_sheet": selected_label,
        "merged_sheets": list(sheet_names),
        "merge_group_column": safe_group_col if add_group_column else None,
        "raw_bytes": raw,
        "header_looks_numeric": numeric_header,
    }
    return df, meta


def _looks_numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def detect_repeated_ids(df: pd.DataFrame, id_columns: List[str]) -> Dict[str, Any]:
    """Return per-ID-column repeat statistics for the follow-up-data prompt."""
    out: Dict[str, Any] = {"any_repeats": False, "columns": []}
    for col in id_columns:
        if col not in df.columns:
            continue
        counts = df[col].value_counts(dropna=True)
        repeats = int((counts > 1).sum())
        out["columns"].append(
            {
                "column": col,
                "unique_ids": int(counts.shape[0]),
                "repeated_ids": repeats,
                "max_repeats": int(counts.max()) if not counts.empty else 0,
            }
        )
        if repeats > 0:
            out["any_repeats"] = True
    return out


def preview_records(df: pd.DataFrame, n: int = 5) -> List[Dict[str, Any]]:
    """Return the first ``n`` rows as JSON-safe records (NaN → None)."""
    head = df.head(n).where(pd.notnull(df.head(n)), None)
    return head.to_dict(orient="records")
