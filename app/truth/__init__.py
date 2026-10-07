# app.truth package
from app.truth.claim_extractor import ClaimExtractor, extract_claims, normalize_numeric_string
from app.truth.contracts import (
    Claim,
    ClaimType,
    EvidenceRef,
    TruthGateResult,
    TruthStatus,
)
from app.truth.evidence_matcher import ClaimEvidenceMatcher, match_claims_to_evidence
from app.truth.gate import TruthGate, evaluate_truth_gate

__all__ = [
    "Claim",
    "ClaimEvidenceMatcher",
    "ClaimExtractor",
    "ClaimType",
    "EvidenceRef",
    "TruthGate",
    "TruthGateResult",
    "TruthStatus",
    "evaluate_truth_gate",
    "extract_claims",
    "match_claims_to_evidence",
    "normalize_numeric_string",
]
