"""
tests.test_proof_renderer
-------------------------
Unit tests for human-readable ProofCard text rendering.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.execution.contracts import ExecutionResult
from app.proof.builder import build_proof_card
from app.proof.contracts import ProofCard
from app.proof.renderer import render_proof_card_text, save_proof_card_text
from app.truth.contracts import Claim, ClaimType, TruthGateResult, TruthStatus
from app.verification.contracts import VerificationResult, VerificationStatus


@pytest.fixture
def sample_verified_card() -> ProofCard:
    tg = TruthGateResult(
        overall_status=TruthStatus.VERIFIED,
        answer_blocked=False,
        deterministic_decision="PERMITTED",
        verified_claims=[
            Claim(claim_text="Total revenue was ₹1000.0", claim_type=ClaimType.NUMERICAL_VALUE, numerical_value=1000.0, supported=True)
        ],
    )
    vr = VerificationResult(
        world_id="w1",
        status=VerificationStatus.VERIFIED,
        primary_result=1000.0,
        duckdb_result=1000.0,
        verification_passed=True,
    )
    exec_res = ExecutionResult(
        world_id="w1",
        code_path=Path("proofs/test_analysis.py"),
        exit_code=0,
        stdout="1000.0\n",
        result_value=1000.0,
        execution_success=True,
    )
    return build_proof_card("What was total revenue?", verification_result=vr, execution_result=exec_res, truth_gate_result=tg)


def test_render_proof_card_text_headers(sample_verified_card: ProofCard):
    text = render_proof_card_text(sample_verified_card)
    assert "PROOFLENS PROOF CARD" in text
    assert "Proof ID:" in text
    assert "Question:" in text
    assert "What was total revenue?" in text


def test_render_verified_result_and_unit(sample_verified_card: ProofCard):
    text = render_proof_card_text(sample_verified_card)
    assert "Status:" in text
    assert "VERIFIED" in text
    assert "1000.0" in text
    assert "Decision:             PERMITTED" in text


def test_render_blocked_answer():
    tg = TruthGateResult(
        overall_status=TruthStatus.CONTRADICTED,
        answer_blocked=True,
        deterministic_decision="BLOCKED",
        blocking_reasons=["Claimed 1500 contradicts verified calculation 1000"],
    )
    card = build_proof_card("Total revenue", truth_gate_result=tg)
    text = render_proof_card_text(card)
    assert "[ANSWER BLOCKED - NO PROOF = NO NUMBER]" in text
    assert "Decision:             BLOCKED" in text
    assert "Claimed 1500 contradicts verified" in text


def test_render_repair_world_and_policy(sample_verified_card: ProofCard):
    text = render_proof_card_text(sample_verified_card)
    assert "Repair World:" in text
    assert "Policy:" in text


def test_render_verification_and_metamorphic(sample_verified_card: ProofCard):
    text = render_proof_card_text(sample_verified_card)
    assert "Primary Result:" in text
    assert "Independent Result (DuckDB):" in text
    assert "Verification:" in text
    assert "PASS" in text


def test_save_proof_card_text_to_disk(sample_verified_card: ProofCard, tmp_path: Path):
    saved_txt = save_proof_card_text(sample_verified_card, output_dir=tmp_path)
    assert saved_txt.exists()
    assert saved_txt.suffix == ".txt"
    content = saved_txt.read_text(encoding="utf-8")
    assert "PROOFLENS PROOF CARD" in content
