"""
app.verification.metamorphic
----------------------------
Deterministic Metamorphic Property Testing for ProofLens.

CORE PRINCIPLE (PROOFLENS_MASTER_CONTEXT.md §15):
    Test mathematical invariants and properties that MUST hold true
    under controlled data transformations.

No random data modifications. Every transformation is:
  - Explicit
  - Deterministic
  - Mathematically bounded
  - Declares applicability condition, expected relation, and observed relation.
"""

from __future__ import annotations

import math
from typing import Any

import duckdb
import pandas as pd

from app.agent.contracts import AnalysisPlan
from app.repair.contracts import RepairWorld
from app.verification.contracts import CheckOutcome, MetamorphicTestResult


# ---------------------------------------------------------------------------
# Numeric & Value Comparison Helper
# ---------------------------------------------------------------------------

def compare_values(
    val1: Any,
    val2: Any,
    abs_tol: float = 1e-9,
    rel_tol: float = 1e-9,
    allow_nan_match: bool = False,
) -> tuple[bool, str]:
    """
    Deterministically compare two values (primary and secondary).

    Returns:
        (matches: bool, explanation: str)
    """
    if val1 is None or val2 is None:
        if val1 is None and val2 is None:
            return True, "Both values are None"
        return False, f"One value is None: {val1!r} vs {val2!r}"

    # Check for NaN / Inf
    def _is_nan(v: Any) -> bool:
        if isinstance(v, (float, int)) and not isinstance(v, bool):
            return math.isnan(v)
        return False

    def _is_inf(v: Any) -> bool:
        if isinstance(v, (float, int)) and not isinstance(v, bool):
            return math.isinf(v)
        return False

    if _is_nan(val1) or _is_nan(val2):
        if _is_nan(val1) and _is_nan(val2):
            if allow_nan_match:
                return True, "Both values are NaN (allowed by policy)"
            return False, "Both values are NaN; NaN values are treated as undefined/unstable"
        return False, f"NaN mismatch: {val1!r} vs {val2!r}"

    if _is_inf(val1) or _is_inf(val2):
        if _is_inf(val1) and _is_inf(val2):
            matches = (val1 > 0 and val2 > 0) or (val1 < 0 and val2 < 0)
            return matches, f"Infinities compared: {val1} vs {val2}"
        return False, f"Infinity mismatch: {val1} vs {val2}"

    # Numeric comparison
    is_num1 = isinstance(val1, (int, float)) and not isinstance(val1, bool)
    is_num2 = isinstance(val2, (int, float)) and not isinstance(val2, bool)

    if is_num1 and is_num2:
        f1 = float(val1)
        f2 = float(val2)
        diff = abs(f1 - f2)
        matches = math.isclose(f1, f2, rel_tol=rel_tol, abs_tol=abs_tol)
        return matches, f"Numeric diff: {diff} (abs_tol={abs_tol}, rel_tol={rel_tol})"

    # String comparison (case and whitespace normalized)
    if isinstance(val1, str) and isinstance(val2, str):
        matches = val1.strip() == val2.strip()
        return matches, f"String equality: '{val1}' vs '{val2}'"

    # Dictionary comparison (e.g. grouped results)
    if isinstance(val1, dict) and isinstance(val2, dict):
        if set(val1.keys()) != set(val2.keys()):
            return False, f"Dict keys mismatch: {sorted(val1.keys())} vs {sorted(val2.keys())}"
        for k in val1:
            ok, sub_exp = compare_values(val1[k], val2[k], abs_tol=abs_tol, rel_tol=rel_tol, allow_nan_match=allow_nan_match)
            if not ok:
                return False, f"Dict key '{k}' value mismatch: {sub_exp}"
        return True, "All dictionary keys and values match within tolerance"

    # List / Tuple comparison
    if isinstance(val1, (list, tuple)) and isinstance(val2, (list, tuple)):
        if len(val1) != len(val2):
            return False, f"List length mismatch: {len(val1)} vs {len(val2)}"
        for idx, (item1, item2) in enumerate(zip(val1, val2)):
            ok, sub_exp = compare_values(item1, item2, abs_tol=abs_tol, rel_tol=rel_tol, allow_nan_match=allow_nan_match)
            if not ok:
                return False, f"List index {idx} mismatch: {sub_exp}"
        return True, "All sequence items match within tolerance"

    # Direct fallback equality
    return bool(val1 == val2), f"Direct equality: {val1!r} == {val2!r}"


