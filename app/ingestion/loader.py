"""
app.ingestion.loader
--------------------
Deterministic, read-only file loader for the ProofLens ingestion layer.

Public API
----------
    detect_file_type(path: Path) -> FileType
    load_file(ref: DataSourceRef) -> list[LoadedTable]

Supported formats (Phase 2)
----------------------------
    CSV   — any delimiter-separated text file with a .csv extension
    XLSX  — Excel workbook; one LoadedTable per sheet
    JSON  — flat array-of-objects (nested JSON raises IngestionError)

CORE RULE (PROOFLENS_MASTER_CONTEXT.md §6, §10):
    The loader ONLY loads and describes.
    It NEVER:
      - removes duplicate rows
      - fills missing / null values
      - parses or converts dates
      - converts currencies or units
      - renames columns
      - infers business meaning
      - deletes rows
      - alters cell values

All DataFrames are loaded with dtype=str so that every cell value is
preserved exactly as it appears in the source file.

For CSV, keep_default_na=False and na_values=[] are set so that strings
like "NA", "N/A", "nan", "" are NOT silently converted to NaN.
The audit stage (Phase 3) is responsible for detecting missing values.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.ingestion.contracts import (
    DataSourceRef,
    FileType,
    IngestionError,
    LoadedTable,
)

# ---------------------------------------------------------------------------
# Supported extensions
# ---------------------------------------------------------------------------

_EXTENSION_MAP: dict[str, FileType] = {
    ".csv": FileType.CSV,
    ".xlsx": FileType.XLSX,
    ".xls": FileType.XLSX,
    ".json": FileType.JSON,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_file_type(path: Path) -> FileType:
    """
    Return the FileType for *path* based solely on its extension.

    Raises
    ------
    IngestionError(reason='UNSUPPORTED_FILE_TYPE')
        If the extension is not in the supported set.
    """
    ext = path.suffix.lower()
    if ext not in _EXTENSION_MAP:
        raise IngestionError(
            f"Unsupported file extension '{ext}'. "
            f"Supported: {', '.join(_EXTENSION_MAP)}",
            path=path,
            reason="UNSUPPORTED_FILE_TYPE",
        )
    return _EXTENSION_MAP[ext]


def load_file(ref: DataSourceRef) -> list[LoadedTable]:
    """
    Load all tables from the file described by *ref*.

    Returns a list because XLSX workbooks may contain multiple sheets.
    CSV and JSON always return a single-element list.

    Parameters
    ----------
    ref:
        A DataSourceRef pointing to the file to load.

    Returns
    -------
    list[LoadedTable]
        One LoadedTable per table/sheet found in the file.
        DataFrames are raw (dtype=str); values are exactly as on disk.

    Raises
    ------
    IngestionError(reason='FILE_NOT_FOUND')
        If the path does not exist.
    IngestionError(reason='UNSUPPORTED_FILE_TYPE')
        If the extension is not supported.
    IngestionError(reason='READ_ERROR')
        If pandas or json cannot parse the file.
    IngestionError(reason='NON_TABULAR_JSON')
        If the JSON file is not a flat array-of-objects.
    IngestionError(reason='CORRUPT_XLSX')
        If openpyxl cannot open the workbook.
    """
    path = ref.path

    # ── 1. Existence check ────────────────────────────────────────────────
    if not path.exists():
        raise IngestionError(
            f"File not found: {path}",
            path=path,
            reason="FILE_NOT_FOUND",
        )

    # ── 2. Format detection ───────────────────────────────────────────────
    file_type = detect_file_type(path)

    # ── 3. Dispatch ───────────────────────────────────────────────────────
    alias = ref.alias  # may be None; loaders use path.stem as fallback

    if file_type == FileType.CSV:
        return _load_csv(path, alias)
    if file_type == FileType.XLSX:
        return _load_xlsx(path, alias)
    if file_type == FileType.JSON:
        return _load_json(path, alias)

    # Should be unreachable after detect_file_type, but be explicit.
    raise IngestionError(  # pragma: no cover
        f"Unhandled file type: {file_type}",
        path=path,
        reason="UNSUPPORTED_FILE_TYPE",
    )


# ---------------------------------------------------------------------------
# Internal loaders
# ---------------------------------------------------------------------------

def _load_csv(path: Path, alias: str | None) -> list[LoadedTable]:
    """
    Load a CSV file preserving all values exactly as they appear on disk.

    dtype=str          — no silent numeric / date coercion
    keep_default_na=False + na_values=[] — "NA", "N/A", "", "nan" etc.
                        stay as plain strings; NaN detection is the
                        audit module's responsibility.
    encoding_errors='replace' — malformed bytes produce a replacement
                        character rather than an exception.
    """
    try:
        df = pd.read_csv(
            path,
            dtype=str,
            keep_default_na=False,
            na_values=[],
            encoding_errors="replace",
        )
    except Exception as exc:
        raise IngestionError(
            f"Could not read CSV: {exc}",
            path=path,
            reason="READ_ERROR",
        ) from exc

    table_name = alias or path.stem
    return [
        LoadedTable(
            source_path=path,
            file_type=FileType.CSV,
            table_name=table_name,
            sheet_name=None,
            column_names=list(df.columns),
            row_count=len(df),
            dataframe=df,
        )
    ]


def _load_xlsx(path: Path, alias: str | None) -> list[LoadedTable]:
    """
    Load every sheet of an XLSX workbook.

    Returns one LoadedTable per sheet.
    sheet_name is set to the worksheet name (e.g. "Sheet1").
    table_name follows the pattern '<file_stem>.<sheet_name>'.

    dtype=str and keep_default_na=False / na_values=[] apply identically
    to the CSV loader — all values are preserved as raw strings.
    """
    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
    except Exception as exc:
        raise IngestionError(
            f"Could not open XLSX workbook: {exc}",
            path=path,
            reason="CORRUPT_XLSX",
        ) from exc

    tables: list[LoadedTable] = []
    stem = alias or path.stem

    for sheet in xl.sheet_names:
        try:
            df = xl.parse(
                sheet,
                dtype=str,
                keep_default_na=False,
                na_values=[],
            )
        except Exception as exc:
            raise IngestionError(
                f"Could not parse sheet '{sheet}': {exc}",
                path=path,
                reason="READ_ERROR",
            ) from exc

        tables.append(
            LoadedTable(
                source_path=path,
                file_type=FileType.XLSX,
                table_name=f"{stem}.{sheet}",
                sheet_name=sheet,
                column_names=list(df.columns),
                row_count=len(df),
                dataframe=df,
            )
        )

    return tables


def _load_json(path: Path, alias: str | None) -> list[LoadedTable]:
    """
    Load a flat array-of-objects JSON file.

    Accepted structure:
        [{"col_a": val, "col_b": val, ...}, ...]

    Rejected structures (raise IngestionError with reason='NON_TABULAR_JSON'):
        - JSON object at the top level: {...}
        - Array of non-objects:         [1, 2, 3]
        - Nested objects inside rows:   [{"col": {"sub": 1}}]

    dtype=str is applied after initial parsing so that numeric values
    are cast to their string representation (e.g. 123 → "123") rather
    than being stored as Python int/float.  This is consistent with
    the CSV/XLSX loaders and ensures the audit module sees uniform
    string data.
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
    except Exception as exc:
        raise IngestionError(
            f"Could not read JSON: {exc}",
            path=path,
            reason="READ_ERROR",
        ) from exc

    # ── Structure validation ──────────────────────────────────────────────
    if not isinstance(data, list):
        raise IngestionError(
            "JSON root must be an array (list), not an object or scalar. "
            "Only flat array-of-objects JSON is supported in Phase 2.",
            path=path,
            reason="NON_TABULAR_JSON",
        )

    if len(data) > 0:
        # Check that each element is a plain dict with no nested dicts/lists.
        for i, row in enumerate(data):
            if not isinstance(row, dict):
                raise IngestionError(
                    f"JSON array element at index {i} is not an object (dict). "
                    "Only flat array-of-objects JSON is supported in Phase 2.",
                    path=path,
                    reason="NON_TABULAR_JSON",
                )
            for key, val in row.items():
                if isinstance(val, (dict, list)):
                    raise IngestionError(
                        f"JSON field '{key}' at index {i} contains a nested "
                        "object or array.  Only flat (non-nested) JSON is "
                        "supported in Phase 2.",
                        path=path,
                        reason="NON_TABULAR_JSON",
                    )

    # ── Build DataFrame from validated data ───────────────────────────────
    try:
        if len(data) == 0:
            # Empty array — produce an empty DataFrame.
            # No column names can be inferred; return an empty table.
            df = pd.DataFrame()
        else:
            df = pd.DataFrame(data)
            # Cast all columns to str, consistent with CSV/XLSX loaders.
            df = df.astype(str)
    except Exception as exc:
        raise IngestionError(
            f"Could not construct DataFrame from JSON: {exc}",
            path=path,
            reason="READ_ERROR",
        ) from exc

    table_name = alias or path.stem
    return [
        LoadedTable(
            source_path=path,
            file_type=FileType.JSON,
            table_name=table_name,
            sheet_name=None,
            column_names=list(df.columns),
            row_count=len(df),
            dataframe=df,
        )
    ]
