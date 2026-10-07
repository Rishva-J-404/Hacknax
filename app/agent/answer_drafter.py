"""
app.agent.answer_drafter
------------------------
Untrusted Natural-Language Answer Drafter & Strict Truth Gate Verification for ProofLens.

CORE PRINCIPLES (PROOFLENS_MASTER_CONTEXT.md §2, §11, §12):
    LLM PROPOSES.
    CODE COMPUTES.
    VERIFICATION DECIDES.
    NO PROOF = NO NUMBER.

The draft generated here is UNTRUSTED.
It must pass through ClaimExtractor -> EvidenceMatcher -> SkepticAgent -> TruthGate
before any text containing numerical statements is permitted.

If TruthGate blocks the draft, a deterministic refusal template is returned.
Under NO circumstances is an unsupported numerical claim presented as verified.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agent.prompt_defense import wrap_untrusted_data
from app.agent.qwen_client import LLMClient
from app.execution.contracts import ExecutionResult
from app.skeptic.agent import SkepticAgent
from app.truth.claim_extractor import ClaimExtractor
from app.truth.contracts import Claim, TruthGateResult, TruthStatus
from app.truth.evidence_matcher import ClaimEvidenceMatcher
from app.truth.gate import TruthGate
from app.verification.contracts import VerificationResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deterministic Refusal Templates
# ---------------------------------------------------------------------------

def generate_refusal_response(
    question: str,
    status: TruthStatus,
    reasons: list[str],
    proof_id: str | None = None,
) -> str:
    """Deterministic refusal message explaining why no verified answer can be published."""
    proof_str = f" [Proof ID: {proof_id}]" if proof_id else ""
    reason_str = "; ".join(reasons) if reasons else "Independent verification did not confirm the claim."

    if status == TruthStatus.CONTRADICTED:
        return (
            f"I cannot provide a verified numerical answer because independent verification "
            f"detected a contradiction in the computation.{proof_str}\n"
            f"Details: {reason_str}"
        )
    if status == TruthStatus.UNANSWERABLE:
        return (
            f"I cannot answer this question because the required data or columns are not available.{proof_str}\n"
            f"Details: {reason_str}"
        )
    if status == TruthStatus.AMBIGUOUS:
        return (
            f"I cannot provide a single numerical answer because multiple defensible interpretations exist in the data.{proof_str}\n"
            f"Details: {reason_str}"
        )
    return (
        f"I cannot provide a verified numerical answer for this question.{proof_str}\n"
        f"Reason: {reason_str}"
    )


# ---------------------------------------------------------------------------
# Answer Drafter
# ---------------------------------------------------------------------------

class AnswerDrafter:
    """
    Drafter that turns verified execution numbers into natural language.
    All drafts are treated as untrusted and audited through the TruthGate.
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        truth_gate: TruthGate | None = None,
        skeptic_agent: SkepticAgent | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.truth_gate = truth_gate or TruthGate()
        self.skeptic_agent = skeptic_agent or SkepticAgent()
        self.claim_extractor = ClaimExtractor()
        self.evidence_matcher = ClaimEvidenceMatcher()

    def draft_and_verify(
        self,
        question: str,
        execution_result: ExecutionResult,
        verification_result: VerificationResult | None,
        overall_status: TruthStatus,
        proof_id: str | None = None,
        formatted_result: str | None = None,
        world: RepairWorld | None = None,
        plan: AnalysisPlan | None = None,
    ) -> tuple[str, bool, TruthGateResult]:
        """
        Produce a natural language answer and strictly verify it with TruthGate.

        Returns:
            (answer_text, is_blocked, truth_gate_result)
        """
        # 1. If pipeline status is already blocked (unanswerable, contradicted, etc.)
        if overall_status in (
            TruthStatus.CONTRADICTED,
            TruthStatus.UNANSWERABLE,
            TruthStatus.NOT_VERIFIED,
            TruthStatus.AMBIGUOUS,
        ):
            reasons = []
            if verification_result and verification_result.failures:
                reasons.extend(verification_result.failures)
            elif not execution_result.execution_success:
                reasons.append(execution_result.execution_error or "Execution failed.")

            refusal = generate_refusal_response(
                question=question,
                status=overall_status,
                reasons=reasons,
                proof_id=proof_id,
            )
            gate_res = TruthGateResult(
                overall_status=overall_status,
                answer_blocked=True,
                deterministic_decision="BLOCKED",
                blocking_reasons=reasons or ["Truth gate blocked answer publication."],
            )
            return refusal, True, gate_res

        # 2. Draft natural language statement from verified number
        raw_val = execution_result.result_value
        val_str = formatted_result or str(raw_val)

        draft_text = self._generate_draft_text(question, val_str, raw_val)

        # 3. Audit Draft via TruthGate
        gate_res = self.truth_gate.evaluate(
            draft_answer=draft_text,
            verification_result=verification_result,
            execution_result=execution_result,
            world=world,
            plan=plan,
        )

        # 4. If draft claims are rejected by TruthGate, block and refuse
        if gate_res.answer_blocked:
            refusal = generate_refusal_response(
                question=question,
                status=gate_res.overall_status,
                reasons=gate_res.blocking_reasons,
                proof_id=proof_id,
            )
            return refusal, True, gate_res

        # 5. Permitted verified draft
        return draft_text, False, gate_res

    def _generate_draft_text(self, question: str, val_str: str, raw_val: Any) -> str:
        """Generate answer text using LLM if available, or deterministic template."""
        if self.llm_client:
            prompt_messages = [
                {
                    "role": "system",
                    "content": (
                        "You are an answer drafting assistant for ProofLens.\n"
                        "STRICT RULES:\n"
                        "1. Do NOT introduce any numerical value that does not appear in the verified evidence.\n"
                        "2. Do NOT invent conclusions or extrapolate.\n"
                        "3. Answer the user question concisely using the exact verified value.\n"
                        "4. State the number clearly and unambiguously."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question: {question}\n"
                        f"Verified Authoritative Evidence Value: {val_str}\n"
                        "Draft a one-sentence factual answer to the question using this exact value."
                    ),
                },
            ]
            try:
                resp = self.llm_client.generate(prompt_messages)
                if resp and resp.strip():
                    return resp.strip()
            except Exception as e:
                logger.warning("LLM draft generation failed: %s; using deterministic draft.", e)

        # Deterministic factual draft fallback
        return f"Based on verified data analysis, the result for '{question}' is {val_str}."
