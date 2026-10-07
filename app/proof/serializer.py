"""
app.proof.serializer
--------------------
Deterministic JSON serializer and persistence layer for ProofCard artifacts.

CORE PRINCIPLE (PROOFLENS_MASTER_CONTEXT.md §20, §23):
    Proof files are authoritative evidence artifacts.
    They must be:
      - Valid UTF-8 JSON
      - Deterministic and schema-consistent
      - Machine-readable and human-inspectable
      - Tamper-evident via SHA-256 canonical hashing
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.proof.builder import compute_canonical_proof_payload
from app.proof.contracts import ProofCard


def serialize_proof_card(proof_card: ProofCard, indent: int = 2) -> str:
    """
    Serialize a ProofCard into a deterministic, formatted JSON string.
    Ensures UTF-8 encoding and sorted keys for maximum reproducibility.
    """
    # Use Pydantic's model_dump to get a clean Python dict, then json.dumps for strict key sorting
    card_dict = proof_card.model_dump(mode="json")
    return json.dumps(card_dict, indent=indent, sort_keys=True, ensure_ascii=False)


def save_proof_card(
    proof_card: ProofCard,
    output_dir: Path | str | None = None,
    file_path: Path | str | None = None,
) -> Path:
    """
    Serialize and save a ProofCard to disk as a JSON artifact.
    Default path: proofs/<proof_id>.json
    """
    if file_path is not None:
        target = Path(file_path)
    else:
        out_directory = Path(output_dir) if output_dir else Path("proofs")
        target = out_directory / f"{proof_card.proof_id}.json"

    target.parent.mkdir(parents=True, exist_ok=True)
    content = serialize_proof_card(proof_card)
    target.write_text(content, encoding="utf-8")
    return target


def load_proof_card(file_path: Path | str) -> ProofCard:
    """
    Load and validate a ProofCard JSON artifact from disk.
    Raises ValueError on nonexistent file or invalid JSON schema.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Proof file not found: {path}")

    raw_json = path.read_text(encoding="utf-8")
    return ProofCard.model_validate_json(raw_json)


def verify_proof_card_integrity(proof_card: ProofCard) -> tuple[bool, str]:
    """
    Verify the cryptographic integrity of a ProofCard artifact.
    Reconstructs the canonical hash payload and compares it to stored canonical_proof_sha256.
    """
    if not proof_card.hashes or not proof_card.hashes.canonical_proof_sha256:
        return False, "ProofCard does not contain stored canonical_proof_sha256 hash."

    # Reconstruct canonical payload dictionary
    dataset_hashes = proof_card.hashes.dataset_sha256 or {}
    canonical_dict: dict[str, Any] = {
        "question": proof_card.question,
        "normalized_question": proof_card.normalized_question or " ".join(proof_card.question.split()),
        "status": proof_card.status.value,
        "result": proof_card.result,
        "result_unit": proof_card.result_unit,
        "answer_blocked": proof_card.answer_blocked,
        "deterministic_decision": proof_card.deterministic_decision,
        "blocking_reasons": sorted(proof_card.blocking_reasons),
        "assumptions": sorted(proof_card.assumptions),
        "code_hash": proof_card.hashes.analysis_code_sha256,
        "dataset_hashes": sorted(dataset_hashes.items()),
        "policy_hash": proof_card.hashes.policy_sha256,
        "world_id": proof_card.result_world_id,
        "verified_claims_count": len([c for c in proof_card.claims if c.supported]),
        "failed_claims_count": len([c for c in proof_card.claims if not c.supported]),
    }

    recomputed_hash, expected_proof_id = compute_canonical_proof_payload(canonical_dict)
    stored_hash = proof_card.hashes.canonical_proof_sha256

    if recomputed_hash != stored_hash:
        return False, (
            f"Cryptographic payload hash mismatch: recomputed {recomputed_hash[:16]}... "
            f"does not match stored {stored_hash[:16]}... (Tampered payload)."
        )

    if proof_card.proof_id != expected_proof_id:
        return False, (
            f"Proof ID mismatch: recomputed {expected_proof_id} "
            f"does not match stored proof_id {proof_card.proof_id}."
        )

    return True, "ProofCard integrity successfully verified."