# ---------------------------------------------------------------------------
# Deterministic SQL Execution on In-Memory DuckDB
# ---------------------------------------------------------------------------

def _q(identifier: str) -> str:
    """Safely quote an identifier in DuckDB to handle spaces, dots, hyphens, and keywords."""
    clean = str(identifier).replace('"', '""')
    return f'"{clean}"'


def execute_duckdb_plan(
    tables: dict[str, pd.DataFrame],
    plan: AnalysisPlan,
) -> Any:
    """
    Execute an AnalysisPlan against registered DataFrames using DuckDB SQL.
    Purely deterministic; never uses LLM-generated SQL.
    """
    conn = duckdb.connect(":memory:")
    for tbl_name, df in tables.items():
        conn.register(tbl_name, df)

    main_tbl = plan.required_tables[0] if plan.required_tables else list(tables.keys())[0]

    # Joins
    from_clause = _q(main_tbl)
    if len(plan.required_tables) > 1 and plan.join_keys:
        for left_ref, right_ref in plan.join_keys:
            other_tbl = right_ref.table
            from_clause += f" INNER JOIN {_q(other_tbl)} ON {_q(left_ref.table)}.{_q(left_ref.column)} = {_q(other_tbl)}.{_q(right_ref.column)}"

    # WHERE clauses
    where_parts: list[str] = []
    if plan.filters:
        for f in plan.filters:
            col_sql = f"{_q(f.column.table)}.{_q(f.column.column)}" if len(plan.required_tables) > 1 else _q(f.column.column)
            val = f.value
            op = f.operator
            if op == "==":
                # Support year substring or exact match
                if isinstance(val, (int, float)):
                    where_parts.append(f"CAST({col_sql} AS VARCHAR) LIKE '%{val}%'")
                else:
                    safe_val = str(val).replace("'", "''")
                    where_parts.append(f"CAST({col_sql} AS VARCHAR) = '{safe_val}'")
            elif op == "!=":
                safe_val = str(val).replace("'", "''")
                where_parts.append(f"CAST({col_sql} AS VARCHAR) != '{safe_val}'")
            elif op in {">", ">=", "<", "<="}:
                where_parts.append(f"TRY_CAST({col_sql} AS DOUBLE) {op} {val}")

    where_clause = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""

    # Aggregation & Result formulation
    agg = plan.aggregation

    if plan.group_by and agg:
        grp_col = plan.group_by[0].column
        grp_sql = f"{_q(plan.group_by[0].table)}.{_q(grp_col)}" if len(plan.required_tables) > 1 else _q(grp_col)
        metric_col = agg.column.column
        metric_sql = f"{_q(agg.column.table)}.{_q(metric_col)}" if len(plan.required_tables) > 1 else _q(metric_col)
        op = agg.operation.lower()
        sql_op = "AVG" if op in {"mean", "average"} else op.upper()

        if plan.limit == 1:
            # Top-N item winner query
            sort_dir = "ASC" if plan.sort_ascending else "DESC"
            q = (
                f"SELECT {grp_sql} "
                f"FROM {from_clause}{where_clause} "
                f"GROUP BY {grp_sql} "
                f"ORDER BY {sql_op}(TRY_CAST({metric_sql} AS DOUBLE)) {sort_dir} "
                f"LIMIT 1"
            )
            res = conn.execute(q).fetchone()
            return str(res[0]) if res else None
        else:
            # Full group-by dictionary
            q = (
                f"SELECT {grp_sql}, {sql_op}(TRY_CAST({metric_sql} AS DOUBLE)) "
                f"FROM {from_clause}{where_clause} "
                f"GROUP BY {grp_sql} "
                f"ORDER BY {grp_sql}"
            )
            rows = conn.execute(q).fetchall()
            return {str(r[0]): (float(r[1]) if r[1] is not None else None) for r in rows}

    elif agg:
        col_name = agg.column.column
        col_sql = f"{_q(agg.column.table)}.{_q(col_name)}" if len(plan.required_tables) > 1 else _q(col_name)
        op = agg.operation.lower()

        if op == "count":
            q = f"SELECT COUNT(*) FROM {from_clause}{where_clause}"
            res = conn.execute(q).fetchone()
            return int(res[0]) if res else 0

        elif op in {"nunique", "distinct_count"}:
            q = f"SELECT COUNT(DISTINCT {col_sql}) FROM {from_clause}{where_clause}"
            res = conn.execute(q).fetchone()
            return int(res[0]) if res else 0

        elif op == "percentage":
            # Ratio of filtered rows to total rows in main table
            q = (
                f"SELECT ROUND(COUNT(*) * 100.0 / NULLIF((SELECT COUNT(*) FROM {_q(main_tbl)}), 0), 2) "
                f"FROM {from_clause}{where_clause}"
            )
            res = conn.execute(q).fetchone()
            return float(res[0]) if res and res[0] is not None else 0.0

        elif op in {"sum", "mean", "average", "min", "max"}:
            sql_op = "AVG" if op in {"mean", "average"} else op.upper()
            q = f"SELECT {sql_op}(TRY_CAST({col_sql} AS DOUBLE)) FROM {from_clause}{where_clause}"
            res = conn.execute(q).fetchone()
            if res and res[0] is not None:
                return float(res[0])
            return None

    # Default row count
    q = f"SELECT COUNT(*) FROM {from_clause}{where_clause}"
    res = conn.execute(q).fetchone()
    return int(res[0]) if res else 0


