"""
tests.test_metamorphic
----------------------
Comprehensive test suite for Phase 7 — Metamorphic Property Testing.

Tests:
1. Row-order invariance (PASS on order-independent aggregations).
2. Duplicate injection for COUNT (PASS: increases count by 1).
3. Duplicate injection for DISTINCT COUNT (PASS: preserves distinct count).
4. Zero-row SUM (PASS: adding 0.0 row leaves sum unchanged).
5. Ratio duplication invariance (PASS: duplicating dataset preserves ratio).
6. Filter monotonicity (PASS: subsetting never increases count).
7. Group-total consistency (PASS: sum of group sums equals overall sum).
8. TOP-N consistency (PASS: Top-1 winner equals highest group).
9. Inapplicable tests return SKIPPED.
10. Metamorphic results are strictly deterministic across repeated runs.
"""

from __future__ import annotations

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
from app.ingestion.contracts import FileType, LoadedTable
from app.repair.contracts import RepairWorld
from app.verification.contracts import CheckOutcome
from app.verification.metamorphic import MetamorphicSuite


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sales_table() -> LoadedTable:
    df = pd.DataFrame(
        [
            {"order_id": "1", "amount": "100.0", "status": "completed", "category": "A"},
            {"order_id": "2", "amount": "200.0", "status": "completed", "category": "B"},
            {"order_id": "3", "amount": "300.0", "status": "failed", "category": "A"},
            {"order_id": "4", "amount": "400.0", "status": "completed", "category": "C"},
        ]
    )
    return LoadedTable(
        source_path=Path("tests/data/sales.csv"),
        file_type=FileType.CSV,
        table_name="sales",
        column_names=list(df.columns),
        row_count=len(df),
        dataframe=df,
    )


@pytest.fixture
def sample_world(sales_table: LoadedTable) -> RepairWorld:
    return RepairWorld(
        world_id="world_001",
        description="Clean baseline test world",
        policies=[],
        repaired_tables=[sales_table],
    )


@pytest.fixture
def suite() -> MetamorphicSuite:
    return MetamorphicSuite()


# ---------------------------------------------------------------------------
# Metamorphic Tests
# ---------------------------------------------------------------------------

def test_row_order_invariance(sample_world: RepairWorld, suite: MetamorphicSuite):
    """Reversing rows leaves SUM aggregation invariant."""
    plan = AnalysisPlan(
        question="Total sales",
        status=PlanStatus.READY,
        required_tables=["sales"],
        required_columns=[ColumnRef(table="sales", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="sales", column="amount"), operation="sum"),
    )
    baseline_sum = 1000.0

    res = suite.test_row_order_invariance(sample_world, plan, baseline_sum)

    assert res.applicable is True
    assert res.status == CheckOutcome.PASS
    assert float(res.observed) == 1000.0


def test_duplicate_injection_count(sample_world: RepairWorld, suite: MetamorphicSuite):
    """Injecting a duplicate row increases COUNT by exactly 1."""
    plan = AnalysisPlan(
        question="Count sales",
        status=PlanStatus.READY,
        required_tables=["sales"],
        required_columns=[],
        aggregation=AggregationSpec(column=ColumnRef(table="sales", column="order_id"), operation="count"),
    )
    baseline_count = 4

    res = suite.test_duplicate_injection(sample_world, plan, baseline_count)

    assert res.applicable is True
    assert res.status == CheckOutcome.PASS
    assert int(res.observed) == 5
    assert int(res.expected) == 5


def test_duplicate_injection_distinct_count(sample_world: RepairWorld, suite: MetamorphicSuite):
    """Injecting a duplicate row leaves DISTINCT COUNT unchanged."""
    plan = AnalysisPlan(
        question="Distinct categories",
        status=PlanStatus.READY,
        required_tables=["sales"],
        required_columns=[ColumnRef(table="sales", column="category")],
        aggregation=AggregationSpec(column=ColumnRef(table="sales", column="category"), operation="nunique"),
    )
    baseline_distinct = 3  # Categories A, B, C

    res = suite.test_duplicate_injection(sample_world, plan, baseline_distinct)

    assert res.applicable is True
    assert res.status == CheckOutcome.PASS
    assert int(res.observed) == 3
    assert int(res.expected) == 3


def test_zero_row_sum(sample_world: RepairWorld, suite: MetamorphicSuite):
    """Adding a row with 0.0 leaves the overall SUM unchanged."""
    plan = AnalysisPlan(
        question="Total sales",
        status=PlanStatus.READY,
        required_tables=["sales"],
        required_columns=[ColumnRef(table="sales", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="sales", column="amount"), operation="sum"),
    )
    baseline_sum = 1000.0

    res = suite.test_add_zero_row(sample_world, plan, baseline_sum)

    assert res.applicable is True
    assert res.status == CheckOutcome.PASS
    assert float(res.observed) == 1000.0


