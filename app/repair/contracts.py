"""
app.repair.contracts
--------------------
Data structures describing repair policies and the worlds they produce.

Responsibility:
  Describe how each data-quality issue will be handled (the POLICY)
  and what alternative dataset variants (WORLDS) result from applying
  those policies.

Design rules (PROOFLENS_MASTER_CONTEXT.md §6):
  - Original data is NEVER modified.
  - Each world is an explicitly-described, controlled variant of the
    original data.
  - The SAME analysis code must run against every world.
  - Different worlds must NOT use different analysis logic.
  - All policy decisions must be recorded with a rationale so they
    appear in the proof card.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.audit.contracts import IssueType
from app.ingestion.contracts import LoadedTable


class DuplicateAction(str, Enum):
    """Policy choices for handling duplicate rows/keys."""

    KEEP = "KEEP"
    """Keep all rows including duplicates (World A / default baseline)."""

    KEEP_ALL = "KEEP_ALL"
    """Synonym for KEEP."""

    EXACT_DEDUP = "EXACT_DEDUP"
    """Remove exact complete-row duplicate rows, keeping first occurrence."""

    DROP_EXACT_DUPLICATES = "DROP_EXACT_DUPLICATES"
    """Synonym for EXACT_DEDUP."""

    DROP_KEY_DUPLICATES = "DROP_KEY_DUPLICATES"
    """Keep first occurrence per primary key, drop the rest."""

    REVIEW = "REVIEW"
    """Flag duplicate rows for human review; keep data unchanged."""

    COMPARE = "COMPARE"
    """Generate separate worlds for KEEP vs EXACT_DEDUP to measure impact."""


class MissingValueAction(str, Enum):
    """Policy choices for handling missing / null values."""

    LEAVE = "LEAVE"
    """Retain rows with null/missing values unchanged."""

    KEEP_NULLS = "KEEP_NULLS"
    """Synonym for LEAVE."""

    DROP = "DROP"
    """Remove rows containing missing values in target columns."""

    DROP_ROWS = "DROP_ROWS"
    """Synonym for DROP."""

    FILL_ZERO = "FILL_ZERO"
    """Replace missing values with 0 (allowed on numeric columns only)."""

    FILL_MEDIAN = "FILL_MEDIAN"
    """Replace missing values with column median (numeric columns only)."""

    FILL_COLUMN_MEAN = "FILL_COLUMN_MEAN"
    """Replace missing values with column mean (numeric columns only)."""

    COMPARE = "COMPARE"
    """Generate separate worlds for LEAVE vs DROP (or FILL) to measure impact."""


class DateFormatAction(str, Enum):
    """Policy choices for resolving ambiguous date formats."""

    KEEP_SOURCE = "KEEP_SOURCE"
    """Keep original source date strings unchanged."""

    DD_MM_YYYY = "DD_MM_YYYY"
    """Interpret day-first: DD/MM/YYYY."""

    MM_DD_YYYY = "MM_DD_YYYY"
    """Interpret month-first: MM/DD/YYYY."""

    YYYY_MM_DD = "YYYY_MM_DD"
    """Interpret ISO format: YYYY-MM-DD."""

    COMPARE = "COMPARE"
    """Generate separate worlds for DD_MM_YYYY vs MM_DD_YYYY to measure impact."""


class CurrencyAction(str, Enum):
    """Policy choices for handling mixed-currency columns."""

    KEEP_SEPARATE = "KEEP_SEPARATE"
    """Do not convert or combine currencies across rows."""

    ASSUME_SINGLE_CURRENCY = "ASSUME_SINGLE_CURRENCY"
    """Treat the whole column as one currency (must specify which in parameters)."""

    USE_SUPPLIED_RATES = "USE_SUPPLIED_RATES"
    """Convert amounts to a base currency using explicitly supplied exchange rates."""

    CONVERT_TO_BASE = "CONVERT_TO_BASE"
    """Synonym for USE_SUPPLIED_RATES."""

    DROP_FOREIGN_CURRENCY = "DROP_FOREIGN_CURRENCY"
    """Remove rows whose currency does not match the majority/specified currency."""

    COMPARE = "COMPARE"
    """Generate separate worlds for KEEP_SEPARATE vs USE_SUPPLIED_RATES."""


class RepairHistoryEntry(BaseModel):
    """
    Machine-readable record of one transformation applied to produce a RepairWorld.
    (PROOFLENS_MASTER_CONTEXT.md §6 — No silent repairs)
    """

    operation: str = Field(
        ...,
        description="Operation performed: 'EXACT_DEDUP', 'DROP_MISSING', 'FILL_ZERO', 'FILL_MEDIAN', 'DATE_CONVERSION', 'CURRENCY_CONVERSION', 'KEEP'.",
    )
    table: str = Field(..., description="Table name that was transformed.")
    column: str | None = Field(default=None, description="Affected column if column-specific.")
    rows_before: int = Field(..., description="Row count before the operation.")
    rows_after: int = Field(..., description="Row count after the operation.")
    affected_rows: int = Field(..., description="Number of rows modified or dropped.")
    reason: str = Field(default="", description="Rationale or policy citation.")
    details: dict[str, Any] = Field(default_factory=dict, description="Additional metadata.")


class RepairPolicy(BaseModel):
    """
    One explicit decision about how to handle a specific data-quality issue.

    Pipeline position: REPAIR / AMBIGUITY DECISION CENTER output.

    A set of RepairPolicy objects together define one RepairWorld.
    Every policy must have a rationale so the proof card can explain
    what assumptions were made.
    """

    issue_type: IssueType = Field(
        ...,
        description="Which category of data-quality issue this policy addresses.",
    )
    selected_action: str = Field(
        ...,
        description=(
            "The chosen action from the relevant *Action enum "
            "(DuplicateAction, MissingValueAction, DateFormatAction, CurrencyAction, etc.). "
            "Stored as a plain string so new action types can be added without "
            "changing this model."
        ),
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Extra parameters needed to apply the action "
            "(e.g. {'base_currency': 'INR', 'rates': {'USD': 83.5}})."
        ),
    )
    affected_sources: list[str] = Field(
        default_factory=list,
        description="Table aliases or filenames this policy applies to.",
    )
    rationale: str = Field(
        ...,
        description=(
            "Human-readable explanation of why this policy was chosen. "
            "This appears verbatim in the proof card under 'Repair Policy'."
        ),
    )

    model_config = {"frozen": True}


class RepairWorld(BaseModel):
    """
    A controlled alternative dataset variant produced by applying a set
    of repair policies to the original data.

    Pipeline position: REPAIR WORLDS (stage 7 of 18).

    KEY RULE (PROOFLENS_MASTER_CONTEXT.md §6):
      The SAME analysis code runs against every world.
      Different worlds must NOT use different analysis logic.
      Original data is NEVER modified.
    """

    world_id: str = Field(
        ...,
        description="Deterministic unique identifier for this world (e.g. 'world_001', 'world_A').",
    )
    description: str = Field(
        ...,
        description=(
            "Human-readable description of what distinguishes this world "
            "(e.g. 'Keep all duplicates; drop null rows; DD/MM/YYYY dates')."
        ),
    )
    policies: list[RepairPolicy] = Field(
        ...,
        min_length=0,
        description=(
            "The repair policies applied to produce this world. "
            "An empty list means 'use the original data unmodified'."
        ),
    )
    source_file_refs: list[str] = Field(
        default_factory=list,
        description=(
            "Original source file paths that were used as the base for this world. "
            "These must match the DataSourceRef.path values from the AnalysisRequest."
        ),
    )
    world_data_path: Path | None = Field(
        default=None,
        description=(
            "Path to the directory containing the repaired data files for this world. "
            "Located under data/worlds/<world_id>/."
        ),
    )
    world_hash: str | None = Field(
        default=None,
        description=(
            "SHA-256 hash of the world's data content. "
            "Populated by the repair module for provenance. "
            "(PROOFLENS_MASTER_CONTEXT.md §23)"
        ),
    )
    repair_history: list[RepairHistoryEntry] = Field(
        default_factory=list,
        description="Machine-readable audit trail of every transformation in this world.",
    )
    repaired_tables: list[LoadedTable] = Field(
        default_factory=list,
        description="In-memory LoadedTable instances carrying repaired DataFrame copies.",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Assumptions associated with this world (e.g. 'Interpreted ambiguous dates as DD/MM/YYYY').",
    )
    is_safe: bool = Field(
        default=True,
        description="True if all repairs were performed safely; False if unsafe/unparseable values were encountered.",
    )
    safety_issues: list[str] = Field(
        default_factory=list,
        description="Warnings or errors explaining why a world might be unsafe.",
    )

    model_config = {"arbitrary_types_allowed": True, "frozen": False}


class RepairError(Exception):
    """
    Raised when a requested repair action cannot be performed safely or is unsupported.
    """

    def __init__(
        self,
        detail: str,
        *,
        reason: str = "UNSAFE_REPAIR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail
        self.details = details or {}

    def __str__(self) -> str:
        return f"[{self.reason}] {self.detail}"
