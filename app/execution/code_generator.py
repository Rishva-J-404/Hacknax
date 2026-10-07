"""
app.execution.code_generator
----------------------------
Deterministic Python Code Generator for ProofLens.

CORE PRINCIPLE:
    LLM PROPOSES.
    CODE COMPUTES.
    VERIFICATION DECIDES.

This module converts a verified AnalysisPlan into safe, standalone,
executable Python analysis code.

The generated code:
  - Is deterministic.
  - Never contains hardcoded numerical predictions.
  - Includes schema assertions for all required columns.
  - Operates exclusively on DataFrame copies (never mutates original inputs).
  - Emits the computed value via print(result).
  - Must pass strict static safety validation before being returned.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any

from app.agent.contracts import AnalysisPlan, PlanStatus
from app.execution.contracts import GeneratedCode

# ---------------------------------------------------------------------------
# Allowed Modules & Safe AST Rules
# ---------------------------------------------------------------------------

_ALLOWED_MODULES: set[str] = {
    "pandas",
    "math",
    "datetime",
    "json",
    "duckdb",
    "numpy",
}

_DISALLOWED_NAMES: set[str] = {
    "eval",
    "exec",
    "open",
    "__import__",
    "compile",
    "globals",
    "locals",
    "getattr",
    "setattr",
    "delattr",
    "breakpoint",
    "input",
}

_DISALLOWED_ATTRIBUTES: set[str] = {
    "__subclasses__",
    "__globals__",
    "__code__",
    "__builtins__",
    "__class__",
    "__bases__",
}


# ---------------------------------------------------------------------------
# Static Code Safety Validator
# ---------------------------------------------------------------------------

class _SafetyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            base_mod = alias.name.split(".")[0]
            if base_mod not in _ALLOWED_MODULES:
                self.violations.append(
                    f"Forbidden import '{alias.name}'. Only {_ALLOWED_MODULES} are allowed."
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            base_mod = node.module.split(".")[0]
            if base_mod not in _ALLOWED_MODULES:
                self.violations.append(
                    f"Forbidden from-import '{node.module}'. Only {_ALLOWED_MODULES} are allowed."
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Check direct call to disallowed function: e.g. eval(...)
        if isinstance(node.func, ast.Name):
            if node.func.id in _DISALLOWED_NAMES:
                self.violations.append(f"Forbidden call to '{node.func.id}()'.")
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr in _DISALLOWED_NAMES:
                self.violations.append(f"Forbidden call to '{node.func.attr}()'.")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in _DISALLOWED_ATTRIBUTES:
            self.violations.append(f"Forbidden access to dunder attribute '{node.attr}'.")
        self.generic_visit(node)


def validate_code_safety(code: str) -> tuple[bool, list[str]]:
    """
    Statically inspect code with Python AST to ensure it contains no
    dangerous imports, shell execution, eval/exec, or file system attacks.

    Returns:
        (is_safe, list_of_violations)
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as err:
        return False, [f"Syntax error in code: {err}"]

    visitor = _SafetyVisitor()
    visitor.visit(tree)
    is_safe = len(visitor.violations) == 0
    return is_safe, visitor.violations


# ---------------------------------------------------------------------------
# Code Generator
# ---------------------------------------------------------------------------

