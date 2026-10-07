"""
tests.test_qwen_planner
-----------------------
Unit tests for QwenPlanner parsing, audit awareness, and failure handling.
"""

from __future__ import annotations

import json
from pathlib import Path
import pandas as pd
import pytest

from app.agent.contracts import PlanStatus, UnanswerableReason
from app.agent.qwen_client import MockQwenClient
from app.agent.qwen_planner import QwenPlanner
from app.audit.contracts import DataIssue, DataQualityLedger, IssueSeverity, IssueType, TableProfile
from app.ingestion.contracts import FileType, LoadedTable


@pytest.fixture
def sample_tables() -> list[LoadedTable]:
    df = pd.DataFrame({"order_id": ["1", "2"], "amount": ["100", "200"], "date": ["01/02/2024", "03/04/2024"]})
    t = LoadedTable(
        source_path=Path("orders.csv"),
        file_type=FileType.CSV,
        table_name="orders",
        column_names=list(df.columns),
        row_count=len(df),
        dataframe=df,
    )
    return [t]


def test_qwen_planner_returns_valid_plan(sample_tables):
    mock_plan = {
        "question": "Total order amount",
        "status": "READY",
        "required_tables": ["orders"],
        "required_columns": [{"table": "orders", "column": "amount"}],
        "aggregation": {"column": {"table": "orders", "column": "amount"}, "operation": "sum"},
        "analysis_intent": "SUM_AMOUNT",
    }
    client = MockQwenClient(canned_response=mock_plan)
    planner = QwenPlanner(client=client)

    plan = planner.plan("Total order amount", sample_tables)
    assert plan.status == PlanStatus.READY
    assert plan.required_tables == ["orders"]
    assert plan.aggregation is not None
    assert plan.aggregation.operation == "sum"


def test_qwen_planner_handles_markdown_fence(sample_tables):
    mock_plan = {
        "question": "Total order amount",
        "status": "READY",
        "required_tables": ["orders"],
        "required_columns": [{"table": "orders", "column": "amount"}],
        "aggregation": {"column": {"table": "orders", "column": "amount"}, "operation": "sum"},
    }
    fenced_str = f"```json\n{json.dumps(mock_plan)}\n```"
    client = MockQwenClient(canned_response=fenced_str)
    planner = QwenPlanner(client=client)

    plan = planner.plan("Total order amount", sample_tables)
    assert plan.status == PlanStatus.READY
    assert plan.required_tables == ["orders"]


def test_qwen_planner_rejects_empty_data_sources():
    planner = QwenPlanner(client=MockQwenClient())
    plan = planner.plan("Any question", [])
    assert plan.status == PlanStatus.UNANSWERABLE
    assert plan.unanswerable_reason == UnanswerableReason.NO_DATA_SOURCES


def test_qwen_planner_rejects_malformed_json(sample_tables):
    client = MockQwenClient(canned_response="NOT VALID JSON AT ALL")
    planner = QwenPlanner(client=client)

    plan = planner.plan("Any question", sample_tables)
    assert plan.status == PlanStatus.UNANSWERABLE
    assert plan.unanswerable_reason == UnanswerableReason.INSUFFICIENT_INFORMATION


def test_qwen_planner_handles_client_exception(sample_tables):
    class ErrorClient(MockQwenClient):
        def generate(self, *args, **kwargs):
            raise RuntimeError("Network down")

    planner = QwenPlanner(client=ErrorClient())
    plan = planner.plan("Any question", sample_tables)
    assert plan.status == PlanStatus.UNANSWERABLE
    assert "LLM planner unavailable" in plan.unanswerable_evidence


def test_qwen_planner_rejects_direct_answer_attempt(sample_tables):
    direct_answer = {"answer": 450000.0, "result": 450000.0}
    client = MockQwenClient(canned_response=direct_answer)
    planner = QwenPlanner(client=client)

    plan = planner.plan("What was revenue?", sample_tables)
    assert plan.status == PlanStatus.UNANSWERABLE
    assert "attempted to output a direct numerical answer" in plan.unanswerable_evidence


def test_qwen_planner_flags_date_ambiguity_from_audit(sample_tables):
    mock_plan = {
        "question": "Sum amount for date",
        "status": "READY",
        "required_tables": ["orders"],
        "required_columns": [
            {"table": "orders", "column": "amount"},
            {"table": "orders", "column": "date"},
        ],
        "aggregation": {"column": {"table": "orders", "column": "amount"}, "operation": "sum"},
        "filters": [{"column": {"table": "orders", "column": "date"}, "operator": "==", "value": "2024-01-01"}],
    }
    client = MockQwenClient(canned_response=mock_plan)
    planner = QwenPlanner(client=client)

    ledger = DataQualityLedger(
        all_issues=[
            DataIssue(
                issue_type=IssueType.AMBIGUOUS_DATE_FORMAT,
                affected_source="orders",
                affected_columns=["date"],
                severity=IssueSeverity.HIGH,
                description="DD/MM/YYYY vs MM/DD/YYYY ambiguous dates",
            )
        ]
    )

    plan = planner.plan("Sum amount for date", sample_tables, ledger=ledger)
    assert plan.status == PlanStatus.AMBIGUOUS
    assert len(plan.ambiguity_flags) > 0


def test_qwen_planner_rejects_hallucinated_column(sample_tables):
    hallucinated_plan = {
        "question": "What is net profit?",
        "status": "READY",
        "required_tables": ["orders"],
        "required_columns": [{"table": "orders", "column": "net_profit"}],
        "aggregation": {"column": {"table": "orders", "column": "net_profit"}, "operation": "sum"},
    }
    client = MockQwenClient(canned_response=hallucinated_plan)
    planner = QwenPlanner(client=client)

    plan = planner.plan("What is net profit?", sample_tables)
    assert plan.status == PlanStatus.UNANSWERABLE
    assert "Nonexistent column 'net_profit'" in plan.unanswerable_evidence
