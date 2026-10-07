"""
app.proof.contracts
-------------------
Data structures for the Proof Card — the final output of ProofLens.

Responsibility:
  Assemble everything the system has computed into one structured,
  machine-readable proof object that:
    - records the question and answer
    - records the final truth status
    - records all assumptions, policies, and repair worlds
    - records verification results
    - records provenance (lineage, hashes)
    - provides a reproduction command anyone can run

Design rules (PROOFLENS_MASTER_CONTEXT.md §20, §22, §23, §24):
  - Every required field must be populated from actual computed data.
  - No field may be populated from LLM text unless it is explicitly
    labelled as a draft/explanation field.
  - The result field comes exclusively from ExecutionResult.result_value.
  - The status field comes exclusively from the verification + truth modules.
  - The proof must be serialisable to JSON and storable in proofs/.

Core principle:
  NO PROOF = NO NUMBER.
  If a ProofCard cannot be populated with verified data, the system
  must refuse to produce a numerical answer.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.agent.contracts import AnalysisPlan
from app.audit.contracts import DataQualityLedger
from app.repair.contracts import RepairWorld
from app.skeptic.contracts import SkepticReview
from app.truth.contracts import Claim, TruthGateResult, TruthStatus
from app.verification.contracts import VerificationResult


class Lineage(BaseModel):
    """
    Provenance chain for the computed result.
    (PROOFLENS_MASTER_CONTEXT.md §22)

    Records every step that transformed the raw data into the final number.
    """

    source_files: list[str] = Field(
        default_factory=list,
        description="Original file paths used as input.",
    )
    tables_used: list[str] = Field(
        default_factory=list,
        description="Table aliases or filename stems read by the analysis.",
    )
    columns_used: list[str] = Field(
        default_factory=list,
        description="Column names read by the analysis code.",
    )
    filters_applied: list[str] = Field(
        default_factory=list,
        description="Human-readable description of each filter applied.",
    )
    joins_performed: list[str] = Field(
        default_factory=list,
        description="Human-readable description of each join performed.",
    )
    transformations: list[str] = Field(
        default_factory=list,
        description="Human-readable description of each transformation applied.",
    )
    repair_policy_summary: str | None = Field(
        default=None,
        description="One-sentence summary of the repair policies applied.",
    )


class ProofHashes(BaseModel):
    """
    SHA-256 hashes for reproducibility.
    (PROOFLENS_MASTER_CONTEXT.md §23)

    These hashes allow an independent verifier to confirm that the
    stored proof was produced from the exact same data, code, and policy.
    """

    dataset_sha256: dict[str, str] = Field(
        default_factory=dict,
        description="Map of world_id → SHA-256 hash of the world's data content.",
    )
    analysis_code_sha256: str | None = Field(
        default=None,
        description="SHA-256 hash of the analysis code file.",
    )
    policy_sha256: str | None = Field(
        default=None,
        description="SHA-256 hash of the serialised repair policy.",
    )
    canonical_proof_sha256: str | None = Field(
        default=None,
        description="Deterministic SHA-256 hash of the canonical proof payload.",
    )


class ProofCard(BaseModel):
    """
    The complete, final output of one ProofLens analysis run.

    Pipeline position: PROOF CARD → ANSWER / REFUSE (stages 21–22 of 18+).

    This model satisfies the 11 required proof-card fields specified in
    PROOFLENS_MASTER_CONTEXT.md §20:
      1.  question             ← question
      2.  answer               ← result (from execution stdout)
      3.  status               ← status (from verification + truth modules)
      4.  assumptions          ← assumptions
      5.  data quality         ← data_quality_ledger
      6.  repair policy        ← repair_worlds (each world carries its policies)
      7.  impact range         ← impact_range
      8.  analysis code        ← analysis_code_path
      9.  verification         ← verification_results
      10. lineage              ← lineage
      11. reproduction command ← reproduction_command

    The result field MUST come from ExecutionResult.result_value.
    The status field MUST come from the verification + truth modules.
    Neither field may be set from LLM text.
    """

    # ── Identity ─────────────────────────────────────────────────────────────
    proof_id: str = Field(
        ...,
        description=(
            "Unique identifier for this proof "
            "(e.g. 'proof_20261007_001').  Used as the proof filename."
        ),
    )
    session_id: str | None = Field(
        default=None,
        description="Ties this proof to the AnalysisRequest session.",
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when this proof was created.",
    )

    # ── Required field 1: Question ───────────────────────────────────────────
    question: str = Field(
        ...,
        description="The original user question, verbatim.",
    )

    # ── Required field 2: Answer (from execution stdout ONLY) ────────────────
    result: float | int | str | None = Field(
        default=None,
        description=(
            "The final computed answer. "
            "MUST come from ExecutionResult.result_value (subprocess stdout). "
            "NEVER from LLM text or hardcoded values. "
            "None if the answer is UNANSWERABLE or NOT_VERIFIED."
        ),
    )
    result_unit: str | None = Field(
        default=None,
        description="Unit of the result (e.g. 'INR', 'orders', '%').",
    )
    result_world_id: str | None = Field(
        default=None,
        description=(
            "Which RepairWorld produced the reported result. "
            "Required when result is not None."
        ),
    )

    # ── Required field 3: Status (deterministic) ─────────────────────────────
    status: TruthStatus = Field(
        ...,
        description=(
            "Final truth status. "
            "Set ONLY by the verification + truth modules. "
            "The LLM cannot set this field."
        ),
    )

    # ── Required field 4: Assumptions ────────────────────────────────────────
    assumptions: list[str] = Field(
        default_factory=list,
        description=(
            "Explicit assumptions made during this analysis "
            "(e.g. 'treating all dates as DD/MM/YYYY', "
            "'converting USD to INR at 83.5'). "
            "Required when status == VERIFIED_WITH_ASSUMPTION."
        ),
    )

    # ── Required field 5: Data Quality ───────────────────────────────────────
    data_quality_ledger: DataQualityLedger | None = Field(
        default=None,
        description=(
            "The full data quality ledger produced by the audit module. "
            "Populated from actual data inspection — never invented."
        ),
    )

    # ── Required field 6: Repair Policy (via worlds) ─────────────────────────
    repair_worlds: list[RepairWorld] = Field(
        default_factory=list,
        description=(
            "All repair worlds that were created and analysed. "
            "Each world contains its RepairPolicy list."
        ),
    )

    # ── Required field 7: Impact Range ───────────────────────────────────────
    impact_range: dict[str, float | int | str | None] = Field(
        default_factory=dict,
        description=(
            "Cross-world impact summary. "
            "Keys: 'minimum', 'maximum', 'spread', 'value_stable', 'decision_stable'. "
            "Values come from ImpactAnalysis in VerificationResult — never from LLM."
        ),
    )

    # ── Required field 8: Analysis Code ──────────────────────────────────────
    analysis_code_path: Path | None = Field(
        default=None,
        description=(
            "Path to the generated analysis script. "
            "This is the same script that ran against every world."
        ),
    )

    # ── Required field 9: Verification ───────────────────────────────────────
    verification_results: list[VerificationResult] = Field(
        default_factory=list,
        description=(
            "Verification results, one per RepairWorld. "
            "Each records Pandas path, DuckDB path, match check, "
            "metamorphic tests, premise check, etc."
        ),
    )

    # ── Required field 10: Lineage ───────────────────────────────────────────
    lineage: Lineage | None = Field(
        default=None,
        description=(
            "Full provenance chain from raw data to final result. "
            "(PROOFLENS_MASTER_CONTEXT.md §22)"
        ),
    )
    hashes: ProofHashes | None = Field(
        default=None,
        description=(
            "SHA-256 hashes of the dataset, code, and policy. "
            "(PROOFLENS_MASTER_CONTEXT.md §23)"
        ),
    )

    # ── Required field 11: Reproduction Command ───────────────────────────────
    reproduction_command: str | None = Field(
        default=None,
        description=(
            "The exact shell command that reproduces this result. "
            "Example: 'python scripts/replay.py proofs/proof_001.json'. "
            "(PROOFLENS_MASTER_CONTEXT.md §24)"
        ),
    )

    # ── Human-readable explanation (LLM-generated, labelled clearly) ──────────
    draft_explanation: str | None = Field(
        default=None,
        description=(
            "LLM-generated human-readable explanation of the result. "
            "This is labelled as a DRAFT and is not the source of truth. "
            "All numerical values in this text must be backed by evidence refs "
            "in the truth gate result."
        ),
    )

    # ── Refusal path ─────────────────────────────────────────────────────────
    refusal_reason: str | None = Field(
        default=None,
        description=(
            "Populated when the system refuses to produce a numerical answer. "
            "Explains why in human-readable terms."
        ),
    )

    # ── Additional Question / Result Details ─────────────────────────────────
    normalized_question: str | None = Field(
        default=None,
        description="Normalized or sanitized version of question.",
    )
    result_type: str | None = Field(
        default=None,
        description="Type of result: 'float', 'int', 'str', 'table', 'None'.",
    )
    relevant_period: str | None = Field(
        default=None,
        description="Relevant period or date extracted from question or claim.",
    )
    formatted_result: str | None = Field(
        default=None,
        description="Human-friendly formatted result string, e.g. '₹18.42 Cr'.",
    )

    # ── Blocked Answer & Gate Decision ───────────────────────────────────────
    answer_blocked: bool = Field(
        default=False,
        description="True if TruthGate blocked this answer.",
    )
    blocking_reasons: list[str] = Field(
        default_factory=list,
        description="Reasons explaining why answer was blocked.",
    )
    deterministic_decision: str = Field(
        default="PERMITTED",
        description="'PERMITTED' or 'BLOCKED'.",
    )

    # ── Structured Analysis Plan ─────────────────────────────────────────────
    analysis_plan: AnalysisPlan | None = Field(
        default=None,
        description="The full structured AnalysisPlan executed.",
    )

    # ── Execution Summary ────────────────────────────────────────────────────
    execution_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Generated code details, stdout, exit_code, duration.",
    )

    # ── Metamorphic Test Results ─────────────────────────────────────────────
    metamorphic_summary: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Metamorphic test cases (name, status, expected, observed).",
    )

    # ── Claims & Skeptic Review ──────────────────────────────────────────────
    claims: list[Claim] = Field(
        default_factory=list,
        description="All extracted and matched claims.",
    )
    skeptic_review: SkepticReview | None = Field(
        default=None,
        description="Skeptic agent review concerns and blocking flags.",
    )
    truth_gate_result: TruthGateResult | None = Field(
        default=None,
        description="Complete TruthGate evaluation result.",
    )

    # ── Replay Environment & Instructions ────────────────────────────────────
    replay: dict[str, Any] = Field(
        default_factory=dict,
        description="Environment, hashes, and dependency replay information.",
    )
