"""
tests.test_skeptic
------------------
Comprehensive unit test suite for deterministic SkepticAgent.
"""

from __future__ import annotations

import pytest

from app.agent.contracts import AnalysisPlan, PlanStatus, UnanswerableReason
from app.audit.contracts import IssueType
from app.repair.contracts import RepairPolicy, RepairWorld
from app.skeptic.agent import SkepticAgent, review_draft_answer
from app.skeptic.contracts import SkepticConcernType
from app.truth.contracts import Claim, ClaimType, TruthStatus
from app.verification.contracts import VerificationResult, VerificationStatus


@pytest.fixture
def skeptic() -> SkepticAgent:
    return SkepticAgent()


def test_skeptic_clean_draft_no_blocking_concerns(skeptic: SkepticAgent):
    claims = [
        Claim(
            claim_text="Total revenue was 1000.0.",
            claim_type=ClaimType.NUMERICAL_VALUE,
            numerical_value=1000.0,
            supported=True,
            status=TruthStatus.VERIFIED,
        )
    ]
    vr = VerificationResult(
        world_id="world_001",
        status=VerificationStatus.VERIFIED,
        verification_passed=True,
        provenance_verified=True,
    )
    rev = skeptic.review("Total revenue was 1000.0.", claims, verification_result=vr)
    assert rev.has_blocking_concerns is False
    assert len(rev.concerns) == 0


def test_skeptic_unsupported_claim_detected(skeptic: SkepticAgent):
    claims = [
        Claim(
            claim_text="Revenue grew by 50%.",
            claim_type=ClaimType.PERCENTAGE,
            numerical_value=50.0,
            supported=False,
            status=TruthStatus.NOT_VERIFIED,
            mismatch_reason="No evidence exists",
        )
    ]
    rev = skeptic.review("Revenue grew by 50%.", claims)
    assert rev.has_blocking_concerns is True
    assert any(c.concern_type == SkepticConcernType.UNSUPPORTED_CLAIM for c in rev.concerns)


def test_skeptic_explanation_mismatch_detected(skeptic: SkepticAgent):
    claims = [
        Claim(
            claim_text="Total revenue was 1200.0.",
            claim_type=ClaimType.NUMERICAL_VALUE,
            numerical_value=1200.0,
            supported=False,
            status=TruthStatus.CONTRADICTED,
            mismatch_reason="Contradicts verified value 1000.0",
        )
    ]
    rev = skeptic.review("Total revenue was 1200.0.", claims)
    assert rev.has_blocking_concerns is True
    assert any(c.concern_type == SkepticConcernType.EXPLANATION_MISMATCH for c in rev.concerns)


def test_skeptic_false_premise_unanswerable(skeptic: SkepticAgent):
    plan = AnalysisPlan(
        question="What was revenue increase?",
        status=PlanStatus.UNANSWERABLE,
        unanswerable_reason=UnanswerableReason.NO_DATA_SOURCES,
        unanswerable_evidence="No baseline period data found.",
    )
    rev = skeptic.review("Revenue increased by 10%.", [], plan=plan)
    assert rev.has_blocking_concerns is True
    assert any(c.concern_type == SkepticConcernType.FALSE_PREMISE for c in rev.concerns)


def test_skeptic_date_ambiguity_flagged(skeptic: SkepticAgent):
    plan = AnalysisPlan(
        question="Revenue on 01/02/2024",
        status=PlanStatus.AMBIGUOUS,
        unanswerable_reason=UnanswerableReason.AMBIGUOUS_DATE,
    )
    rev = skeptic.review("Revenue was 100.", [], plan=plan)
    assert rev.has_blocking_concerns is True
    assert any(c.concern_type == SkepticConcernType.DATE_AMBIGUITY for c in rev.concerns)


def test_skeptic_date_ambiguity_resolved_by_policy(skeptic: SkepticAgent):
    plan = AnalysisPlan(
        question="Revenue on 01/02/2024",
        status=PlanStatus.AMBIGUOUS,
        unanswerable_reason=UnanswerableReason.AMBIGUOUS_DATE,
    )
    world = RepairWorld(
        world_id="w1",
        description="Resolved dates",
        policies=[
            RepairPolicy(
                issue_type=IssueType.AMBIGUOUS_DATE_FORMAT,
                selected_action="DD_MM_YYYY",
                rationale="Resolved as day-first",
            )
        ],
    )
    claims = [
        Claim(claim_text="Revenue was 100.", claim_type=ClaimType.NUMERICAL_VALUE, numerical_value=100.0, supported=True)
    ]
    vr = VerificationResult(world_id="w1", status=VerificationStatus.VERIFIED_WITH_ASSUMPTION, verification_passed=True, provenance_verified=True)
    rev = skeptic.review("Revenue was 100.", claims, plan=plan, world=world, verification_result=vr)
    assert not any(c.concern_type == SkepticConcernType.DATE_AMBIGUITY for c in rev.concerns)


def test_skeptic_verification_contradiction(skeptic: SkepticAgent):
    vr = VerificationResult(
        world_id="w1",
        status=VerificationStatus.FAILED,
        verification_passed=False,
        results_match=False,
        failures=["Pandas=1000, DuckDB=1200"],
    )
    rev = skeptic.review("Revenue was 1000.", [], verification_result=vr)
    assert rev.has_blocking_concerns is True
    assert any(c.concern_type == SkepticConcernType.CONTRADICTION for c in rev.concerns)


def test_skeptic_provenance_failure(skeptic: SkepticAgent):
    vr = VerificationResult(
        world_id="w1",
        status=VerificationStatus.NOT_VERIFIED,
        verification_passed=False,
        provenance_verified=False,
        failures=["Provenance failure: table hash mismatch"],
    )
    rev = skeptic.review("Revenue was 1000.", [], verification_result=vr)
    assert rev.has_blocking_concerns is True
    assert any(c.concern_type == SkepticConcernType.PROVENANCE_MISMATCH for c in rev.concerns)


def test_skeptic_unit_mismatch(skeptic: SkepticAgent):
    claims = [
        Claim(
            claim_text="Price was $100.",
            claim_type=ClaimType.NUMERICAL_VALUE,
            numerical_value=100.0,
            supported=False,
            mismatch_reason="Unit mismatch: claim asserts USD but dataset is INR",
        )
    ]
    rev = skeptic.review("Price was $100.", claims)
    assert rev.has_blocking_concerns is True
    assert any(c.concern_type == SkepticConcernType.UNIT_MISMATCH for c in rev.concerns)


def test_skeptic_unsupported_precision(skeptic: SkepticAgent):
    claims = [
        Claim(
            claim_text="Total is 18.42881928.",
            claim_type=ClaimType.NUMERICAL_VALUE,
            numerical_value=18.42881928,
            supported=False,
            mismatch_reason="Unsupported precision: 8 decimal places",
        )
    ]
    rev = skeptic.review("Total is 18.42881928.", claims)
    assert rev.has_blocking_concerns is True
    assert any(c.concern_type == SkepticConcernType.UNSUPPORTED_PRECISION for c in rev.concerns)


def test_skeptic_convenience_function():
    rev = review_draft_answer("Draft answer", [])
    assert rev is not None
