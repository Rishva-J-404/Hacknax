"""
app.truth.contracts
-------------------
Data structures for claim extraction and the truthfulness gate.

Responsibility:
  After the draft answer is written, parse every factual claim it
  makes and verify each claim against the execution record.

Design rules (PROOFLENS_MASTER_CONTEXT.md §18):
  - Every numerical value, percentage, count, date, and comparison
    in the draft answer must be extracted as a separate Claim.
  - Each Claim must link to code output, verification, and source
    evidence before it is considered SUPPORTED.
  - An UNSUPPORTED claim causes the answer to be BLOCKED.
  - This is a core anti-hallucination feature.

The TruthStatus enum is the shared status vocabulary used by the
proof card and the final answer/refuse decision.
(PROOFLENS_MASTER_CONTEXT.md §19)
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class TruthStatus(str, Enum):
    """
    The six allowed final statuses for a ProofLens answer.
    (PROOFLENS_MASTER_CONTEXT.md §19)

    CRITICAL RULE:
      These statuses are set DETERMINISTICALLY by the verification
      and truth modules.  The LLM cannot freely set any of these values.
    """

    VERIFIED = "VERIFIED"
    """
    Both Pandas and DuckDB paths agree.
    All mandatory checks pass.
    All claims are supported by execution evidence.
    """

    VERIFIED_WITH_ASSUMPTION = "VERIFIED_WITH_ASSUMPTION"
    """
    Passes verification, but one or more explicit assumptions were made
    (e.g. treating ambiguous dates as DD/MM/YYYY).
    Assumptions are documented in the proof card.
    """

    AMBIGUOUS = "AMBIGUOUS"
    """
    Different plausible interpretations produce materially different results.
    The answer depends on a data-quality or interpretation policy choice.
    """

    CONTRADICTED = "CONTRADICTED"
    """
    Two or more sources provide conflicting values for the same fact.
    """

    NOT_VERIFIED = "NOT_VERIFIED"
    """
    The Pandas and DuckDB results do not match, or a critical
    verification check failed.
    """

    UNANSWERABLE = "UNANSWERABLE"
    """
    The required data is not available in the supplied sources.
    The system refuses to produce a number.
    (PROOFLENS_MASTER_CONTEXT.md §8 — Question Grounding)
    """


class ClaimType(str, Enum):
    """The type of factual assertion made in the draft answer."""

    NUMERICAL_VALUE = "NUMERICAL_VALUE"
    PERCENTAGE = "PERCENTAGE"
    COUNT = "COUNT"
    DATE = "DATE"
    COMPARISON = "COMPARISON"
    """e.g. 'revenue increased', 'region A is highest'"""
    FACTUAL_STATEMENT = "FACTUAL_STATEMENT"
    """Any other verifiable factual assertion."""


class EvidenceRef(BaseModel):
    """A pointer to the evidence that supports (or refutes) a claim."""

    evidence_type: str = Field(
        ...,
        description=(
            "What kind of evidence this is: "
            "'execution_stdout', 'duckdb_result', 'source_cell', "
            "'verification_check', 'lineage'."
        ),
    )
    reference: str = Field(
        ...,
        description=(
            "Human-readable pointer to the evidence "
            "(e.g. 'world_A execution stdout line 1', "
            "'orders.csv row 42 column revenue')."
        ),
    )
    value: str | None = Field(
        default=None,
        description="The actual value found at this evidence location.",
    )

    model_config = {"frozen": True}


from typing import Any


class Claim(BaseModel):
    """
    A single verifiable assertion extracted from the draft answer.

    Pipeline position: CLAIM EXTRACTION → CLAIM→EVIDENCE MATCHING
    (stages 18–19 of 18).

    Every Claim must be either SUPPORTED (linked to evidence) or
    UNSUPPORTED (which blocks the answer from being emitted).
    """

    claim_text: str = Field(
        ...,
        description="The exact text of the claim as it appears in the draft answer.",
    )
    claim_type: ClaimType = Field(
        ...,
        description="What kind of assertion this is.",
    )
    numerical_value: float | int | None = Field(
        default=None,
        description=(
            "The numerical value of the claim, if applicable. "
            "Must match the execution output — NOT the LLM's own wording."
        ),
    )
    unit: str | None = Field(
        default=None,
        description="Unit of the numerical value (e.g. 'INR', '%', 'orders').",
    )
    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list,
        description=(
            "All pieces of evidence that support this claim. "
            "Must be non-empty for the claim to be SUPPORTED."
        ),
    )
    supported: bool = Field(
        ...,
        description=(
            "True only if at least one evidence_ref links this claim to "
            "actual code execution output or verified data. "
            "Set deterministically by the truth module — not by the LLM."
        ),
    )
    subject: str | None = Field(
        default=None,
        description="The subject entity or metric of the claim (e.g. 'revenue', 'growth rate').",
    )
    relevant_period: str | None = Field(
        default=None,
        description="Relevant year or time interval associated with the claim.",
    )
    status: TruthStatus = Field(
        default=TruthStatus.NOT_VERIFIED,
        description="Claim-level truth status assigned by evidence matching.",
    )
    mismatch_reason: str | None = Field(
        default=None,
        description="Explanation if claim is contradicted or unsupported.",
    )
    normalized_value: float | int | None = Field(
        default=None,
        description="Normalized canonical numeric value (scaling words resolved).",
    )

    model_config = {"frozen": False}


class TruthGateResult(BaseModel):
    """
    The output of the truthfulness gate over the full set of claims
    extracted from one draft answer.

    Pipeline position: TRUTHFULNESS GATE (stage 20 of 18, just before PROOF CARD).

    answer_blocked is True if ANY claim is unsupported.
    The proof module will not emit a verified answer while answer_blocked is True.
    """

    claims: list[Claim] = Field(
        default_factory=list,
        description="All claims extracted from the draft answer.",
    )
    unsupported_claims: list[Claim] = Field(
        default_factory=list,
        description="Subset of claims where supported == False.",
    )
    answer_blocked: bool = Field(
        ...,
        description=(
            "True if any claim is unsupported. "
            "The proof module must not emit the answer while this is True. "
            "Set deterministically — not by the LLM."
        ),
    )
    overall_status: TruthStatus = Field(
        default=TruthStatus.NOT_VERIFIED,
        description="Authoritative final TruthStatus determined across all claims and reviews.",
    )
    verified_claims: list[Claim] = Field(
        default_factory=list,
        description="Claims verified by supporting evidence.",
    )
    failed_claims: list[Claim] = Field(
        default_factory=list,
        description="Claims that were contradicted, ambiguous, or unsupported.",
    )
    skeptic_review: Any = Field(
        default=None,
        description="Complete review report from the SkepticAgent.",
    )
    blocking_reasons: list[str] = Field(
        default_factory=list,
        description="Specific reasons why the answer was blocked from being emitted.",
    )
    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list,
        description="Aggregated evidence references supporting the verified claims.",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Assumptions associated with this answer.",
    )
    deterministic_decision: str = Field(
        default="BLOCKED",
        description="'PERMITTED' if answer is verified and clear; 'BLOCKED' otherwise.",
    )
