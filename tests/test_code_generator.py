"""
tests/test_code_generator.py
----------------------------
Tests for Phase 5: Deterministic Code Generator and Safety Validator in ProofLens.

Verifies:
1. Generated code contains actual computation.
2. Generated code does not contain hardcoded final answer.
3. Generated code is deterministic.
4. Generated code contains required-column assertions.
5. Dangerous imports are rejected by static validator.
6. eval/exec are rejected.
7. Network access (requests, socket, urllib) is rejected.
8. Original data is protected by design (df.copy() used).
9. Same plan produces identical code.
10. Unanswerable or Ambiguous plan raises ValueError on code generation.
11. Multi-table join generated code includes merge logic.
12. Dunder attribute attacks are rejected.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.contracts import (
    AggregationSpec,
    AnalysisPlan,
    ColumnRef,
    FilterSpec,
    PlanStatus,
    UnanswerableReason,
)
from app.execution import (
    CodeGenerator,
    GeneratedCode,
    generate_analysis_code,
    validate_code_safety,
)


# ---------------------------------------------------------------------------
# Fixture Plan
# ---------------------------------------------------------------------------

def _make_ready_plan() -> AnalysisPlan:
    col = ColumnRef(table="orders", column="revenue")
    return AnalysisPlan(
        question="What is total revenue?",
        status=PlanStatus.READY,
        required_tables=["orders"],
        required_columns=[col],
        aggregation=AggregationSpec(column=col, operation="sum"),
        analysis_intent="SUM_REVENUE",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_generated_code_contains_actual_computation():
    plan = _make_ready_plan()
    gen_code = generate_analysis_code(plan)
    code = gen_code.code_content
    assert code is not None
    assert "numeric_series.sum()" in code or ".sum()" in code
    assert "print(result)" in code


def test_generated_code_does_not_contain_hardcoded_answer():
    plan = _make_ready_plan()
    gen_code = generate_analysis_code(plan)
    code = gen_code.code_content
    assert code is not None
    # Result must be calculated dynamically, not hardcoded like result = 12345
    lines = [line.strip() for line in code.splitlines()]
    result_lines = [l for l in lines if l.startswith("result =")]
    for rl in result_lines:
        assert not rl.replace("result =", "").strip().isdigit()


def test_generated_code_is_deterministic():
    plan = _make_ready_plan()
    gen1 = generate_analysis_code(plan)
    gen2 = generate_analysis_code(plan)
    assert gen1.code_content == gen2.code_content
    assert gen1.code_sha256 == gen2.code_sha256


def test_generated_code_contains_column_assertions():
    plan = _make_ready_plan()
    gen = generate_analysis_code(plan)
    code = gen.code_content
    assert code is not None
    assert "assert 'revenue' in df.columns" in code
    assert "assert len(df) > 0" in code


def test_dangerous_imports_rejected():
    code_with_os = "import os\nresult = 1\nprint(result)"
    is_safe, violations = validate_code_safety(code_with_os)
    assert is_safe is False
    assert any("os" in v for v in violations)

    code_with_subprocess = "import subprocess\nprint(1)"
    is_safe, violations = validate_code_safety(code_with_subprocess)
    assert is_safe is False
    assert any("subprocess" in v for v in violations)


def test_eval_and_exec_rejected():
    code_with_eval = "x = eval('1 + 1')\nprint(x)"
    is_safe, violations = validate_code_safety(code_with_eval)
    assert is_safe is False
    assert any("eval" in v for v in violations)

    code_with_exec = "exec('result = 10')\nprint(result)"
    is_safe, violations = validate_code_safety(code_with_exec)
    assert is_safe is False
    assert any("exec" in v for v in violations)


def test_network_access_rejected():
    code_requests = "import requests\nprint(1)"
    is_safe, violations = validate_code_safety(code_requests)
    assert is_safe is False
    assert any("requests" in v for v in violations)

    code_socket = "import socket\nprint(1)"
    is_safe, violations = validate_code_safety(code_socket)
    assert is_safe is False
    assert any("socket" in v for v in violations)


def test_dunder_attribute_access_rejected():
    code_dunder = "x = ().__class__.__subclasses__()\nprint(x)"
    is_safe, violations = validate_code_safety(code_dunder)
    assert is_safe is False
    assert any("__subclasses__" in v or "__class__" in v for v in violations)


def test_original_data_not_modified_by_design():
    # Verify generated script explicitly creates a copy
    plan = _make_ready_plan()
    gen = generate_analysis_code(plan)
    code = gen.code_content
    assert code is not None
    assert ".copy()" in code


def test_unanswerable_plan_rejected_by_generator():
    plan = AnalysisPlan(
        question="Impossible",
        status=PlanStatus.UNANSWERABLE,
        unanswerable_reason=UnanswerableReason.MISSING_REQUIRED_FIELD,
    )
    generator = CodeGenerator()
    with pytest.raises(ValueError) as exc_info:
        generator.generate(plan)
    assert "status 'PlanStatus.UNANSWERABLE'" in str(exc_info.value) or "UNANSWERABLE" in str(exc_info.value)


def test_ambiguous_plan_rejected_by_generator():
    plan = AnalysisPlan(
        question="Ambiguous date",
        status=PlanStatus.AMBIGUOUS,
        unanswerable_reason=UnanswerableReason.AMBIGUOUS_DATE,
    )
    generator = CodeGenerator()
    with pytest.raises(ValueError):
        generator.generate(plan)


def test_multi_table_join_code_generation():
    col_rev = ColumnRef(table="orders", column="revenue")
    col_cid1 = ColumnRef(table="orders", column="customer_id")
    col_cid2 = ColumnRef(table="customers", column="customer_id")

    plan = AnalysisPlan(
        question="Total revenue by customer",
        status=PlanStatus.READY,
        required_tables=["orders", "customers"],
        required_columns=[col_rev, col_cid1, col_cid2],
        join_keys=[(col_cid1, col_cid2)],
        aggregation=AggregationSpec(column=col_rev, operation="sum"),
    )

    gen = generate_analysis_code(plan)
    code = gen.code_content
    assert code is not None
    assert "df.merge(" in code
    assert "left_on='customer_id'" in code
    assert "right_on='customer_id'" in code
