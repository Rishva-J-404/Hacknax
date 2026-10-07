"""
app.truth.evidence_matcher
--------------------------
Deterministic Claim-to-Evidence Matcher for ProofLens.

CORE PRINCIPLE (PROOFLENS_MASTER_CONTEXT.md §18, §19):
    Every claim extracted from a draft answer must be linked to
    authoritative execution and verification evidence.
    A numerical claim MUST match the authoritative verified result.
    If it disagrees -> CONTRADICTED.
    If evidence is missing -> NOT_VERIFIED.
    NO PROOF = NO NUMBER.
"""

from __future__ import annotations

import math
from typing import Any

from app.agent.contracts import AnalysisPlan
from app.execution.contracts import ExecutionResult
from app.repair.contracts import RepairWorld
from app.truth.contracts import Claim, ClaimType, EvidenceRef, TruthStatus
from app.verification.contracts import VerificationResult, VerificationStatus
from app.verification.metamorphic import compare_values


class ClaimEvidenceMatcher:
    """
    Matches extracted claims against authoritative execution and verification evidence.
    """

    def __init__(self, abs_tol: float = 1e-9, rel_tol: float = 1e-9) -> None:
        self.abs_tol = abs_tol
        self.rel_tol = rel_tol

    def match_claims(
        self,
        claims: list[Claim],
        verification_result: VerificationResult | None = None,
        execution_result: ExecutionResult | None = None,
        plan: AnalysisPlan | None = None,
        world: RepairWorld | None = None,
    ) -> list[Claim]:
        """
        Evaluate each claim against available verification and execution evidence.
        Returns the updated list of claims with evidence_refs and supported status.
        """
        matched_claims: list[Claim] = []

        # Determine authoritative verified result
        auth_val = None
        has_verified_proof = False
        if verification_result is not None:
            if verification_result.verification_passed:
                auth_val = verification_result.primary_result
                has_verified_proof = True
            else:
                auth_val = verification_result.primary_result  # May still be used to detect contradiction
        elif execution_result is not None and execution_result.execution_success:
            auth_val = execution_result.result_value

        for claim in claims:
            # Deep copy or construct new claim
            c = claim.model_copy(deep=True)
            evidence_refs: list[EvidenceRef] = []

            # --------------------------------------------------------------
            # 1. Numerical / Percentage / Count Claims
            # --------------------------------------------------------------
            if c.numerical_value is not None:
                if not has_verified_proof or auth_val is None:
                    # No verification proof exists
                    c.supported = False
                    c.status = TruthStatus.NOT_VERIFIED
                    c.mismatch_reason = "No verified execution output available to support numerical claim."
                    matched_claims.append(c)
                    continue

                # A. Check for Currency / Unit Incompatibility
                expected_unit = plan.aggregation.unit if (plan and plan.aggregation and plan.aggregation.unit) else None
                if expected_unit and c.unit and c.unit != "%":
                    # Check for direct mismatch like USD vs INR
                    if expected_unit.upper() != c.unit.upper():
                        c.supported = False
                        c.status = TruthStatus.NOT_VERIFIED
                        c.mismatch_reason = (
                            f"Unit mismatch: claim asserts '{c.unit}' but analysis expected '{expected_unit}'."
                        )
                        matched_claims.append(c)
                        continue

                # B. Check for Unsupported Precision
                # E.g. auth_val is 18.42 (2 decimal places), but claim has 18.423871928381
                if isinstance(auth_val, (int, float)) and isinstance(c.numerical_value, (int, float)):
                    c_str = str(c.numerical_value)
                    auth_str = str(auth_val)
                    if "." in c_str and "." in auth_str:
                        c_decimals = len(c_str.split(".")[1])
                        auth_decimals = len(auth_str.split(".")[1])
                        if abs(c.numerical_value - auth_val) > 1e-6 and c_decimals > auth_decimals + 3:
                            c.supported = False
                            c.status = TruthStatus.NOT_VERIFIED
                            c.mismatch_reason = (
                                f"Unsupported precision: claim asserts {c_decimals} decimal places, "
                                f"exceeding verified evidence precision ({auth_decimals} decimals)."
                            )
                            matched_claims.append(c)
                            continue

                # C. Numerical Comparison (Raw or Scaled)
                matches_raw, _ = compare_values(c.numerical_value, auth_val, abs_tol=self.abs_tol, rel_tol=self.rel_tol)
                matches_scaled = False
                if not matches_raw and c.normalized_value is not None:
                    matches_scaled, _ = compare_values(c.normalized_value, auth_val, abs_tol=self.abs_tol, rel_tol=self.rel_tol)

                if matches_raw or matches_scaled:
                    # Verified match
                    c.supported = True
                    has_assumptions = bool(
                        (world and world.assumptions)
                        or (verification_result and verification_result.status == VerificationStatus.VERIFIED_WITH_ASSUMPTION)
                    )
                    c.status = TruthStatus.VERIFIED_WITH_ASSUMPTION if has_assumptions else TruthStatus.VERIFIED
                    c.mismatch_reason = None

                    # Attach Traceable Evidence Refs
                    evidence_refs.append(
                        EvidenceRef(
                            evidence_type="execution_stdout",
                            reference=f"world_{verification_result.world_id} authoritative execution result",
                            value=str(auth_val),
                        )
                    )
                    if verification_result.duckdb_result is not None:
                        evidence_refs.append(
                            EvidenceRef(
                                evidence_type="duckdb_result",
                                reference="independent DuckDB SQL calculation",
                                value=str(verification_result.duckdb_result),
                            )
                        )
                    evidence_refs.append(
                        EvidenceRef(
                            evidence_type="verification_check",
                            reference="dual-path MATCH_CHECK",
                            value="PASS",
                        )
                    )
                    if execution_result and execution_result.generated_code_hash:
                        evidence_refs.append(
                            EvidenceRef(
                                evidence_type="lineage",
                                reference=f"analysis code SHA-256: {execution_result.generated_code_hash[:16]}...",
                                value=execution_result.generated_code_hash,
                            )
                        )

                else:
                    c.supported = False
                    # Check if any other claim in the text already matched the verified value
                    any_other_matched = any(
                        (other is not c) and (
                            compare_values(other.numerical_value, auth_val, abs_tol=self.abs_tol, rel_tol=self.rel_tol)[0]
                            or (other.normalized_value is not None and compare_values(other.normalized_value, auth_val, abs_tol=self.abs_tol, rel_tol=self.rel_tol)[0])
                        )
                        for other in claims
                        if other.numerical_value is not None
                    )

                    target_subjs = set()
                    if plan and plan.aggregation and plan.aggregation.column:
                        target_subjs.add(plan.aggregation.column.column.lower())
                    if plan:
                        for s in ["revenue", "sales", "amount", "profit", "orders", "count"]:
                            if s in plan.question.lower():
                                target_subjs.add(s)

                    is_same_subject_as_target = bool(c.subject and any(ts in c.subject or c.subject in ts for ts in target_subjs))

                    if any_other_matched and not is_same_subject_as_target:
                        c.status = TruthStatus.NOT_VERIFIED
                        c.mismatch_reason = f"No authoritative verification evidence for additional claim: '{c.claim_text}'."
                    elif c.claim_type == ClaimType.PERCENTAGE and not (plan and plan.aggregation and "%" in (plan.aggregation.unit or "")):
                        c.status = TruthStatus.NOT_VERIFIED
                        c.mismatch_reason = f"No authoritative verification evidence for percentage claim: '{c.claim_text}'."
                    else:
                        c.status = TruthStatus.CONTRADICTED
                        c.mismatch_reason = (
                            f"Claimed value '{c.numerical_value}' contradicts authoritative verified value '{auth_val}'."
                        )
                        evidence_refs.append(
                            EvidenceRef(
                                evidence_type="verification_check",
                                reference="dual-path comparison contradiction",
                                value=f"Claimed={c.numerical_value} vs Verified={auth_val}",
                            )
                        )

            # --------------------------------------------------------------
            # 2. Non-Numerical Claims (Comparisons, Dates, Factual)
            # --------------------------------------------------------------
            else:
                if c.claim_type == ClaimType.COMPARISON and auth_val is not None and isinstance(auth_val, str):
                    # Check if Top-N string winner matches entity mentioned in claim
                    if auth_val.lower() in c.claim_text.lower():
                        c.supported = True
                        has_assumptions = bool(world and world.assumptions)
                        c.status = TruthStatus.VERIFIED_WITH_ASSUMPTION if has_assumptions else TruthStatus.VERIFIED
                        c.mismatch_reason = None
                        evidence_refs.append(
                            EvidenceRef(
                                evidence_type="duckdb_result",
                                reference="Top-N ranking selection",
                                value=auth_val,
                            )
                        )
                    else:
                        c.supported = False
                        c.status = TruthStatus.NOT_VERIFIED
                        c.mismatch_reason = f"Comparative claim does not match verified top item '{auth_val}'."
                else:
                    c.supported = False
                    c.status = TruthStatus.NOT_VERIFIED
                    c.mismatch_reason = "Factual or comparative assertion lacks independent verified proof."

            c.evidence_refs = evidence_refs
            matched_claims.append(c)

        return matched_claims


def match_claims_to_evidence(
    claims: list[Claim],
    verification_result: VerificationResult | None = None,
    execution_result: ExecutionResult | None = None,
    plan: AnalysisPlan | None = None,
    world: RepairWorld | None = None,
) -> list[Claim]:
    """Convenience functional wrapper for claim matching."""
    matcher = ClaimEvidenceMatcher()
    return matcher.match_claims(
        claims=claims,
        verification_result=verification_result,
        execution_result=execution_result,
        plan=plan,
        world=world,
    )
