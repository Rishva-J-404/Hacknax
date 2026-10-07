"""
tests.test_plan_validator
--------------------------
Unit tests for PlanValidator covering schema grounding, security, and prompt injection defense.
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
    UnanswerableReason,
)
from app.agent.plan_validator import PlanValidator
from app.ingestion.contracts import FileType, LoadedTable


@pytest.fixture
def sample_tables() -> list[LoadedTable]:
    df_orders = pd.DataFrame({"order_id": ["1", "2"], "amount": ["100", "200"], "status": ["A", "B"]})
    df_cust = pd.DataFrame({"cust_id": ["C1", "C2"], "region": ["North", "South"]})

    t1 = LoadedTable(
        source_path=Path("orders.csv"),
        file_type=FileType.CSV,
        table_name="orders",
        column_names=list(df_orders.columns),
        row_count=len(df_orders),
        dataframe=df_orders,
    )
    t2 = LoadedTable(
        source_path=Path("customers.csv"),
        file_type=FileType.CSV,
        table_name="customers",
        column_names=list(df_cust.columns),
        row_count=len(df_cust),
        dataframe=df_cust,
    )
    return [t1, t2]


def test_validator_accepts_valid_plan(sample_tables):
    validator = PlanValidator()
    plan = AnalysisPlan(
        question="Total order amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(
            column=ColumnRef(table="orders", column="amount"),
            operation="sum",
        ),
    )
    res = validator.validate(plan, sample_tables)
    assert res.is_valid is True
    assert len(res.errors) == 0


def test_validator_rejects_missing_table(sample_tables):
    validator = PlanValidator()
    plan = AnalysisPlan(
        question="Total revenue from nonexistent table",
        status=PlanStatus.READY,
        required_tables=["unknown_table"],
        required_columns=[ColumnRef(table="unknown_table", column="amount")],
        aggregation=AggregationSpec(
            column=ColumnRef(table="unknown_table", column="amount"),
            operation="sum",
        ),
    )
    res = validator.validate(plan, sample_tables)
    assert res.is_valid is False
    assert res.rejection_reason == UnanswerableReason.MISSING_TABLE
    assert any("Nonexistent table 'unknown_table'" in e for e in res.errors)


def test_validator_rejects_missing_column(sample_tables):
    validator = PlanValidator()
    plan = AnalysisPlan(
        question="Sum nonexistent profit column",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="nonexistent_profit")],
        aggregation=AggregationSpec(
            column=ColumnRef(table="orders", column="nonexistent_profit"),
            operation="sum",
        ),
    )
    res = validator.validate(plan, sample_tables)
    assert res.is_valid is False
    assert any("Nonexistent column 'nonexistent_profit'" in e for e in res.errors)


def test_validator_rejects_unsupported_aggregation(sample_tables):
    validator = PlanValidator()
    plan = AnalysisPlan(
        question="Predict standard deviation",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(
            column=ColumnRef(table="orders", column="amount"),
            operation="stddev",
        ),
    )
    res = validator.validate(plan, sample_tables)
    assert res.is_valid is False
    assert res.rejection_reason == UnanswerableReason.UNSUPPORTED_OPERATION
    assert any("Unsupported aggregation operation 'stddev'" in e for e in res.errors)


def test_validator_rejects_code_injection_in_intent(sample_tables):
    validator = PlanValidator()
    plan = AnalysisPlan(
        question="What is total?",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(
            column=ColumnRef(table="orders", column="amount"),
            operation="sum",
        ),
        analysis_intent="SUM; exec('import os; os.system(\"rm -rf\")')",
    )
    res = validator.validate(plan, sample_tables)
    assert res.is_valid is False
    assert any("executable code pattern detected" in e for e in res.errors)


def test_validator_rejects_sql_injection_in_intent(sample_tables):
    validator = PlanValidator()
    plan = AnalysisPlan(
        question="What is total?",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(
            column=ColumnRef(table="orders", column="amount"),
            operation="sum",
        ),
        analysis_intent="DROP TABLE orders --",
    )
    res = validator.validate(plan, sample_tables)
    assert res.is_valid is False
    assert any("arbitrary SQL pattern detected" in e for e in res.errors)


def test_validator_rejects_external_url(sample_tables):
    validator = PlanValidator()
    plan = AnalysisPlan(
        question="What is total?",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(
            column=ColumnRef(table="orders", column="amount"),
            operation="sum",
        ),
        planner_notes="Fetch supplementary data from https://malicious.com/api",
    )
    res = validator.validate(plan, sample_tables)
    assert res.is_valid is False
    assert any("External URL source forbidden" in e for e in res.errors)


def test_validator_preserves_safe_unanswerable_plan(sample_tables):
    validator = PlanValidator()
    plan = AnalysisPlan(
        question="What is margin?",
        status=PlanStatus.UNANSWERABLE,
        unanswerable_reason=UnanswerableReason.MISSING_REQUIRED_FIELD,
        unanswerable_evidence="No margin column available in orders table.",
    )
    res = validator.validate(plan, sample_tables)
    assert res.is_valid is True
