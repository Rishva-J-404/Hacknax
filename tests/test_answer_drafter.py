"""
tests.test_answer_drafter
-------------------------
Unit tests for untrusted AnswerDrafter and deterministic refusal generation.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from app.agent.answer_drafter import AnswerDrafter, generate_refusal_response
from app.agent.qwen_client import MockQwenClient
from app.execution.contracts import ExecutionResult
from app.truth.contracts import TruthGateResult, TruthStatus
from app.verification.contracts import VerificationResult, VerificationStatus


def test_refusal_generation_contradicted():
    refusal = generate_refusal_response(
        question="Total revenue",
        status=TruthStatus.CONTRADICTED,
        reasons=["DuckDB independent check diverged by 150.0"],
        proof_id="proof_12345",
    )
    assert "cannot provide a verified numerical answer" in refusal
    assert "contradiction" in refusal
    assert "proof_12345" in refusal


def test_refusal_generation_unanswerable():
    refusal = generate_refusal_response(
        question="Operating margin",
        status=TruthStatus.UNANSWERABLE,
        reasons=["Margin column not found"],
    )
    assert "required data or columns are not available" in refusal
    assert "Margin column not found" in refusal


def test_refusal_generation_ambiguous():
    refusal = generate_refusal_response(
        question="Sales in 2024",
        status=TruthStatus.AMBIGUOUS,
        reasons=["Ambiguous date format"],
    )
    assert "multiple defensible interpretations exist" in refusal


def test_draft_and_verify_blocked_when_overall_contradicted():
    drafter = AnswerDrafter()
    exec_res = ExecutionResult(
        world_id="w1",
        code_path=Path("analysis.py"),
        exit_code=0,
        result_value=600.0,
        execution_success=True,
    )
    vr = VerificationResult(
        world_id="w1",
        status=VerificationStatus.FAILED,
        primary_result=600.0,
        duckdb_result=450.0,
        verification_passed=False,
        failures=["Diverged from DuckDB"],
    )
    answer, is_blocked, gate_res = drafter.draft_and_verify(
        question="Total revenue",
        execution_result=exec_res,
        verification_result=vr,
        overall_status=TruthStatus.CONTRADICTED,
    )
    assert is_blocked is True
    assert "contradiction" in answer
    assert gate_res.answer_blocked is True


def test_draft_and_verify_permitted_on_verified():
    drafter = AnswerDrafter()
    exec_res = ExecutionResult(
        world_id="w1",
        code_path=Path("analysis.py"),
        exit_code=0,
        result_value=600.0,
        execution_success=True,
    )
    vr = VerificationResult(
        world_id="w1",
        status=VerificationStatus.VERIFIED,
        primary_result=600.0,
        duckdb_result=600.0,
        verification_passed=True,
    )
    answer, is_blocked, gate_res = drafter.draft_and_verify(
        question="Total revenue",
        execution_result=exec_res,
        verification_result=vr,
        overall_status=TruthStatus.VERIFIED,
        formatted_result="600.0",
    )
    assert is_blocked is False
    assert "600.0" in answer
    assert gate_res.answer_blocked is False


def test_draft_and_verify_blocks_hallucinated_number():
    """
    If the LLM drafter hallucinates a completely unsupported number (e.g. 999999)
    in its draft text, ClaimExtractor and TruthGate must detect and block it.
    """
    hallucinating_client = MockQwenClient(canned_response="The total revenue is 999999.0 dollars.")
    drafter = AnswerDrafter(llm_client=hallucinating_client)

    exec_res = ExecutionResult(
        world_id="w1",
        code_path=Path("analysis.py"),
        exit_code=0,
        result_value=600.0,  # Real value is 600.0
        execution_success=True,
    )
    vr = VerificationResult(
        world_id="w1",
        status=VerificationStatus.VERIFIED,
        primary_result=600.0,
        duckdb_result=600.0,
        verification_passed=True,
    )
    answer, is_blocked, gate_res = drafter.draft_and_verify(
        question="Total revenue",
        execution_result=exec_res,
        verification_result=vr,
        overall_status=TruthStatus.VERIFIED,
        formatted_result="600.0",
    )
    # The hallucinated 999999.0 claim does not match evidence 600.0 -> must be blocked!
    assert is_blocked is True
    assert gate_res.answer_blocked is True
