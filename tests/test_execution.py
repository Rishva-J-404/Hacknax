"""
tests.test_execution
--------------------
Exhaustive test suite for Phase 6 — Secure Execution Engine and Result Capture.

Tests:
1. Basic operations (SUM, COUNT, MEAN, Group-by, Multi-table join)
2. Failures (Missing table, Missing column, Runtime error, AssertionError, ResultMissing)
3. Timeout enforcement (Hard timeout on infinite loop)
4. Security & Safety (Reject os, sys, subprocess, socket, requests, eval, exec, open,
   __import__, globals, locals, getattr, dunder attributes)
5. Environment isolation (API keys and secrets stripped from worker environment)
6. Immutability (Input DataFrames and RepairWorld untouched)
7. Determinism & Provenance (Cryptographic hashes for code and tables)
8. Output truncation (Large stdout bounded and flagged)
9. raise_on_error flag and convenience functions
"""

from __future__ import annotations

import os
from pathlib import Path
import time
import pandas as pd
import pytest

from app.agent.contracts import (
    AggregationSpec,
    AnalysisPlan,
    ColumnRef,
    PlanStatus,
)
from app.execution.code_generator import generate_analysis_code
from app.execution.contracts import ExecutionResult, GeneratedCode
from app.execution.runner import (
    ExecutionConfig,
    ExecutionError,
    ExecutionTimeoutError,
    MissingColumnError,
    MissingTableError,
    ResultMissingError,
    SecureRunner,
    UnsafeCodeError,
    _build_clean_environment,
    run_analysis,
)
from app.ingestion.contracts import FileType, LoadedTable
from app.repair.contracts import RepairWorld


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def orders_table() -> LoadedTable:
    df = pd.DataFrame(
        [
            {"order_id": "1", "customer_id": "C101", "amount": "100.0", "status": "completed", "category": "books"},
            {"order_id": "2", "customer_id": "C102", "amount": "200.0", "status": "completed", "category": "electronics"},
            {"order_id": "3", "customer_id": "C101", "amount": "300.0", "status": "failed", "category": "books"},
            {"order_id": "4", "customer_id": "C103", "amount": "400.0", "status": "completed", "category": "furniture"},
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
def customers_table() -> LoadedTable:
    df = pd.DataFrame(
        [
            {"customer_id": "C101", "region": "North"},
            {"customer_id": "C102", "region": "South"},
            {"customer_id": "C103", "region": "North"},
        ]
    )
    return LoadedTable(
        source_path=Path("tests/data/customers.csv"),
        file_type=FileType.CSV,
        table_name="customers",
        column_names=list(df.columns),
        row_count=len(df),
        dataframe=df,
    )


@pytest.fixture
def sample_world(orders_table: LoadedTable, customers_table: LoadedTable) -> RepairWorld:
    return RepairWorld(
        world_id="world_001",
        description="Clean baseline test world",
        policies=[],
        repaired_tables=[orders_table, customers_table],
    )


@pytest.fixture
def runner() -> SecureRunner:
    return SecureRunner(ExecutionConfig(timeout_seconds=5.0))


# ---------------------------------------------------------------------------
# 1. Basic Analytical Operations
# ---------------------------------------------------------------------------

def test_execute_sum_metric(sample_world: RepairWorld, runner: SecureRunner):
    """Test safe execution of a SUM aggregation."""
    code_text = (
        "df = tables['orders'].copy()\n"
        "assert 'amount' in df.columns\n"
        "numeric_vals = pd.to_numeric(df['amount'], errors='coerce')\n"
        "result = float(numeric_vals.sum())\n"
        "RESULT = result\n"
        "print(result)\n"
    )
    plan = AnalysisPlan(
        question="Total amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="sum"),
    )
    code = GeneratedCode(
        code_path=Path("proofs/test_sum.py"),
        world_id=sample_world.world_id,
        code_content=code_text,
    )

    res = runner.run(sample_world, plan, code)

    assert res.execution_success is True
    assert res.exit_code == 0
    assert res.result_value == 1000.0
    assert res.result_type == "float"
    assert res.error_type is None
    assert "1000.0" in res.stdout
    assert res.table_names == ["orders", "customers"]
    assert res.row_counts == {"orders": 4, "customers": 3}
    assert res.generated_code_hash is not None
    assert len(res.input_data_hashes) == 2


def test_execute_count_metric(sample_world: RepairWorld, runner: SecureRunner):
    """Test safe execution of a COUNT metric."""
    code_text = (
        "df = tables['orders'].copy()\n"
        "result = int(len(df))\n"
        "RESULT = result\n"
        "print(result)\n"
    )
    plan = AnalysisPlan(
        question="How many orders",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="order_id")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="order_id"), operation="count"),
    )
    code = GeneratedCode(
        code_path=Path("proofs/test_count.py"),
        world_id=sample_world.world_id,
        code_content=code_text,
    )

    res = runner.run(sample_world, plan, code)

    assert res.execution_success is True
    assert res.result_value == 4
    assert res.result_type == "int"
    assert res.exit_code == 0


