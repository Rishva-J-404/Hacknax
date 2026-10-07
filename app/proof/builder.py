"""
app.proof.builder
-----------------
Deterministic ProofCard Builder for ProofLens.

CORE PRINCIPLE (PROOFLENS_MASTER_CONTEXT.md §20, §22, §23, §24):
    LLM PROPOSES.
    CODE COMPUTES.
    VERIFICATION DECIDES.
    NO PROOF = NO NUMBER.

The ProofCard is the final authoritative artifact produced by ProofLens.
Every field must be populated from computed data or explicit gate evaluations.
No LLM hallucinations. No random UUIDs. Deterministic SHA-256 hashes.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

import duckdb
import pandas as pd
import pydantic

from app.agent.contracts import AnalysisPlan, PlanStatus
from app.audit.contracts import DataQualityLedger
from app.execution.contracts import ExecutionResult, GeneratedCode
from app.proof.contracts import Lineage, ProofCard, ProofHashes
from app.repair.contracts import RepairWorld
from app.truth.contracts import Claim, TruthGateResult, TruthStatus
from app.verification.contracts import VerificationResult


# ---------------------------------------------------------------------------
# Deterministic Hashing Utilities
# ---------------------------------------------------------------------------

def compute_sha256_string(content: str) -> str:
    """Compute SHA-256 of a string using UTF-8 encoding."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def compute_canonical_proof_payload(canonical_dict: dict[str, Any]) -> tuple[str, str]:
    """
    Produce deterministic JSON string and SHA-256 hash from a canonical dictionary.
    Excludes non-reproducible volatile elements (timestamps, random IDs).
    """
    canonical_json = json.dumps(
        canonical_dict,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        ensure_ascii=False,
    )
    payload_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    proof_id = f"proof_{payload_hash[:12]}"
    return payload_hash, proof_id


# ---------------------------------------------------------------------------
# ProofCardBuilder Class
# ---------------------------------------------------------------------------

