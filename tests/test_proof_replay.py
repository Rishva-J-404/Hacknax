"""
tests.test_proof_replay
-----------------------
Unit tests for independent proof replay and validation.
Covers trap tests 7, 8, 9, 10, 14, 15 from Phase 9 specification.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from app.execution.contracts import ExecutionResult
from app.proof.builder import build_proof_card
from app.proof.contracts import ProofCard
from app.proof.serializer import save_proof_card
from app.truth.contracts import TruthGateResult, TruthStatus
from app.verification.contracts import VerificationResult, VerificationStatus
from scripts.replay import replay_proof


@pytest.fixture
def replay_env(tmp_path: Path):
    """Create a self-contained fixture with an on-disk CSV and analysis script."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    csv_file = data_dir / "orders.csv"
    df = pd.DataFrame({"order_id": [1, 2, 3], "amount": [100.0, 200.0, 300.0]})
    df.to_csv(csv_file, index=False)

    csv_bytes = df.to_csv(index=False).encode("utf-8")
    dataset_hash = hashlib.sha256(csv_bytes).hexdigest()

    code_file = tmp_path / "analysis.py"
    code_content = (
        "df = tables['orders'].copy()\n"
        "RESULT = float(pd.to_numeric(df['amount']).sum())\n"
    )
    code_file.write_text(code_content, encoding="utf-8")
    code_hash = hashlib.sha256(code_content.encode("utf-8")).hexdigest()

    from app.audit.contracts import DataQualityLedger, TableProfile
    from app.execution.contracts import GeneratedCode

    gen_code = GeneratedCode(code_content=code_content, code_sha256=code_hash, code_path=code_file, world_id="w1")
    exec_res = ExecutionResult(
        world_id="w1",
        code_path=code_file,
        exit_code=0,
        stdout="600.0\n",
        result_value=600.0,
        execution_success=True,
        generated_code_hash=code_hash,
        input_data_hashes={"orders": dataset_hash},
    )
    vr = VerificationResult(
        world_id="w1",
        status=VerificationStatus.VERIFIED,
        primary_result=600.0,
        duckdb_result=600.0,
        verification_passed=True,
    )
    tg = TruthGateResult(overall_status=TruthStatus.VERIFIED, answer_blocked=False, deterministic_decision="PERMITTED")

    ledger = DataQualityLedger(
        table_profiles=[
            TableProfile(source=str(csv_file), row_count=3, column_count=2, column_names=["order_id", "amount"], dataset_sha256=dataset_hash)
        ]
    )

    card = build_proof_card(
        question="Total order amount",
        audit_ledger=ledger,
        execution_result=exec_res,
        verification_result=vr,
        truth_gate_result=tg,
        generated_code=gen_code,
    )

    proof_file = save_proof_card(card, output_dir=tmp_path)
    return {
        "proof_file": proof_file,
        "csv_file": csv_file,
        "code_file": code_file,
        "card": card,
        "df": df,
    }


# Trap 14: Replay succeeds on matching artifacts
def test_replay_succeeds_matching_artifacts(replay_env):
    res = replay_proof(replay_env["proof_file"])
    assert res.status == "PASS"
    assert "matches stored 600.0" in res.message


# Trap 15: Replay reports INCOMPLETE when data is unavailable
def test_replay_reports_incomplete_when_data_missing(tmp_path: Path):
    from app.audit.contracts import DataQualityLedger, TableProfile
    missing_file = tmp_path / "nonexistent.csv"
    ledger = DataQualityLedger(
        table_profiles=[
            TableProfile(source=str(missing_file), row_count=10, column_count=2, column_names=["a", "b"], dataset_sha256="abc123hash")
        ]
    )
    card = build_proof_card("Total revenue", audit_ledger=ledger)
    proof_path = save_proof_card(card, output_dir=tmp_path)

    res = replay_proof(proof_path)
    assert res.status == "INCOMPLETE"
    assert "unavailable on disk" in res.message


# Trap 7: Wrong code hash detected
def test_replay_wrong_code_hash_fails(replay_env):
    card = replay_env["card"]
    # Corrupt code hash
    card.hashes.analysis_code_sha256 = "corrupted_code_hash_123"
    res = replay_proof(card)
    assert res.status == "FAIL"


# Trap 8: Wrong input hash detected
def test_replay_wrong_input_hash_fails(replay_env):
    card = replay_env["card"]
    # Alter the physical CSV on disk to produce a different hash
    csv_file = replay_env["csv_file"]
    csv_file.write_text("order_id,amount\n1,9999.0\n", encoding="utf-8")

    res = replay_proof(card)
    assert res.status == "FAIL"


# Trap 10: Tampered proof payload fails replay
def test_replay_tampered_proof_payload_fails(replay_env):
    card = replay_env["card"]
    card.question = "Tampered question: what was total profit?"
    res = replay_proof(card)
    assert res.status == "FAIL"
    assert "tampering detected" in res.message


# Nonexistent file returns FAIL
def test_replay_nonexistent_file_fails():
    res = replay_proof("nonexistent_proof_9999.json")
    assert res.status == "FAIL"
    assert "does not exist" in res.message


# Malformed JSON file returns FAIL
def test_replay_malformed_json_fails(tmp_path: Path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not json", encoding="utf-8")
    res = replay_proof(bad_file)
    assert res.status == "FAIL"
    assert "malformed" in res.message.lower()
