"""
tests/test_planner.py
---------------------
Tests for Phase 5: Deterministic Analysis Planner in ProofLens.

Verifies:
1. Total SUM question.
2. Average question.
3. COUNT question.
4. MIN/MAX questions.
5. DISTINCT COUNT question.
6. GROUP BY (Top N) question.
7. Filter by year.
8. Simple percentage question.
9. Missing column -> UNANSWERABLE.
10. Ambiguous column -> AMBIGUOUS.
11. Ambiguous date -> AMBIGUOUS.
12. Unsupported operation -> UNANSWERABLE.
13. Multi-table deterministic join works when key relationship is explicit.
14. Unclear join is rejected.
15. Plan is JSON serializable and roundtrips cleanly.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.agent import (
    AnalysisPlan,
    DeterministicPlanner,
    PlanStatus,
    UnanswerableReason,
)
from app.audit import audit_tables
from app.ingestion.contracts import FileType, LoadedTable


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_table(name: str, data: dict[str, list[str]]) -> LoadedTable:
    df = pd.DataFrame(data).astype(str)
    return LoadedTable(
        source_path=Path(f"data/{name}.csv"),
        file_type=FileType.CSV,
        table_name=name,
        sheet_name=None,
        column_names=list(df.columns),
        row_count=len(df),
        dataframe=df,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_total_sum_question():
    table = _make_table("orders", {"order_id": ["1", "2"], "revenue": ["100", "200"]})
    planner = DeterministicPlanner()
    plan = planner.plan("What is the total revenue?", [table])

    assert plan.status == PlanStatus.READY
    assert plan.aggregation is not None
    assert plan.aggregation.operation == "sum"
    assert plan.aggregation.column.column == "revenue"


def test_average_question():
    table = _make_table("orders", {"order_id": ["1", "2"], "sales": ["50", "150"]})
    planner = DeterministicPlanner()
    plan = planner.plan("What is the average sales amount?", [table])

    assert plan.status == PlanStatus.READY
    assert plan.aggregation is not None
    assert plan.aggregation.operation == "mean"
    assert plan.aggregation.column.column == "sales"


def test_count_question():
    table = _make_table("transactions", {"tx_id": ["T1", "T2", "T3"], "status": ["ok", "ok", "ok"]})
    planner = DeterministicPlanner()
    plan = planner.plan("How many transactions are there?", [table])

    assert plan.status == PlanStatus.READY
    assert plan.aggregation is not None
    assert plan.aggregation.operation == "count"


def test_min_max_questions():
    table = _make_table("orders", {"order_id": ["1", "2"], "amount": ["10", "90"]})
    planner = DeterministicPlanner()

    plan_min = planner.plan("What is the minimum amount?", [table])
    assert plan_min.status == PlanStatus.READY
    assert plan_min.aggregation is not None
    assert plan_min.aggregation.operation == "min"

    plan_max = planner.plan("What is the maximum amount?", [table])
    assert plan_max.status == PlanStatus.READY
    assert plan_max.aggregation is not None
    assert plan_max.aggregation.operation == "max"


def test_distinct_count_question():
    table = _make_table("orders", {"customer_id": ["C1", "C2", "C1"], "revenue": ["10", "20", "30"]})
    planner = DeterministicPlanner()
    plan = planner.plan("How many unique customers are there?", [table])

    assert plan.status == PlanStatus.READY
    assert plan.aggregation is not None
    assert plan.aggregation.operation == "nunique"
    assert plan.aggregation.column.column == "customer_id"


def test_group_by_top_n_question():
    table = _make_table("sales", {"product": ["A", "B", "A"], "revenue": ["100", "200", "50"]})
    planner = DeterministicPlanner()
    plan = planner.plan("Which product had the highest revenue?", [table])

    assert plan.status == PlanStatus.READY
    assert len(plan.group_by) == 1
    assert plan.group_by[0].column == "product"
    assert plan.sort_by is not None
    assert plan.sort_by.column == "revenue"
    assert plan.limit == 1
    assert plan.sort_ascending is False


def test_filter_by_year():
    table = _make_table("orders", {"order_id": ["1"], "revenue": ["100"], "order_date": ["2025-05-01"]})
    planner = DeterministicPlanner()
    plan = planner.plan("What was the total revenue in 2025?", [table])

    assert plan.status == PlanStatus.READY
    assert len(plan.filters) == 1
    assert plan.filters[0].column.column == "order_date"
    assert plan.filters[0].operator == "=="
    assert plan.filters[0].value == 2025


def test_simple_percentage():
    table = _make_table("transactions", {"tx_id": ["1", "2"], "status": ["successful", "failed"]})
    planner = DeterministicPlanner()
    plan = planner.plan("What percentage of transactions were successful?", [table])

    assert plan.status == PlanStatus.READY
    assert plan.aggregation is not None
    assert plan.aggregation.operation == "percentage"
    assert len(plan.filters) == 1
    assert plan.filters[0].value == "successful"


def test_missing_column_unanswerable():
    table = _make_table("orders", {"order_id": ["1", "2"], "status": ["ok", "ok"]})
    planner = DeterministicPlanner()
    plan = planner.plan("What is the total revenue?", [table])

    assert plan.status == PlanStatus.UNANSWERABLE
    assert plan.unanswerable_reason == UnanswerableReason.MISSING_REQUIRED_FIELD


def test_ambiguous_column_flagged():
    # Table has both 'sales' and 'revenue'
    table = _make_table("finance", {"sales": ["100"], "revenue": ["100"]})
    planner = DeterministicPlanner()
    plan = planner.plan("What are the sales?", [table])

    assert plan.status == PlanStatus.AMBIGUOUS
    assert plan.unanswerable_reason == UnanswerableReason.AMBIGUOUS_COLUMN
    assert len(plan.ambiguity_flags) > 0


def test_ambiguous_date_flagged():
    table = _make_table("dated", {"date": ["01/02/2025", "03/04/2025"], "revenue": ["50", "60"]})
    ledger = audit_tables([table])
    planner = DeterministicPlanner()
    plan = planner.plan("What was revenue on 01/02/2025?", [table], ledger=ledger)

    assert plan.status == PlanStatus.AMBIGUOUS
    assert plan.unanswerable_reason == UnanswerableReason.AMBIGUOUS_DATE
    assert len(plan.ambiguity_flags) > 0


def test_unsupported_operation_unanswerable():
    table = _make_table("orders", {"revenue": ["100"]})
    planner = DeterministicPlanner()
    plan = planner.plan("Predict next month's revenue with machine learning.", [table])

    assert plan.status == PlanStatus.UNANSWERABLE
    assert plan.unanswerable_reason == UnanswerableReason.UNSUPPORTED_OPERATION


def test_multi_table_join_explicit_key():
    t_orders = _make_table("orders", {"order_id": ["1"], "customer_id": ["C1"], "revenue": ["100"]})
    t_cust = _make_table("customers", {"customer_id": ["C1"], "customer_name": ["Alice"]})
    planner = DeterministicPlanner()
    plan = planner.plan("What is the total revenue for customers?", [t_orders, t_cust])

    assert plan.status == PlanStatus.READY
    assert len(plan.join_keys) == 1
    assert plan.join_keys[0][0].column == "customer_id"
    assert plan.join_keys[0][1].column == "customer_id"


def test_unclear_join_rejected():
    t_orders = _make_table("orders", {"order_id": ["1"], "revenue": ["100"]})
    t_cust = _make_table("customers", {"client_name": ["Alice"]})  # No common key
    planner = DeterministicPlanner()
    plan = planner.plan("What is total revenue for customers?", [t_orders, t_cust])

    assert plan.status in {PlanStatus.UNANSWERABLE, PlanStatus.AMBIGUOUS}
    assert plan.unanswerable_reason == UnanswerableReason.INSUFFICIENT_INFORMATION


def test_plan_is_json_serializable():
    table = _make_table("orders", {"revenue": ["100"]})
    planner = DeterministicPlanner()
    plan = planner.plan("What is total revenue?", [table])

    json_str = plan.model_dump_json()
    restored = AnalysisPlan.model_validate_json(json_str)
    assert restored.question == plan.question
    assert restored.status == plan.status
    assert restored.aggregation is not None
    assert restored.aggregation.operation == plan.aggregation.operation
