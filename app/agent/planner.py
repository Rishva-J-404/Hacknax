"""
app.agent.planner
-----------------
Deterministic Analysis Planner for ProofLens.

CORE PRINCIPLE:
    LLM PROPOSES.
    CODE COMPUTES.
    VERIFICATION DECIDES.

The Planner is responsible for translating the user's natural language
question into a structured, executable AnalysisPlan.

It enforces ANSWERABILITY FIRST:
  - If a required metric/column is missing -> UNANSWERABLE
  - If multiple candidate columns exist -> AMBIGUOUS
  - If date format is unresolved and ambiguous -> AMBIGUOUS
  - If join relationship is unclear -> UNANSWERABLE
  - If predictive/unsupported operation requested -> UNANSWERABLE

This planner operates deterministically and offline without requiring an LLM.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import re
from typing import Any

from app.agent.contracts import (
    AggregationSpec,
    AmbiguityFlag,
    AnalysisPlan,
    ColumnRef,
    FilterSpec,
    PlanStatus,
    UnanswerableReason,
)
from app.audit.contracts import DataQualityLedger, IssueType
from app.ingestion.contracts import LoadedTable

# ---------------------------------------------------------------------------
# Planner Backend Interface
# ---------------------------------------------------------------------------

class PlannerBackend(ABC):
    """Abstract interface for planning backends (Deterministic or LLM)."""

    @abstractmethod
    def plan(
        self,
        question: str,
        tables: list[LoadedTable],
        ledger: DataQualityLedger | None = None,
    ) -> AnalysisPlan:
        """Produce an AnalysisPlan from question and loaded tables."""
        pass


# ---------------------------------------------------------------------------
# Deterministic Planner Implementation
# ---------------------------------------------------------------------------

class DeterministicPlanner(PlannerBackend):
    """
    Rule-based, pattern-matching analytical planner.
    Provides offline, deterministic planning for common analytical queries.
    """

    def plan(
        self,
        question: str,
        tables: list[LoadedTable],
        ledger: DataQualityLedger | None = None,
    ) -> AnalysisPlan:
        q_raw = question.strip()
        q_lower = q_raw.lower()

        # ── 1. Check Data Sources ───────────────────────────────────────────
        if not tables:
            return AnalysisPlan(
                question=q_raw,
                status=PlanStatus.UNANSWERABLE,
                unanswerable_reason=UnanswerableReason.NO_DATA_SOURCES,
                unanswerable_evidence="No tables or data sources were provided for analysis.",
            )

        # ── 2. Check for Unsupported Predictive / ML Operations ─────────────
        unsupported_keywords = [
            "predict",
            "forecast",
            "machine learning",
            "cluster",
            "sentiment",
            "classify",
            "neural network",
            "extrapolate",
        ]
        if any(kw in q_lower for kw in unsupported_keywords):
            return AnalysisPlan(
                question=q_raw,
                status=PlanStatus.UNANSWERABLE,
                unanswerable_reason=UnanswerableReason.UNSUPPORTED_OPERATION,
                unanswerable_evidence="Predictive, forecasting, and ML operations are not supported.",
            )

        # ── 3. Build Column and Table Index ─────────────────────────────────
        # Map: lowercase column name -> list of (table_name, actual_col_name)
        col_index: dict[str, list[tuple[str, str]]] = {}
        for t in tables:
            for c in t.column_names:
                col_index.setdefault(c.lower(), []).append((t.table_name, c))

        # ── 4. Check Date Ambiguity from Audit Ledger ───────────────────────
        # If question involves dates, check if audit flagged AMBIGUOUS_DATE_FORMAT
        date_pattern = re.search(r"\b(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})\b", q_raw)
        has_date_intent = bool(date_pattern) or any(
            w in q_lower for w in ["date", "month", "year", "2024", "2025", "2026", "january", "february"]
        )

        if ledger and has_date_intent:
            ambig_date_issues = [
                i for i in ledger.all_issues if i.issue_type == IssueType.AMBIGUOUS_DATE_FORMAT
            ]
            if ambig_date_issues and date_pattern:
                ambig_sample = ambig_date_issues[0].evidence.get("sample_ambiguous_dates", ["date"])
                return AnalysisPlan(
                    question=q_raw,
                    status=PlanStatus.AMBIGUOUS,
                    unanswerable_reason=UnanswerableReason.AMBIGUOUS_DATE,
                    unanswerable_evidence=(
                        f"Question queries date '{date_pattern.group(1)}', but the dataset "
                        f"contains ambiguous date format (DD/MM vs MM/DD) without explicit resolution."
                    ),
                    ambiguity_flags=[
                        AmbiguityFlag(
                            description="Date format is ambiguous in audit ledger (DD/MM vs MM/DD).",
                            example=str(ambig_sample[0] if ambig_sample else date_pattern.group(1)),
                        )
                    ],
                )

        # ── 5. Recognize Intent & Target Metrics ─────────────────────────────

        # A. Count Rows / Transactions
        if any(q_lower.startswith(prefix) for prefix in ["how many transactions", "how many rows", "number of transactions", "count of transactions", "total transactions", "count rows"]):
            target_table = tables[0].table_name
            # If a specific table matches
            for t in tables:
                if t.table_name.lower() in q_lower:
                    target_table = t.table_name
                    break
            # Pick primary key or first column
            first_col = tables[0].column_names[0]
            col_ref = ColumnRef(table=target_table, column=first_col)
            return AnalysisPlan(
                question=q_raw,
                status=PlanStatus.READY,
                required_tables=[target_table],
                required_columns=[col_ref],
                aggregation=AggregationSpec(column=col_ref, operation="count"),
                analysis_intent="COUNT_ROWS",
            )

        # B. Distinct / Unique Count
        distinct_match = re.search(r"(?:how many unique|how many distinct|distinct count of|number of unique)\s+([a-zA-Z_]+)", q_lower)
        if distinct_match or "unique" in q_lower or "distinct" in q_lower:
            entity = distinct_match.group(1).strip() if distinct_match else ""
            entity_stem = entity[:-1] if entity.endswith("s") else entity
            target_col_ref = None

            # Look for entity_id or entity
            for t in tables:
                for c in t.column_names:
                    c_low = c.lower()
                    if entity and (
                        entity in c_low
                        or entity_stem in c_low
                        or c_low.startswith(entity_stem)
                        or f"{entity_stem}_id" in c_low
                    ):
                        target_col_ref = ColumnRef(table=t.table_name, column=c)
                        break
                    elif not entity and ("_id" in c_low or c_low == "id"):
                        target_col_ref = ColumnRef(table=t.table_name, column=c)
                        break
                if target_col_ref:
                    break

            if target_col_ref:
                return AnalysisPlan(
                    question=q_raw,
                    status=PlanStatus.READY,
                    required_tables=[target_col_ref.table],
                    required_columns=[target_col_ref],
                    aggregation=AggregationSpec(column=target_col_ref, operation="nunique"),
                    analysis_intent="DISTINCT_COUNT",
                )

        # C. Simple Percentage / Success Rate
        if "percentage" in q_lower or "percent" in q_lower or "rate" in q_lower:
            # Look for filter condition, e.g., 'successful' or 'completed'
            target_table = tables[0].table_name
            status_col = None
            for c in tables[0].column_names:
                if "status" in c.lower() or "result" in c.lower() or "success" in c.lower():
                    status_col = c
                    break

            if status_col:
                col_ref = ColumnRef(table=target_table, column=status_col)
                # Find target value
                target_val = "successful"
                if "successful" in q_lower or "success" in q_lower:
                    target_val = "successful"
                elif "failed" in q_lower:
                    target_val = "failed"

                return AnalysisPlan(
                    question=q_raw,
                    status=PlanStatus.READY,
                    required_tables=[target_table],
                    required_columns=[col_ref],
                    filters=[FilterSpec(column=col_ref, operator="==", value=target_val)],
                    aggregation=AggregationSpec(column=col_ref, operation="percentage"),
                    analysis_intent="PERCENTAGE",
                )

        # D. Highest / Top N / Lowest
        is_top = any(w in q_lower for w in ["highest", "top", "best", "max sales", "highest sales", "highest revenue"])
        is_bottom = any(w in q_lower for w in ["lowest", "bottom", "worst"])

        if is_top or is_bottom:
            # Check if group by is involved (e.g. "which product had the highest sales")
            group_col_ref = None
            metric_col_ref = None
            target_table = tables[0].table_name

            for c in tables[0].column_names:
                c_low = c.lower()
                if any(w in c_low for w in ["product", "item", "customer", "category", "region", "name"]):
                    group_col_ref = ColumnRef(table=target_table, column=c)
                if any(w in c_low for w in ["revenue", "sales", "amount", "price", "total", "score", "val"]):
                    metric_col_ref = ColumnRef(table=target_table, column=c)

            if group_col_ref and metric_col_ref:
                return AnalysisPlan(
                    question=q_raw,
                    status=PlanStatus.READY,
                    required_tables=[target_table],
                    required_columns=[group_col_ref, metric_col_ref],
                    aggregation=AggregationSpec(column=metric_col_ref, operation="sum"),
                    group_by=[group_col_ref],
                    sort_by=metric_col_ref,
                    sort_ascending=bool(is_bottom),
                    limit=1,
                    analysis_intent="TOP_N" if is_top else "BOTTOM_N",
                )
            elif metric_col_ref and ("value" in q_lower or "what is the highest" in q_lower or "what is the maximum" in q_lower):
                op = "max" if is_top else "min"
                return AnalysisPlan(
                    question=q_raw,
                    status=PlanStatus.READY,
                    required_tables=[target_table],
                    required_columns=[metric_col_ref],
                    aggregation=AggregationSpec(column=metric_col_ref, operation=op),
                    analysis_intent=op.upper(),
                )

        # E. Min / Max standalone
        if "minimum" in q_lower or "min value" in q_lower:
            for t in tables:
                for c in t.column_names:
                    if any(w in c.lower() for w in ["revenue", "sales", "amount", "price", "val", "score"]):
                        col_ref = ColumnRef(table=t.table_name, column=c)
                        return AnalysisPlan(
                            question=q_raw,
                            status=PlanStatus.READY,
                            required_tables=[t.table_name],
                            required_columns=[col_ref],
                            aggregation=AggregationSpec(column=col_ref, operation="min"),
                            analysis_intent="MIN",
                        )

        if "maximum" in q_lower or "max value" in q_lower:
            for t in tables:
                for c in t.column_names:
                    if any(w in c.lower() for w in ["revenue", "sales", "amount", "price", "val", "score"]):
                        col_ref = ColumnRef(table=t.table_name, column=c)
                        return AnalysisPlan(
                            question=q_raw,
                            status=PlanStatus.READY,
                            required_tables=[t.table_name],
                            required_columns=[col_ref],
                            aggregation=AggregationSpec(column=col_ref, operation="max"),
                            analysis_intent="MAX",
                        )

        # F. Average / Mean / Sum
        is_avg = any(w in q_lower for w in ["average", "mean", "avg"])
        is_sum = any(w in q_lower for w in ["total", "sum", "overall"]) or (not is_avg and "what is the" in q_lower)

        # Check required metric name
        metric_keywords = ["revenue", "sales", "amount", "profit", "price", "cost", "score"]
        requested_metric = None
        for m in metric_keywords:
            if m in q_lower:
                requested_metric = m
                break

        if not requested_metric:
            # Fallback search for any known numerical column
            for t in tables:
                for c in t.column_names:
                    if any(m in c.lower() for m in metric_keywords):
                        requested_metric = m
                        break
                if requested_metric:
                    break

        if not requested_metric:
            return AnalysisPlan(
                question=q_raw,
                status=PlanStatus.UNANSWERABLE,
                unanswerable_reason=UnanswerableReason.MISSING_REQUIRED_FIELD,
                unanswerable_evidence="Could not identify any computable metric or column in the question.",
            )

        # ── 6. Check for Ambiguous Columns (Multiple Candidate Columns) ─────
        # E.g., question says "sales", but table has both "sales" and "revenue"
        candidate_columns: list[ColumnRef] = []
        for t in tables:
            for c in t.column_names:
                c_low = c.lower()
                if requested_metric in c_low:
                    candidate_columns.append(ColumnRef(table=t.table_name, column=c))

        # Check if question says "sales" and table has both "sales" and "revenue"
        if ("sales" in q_lower or "revenue" in q_lower) and len(tables) == 1:
            matching_financial = [
                ColumnRef(table=tables[0].table_name, column=c)
                for c in tables[0].column_names
                if c.lower() in ["sales", "revenue", "gross_sales", "net_sales", "amount"]
            ]
            if len(matching_financial) > 1 and "sales" in q_lower and "revenue" in [c.column.lower() for c in matching_financial]:
                return AnalysisPlan(
                    question=q_raw,
                    status=PlanStatus.AMBIGUOUS,
                    unanswerable_reason=UnanswerableReason.AMBIGUOUS_COLUMN,
                    unanswerable_evidence=(
                        f"Multiple candidate columns found for metric: "
                        f"{[c.column for c in matching_financial]}."
                    ),
                    ambiguity_flags=[
                        AmbiguityFlag(
                            description="Multiple columns could represent the requested sales/revenue metric.",
                            affected_columns=matching_financial,
                        )
                    ],
                )

        if len(candidate_columns) == 0:
            return AnalysisPlan(
                question=q_raw,
                status=PlanStatus.UNANSWERABLE,
                unanswerable_reason=UnanswerableReason.MISSING_REQUIRED_FIELD,
                unanswerable_evidence=f"Question asks for '{requested_metric}', but no matching column was found.",
            )

        target_col_ref = candidate_columns[0]
        target_table = target_col_ref.table

        # ── 7. Check for Date / Year Filters ─────────────────────────────────
        filters: list[FilterSpec] = []
        year_match = re.search(r"\b(20\d{2}|19\d{2})\b", q_raw)
        if year_match:
            year_val = int(year_match.group(1))
            # Find date column
            date_col = None
            for c in tables[0].column_names:
                if any(w in c.lower() for w in ["date", "time", "year", "created"]):
                    date_col = c
                    break

            if not date_col:
                return AnalysisPlan(
                    question=q_raw,
                    status=PlanStatus.UNANSWERABLE,
                    unanswerable_reason=UnanswerableReason.MISSING_REQUIRED_FIELD,
                    unanswerable_evidence=f"Question filters by year {year_val}, but no date column exists in table '{target_table}'.",
                )

            date_col_ref = ColumnRef(table=target_table, column=date_col)
            filters.append(
                FilterSpec(
                    column=date_col_ref,
                    operator="==",
                    value=year_val,
                )
            )

        # ── 8. Multi-Table Join Resolution (if question mentions entities in other tables)
        join_keys: list[tuple[ColumnRef, ColumnRef]] = []
        req_tables = [target_table]
        req_cols = [target_col_ref]
        if filters:
            req_cols.extend(f.column for f in filters)

        if len(tables) > 1:
            for other_t in tables:
                if other_t.table_name == target_table:
                    continue
                # If question explicitly mentions other table name or entity in other table
                if other_t.table_name.lower() in q_lower:
                    # Look for explicit common key
                    common_keys = set(tables[0].column_names).intersection(set(other_t.column_names))
                    valid_join_key = None
                    for k in common_keys:
                        if "_id" in k.lower() or k.lower() == "id":
                            valid_join_key = k
                            break

                    if valid_join_key:
                        join_keys.append((
                            ColumnRef(table=target_table, column=valid_join_key),
                            ColumnRef(table=other_t.table_name, column=valid_join_key),
                        ))
                        req_tables.append(other_t.table_name)
                    else:
                        # Ambiguous / unclear join relationship
                        return AnalysisPlan(
                            question=q_raw,
                            status=PlanStatus.UNANSWERABLE,
                            unanswerable_reason=UnanswerableReason.INSUFFICIENT_INFORMATION,
                            unanswerable_evidence=(
                                f"Cannot join tables '{target_table}' and '{other_t.table_name}': "
                                f"no common identifier key found."
                            ),
                        )

        # ── 9. Final Plan Construction ───────────────────────────────────────
        op = "mean" if is_avg else "sum"
        return AnalysisPlan(
            question=q_raw,
            status=PlanStatus.READY,
            required_tables=req_tables,
            required_columns=req_cols,
            filters=filters,
            aggregation=AggregationSpec(column=target_col_ref, operation=op),
            join_keys=join_keys,
            analysis_intent=f"{op.upper()}_{target_col_ref.column.upper()}",
            assumptions=["Calculated over all valid matching rows."],
        )