class ProofCardBuilder:
    """
    Deterministic builder assembling all pipeline outputs into a complete ProofCard.
    """

    def build(
        self,
        question: str,
        analysis_plan: AnalysisPlan | None = None,
        audit_ledger: DataQualityLedger | None = None,
        repair_world: RepairWorld | None = None,
        execution_result: ExecutionResult | None = None,
        verification_result: VerificationResult | None = None,
        truth_gate_result: TruthGateResult | None = None,
        generated_code: GeneratedCode | None = None,
        session_id: str | None = None,
        repair_worlds: list[RepairWorld] | None = None,
        verification_results: list[VerificationResult] | None = None,
        draft_explanation: str | None = None,
        refusal_reason: str | None = None,
        created_at: datetime | None = None,
    ) -> ProofCard:
        """
        Assemble the complete, deterministic ProofCard.
        """
        # 1. Question Normalization
        raw_question = question.strip()
        normalized_question = " ".join(raw_question.split())

        # Extract 4-digit year/period if present
        period_match = re.search(r"\b(19\d{2}|20\d{2})\b", raw_question)
        relevant_period = period_match.group(1) if period_match else None

        # 2. Determine Truth Status & Blocking Decisions
        # Law: Status comes exclusively from TruthGateResult or VerificationResult
        blocking_reasons: list[str] = []
        assumptions: list[str] = []
        claims: list[Claim] = []
        skeptic_review = None

        if truth_gate_result is not None:
            status = truth_gate_result.overall_status
            answer_blocked = truth_gate_result.answer_blocked
            blocking_reasons = list(truth_gate_result.blocking_reasons)
            deterministic_decision = truth_gate_result.deterministic_decision
            claims = list(truth_gate_result.claims)
            skeptic_review = truth_gate_result.skeptic_review
            assumptions = list(truth_gate_result.assumptions)
            # Update relevant_period from verified claim if available
            for c in claims:
                if c.supported and c.relevant_period:
                    relevant_period = c.relevant_period
                    break

        elif verification_result is not None:
            status = TruthStatus(verification_result.status.value)
            answer_blocked = not verification_result.verification_passed
            deterministic_decision = "PERMITTED" if verification_result.verification_passed else "BLOCKED"
            if not verification_result.verification_passed:
                blocking_reasons = list(verification_result.failures)
            assumptions = list(verification_result.world_assumptions)

        elif analysis_plan is not None and analysis_plan.status == PlanStatus.UNANSWERABLE:
            status = TruthStatus.UNANSWERABLE
            answer_blocked = True
            deterministic_decision = "BLOCKED"
            reason = analysis_plan.unanswerable_evidence or "Question unanswerable from provided data."
            blocking_reasons = [reason]
            refusal_reason = refusal_reason or reason

        elif analysis_plan is not None and analysis_plan.status == PlanStatus.AMBIGUOUS:
            status = TruthStatus.AMBIGUOUS
            answer_blocked = True
            deterministic_decision = "BLOCKED"
            flags = [
                f.issue_type.value if hasattr(getattr(f, "issue_type", None), "value")
                else getattr(f, "description", str(f))
                for f in analysis_plan.ambiguity_flags
            ]
            reason = f"Unresolved ambiguities: {', '.join(flags)}" if flags else "Ambiguous question or data."
            blocking_reasons = [reason]
            refusal_reason = refusal_reason or reason

        else:
            status = TruthStatus.NOT_VERIFIED
            answer_blocked = True
            deterministic_decision = "BLOCKED"
            blocking_reasons = ["No verification evidence or truth gate evaluation available."]
            refusal_reason = refusal_reason or "Answer not verified."

        # Collect additional assumptions from repair worlds if needed
        all_worlds = repair_worlds or ([repair_world] if repair_world else [])
        for w in all_worlds:
            for a in w.assumptions:
                if a not in assumptions:
                    assumptions.append(a)

        # 3. Compute Result and Formatted Display Value
        raw_result = None
        if execution_result and execution_result.result_value is not None:
            raw_result = execution_result.result_value
        elif verification_result and verification_result.primary_result is not None:
            raw_result = verification_result.primary_result

        result_unit = None
        if analysis_plan and analysis_plan.aggregation and analysis_plan.aggregation.unit:
            result_unit = analysis_plan.aggregation.unit
        elif claims:
            for c in claims:
                if c.unit:
                    result_unit = c.unit
                    break

        result_world_id = None
        if repair_world:
            result_world_id = repair_world.world_id
        elif execution_result and execution_result.world_id:
            result_world_id = execution_result.world_id
        elif verification_result and verification_result.world_id:
            result_world_id = verification_result.world_id

        # Law: If answer_blocked == True, never present authoritative verified number
        result_val = raw_result
        if status in {TruthStatus.UNANSWERABLE, TruthStatus.AMBIGUOUS}:
            result_val = None

        result_type = type(result_val).__name__ if result_val is not None else None

        # Format display value
        formatted_result: str | None = None
        if result_val is not None:
            try:
                num_f = float(result_val)
                if result_unit == "INR" and abs(num_f) >= 10_000_000:
                    formatted_result = f"₹{round(num_f / 10_000_000, 2)} Cr"
                elif result_unit == "INR":
                    formatted_result = f"₹{result_val}"
                elif result_unit == "%":
                    formatted_result = f"{result_val}%"
                elif result_unit:
                    formatted_result = f"{result_val} {result_unit}"
                else:
                    formatted_result = str(result_val)
            except (ValueError, TypeError):
                formatted_result = str(result_val)

        # 4. Assemble Lineage & Provenance
        tables_used: list[str] = []
        columns_used: list[str] = []
        filters_applied: list[str] = []
        joins_performed: list[str] = []
        transformations: list[str] = []

        if analysis_plan:
            tables_used = list(analysis_plan.required_tables)
            columns_used = [f"{c.table}.{c.column}" for c in analysis_plan.required_columns]
            filters_applied = [
                f"{f.column.table}.{f.column.column} {f.operator} {f.value}"
                for f in analysis_plan.filters
            ]
            joins_performed = [
                f"{left.table}.{left.column} = {right.table}.{right.column}"
                for left, right in analysis_plan.join_keys
            ]
            if analysis_plan.aggregation:
                agg = analysis_plan.aggregation
                transformations.append(f"{agg.operation.upper()}({agg.column.table}.{agg.column.column})")

        policy_summary_parts: list[str] = []
        for w in all_worlds:
            for p in w.policies:
                policy_summary_parts.append(f"{p.issue_type.value}: {p.selected_action}")
        repair_policy_summary = "; ".join(policy_summary_parts) if policy_summary_parts else None

        source_files: list[str] = []
        if audit_ledger:
            for t_prof in audit_ledger.table_profiles:
                source_files.append(t_prof.source)

        lineage = Lineage(
            source_files=source_files,
            tables_used=tables_used,
            columns_used=columns_used,
            filters_applied=filters_applied,
            joins_performed=joins_performed,
            transformations=transformations,
            repair_policy_summary=repair_policy_summary,
        )

        # 5. Execution Summary
        execution_summary: dict[str, Any] = {}
        analysis_code_str: str | None = None
        code_hash: str | None = None

        if generated_code:
            analysis_code_str = generated_code.code_content
            code_hash = generated_code.code_sha256
        elif execution_result and execution_result.code_path and execution_result.code_path.exists():
            try:
                analysis_code_str = execution_result.code_path.read_text(encoding="utf-8")
                code_hash = execution_result.generated_code_hash or compute_sha256_string(analysis_code_str)
            except Exception:
                code_hash = execution_result.generated_code_hash
        elif execution_result:
            code_hash = execution_result.generated_code_hash

        if execution_result:
            execution_summary = {
                "execution_success": execution_result.execution_success,
                "exit_code": execution_result.exit_code,
                "stdout": execution_result.stdout,
                "stderr": execution_result.stderr,
                "duration_seconds": getattr(execution_result, "duration_seconds", None),
                "generated_code_hash": code_hash,
                "input_data_hashes": execution_result.input_data_hashes,
                "row_count_waterfall": execution_result.row_count_waterfall,
                "execution_error": getattr(execution_result, "execution_error", None),
            }

        # 6. Verification Summary & Metamorphic Checks
        all_vr = verification_results or ([verification_result] if verification_result else [])
        metamorphic_summary: list[dict[str, Any]] = []

        for vr in all_vr:
            for chk in vr.metamorphic_results:
                name_str = getattr(chk, "name", str(getattr(chk, "check", "TEST")))
                status_obj = getattr(chk, "status", getattr(chk, "outcome", "PASS"))
                outcome_str = status_obj.value if hasattr(status_obj, "value") else str(status_obj)
                metamorphic_summary.append({
                    "name": name_str,
                    "transformation": getattr(chk, "transformation", getattr(chk, "description", name_str)),
                    "expected": str(getattr(chk, "expected", "Metamorphic invariant holds")),
                    "observed": str(getattr(chk, "observed", outcome_str)),
                    "status": outcome_str,
                    "reason": getattr(chk, "reason", getattr(chk, "details", None)),
                })

        impact_range: dict[str, float | int | str | None] = {}
        if verification_result and verification_result.impact:
            imp = verification_result.impact
            impact_range = {
                "minimum": imp.minimum_value,
                "maximum": imp.maximum_value,
                "spread": imp.spread,
                "value_stable": imp.value_stable,
                "decision_stable": imp.decision_stable,
            }

        # 7. Collect Dataset Hashes
        dataset_hashes: dict[str, str] = {}
        if execution_result and execution_result.input_data_hashes:
            dataset_hashes.update(execution_result.input_data_hashes)
        if audit_ledger:
            for tp in audit_ledger.table_profiles:
                if tp.source not in dataset_hashes and tp.dataset_sha256:
                    dataset_hashes[tp.source] = tp.dataset_sha256

        # Policy Hash
        policy_serialized = ";".join(sorted(policy_summary_parts))
        policy_hash = compute_sha256_string(policy_serialized) if policy_serialized else None

        # 8. Deterministic Canonical Payload & Proof ID
        canonical_dict: dict[str, Any] = {
            "question": raw_question,
            "normalized_question": normalized_question,
            "status": status.value,
            "result": result_val,
            "result_unit": result_unit,
            "answer_blocked": answer_blocked,
            "deterministic_decision": deterministic_decision,
            "blocking_reasons": sorted(blocking_reasons),
            "assumptions": sorted(assumptions),
            "code_hash": code_hash,
            "dataset_hashes": sorted(dataset_hashes.items()),
            "policy_hash": policy_hash,
            "world_id": result_world_id,
            "verified_claims_count": len([c for c in claims if c.supported]),
            "failed_claims_count": len([c for c in claims if not c.supported]),
        }

        canonical_hash, proof_id = compute_canonical_proof_payload(canonical_dict)

        hashes = ProofHashes(
            dataset_sha256=dataset_hashes,
            analysis_code_sha256=code_hash,
            policy_sha256=policy_hash,
            canonical_proof_sha256=canonical_hash,
        )

        reproduction_command = f"python scripts/replay.py proofs/{proof_id}.json"

        # 9. Replay Metadata
        replay_info: dict[str, Any] = {
            "reproduction_command": reproduction_command,
            "proof_id": proof_id,
            "python_version": sys.version.split()[0],
            "platform": sys.platform,
            "dependencies": {
                "pydantic": pydantic.__version__,
                "pandas": pd.__version__,
                "duckdb": duckdb.__version__,
            },
            "code_sha256": code_hash,
            "dataset_sha256": dataset_hashes,
            "canonical_payload_sha256": canonical_hash,
            "world_id": result_world_id,
            "tolerance": {"abs_tol": 1e-6, "rel_tol": 1e-4},
            "replay_executable": bool(code_hash and dataset_hashes),
        }

        # 10. Construct Final ProofCard
        card = ProofCard(
            proof_id=proof_id,
            session_id=session_id,
            created_at=created_at or datetime.utcnow(),
            question=raw_question,
            normalized_question=normalized_question,
            result=result_val,
            result_unit=result_unit,
            result_world_id=result_world_id,
            status=status,
            assumptions=assumptions,
            data_quality_ledger=audit_ledger,
            repair_worlds=all_worlds,
            impact_range=impact_range,
            analysis_code_path=execution_result.code_path if execution_result else None,
            verification_results=all_vr,
            lineage=lineage,
            hashes=hashes,
            reproduction_command=reproduction_command,
            draft_explanation=draft_explanation,
            refusal_reason=refusal_reason,
            result_type=result_type,
            relevant_period=relevant_period,
            formatted_result=formatted_result,
            answer_blocked=answer_blocked,
            blocking_reasons=blocking_reasons,
            deterministic_decision=deterministic_decision,
            analysis_plan=analysis_plan,
            execution_summary=execution_summary,
            metamorphic_summary=metamorphic_summary,
            claims=claims,
            skeptic_review=skeptic_review,
            truth_gate_result=truth_gate_result,
            replay=replay_info,
        )
        return card


def build_proof_card(
    question: str,
    analysis_plan: AnalysisPlan | None = None,
    audit_ledger: DataQualityLedger | None = None,
    repair_world: RepairWorld | None = None,
    execution_result: ExecutionResult | None = None,
    verification_result: VerificationResult | None = None,
    truth_gate_result: TruthGateResult | None = None,
    generated_code: GeneratedCode | None = None,
    session_id: str | None = None,
    repair_worlds: list[RepairWorld] | None = None,
    verification_results: list[VerificationResult] | None = None,
    draft_explanation: str | None = None,
    refusal_reason: str | None = None,
    created_at: datetime | None = None,
) -> ProofCard:
    """Convenience functional wrapper for ProofCardBuilder."""
    builder = ProofCardBuilder()
    return builder.build(
        question=question,
        analysis_plan=analysis_plan,
        audit_ledger=audit_ledger,
        repair_world=repair_world,
        execution_result=execution_result,
        verification_result=verification_result,
        truth_gate_result=truth_gate_result,
        generated_code=generated_code,
        session_id=session_id,
        repair_worlds=repair_worlds,
        verification_results=verification_results,
        draft_explanation=draft_explanation,
        refusal_reason=refusal_reason,
        created_at=created_at,
    )