def test_execute_mean_average_metric(sample_world: RepairWorld, runner: SecureRunner):
    """Test safe execution of a MEAN/AVERAGE metric."""
    code_text = (
        "df = tables['orders'].copy()\n"
        "result = float(pd.to_numeric(df['amount']).mean())\n"
        "RESULT = result\n"
        "print(result)\n"
    )
    plan = AnalysisPlan(
        question="Average amount",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="amount")],
        aggregation=AggregationSpec(column=ColumnRef(table="orders", column="amount"), operation="mean"),
    )
    code = GeneratedCode(
        code_path=Path("proofs/test_mean.py"),
        world_id=sample_world.world_id,
        code_content=code_text,
    )

    res = runner.run(sample_world, plan, code)

    assert res.execution_success is True
    assert res.result_value == 250.0
    assert res.result_type == "float"


def test_execute_groupby_metric(sample_world: RepairWorld, runner: SecureRunner):
    """Test safe execution of a group-by aggregation emitting a dictionary."""
    code_text = (
        "df = tables['orders'].copy()\n"
        "df['amount'] = pd.to_numeric(df['amount'])\n"
        "grouped = df.groupby('category')['amount'].sum()\n"
        "result = grouped.to_dict()\n"
        "RESULT = result\n"
        "print(result)\n"
    )
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
    code = GeneratedCode(
        code_path=Path("proofs/test_grp.py"),
        world_id=sample_world.world_id,
        code_content=code_text,
    )

    res = runner.run(sample_world, plan, code)

    assert res.execution_success is True
    assert isinstance(res.result_value, dict)
    assert res.result_value == {"books": 400.0, "electronics": 200.0, "furniture": 400.0}
    assert res.result_type == "dict"


def test_execute_multi_table_join(sample_world: RepairWorld, runner: SecureRunner):
    """Test safe execution joining multiple tables."""
    code_text = (
        "df_ord = tables['orders'].copy()\n"
        "df_cust = tables['customers'].copy()\n"
        "merged = df_ord.merge(df_cust, on='customer_id', how='inner')\n"
        "merged['amount'] = pd.to_numeric(merged['amount'])\n"
        "north_total = float(merged[merged['region'] == 'North']['amount'].sum())\n"
        "RESULT = north_total\n"
        "print(north_total)\n"
    )
    plan = AnalysisPlan(
        question="Total amount in North region",
        status=PlanStatus.READY,
        required_tables=["orders", "customers"],
        required_columns=[
            ColumnRef(table="orders", column="customer_id"),
            ColumnRef(table="orders", column="amount"),
            ColumnRef(table="customers", column="customer_id"),
            ColumnRef(table="customers", column="region"),
        ],
        join_keys=[
            (
                ColumnRef(table="orders", column="customer_id"),
                ColumnRef(table="customers", column="customer_id"),
            )
        ],
    )
    code = GeneratedCode(
        code_path=Path("proofs/test_join.py"),
        world_id=sample_world.world_id,
        code_content=code_text,
    )

    res = runner.run(sample_world, plan, code)

    assert res.execution_success is True
    # C101: 100+300 = 400, C103: 400 -> total 800
    assert res.result_value == 800.0
    assert res.result_type == "float"


