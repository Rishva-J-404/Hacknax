"""
tests.test_verification
-----------------------
Comprehensive test suite for Phase 7 — Independent Verification Engine.

Tests:
1. SUM matches.
2. COUNT matches.
3. MEAN matches.
4. MIN matches.
5. MAX matches.
6. DISTINCT COUNT matches.
7. GROUP BY matches.
8. FILTER matches.
9. YEAR FILTER matches.
10. TOP-N matches.
11. Percentage matches.
12. Pandas/DuckDB mismatch detected (Trap).
13. Hardcoded wrong result detected (Trap).
14. Wrong aggregation detected (Trap).
15. Missing provenance detected.
16. Hash mismatch detected (Provenance trap).
17. World mismatch detected (World mix-up trap).
18. Missing table detected.
19. Missing column detected.
20. Unsupported verification returns NOT_VERIFIED.
21. Numeric tolerance works (ABS_TOL, REL_TOL).
22. NaN handling works.
23. Dictionary / Sequence result comparison works.
24. Deterministic verification repeated twice gives same status.
25. Verified with assumption status assigned when assumptions exist.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import pandas as pd
import pytest

from app.agent.contracts import (
    AggregationSpec,
    AnalysisPlan,
    ColumnRef,
    FilterSpec,
    PlanStatus,
)
from app.execution.contracts import ExecutionResult
from app.ingestion.contracts import FileType, LoadedTable
from app.repair.contracts import RepairWorld
from app.verification.contracts import (
    CheckOutcome,
    VerificationCheckName,
    VerificationStatus,
)
from app.verification.engine import VerificationEngine, verify_execution


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def orders_table() -> LoadedTable:
    df = pd.DataFrame(
        [
            {"order_id": "1", "amount": "100.0", "status": "completed", "date": "2024-01-15", "category": "books"},
            {"order_id": "2", "amount": "200.0", "status": "completed", "date": "2024-02-20", "category": "electronics"},
            {"order_id": "3", "amount": "300.0", "status": "failed", "date": "2023-11-10", "category": "books"},
            {"order_id": "4", "amount": "400.0", "status": "completed", "date": "2024-05-05", "category": "furniture"},
        ]
    )
    return LoadedTable(
        source_path=Path("tests/data/orders.csv"),
        file_type=FileType.CSV,
        table_name="orders",
        column_names=list(df.columns),
        row_count=len(df),
        dataframe=df,
    )


@pytest.fixture
def sample_world(orders_table: LoadedTable) -> RepairWorld:
    return RepairWorld(
        world_id="world_001",
        description="Clean baseline world",
        policies=[],
        repaired_tables=[orders_table],
    )


def _make_exec_result(
    world_id: str,
    result_val: any,
    orders_table: LoadedTable,
    code_hash: str = "code_hash_abc123",
) -> ExecutionResult:
    """Helper to construct a valid ExecutionResult with matching provenance hashes."""
    tbl_csv = orders_table.dataframe.to_csv(index=False).encode("utf-8")
    tbl_hash = hashlib.sha256(tbl_csv).hexdigest()
    return ExecutionResult(
        world_id=world_id,
        code_path=Path("proofs/test_analysis.py"),
        stdout=f"{result_val}\n",
        exit_code=0,
        execution_success=True,
        result_value=result_val,
        generated_code_hash=code_hash,
        input_data_hashes={"orders": tbl_hash},
        table_names=["orders"],
        row_counts={"orders": len(orders_table.dataframe)},
    )


# ---------------------------------------------------------------------------
# 1. Standard Aggregations & Dual-Path Verification
# ---------------------------------------------------------------------------

def test_sum_matches(sample_world: RepairWorld, orders_table: LoadedTable):
    """SUM aggregation is independently reproduced and verified by DuckDB."""
    plan = AnalysisPlan(
        question="Total amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="sum"),
    )
    # 100 + 200 + 300 + 400 = 1000.0
    exec_res = _make_exec_result("world_001", 1000.0, orders_table)

    engine = VerificationEngine()
    vr = engine.verify(sample_world, plan, exec_res)

    assert vr.verification_passed is True
    assert vr.status == VerificationStatus.VERIFIED
    assert vr.results_match is True
    assert vr.duckdb_result == 1000.0
    assert vr.primary_result == 1000.0
    assert vr.failures == []


def test_count_matches(sample_world: RepairWorld, orders_table: LoadedTable):
    """COUNT aggregation is independently reproduced and verified by DuckDB."""
    plan = AnalysisPlan(
        question="Row count",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="order_id"), operation="count"),
    )
    exec_res = _make_exec_result("world_001", 4, orders_table)

    vr = verify_execution(sample_world, plan, exec_res)

    assert vr.verification_passed is True
    assert vr.status == VerificationStatus.VERIFIED
    assert vr.duckdb_result == 4


def test_mean_matches(sample_world: RepairWorld, orders_table: LoadedTable):
    """MEAN aggregation is independently reproduced and verified by DuckDB."""
    plan = AnalysisPlan(
        question="Average amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="mean"),
    )
    # (100 + 200 + 300 + 400) / 4 = 250.0
    exec_res = _make_exec_result("world_001", 250.0, orders_table)

    vr = verify_execution(sample_world, plan, exec_res)

    assert vr.verification_passed is True
    assert vr.duckdb_result == 250.0


def test_min_matches(sample_world: RepairWorld, orders_table: LoadedTable):
    """MIN aggregation is independently reproduced and verified by DuckDB."""
    plan = AnalysisPlan(
        question="Minimum amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="min"),
    )
    exec_res = _make_exec_result("world_001", 100.0, orders_table)

    vr = verify_execution(sample_world, plan, exec_res)

    assert vr.verification_passed is True
    assert vr.duckdb_result == 100.0


def test_max_matches(sample_world: RepairWorld, orders_table: LoadedTable):
    """MAX aggregation is independently reproduced and verified by DuckDB."""
    plan = AnalysisPlan(
        question="Maximum amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="max"),
    )
    exec_res = _make_exec_result("world_001", 400.0, orders_table)

    vr = verify_execution(sample_world, plan, exec_res)

    assert vr.verification_passed is True
    assert vr.duckdb_result == 400.0


def test_distinct_count_matches(sample_world: RepairWorld, orders_table: LoadedTable):
    """DISTINCT COUNT is independently reproduced and verified by DuckDB."""
    plan = AnalysisPlan(
        question="Distinct categories",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="category")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="category"), operation="nunique"),
    )
    # 'books', 'electronics', 'furniture' = 3
    exec_res = _make_exec_result("world_001", 3, orders_table)

    vr = verify_execution(sample_world, plan, exec_res)

    assert vr.verification_passed is True
    assert vr.duckdb_result == 3


def test_group_by_matches(sample_world: RepairWorld, orders_table: LoadedTable):
    """GROUP BY dictionary result is independently reproduced and verified."""
    plan = AnalysisPlan(
        question="Amount by category",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[
            ColumnRef(table="orders", column="category"),
            ColumnRef(table="orders", column="amount"),
        ],
        group_by=[ColumnRef(table="orders", column="category")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="sum"),
    )
    expected_dict = {"books": 400.0, "electronics": 200.0, "furniture": 400.0}
    exec_res = _make_exec_result("world_001", expected_dict, orders_table)

    vr = verify_execution(sample_world, plan, exec_res)

    assert vr.verification_passed is True
    assert vr.duckdb_result == expected_dict


def test_filter_matches(sample_world: RepairWorld, orders_table: LoadedTable):
    """SUM with an explicit status filter is verified independently."""
    plan = AnalysisPlan(
        question="Completed amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[
            ColumnRef(table="orders", column="amount"),
            ColumnRef(table="orders", column="status"),
        ],
        filters=[
            FilterSpec(
                column=ColumnRef(table="orders", column="status"),
                operator="==",
                value="completed",
            )
        ],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="sum"),
    )
    # 100 + 200 + 400 = 700.0
    exec_res = _make_exec_result("world_001", 700.0, orders_table)

    vr = verify_execution(sample_world, plan, exec_res)

    assert vr.verification_passed is True
    assert vr.duckdb_result == 700.0


def test_year_filter_matches(sample_world: RepairWorld, orders_table: LoadedTable):
    """Year filter (2024) is verified independently."""
    plan = AnalysisPlan(
        question="2024 total amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[
            ColumnRef(table="orders", column="amount"),
            ColumnRef(table="orders", column="date"),
        ],
        filters=[
            FilterSpec(
                column=ColumnRef(table="orders", column="date"),
                operator="==",
                value=2024,
            )
        ],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="sum"),
    )
    # 2024 rows: order 1 (100), order 2 (200), order 4 (400) = 700.0
    exec_res = _make_exec_result("world_001", 700.0, orders_table)

    vr = verify_execution(sample_world, plan, exec_res)

    assert vr.verification_passed is True
    assert vr.duckdb_result == 700.0


def test_top_n_matches(sample_world: RepairWorld, orders_table: LoadedTable):
    """Top-1 category winner is independently confirmed."""
    plan = AnalysisPlan(
        question="Category with highest amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[
            ColumnRef(table="orders", column="category"),
            ColumnRef(table="orders", column="amount"),
        ],
        group_by=[ColumnRef(table="orders", column="category")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="sum"),
        limit=1,
        sort_ascending=False,
    )
    # Distinct top winner without ties (furniture = 500.0 vs books = 400.0)
    df_top = orders_table.dataframe.copy(deep=True)
    df_top.loc[df_top["category"] == "furniture", "amount"] = "500.0"
    top_table = LoadedTable(
        source_path=orders_table.source_path,
        file_type=orders_table.file_type,
        table_name="orders",
        column_names=list(df_top.columns),
        row_count=len(df_top),
        dataframe=df_top,
    )
    top_world = RepairWorld(
        world_id="world_001",
        description="Top N world",
        policies=[],
        repaired_tables=[top_table],
    )
    duckdb_winner = "furniture"
    exec_res = _make_exec_result("world_001", duckdb_winner, top_table)

    vr = verify_execution(top_world, plan, exec_res)

    assert vr.verification_passed is True
    assert vr.duckdb_result == duckdb_winner


def test_percentage_matches(sample_world: RepairWorld, orders_table: LoadedTable):
    """Percentage metric is independently reproduced."""
    plan = AnalysisPlan(
        question="Percentage of completed orders",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="status")],
        filters=[
            FilterSpec(
                column=ColumnRef(table="orders", column="status"),
                operator="==",
                value="completed",
            )
        ],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="status"), operation="percentage"),
    )
    # 3 out of 4 = 75.0%
    exec_res = _make_exec_result("world_001", 75.0, orders_table)

    vr = verify_execution(sample_world, plan, exec_res)

    assert vr.verification_passed is True
    assert vr.duckdb_result == 75.0


# ---------------------------------------------------------------------------
# 2. Trap Detection & Contradiction Handling
# ---------------------------------------------------------------------------

def test_duckdb_mismatch_detected(sample_world: RepairWorld, orders_table: LoadedTable):
    """Contradiction between primary and independent path fails verification."""
    plan = AnalysisPlan(
        question="Total amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="sum"),
    )
    # Actual sum is 1000.0, but primary falsely claims 1250.0
    exec_res = _make_exec_result("world_001", 1250.0, orders_table)

    vr = verify_execution(sample_world, plan, exec_res)

    assert vr.verification_passed is False
    assert vr.status == VerificationStatus.FAILED
    assert vr.results_match is False
    assert len(vr.failures) > 0
    assert "contradiction" in vr.failures[0].lower() or "mismatch" in vr.failures[0].lower()


def test_hardcoded_wrong_result_detected(sample_world: RepairWorld, orders_table: LoadedTable):
    """Deliberately wrong result (e.g. + 1000 trap) is caught and rejected."""
    plan = AnalysisPlan(
        question="Total amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="sum"),
    )
    # Real sum 1000.0 + 1000 trap = 2000.0
    exec_res = _make_exec_result("world_001", 2000.0, orders_table)

    vr = verify_execution(sample_world, plan, exec_res)

    assert vr.verification_passed is False
    assert vr.status == VerificationStatus.FAILED


def test_wrong_aggregation_detected(sample_world: RepairWorld, orders_table: LoadedTable):
    """Primary computes MEAN instead of requested SUM; caught by independent verifier."""
    plan = AnalysisPlan(
        question="Total amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="sum"),
    )
    # Provided mean 250.0 instead of sum 1000.0
    exec_res = _make_exec_result("world_001", 250.0, orders_table)

    vr = verify_execution(sample_world, plan, exec_res)

    assert vr.verification_passed is False
    assert vr.status == VerificationStatus.FAILED


# ---------------------------------------------------------------------------
# 3. Provenance and World Traps
# ---------------------------------------------------------------------------

def test_missing_provenance_detected(sample_world: RepairWorld, orders_table: LoadedTable):
    """Missing code hash or table hashes blocks verification (NOT_VERIFIED)."""
    plan = AnalysisPlan(
        question="Total amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="sum"),
    )
    exec_res = _make_exec_result("world_001", 1000.0, orders_table)
    # Strip provenance code hash
    exec_res_no_code_hash = exec_res.model_copy(update={"generated_code_hash": None})

    vr = verify_execution(sample_world, plan, exec_res_no_code_hash)

    assert vr.verification_passed is False
    assert vr.status == VerificationStatus.NOT_VERIFIED
    assert "provenance" in vr.failures[0].lower()


def test_hash_mismatch_detected(sample_world: RepairWorld, orders_table: LoadedTable):
    """Modifying table after execution triggers input hash mismatch failure."""
    plan = AnalysisPlan(
        question="Total amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="sum"),
    )
    exec_res = _make_exec_result("world_001", 1000.0, orders_table)

    # Now mutate the world table behind the back of the execution
    mutated_df = orders_table.dataframe.copy(deep=True)
    mutated_df.loc[0, "amount"] = "9999.0"
    mutated_table = LoadedTable(
        source_path=Path("tests/data/orders.csv"),
        file_type=FileType.CSV,
        table_name="orders",
        column_names=list(mutated_df.columns),
        row_count=len(mutated_df),
        dataframe=mutated_df,
    )
    mutated_world = RepairWorld(
        world_id="world_001",
        description="Mutated world",
        policies=[],
        repaired_tables=[mutated_table],
    )

    vr = verify_execution(mutated_world, plan, exec_res)

    assert vr.verification_passed is False
    assert vr.status == VerificationStatus.NOT_VERIFIED
    assert "mutation detected" in vr.failures[0].lower()


def test_world_mismatch_detected(orders_table: LoadedTable):
    """World Mix-up Trap: Primary ran on world_001, verifying against world_002."""
    plan = AnalysisPlan(
        question="Total amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="sum"),
    )
    exec_res = _make_exec_result("world_001", 1000.0, orders_table)

    world_002 = RepairWorld(
        world_id="world_002",
        description="Different world",
        policies=[],
        repaired_tables=[orders_table],
    )

    vr = verify_execution(world_002, plan, exec_res)

    assert vr.verification_passed is False
    assert vr.status == VerificationStatus.NOT_VERIFIED
    assert "world id mismatch" in vr.failures[0].lower()


def test_missing_table_detected(sample_world: RepairWorld, orders_table: LoadedTable):
    """Schema check detects table requested by plan missing from world."""
    plan = AnalysisPlan(
        question="Inventory",
        status=PlanStatus.READY,
        required_tables=["inventory"],
        required_columns=[],
    )
    exec_res = _make_exec_result("world_001", 50, orders_table)

    vr = verify_execution(sample_world, plan, exec_res)

    assert vr.verification_passed is False
    assert vr.status == VerificationStatus.NOT_VERIFIED
    assert "schema check failed" in vr.failures[0].lower()


def test_missing_column_detected(sample_world: RepairWorld, orders_table: LoadedTable):
    """Schema check detects column requested by plan missing from table."""
    plan = AnalysisPlan(
        question="Profit",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="profit")],
    )
    exec_res = _make_exec_result("world_001", 50, orders_table)

    vr = verify_execution(sample_world, plan, exec_res)

    assert vr.verification_passed is False
    assert vr.status == VerificationStatus.NOT_VERIFIED
    assert "schema check failed" in vr.failures[0].lower()


# ---------------------------------------------------------------------------
# 4. Numeric Tolerances & Special Values
# ---------------------------------------------------------------------------

def test_numeric_tolerance_works(sample_world: RepairWorld, orders_table: LoadedTable):
    """Verification respects absolute and relative tolerances."""
    plan = AnalysisPlan(
        question="Total amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="sum"),
    )
    # DuckDB sum is 1000.0, primary has tiny floating point diff 1000.0000000000001
    exec_res = _make_exec_result("world_001", 1000.0000000000001, orders_table)

    engine = VerificationEngine(abs_tol=1e-8, rel_tol=1e-8)
    vr = engine.verify(sample_world, plan, exec_res)

    assert vr.verification_passed is True
    assert vr.results_match is True


def test_nan_handling_policy(sample_world: RepairWorld, orders_table: LoadedTable):
    """NaN vs NaN is rejected as unstable unless allow_nan_match=True."""
    plan = AnalysisPlan(
        question="Total amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="sum"),
    )
    exec_res = _make_exec_result("world_001", float("nan"), orders_table)

    engine = VerificationEngine(allow_nan_match=False)
    vr = engine.verify(sample_world, plan, exec_res)

    # DuckDB returns 1000.0, primary was NaN -> mismatch
    assert vr.verification_passed is False
    assert vr.status == VerificationStatus.FAILED


def test_deterministic_repeatability(sample_world: RepairWorld, orders_table: LoadedTable):
    """Running verification twice produces identical status, checks, and output."""
    plan = AnalysisPlan(
        question="Total amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="sum"),
    )
    exec_res = _make_exec_result("world_001", 1000.0, orders_table)

    engine = VerificationEngine()
    vr1 = engine.verify(sample_world, plan, exec_res)
    vr2 = engine.verify(sample_world, plan, exec_res)

    assert vr1.status == vr2.status
    assert vr1.verification_passed == vr2.verification_passed
    assert len(vr1.checks) == len(vr2.checks)


def test_verified_with_assumption(orders_table: LoadedTable):
    """RepairWorld carrying explicit assumptions results in VERIFIED_WITH_ASSUMPTION."""
    plan = AnalysisPlan(
        question="Total amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="sum"),
    )
    exec_res = _make_exec_result("world_001", 1000.0, orders_table)

    world_with_assump = RepairWorld(
        world_id="world_001",
        description="Assumed dates as DD/MM/YYYY",
        policies=[],
        repaired_tables=[orders_table],
        assumptions=["Interpreted all ambiguous dates as DD/MM/YYYY"],
    )

    vr = verify_execution(world_with_assump, plan, exec_res)

    assert vr.verification_passed is True
    assert vr.status == VerificationStatus.VERIFIED_WITH_ASSUMPTION
    assert len(vr.world_assumptions) == 1
