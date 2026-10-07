"""
tests.test_evidence_matcher
---------------------------
Comprehensive unit test suite for ClaimEvidenceMatcher.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from app.agent.contracts import AggregationSpec, AnalysisPlan, ColumnRef, PlanStatus
from app.execution.contracts import ExecutionResult
from app.repair.contracts import RepairWorld
from app.truth.contracts import Claim, ClaimType, TruthStatus
from app.truth.evidence_matcher import ClaimEvidenceMatcher, match_claims_to_evidence
from app.verification.contracts import VerificationResult, VerificationStatus


@pytest.fixture
def matcher() -> ClaimEvidenceMatcher:
    return ClaimEvidenceMatcher()


@pytest.fixture
def sample_vr() -> VerificationResult:
    return VerificationResult(
        world_id="world_001",
        status=VerificationStatus.VERIFIED,
        pandas_result=1000.0,
        duckdb_result=1000.0,
        primary_result=1000.0,
        independent_result=1000.0,
        results_match=True,
        verification_passed=True,
    )


@pytest.fixture
def sample_plan() -> AnalysisPlan:
    return AnalysisPlan(
        question="Total amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(
            column=ColumnRef(table="orders", column="amount"),
            operation="sum",
            unit="INR",
        ),
    )


def test_exact_numerical_match_supported(matcher: ClaimEvidenceMatcher, sample_vr: VerificationResult, sample_plan: AnalysisPlan):
    claim = Claim(
        claim_text="Total amount was 1000.0.",
        claim_type=ClaimType.NUMERICAL_VALUE,
        numerical_value=1000.0,
        unit="INR",
        supported=False,
    )
    res = matcher.match_claims([claim], verification_result=sample_vr, plan=sample_plan)
    assert len(res) == 1
    c = res[0]
    assert c.supported is True
    assert c.status == TruthStatus.VERIFIED
    assert len(c.evidence_refs) >= 2


def test_scaled_crore_match_supported(matcher: ClaimEvidenceMatcher, sample_plan: AnalysisPlan):
    vr = VerificationResult(
        world_id="world_001",
        status=VerificationStatus.VERIFIED,
        primary_result=184200000.0,
        duckdb_result=184200000.0,
        verification_passed=True,
    )
    claim = Claim(
        claim_text="Total revenue was ₹18.42 Cr.",
        claim_type=ClaimType.NUMERICAL_VALUE,
        numerical_value=18.42,
        normalized_value=184200000.0,
        unit="INR",
        supported=False,
    )
    res = matcher.match_claims([claim], verification_result=vr, plan=sample_plan)
    assert res[0].supported is True
    assert res[0].status == TruthStatus.VERIFIED


def test_numerical_mismatch_contradicted(matcher: ClaimEvidenceMatcher, sample_vr: VerificationResult, sample_plan: AnalysisPlan):
    claim = Claim(
        claim_text="Total amount was 1250.0.",
        claim_type=ClaimType.NUMERICAL_VALUE,
        numerical_value=1250.0,
        unit="INR",
        supported=False,
    )
    res = matcher.match_claims([claim], verification_result=sample_vr, plan=sample_plan)
    c = res[0]
    assert c.supported is False
    assert c.status == TruthStatus.CONTRADICTED
    assert "contradicts" in (c.mismatch_reason or "").lower()


def test_missing_verification_result_unsupported(matcher: ClaimEvidenceMatcher, sample_plan: AnalysisPlan):
    claim = Claim(
        claim_text="Total amount was 1000.0.",
        claim_type=ClaimType.NUMERICAL_VALUE,
        numerical_value=1000.0,
        supported=False,
    )
    res = matcher.match_claims([claim], verification_result=None, plan=sample_plan)
    assert res[0].supported is False
    assert res[0].status == TruthStatus.NOT_VERIFIED


def test_unverified_execution_unsupported(matcher: ClaimEvidenceMatcher, sample_plan: AnalysisPlan):
    vr_failed = VerificationResult(
        world_id="world_001",
        status=VerificationStatus.FAILED,
        primary_result=1000.0,
        duckdb_result=1200.0,
        verification_passed=False,
    )
    claim = Claim(
        claim_text="Total amount was 1000.0.",
        claim_type=ClaimType.NUMERICAL_VALUE,
        numerical_value=1000.0,
        supported=False,
    )
    res = matcher.match_claims([claim], verification_result=vr_failed, plan=sample_plan)
    assert res[0].supported is False
    assert res[0].status == TruthStatus.NOT_VERIFIED


def test_unit_mismatch_flagged(matcher: ClaimEvidenceMatcher, sample_vr: VerificationResult, sample_plan: AnalysisPlan):
    # Dataset expected INR, claim asserts USD
    claim = Claim(
        claim_text="Total amount was $1000.0.",
        claim_type=ClaimType.NUMERICAL_VALUE,
        numerical_value=1000.0,
        unit="USD",
        supported=False,
    )
    res = matcher.match_claims([claim], verification_result=sample_vr, plan=sample_plan)
    assert res[0].supported is False
    assert res[0].status == TruthStatus.NOT_VERIFIED
    assert "unit mismatch" in (res[0].mismatch_reason or "").lower()


def test_unsupported_precision_flagged(matcher: ClaimEvidenceMatcher, sample_plan: AnalysisPlan):
    vr = VerificationResult(
        world_id="world_001",
        status=VerificationStatus.VERIFIED,
        primary_result=18.42,
        duckdb_result=18.42,
        verification_passed=True,
    )
    claim = Claim(
        claim_text="Revenue was 18.423871928381.",
        claim_type=ClaimType.NUMERICAL_VALUE,
        numerical_value=18.423871928381,
        supported=False,
    )
    res = matcher.match_claims([claim], verification_result=vr, plan=sample_plan)
    assert res[0].supported is False
    assert res[0].status == TruthStatus.NOT_VERIFIED
    assert "unsupported precision" in (res[0].mismatch_reason or "").lower()


def test_tolerance_match_supported(matcher: ClaimEvidenceMatcher, sample_vr: VerificationResult, sample_plan: AnalysisPlan):
    claim = Claim(
        claim_text="Total amount was 1000.0000000000001.",
        claim_type=ClaimType.NUMERICAL_VALUE,
        numerical_value=1000.0000000000001,
        unit="INR",
        supported=False,
    )
    res = matcher.match_claims([claim], verification_result=sample_vr, plan=sample_plan)
    assert res[0].supported is True


def test_assumption_backed_match(matcher: ClaimEvidenceMatcher, sample_vr: VerificationResult, sample_plan: AnalysisPlan):
    world = RepairWorld(
        world_id="world_001",
        description="Assumed dates",
        policies=[],
        assumptions=["Interpreted dates as DD/MM/YYYY"],
    )
    claim = Claim(
        claim_text="Total amount was 1000.0.",
        claim_type=ClaimType.NUMERICAL_VALUE,
        numerical_value=1000.0,
        unit="INR",
        supported=False,
    )
    res = matcher.match_claims([claim], verification_result=sample_vr, plan=sample_plan, world=world)
    assert res[0].supported is True
    assert res[0].status == TruthStatus.VERIFIED_WITH_ASSUMPTION


def test_top_n_comparison_claim_match(matcher: ClaimEvidenceMatcher, sample_plan: AnalysisPlan):
    vr = VerificationResult(
        world_id="world_001",
        status=VerificationStatus.VERIFIED,
        primary_result="furniture",
        duckdb_result="furniture",
        verification_passed=True,
    )
    claim = Claim(
        claim_text="furniture category had the highest sales",
        claim_type=ClaimType.COMPARISON,
        numerical_value=None,
        supported=False,
    )
    res = matcher.match_claims([claim], verification_result=vr, plan=sample_plan)
    assert res[0].supported is True
    assert res[0].status == TruthStatus.VERIFIED


def test_unsupported_factual_claim(matcher: ClaimEvidenceMatcher, sample_vr: VerificationResult, sample_plan: AnalysisPlan):
    claim = Claim(
        claim_text="Data was verified by accounting team.",
        claim_type=ClaimType.FACTUAL_STATEMENT,
        numerical_value=None,
        supported=False,
    )
    res = matcher.match_claims([claim], verification_result=sample_vr, plan=sample_plan)
    assert res[0].supported is False
    assert res[0].status == TruthStatus.NOT_VERIFIED


def test_convenience_match_claims():
    claims = [Claim(claim_text="X", claim_type=ClaimType.COUNT, numerical_value=5, supported=False)]
    matched = match_claims_to_evidence(claims)
    assert len(matched) == 1
    assert matched[0].supported is False