def test_ratio_duplication_invariance(sample_world: RepairWorld, suite: MetamorphicSuite):
    """Duplicating all rows equally preserves the percentage metric."""
    plan = AnalysisPlan(
        question="Completion percentage",
        status=PlanStatus.READY,
        required_tables=["sales"],
        required_columns=[ColumnRef(table="sales", column="status")],
        filters=[
            FilterSpec(
                column=ColumnRef(table="sales", column="status"),
                operator="==",
                value="completed",
            )
        ],
        aggregation=AggregationSpec(column=ColumnRef(table="sales", column="status"), operation="percentage"),
    )
    baseline_percentage = 75.0  # 3 of 4

    res = suite.test_ratio_duplication(sample_world, plan, baseline_percentage)

    assert res.applicable is True
    assert res.status == CheckOutcome.PASS
    assert float(res.observed) == 75.0


def test_filter_monotonicity(sample_world: RepairWorld, suite: MetamorphicSuite):
    """Subsetting the data never increases COUNT."""
    plan = AnalysisPlan(
        question="Count sales",
        status=PlanStatus.READY,
        required_tables=["sales"],
        required_columns=[],
        aggregation=AggregationSpec(column=ColumnRef(table="sales", column="order_id"), operation="count"),
    )
    baseline_count = 4

    res = suite.test_filter_monotonicity(sample_world, plan, baseline_count)

    assert res.applicable is True
    assert res.status == CheckOutcome.PASS
    assert int(res.observed) <= 4


def test_group_total_consistency(sample_world: RepairWorld, suite: MetamorphicSuite):
    """Sum of all category sums equals overall ungrouped table SUM."""
    plan = AnalysisPlan(
        question="Sales by category",
        status=PlanStatus.READY,
        required_tables=["sales"],
        required_columns=[
            ColumnRef(table="sales", column="category"),
            ColumnRef(table="sales", column="amount"),
        ],
        group_by=[ColumnRef(table="sales", column="category")],
        aggregation=AggregationSpec(column=ColumnRef(table="sales", column="amount"), operation="sum"),
    )
    baseline_dict = {"A": 400.0, "B": 200.0, "C": 400.0}

    res = suite.test_group_total_consistency(sample_world, plan, baseline_dict)

    assert res.applicable is True
    assert res.status == CheckOutcome.PASS
    assert float(res.expected) == 1000.0
    assert float(res.observed) == 1000.0


def test_top_n_consistency(sample_world: RepairWorld, suite: MetamorphicSuite):
    """Top-1 winner selection agrees with highest category group sum."""
    plan = AnalysisPlan(
        question="Top category by sales",
        status=PlanStatus.READY,
        required_tables=["sales"],
        required_columns=[
            ColumnRef(table="sales", column="category"),
            ColumnRef(table="sales", column="amount"),
        ],
        group_by=[ColumnRef(table="sales", column="category")],
        aggregation=AggregationSpec(column=ColumnRef(table="sales", column="amount"), operation="sum"),
        limit=1,
        sort_ascending=False,
    )
    winner = "A"  # A has 400.0 (ties C 400.0)

    res = suite.test_top_n_consistency(sample_world, plan, winner)

    assert res.applicable is True
    assert res.status == CheckOutcome.PASS


def test_inapplicable_test_returns_skipped(sample_world: RepairWorld, suite: MetamorphicSuite):
    """Add-zero test on a COUNT query is marked SKIPPED."""
    plan = AnalysisPlan(
        question="Count sales",
        status=PlanStatus.READY,
        required_tables=["sales"],
        required_columns=[],
        aggregation=AggregationSpec(column=ColumnRef(table="sales", column="order_id"), operation="count"),
    )
    res = suite.test_add_zero_row(sample_world, plan, 4)

    assert res.applicable is False
    assert res.status == CheckOutcome.SKIPPED


def test_deterministic_metamorphic_results(sample_world: RepairWorld, suite: MetamorphicSuite):
    """Running metamorphic suite repeatedly produces identical results."""
    plan = AnalysisPlan(
        question="Total sales",
        status=PlanStatus.READY,
        required_tables=["sales"],
        required_columns=[ColumnRef(table="sales", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="sales", column="amount"), operation="sum"),
    )
    baseline_sum = 1000.0

    run1 = suite.run_all(sample_world, plan, baseline_sum)
    run2 = suite.run_all(sample_world, plan, baseline_sum)

    assert len(run1) == len(run2)
    for r1, r2 in zip(run1, run2):
        assert r1.name == r2.name
        assert r1.status == r2.status
        assert r1.expected == r2.expected
        assert r1.observed == r2.observed
