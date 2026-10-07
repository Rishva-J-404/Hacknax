"""
app.audit.contracts
-------------------
Data structures produced by the data audit module.

Responsibility:
  Describe data-quality problems found in the raw source files.
  The audit module reads the actual data and produces a structured
  Data Quality Ledger.  This contract defines what issues look like
  and what the ledger looks like.

Design rules (PROOFLENS_MASTER_CONTEXT.md §7):
  - Every issue must be backed by evidence (actual counts, values,
    or column names found in the real data).
  - The audit module NEVER modifies source files.
  - Issues feed the repair decision centre, not the LLM directly.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class IssueType(str, Enum):
    """
    Taxonomy of data-quality issues ProofLens can detect.
    (PROOFLENS_MASTER_CONTEXT.md §7)
    """

    DUPLICATE_ROWS = "DUPLICATE_ROWS"
    DUPLICATE_KEYS = "DUPLICATE_KEYS"
    MISSING_VALUES = "MISSING_VALUES"
    MIXED_CURRENCIES = "MIXED_CURRENCIES"
    MIXED_UNITS = "MIXED_UNITS"
    AMBIGUOUS_DATE_FORMAT = "AMBIGUOUS_DATE_FORMAT"
    ORPHAN_FOREIGN_KEY = "ORPHAN_FOREIGN_KEY"
    CROSS_TABLE_MISMATCH = "CROSS_TABLE_MISMATCH"
    CONTRADICTORY_VALUES = "CONTRADICTORY_VALUES"
    SUSPICIOUS_SCHEMA = "SUSPICIOUS_SCHEMA"
    ANOMALY = "ANOMALY"
    OTHER = "OTHER"


class IssueSeverity(str, Enum):
    """
    How much the issue is likely to affect the analytical result.
    Severity is set deterministically by the audit module — not by the LLM.
    """

    CRITICAL = "CRITICAL"
    """The issue will almost certainly corrupt the result if ignored."""

    HIGH = "HIGH"
    """The issue materially affects the result under common analysis patterns."""

    MEDIUM = "MEDIUM"
    """The issue may affect the result depending on the question asked."""

    LOW = "LOW"
    """The issue is present but unlikely to affect this specific analysis."""

    INFO = "INFO"
    """Informational only — recorded for provenance."""


class DataIssue(BaseModel):
    """
    A single data-quality problem found in one source file or table.

    Pipeline position: DATA AUDIT output → DATA QUALITY LEDGER (stages 4–5).

    This is consumed by:
      - the repair decision centre (to decide which worlds to create)
      - the proof card (to report data quality to the user)
    """

    issue_type: IssueType = Field(
        ...,
        description="The category of data-quality problem.",
    )
    severity: IssueSeverity = Field(
        ...,
        description="How much this issue is likely to impact the analytical result.",
    )
    affected_source: str = Field(
        ...,
        description="Filename or table alias where the issue was detected.",
    )
    affected_columns: list[str] = Field(
        default_factory=list,
        description="Column names involved in this issue.",
    )
    description: str = Field(
        ...,
        description="Human-readable description of the problem.",
    )
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Machine-readable evidence backing this issue. "
            "Examples: {'duplicate_count': 14}, {'missing_pct': 0.12}, "
            "{'currencies_found': ['INR', 'USD']}. "
            "Values must come from actual data inspection — never invented."
        ),
    )

    model_config = {"frozen": True}


class ColumnProfile(BaseModel):
    """
    Summary statistics and observations for a single column.
    All metrics are computed deterministically from the raw data.
    """

    column_name: str = Field(..., description="Name of the column as loaded.")
    inferred_type: str = Field(
        ...,
        description="Inferred type: 'numeric', 'date', 'text', 'boolean', 'empty'.",
    )
    total_count: int = Field(..., description="Total row count.")
    unique_count: int = Field(..., description="Number of distinct non-missing values.")
    missing_count: int = Field(..., description="Count of null, empty, or whitespace-only values.")
    missing_pct: float = Field(..., description="Percentage of missing values (0.0 to 1.0).")
    sample_values: list[str] = Field(
        default_factory=list,
        description="Sample distinct non-missing values.",
    )
    detected_currencies: list[str] = Field(
        default_factory=list,
        description="Currency codes/symbols detected in this column.",
    )
    detected_units: list[str] = Field(
        default_factory=list,
        description="Unit indicators detected in this column.",
    )
    is_potential_key: bool = Field(
        default=False,
        description="True if column appears to be a unique or primary key.",
    )


class TableProfile(BaseModel):
    """
    Summary statistics for a single loaded table, as computed by the audit module.
    All values come from actual execution against the real data.
    """

    source: str = Field(..., description="Filename or table alias.")
    row_count: int = Field(..., description="Total number of rows in the raw file.")
    column_count: int = Field(..., description="Number of columns.")
    column_names: list[str] = Field(..., description="Actual column names found.")
    column_profiles: list[ColumnProfile] = Field(
        default_factory=list,
        description="Detailed profile for each column in the table.",
    )
    issues: list[DataIssue] = Field(
        default_factory=list,
        description="All data-quality issues detected in this table.",
    )
    dataset_sha256: str | None = Field(
        default=None,
        description=(
            "SHA-256 hash of the raw file content. "
            "Populated by the audit module for provenance. "
            "(PROOFLENS_MASTER_CONTEXT.md §23)"
        ),
    )


class DataQualityLedger(BaseModel):
    """
    The complete data-quality report produced for one AnalysisRequest.

    Pipeline position: DATA QUALITY LEDGER (stage 5 of 18).

    This is the single authoritative source of truth about data quality
    for a given run.  It is stored as part of the proof.
    """

    session_id: str | None = Field(
        default=None,
        description="Ties this ledger to a specific analysis run.",
    )
    audit_timestamp: str | None = Field(
        default=None,
        description="ISO 8601 UTC timestamp of when the audit was performed.",
    )
    table_profiles: list[TableProfile] = Field(
        default_factory=list,
        description="One profile per loaded table.",
    )
    all_issues: list[DataIssue] = Field(
        default_factory=list,
        description="Flat list of all issues across all tables (for quick filtering).",
    )
    has_critical_issues: bool = Field(
        default=False,
        description=(
            "True if any CRITICAL-severity issue was detected. "
            "The repair decision centre must address critical issues before proceeding."
        ),
    )