# ---------------------------------------------------------------------------
# 2. Failure Cases
# ---------------------------------------------------------------------------

def test_missing_table_fails_gracefully(sample_world: RepairWorld, runner: SecureRunner):
    """Execution cleanly fails when required table does not exist."""
    plan = AnalysisPlan(
        question="Missing table query",
        status=PlanStatus.READY,
        required_tables=["non_existent_inventory"],
        required_columns=[ColumnRef(table="non_existent_inventory", column="item_id")],
    )
    code = GeneratedCode(
        code_path=Path("proofs/test_missing.py"),
        world_id=sample_world.world_id,
        code_content="RESULT = 1",
    )

    res = runner.run(sample_world, plan, code)

    assert res.execution_success is False
    assert res.exit_code != 0
    assert res.error_type == "MissingTableError"
    assert "non_existent_inventory" in (res.execution_error or "")
    assert res.result_value is None


def test_missing_column_fails_gracefully(sample_world: RepairWorld, runner: SecureRunner):
    """Execution cleanly fails when required column does not exist."""
    plan = AnalysisPlan(
        question="Missing column query",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="non_existent_discount")],
    )
    code = GeneratedCode(
        code_path=Path("proofs/test_missing_col.py"),
        world_id=sample_world.world_id,
        code_content="RESULT = 1",
    )

    res = runner.run(sample_world, plan, code)

    assert res.execution_success is False
    assert res.exit_code != 0
    assert res.error_type == "MissingColumnError"
    assert "non_existent_discount" in (res.execution_error or "")
    assert res.result_value is None


def test_runtime_zero_division_captured(sample_world: RepairWorld, runner: SecureRunner):
    """Runtime Python exception (ZeroDivisionError) is captured properly."""
    code_text = (
        "df = tables['orders'].copy()\n"
        "val = 1 / 0\n"
        "RESULT = val\n"
    )
    plan = AnalysisPlan(
        question="Div by zero",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[],
    )
    code = GeneratedCode(
        code_path=Path("proofs/test_zdiv.py"),
        world_id=sample_world.world_id,
        code_content=code_text,
    )

    res = runner.run(sample_world, plan, code)

    assert res.execution_success is False
    assert res.exit_code != 0
    assert res.error_type == "ZeroDivisionError"
    assert "division by zero" in (res.execution_error or "").lower()
    assert res.result_value is None


def test_runtime_assertion_failure_captured(sample_world: RepairWorld, runner: SecureRunner):
    """AssertionError in generated code is captured as failure."""
    code_text = (
        "df = tables['orders'].copy()\n"
        "assert len(df) > 100, 'Orders count is unexpectedly small'\n"
        "RESULT = len(df)\n"
    )
    plan = AnalysisPlan(
        question="Assertion test",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[],
    )
    code = GeneratedCode(
        code_path=Path("proofs/test_assert.py"),
        world_id=sample_world.world_id,
        code_content=code_text,
    )

    res = runner.run(sample_world, plan, code)

    assert res.execution_success is False
    assert res.error_type == "AssertionError"
    assert "Orders count is unexpectedly small" in (res.execution_error or "")
    assert res.result_value is None


def test_missing_result_variable_fails(sample_world: RepairWorld, runner: SecureRunner):
    """Execution completes without setting RESULT or result variable."""
    code_text = (
        "df = tables['orders'].copy()\n"
        "total = df['amount'].count()\n"
        "# forgot RESULT = total\n"
    )
    plan = AnalysisPlan(
        question="Missing result variable",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[],
    )
    code = GeneratedCode(
        code_path=Path("proofs/test_no_result.py"),
        world_id=sample_world.world_id,
        code_content=code_text,
    )

    res = runner.run(sample_world, plan, code)

    assert res.execution_success is False
    assert res.error_type == "ResultMissingError"
    assert res.result_value is None


