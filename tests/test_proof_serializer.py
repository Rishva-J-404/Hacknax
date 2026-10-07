"""
tests.test_proof_serializer
---------------------------
Unit tests for ProofCard JSON serialization, round-tripping, and cryptographic integrity.
Covers trap test 10 (Tampered proof payload).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.proof.builder import build_proof_card
from app.proof.contracts import ProofCard
from app.proof.serializer import (
    load_proof_card,
    save_proof_card,
    serialize_proof_card,
    verify_proof_card_integrity,
)
from app.truth.contracts import TruthGateResult, TruthStatus


@pytest.fixture
def sample_card() -> ProofCard:
    tg = TruthGateResult(overall_status=TruthStatus.VERIFIED, answer_blocked=False, deterministic_decision="PERMITTED")
    return build_proof_card("What was total revenue in 2025?", truth_gate_result=tg)


def test_serialize_proof_card_valid_json(sample_card: ProofCard):
    raw_json = serialize_proof_card(sample_card)
    assert isinstance(raw_json, str)
    parsed = json.loads(raw_json)
    assert parsed["proof_id"] == sample_card.proof_id
    assert parsed["question"] == sample_card.question
    assert parsed["status"] == "VERIFIED"


def test_serialize_deterministic_sorted_keys(sample_card: ProofCard):
    json_1 = serialize_proof_card(sample_card)
    json_2 = serialize_proof_card(sample_card)
    assert json_1 == json_2


def test_save_and_load_roundtrip(sample_card: ProofCard, tmp_path: Path):
    saved_path = save_proof_card(sample_card, output_dir=tmp_path)
    assert saved_path.exists()
    assert saved_path.suffix == ".json"

    loaded_card = load_proof_card(saved_path)
    assert loaded_card.proof_id == sample_card.proof_id
    assert loaded_card.question == sample_card.question
    assert loaded_card.status == sample_card.status
    assert loaded_card.hashes.canonical_proof_sha256 == sample_card.hashes.canonical_proof_sha256


def test_load_nonexistent_file_raises():
    with pytest.raises(FileNotFoundError):
        load_proof_card(Path("nonexistent_path_xyz.json"))


def test_load_malformed_json_raises(tmp_path: Path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{ this is not valid json }", encoding="utf-8")
    with pytest.raises(Exception):
        load_proof_card(bad_file)


def test_verify_integrity_untampered(sample_card: ProofCard):
    ok, msg = verify_proof_card_integrity(sample_card)
    assert ok is True
    assert "successfully verified" in msg


# Trap 10: Tampered proof payload detected
def test_verify_integrity_tampered_question(sample_card: ProofCard):
    sample_card.question = "Tampered question: what was profit?"
    ok, msg = verify_proof_card_integrity(sample_card)
    assert ok is False
    assert "Tampered payload" in msg


def test_verify_integrity_tampered_proof_id(sample_card: ProofCard):
    sample_card.proof_id = "proof_000000000000"
    ok, msg = verify_proof_card_integrity(sample_card)
    assert ok is False
    assert "Proof ID mismatch" in msg


def test_save_custom_file_path(sample_card: ProofCard, tmp_path: Path):
    custom_target = tmp_path / "custom_subdir" / "my_proof.json"
    result_path = save_proof_card(sample_card, file_path=custom_target)
    assert result_path == custom_target
    assert result_path.exists()
