"""
tests/test_contracts.py
-----------------------
Tests that every Pydantic contract can be instantiated with valid data
and serialised to JSON without errors.

Scope:
  - Instantiation of every contract model with minimal valid data.
  - JSON round-trip serialisation (model → JSON → model).
  - Enum value correctness.
  - Required field enforcement (missing required field → ValidationError).

NOT tested here:
  - Business logic (not yet implemented).
  - Qwen API calls (not implemented).
  - Actual data loading or computation (not implemented).
  - Verification logic (not implemented).
  - Claim matching (not implemented).

Run with:
  .venv\\Scripts\\pytest tests/test_contracts.py -v
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

# ── Ingestion ─────────────────────────────────────────────────────────────────
from app.ingestion.contracts import (
    AnalysisRequest,
    DataSourceRef,
    DocumentRef,
    FileType,
    IngestionError,
    LoadedTable,
)

# ── Agent ─────────────────────────────────────────────────────────────────────
from app.agent.contracts import (
    AggregationSpec,
    AmbiguityFlag,
    AnalysisPlan,
    ColumnRef,
    FilterSpec,
    PlanStatus,
    UnanswerableReason,
)

# ── Audit ─────────────────────────────────────────────────────────────────────
from app.audit.contracts import (
    DataIssue,
    DataQualityLedger,
    IssueType,
    IssueSeverity,
    TableProfile,
)

# ── Repair ────────────────────────────────────────────────────────────────────
from app.repair.contracts import (
    CurrencyAction,
    DateFormatAction,
    DuplicateAction,
    MissingValueAction,
    RepairPolicy,
    RepairWorld,
)

# ── Execution ─────────────────────────────────────────────────────────────────
from app.execution.contracts import ExecutionResult, GeneratedCode

# ── Verification ─────────────────────────────────────────────────────────────
from app.verification.contracts import (
    CheckOutcome,
    ImpactAnalysis,
    VerificationCheck,
    VerificationCheckName,
    VerificationResult,
)

# ── Skeptic ───────────────────────────────────────────────────────────────────
from app.skeptic.contracts import SkepticConcern, SkepticConcernType, SkepticReview

# ── Truth ─────────────────────────────────────────────────────────────────────
from app.truth.contracts import (
    Claim,
    ClaimType,
    EvidenceRef,
    TruthGateResult,
    TruthStatus,
)

# ── Proof ─────────────────────────────────────────────────────────────────────
from app.proof.contracts import Lineage, ProofCard, ProofHashes


# =============================================================================
# Ingestion contracts
# =============================================================================

class TestIngestionContracts:
    def test_data_source_ref_minimal(self):
        ref = DataSourceRef(path=Path("data/original/orders.csv"))
        assert ref.path == Path("data/original/orders.csv")
        assert ref.alias is None

    def test_data_source_ref_with_alias(self):
        ref = DataSourceRef(path=Path("orders.csv"), alias="orders")
        assert ref.alias == "orders"

    def test_document_ref(self):
        doc = DocumentRef(
            path=Path("docs/data_dictionary.pdf"),
            description="Data dictionary",
        )
        assert doc.path == Path("docs/data_dictionary.pdf")

    def test_analysis_request_minimal(self):
        req = AnalysisRequest(
            question="What was total revenue in 2025?",
            data_sources=[DataSourceRef(path=Path("orders.csv"))],
        )
        assert req.question == "What was total revenue in 2025?"
        assert len(req.data_sources) == 1
        assert req.supporting_documents == []

    def test_analysis_request_with_document(self):
        req = AnalysisRequest(
            question="What was profit?",
            data_sources=[DataSourceRef(path=Path("orders.csv"))],
            supporting_documents=[DocumentRef(path=Path("rules.pdf"))],
        )
        assert len(req.supporting_documents) == 1

    def test_analysis_request_requires_question(self):
        with pytest.raises(ValidationError):
            AnalysisRequest(
                question="",            # min_length=1 violated
                data_sources=[DataSourceRef(path=Path("orders.csv"))],
            )

    def test_analysis_request_requires_data_sources(self):
        with pytest.raises(ValidationError):
            AnalysisRequest(
                question="What was revenue?",
                data_sources=[],        # min_length=1 violated
            )

    def test_analysis_request_json_roundtrip(self):
        req = AnalysisRequest(
            question="What was revenue?",
            data_sources=[DataSourceRef(path=Path("orders.csv"), alias="orders")],
            session_id="sess_001",
        )
        json_str = req.model_dump_json()
        restored = AnalysisRequest.model_validate_json(json_str)
        assert restored.question == req.question
        assert restored.session_id == req.session_id

    def test_file_type_enum_values(self):
        assert FileType.CSV == "CSV"
        assert FileType.XLSX == "XLSX"
        assert FileType.JSON == "JSON"

    def test_ingestion_error(self):
        err = IngestionError("Test failure", path=Path("data/test.csv"), reason="READ_ERROR")
        assert err.reason == "READ_ERROR"
        assert err.path == Path("data/test.csv")
        assert "Test failure" in str(err)

    def test_loaded_table_instantiation_and_records(self):
        df = pd.DataFrame({"a": ["1", "2"], "b": ["x", "y"]})
        table = LoadedTable(
            source_path=Path("data/test.csv"),
            file_type=FileType.CSV,
            table_name="test",
            sheet_name=None,
            column_names=["a", "b"],
            row_count=2,
            dataframe=df,
        )
        assert table.table_name == "test"
        assert table.row_count == 2
        assert table.column_names == ["a", "b"]
        records = table.to_records()
        assert records == [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}]


# =============================================================================
# Agent contracts
# =============================================================================

class TestAgentContracts:
    def test_column_ref(self):
        col = ColumnRef(table="orders", column="revenue")
        assert col.table == "orders"
        assert col.column == "revenue"

    def test_filter_spec(self):
        f = FilterSpec(
            column=ColumnRef(table="orders", column="year"),
            operator="==",
            value=2025,
        )
        assert f.value == 2025

    def test_aggregation_spec(self):
        agg = AggregationSpec(
            column=ColumnRef(table="orders", column="revenue"),
            operation="sum",
            unit="INR",
        )
        assert agg.operation == "sum"

    def test_ambiguity_flag(self):
        flag = AmbiguityFlag(
            description="Date format is ambiguous",
            affected_columns=[ColumnRef(table="orders", column="date")],
            example="01/02/2024 — DD/MM or MM/DD?",
        )
        assert "DD/MM" in flag.example

    def test_plan_status_enum_values(self):
        assert PlanStatus.READY == "READY"
        assert PlanStatus.UNANSWERABLE == "UNANSWERABLE"
        assert PlanStatus.NEEDS_CLARIFICATION == "NEEDS_CLARIFICATION"

    def test_analysis_plan_ready(self):
        plan = AnalysisPlan(
            question="What was total revenue in 2025?",
            status=PlanStatus.READY,
            required_tables=["orders"],
            required_columns=[ColumnRef(table="orders", column="revenue")],
            aggregation=AggregationSpec(
                column=ColumnRef(table="orders", column="revenue"),
                operation="sum",
                unit="INR",
            ),
        )
        assert plan.status == PlanStatus.READY
        assert plan.unanswerable_reason is None

    def test_analysis_plan_unanswerable(self):
        plan = AnalysisPlan(
            question="What was profit margin?",
            status=PlanStatus.UNANSWERABLE,
            unanswerable_reason=UnanswerableReason.MISSING_REQUIRED_FIELD,
            unanswerable_evidence="No profit or cost field is available.",
        )
        assert plan.status == PlanStatus.UNANSWERABLE
        assert plan.unanswerable_reason == UnanswerableReason.MISSING_REQUIRED_FIELD

    def test_analysis_plan_json_roundtrip(self):
        plan = AnalysisPlan(
            question="Revenue?",
            status=PlanStatus.READY,
            required_tables=["orders"],
        )
        restored = AnalysisPlan.model_validate_json(plan.model_dump_json())
        assert restored.question == plan.question


# =============================================================================
# Audit contracts
# =============================================================================

class TestAuditContracts:
    def test_issue_type_and_severity_enums(self):
        assert IssueType.DUPLICATE_ROWS == "DUPLICATE_ROWS"
        assert IssueSeverity.CRITICAL == "CRITICAL"
        assert IssueSeverity.INFO == "INFO"

    def test_data_issue_minimal(self):
        issue = DataIssue(
            issue_type=IssueType.DUPLICATE_ROWS,
            severity=IssueSeverity.HIGH,
            affected_source="orders.csv",
            description="14 duplicate order IDs found.",
            evidence={"duplicate_count": 14},
        )
        assert issue.evidence["duplicate_count"] == 14

    def test_data_issue_immutable(self):
        issue = DataIssue(
            issue_type=IssueType.MISSING_VALUES,
            severity=IssueSeverity.MEDIUM,
            affected_source="orders.csv",
            description="12 rows missing revenue.",
            evidence={"missing_count": 12},
        )
        with pytest.raises(Exception):
            issue.affected_source = "other.csv"   # frozen model

    def test_table_profile(self):
        profile = TableProfile(
            source="orders.csv",
            row_count=10000,
            column_count=8,
            column_names=["order_id", "date", "revenue", "currency"],
        )
        assert profile.row_count == 10000
        assert profile.issues == []

    def test_data_quality_ledger(self):
        issue = DataIssue(
            issue_type=IssueType.MIXED_CURRENCIES,
            severity=IssueSeverity.CRITICAL,
            affected_source="orders.csv",
            description="Both INR and USD found in currency column.",
            evidence={"currencies_found": ["INR", "USD"]},
        )
        profile = TableProfile(
            source="orders.csv",
            row_count=10000,
            column_count=5,
            column_names=["order_id", "revenue", "currency"],
            issues=[issue],
        )
        ledger = DataQualityLedger(
            session_id="sess_001",
            table_profiles=[profile],
            all_issues=[issue],
            has_critical_issues=True,
        )
        assert ledger.has_critical_issues is True
        assert len(ledger.all_issues) == 1

    def test_data_quality_ledger_json_roundtrip(self):
        ledger = DataQualityLedger(session_id="test")
        restored = DataQualityLedger.model_validate_json(ledger.model_dump_json())
        assert restored.session_id == "test"


# =============================================================================
# Repair contracts
# =============================================================================

class TestRepairContracts:
    def test_action_enums(self):
        assert DuplicateAction.KEEP_ALL == "KEEP_ALL"
        assert MissingValueAction.DROP_ROWS == "DROP_ROWS"
        assert DateFormatAction.DD_MM_YYYY == "DD_MM_YYYY"
        assert CurrencyAction.ASSUME_SINGLE_CURRENCY == "ASSUME_SINGLE_CURRENCY"

    def test_repair_policy(self):
        policy = RepairPolicy(
            issue_type=IssueType.DUPLICATE_ROWS,
            selected_action=DuplicateAction.DROP_EXACT_DUPLICATES,
            affected_sources=["orders.csv"],
            rationale="Remove exact duplicate rows; keep first occurrence.",
        )
        assert policy.selected_action == "DROP_EXACT_DUPLICATES"

    def test_repair_world_minimal(self):
        policy = RepairPolicy(
            issue_type=IssueType.DUPLICATE_ROWS,
            selected_action=DuplicateAction.KEEP_ALL,
            affected_sources=["orders.csv"],
            rationale="World A — keep all rows including duplicates.",
        )
        world = RepairWorld(
            world_id="world_A",
            description="Keep all duplicates; drop null rows; DD/MM/YYYY dates.",
            policies=[policy],
            source_file_refs=["data/original/orders.csv"],
        )
        assert world.world_id == "world_A"
        assert world.world_data_path is None  # not yet written

    def test_repair_world_empty_policies(self):
        """A world with no policies means 'use original data unmodified'."""
        world = RepairWorld(
            world_id="world_original",
            description="Original data, no repairs applied.",
            policies=[],
        )
        assert world.policies == []

    def test_repair_world_json_roundtrip(self):
        world = RepairWorld(
            world_id="world_B",
            description="Drop exact duplicates.",
            policies=[
                RepairPolicy(
                    issue_type=IssueType.DUPLICATE_ROWS,
                    selected_action=DuplicateAction.DROP_EXACT_DUPLICATES,
                    affected_sources=["orders.csv"],
                    rationale="Remove exact duplicates.",
                )
            ],
        )
        restored = RepairWorld.model_validate_json(world.model_dump_json())
        assert restored.world_id == "world_B"


# =============================================================================
# Execution contracts
# =============================================================================

class TestExecutionContracts:
    def test_generated_code(self):
        gc = GeneratedCode(
            code_path=Path("proofs/sess_001/analysis.py"),
            world_id="world_A",
            code_sha256="abc123",
        )
        assert gc.world_id == "world_A"

    def test_execution_result_success(self):
        result = ExecutionResult(
            world_id="world_A",
            code_path=Path("proofs/sess_001/analysis.py"),
            stdout="184200000\n",
            stderr="",
            exit_code=0,
            execution_success=True,
            result_value=184200000,
            duration_seconds=1.2,
        )
        assert result.execution_success is True
        assert result.result_value == 184200000

    def test_execution_result_failure(self):
        result = ExecutionResult(
            world_id="world_A",
            code_path=Path("proofs/sess_001/analysis.py"),
            stdout="",
            stderr="AssertionError: 'revenue' not in df.columns",
            exit_code=1,
            execution_success=False,
            result_value=None,
            execution_error="Assertion failed: required column missing.",
        )
        assert result.execution_success is False
        assert result.result_value is None

    def test_execution_result_json_roundtrip(self):
        result = ExecutionResult(
            world_id="world_B",
            code_path=Path("proofs/sess_001/analysis.py"),
            stdout="999",
            stderr="",
            exit_code=0,
            execution_success=True,
            result_value=999,
        )
        restored = ExecutionResult.model_validate_json(result.model_dump_json())
        assert restored.result_value == 999


# =============================================================================
# Verification contracts
# =============================================================================

class TestVerificationContracts:
    def test_check_outcome_enum(self):
        assert CheckOutcome.PASS == "PASS"
        assert CheckOutcome.FAIL == "FAIL"
        assert CheckOutcome.SKIPPED == "SKIPPED"

    def test_verification_check(self):
        check = VerificationCheck(
            check=VerificationCheckName.MATCH_CHECK,
            outcome=CheckOutcome.PASS,
            expected="184200000",
            actual="184200000",
        )
        assert check.outcome == CheckOutcome.PASS

    def test_impact_analysis(self):
        impact = ImpactAnalysis(
            world_results={"world_A": 18610000, "world_B": 18420000, "world_C": 17910000},
            minimum=17910000,
            maximum=18610000,
            spread=700000,
            value_stable=False,
            decision_stable=True,
        )
        assert impact.spread == 700000
        assert impact.decision_stable is True

    def test_verification_result_passed(self):
        vr = VerificationResult(
            world_id="world_B",
            pandas_result=184200000,
            duckdb_result=184200000,
            results_match=True,
            verification_passed=True,
            checks=[
                VerificationCheck(
                    check=VerificationCheckName.PANDAS_PRIMARY,
                    outcome=CheckOutcome.PASS,
                    actual="184200000",
                ),
                VerificationCheck(
                    check=VerificationCheckName.DUCKDB_SECONDARY,
                    outcome=CheckOutcome.PASS,
                    actual="184200000",
                ),
                VerificationCheck(
                    check=VerificationCheckName.MATCH_CHECK,
                    outcome=CheckOutcome.PASS,
                    expected="184200000",
                    actual="184200000",
                ),
            ],
        )
        assert vr.verification_passed is True
        assert vr.failures == []

    def test_verification_result_failed(self):
        vr = VerificationResult(
            world_id="world_A",
            pandas_result=184200000,
            duckdb_result=191000000,
            results_match=False,
            verification_passed=False,
            failures=["MATCH_CHECK failed: Pandas=184200000, DuckDB=191000000"],
        )
        assert vr.verification_passed is False
        assert len(vr.failures) == 1

    def test_verification_result_json_roundtrip(self):
        vr = VerificationResult(
            world_id="world_A",
            verification_passed=False,
            results_match=False,
        )
        restored = VerificationResult.model_validate_json(vr.model_dump_json())
        assert restored.world_id == "world_A"


# =============================================================================
# Skeptic contracts
# =============================================================================

class TestSkepticContracts:
    def test_skeptic_concern_type_enum(self):
        assert SkepticConcernType.EXPLANATION_MISMATCH == "EXPLANATION_MISMATCH"
        assert SkepticConcernType.FALSE_PREMISE == "FALSE_PREMISE"

    def test_skeptic_concern(self):
        concern = SkepticConcern(
            concern_type=SkepticConcernType.CURRENCY_MISMATCH,
            description="Draft explanation mentions USD but analysis used INR.",
            location="draft_answer",
            severity="blocking",
        )
        assert concern.severity == "blocking"

    def test_skeptic_review_no_concerns(self):
        review = SkepticReview(
            concerns=[],
            has_blocking_concerns=False,
        )
        assert review.has_blocking_concerns is False

    def test_skeptic_review_with_blocking_concern(self):
        review = SkepticReview(
            concerns=[
                SkepticConcern(
                    concern_type=SkepticConcernType.EXPLANATION_MISMATCH,
                    description="LLM text says ₹18.42 Cr but execution output was ₹18.21 Cr.",
                    location="draft_answer",
                    severity="blocking",
                )
            ],
            has_blocking_concerns=True,
        )
        assert review.has_blocking_concerns is True
        assert len(review.concerns) == 1

    def test_skeptic_review_json_roundtrip(self):
        review = SkepticReview(concerns=[], has_blocking_concerns=False)
        restored = SkepticReview.model_validate_json(review.model_dump_json())
        assert restored.has_blocking_concerns is False


# =============================================================================
# Truth contracts
# =============================================================================

class TestTruthContracts:
    def test_truth_status_all_six_values(self):
        """Verify all six required statuses exist and match the spec exactly."""
        assert TruthStatus.VERIFIED == "VERIFIED"
        assert TruthStatus.VERIFIED_WITH_ASSUMPTION == "VERIFIED_WITH_ASSUMPTION"
        assert TruthStatus.AMBIGUOUS == "AMBIGUOUS"
        assert TruthStatus.CONTRADICTED == "CONTRADICTED"
        assert TruthStatus.NOT_VERIFIED == "NOT_VERIFIED"
        assert TruthStatus.UNANSWERABLE == "UNANSWERABLE"

    def test_claim_type_enum(self):
        assert ClaimType.NUMERICAL_VALUE == "NUMERICAL_VALUE"
        assert ClaimType.COMPARISON == "COMPARISON"

    def test_evidence_ref(self):
        ref = EvidenceRef(
            evidence_type="execution_stdout",
            reference="world_A execution stdout line 1",
            value="184200000",
        )
        assert ref.value == "184200000"

    def test_claim_supported(self):
        claim = Claim(
            claim_text="Revenue was ₹18.42 Cr.",
            claim_type=ClaimType.NUMERICAL_VALUE,
            numerical_value=184200000,
            unit="INR",
            evidence_refs=[
                EvidenceRef(
                    evidence_type="execution_stdout",
                    reference="world_B stdout",
                    value="184200000",
                )
            ],
            supported=True,
        )
        assert claim.supported is True
        assert claim.numerical_value == 184200000

    def test_claim_unsupported(self):
        claim = Claim(
            claim_text="Revenue grew by 30%.",
            claim_type=ClaimType.PERCENTAGE,
            numerical_value=30.0,
            unit="%",
            evidence_refs=[],   # no evidence
            supported=False,
        )
        assert claim.supported is False

    def test_truth_gate_result_blocked(self):
        unsupported = Claim(
            claim_text="Revenue grew by 30%.",
            claim_type=ClaimType.PERCENTAGE,
            evidence_refs=[],
            supported=False,
        )
        gate = TruthGateResult(
            claims=[unsupported],
            unsupported_claims=[unsupported],
            answer_blocked=True,
        )
        assert gate.answer_blocked is True

    def test_truth_gate_result_clear(self):
        supported = Claim(
            claim_text="Revenue was 184200000 INR.",
            claim_type=ClaimType.NUMERICAL_VALUE,
            numerical_value=184200000,
            evidence_refs=[
                EvidenceRef(
                    evidence_type="execution_stdout",
                    reference="world_B stdout",
                    value="184200000",
                )
            ],
            supported=True,
        )
        gate = TruthGateResult(
            claims=[supported],
            unsupported_claims=[],
            answer_blocked=False,
        )
        assert gate.answer_blocked is False

    def test_truth_gate_json_roundtrip(self):
        gate = TruthGateResult(
            claims=[],
            unsupported_claims=[],
            answer_blocked=False,
        )
        restored = TruthGateResult.model_validate_json(gate.model_dump_json())
        assert restored.answer_blocked is False


# =============================================================================
# Proof contracts
# =============================================================================

class TestProofContracts:
    def test_lineage(self):
        lineage = Lineage(
            source_files=["data/original/orders.csv"],
            tables_used=["orders"],
            columns_used=["revenue", "date"],
            filters_applied=["year == 2025"],
        )
        assert "revenue" in lineage.columns_used

    def test_proof_hashes(self):
        hashes = ProofHashes(
            dataset_sha256={"world_A": "abc123", "world_B": "def456"},
            analysis_code_sha256="ghi789",
            policy_sha256="jkl012",
        )
        assert hashes.dataset_sha256["world_A"] == "abc123"

    def test_proof_card_minimal_unanswerable(self):
        """
        A ProofCard for an unanswerable question has no result
        but must still carry a status and refusal reason.
        """
        card = ProofCard(
            proof_id="proof_001",
            question="What was profit margin?",
            result=None,
            status=TruthStatus.UNANSWERABLE,
            refusal_reason="No profit or cost field is available in the data.",
        )
        assert card.status == TruthStatus.UNANSWERABLE
        assert card.result is None

    def test_proof_card_verified(self):
        card = ProofCard(
            proof_id="proof_002",
            question="What was total revenue in 2025?",
            result=184200000,
            result_unit="INR",
            result_world_id="world_B",
            status=TruthStatus.VERIFIED_WITH_ASSUMPTION,
            assumptions=["Treating all dates as DD/MM/YYYY"],
            reproduction_command="python scripts/replay.py proofs/proof_002.json",
            analysis_code_path=Path("proofs/proof_002/analysis.py"),
        )
        assert card.status == TruthStatus.VERIFIED_WITH_ASSUMPTION
        assert card.result == 184200000
        assert card.reproduction_command is not None

    def test_proof_card_requires_proof_id(self):
        with pytest.raises(ValidationError):
            ProofCard(
                question="Revenue?",
                status=TruthStatus.UNANSWERABLE,
                # proof_id is missing
            )

    def test_proof_card_json_roundtrip(self):
        card = ProofCard(
            proof_id="proof_003",
            question="What was revenue?",
            status=TruthStatus.NOT_VERIFIED,
        )
        restored = ProofCard.model_validate_json(card.model_dump_json())
        assert restored.proof_id == "proof_003"
        assert restored.status == TruthStatus.NOT_VERIFIED

    def test_proof_card_with_full_verification(self):
        """Integration-style test: assemble a realistic proof card."""
        card = ProofCard(
            proof_id="proof_004",
            session_id="sess_001",
            question="What was total revenue in 2025?",
            result=184200000,
            result_unit="INR",
            result_world_id="world_B",
            status=TruthStatus.VERIFIED_WITH_ASSUMPTION,
            assumptions=["All dates parsed as DD/MM/YYYY"],
            data_quality_ledger=DataQualityLedger(session_id="sess_001"),
            repair_worlds=[
                RepairWorld(
                    world_id="world_B",
                    description="Drop exact duplicates.",
                    policies=[
                        RepairPolicy(
                            issue_type=IssueType.DUPLICATE_ROWS,
                            selected_action=DuplicateAction.DROP_EXACT_DUPLICATES,
                            affected_sources=["orders.csv"],
                            rationale="Remove exact duplicates.",
                        )
                    ],
                )
            ],
            impact_range={
                "minimum": 17910000,
                "maximum": 18610000,
                "spread": 700000,
                "value_stable": False,
                "decision_stable": True,
            },
            analysis_code_path=Path("proofs/proof_004/analysis.py"),
            verification_results=[
                VerificationResult(
                    world_id="world_B",
                    pandas_result=184200000,
                    duckdb_result=184200000,
                    results_match=True,
                    verification_passed=True,
                )
            ],
            lineage=Lineage(
                source_files=["data/original/orders.csv"],
                tables_used=["orders"],
                columns_used=["revenue", "date"],
                filters_applied=["year == 2025"],
                repair_policy_summary="Dropped 14 exact duplicate rows.",
            ),
            hashes=ProofHashes(
                dataset_sha256={"world_B": "deadbeef"},
                analysis_code_sha256="cafebabe",
            ),
            reproduction_command="python scripts/replay.py proofs/proof_004.json",
        )
        # Verify the full round-trip
        restored = ProofCard.model_validate_json(card.model_dump_json())
        assert restored.result == 184200000
        assert restored.status == TruthStatus.VERIFIED_WITH_ASSUMPTION
        assert len(restored.repair_worlds) == 1
        assert len(restored.verification_results) == 1
        assert restored.hashes.analysis_code_sha256 == "cafebabe"
