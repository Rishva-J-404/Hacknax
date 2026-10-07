"""
tests.test_truth_gate
---------------------
Comprehensive test suite for Phase 8 — Claim-Level Truth Gate.

Covers all 15 trap tests specified in PROOFLENS_MASTER_CONTEXT.md §18, §19, §20.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from app.agent.contracts import AggregationSpec, AnalysisPlan, ColumnRef, PlanStatus, UnanswerableReason
from app.execution.contracts import ExecutionResult
from app.repair.contracts import RepairWorld
from app.truth.contracts import TruthGateResult, TruthStatus
from app.truth.gate import TruthGate, evaluate_truth_gate
from app.verification.contracts import VerificationResult, VerificationStatus


@pytest.fixture
def gate() -> TruthGate:
    return TruthGate()


@pytest.fixture
def valid_plan() -> AnalysisPlan:
    return AnalysisPlan(
        question="Total revenue",
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
def valid_vr() -> VerificationResult:
    return VerificationResult(
        world_id="world_001",
        status=VerificationStatus.VERIFIED,
        pandas_result=1000.0,
        duckdb_result=1000.0,
        primary_result=1000.0,
        independent_result=1000.0,
        results_match=True,
        verification_passed=True,
        provenance_verified=True,
    )


@pytest.fixture
def valid_er() -> ExecutionResult:
    return ExecutionResult(
        world_id="world_001",
        code_path=Path("proofs/a.py"),
        stdout="1000.0\n",
        exit_code=0,
        execution_success=True,
        result_value=1000.0,
        generated_code_hash="code_hash_123",
        input_data_hashes={"orders": "data_hash_123"},
    )


# 1. Correct result + correct claim -> VERIFIED
def test_gate_correct_result_and_claim_verified(gate: TruthGate, valid_vr: VerificationResult, valid_er: ExecutionResult, valid_plan: AnalysisPlan):
    draft = "Total revenue was ₹1000.0."
    res = gate.evaluate(draft, verification_result=valid_vr, execution_result=valid_er, plan=valid_plan)
    assert res.overall_status == TruthStatus.VERIFIED
    assert res.answer_blocked is False
    assert res.deterministic_decision == "PERMITTED"
    assert len(res.verified_claims) >= 1
    assert len(res.unsupported_claims) == 0


# 2. Correct result + wrong claim -> CONTRADICTED
def test_gate_correct_result_and_wrong_claim_contradicted(gate: TruthGate, valid_vr: VerificationResult, valid_er: ExecutionResult, valid_plan: AnalysisPlan):
    draft = "Total revenue was ₹1200.0."
    res = gate.evaluate(draft, verification_result=valid_vr, execution_result=valid_er, plan=valid_plan)
    assert res.overall_status == TruthStatus.CONTRADICTED
    assert res.answer_blocked is True
    assert res.deterministic_decision == "BLOCKED"


# 3. Correct result + unsupported extra number -> NOT_VERIFIED
def test_gate_unsupported_extra_number_not_verified(gate: TruthGate, valid_vr: VerificationResult, valid_er: ExecutionResult, valid_plan: AnalysisPlan):
    draft = "Total revenue was ₹1000.0. Unrecorded profit was 450.0."
    res = gate.evaluate(draft, verification_result=valid_vr, execution_result=valid_er, plan=valid_plan)
    assert res.overall_status == TruthStatus.NOT_VERIFIED
    assert res.answer_blocked is True
    assert res.deterministic_decision == "BLOCKED"
    assert any("450" in r for r in res.blocking_reasons)


# 4. Correct result + unsupported percentage -> NOT_VERIFIED
def test_gate_unsupported_percentage_not_verified(gate: TruthGate, valid_vr: VerificationResult, valid_er: ExecutionResult, valid_plan: AnalysisPlan):
    draft = "Total revenue was ₹1000.0 and margins grew by 15%."
    res = gate.evaluate(draft, verification_result=valid_vr, execution_result=valid_er, plan=valid_plan)
    assert res.overall_status == TruthStatus.NOT_VERIFIED
    assert res.answer_blocked is True


# 5. Ambiguous date -> AMBIGUOUS
def test_gate_ambiguous_date(gate: TruthGate, valid_vr: VerificationResult):
    ambig_plan = AnalysisPlan(
        question="Revenue on 01/02/2024",
        status=PlanStatus.AMBIGUOUS,
        unanswerable_reason=UnanswerableReason.AMBIGUOUS_DATE,
    )
    draft = "Revenue was 1000.0 on 01/02/2024."
    res = gate.evaluate(draft, verification_result=valid_vr, plan=ambig_plan)
    assert res.overall_status == TruthStatus.AMBIGUOUS
    assert res.answer_blocked is True


# 6. Missing baseline -> UNANSWERABLE
def test_gate_missing_baseline_unanswerable(gate: TruthGate, valid_vr: VerificationResult):
    unans_plan = AnalysisPlan(
        question="Revenue growth rate",
        status=PlanStatus.UNANSWERABLE,
        unanswerable_reason=UnanswerableReason.NO_DATA_SOURCES,
        unanswerable_evidence="No baseline period data found.",
    )
    draft = "Revenue growth was 1000.0."
    res = gate.evaluate(draft, verification_result=valid_vr, plan=unans_plan)
    assert res.overall_status == TruthStatus.UNANSWERABLE
    assert res.answer_blocked is True


# 7. Provenance mismatch -> NOT_VERIFIED
def test_gate_provenance_mismatch_not_verified(gate: TruthGate, valid_plan: AnalysisPlan):
    vr_prov_fail = VerificationResult(
        world_id="world_001",
        status=VerificationStatus.NOT_VERIFIED,
        verification_passed=False,
        provenance_verified=False,
        failures=["Table hash mismatch"],
    )
    draft = "Total revenue was 1000.0."
    res = gate.evaluate(draft, verification_result=vr_prov_fail, plan=valid_plan)
    assert res.overall_status == TruthStatus.NOT_VERIFIED
    assert res.answer_blocked is True


# 8. Verification failure -> CONTRADICTED
def test_gate_verification_failure_contradicted(gate: TruthGate, valid_plan: AnalysisPlan):
    vr_failed = VerificationResult(
        world_id="world_001",
        status=VerificationStatus.FAILED,
        verification_passed=False,
        results_match=False,
        failures=["Dual-path contradiction: Pandas=1000.0, DuckDB=1200.0"],
    )
    draft = "Total revenue was 1000.0."
    res = gate.evaluate(draft, verification_result=vr_failed, plan=valid_plan)
    assert res.overall_status == TruthStatus.CONTRADICTED
    assert res.answer_blocked is True


# 9. Correct value but wrong unit -> NOT_VERIFIED
def test_gate_correct_value_wrong_unit(gate: TruthGate, valid_vr: VerificationResult, valid_plan: AnalysisPlan):
    # Expected INR, claimed USD
    draft = "Total revenue was $1000.0."
    res = gate.evaluate(draft, verification_result=valid_vr, plan=valid_plan)
    assert res.overall_status == TruthStatus.NOT_VERIFIED
    assert res.answer_blocked is True


# 10. Excessive precision -> NOT_VERIFIED
def test_gate_excessive_precision(gate: TruthGate, valid_plan: AnalysisPlan):
    vr = VerificationResult(
        world_id="world_001",
        status=VerificationStatus.VERIFIED,
        primary_result=18.42,
        duckdb_result=18.42,
        verification_passed=True,
        provenance_verified=True,
    )
    draft = "Total revenue was 18.423871928381."
    res = gate.evaluate(draft, verification_result=vr, plan=valid_plan)
    assert res.overall_status == TruthStatus.NOT_VERIFIED
    assert res.answer_blocked is True


# 11. VERIFIED main claim + unsupported conclusion -> overall NOT_VERIFIED
def test_gate_verified_main_claim_with_unsupported_conclusion(gate: TruthGate, valid_vr: VerificationResult, valid_plan: AnalysisPlan):
    draft = "Total revenue was 1000.0. This shows customer satisfaction increased."
    res = gate.evaluate(draft, verification_result=valid_vr, plan=valid_plan)
    assert res.overall_status == TruthStatus.NOT_VERIFIED
    assert res.answer_blocked is True


# 12. Multiple claims where one is contradicted -> overall CONTRADICTED
def test_gate_multiple_claims_one_contradicted(gate: TruthGate, valid_vr: VerificationResult, valid_plan: AnalysisPlan):
    draft = "Total revenue was 1000.0. However, total revenue was also reported as 9999.0."
    res = gate.evaluate(draft, verification_result=valid_vr, plan=valid_plan)
    assert res.overall_status == TruthStatus.CONTRADICTED
    assert res.answer_blocked is True


# 13. Assumption-backed answer -> VERIFIED_WITH_ASSUMPTION
def test_gate_assumption_backed_answer(gate: TruthGate, valid_vr: VerificationResult, valid_plan: AnalysisPlan):
    world_assump = RepairWorld(
        world_id="world_001",
        description="Assumed world",
        policies=[],
        assumptions=["Interpreted all ambiguous dates as DD/MM/YYYY"],
    )
    draft = "Total revenue was 1000.0."
    res = gate.evaluate(draft, verification_result=valid_vr, plan=valid_plan, world=world_assump)
    assert res.overall_status == TruthStatus.VERIFIED_WITH_ASSUMPTION
    assert res.answer_blocked is False
    assert res.deterministic_decision == "PERMITTED"
    assert len(res.assumptions) == 1


# 14. No numerical claim but unsupported factual claim -> NOT_VERIFIED
def test_gate_unsupported_factual_claim(gate: TruthGate, valid_vr: VerificationResult, valid_plan: AnalysisPlan):
    draft = "Data was validated by our third party auditor."
    res = gate.evaluate(draft, verification_result=valid_vr, plan=valid_plan)
    assert res.overall_status == TruthStatus.NOT_VERIFIED
    assert res.answer_blocked is True


# 15. Evidence references missing -> NOT_VERIFIED
def test_gate_missing_evidence_refs(gate: TruthGate, valid_plan: AnalysisPlan):
    draft = "Revenue was 1000.0."
    res = gate.evaluate(draft, verification_result=None, plan=valid_plan)
    assert res.overall_status == TruthStatus.NOT_VERIFIED
    assert res.answer_blocked is True


# 16. Convenience function evaluate_truth_gate
def test_gate_convenience_function(valid_vr: VerificationResult, valid_plan: AnalysisPlan):
    draft = "Total revenue was ₹1000.0."
    res = evaluate_truth_gate(draft, verification_result=valid_vr, plan=valid_plan)
    assert res.overall_status == TruthStatus.VERIFIED
    assert res.deterministic_decision == "PERMITTED"