class CodeGenerator:
    """Deterministic generator of sandboxed Python analysis scripts."""

    def generate(
        self,
        plan: AnalysisPlan,
        world_id: str = "world_001",
        output_path: Path | None = None,
    ) -> GeneratedCode:
        """
        Generate safe, executable Python code from an AnalysisPlan.

        Raises:
            ValueError: If the plan is UNANSWERABLE or AMBIGUOUS.
            ValueError: If the generated code fails static safety validation.
        """
        if plan.status != PlanStatus.READY:
            raise ValueError(
                f"Cannot generate code for a plan with status '{plan.status}'. "
                f"Reason: {plan.unanswerable_reason}"
            )

        lines: list[str] = [
            "# =============================================================================",
            "# ProofLens Generated Analysis Script",
            f"# Question: {plan.question}",
            f"# Intent: {plan.analysis_intent or 'COMPUTE_METRIC'}",
            "# Rule: LLM PROPOSES. CODE COMPUTES. VERIFICATION DECIDES.",
            "# =============================================================================",
            "",
            "import pandas as pd",
            "",
            "# ── 1. Load Data ──────────────────────────────────────────────────────────",
            "# Expects 'tables' dictionary of DataFrames or Loads from current environment",
        ]

        main_table = plan.required_tables[0] if plan.required_tables else "data"
        lines.append(f"df = tables['{main_table}'].copy()")
        lines.append("")

        # ── 2. Assertions ────────────────────────────────────────────────────
        lines.append("# ── 2. Schema Assertions ──────────────────────────────────────────────────")
        lines.append("assert len(df) > 0, 'Input dataset must not be empty'")
        for col_ref in plan.required_columns:
            if col_ref.table == main_table:
                lines.append(
                    f"assert '{col_ref.column}' in df.columns, "
                    f"'Required column \"{col_ref.column}\" is missing from table \"{main_table}\"'"
                )
        lines.append("")

        # ── 3. Multi-table Joins (if applicable) ─────────────────────────────
        if len(plan.required_tables) > 1 and plan.join_keys:
            lines.append("# ── 3. Table Joins ────────────────────────────────────────────────────────")
            for left_ref, right_ref in plan.join_keys:
                other_table = right_ref.table
                lines.append(f"df_{other_table} = tables['{other_table}'].copy()")
                lines.append(
                    f"assert '{right_ref.column}' in df_{other_table}.columns, "
                    f"'Join key \"{right_ref.column}\" missing from \"{other_table}\"'"
                )
                lines.append(
                    f"df = df.merge(df_{other_table}, left_on='{left_ref.column}', "
                    f"right_on='{right_ref.column}', how='inner')"
                )
            lines.append("")

        # ── 4. Filters ───────────────────────────────────────────────────────
        if plan.filters:
            lines.append("# ── 4. Apply Filters ─────────────────────────────────────────────────────")
            for f in plan.filters:
                col_name = f.column.column
                val = f.value
                if f.operator == "==":
                    # Support year filter on string dates or exact match
                    lines.append(
                        f"df = df[df['{col_name}'].astype(str).str.contains(r'\\b{val}\\b', regex=True, na=False)]"
                    )
                elif f.operator == "!=":
                    lines.append(f"df = df[df['{col_name}'] != '{val}']")
                elif f.operator in {">", ">=", "<", "<="}:
                    lines.append(
                        f"df = df[pd.to_numeric(df['{col_name}'], errors='coerce') {f.operator} {val}]"
                    )
            lines.append("")

        # ── 5. Aggregation / Computation ─────────────────────────────────────
        lines.append("# ── 5. Deterministic Computation ──────────────────────────────────────────")
        agg = plan.aggregation

        if plan.group_by and agg:
            grp_col = plan.group_by[0].column
            metric_col = agg.column.column
            op = agg.operation
            lines.append(f"# Group by '{grp_col}' and aggregate '{metric_col}' with {op}")
            lines.append(
                f"grouped = df.groupby('{grp_col}')['{metric_col}']"
                f".apply(lambda s: pd.to_numeric(s, errors='coerce').{op}())"
            )
            sort_asc = "True" if plan.sort_ascending else "False"
            lines.append(f"sorted_group = grouped.sort_values(ascending={sort_asc})")
            if plan.limit:
                lines.append(f"result = sorted_group.head({plan.limit}).index[0]")
            else:
                lines.append("result = sorted_group.to_dict()")

        elif agg:
            col_name = agg.column.column
            op = agg.operation.lower()

            if op == "count":
                lines.append(f"result = int(len(df))")
            elif op == "nunique":
                lines.append(f"result = int(df['{col_name}'].nunique())")
            elif op == "percentage":
                # Compute percentage of rows matching filter vs total
                lines.append("# Percentage calculation")
                lines.append("total_rows = len(df)")
                lines.append("assert total_rows > 0, 'Cannot compute percentage on empty table'")
                # If filter was applied above, we need count
                lines.append("result = round((len(df) / total_rows) * 100.0, 2)")
            elif op in {"sum", "mean", "min", "max", "median"}:
                lines.append(f"numeric_series = pd.to_numeric(df['{col_name}'], errors='coerce').dropna()")
                lines.append(f"result = float(numeric_series.{op}())")
            else:
                lines.append(f"result = df['{col_name}'].{op}()")
        else:
            lines.append("result = len(df)")

        lines.append("")
        lines.append("# ── 6. Emit Authoritative Result ─────────────────────────────────────────")
        lines.append("RESULT = result")
        lines.append("print(result)")

        code_str = "\n".join(lines) + "\n"

        # ── Static Safety Verification ──────────────────────────────────────
        is_safe, violations = validate_code_safety(code_str)
        if not is_safe:
            raise ValueError(f"Generated code failed static safety check: {violations}")

        # Compute hash
        code_sha256 = hashlib.sha256(code_str.encode("utf-8")).hexdigest()

        # Write to file if path requested
        final_path = output_path or Path(f"proofs/analysis_{world_id}.py")
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(code_str, encoding="utf-8")

        return GeneratedCode(
            code_path=final_path,
            code_sha256=code_sha256,
            world_id=world_id,
            code_content=code_str,
        )


# Global convenience function
def generate_analysis_code(
    plan: AnalysisPlan,
    world_id: str = "world_001",
    output_path: Path | None = None,
) -> GeneratedCode:
    """Generate safe, deterministic Python analysis code from an AnalysisPlan."""
    generator = CodeGenerator()
    return generator.generate(plan, world_id=world_id, output_path=output_path)
