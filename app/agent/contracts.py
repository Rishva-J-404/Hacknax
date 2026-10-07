"""
app.agent.contracts
-------------------
Data structures produced by the Qwen planner.

Responsibility:
  Describe the *plan* that the LLM (Qwen) returns for a given
  AnalysisRequest.  The plan describes WHAT to compute and HOW to
  structure the computation — it does NOT contain the computed number.

Design rules (PROOFLENS_MASTER_CONTEXT.md §9):
  - Qwen is responsible for the plan, NOT for numerical truth.
  - If the data cannot answer the question, the plan status must be
    UNANSWERABLE with a reason.
  - The LLM cannot set verification status.
  - Prefer strongly typed, structured output.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PlanStatus(str, Enum):
    """
    Whether the planner believes the question is answerable.

    PROOFLENS_MASTER_CONTEXT.md §9 requires explicit structured
    signals for unanswerable or ambiguous situations.
    """

    READY = "READY"
    """Planner believes the data is sufficient to attempt an answer."""

    UNANSWERABLE = "UNANSWERABLE"
    """
    Required data is unavailable.
    The system must refuse to produce a number.
    (PROOFLENS_MASTER_CONTEXT.md §8 — Question Grounding)
    """

    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    """
    The question is ambiguous enough that the planner cannot determine
    a single unambiguous interpretation without more information.
    """

    AMBIGUOUS = "AMBIGUOUS"
    """
    Multiple valid interpretations exist in columns, dates, or joins.
    """


class UnanswerableReason(str, Enum):
    """Structured reason codes for UNANSWERABLE and AMBIGUOUS plans."""

    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    MISSING_TABLE = "MISSING_TABLE"
    NO_DATA_SOURCES = "NO_DATA_SOURCES"
    INSUFFICIENT_DATE_RANGE = "INSUFFICIENT_DATE_RANGE"
    METRIC_NOT_COMPUTABLE = "METRIC_NOT_COMPUTABLE"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"
    AMBIGUOUS_COLUMN = "AMBIGUOUS_COLUMN"
    AMBIGUOUS_DATE = "AMBIGUOUS_DATE"
    CONTRADICTORY_DATA = "CONTRADICTORY_DATA"
    OTHER = "OTHER"


class ColumnRef(BaseModel):
    """A reference to a specific column within a named table."""

    table: str = Field(..., description="Table alias or filename stem.")
    column: str = Field(..., description="Column name as it appears in the data.")

    model_config = {"frozen": True}


class FilterSpec(BaseModel):
    """A single filter condition to be applied during analysis."""

    column: ColumnRef
    operator: str = Field(
        ...,
        description="Comparison operator: ==, !=, >, >=, <, <=, in, not_in.",
    )
    value: Any = Field(..., description="The value to compare against.")

    model_config = {"frozen": True}


class AggregationSpec(BaseModel):
    """The aggregation the planner intends to compute."""

    column: ColumnRef
    operation: str = Field(
        ...,
        description="Aggregation function: sum, mean, count, min, max, median.",
    )
    unit: str | None = Field(
        default=None,
        description="Expected unit of the result (e.g. 'INR', 'USD', 'units').",
    )

    model_config = {"frozen": True}


class AmbiguityFlag(BaseModel):
    """
    A potential ambiguity the planner has identified in the data or question.

    The planner *identifies* ambiguities — the repair module *resolves* them.
    """

    description: str = Field(
        ...,
        description="Human-readable description of the ambiguity.",
    )
    affected_columns: list[ColumnRef] = Field(
        default_factory=list,
        description="Which columns are involved in the ambiguity.",
    )
    example: str | None = Field(
        default=None,
        description="A concrete example of the ambiguity (e.g. '01/02/2024 — DD/MM or MM/DD?').",
    )

    model_config = {"frozen": True}


class AnalysisPlan(BaseModel):
    """
    The structured plan produced by the Qwen planner for one AnalysisRequest.

    Pipeline position: QWEN PLANNER output (stage 2 of 18).

    This contract is consumed by:
      - the grounding check (to decide if the plan is viable)
      - the audit module (to know which tables/columns to profile)
      - the execution module (to generate analysis code)

    IMPORTANT: This model describes WHAT to compute.
    It does NOT contain computed numbers.
    The LLM cannot set verification status through this model.
    """

    question: str = Field(..., description="The original user question, verbatim.")
    status: PlanStatus = Field(
        ...,
        description="Whether the planner considers this question answerable.",
    )

    # ── Unanswerable path ────────────────────────────────────────────────────
    unanswerable_reason: UnanswerableReason | None = Field(
        default=None,
        description="Populated when status == UNANSWERABLE.",
    )
    unanswerable_evidence: str | None = Field(
        default=None,
        description=(
            "Human-readable explanation of why the question cannot be answered "
            "(e.g. 'No profit or cost field is available.')."
        ),
    )

    # ── Answerable path ──────────────────────────────────────────────────────
    required_tables: list[str] = Field(
        default_factory=list,
        description="Table aliases or filename stems needed for this analysis.",
    )
    required_columns: list[ColumnRef] = Field(
        default_factory=list,
        description="Specific columns the analysis will read.",
    )
    filters: list[FilterSpec] = Field(
        default_factory=list,
        description="Filters to apply before aggregation.",
    )
    aggregation: AggregationSpec | None = Field(
        default=None,
        description="The primary aggregation to compute.",
    )
    join_keys: list[tuple[ColumnRef, ColumnRef]] = Field(
        default_factory=list,
        description=(
            "Pairs of (left_column, right_column) describing intended table joins. "
            "Stored as a list of two-element lists for JSON serialisation."
        ),
    )
    group_by: list[ColumnRef] = Field(
        default_factory=list,
        description="Columns to group by before aggregation.",
    )
    sort_by: ColumnRef | None = Field(
        default=None,
        description="Column to sort the result by.",
    )
    sort_ascending: bool = Field(
        default=True,
        description="Sort direction (True = ascending, False = descending).",
    )
    limit: int | None = Field(
        default=None,
        description="Row limit (for Top-N queries).",
    )
    analysis_intent: str | None = Field(
        default=None,
        description="Machine-readable summary of analysis intent (e.g. 'SUM_REVENUE', 'TOP_PRODUCT').",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description=(
            "Explicit assumptions the planner is making "
            "(e.g. 'treating currency column as INR throughout')."
        ),
    )
    ambiguity_flags: list[AmbiguityFlag] = Field(
        default_factory=list,
        description=(
            "Ambiguities the planner detected. "
            "Each flag may produce one or more repair worlds."
        ),
    )
    planner_notes: str | None = Field(
        default=None,
        description="Free-text notes from the planner (for human review only).",
    )
