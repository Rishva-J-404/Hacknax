"""
app.orchestrator
----------------
End-to-End Pipeline Orchestrator for ProofLens.

CORE PRINCIPLES (PROOFLENS_MASTER_CONTEXT.md §2, §10, §11, §12, §13, §14):
    LLM PROPOSES.
    CODE COMPUTES.
    VERIFICATION DECIDES.
    NO PROOF = NO NUMBER.

The Orchestrator coordinates the complete 14-step verification pipeline:
    1. Ingestion: Load raw data without silent mutation.
    2. Audit: Run deterministic profiling to produce DataQualityLedger.
    3. Plan: Query Qwen (or deterministic planner) for structured AnalysisPlan.
    4. Plan Validation: Authoritative schema grounding & security validation.
    5. Unanswerability Gate: Refuse early if data/columns are missing or predictive.
    6. Repair Engine: Generate explicit, defensible RepairWorlds from audit ledger.
    7. Code Generation: Deterministically emit Python analysis script.
    8. Sandboxed Execution: Execute code across all worlds via SecureRunner.
    9. Dual-Path Verification: Independently verify primary result against DuckDB.
    10. Metamorphic Validation: Run invariant checks across data transformations.
    11. Cross-World Impact Analysis: Evaluate spread and decision stability across worlds.
    12. Claim Truth Gate: Verify draft claims through ClaimExtractor, Skeptic, and Gate.
    13. Proof Card Synthesis: Deterministically assemble and serialize ProofCard.
    14. Output OrchestratorResult: Return structured, audited final answer.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, Field

from app.agent.answer_drafter import AnswerDrafter, generate_refusal_response
from app.agent.contracts import AnalysisPlan, PlanStatus, UnanswerableReason
from app.agent.plan_validator import PlanValidator
from app.agent.planner import DeterministicPlanner, PlannerBackend
from app.agent.qwen_client import LLMClient, OpenRouterQwenClient
from app.agent.qwen_planner import QwenPlanner
from app.audit.contracts import DataQualityLedger
from app.audit.profiler import audit_tables
from app.execution.code_generator import generate_analysis_code
from app.execution.contracts import ExecutionResult, GeneratedCode
from app.execution.runner import SecureRunner
from app.ingestion.contracts import DataSourceRef, LoadedTable
from app.ingestion.loader import load_file
from app.proof.builder import build_proof_card
from app.proof.contracts import ProofCard
from app.proof.serializer import save_proof_card
from app.repair.contracts import RepairError, RepairWorld
from app.repair.engine import RepairEngine
from app.skeptic.agent import SkepticAgent
from app.truth.contracts import TruthGateResult, TruthStatus
from app.truth.gate import TruthGate
from app.verification.contracts import ImpactAnalysis, VerificationResult, VerificationStatus
from app.verification.engine import VerificationEngine
from app.verification.metamorphic import MetamorphicSuite

logger = logging.getLogger(__name__)


class OrchestratorResult(BaseModel):
    """Structured, authoritative output of the end-to-end ProofLens pipeline."""

    question: str = Field(..., description="The original analytical question asked.")
    status: TruthStatus = Field(..., description="Final authoritative truth status.")
    answer: str = Field(..., description="Audited natural language answer or refusal.")
    answer_blocked: bool = Field(..., description="True if TruthGate blocked answer publication.")
    result: Any = Field(default=None, description="Authoritative numeric/metric value computed by code.")
    proof_card: ProofCard = Field(..., description="Complete, tamper-evident ProofCard.")
    repair_worlds: list[RepairWorld] = Field(default_factory=list, description="All repair worlds generated.")
    impact_analysis: ImpactAnalysis | None = Field(default=None, description="Cross-world sensitivity analysis.")
    verification: VerificationResult | None = Field(default=None, description="Primary verification record.")
    truth_gate: TruthGateResult | None = Field(default=None, description="Authoritative TruthGate decision.")
    errors: list[str] = Field(default_factory=list, description="Pipeline error messages.")
    warnings: list[str] = Field(default_factory=list, description="Pipeline warning messages.")


class ProofLensOrchestrator:
    """
    Coordinates data ingestion, deterministic audit, Qwen planning,
    sandboxed execution, dual-path verification, and proof card generation.
    """

    def __init__(
        self,
        planner: PlannerBackend | None = None,
        llm_client: LLMClient | None = None,
        proof_output_dir: Path | str = "proofs",
        session_id: str | None = None,
    ) -> None:
        self.session_id = session_id or "session_orchestrator"
        self.llm_client = llm_client
        if planner is not None:
            self.planner = planner
        elif llm_client is not None:
            self.planner = QwenPlanner(client=llm_client)
        else:
            openrouter_client = OpenRouterQwenClient()
            if openrouter_client.is_configured:
                self.planner = QwenPlanner(client=openrouter_client)
            else:
                self.planner = DeterministicPlanner()

        self.validator = PlanValidator()
        self.repair_engine = RepairEngine()
        self.runner = SecureRunner()
        self.verifier = VerificationEngine()
        self.metamorphic_suite = MetamorphicSuite()
        self.truth_gate = TruthGate()
        self.skeptic = SkepticAgent()
        self.answer_drafter = AnswerDrafter(
            llm_client=self.llm_client,
            truth_gate=self.truth_gate,
            skeptic_agent=self.skeptic,
        )
        self.proof_output_dir = Path(proof_output_dir)

    def run(
        self,
        question: str,
        sources: Sequence[str | Path | DataSourceRef | LoadedTable],
        output_dir: Path | str | None = None,
        repair_parameters: dict[str, Any] | None = None,
    ) -> OrchestratorResult:
        """
        Execute the full 14-stage ProofLens pipeline against specified input data sources.
        """
        out_dir = Path(output_dir) if output_dir else self.proof_output_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        errors: list[str] = []
        warnings: list[str] = []

        # ── STEP 1: Ingestion ──────────────────────────────────────────────────
        loaded_tables: list[LoadedTable] = []
        for src in sources:
            if isinstance(src, LoadedTable):
                loaded_tables.append(src)
            elif isinstance(src, DataSourceRef):
                loaded_tables.extend(load_file(src))
            else:
                p = Path(src)
                loaded_tables.extend(load_file(DataSourceRef(path=p)))

        if not loaded_tables:
            return self._handle_early_refusal(
                question=question,
                status=TruthStatus.UNANSWERABLE,
                reason="No valid data sources could be loaded.",
                out_dir=out_dir,
            )

        # ── STEP 2: Deterministic Data Audit ───────────────────────────────────
        ledger: DataQualityLedger = audit_tables(loaded_tables)

        # ── STEP 3: Analysis Planning ──────────────────────────────────────────
        plan: AnalysisPlan = self.planner.plan(
            question=question,
            tables=loaded_tables,
            ledger=ledger,
        )

        # ── STEP 4: Plan Validation ────────────────────────────────────────────
        val_res = self.validator.validate(plan, loaded_tables)
        if not val_res.is_valid:
            return self._handle_early_refusal(
                question=question,
                status=TruthStatus.UNANSWERABLE,
                reason="; ".join(val_res.errors),
                ledger=ledger,
                plan=plan,
                out_dir=out_dir,
            )

        # ── STEP 5: Grounding / Unanswerability & Ambiguity Check ───────────────
        if plan.status in (PlanStatus.UNANSWERABLE, PlanStatus.NEEDS_CLARIFICATION):
            reason_text = plan.unanswerable_evidence or str(plan.unanswerable_reason or "Question is unanswerable.")
            return self._handle_early_refusal(
                question=question,
                status=TruthStatus.UNANSWERABLE,
                reason=reason_text,
                ledger=ledger,
                plan=plan,
                out_dir=out_dir,
            )

        if plan.status == PlanStatus.AMBIGUOUS:
            reason_text = (
                plan.ambiguity_flags[0].description
                if plan.ambiguity_flags
                else "Unresolved ambiguity detected in data or question."
            )
            return self._handle_early_refusal(
                question=question,
                status=TruthStatus.AMBIGUOUS,
                reason=reason_text,
                ledger=ledger,
                plan=plan,
                out_dir=out_dir,
            )

        # ── STEP 6: Repair Worlds Generation ───────────────────────────────────
        try:
            repair_worlds = self.repair_engine.create_worlds_from_ledger(
                loaded_tables, ledger, parameters=repair_parameters
            )
        except RepairError as err:
            return self._handle_early_refusal(
                question=question,
                status=TruthStatus.UNANSWERABLE,
                reason=f"Data repair impossible: {err.detail if hasattr(err, 'detail') else err}",
                ledger=ledger,
                plan=plan,
                out_dir=out_dir,
            )

        if not repair_worlds:
            repair_worlds = [
                RepairWorld(
                    world_id="world_clean",
                    description="Original data unmodified",
                    policies=[],
                    repaired_tables=loaded_tables,
                )
            ]

        # Filter executable safe worlds (exclude impossible date/repair interpretations)
        valid_worlds = [w for w in repair_worlds if w.is_safe]

        if not valid_worlds:
            # All candidate worlds were impossible / unparseable
            reasons = []
            for w in repair_worlds:
                reasons.extend(w.safety_issues)
            refusal_reason = (
                "; ".join(reasons)
                if reasons
                else "All candidate repair worlds were impossible or unparseable for the data."
            )
            return self._handle_early_refusal(
                question=question,
                status=TruthStatus.UNANSWERABLE,
                reason=refusal_reason,
                ledger=ledger,
                plan=plan,
                worlds=repair_worlds,
                out_dir=out_dir,
            )

        # ── STEP 7: Code Generation ────────────────────────────────────────────
        primary_world = valid_worlds[0]
        gen_code_path = out_dir / f"analysis_{primary_world.world_id}.py"
        try:
            gen_code: GeneratedCode = generate_analysis_code(
                plan=plan,
                world_id=primary_world.world_id,
                output_path=gen_code_path,
            )
        except Exception as exc:
            return self._handle_early_refusal(
                question=question,
                status=TruthStatus.NOT_VERIFIED,
                reason=f"Failed to generate analysis code: {exc}",
                ledger=ledger,
                plan=plan,
                out_dir=out_dir,
            )

        # ── STEP 8: Sandboxed Primary Execution ────────────────────────────────
        primary_exec: ExecutionResult = self.runner.run(
            world=primary_world,
            plan=plan,
            code=gen_code,
        )

        if not primary_exec.execution_success:
            err_msg = primary_exec.execution_error or primary_exec.stderr or "Primary execution failed."
            errors.append(err_msg)
            return self._handle_early_refusal(
                question=question,
                status=TruthStatus.NOT_VERIFIED,
                reason=err_msg,
                ledger=ledger,
                plan=plan,
                worlds=repair_worlds,
                out_dir=out_dir,
            )

        # ── STEP 9: Independent Dual-Path DuckDB Verification ──────────────────
        verification_res: VerificationResult = self.verifier.verify(
            world=primary_world,
            plan=plan,
            execution_result=primary_exec,
            run_metamorphic=True,
        )

        # ── STEP 10: Metamorphic Validation ────────────────────────────────────
        metamorphic_res = self.metamorphic_suite.run_all(
            world=primary_world,
            plan=plan,
            baseline_result=primary_exec.result_value,
        )
        metamorphic_summary = {
            "total_tested": len(metamorphic_res),
            "passed": sum(1 for r in metamorphic_res if r.status.value == "PASS"),
            "failed": sum(1 for r in metamorphic_res if r.status.value == "FAIL"),
            "skipped": sum(1 for r in metamorphic_res if r.status.value == "SKIPPED"),
            "results": {r.name: r.status.value for r in metamorphic_res},
        }

        # ── STEP 11: Cross-World Execution & Impact Analysis ───────────────────
        impact_analysis: ImpactAnalysis | None = None
        world_results: dict[str, Any] = {primary_world.world_id: primary_exec.result_value}

        # Track any impossible worlds as None in world_results
        for w in repair_worlds:
            if not w.is_safe and w.world_id not in world_results:
                world_results[w.world_id] = None

        if len(valid_worlds) > 1:
            for extra_world in valid_worlds[1:]:
                extra_exec = self.runner.run(
                    world=extra_world,
                    plan=plan,
                    code=gen_code,
                )
                if extra_exec.execution_success:
                    world_results[extra_world.world_id] = extra_exec.result_value
                else:
                    world_results[extra_world.world_id] = None

            # Compute min, max, spread across valid numeric values
            numeric_vals = [v for v in world_results.values() if isinstance(v, (int, float))]
            if numeric_vals:
                min_val = min(numeric_vals)
                max_val = max(numeric_vals)
                spread_val = max_val - min_val
                val_stable = spread_val < 1e-6
                # Decision stability: stable if relative spread < 5% or sign invariant
                dec_stable = spread_val == 0.0 or (spread_val / (abs(max_val) + 1e-9) < 0.05)
                impact_analysis = ImpactAnalysis(
                    world_results=world_results,
                    minimum=min_val,
                    maximum=max_val,
                    spread=spread_val,
                    value_stable=val_stable,
                    decision_stable=dec_stable,
                )
            else:
                impact_analysis = ImpactAnalysis(world_results=world_results)

        # ── STEP 12: Truth Gate Evaluation ─────────────────────────────────────
        # If verification failed (mismatch with DuckDB), flag CONTRADICTED
        if verification_res.status == VerificationStatus.FAILED:
            tentative_status = TruthStatus.CONTRADICTED
        elif not verification_res.verification_passed:
            tentative_status = TruthStatus.NOT_VERIFIED
        elif plan.status == PlanStatus.AMBIGUOUS:
            tentative_status = TruthStatus.AMBIGUOUS
        elif impact_analysis and impact_analysis.decision_stable is False:
            tentative_status = TruthStatus.AMBIGUOUS
        elif primary_world.assumptions or (ledger and ledger.all_issues):
            tentative_status = TruthStatus.VERIFIED_WITH_ASSUMPTION
            if not primary_world.assumptions:
                primary_world.assumptions.extend(
                    [f"Data quality issue handled under policy: {p.selected_action}" for p in primary_world.policies]
                )
        else:
            tentative_status = TruthStatus.VERIFIED

        # ── STEP 13: Draft Answer & Verification Chain ─────────────────────────
        answer_text, is_blocked, gate_res = self.answer_drafter.draft_and_verify(
            question=question,
            execution_result=primary_exec,
            verification_result=verification_res,
            overall_status=tentative_status,
            world=primary_world,
            plan=plan,
        )

        final_status = gate_res.overall_status

        # If answer is blocked by truth gate, suppress authoritative result display
        final_result = None if is_blocked else primary_exec.result_value

        # ── STEP 14: Proof Card Assembly & Serialization ───────────────────────
        card = build_proof_card(
            question=question,
            analysis_plan=plan,
            audit_ledger=ledger,
            repair_world=primary_world,
            execution_result=primary_exec,
            verification_result=verification_res,
            truth_gate_result=gate_res,
            generated_code=gen_code,
            repair_worlds=repair_worlds,
            session_id=self.session_id,
            draft_explanation=answer_text,
        )

        # Update card impact range if multiple worlds
        if impact_analysis:
            card.impact_range = {
                "minimum": impact_analysis.minimum,
                "maximum": impact_analysis.maximum,
                "spread": impact_analysis.spread,
                "value_stable": impact_analysis.value_stable,
                "decision_stable": impact_analysis.decision_stable,
            }

        # Save proof card JSON to disk
        save_proof_card(card, output_dir=out_dir)

        return OrchestratorResult(
            question=question,
            status=final_status,
            answer=answer_text,
            answer_blocked=is_blocked,
            result=final_result,
            proof_card=card,
            repair_worlds=repair_worlds,
            impact_analysis=impact_analysis,
            verification=verification_res,
            truth_gate=gate_res,
            errors=errors,
            warnings=warnings,
        )

    def _handle_early_refusal(
        self,
        question: str,
        status: TruthStatus,
        reason: str,
        out_dir: Path,
        ledger: DataQualityLedger | None = None,
        plan: AnalysisPlan | None = None,
        worlds: list[RepairWorld] | None = None,
    ) -> OrchestratorResult:
        """Construct early refusal and ProofCard for unanswerable/blocked requests."""
        dummy_exec = ExecutionResult(
            world_id="unanswerable_world",
            code_path=out_dir / "unanswerable.py",
            exit_code=1,
            execution_success=False,
            execution_error=reason,
            duration_seconds=0.0,
        )
        gate_res = TruthGateResult(
            overall_status=status,
            answer_blocked=True,
            deterministic_decision="BLOCKED",
            blocking_reasons=[reason],
        )

        card = build_proof_card(
            question=question,
            audit_ledger=ledger,
            execution_result=dummy_exec,
            verification_result=None,
            truth_gate_result=gate_res,
            analysis_plan=plan,
            repair_worlds=worlds or [],
        )
        save_proof_card(card, output_dir=out_dir)

        refusal = generate_refusal_response(
            question=question,
            status=status,
            reasons=[reason],
            proof_id=card.proof_id,
        )

        return OrchestratorResult(
            question=question,
            status=status,
            answer=refusal,
            answer_blocked=True,
            result=None,
            proof_card=card,
            repair_worlds=worlds or [],
            truth_gate=gate_res,
            errors=[reason],
        )
