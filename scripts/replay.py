"""
scripts.replay
--------------
Independent, offline proof replay utility for ProofLens.

CORE LAW (PROOFLENS_MASTER_CONTEXT.md §24):
    "Can another person or machine reproduce the exact same proof?"

Safety:
    - Never executes arbitrary unchecked shell or code.
    - Uses ProofLens SecureRunner and DualPathVerifier.
    - If source data files are missing or incomplete, reports INCOMPLETE (never false PASS).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import math
from pathlib import Path
import sys
from typing import Any

from app.agent.contracts import AnalysisPlan, PlanStatus
from app.execution.contracts import GeneratedCode
from app.execution.runner import SecureRunner
from app.ingestion.contracts import DataSourceRef
from app.ingestion.loader import load_file
from app.proof.contracts import ProofCard
from app.proof.serializer import load_proof_card, verify_proof_card_integrity
from app.repair.contracts import RepairWorld


@dataclass
class ReplayResult:
    """Outcome of a proof replay execution."""
    status: str  # "PASS" | "FAIL" | "INCOMPLETE"
    message: str
    proof_id: str
    details: dict[str, Any] = field(default_factory=dict)


def replay_proof(
    proof_source: Path | str | ProofCard,
    abs_tol: float = 1e-6,
    rel_tol: float = 1e-4,
) -> ReplayResult:
    """
    Rerun and validate a stored ProofCard.
    """
    # 1. Load ProofCard
    if isinstance(proof_source, ProofCard):
        card = proof_source
    else:
        path = Path(proof_source)
        if not path.exists():
            return ReplayResult(
                status="FAIL",
                message=f"Proof file does not exist: {path}",
                proof_id="unknown",
            )
        try:
            card = load_proof_card(path)
        except Exception as e:
            return ReplayResult(
                status="FAIL",
                message=f"Invalid ProofCard schema or malformed JSON: {e}",
                proof_id=path.stem,
            )

    proof_id = card.proof_id

    # 2. Cryptographic Payload Integrity Check
    is_valid, reason = verify_proof_card_integrity(card)
    if not is_valid:
        return ReplayResult(
            status="FAIL",
            message=f"Cryptographic payload tampering detected: {reason}",
            proof_id=proof_id,
            details={"integrity_error": reason},
        )

    # 3. Check Analysis Code
    code_str = None
    stored_code_hash = card.hashes.analysis_code_sha256 if card.hashes else None
    if card.execution_summary and "stdout" in card.execution_summary and card.analysis_code_path:
        p = Path(card.analysis_code_path)
        if p.exists():
            try:
                code_str = p.read_text(encoding="utf-8")
            except Exception:
                pass

    if not code_str and card.execution_summary and card.execution_summary.get("code"):
        code_str = card.execution_summary.get("code")

    # If code is present, verify its SHA-256 matches stored hash
    if code_str and stored_code_hash:
        recomputed_code_hash = hashlib.sha256(code_str.encode("utf-8")).hexdigest()
        if recomputed_code_hash != stored_code_hash:
            return ReplayResult(
                status="FAIL",
                message=(
                    f"Code hash mismatch: code SHA-256 {recomputed_code_hash[:16]}... "
                    f"does not match stored hash {stored_code_hash[:16]}..."
                ),
                proof_id=proof_id,
                details={"stored_code_hash": stored_code_hash, "recomputed": recomputed_code_hash},
            )

    # 4. Check Dataset Availability
    dataset_hashes = card.hashes.dataset_sha256 if card.hashes else {}
    if not dataset_hashes and not (card.lineage and card.lineage.source_files):
        return ReplayResult(
            status="INCOMPLETE",
            message="No dataset references or input hashes available in proof card.",
            proof_id=proof_id,
        )

    # Check whether referenced source data files actually exist on disk
    loaded_tables = []
    source_files_found = 0
    candidate_files = []
    if card.lineage and card.lineage.source_files:
        candidate_files.extend(card.lineage.source_files)

    for sf in candidate_files:
        p = Path(sf)
        if p.exists():
            try:
                tbls = load_file(DataSourceRef(path=p))
                loaded_tables.extend(tbls)
                source_files_found += 1
            except Exception:
                pass

    if source_files_found == 0 or not loaded_tables:
        return ReplayResult(
            status="INCOMPLETE",
            message="Source data files unavailable on disk for physical execution replay.",
            proof_id=proof_id,
            details={"searched_files": candidate_files},
        )

    # Verify input dataset hashes
    for lt in loaded_tables:
        csv_bytes = lt.dataframe.to_csv(index=False).encode("utf-8")
        current_hash = hashlib.sha256(csv_bytes).hexdigest()
        if lt.table_name in dataset_hashes:
            stored_hash = dataset_hashes[lt.table_name]
            if current_hash != stored_hash:
                return ReplayResult(
                    status="FAIL",
                    message=(
                        f"Dataset hash mismatch for table '{lt.table_name}': "
                        f"current {current_hash[:16]}... vs stored {stored_hash[:16]}..."
                    ),
                    proof_id=proof_id,
                    details={"table": lt.table_name, "stored": stored_hash, "current": current_hash},
                )

    # 5. Rerun Execution Safely
    if not code_str:
        return ReplayResult(
            status="INCOMPLETE",
            message="Analysis source code unavailable to execute replay.",
            proof_id=proof_id,
        )

    if card.repair_worlds:
        base_world = card.repair_worlds[0]
        world = RepairWorld(
            world_id=base_world.world_id,
            description=base_world.description,
            policies=base_world.policies,
            repaired_tables=loaded_tables,
        )
    else:
        world = RepairWorld(
            world_id="replay_world",
            description="Replay world",
            policies=[],
            repaired_tables=loaded_tables,
        )
    plan = card.analysis_plan or AnalysisPlan(question=card.question, status=PlanStatus.READY)
    code_hash_val = stored_code_hash or hashlib.sha256(code_str.encode("utf-8")).hexdigest()
    code_path_val = Path(card.analysis_code_path) if card.analysis_code_path else Path("proofs/replay_analysis.py")
    code_obj = GeneratedCode(
        code_path=code_path_val,
        code_content=code_str,
        code_sha256=code_hash_val,
        world_id=world.world_id,
    )
    runner = SecureRunner()
    exec_res = runner.run(world=world, plan=plan, code=code_obj)

    if not exec_res.execution_success:
        return ReplayResult(
            status="FAIL",
            message=f"Replay execution failed: {exec_res.execution_error or exec_res.stderr}",
            proof_id=proof_id,
            details={"stderr": exec_res.stderr},
        )

    replayed_val = exec_res.result_value
    stored_val = card.result

    # 6. Compare Replayed Value with Stored Proof Value
    if stored_val is None:
        if replayed_val is None:
            return ReplayResult(status="PASS", message="Replay verified: both results are None.", proof_id=proof_id)
        else:
            return ReplayResult(status="FAIL", message=f"Replayed {replayed_val} vs stored None", proof_id=proof_id)

    # Numerical comparison
    if isinstance(stored_val, (int, float)) and isinstance(replayed_val, (int, float)):
        if math.isclose(float(replayed_val), float(stored_val), abs_tol=abs_tol, rel_tol=rel_tol):
            return ReplayResult(
                status="PASS",
                message=f"Replay verified: replayed {replayed_val} matches stored {stored_val}.",
                proof_id=proof_id,
                details={"replayed": replayed_val, "stored": stored_val},
            )
        else:
            return ReplayResult(
                status="FAIL",
                message=f"Numerical mismatch: replayed {replayed_val} != stored {stored_val}",
                proof_id=proof_id,
                details={"replayed": replayed_val, "stored": stored_val},
            )

    # String comparison
    if str(replayed_val).strip() == str(stored_val).strip():
        return ReplayResult(
            status="PASS",
            message=f"Replay verified: {replayed_val} matches stored {stored_val}.",
            proof_id=proof_id,
        )

    return ReplayResult(
        status="FAIL",
        message=f"Result mismatch: replayed {replayed_val} != stored {stored_val}",
        proof_id=proof_id,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="ProofLens Proof Replay Utility")
    parser.add_argument("proof_file", help="Path to proof JSON artifact (e.g. proofs/proof_001.json)")
    args = parser.parse_args()

    result = replay_proof(args.proof_file)
    print(f"[{result.status}] {result.proof_id}: {result.message}")
    if result.status == "PASS":
        sys.exit(0)
    elif result.status == "FAIL":
        sys.exit(1)
    else:  # INCOMPLETE
        sys.exit(2)


if __name__ == "__main__":
    main()