# ---------------------------------------------------------------------------
# 3. Timeout Enforcement
# ---------------------------------------------------------------------------

def test_timeout_kills_infinite_loop(sample_world: RepairWorld):
    """Hard timeout kills hanging process and returns TimeoutError."""
    hang_code = (
        "df = tables['orders'].copy()\n"
        "while True:\n"
        "    pass\n"
    )
    plan = AnalysisPlan(
        question="Infinite loop",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[],
    )
    code = GeneratedCode(
        code_path=Path("proofs/test_timeout.py"),
        world_id=sample_world.world_id,
        code_content=hang_code,
    )

    # Use a small timeout of 0.8s
    quick_runner = SecureRunner(ExecutionConfig(timeout_seconds=0.8))
    t0 = time.perf_counter()
    res = quick_runner.run(sample_world, plan, code)
    elapsed = time.perf_counter() - t0

    assert res.execution_success is False
    assert res.error_type == "TimeoutError"
    assert res.exit_code == 124
    assert res.result_value is None
    assert elapsed < 4.0  # Finished within reasonable bound


# ---------------------------------------------------------------------------
# 4. Security & Safety Enforcements
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "prohibited_code, expected_violation",
    [
        ("import os\nresult = 1\nRESULT = 1", "os"),
        ("import sys\nresult = 1\nRESULT = 1", "sys"),
        ("import subprocess\nresult = 1\nRESULT = 1", "subprocess"),
        ("import socket\nresult = 1\nRESULT = 1", "socket"),
        ("import requests\nresult = 1\nRESULT = 1", "requests"),
        ("from os import path\nresult = 1\nRESULT = 1", "os"),
        ("eval('1 + 1')\nRESULT = 1", "eval"),
        ("exec('a = 1')\nRESULT = 1", "exec"),
        ("open('secret.txt', 'w')\nRESULT = 1", "open"),
        ("__import__('os')\nRESULT = 1", "__import__"),
        ("g = globals()\nRESULT = 1", "globals"),
        ("l = locals()\nRESULT = 1", "locals"),
        ("getattr(pd, 'read_csv')\nRESULT = 1", "getattr"),
        ("x = ().__class__.__bases__\nRESULT = 1", "__class__"),
    ],
)
def test_security_rejects_unsafe_code(
    sample_world: RepairWorld,
    runner: SecureRunner,
    prohibited_code: str,
    expected_violation: str,
):
    """Ensure static safety checks block dangerous constructs before execution."""
    plan = AnalysisPlan(
        question="Security test",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[],
    )
    code = GeneratedCode(
        code_path=Path("proofs/test_security.py"),
        world_id=sample_world.world_id,
        code_content=prohibited_code,
    )

    res = runner.run(sample_world, plan, code)

    assert res.execution_success is False
    assert res.error_type == "UnsafeCodeError"
    assert res.result_value is None
    assert expected_violation in (res.execution_error or "")


# ---------------------------------------------------------------------------
# 5. Environment Isolation
# ---------------------------------------------------------------------------

