"""
app.skeptic.contracts
---------------------
Data structures produced by the AI skeptic reviewer.

Responsibility:
  Record the output of a separate LLM review pass that attempts to
  find problems with the plan, code, execution, and draft answer.

Design rules (PROOFLENS_MASTER_CONTEXT.md §17):
  - The skeptic is a REVIEWER, not a source of truth.
  - Deterministic execution and verification remain authoritative.
  - The skeptic cannot override the verification result.
  - The skeptic CAN raise concerns that block the draft answer from
    being emitted — the final decision on those concerns is made by
    the proof module, not the skeptic.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SkepticConcernType(str, Enum):
    """Categories of problems the skeptic is asked to look for."""

    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    INCORRECT_JOIN = "INCORRECT_JOIN"
    MISSING_DATA = "MISSING_DATA"
    DUPLICATE_IMPACT = "DUPLICATE_IMPACT"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    DATE_AMBIGUITY = "DATE_AMBIGUITY"
    CONTRADICTION = "CONTRADICTION"
    FALSE_PREMISE = "FALSE_PREMISE"
    UNSUPPORTED_CONVERSION = "UNSUPPORTED_CONVERSION"
    EXPLANATION_MISMATCH = "EXPLANATION_MISMATCH"
    """
    The draft explanation describes a number that differs from
    the execution result.  This is a critical anti-hallucination check.
    (PROOFLENS_MASTER_CONTEXT.md §2 — never copy LLM number into final result)
    """
    UNSUPPORTED_PRECISION = "UNSUPPORTED_PRECISION"
    """The draft answer claims more precision than the evidence supports."""
    PROVENANCE_MISMATCH = "PROVENANCE_MISMATCH"
    """Cryptographic hashes, worlds, or code versions do not match."""
    OTHER = "OTHER"


class SkepticConcern(BaseModel):
    """A single concern raised by the AI skeptic reviewer."""

    concern_type: SkepticConcernType = Field(
        ...,
        description="Category of problem detected.",
    )
    description: str = Field(
        ...,
        description="Human-readable description of the concern.",
    )
    location: str | None = Field(
        default=None,
        description=(
            "Where the problem was found: "
            "'plan', 'code', 'execution', 'verification', 'draft_answer', etc."
        ),
    )
    severity: str | None = Field(
        default=None,
        description="'blocking' or 'advisory' — set by the skeptic.",
    )

    model_config = {"frozen": True}


class SkepticReview(BaseModel):
    """
    The complete output of one AI skeptic review pass.

    Pipeline position: AI SKEPTIC REVIEW (stage 16 of 18).

    This is consumed by the proof module to decide whether to emit
    the draft answer or block it pending resolution.

    The skeptic is NOT the source of truth.  A concern here does not
    automatically change the verification status.  The proof module
    applies its own deterministic rules.
    """

    concerns: list[SkepticConcern] = Field(
        default_factory=list,
        description="All concerns raised.  Empty means the skeptic found no issues.",
    )
    has_blocking_concerns: bool = Field(
        ...,
        description=(
            "True if any concern has severity == 'blocking'. "
            "Set deterministically by the proof module from the concerns list — "
            "not freely set by the LLM."
        ),
    )
    skeptic_notes: str | None = Field(
        default=None,
        description="Free-text summary from the skeptic LLM (for human review only).",
    )
