"""
app.skeptic.agent
------------------
Deterministic AI Skeptic Reviewer for ProofLens.

CORE PRINCIPLE (PROOFLENS_MASTER_CONTEXT.md §17):
    The skeptic is an ADVERSARIAL REVIEWER, not a source of truth.
    Deterministic execution and verification remain authoritative.
    The skeptic identifies concerns that block the draft answer from
    being emitted until all claims are rigorously supported by evidence.
"""

from __future__ import annotations

from app.agent.contracts import AnalysisPlan, PlanStatus, UnanswerableReason
from app.execution.contracts import ExecutionResult
from app.repair.contracts import RepairWorld
from app.skeptic.contracts import SkepticConcern, SkepticConcernType, SkepticReview
from app.truth.contracts import Claim, TruthStatus
from app.verification.contracts import VerificationResult, VerificationStatus


class SkepticAgent:
    """
    Adversarial reviewer that inspects draft answers, claims, and verification
    results to surface potential flaws, contradictions, or ungrounded claims.
    """

    def review(
        self,
        draft_answer: str,
        claims: list[Claim],
        verification_result: VerificationResult | None = None,
        world: RepairWorld | None = None,
        plan: AnalysisPlan | None = None,
        execution_result: ExecutionResult | None = None,
    ) -> SkepticReview:
        """
        Conduct a deterministic adversarial review across all components.
        """
        concerns: list[SkepticConcern] = []

        # ------------------------------------------------------------------
        # 1. False Premise & Answerability Check
        # ------------------------------------------------------------------
        if plan is not None and plan.status == PlanStatus.UNANSWERABLE:
            concerns.append(
                SkepticConcern(
                    concern_type=SkepticConcernType.FALSE_PREMISE,
                    description=(
                        f"Analysis question is unanswerable: {plan.unanswerable_evidence or plan.unanswerable_reason}. "
                        f"Draft answer must not present a numerical response."
                    ),
                    location="plan",
                    severity="blocking",
                )
            )

        # ------------------------------------------------------------------
        # 2. Date Ambiguity Check
        # ------------------------------------------------------------------
        if plan is not None and plan.status == PlanStatus.AMBIGUOUS:
            if plan.unanswerable_reason == UnanswerableReason.AMBIGUOUS_DATE:
                # Check if world has an explicit date resolution policy
                has_date_policy = False
                if world:
                    has_date_policy = any(
                        p.issue_type.value == "AMBIGUOUS_DATE_FORMAT"
                        and p.selected_action in {"DD_MM_YYYY", "MM_DD_YYYY", "YYYY_MM_DD"}
                        for p in world.policies
                    )
                if not has_date_policy:
                    concerns.append(
                        SkepticConcern(
                            concern_type=SkepticConcernType.DATE_AMBIGUITY,
                            description=(
                                "Date format is ambiguous (DD/MM vs MM/DD) and no explicit "
                                "repair policy resolves it."
                            ),
                            location="audit",
                            severity="blocking",
                        )
                    )

        # ------------------------------------------------------------------
        # 3. Dual-Path Verification Contradiction Check
        # ------------------------------------------------------------------
        if verification_result is not None:
            if verification_result.status == VerificationStatus.FAILED or verification_result.results_match is False:
                concerns.append(
                    SkepticConcern(
                        concern_type=SkepticConcernType.CONTRADICTION,
                        description=(
                            f"Dual-path computation contradiction detected: "
                            f"{'; '.join(verification_result.failures)}"
                        ),
                        location="verification",
                        severity="blocking",
                    )
                )

            # Check Provenance Failures
            if not verification_result.provenance_verified and verification_result.status == VerificationStatus.NOT_VERIFIED:
                if any("provenance" in f.lower() or "mutation" in f.lower() for f in verification_result.failures):
                    concerns.append(
                        SkepticConcern(
                            concern_type=SkepticConcernType.PROVENANCE_MISMATCH,
                            description=(
                                f"Provenance validation failed: {'; '.join(verification_result.failures)}"
                            ),
                            location="verification",
                            severity="blocking",
                        )
                    )

        # ------------------------------------------------------------------
        # 4. Claim-Level Checks (Explanation Mismatch, Unsupported Claims)
        # ------------------------------------------------------------------
        for claim in claims:
            # A. Contradicted Claims
            if claim.status == TruthStatus.CONTRADICTED:
                concerns.append(
                    SkepticConcern(
                        concern_type=SkepticConcernType.EXPLANATION_MISMATCH,
                        description=(
                            f"Claim '{claim.claim_text}' asserts {claim.numerical_value}, "
                            f"which contradicts verified evidence: {claim.mismatch_reason}"
                        ),
                        location="draft_answer",
                        severity="blocking",
                    )
                )

            # B. Unsupported Claims
            elif not claim.supported:
                # Check for unit or currency mismatch
                if claim.mismatch_reason and "unit mismatch" in claim.mismatch_reason.lower():
                    concerns.append(
                        SkepticConcern(
                            concern_type=SkepticConcernType.UNIT_MISMATCH,
                            description=claim.mismatch_reason,
                            location="draft_answer",
                            severity="blocking",
                        )
                    )
                # Check for excessive precision
                elif claim.mismatch_reason and "precision" in claim.mismatch_reason.lower():
                    concerns.append(
                        SkepticConcern(
                            concern_type=SkepticConcernType.UNSUPPORTED_PRECISION,
                            description=claim.mismatch_reason,
                            location="draft_answer",
                            severity="blocking",
                        )
                    )
                else:
                    concerns.append(
                        SkepticConcern(
                            concern_type=SkepticConcernType.UNSUPPORTED_CLAIM,
                            description=(
                                f"Unsupported assertion: '{claim.claim_text}'. "
                                f"{claim.mismatch_reason or 'No evidence reference found.'}"
                            ),
                            location="draft_answer",
                            severity="blocking",
                        )
                    )

        # ------------------------------------------------------------------
        # Summary Evaluation
        # ------------------------------------------------------------------
        has_blocking = any(c.severity == "blocking" for c in concerns)
        summary_lines = [
            f"Skeptic review identified {len(concerns)} concern(s).",
            f"Blocking concerns present: {has_blocking}.",
        ]
        if concerns:
            summary_lines.extend(f"- [{c.concern_type.value}] {c.description}" for c in concerns)

        return SkepticReview(
            concerns=concerns,
            has_blocking_concerns=has_blocking,
            skeptic_notes="\n".join(summary_lines),
        )


def review_draft_answer(
    draft_answer: str,
    claims: list[Claim],
    verification_result: VerificationResult | None = None,
    world: RepairWorld | None = None,
    plan: AnalysisPlan | None = None,
    execution_result: ExecutionResult | None = None,
) -> SkepticReview:
    """Convenience functional wrapper for skeptic review."""
    agent = SkepticAgent()
    return agent.review(
        draft_answer=draft_answer,
        claims=claims,
        verification_result=verification_result,
        world=world,
        plan=plan,
        execution_result=execution_result,
    )