def test_environment_isolation_strips_api_keys(monkeypatch: pytest.MonkeyPatch):
    """Verify secrets and API keys are completely stripped from worker environment."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-secret-test-key-12345")
    monkeypatch.setenv("QWEN_MODEL", "qwen-test")
    monkeypatch.setenv("MY_SECRET_TOKEN", "super-secret")
    monkeypatch.setenv("DATABASE_PASSWORD", "pwd123")

    clean_env = _build_clean_environment()

    assert "OPENROUTER_API_KEY" not in clean_env
    assert "QWEN_MODEL" not in clean_env
    assert "MY_SECRET_TOKEN" not in clean_env
    assert "DATABASE_PASSWORD" not in clean_env

    # Critical system variables must remain for Windows Python
    assert "PATH" in clean_env or "path" in clean_env


# ---------------------------------------------------------------------------
# 6. Immutability & Data Isolation
# ---------------------------------------------------------------------------

def test_input_dataframe_immutability(sample_world: RepairWorld, runner: SecureRunner):
    """Mutations inside generated code do not affect the caller's DataFrame."""
    initial_columns = list(sample_world.repaired_tables[0].dataframe.columns)
    initial_row_count = len(sample_world.repaired_tables[0].dataframe)

    # Malicious or buggy code modifying tables['orders'] in place
    code_text = (
        "df = tables['orders']\n"
        "df.drop(columns=['amount'], inplace=True)\n"
        "df['mutated_col'] = 'HACKED'\n"
        "RESULT = 42\n"
    )
    plan = AnalysisPlan(
        question="Mutation test",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[],
    )
    code = GeneratedCode(
        code_path=Path("proofs/test_mut.py"),
        world_id=sample_world.world_id,
        code_content=code_text,
    )

    res = runner.run(sample_world, plan, code)

    assert res.execution_success is True
    assert res.result_value == 42

    # Verify original table in sample_world is completely unchanged
    table_after = sample_world.repaired_tables[0]
    assert list(table_after.dataframe.columns) == initial_columns
    assert len(table_after.dataframe) == initial_row_count
    assert "amount" in table_after.dataframe.columns
    assert "mutated_col" not in table_after.dataframe.columns


def test_repair_world_immutability(sample_world: RepairWorld, runner: SecureRunner):
    """RepairWorld structure and metadata remain unmodified through execution."""
    world_id_before = sample_world.world_id
    tables_count_before = len(sample_world.repaired_tables)

    plan = AnalysisPlan(
        question="World immutability",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[],
    )
    code = GeneratedCode(
        code_path=Path("proofs/test_wimm.py"),
        world_id=sample_world.world_id,
        code_content="RESULT = len(tables['orders'])",
    )

    res = runner.run(sample_world, plan, code)

    assert res.execution_success is True
    assert sample_world.world_id == world_id_before
    assert len(sample_world.repaired_tables) == tables_count_before


# ---------------------------------------------------------------------------
# 7. Determinism & Provenance
# ---------------------------------------------------------------------------

def test_repeated_executions_are_deterministic(sample_world: RepairWorld, runner: SecureRunner):
    """Running identical code and data produces identical outputs and hashes."""
    code_text = (
        "df = tables['orders'].copy()\n"
        "RESULT = float(pd.to_numeric(df['amount']).sum())\n"
    )
    plan = AnalysisPlan(
        question="Determinism test",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[],
    )
    code = GeneratedCode(
        code_path=Path("proofs/test_det.py"),
        world_id=sample_world.world_id,
        code_content=code_text,
    )

    res1 = runner.run(sample_world, plan, code)
    res2 = runner.run(sample_world, plan, code)

    assert res1.execution_success is True
    assert res2.execution_success is True
    assert res1.result_value == res2.result_value
    assert res1.generated_code_hash == res2.generated_code_hash
    assert res1.input_data_hashes == res2.input_data_hashes


def test_different_code_produces_different_code_hash(sample_world: RepairWorld, runner: SecureRunner):
    """Different analysis code scripts produce different code provenance hashes."""
    plan = AnalysisPlan(
        question="Hash test",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[],
    )
    code1 = GeneratedCode(
        code_path=Path("proofs/c1.py"),
        world_id=sample_world.world_id,
        code_content="RESULT = 1\n",
    )
    code2 = GeneratedCode(
        code_path=Path("proofs/c2.py"),
        world_id=sample_world.world_id,
        code_content="RESULT = 2\n",
    )

    res1 = runner.run(sample_world, plan, code1)
    res2 = runner.run(sample_world, plan, code2)

    assert res1.generated_code_hash != res2.generated_code_hash


