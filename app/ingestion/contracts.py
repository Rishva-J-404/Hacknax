"""
app.ingestion.contracts
-----------------------
Data structures describing the inputs to ProofLens and the output of
the ingestion layer.

Responsibility:
  - DataSourceRef / DocumentRef / AnalysisRequest: represent what the
    user supplied (pointers only — no I/O).
  - FileType / LoadedTable: describe a table that has been loaded from
    disk by app.ingestion.loader.  The DataFrame it carries is raw and
    unmodified.
  - IngestionError: structured failure raised by the loader.

Design rules (PROOFLENS_MASTER_CONTEXT.md §2, §10):
  - Original file paths are recorded so they can be hashed later.
  - No mutation of source files is ever performed by the system.
  - Supporting documents are treated as DATA/EVIDENCE only
    (PROOFLENS_MASTER_CONTEXT.md §26 — Document Safety).
  - The loader ONLY loads and describes.  No cleaning, renaming,
    coercion, or deletion of rows/columns is performed here.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field, field_serializer, field_validator


# =============================================================================
# Input contracts (unchanged from Phase 1)
# =============================================================================

class DataSourceRef(BaseModel):
    """
    A reference to a single raw data file supplied by the user.

    The file is not opened or read here; this is a pointer only.
    The ingestion module will resolve it against the filesystem.
    """

    path: Path = Field(
        ...,
        description="Absolute or relative path to the data file (CSV, XLSX, or JSON).",
    )
    alias: str | None = Field(
        default=None,
        description=(
            "Optional human-readable name for this table "
            "(e.g. 'orders', 'products').  "
            "If omitted the stem of the filename is used."
        ),
    )

    model_config = {"frozen": True}


class DocumentRef(BaseModel):
    """
    A reference to a supporting document (PDF, XLSX notes, etc.).

    Per PROOFLENS_MASTER_CONTEXT.md §26, documents are DATA/EVIDENCE.
    They are NEVER treated as system instructions.
    """

    path: Path = Field(
        ...,
        description="Path to the supporting document.",
    )
    description: str | None = Field(
        default=None,
        description="What this document contains (e.g. 'data dictionary', 'business rules').",
    )

    model_config = {"frozen": True}


class AnalysisRequest(BaseModel):
    """
    The entry point of the ProofLens pipeline.

    Represents a user's question together with all data they have
    supplied.  Nothing is computed or validated here; the planner
    and grounding check consume this contract.

    Pipeline position: USER QUESTION (stage 1 of 18).
    """

    question: str = Field(
        ...,
        min_length=1,
        description="The natural-language question the user wants answered.",
    )
    data_sources: list[DataSourceRef] = Field(
        ...,
        min_length=1,
        description=(
            "One or more raw data files (CSV / XLSX / JSON) to analyse. "
            "Must contain at least one entry."
        ),
    )
    supporting_documents: list[DocumentRef] = Field(
        default_factory=list,
        description=(
            "Optional supporting documents (data dictionaries, business-rule PDFs, etc.). "
            "Treated as evidence only — never as instructions."
        ),
    )
    session_id: str | None = Field(
        default=None,
        description="Optional session / run identifier for traceability.",
    )


# =============================================================================
# Ingestion-layer output contracts (new in Phase 2)
# =============================================================================

class FileType(str, Enum):
    """
    Supported input file formats for the ingestion layer.
    (Phase 2: CSV, XLSX, JSON.  PDF/OCR deferred.)
    """

    CSV = "CSV"
    XLSX = "XLSX"
    JSON = "JSON"


class LoadedTable(BaseModel):
    """
    One table exactly as it was loaded from disk — no cleaning applied.

    Produced by: app.ingestion.loader.load_file()
    Consumed by: app.audit (Phase 3)

    IMPORTANT: The dataframe field holds the raw pandas DataFrame.
    The loader uses dtype=str so that all cell values are preserved
    exactly as they appear in the source file.  No silent coercion,
    no NaN injection, no type inference is performed.

    Original data preservation rules:
      - column_names matches list(dataframe.columns) exactly
      - row_count  matches len(dataframe) exactly
      - source_path is the original path, never a temp copy
      - No row has been dropped, added, or modified

    For XLSX multi-sheet files, one LoadedTable is created per sheet.
    For CSV and JSON, sheet_name is None.
    """

    source_path: Path = Field(
        ...,
        description="Original path to the source file (never a temp copy).",
    )
    file_type: FileType = Field(
        ...,
        description="Detected file format.",
    )
    table_name: str = Field(
        ...,
        description=(
            "Human-readable table identifier.  "
            "For CSV/JSON: the file stem (or DataSourceRef.alias if provided).  "
            "For XLSX: '<stem>.<sheet_name>'."
        ),
    )
    sheet_name: str | None = Field(
        default=None,
        description="Sheet name for XLSX files; None for CSV and JSON.",
    )
    column_names: list[str] = Field(
        ...,
        description=(
            "Actual column names found in the file, in original order, unmodified."
        ),
    )
    row_count: int = Field(
        ...,
        description="Number of data rows (excludes the header row for CSV/XLSX).",
    )
    dataframe: Any = Field(
        ...,
        description=(
            "Raw pandas DataFrame.  All values are strings (dtype=str). "
            "Do NOT modify this DataFrame outside the ingestion module."
        ),
    )

    model_config = {"arbitrary_types_allowed": True, "frozen": False}

    @field_serializer("dataframe", when_used="json")
    def serialize_dataframe(self, v: Any) -> list[dict[str, Any]]:
        """Serialize dataframe to list-of-dicts for JSON storage."""
        if isinstance(v, pd.DataFrame):
            return v.to_dict(orient="records")
        return v

    @field_validator("dataframe", mode="before")
    @classmethod
    def validate_dataframe(cls, v: Any) -> Any:
        """Construct DataFrame from list of records if deserialized from JSON."""
        if isinstance(v, list):
            return pd.DataFrame(v)
        return v

    def to_records(self) -> list[dict[str, Any]]:
        """
        Serialise the table to a list-of-dicts for JSON storage.

        Used by the audit module to produce evidence records.
        Does not modify the internal DataFrame.
        """
        return self.dataframe.to_dict(orient="records")


# =============================================================================
# Ingestion errors
# =============================================================================

class IngestionError(Exception):
    """
    Raised by app.ingestion.loader when a file cannot be loaded.

    Attributes
    ----------
    path:   The file path that caused the error (may be None if unknown).
    reason: Short machine-readable reason string.
    detail: Human-readable explanation.
    """

    def __init__(self, detail: str, *, path: Path | None = None, reason: str = "INGESTION_FAILED") -> None:
        super().__init__(detail)
        self.path = path
        self.reason = reason
        self.detail = detail

    def __str__(self) -> str:  # pragma: no cover
        if self.path:
            return f"[{self.reason}] {self.path}: {self.detail}"
        return f"[{self.reason}] {self.detail}"