# ---------------------------------------------------------------------------
# Metamorphic Property Suite
# ---------------------------------------------------------------------------

class MetamorphicSuite:
    """
    Executes controlled metamorphic invariant tests on an analysis.
    """

    def __init__(self, abs_tol: float = 1e-9, rel_tol: float = 1e-9) -> None:
        self.abs_tol = abs_tol
        self.rel_tol = rel_tol

    def run_all(
        self,
        world: RepairWorld,
        plan: AnalysisPlan,
        baseline_result: Any,
    ) -> list[MetamorphicTestResult]:
        """Run all seven metamorphic tests."""
        results: list[MetamorphicTestResult] = [
            self.test_row_order_invariance(world, plan, baseline_result),
            self.test_duplicate_injection(world, plan, baseline_result),
            self.test_add_zero_row(world, plan, baseline_result),
            self.test_ratio_duplication(world, plan, baseline_result),
            self.test_filter_monotonicity(world, plan, baseline_result),
            self.test_group_total_consistency(world, plan, baseline_result),
            self.test_top_n_consistency(world, plan, baseline_result),
        ]
        return results

    # 1. Row Order Invariance
    def test_row_order_invariance(
        self,
        world: RepairWorld,
        plan: AnalysisPlan,
        baseline_result: Any,
    ) -> MetamorphicTestResult:
        """Deterministically reverse row order; scalar order-independent metrics must stay identical."""
        agg_op = plan.aggregation.operation.lower() if plan.aggregation else "count"
        is_order_independent = agg_op in {"sum", "count", "mean", "average", "min", "max", "nunique", "percentage"}

        # Inapplicable if query has group_by or limit (ties or slicing order can vary)
        if not is_order_independent or plan.group_by or plan.limit is not None or not isinstance(baseline_result, (int, float)):
            return MetamorphicTestResult(
                name="METAMORPHIC_ROW_SHUFFLE",
                status=CheckOutcome.SKIPPED,
                applicable=False,
                expected="N/A",
                observed="N/A",
                details=f"Metric '{agg_op}' with query shape (group_by={bool(plan.group_by)}, limit={plan.limit}) is not guaranteed order-independent.",
                transformation="None",
            )

        # Reverse rows in each table
        reversed_tables = {
            t.table_name: t.dataframe.iloc[::-1].reset_index(drop=True)
            for t in world.repaired_tables
        }

        try:
            shuffled_res = execute_duckdb_plan(reversed_tables, plan)
            ok, diff_msg = compare_values(baseline_result, shuffled_res, self.abs_tol, self.rel_tol)
            status = CheckOutcome.PASS if ok else CheckOutcome.FAIL
            return MetamorphicTestResult(
                name="METAMORPHIC_ROW_SHUFFLE",
                status=status,
                applicable=True,
                expected=str(baseline_result),
                observed=str(shuffled_res),
                details="Row order reversed. Result must remain equal: " + diff_msg,
                transformation="Reversed rows (iloc[::-1]) on all input tables.",
            )
        except Exception as e:
            return MetamorphicTestResult(
                name="METAMORPHIC_ROW_SHUFFLE",
                status=CheckOutcome.FAIL,
                applicable=True,
                expected=str(baseline_result),
                observed="ERROR",
                details=f"Execution error on reversed rows: {e}",
                transformation="Reversed rows.",
            )

    # 2. Duplicate Injection
    def test_duplicate_injection(
        self,
        world: RepairWorld,
        plan: AnalysisPlan,
        baseline_result: Any,
    ) -> MetamorphicTestResult:
        """Injecting a duplicate row must alter scalar COUNT, DISTINCT COUNT, and SUM predictably."""
        agg_op = plan.aggregation.operation.lower() if plan.aggregation else "count"
        if plan.group_by or plan.limit is not None or not isinstance(baseline_result, (int, float)) or agg_op not in {"count", "nunique", "distinct_count", "sum"}:
            return MetamorphicTestResult(
                name="METAMORPHIC_DUPLICATE_INJECTION",
                status=CheckOutcome.SKIPPED,
                applicable=False,
                expected="N/A",
                observed="N/A",
                details=f"Metric '{agg_op}' with query shape does not have a simple scalar response to duplicate injection.",
                transformation="None",
            )

        main_t = world.repaired_tables[0]
        if len(main_t.dataframe) == 0:
            return MetamorphicTestResult(
                name="METAMORPHIC_DUPLICATE_INJECTION",
                status=CheckOutcome.SKIPPED,
                applicable=False,
                expected="N/A",
                observed="N/A",
                details="Empty table; cannot duplicate row 0.",
                transformation="None",
            )

        # Clone table with row 0 duplicated
        df_mod = pd.concat([main_t.dataframe, main_t.dataframe.iloc[[0]]]).reset_index(drop=True)
        mod_tables = {t.table_name: t.dataframe.copy(deep=True) for t in world.repaired_tables}
        mod_tables[main_t.table_name] = df_mod

        try:
            obs = execute_duckdb_plan(mod_tables, plan)
            if agg_op == "count":
                expected = (baseline_result or 0) + 1
                ok, exp_msg = compare_values(expected, obs, self.abs_tol, self.rel_tol)
            elif agg_op in {"nunique", "distinct_count"}:
                expected = baseline_result
                ok, exp_msg = compare_values(expected, obs, self.abs_tol, self.rel_tol)
            elif agg_op == "sum":
                metric_col = plan.aggregation.column.column
                row_0_val = pd.to_numeric(main_t.dataframe.iloc[0][metric_col], errors="coerce")
                row_0_val = 0.0 if pd.isna(row_0_val) else float(row_0_val)
                expected = (baseline_result or 0.0) + row_0_val
                ok, exp_msg = compare_values(expected, obs, self.abs_tol, self.rel_tol)
            else:
                return MetamorphicTestResult(
                    name="METAMORPHIC_DUPLICATE_INJECTION",
                    status=CheckOutcome.SKIPPED,
                    applicable=False,
                    expected="N/A",
                    observed="N/A",
                    details="Inapplicable metric",
                )

            return MetamorphicTestResult(
                name="METAMORPHIC_DUPLICATE_INJECTION",
                status=CheckOutcome.PASS if ok else CheckOutcome.FAIL,
                applicable=True,
                expected=str(expected),
                observed=str(obs),
                details=f"Duplicate row 0 injected: {exp_msg}",
                transformation="Appended clone of row 0 to main table.",
            )
        except Exception as e:
            return MetamorphicTestResult(
                name="METAMORPHIC_DUPLICATE_INJECTION",
                status=CheckOutcome.FAIL,
                applicable=True,
                expected="predictable",
                observed="ERROR",
                details=f"Error in duplicate injection: {e}",
            )

    # 3. Add Zero Row
    def test_add_zero_row(
        self,
        world: RepairWorld,
        plan: AnalysisPlan,
        baseline_result: Any,
    ) -> MetamorphicTestResult:
        """For SUM, adding a row with metric value 0.0 must leave the total sum unchanged."""
        agg_op = plan.aggregation.operation.lower() if plan.aggregation else "count"
        if plan.group_by or plan.limit is not None or not isinstance(baseline_result, (int, float)) or agg_op != "sum":
            return MetamorphicTestResult(
                name="METAMORPHIC_ADD_ZERO",
                status=CheckOutcome.SKIPPED,
                applicable=False,
                expected="N/A",
                observed="N/A",
                details=f"Metric '{agg_op}' is not a scalar additive sum invariant under zero insertion.",
                transformation="None",
            )

        main_t = world.repaired_tables[0]
        if len(main_t.dataframe) == 0:
            return MetamorphicTestResult(
                name="METAMORPHIC_ADD_ZERO",
                status=CheckOutcome.SKIPPED,
                applicable=False,
                expected="N/A",
                observed="N/A",
                details="Empty table.",
            )

        metric_col = plan.aggregation.column.column
        # Synthesize zero row
        new_row = main_t.dataframe.iloc[0].to_dict()
        new_row[metric_col] = "0.0"
        df_mod = pd.concat([main_t.dataframe, pd.DataFrame([new_row])]).reset_index(drop=True)
        mod_tables = {t.table_name: t.dataframe.copy(deep=True) for t in world.repaired_tables}
        mod_tables[main_t.table_name] = df_mod

        try:
            obs = execute_duckdb_plan(mod_tables, plan)
            ok, diff_msg = compare_values(baseline_result, obs, self.abs_tol, self.rel_tol)
            return MetamorphicTestResult(
                name="METAMORPHIC_ADD_ZERO",
                status=CheckOutcome.PASS if ok else CheckOutcome.FAIL,
                applicable=True,
                expected=str(baseline_result),
                observed=str(obs),
                details=f"Added row with {metric_col}=0.0: {diff_msg}",
                transformation="Appended synthetic row with 0.0 metric value.",
            )
        except Exception as e:
            return MetamorphicTestResult(
                name="METAMORPHIC_ADD_ZERO",
                status=CheckOutcome.FAIL,
                applicable=True,
                expected=str(baseline_result),
                observed="ERROR",
                details=f"Error in zero-row addition: {e}",
            )

    # 4. Ratio Duplication
    def test_ratio_duplication(
        self,
        world: RepairWorld,
        plan: AnalysisPlan,
        baseline_result: Any,
    ) -> MetamorphicTestResult:
        """Duplicating all rows equally must preserve ratio and percentage values."""
        agg_op = plan.aggregation.operation.lower() if plan.aggregation else ""
        if plan.group_by or plan.limit is not None or not isinstance(baseline_result, (int, float)) or agg_op != "percentage":
            return MetamorphicTestResult(
                name="METAMORPHIC_RATIO_DUPLICATION",
                status=CheckOutcome.SKIPPED,
                applicable=False,
                expected="N/A",
                observed="N/A",
                details=f"Metric '{agg_op}' is not a scalar ratio/percentage.",
                transformation="None",
            )

        # Duplicate every row in all tables
        mod_tables = {
            t.table_name: pd.concat([t.dataframe, t.dataframe]).reset_index(drop=True)
            for t in world.repaired_tables
        }

        try:
            obs = execute_duckdb_plan(mod_tables, plan)
            ok, diff_msg = compare_values(baseline_result, obs, self.abs_tol, self.rel_tol)
            return MetamorphicTestResult(
                name="METAMORPHIC_RATIO_DUPLICATION",
                status=CheckOutcome.PASS if ok else CheckOutcome.FAIL,
                applicable=True,
                expected=str(baseline_result),
                observed=str(obs),
                details=f"Duplicated entire dataset: {diff_msg}",
                transformation="Duplicated all rows across all tables (concat([df, df])).",
            )
        except Exception as e:
            return MetamorphicTestResult(
                name="METAMORPHIC_RATIO_DUPLICATION",
                status=CheckOutcome.FAIL,
                applicable=True,
                expected=str(baseline_result),
                observed="ERROR",
                details=f"Error in ratio duplication: {e}",
            )

    # 5. Filter Monotonicity
    def test_filter_monotonicity(
        self,
        world: RepairWorld,
        plan: AnalysisPlan,
        baseline_result: Any,
    ) -> MetamorphicTestResult:
        """Adding a restrictive filter must never increase scalar COUNT or non-negative SUM."""
        agg_op = plan.aggregation.operation.lower() if plan.aggregation else "count"
        if plan.group_by or plan.limit is not None or not isinstance(baseline_result, (int, float)) or agg_op not in {"count", "sum"}:
            return MetamorphicTestResult(
                name="METAMORPHIC_FILTER_MONOTONICITY",
                status=CheckOutcome.SKIPPED,
                applicable=False,
                expected="N/A",
                observed="N/A",
                details=f"Metric '{agg_op}' is not a scalar count or non-negative sum.",
                transformation="None",
            )

        main_df = world.repaired_tables[0].dataframe
        if len(main_df) == 0:
            return MetamorphicTestResult(
                name="METAMORPHIC_FILTER_MONOTONICITY",
                status=CheckOutcome.SKIPPED,
                applicable=False,
                expected="N/A",
                observed="N/A",
                details="Empty dataset.",
            )

        # Restrict table by keeping only first 50% of rows
        half_n = max(1, len(main_df) // 2)
        restricted_tables = {
            t.table_name: t.dataframe.iloc[:half_n].reset_index(drop=True)
            for t in world.repaired_tables
        }

        try:
            obs = execute_duckdb_plan(restricted_tables, plan)
            if obs is not None:
                # Restricted subset must be <= full baseline
                is_monotonic = float(obs) <= float(baseline_result) + self.abs_tol
                status = CheckOutcome.PASS if is_monotonic else CheckOutcome.FAIL
                return MetamorphicTestResult(
                    name="METAMORPHIC_FILTER_MONOTONICITY",
                    status=status,
                    applicable=True,
                    expected=f"<= {baseline_result}",
                    observed=str(obs),
                    details=f"Subset (first {half_n} rows) resulted in {obs} <= {baseline_result}",
                    transformation="Restricted dataset to first half of rows.",
                )
            return MetamorphicTestResult(
                name="METAMORPHIC_FILTER_MONOTONICITY",
                status=CheckOutcome.SKIPPED,
                applicable=False,
                expected="N/A",
                observed="None",
                details="Could not evaluate restricted subset.",
            )
        except Exception as e:
            return MetamorphicTestResult(
                name="METAMORPHIC_FILTER_MONOTONICITY",
                status=CheckOutcome.FAIL,
                applicable=True,
                expected=f"<= {baseline_result}",
                observed="ERROR",
                details=f"Error evaluating monotonicity: {e}",
            )

    # 6. Group Total Consistency
    def test_group_total_consistency(
        self,
        world: RepairWorld,
        plan: AnalysisPlan,
        baseline_result: Any,
    ) -> MetamorphicTestResult:
        """For grouped SUM without limit, sum(group_results) must equal overall table SUM."""
        agg_op = plan.aggregation.operation.lower() if plan.aggregation else ""
        if not plan.group_by or agg_op != "sum" or plan.limit is not None or not isinstance(baseline_result, dict):
            return MetamorphicTestResult(
                name="METAMORPHIC_GROUP_TOTAL",
                status=CheckOutcome.SKIPPED,
                applicable=False,
                expected="N/A",
                observed="N/A",
                details="Not a full grouped SUM without limit.",
                transformation="None",
            )

        # Sum of all group values in baseline_result
        grouped_sum = sum(float(v) for v in baseline_result.values() if v is not None)

        # Calculate overall sum query by dropping group_by
        plan_no_group = plan.model_copy(update={"group_by": []})
        tables = {t.table_name: t.dataframe for t in world.repaired_tables}

        try:
            overall_sum = execute_duckdb_plan(tables, plan_no_group)
            ok, diff_msg = compare_values(grouped_sum, overall_sum, self.abs_tol, self.rel_tol)
            return MetamorphicTestResult(
                name="METAMORPHIC_GROUP_TOTAL",
                status=CheckOutcome.PASS if ok else CheckOutcome.FAIL,
                applicable=True,
                expected=str(overall_sum),
                observed=str(grouped_sum),
                details=f"Sum of group sums vs overall sum: {diff_msg}",
                transformation="Compared sum(group_dict.values()) against ungrouped SUM query.",
            )
        except Exception as e:
            return MetamorphicTestResult(
                name="METAMORPHIC_GROUP_TOTAL",
                status=CheckOutcome.FAIL,
                applicable=True,
                expected="consistent",
                observed="ERROR",
                details=f"Error comparing group total: {e}",
            )

    # 7. Top-N Consistency
    def test_top_n_consistency(
        self,
        world: RepairWorld,
        plan: AnalysisPlan,
        baseline_result: Any,
    ) -> MetamorphicTestResult:
        """For Top-1 winner query, the returned item must equal the group key with maximum sum."""
        if not plan.group_by or plan.limit != 1:
            return MetamorphicTestResult(
                name="METAMORPHIC_TOP_N",
                status=CheckOutcome.SKIPPED,
                applicable=False,
                expected="N/A",
                observed="N/A",
                details="Query is not a Top-1 winner selection.",
                transformation="None",
            )

        # Query all groups to independently find the winner
        plan_all_groups = plan.model_copy(update={"limit": None})
        tables = {t.table_name: t.dataframe for t in world.repaired_tables}

        try:
            all_groups = execute_duckdb_plan(tables, plan_all_groups)
            if isinstance(all_groups, dict) and all_groups:
                sort_asc = bool(plan.sort_ascending)
                sorted_items = sorted(all_groups.items(), key=lambda x: (x[1] if x[1] is not None else 0), reverse=not sort_asc)
                expected_winner = sorted_items[0][0]
                ok = str(baseline_result) == str(expected_winner)
                return MetamorphicTestResult(
                    name="METAMORPHIC_TOP_N",
                    status=CheckOutcome.PASS if ok else CheckOutcome.FAIL,
                    applicable=True,
                    expected=str(expected_winner),
                    observed=str(baseline_result),
                    details=f"Independent group ranking confirms '{expected_winner}' is the top item.",
                    transformation="Computed full group distribution to verify top ranking.",
                )
            return MetamorphicTestResult(
                name="METAMORPHIC_TOP_N",
                status=CheckOutcome.SKIPPED,
                applicable=False,
                expected="N/A",
                observed="N/A",
                details="No groups returned.",
            )
        except Exception as e:
            return MetamorphicTestResult(
                name="METAMORPHIC_TOP_N",
                status=CheckOutcome.FAIL,
                applicable=True,
                expected="top item",
                observed="ERROR",
                details=f"Error evaluating Top-N consistency: {e}",
            )