def test_different_data_produces_different_data_hash(orders_table: LoadedTable, runner: SecureRunner):
    """Different datasets produce different input data hashes."""
    df2 = orders_table.dataframe.copy(deep=True)
    df2.loc[0, "amount"] = "9999.0"

    table2 = LoadedTable(
        source_path=Path("tests/data/orders2.csv"),
        file_type=FileType.CSV,
        table_name="orders",
        column_names=list(df2.columns),
        row_count=len(df2),
        dataframe=df2,
    )

    world1 = RepairWorld(world_id="w1", description="W1", policies=[], repaired_tables=[orders_table])
    world2 = RepairWorld(world_id="w2", description="W2", policies=[], repaired_tables=[table2])

    plan = AnalysisPlan(question="Q", status=PlanStatus.READY, required_tables=["orders"], required_columns=[])
    code = GeneratedCode(code_path=Path("proofs/c.py"), world_id="w1", code_content="RESULT = 1\n")

    res1 = runner.run(world1, plan, code)
    res2 = runner.run(world2, plan, code)

    assert res1.input_data_hashes["orders"] != res2.input_data_hashes["orders"]


# ---------------------------------------------------------------------------
# 8. Output Truncation Limits
# ---------------------------------------------------------------------------

def test_output_truncation_limits(sample_world: RepairWorld):
    """Massive stdout is bounded and flagged with output_truncated = True."""
    flood_code = (
        "for _ in range(500):\n"
        "    print('A' * 200)\n"
        "RESULT = 100\n"
    )
    plan = AnalysisPlan(
        question="Flood stdout",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[],
    )
    code = GeneratedCode(
        code_path=Path("proofs/test_flood.py"),
        world_id=sample_world.world_id,
        code_content=flood_code,
    )

    # Set small max_output_bytes limit of 500 bytes
    bounded_runner = SecureRunner(ExecutionConfig(max_output_bytes=500))
    res = bounded_runner.run(sample_world, plan, code)

    assert res.execution_success is True
    assert res.result_value == 100
    assert res.output_truncated is True
    assert len(res.stdout.encode("utf-8")) <= 600
    assert "[... OUTPUT TRUNCATED ...]" in res.stdout


# ---------------------------------------------------------------------------
# 9. Exception Raising & Convenience Functions
# ---------------------------------------------------------------------------

def test_run_with_raise_on_error(sample_world: RepairWorld, runner: SecureRunner):
    """When raise_on_error=True, exceptions are raised directly."""
    plan_bad_table = AnalysisPlan(
        question="Bad table",
        status=PlanStatus.READY,
        required_tables=["missing_tbl"],
        required_columns=[],
    )
    code_ok = GeneratedCode(
        code_path=Path("proofs/test_ok.py"),
        world_id=sample_world.world_id,
        code_content="RESULT = 1\n",
    )

    with pytest.raises(MissingTableError):
        runner.run(sample_world, plan_bad_table, code_ok, raise_on_error=True)

    plan_bad_col = AnalysisPlan(
        question="Bad col",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[ColumnRef(table="orders", column="non_existent_c")],
    )
    with pytest.raises(MissingColumnError):
        runner.run(sample_world, plan_bad_col, code_ok, raise_on_error=True)

    code_unsafe = GeneratedCode(
        code_path=Path("proofs/test_unsafe.py"),
        world_id=sample_world.world_id,
        code_content="import os\nRESULT = 1\n",
    )
    plan_ok = AnalysisPlan(question="Q", status=PlanStatus.READY, required_tables=["orders"], required_columns=[])
    with pytest.raises(UnsafeCodeError):
        runner.run(sample_world, plan_ok, code_unsafe, raise_on_error=True)


def test_convenience_function_run_analysis(sample_world: RepairWorld):
    """Test global run_analysis() convenience function."""
    code_text = "RESULT = 42\n"
    plan = AnalysisPlan(question="Q", status=PlanStatus.READY, required_tables=["orders"], required_columns=[])
    code = GeneratedCode(
        code_path=Path("proofs/test_conv.py"),
        world_id=sample_world.world_id,
        code_content=code_text,
    )

    res = run_analysis(sample_world, plan, code)
    assert res.execution_success is True
    assert res.result_value == 42
    assert res.exit_code == 0
