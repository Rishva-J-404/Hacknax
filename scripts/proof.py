"""
scripts.proof
-------------
Command-line interface and programmatic API for ProofLens Proof Cards.

Usage:
    python scripts/proof.py --help
    python scripts/proof.py inspect proofs/proof_a13f8c72d91e.json
    python scripts/proof.py verify proofs/proof_a13f8c72d91e.json
    python scripts/proof.py list
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Ensure repository root is on sys.path for direct CLI execution
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.proof.builder import build_proof_card
from app.proof.contracts import ProofCard
from app.proof.renderer import render_proof_card_text, save_proof_card_text
from app.proof.serializer import load_proof_card, save_proof_card
from scripts.replay import replay_proof


def inspect_proof(proof_path: Path | str) -> str:
    """Inspect and format a stored proof card."""
    card = load_proof_card(proof_path)
    return render_proof_card_text(card)


def verify_proof_file(proof_path: Path | str) -> bool:
    """Run proof replay and integrity check."""
    res = replay_proof(proof_path)
    print(f"[{res.status}] {res.proof_id}: {res.message}")
    return res.status == "PASS"


def list_proofs(proofs_dir: Path | str = "proofs") -> list[str]:
    """List all stored proof artifacts."""
    p_dir = Path(proofs_dir)
    if not p_dir.exists():
        return []
    return [str(p) for p in sorted(p_dir.glob("*.json"))]


def build_and_save(question: str, **kwargs) -> ProofCard:
    """Programmatic API to build and persist a proof card."""
    card = build_proof_card(question=question, **kwargs)
    save_proof_card(card)
    save_proof_card_text(card)
    return card


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ProofLens Proof Card CLI — Inspect, verify, and list proof artifacts."
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # inspect
    inspect_parser = subparsers.add_parser("inspect", help="Display human-readable text of a proof card")
    inspect_parser.add_argument("proof_file", help="Path to proof JSON file")

    # verify
    verify_parser = subparsers.add_parser("verify", help="Verify integrity and replay a proof card")
    verify_parser.add_argument("proof_file", help="Path to proof JSON file")

    # run
    run_parser = subparsers.add_parser("run", help="Execute end-to-end ProofLens analysis")
    run_parser.add_argument("--question", "-q", required=True, help="Analytical question to ask")
    run_parser.add_argument("--sources", "-s", nargs="+", required=True, help="Path to input data source file(s)")
    run_parser.add_argument("--output-dir", "-o", default="proofs", help="Output directory for proofs")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "run":
        from app.orchestrator import ProofLensOrchestrator
        orchestrator = ProofLensOrchestrator(proof_output_dir=args.output_dir)
        try:
            res = orchestrator.run(
                question=args.question,
                sources=args.sources,
                output_dir=args.output_dir,
            )
            print(f"Status: {res.status.value}")
            print(f"Proof ID: {res.proof_card.proof_id}")
            if res.answer_blocked:
                print("Decision: BLOCKED")
                print(f"Refusal: {res.answer}")
                sys.exit(1)
            else:
                print("Decision: PERMITTED")
                print(f"Result: {res.result}")
                print(f"Answer: {res.answer}")
                sys.exit(0)
        except Exception as e:
            print(f"Orchestrator error: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "inspect":
        try:
            text = inspect_proof(args.proof_file)
            print(text)
        except Exception as e:
            print(f"Error inspecting proof: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "verify":
        ok = verify_proof_file(args.proof_file)
        sys.exit(0 if ok else 1)

    elif args.command == "list":
        proofs = list_proofs()
        if not proofs:
            print("No proofs found in proofs/ directory.")
        else:
            print(f"Found {len(proofs)} proof(s):")
            for p in proofs:
                print(f"  * {p}")


if __name__ == "__main__":
    main()
