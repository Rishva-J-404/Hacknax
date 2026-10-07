"""
app.agent.qwen_planner
----------------------
Structured Qwen Analysis Planner for ProofLens.

CORE PRINCIPLE (PROOFLENS_MASTER_CONTEXT.md §2, §9):
    LLM PROPOSES.
    CODE COMPUTES.
    VERIFICATION DECIDES.

RESPONSIBILITIES:
    - Calls OpenRouter (or mock client) with structured prompt and strict prompt defense.
    - Prompts the LLM with user question, schema, and compact audit ledger summary.
    - Demands structured JSON matching the AnalysisPlan schema.
    - NEVER asks the LLM to write executable Python code or compute answers.
    - Strictly validates the response through PlanValidator.
    - Preserves and raises ambiguity flags when data audit contains unresolved issues.
"""

from __future__ import annotations

import json
import logging
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
from app.agent.plan_validator import PlanValidator
from app.agent.planner import PlannerBackend
from app.agent.prompt_defense import build_planner_prompt
from app.agent.qwen_client import LLMClient, OpenRouterQwenClient
from app.audit.contracts import DataQualityLedger, IssueType
from app.ingestion.contracts import LoadedTable

logger = logging.getLogger(__name__)


class QwenPlanner(PlannerBackend):
    """
    LLM-powered planner using Qwen via OpenRouter (or mock client).
    Produces strictly structured, schema-grounded AnalysisPlans.
    """

    def __init__(
        self,
        client: LLMClient | None = None,
        validator: PlanValidator | None = None,
    ) -> None:
        self.client = client or OpenRouterQwenClient()
        self.validator = validator or PlanValidator()

    def plan(
        self,
        question: str,
        tables: list[LoadedTable],
        ledger: DataQualityLedger | None = None,
    ) -> AnalysisPlan:
        """
        Query Qwen for a structured AnalysisPlan, validate it, and return the plan.
        """
        # 1. Quick check for empty data sources
        if not tables:
            return AnalysisPlan(
                question=question,
                status=PlanStatus.UNANSWERABLE,
                unanswerable_reason=UnanswerableReason.NO_DATA_SOURCES,
                unanswerable_evidence="No tables or data sources were provided for analysis.",
            )

        # 2. Extract schema and compact audit summary
        available_tables = [t.table_name for t in tables]
        table_columns = {t.table_name: list(t.column_names) for t in tables}
        audit_summary = self._build_compact_audit_summary(ledger)

        # 3. Build safe chat prompt with prompt-injection defense
        messages = build_planner_prompt(
            question=question,
            available_tables=available_tables,
            table_columns=table_columns,
            audit_summary=audit_summary,
        )

        # 4. Invoke LLM Client
        try:
            raw_response = self.client.generate(messages)
        except Exception as exc:
            # Safe failure: never crash the pipeline and never fabricate an answer
            clean_err = str(exc)
            logger.warning("LLM client failure during planning: %s", clean_err)
            return AnalysisPlan(
                question=question,
                status=PlanStatus.UNANSWERABLE,
                unanswerable_reason=UnanswerableReason.INSUFFICIENT_INFORMATION,
                unanswerable_evidence=f"LLM planner unavailable: {clean_err}",
            )

        # 5. Parse and deserialize response
        plan_dict, parse_err = self._parse_json_response(raw_response)
        if parse_err or not plan_dict:
            return AnalysisPlan(
                question=question,
                status=PlanStatus.UNANSWERABLE,
                unanswerable_reason=UnanswerableReason.INSUFFICIENT_INFORMATION,
                unanswerable_evidence=f"LLM returned malformed plan response: {parse_err}",
            )

        # 6. Reject if model returned a computed answer instead of a plan
        if "answer" in plan_dict or "result" in plan_dict:
            # Check if it tried to output an answer directly
            if not any(k in plan_dict for k in ("required_tables", "required_columns", "aggregation")):
                return AnalysisPlan(
                    question=question,
                    status=PlanStatus.UNANSWERABLE,
                    unanswerable_reason=UnanswerableReason.UNSUPPORTED_OPERATION,
                    unanswerable_evidence="Model attempted to output a direct numerical answer instead of an AnalysisPlan.",
                )

        # 7. Construct AnalysisPlan Pydantic model
        try:
            # Ensure question matches original verbatim
            plan_dict["question"] = question
            plan = self._build_analysis_plan_from_dict(plan_dict)
        except Exception as pydantic_err:
            return AnalysisPlan(
                question=question,
                status=PlanStatus.UNANSWERABLE,
                unanswerable_reason=UnanswerableReason.INSUFFICIENT_INFORMATION,
                unanswerable_evidence=f"Failed to parse AnalysisPlan schema: {pydantic_err}",
            )

        # 8. Check for Audit-related ambiguities
        plan = self._apply_audit_ambiguity_checks(plan, ledger)

        # 9. Authoritative Plan Validation
        val_res = self.validator.validate(plan, tables)
        if not val_res.is_valid:
            return AnalysisPlan(
                question=question,
                status=PlanStatus.UNANSWERABLE,
                unanswerable_reason=val_res.rejection_reason or UnanswerableReason.MISSING_REQUIRED_FIELD,
                unanswerable_evidence="; ".join(val_res.errors),
            )

        return val_res.validated_plan or plan

    def _build_compact_audit_summary(
        self, ledger: DataQualityLedger | None
    ) -> dict[str, Any]:
        """Convert DataQualityLedger into a compact, human-readable summary for the prompt."""
        if not ledger:
            return {}
        summary: dict[str, Any] = {}
        for profile in ledger.table_profiles:
            tbl_issues: list[str] = []
            for issue in profile.issues:
                desc = issue.description or str(issue.issue_type.value)
                tbl_issues.append(desc)
            summary[profile.source] = {"issues": tbl_issues, "row_count": profile.row_count}

        all_issues = getattr(ledger, "all_issues", None) or getattr(ledger, "issues", [])
        for issue in all_issues:
            tbl = getattr(issue, "affected_source", "unknown")
            if tbl not in summary:
                summary[tbl] = {"issues": []}
            desc = issue.description or str(issue.issue_type.value)
            if desc not in summary[tbl]["issues"]:
                summary[tbl]["issues"].append(desc)

        return summary

    def _parse_json_response(self, text: str) -> tuple[dict[str, Any] | None, str | None]:
        """Safely parse JSON response from LLM, stripping any markdown fences if present."""
        text = text.strip()
        # Strip markdown fences ```json ... ```
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data, None
            return None, "Response is not a JSON object."
        except Exception as err:
            return None, str(err)

    def _build_analysis_plan_from_dict(self, d: dict[str, Any]) -> AnalysisPlan:
        """Construct AnalysisPlan with structured nested models."""
        # Normalize status enum
        status_str = str(d.get("status", "READY")).upper()
        try:
            status = PlanStatus(status_str)
        except ValueError:
            status = PlanStatus.READY

        # Parse required columns
        req_cols: list[ColumnRef] = []
        for c in d.get("required_columns", []):
            if isinstance(c, dict):
                req_cols.append(ColumnRef(table=c.get("table", ""), column=c.get("column", "")))
            elif isinstance(c, str) and "." in c:
                parts = c.split(".", 1)
                req_cols.append(ColumnRef(table=parts[0], column=parts[1]))

        # Parse aggregation
        agg: AggregationSpec | None = None
        raw_agg = d.get("aggregation")
        if isinstance(raw_agg, dict):
            c_info = raw_agg.get("column")
            if isinstance(c_info, dict):
                col_ref = ColumnRef(table=c_info.get("table", ""), column=c_info.get("column", ""))
            elif isinstance(c_info, str) and "." in c_info:
                p = c_info.split(".", 1)
                col_ref = ColumnRef(table=p[0], column=p[1])
            else:
                col_ref = req_cols[0] if req_cols else ColumnRef(table="data", column="val")

            agg = AggregationSpec(
                column=col_ref,
                operation=str(raw_agg.get("operation", "sum")).lower(),
                unit=raw_agg.get("unit"),
            )

        # Parse filters
        filters: list[FilterSpec] = []
        for f in d.get("filters", []):
            if isinstance(f, dict):
                c_info = f.get("column")
                if isinstance(c_info, dict):
                    col_ref = ColumnRef(table=c_info.get("table", ""), column=c_info.get("column", ""))
                else:
                    col_ref = ColumnRef(table="data", column=str(c_info))
                filters.append(
                    FilterSpec(
                        column=col_ref,
                        operator=str(f.get("operator", "==")),
                        value=f.get("value"),
                    )
                )

        return AnalysisPlan(
            question=d.get("question", ""),
            status=status,
            required_tables=d.get("required_tables", []),
            required_columns=req_cols,
            aggregation=agg,
            filters=filters,
            join_keys=[],
            group_by=[],
            analysis_intent=d.get("analysis_intent"),
            assumptions=d.get("assumptions", []),
            ambiguity_flags=[],
            unanswerable_reason=d.get("unanswerable_reason"),
            unanswerable_evidence=d.get("unanswerable_evidence"),
        )

    def _apply_audit_ambiguity_checks(
        self, plan: AnalysisPlan, ledger: DataQualityLedger | None
    ) -> AnalysisPlan:
        """If plan touches columns/tables with unresolved critical ambiguities, mark AMBIGUOUS."""
        if not ledger or plan.status != PlanStatus.READY:
            return plan

        all_issues = getattr(ledger, "all_issues", None) or getattr(ledger, "issues", [])
        for issue in all_issues:
            src = getattr(issue, "affected_source", getattr(issue, "table", ""))
            cols = getattr(issue, "affected_columns", [getattr(issue, "column", "")])
            if issue.issue_type == IssueType.AMBIGUOUS_DATE_FORMAT:
                # Check if date filter or date column is read in plan
                if any(
                    "date" in c.column.lower()
                    for c in plan.required_columns
                    if c.table == src
                ) or any(
                    "date" in f.column.column.lower()
                    for f in plan.filters
                    if f.column.table == src
                ):
                    plan.status = PlanStatus.AMBIGUOUS
                    plan.ambiguity_flags.append(
                        AmbiguityFlag(
                            description="Unresolved date format ambiguity (DD/MM vs MM/DD) in referenced date column.",
                            affected_columns=[ColumnRef(table=src, column=cols[0] if cols else "date")],
                        )
                    )

            elif issue.issue_type == IssueType.MIXED_CURRENCIES:
                if plan.aggregation and plan.aggregation.column.table == src:
                    if cols and plan.aggregation.column.column in cols:
                        plan.status = PlanStatus.AMBIGUOUS
                        plan.ambiguity_flags.append(
                            AmbiguityFlag(
                                description="Referenced aggregation column contains mixed currencies without exchange rates.",
                                affected_columns=[ColumnRef(table=src, column=cols[0])],
                            )
                        )

        return plan
