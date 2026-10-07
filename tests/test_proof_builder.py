"""
tests.test_proof_builder
------------------------
Comprehensive test suite for deterministic ProofCardBuilder.
Covers trap tests 1-6, 11-13 from Phase 9 specification.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.agent.contracts import (
    AggregationSpec,
    AmbiguityFlag,
    AnalysisPlan,
    ColumnRef,
    PlanStatus,
    UnanswerableReason,
)
from app.audit.contracts import DataIssue, IssueSeverity, IssueType
from app.execution.contracts import ExecutionResult, GeneratedCode
from app.proof.builder import ProofCardBuilder, build_proof_card
from app.proof.contracts import ProofCard
from app.repair.contracts import RepairPolicy, RepairWorld
from app.truth.contracts import Claim, ClaimType, TruthGateResult, TruthStatus
from app.verification.contracts import VerificationCheck, VerificationResult, VerificationStatus


@pytest.fixture
def builder() -> ProofCardBuilder:
    return ProofCardBuilder()


@pytest.fixture
def sample_plan() -> AnalysisPlan:
    return AnalysisPlan(
        question="Total revenue in 2025",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(
            column=ColumnRef(table="orders", column="amount"),
            operation="sum",
            unit="INR",
        ),
    )


@pytest.fixture
def sample_exec() -> ExecutionResult:
    return ExecutionResult(
        world_id="world_001",
        code_path=Path("proofs/test_analysis.py"),
        stdout="1000.0\n",
        exit_code=0,
        execution_success=True,
        result_value=1000.0,
        generated_code_hash="code_hash_abc",
        input_data_hashes={"orders": "data_hash_orders"},
    )


@pytest.fixture
def sample_vr() -> VerificationResult:
    return VerificationResult(
        world_id="world_001",
        status=VerificationStatus.VERIFIED,
        pandas_result=1000.0,
        duckdb_result=1000.0,
        primary_result=1000.0,
        results_match=True,
        verification_passed=True,
        provenance_verified=True,
    )


# 1. Trap 1: VERIFIED proof card
def test_build_verified_proof_card(
    builder: ProofCardBuilder,
    sample_plan: AnalysisPlan,
    sample_exec: ExecutionResult,
    sample_vr: VerificationResult,
):
    tg_res = TruthGateResult(
        overall_status=TruthStatus.VERIFIED,
        answer_blocked=False,
        deterministic_decision="PERMITTED",
        verified_claims=[
            Claim(claim_text="Total revenue is ₹1000.0", claim_type=ClaimType.NUMERICAL_VALUE, numerical_value=1000.0, supported=True)
        ],
    )
    card = builder.build(
        question="Total revenue in 2025",
        analysis_plan=sample_plan,
        execution_result=sample_exec,
        verification_result=sample_vr,
        truth_gate_result=tg_res,
    )
    assert card.status == TruthStatus.VERIFIED
    assert card.result == 1000.0
    assert card.answer_blocked is False
    assert card.deterministic_decision == "PERMITTED"
    assert card.proof_id.startswith("proof_")
    assert card.hashes is not None
    assert card.hashes.canonical_proof_sha256 is not None


# 2. Trap 2: VERIFIED_WITH_ASSUMPTION proof card
def test_build_verified_with_assumption(
    builder: ProofCardBuilder,
    sample_plan: AnalysisPlan,
    sample_exec: ExecutionResult,
    sample_vr: VerificationResult,
):
    world = RepairWorld(
        world_id="world_assump",
        description="Assumed dates DD/MM/YYYY",
        policies=[],
        assumptions=["Interpreted all dates as DD/MM/YYYY"],
    )
    tg_res = TruthGateResult(
        overall_status=TruthStatus.VERIFIED_WITH_ASSUMPTION,
        answer_blocked=False,
        deterministic_decision="PERMITTED",
        assumptions=["Interpreted all dates as DD/MM/YYYY"],
    )
    card = builder.build(
        question="Total revenue in 2025",
        analysis_plan=sample_plan,
        repair_world=world,
        execution_result=sample_exec,
        verification_result=sample_vr,
        truth_gate_result=tg_res,
    )
    assert card.status == TruthStatus.VERIFIED_WITH_ASSUMPTION
    assert card.answer_blocked is False
    assert len(card.assumptions) == 1
    assert "DD/MM/YYYY" in card.assumptions[0]


# 3. Trap 3 & 13: CONTRADICTED proof & Blocked answer still generates failure proof
def test_build_contradicted_failure_proof(
    builder: ProofCardBuilder,
    sample_plan: AnalysisPlan,
    sample_exec: ExecutionResult,
    sample_vr: VerificationResult,
):
    tg_res = TruthGateResult(
        overall_status=TruthStatus.CONTRADICTED,
        answer_blocked=True,
        deterministic_decision="BLOCKED",
        blocking_reasons=["Claimed value 1200 contradicts verified value 1000"],
        failed_claims=[
            Claim(claim_text="Total revenue was 1200", claim_type=ClaimType.NUMERICAL_VALUE, numerical_value=1200.0, supported=False, status=TruthStatus.CONTRADICTED)
        ],
    )
    card = builder.build(
        question="Total revenue in 2025",
        analysis_plan=sample_plan,
        execution_result=sample_exec,
        verification_result=sample_vr,
        truth_gate_result=tg_res,
    )
    assert card.status == TruthStatus.CONTRADICTED
    assert card.answer_blocked is True
    assert card.deterministic_decision == "BLOCKED"
    assert len(card.blocking_reasons) == 1
    assert "contradicts" in card.blocking_reasons[0]
    # Proof artifact is still generated as failure evidence
    assert card.proof_id.startswith("proof_")


# 4. Trap 4: NOT_VERIFIED proof
def test_build_not_verified_proof(
    builder: ProofCardBuilder,
    sample_plan: AnalysisPlan,
    sample_exec: ExecutionResult,
):
    tg_res = TruthGateResult(
        overall_status=TruthStatus.NOT_VERIFIED,
        answer_blocked=True,
        deterministic_decision="BLOCKED",
        blocking_reasons=["Extra unsupported claim: margins grew by 15%"],
    )
    card = builder.build(
        question="Total revenue in 2025",
        analysis_plan=sample_plan,
        execution_result=sample_exec,
        truth_gate_result=tg_res,
    )
    assert card.status == TruthStatus.NOT_VERIFIED
    assert card.answer_blocked is True
    assert card.deterministic_decision == "BLOCKED"


# 5. Trap 5: UNANSWERABLE proof
def test_build_unanswerable_proof(builder: ProofCardBuilder):
    unans_plan = AnalysisPlan(
        question="Calculate profit margins",
        status=PlanStatus.UNANSWERABLE,
        unanswerable_reason=UnanswerableReason.NO_DATA_SOURCES,
        unanswerable_evidence="No profit or cost table exists in data.",
    )
    card = builder.build(question="Calculate profit margins", analysis_plan=unans_plan)
    assert card.status == TruthStatus.UNANSWERABLE
    assert card.result is None
    assert card.answer_blocked is True
    assert card.deterministic_decision == "BLOCKED"
    assert "No profit" in (card.refusal_reason or "")


# 6. Trap 6: AMBIGUOUS proof
def test_build_ambiguous_proof(builder: ProofCardBuilder):
    ambig_plan = AnalysisPlan(
        question="Revenue on 01/02/2024",
        status=PlanStatus.AMBIGUOUS,
        ambiguity_flags=[
            AmbiguityFlag(
                description="Ambiguous date DD/MM vs MM/DD",
                affected_columns=[ColumnRef(table="orders", column="date")],
            )
        ],
    )
    card = builder.build(question="Revenue on 01/02/2024", analysis_plan=ambig_plan)
    assert card.status == TruthStatus.AMBIGUOUS
    assert card.result is None
    assert card.answer_blocked is True
    assert card.deterministic_decision == "BLOCKED"


# 7. Trap 11: Deterministic proof ID
def test_deterministic_proof_id(
    builder: ProofCardBuilder,
    sample_plan: AnalysisPlan,
    sample_exec: ExecutionResult,
    sample_vr: VerificationResult,
):
    tg = TruthGateResult(overall_status=TruthStatus.VERIFIED, answer_blocked=False, deterministic_decision="PERMITTED")
    card1 = builder.build("Total revenue", analysis_plan=sample_plan, execution_result=sample_exec, verification_result=sample_vr, truth_gate_result=tg)
    card2 = builder.build("Total revenue", analysis_plan=sample_plan, execution_result=sample_exec, verification_result=sample_vr, truth_gate_result=tg)

    assert card1.proof_id == card2.proof_id
    assert card1.hashes.canonical_proof_sha256 == card2.hashes.canonical_proof_sha256


# 8. Trap 12: Deterministic canonical JSON independent of timestamps
def test_deterministic_canonical_payload_independent_of_timestamp(
    builder: ProofCardBuilder,
    sample_plan: AnalysisPlan,
    sample_exec: ExecutionResult,
    sample_vr: VerificationResult,
):
    tg = TruthGateResult(overall_status=TruthStatus.VERIFIED, answer_blocked=False, deterministic_decision="PERMITTED")
    t1 = datetime(2026, 10, 7, 10, 0, 0)
    t2 = datetime(2026, 10, 7, 15, 30, 45)

    card1 = builder.build("Total revenue", analysis_plan=sample_plan, execution_result=sample_exec, verification_result=sample_vr, truth_gate_result=tg, created_at=t1)
    card2 = builder.build("Total revenue", analysis_plan=sample_plan, execution_result=sample_exec, verification_result=sample_vr, truth_gate_result=tg, created_at=t2)

    assert card1.proof_id == card2.proof_id
    assert card1.hashes.canonical_proof_sha256 == card2.hashes.canonical_proof_sha256


# 9. Lineage and provenance details populated
def test_lineage_and_provenance_populated(
    builder: ProofCardBuilder,
    sample_plan: AnalysisPlan,
    sample_exec: ExecutionResult,
    sample_vr: VerificationResult,
):
    card = builder.build("Total revenue", analysis_plan=sample_plan, execution_result=sample_exec, verification_result=sample_vr)
    assert card.lineage is not None
    assert "orders" in card.lineage.tables_used
    assert "orders.amount" in card.lineage.columns_used
    assert any("SUM" in t for t in card.lineage.transformations)


# 10. Formatted INR Crore display
def test_formatted_display_crore_scaling(builder: ProofCardBuilder, sample_plan: AnalysisPlan):
    exec_res = ExecutionResult(
        world_id="w1",
        code_path=Path("proofs/test_analysis.py"),
        exit_code=0,
        stdout="184200000.0\n",
        result_value=184200000.0,
        execution_success=True,
    )
    tg = TruthGateResult(overall_status=TruthStatus.VERIFIED, answer_blocked=False, deterministic_decision="PERMITTED")
    card = builder.build("Total revenue in 2025", analysis_plan=sample_plan, execution_result=exec_res, truth_gate_result=tg)
    assert card.formatted_result == "₹18.42 Cr"
    assert card.relevant_period == "2025"


# 11. Metamorphic summary included
def test_metamorphic_summary_included(builder: ProofCardBuilder, sample_plan: AnalysisPlan, sample_exec: ExecutionResult):
    from app.verification.contracts import CheckOutcome, MetamorphicTestResult
    vr = VerificationResult(
        world_id="w1",
        status=VerificationStatus.VERIFIED,
        verification_passed=True,
        metamorphic_results=[
            MetamorphicTestResult(
                name="METAMORPHIC_ROW_SHUFFLE",
                status=CheckOutcome.PASS,
                applicable=True,
                expected="Order invariance test",
                observed="PASS",
            )
        ],
    )
    card = builder.build("Total revenue", analysis_plan=sample_plan, execution_result=sample_exec, verification_result=vr)
    assert len(card.metamorphic_summary) == 1
    assert card.metamorphic_summary[0]["status"] == "PASS"


# 12. Convenience function build_proof_card
def test_convenience_function():
    card = build_proof_card("Total revenue")
    assert isinstance(card, ProofCard)
    assert card.proof_id.startswith("proof_")
