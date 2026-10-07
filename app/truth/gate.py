"""
app.truth.gate
--------------
Deterministic Claim-Level Truth Gate for ProofLens.

CORE LAW (PROOFLENS_MASTER_CONTEXT.md §2, §18, §19, §20):
    LLM PROPOSES.
    CODE COMPUTES.
    VERIFICATION DECIDES.
    NO PROOF = NO NUMBER.

The Truth Gate evaluates every factual assertion in a draft answer against
independent execution and verification evidence.
If even one critical numerical claim is unsupported, the answer is BLOCKED.
No probabilistic scoring. No LLM override.
"""

from __future__ import annotations

from typing import Any

from app.agent.contracts import AnalysisPlan, PlanStatus, UnanswerableReason
from app.execution.contracts import ExecutionResult
from app.repair.contracts import RepairWorld
from app.skeptic.contracts import SkepticReview
from app.truth.claim_extractor import ClaimExtractor
from app.truth.contracts import Claim, EvidenceRef, TruthGateResult, TruthStatus
from app.truth.evidence_matcher import ClaimEvidenceMatcher
from app.verification.contracts import VerificationResult, VerificationStatus


class TruthGate:
    """
    Deterministic gatekeeper that evaluates draft answers and claims
    against authoritative verification evidence and skeptic review.
    """

    def __init__(
        self,
        claim_extractor: ClaimExtractor | None = None,
        evidence_matcher: ClaimEvidenceMatcher | None = None,
        skeptic_agent: Any = None,
    ) -> None:
        self.extractor = claim_extractor or ClaimExtractor()
        self.matcher = evidence_matcher or ClaimEvidenceMatcher()
        if skeptic_agent is None:
            from app.skeptic.agent import SkepticAgent
            self.skeptic = SkepticAgent()
        else:
            self.skeptic = skeptic_agent

    def evaluate(
        self,
        draft_answer: str,
        verification_result: VerificationResult | None = None,
        execution_result: ExecutionResult | None = None,
        plan: AnalysisPlan | None = None,
        world: RepairWorld | None = None,
    ) -> TruthGateResult:
        """
        Execute full claim-level truth gate pipeline on draft answer.
        """
        # 1. Claim Extraction
        raw_claims = self.extractor.extract_claims(
            text=draft_answer,
            plan=plan,
            verification_result=verification_result,
        )

        # 2. Claim-to-Evidence Matching
        matched_claims = self.matcher.match_claims(
            claims=raw_claims,
            verification_result=verification_result,
            execution_result=execution_result,
            plan=plan,
            world=world,
        )

        # 3. Adversarial Skeptic Review
        skeptic_review = self.skeptic.review(
            draft_answer=draft_answer,
            claims=matched_claims,
            verification_result=verification_result,
            world=world,
            plan=plan,
            execution_result=execution_result,
        )

        # 4. Partition Claims
        verified_claims = [c for c in matched_claims if c.supported]
        unsupported_claims = [c for c in matched_claims if not c.supported]

        blocking_reasons: list[str] = []
        for c in unsupported_claims:
            blocking_reasons.append(
                f"Unsupported claim [{c.claim_type.value}]: '{c.claim_text}' ({c.mismatch_reason or 'No evidence'})"
            )

        for sc in skeptic_review.concerns:
            if sc.severity == "blocking":
                blocking_reasons.append(f"Skeptic blocking concern [{sc.concern_type.value}]: {sc.description}")

        # 5. Deterministic Status Precedence Resolution
        # Precedence: CONTRADICTED > UNANSWERABLE > AMBIGUOUS > NOT_VERIFIED > VERIFIED_WITH_ASSUMPTION > VERIFIED
        has_contradiction = any(c.status == TruthStatus.CONTRADICTED for c in matched_claims) or (
            verification_result is not None and (
                verification_result.status == VerificationStatus.FAILED
                or verification_result.results_match is False
            )
        )
        is_unanswerable = plan is not None and plan.status == PlanStatus.UNANSWERABLE
        is_ambiguous = plan is not None and plan.status == PlanStatus.AMBIGUOUS

        # Check if ambiguity was resolved in current world
        if is_ambiguous and world:
            if plan and plan.unanswerable_reason == UnanswerableReason.AMBIGUOUS_DATE:
                has_date_policy = any(
                    p.issue_type.value == "AMBIGUOUS_DATE_FORMAT"
                    and p.selected_action in {"DD_MM_YYYY", "MM_DD_YYYY", "YYYY_MM_DD"}
                    for p in world.policies
                )
                if has_date_policy:
                    is_ambiguous = False

        if has_contradiction:
            overall_status = TruthStatus.CONTRADICTED
        elif is_unanswerable:
            overall_status = TruthStatus.UNANSWERABLE
        elif is_ambiguous:
            overall_status = TruthStatus.AMBIGUOUS
        elif unsupported_claims or (verification_result is not None and not verification_result.verification_passed):
            overall_status = TruthStatus.NOT_VERIFIED
        elif not matched_claims:
            # Empty draft or no verifiable claims
            overall_status = TruthStatus.NOT_VERIFIED
            blocking_reasons.append("Draft answer contained no verifiable factual or numerical claims.")
        else:
            # All claims supported and verification passed
            has_assumptions = bool(
                (world and world.assumptions)
                or (verification_result and verification_result.status == VerificationStatus.VERIFIED_WITH_ASSUMPTION)
            )
            overall_status = TruthStatus.VERIFIED_WITH_ASSUMPTION if has_assumptions else TruthStatus.VERIFIED

        # 6. Final Decision Gate
        is_permitted = (
            overall_status in {TruthStatus.VERIFIED, TruthStatus.VERIFIED_WITH_ASSUMPTION}
            and not skeptic_review.has_blocking_concerns
            and len(unsupported_claims) == 0
        )

        answer_blocked = not is_permitted
        decision_str = "PERMITTED" if is_permitted else "BLOCKED"

        # Aggregate evidence references
        all_evidence: list[EvidenceRef] = []
        for c in verified_claims:
            all_evidence.extend(c.evidence_refs)

        assumptions_list = list(world.assumptions) if (world and world.assumptions) else []

        return TruthGateResult(
            claims=matched_claims,
            unsupported_claims=unsupported_claims,
            answer_blocked=answer_blocked,
            overall_status=overall_status,
            verified_claims=verified_claims,
            failed_claims=unsupported_claims,
            skeptic_review=skeptic_review,
            blocking_reasons=blocking_reasons,
            evidence_refs=all_evidence,
            assumptions=assumptions_list,
            deterministic_decision=decision_str,
        )


def evaluate_truth_gate(
    draft_answer: str,
    verification_result: VerificationResult | None = None,
    execution_result: ExecutionResult | None = None,
    plan: AnalysisPlan | None = None,
    world: RepairWorld | None = None,
) -> TruthGateResult:
    """Convenience functional wrapper for evaluating truth gate."""
    gate = TruthGate()
    return gate.evaluate(
        draft_answer=draft_answer,
        verification_result=verification_result,
        execution_result=execution_result,
        plan=plan,
        world=world,
    )
