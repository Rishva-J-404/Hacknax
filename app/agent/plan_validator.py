"""
app.agent.plan_validator
------------------------
Strict, Authoritative Sanitizer and Validator for LLM-Proposed Analysis Plans.

CORE PRINCIPLES (PROOFLENS_MASTER_CONTEXT.md §2, §5, §8, §9):
    LLM PROPOSES.
    CODE COMPUTES.
    VERIFICATION DECIDES.

The validator is authoritative:
    - If the LLM invents a column, table, or aggregation: REJECT. Never guess.
    - If the LLM injects code, SQL, file paths, or URLs: REJECT.
    - A malformed or ungrounded LLM plan must NEVER silently be repaired.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.agent.contracts import (
    AggregationSpec,
    AnalysisPlan,
    ColumnRef,
    PlanStatus,
    UnanswerableReason,
)
from app.ingestion.contracts import LoadedTable

# Supported operations whitelist
_SUPPORTED_AGGREGATIONS = {"sum", "mean", "count", "min", "max", "median"}

# Dangerous patterns in plan text fields (code/SQL injection defense)
_CODE_INJECTION_PATTERN = re.compile(
    r"\b(import|exec|eval|__import__|os\.|sys\.|subprocess|open\s*\(|lambda\s+:)\b",
    re.IGNORECASE,
)
_SQL_INJECTION_PATTERN = re.compile(
    r"\b(DROP\s+TABLE|DELETE\s+FROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|ALTER\s+TABLE|UNION\s+SELECT|--\s*)\b",
    re.IGNORECASE,
)
_URL_PATTERN = re.compile(r"https?://|ftp://", re.IGNORECASE)
_FILE_PATH_PATTERN = re.compile(r"[a-zA-Z]:\\|/(etc|usr|bin|tmp|var)/|\.\./|\.py$|\.sh$", re.IGNORECASE)


class PlanValidationResult(BaseModel):
    """Result of plan validation containing authoritative pass/fail and error log."""

    is_valid: bool = Field(..., description="True if plan satisfies all strict ground rules.")
    errors: list[str] = Field(default_factory=list, description="List of validation errors found.")
    validated_plan: AnalysisPlan | None = Field(default=None, description="The approved plan or None if invalid.")
    rejection_reason: UnanswerableReason | None = Field(default=None, description="Reason code if rejected.")


class PlanValidator:
    """Authoritative validator verifying LLM-generated plans against physical schemas."""

    def __init__(self, allowed_aggregations: set[str] | None = None) -> None:
        self.allowed_aggregations = allowed_aggregations or _SUPPORTED_AGGREGATIONS

    def validate(
        self,
        plan: AnalysisPlan,
        tables: list[LoadedTable],
    ) -> PlanValidationResult:
        """
        Validate an LLM-proposed AnalysisPlan against actual loaded tables.
        Returns PlanValidationResult.
        """
        errors: list[str] = []

        # Build schema maps from loaded tables
        table_names = {t.table_name for t in tables}
        column_map: dict[str, set[str]] = {t.table_name: set(t.column_names) for t in tables}

        # ── 1. If Plan is explicitly UNANSWERABLE or AMBIGUOUS ──────────────────
        if plan.status in (PlanStatus.UNANSWERABLE, PlanStatus.NEEDS_CLARIFICATION, PlanStatus.AMBIGUOUS):
            # Still verify no malicious code or SQL injected into text fields
            sec_errs = self._check_security_violations(plan)
            if sec_errs:
                return PlanValidationResult(
                    is_valid=False,
                    errors=sec_errs,
                    rejection_reason=UnanswerableReason.UNSUPPORTED_OPERATION,
                )
            return PlanValidationResult(is_valid=True, validated_plan=plan)

        # ── 2. Security & Injection Checks ──────────────────────────────────────
        sec_errs = self._check_security_violations(plan)
        if sec_errs:
            errors.extend(sec_errs)
            return PlanValidationResult(
                is_valid=False,
                errors=errors,
                rejection_reason=UnanswerableReason.UNSUPPORTED_OPERATION,
            )

        # ── 3. Table Existence ──────────────────────────────────────────────────
        if not plan.required_tables:
            errors.append("Plan specifies no required tables.")
        else:
            for req_tbl in plan.required_tables:
                if req_tbl not in table_names:
                    errors.append(
                        f"Nonexistent table '{req_tbl}' referenced. Available tables: {sorted(table_names)}"
                    )

        # ── 4. Required Columns Existence ───────────────────────────────────────
        for col_ref in plan.required_columns:
            if col_ref.table not in table_names:
                errors.append(f"Column '{col_ref.column}' references unknown table '{col_ref.table}'.")
            elif col_ref.column not in column_map.get(col_ref.table, set()):
                errors.append(
                    f"Nonexistent column '{col_ref.column}' referenced in table '{col_ref.table}'. "
                    f"Available columns: {sorted(column_map.get(col_ref.table, set()))}"
                )

        # ── 5. Filter Columns Existence ─────────────────────────────────────────
        for f in plan.filters:
            col_ref = f.column
            if col_ref.table not in table_names:
                errors.append(f"Filter references unknown table '{col_ref.table}'.")
            elif col_ref.column not in column_map.get(col_ref.table, set()):
                errors.append(
                    f"Filter references nonexistent column '{col_ref.column}' in table '{col_ref.table}'."
                )

        # ── 6. Aggregation Column & Operation ───────────────────────────────────
        if plan.aggregation:
            agg_col = plan.aggregation.column
            if agg_col.table not in table_names:
                errors.append(f"Aggregation references unknown table '{agg_col.table}'.")
            elif agg_col.column not in column_map.get(agg_col.table, set()):
                errors.append(
                    f"Aggregation references nonexistent column '{agg_col.column}' in table '{agg_col.table}'."
                )

            op_lower = plan.aggregation.operation.lower()
            if op_lower not in self.allowed_aggregations:
                errors.append(
                    f"Unsupported aggregation operation '{plan.aggregation.operation}'. "
                    f"Supported: {sorted(self.allowed_aggregations)}"
                )
        elif not plan.group_by:
            # If no aggregation and no group by, might be missing aggregation
            errors.append("Plan specifies neither an aggregation nor a grouping operation.")

        # ── 7. Group By Columns ─────────────────────────────────────────────────
        for g_col in plan.group_by:
            if g_col.table not in table_names:
                errors.append(f"Group-by references unknown table '{g_col.table}'.")
            elif g_col.column not in column_map.get(g_col.table, set()):
                errors.append(
                    f"Group-by references nonexistent column '{g_col.column}' in table '{g_col.table}'."
                )

        # ── 8. Sort By Column ───────────────────────────────────────────────────
        if plan.sort_by:
            if plan.sort_by.table not in table_names:
                errors.append(f"Sort-by references unknown table '{plan.sort_by.table}'.")
            elif plan.sort_by.column not in column_map.get(plan.sort_by.table, set()):
                errors.append(
                    f"Sort-by references nonexistent column '{plan.sort_by.column}' in table '{plan.sort_by.table}'."
                )

        # ── 9. Join Keys ────────────────────────────────────────────────────────
        for left_col, right_col in plan.join_keys:
            if left_col.table not in table_names:
                errors.append(f"Join key references unknown left table '{left_col.table}'.")
            elif left_col.column not in column_map.get(left_col.table, set()):
                errors.append(
                    f"Join key references nonexistent column '{left_col.column}' in '{left_col.table}'."
                )

            if right_col.table not in table_names:
                errors.append(f"Join key references unknown right table '{right_col.table}'.")
            elif right_col.column not in column_map.get(right_col.table, set()):
                errors.append(
                    f"Join key references nonexistent column '{right_col.column}' in '{right_col.table}'."
                )

        if errors:
            # Determine appropriate rejection reason
            rejection_reason = UnanswerableReason.MISSING_REQUIRED_FIELD
            if any("table" in e for e in errors):
                rejection_reason = UnanswerableReason.MISSING_TABLE
            elif any("aggregation" in e for e in errors):
                rejection_reason = UnanswerableReason.UNSUPPORTED_OPERATION

            return PlanValidationResult(
                is_valid=False,
                errors=errors,
                rejection_reason=rejection_reason,
            )

        return PlanValidationResult(is_valid=True, validated_plan=plan)

    def _check_security_violations(self, plan: AnalysisPlan) -> list[str]:
        """Check all text fields in plan for injected code, SQL, paths, or URLs."""
        violations: list[str] = []
        text_fields = [
            plan.question,
            plan.analysis_intent or "",
            plan.unanswerable_evidence or "",
            plan.planner_notes or "",
        ]
        text_fields.extend(plan.assumptions)
        text_fields.extend([f.description for f in plan.ambiguity_flags])
        for tbl in plan.required_tables:
            text_fields.append(tbl)
        for col in plan.required_columns:
            text_fields.append(col.column)

        for text in text_fields:
            if not text:
                continue
            if _CODE_INJECTION_PATTERN.search(text):
                violations.append(f"Prohibited executable code pattern detected in plan: '{text[:50]}'")
            if _SQL_INJECTION_PATTERN.search(text):
                violations.append(f"Prohibited arbitrary SQL pattern detected in plan: '{text[:50]}'")
            if _URL_PATTERN.search(text):
                violations.append(f"External URL source forbidden in plan: '{text[:50]}'")
            if _FILE_PATH_PATTERN.search(text):
                violations.append(f"Arbitrary system file path forbidden in plan: '{text[:50]}'")

        return violations
