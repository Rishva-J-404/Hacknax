"""
app.verification.engine
-----------------------
Deterministic Independent Verification Engine for ProofLens.

CORE PRINCIPLE (PROOFLENS_MASTER_CONTEXT.md §2, §12, §13, §14):
    LLM PROPOSES.
    CODE COMPUTES.
    VERIFICATION DECIDES.

Phase 7 is where verification begins to decide whether an execution result
is trustworthy.

Responsibilities:
  1. Cryptographic Provenance Checks: code hash, table hashes, world_id match.
  2. Schema Checks: required tables and columns exist in the same world.
  3. Independent Calculation Path: DuckDB SQL execution generated purely
     from AnalysisPlan (NEVER asking an LLM for SQL).
  4. Dual-Path Result Comparison: strict absolute and relative tolerances,
     handling numeric, string, dictionary, list, NaN, and infinity values.
  5. Metamorphic Property Suite: testing mathematical invariants under controlled
     data transformations.
  6. Deterministic Status Assignment: VERIFIED, VERIFIED_WITH_ASSUMPTION,
     NOT_VERIFIED, or FAILED. (LLM cannot override).
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.agent.contracts import AnalysisPlan
from app.execution.contracts import ExecutionResult
from app.repair.contracts import RepairWorld
from app.verification.contracts import (
    CheckOutcome,
    VerificationCheck,
    VerificationCheckName,
    VerificationResult,
    VerificationStatus,
)
from app.verification.metamorphic import (
    MetamorphicSuite,
    compare_values,
    execute_duckdb_plan,
)


class VerificationEngine:
    """
    Independent Verification Engine that audits execution results against
    an independent DuckDB computation and metamorphic property tests.
    """

    def __init__(
        self,
        abs_tol: float = 1e-9,
        rel_tol: float = 1e-9,
        allow_nan_match: bool = False,
    ) -> None:
        self.abs_tol = abs_tol
        self.rel_tol = rel_tol
        self.allow_nan_match = allow_nan_match
        self.metamorphic_suite = MetamorphicSuite(abs_tol=abs_tol, rel_tol=rel_tol)

    def verify(
        self,
        world: RepairWorld,
        plan: AnalysisPlan,
        execution_result: ExecutionResult,
        run_metamorphic: bool = True,
    ) -> VerificationResult:
        """
        Verify an ExecutionResult against independent DuckDB computation and metamorphic invariants.
        """
        checks: list[VerificationCheck] = []
        failures: list[str] = []
        warnings: list[str] = []
        prov_details: dict[str, Any] = {}

        # ------------------------------------------------------------------
        # 1. Primary Execution Integrity Check
        # ------------------------------------------------------------------
        if not execution_result.execution_success or execution_result.result_value is None:
            err_msg = execution_result.execution_error or "Execution failed or emitted no result"
            checks.append(
                VerificationCheck(
                    check=VerificationCheckName.PANDAS_PRIMARY,
                    outcome=CheckOutcome.FAIL,
                    expected="execution_success == True with non-None result",
                    actual=f"success={execution_result.execution_success}, result={execution_result.result_value}",
                    detail=err_msg,
                )
            )
            failures.append(f"Primary execution did not succeed: {err_msg}")
            return VerificationResult(
                world_id=world.world_id,
                status=VerificationStatus.NOT_VERIFIED,
                pandas_result=execution_result.result_value,
                primary_result=execution_result.result_value,
                duckdb_result=None,
                independent_result=None,
                results_match=False,
                verification_passed=False,
                checks=checks,
                failures=failures,
                warnings=warnings,
                tolerance_abs=self.abs_tol,
                tolerance_rel=self.rel_tol,
                provenance_verified=False,
                world_policies=[f"{p.issue_type.value}: {p.selected_action}" for p in world.policies],
                world_assumptions=list(world.assumptions),
            )

        checks.append(
            VerificationCheck(
                check=VerificationCheckName.PANDAS_PRIMARY,
                outcome=CheckOutcome.PASS,
                actual=str(execution_result.result_value),
                detail="Primary execution succeeded and emitted authoritative result.",
            )
        )

        # ------------------------------------------------------------------
        # 2. Cryptographic Provenance Checks
        # ------------------------------------------------------------------
        prov_ok = True
        prov_reasons: list[str] = []

        # A. World ID match
        if execution_result.world_id != world.world_id:
            prov_ok = False
            prov_reasons.append(
                f"World ID mismatch: execution was for '{execution_result.world_id}', "
                f"but verification requested for '{world.world_id}'."
            )

        # B. Code hash presence
        if not execution_result.generated_code_hash:
            prov_ok = False
            prov_reasons.append("Missing generated_code_hash in execution result.")

        # C. Input table hashes presence & validity against current world tables
        if not execution_result.input_data_hashes:
            prov_ok = False
            prov_reasons.append("Missing input_data_hashes in execution result.")
        else:
            current_table_hashes: dict[str, str] = {}
            for t in world.repaired_tables:
                csv_bytes = t.dataframe.to_csv(index=False).encode("utf-8")
                tbl_hash = hashlib.sha256(csv_bytes).hexdigest()
                current_table_hashes[t.table_name] = tbl_hash

                recorded_hash = execution_result.input_data_hashes.get(t.table_name)
                if not recorded_hash:
                    prov_ok = False
                    prov_reasons.append(f"Table '{t.table_name}' was not recorded in input_data_hashes.")
                elif recorded_hash != tbl_hash:
                    prov_ok = False
                    prov_reasons.append(
                        f"Data mutation detected on table '{t.table_name}': recorded hash "
                        f"'{recorded_hash}' does not match current hash '{tbl_hash}'."
                    )

            prov_details["current_table_hashes"] = current_table_hashes
            prov_details["recorded_table_hashes"] = execution_result.input_data_hashes

        prov_details["code_hash"] = execution_result.generated_code_hash
        prov_details["world_id"] = execution_result.world_id

        if not prov_ok:
            reason_str = "; ".join(prov_reasons)
            checks.append(
                VerificationCheck(
                    check=VerificationCheckName.PROVENANCE_CHECK,
                    outcome=CheckOutcome.FAIL,
                    expected="Consistent world_id, code_hash, and table hashes",
                    actual="Provenance failure",
                    detail=reason_str,
                )
            )
            failures.append(f"Provenance check failed: {reason_str}")
            return VerificationResult(
                world_id=world.world_id,
                status=VerificationStatus.NOT_VERIFIED,
                pandas_result=execution_result.result_value,
                primary_result=execution_result.result_value,
                duckdb_result=None,
                independent_result=None,
                results_match=None,
                verification_passed=False,
                checks=checks,
                failures=failures,
                warnings=warnings,
                tolerance_abs=self.abs_tol,
                tolerance_rel=self.rel_tol,
                provenance_verified=False,
                provenance_details=prov_details,
                world_policies=[f"{p.issue_type.value}: {p.selected_action}" for p in world.policies],
                world_assumptions=list(world.assumptions),
            )

        checks.append(
            VerificationCheck(
                check=VerificationCheckName.PROVENANCE_CHECK,
                outcome=CheckOutcome.PASS,
                detail="All provenance hashes and world identifiers verified.",
            )
        )

        # ------------------------------------------------------------------
        # 3. Schema Checks
        # ------------------------------------------------------------------
        schema_ok = True
        schema_reasons: list[str] = []
        table_map = {t.table_name: t.dataframe for t in world.repaired_tables}

        for req_tbl in plan.required_tables:
            if req_tbl not in table_map:
                schema_ok = False
                schema_reasons.append(f"Required table '{req_tbl}' missing from world.")

        for col_ref in plan.required_columns:
            if col_ref.table in table_map:
                if col_ref.column not in table_map[col_ref.table].columns:
                    schema_ok = False
                    schema_reasons.append(f"Required column '{col_ref.column}' missing from table '{col_ref.table}'.")

        if not schema_ok:
            reason_str = "; ".join(schema_reasons)
            checks.append(
                VerificationCheck(
                    check=VerificationCheckName.SCHEMA_CHECK,
                    outcome=CheckOutcome.FAIL,
                    expected="All required tables and columns present",
                    actual="Schema mismatch",
                    detail=reason_str,
                )
            )
            failures.append(f"Schema check failed: {reason_str}")
            return VerificationResult(
                world_id=world.world_id,
                status=VerificationStatus.NOT_VERIFIED,
                pandas_result=execution_result.result_value,
                primary_result=execution_result.result_value,
                duckdb_result=None,
                independent_result=None,
                results_match=None,
                verification_passed=False,
                checks=checks,
                failures=failures,
                warnings=warnings,
                tolerance_abs=self.abs_tol,
                tolerance_rel=self.rel_tol,
                provenance_verified=True,
                provenance_details=prov_details,
                world_policies=[f"{p.issue_type.value}: {p.selected_action}" for p in world.policies],
                world_assumptions=list(world.assumptions),
            )

        checks.append(
            VerificationCheck(
                check=VerificationCheckName.SCHEMA_CHECK,
                outcome=CheckOutcome.PASS,
                detail="All required tables and columns verified in target RepairWorld.",
            )
        )

        # ------------------------------------------------------------------
        # 4. Independent DuckDB Secondary Computation Path
        # ------------------------------------------------------------------
        independent_res: Any = None
        try:
            independent_res = execute_duckdb_plan(table_map, plan)
            checks.append(
                VerificationCheck(
                    check=VerificationCheckName.DUCKDB_SECONDARY,
                    outcome=CheckOutcome.PASS,
                    actual=str(independent_res),
                    detail="Independent DuckDB query executed successfully.",
                )
            )
        except Exception as d_err:
            checks.append(
                VerificationCheck(
                    check=VerificationCheckName.DUCKDB_SECONDARY,
                    outcome=CheckOutcome.FAIL,
                    expected="Successful DuckDB evaluation",
                    actual="ERROR",
                    detail=f"DuckDB independent path error: {d_err}",
                )
            )
            failures.append(f"Independent DuckDB calculation failed: {d_err}")
            return VerificationResult(
                world_id=world.world_id,
                status=VerificationStatus.NOT_VERIFIED,
                pandas_result=execution_result.result_value,
                primary_result=execution_result.result_value,
                duckdb_result=None,
                independent_result=None,
                results_match=False,
                verification_passed=False,
                checks=checks,
                failures=failures,
                warnings=warnings,
                tolerance_abs=self.abs_tol,
                tolerance_rel=self.rel_tol,
                provenance_verified=True,
                provenance_details=prov_details,
                world_policies=[f"{p.issue_type.value}: {p.selected_action}" for p in world.policies],
                world_assumptions=list(world.assumptions),
            )

        # ------------------------------------------------------------------
        # 5. Dual-Path Result Comparison (Primary vs Independent)
        # ------------------------------------------------------------------
        primary_val = execution_result.result_value
        matches, comp_msg = compare_values(
            primary_val,
            independent_res,
            abs_tol=self.abs_tol,
            rel_tol=self.rel_tol,
            allow_nan_match=self.allow_nan_match,
        )

        if not matches:
            checks.append(
                VerificationCheck(
                    check=VerificationCheckName.MATCH_CHECK,
                    outcome=CheckOutcome.FAIL,
                    expected=str(independent_res),
                    actual=str(primary_val),
                    detail=f"Results do not match within tolerance: {comp_msg}",
                )
            )
            failures.append(
                f"Dual-path calculation contradiction: Pandas={primary_val!r}, "
                f"DuckDB={independent_res!r}. {comp_msg}"
            )
            return VerificationResult(
                world_id=world.world_id,
                status=VerificationStatus.FAILED,
                pandas_result=primary_val,
                duckdb_result=independent_res,
                primary_result=primary_val,
                independent_result=independent_res,
                results_match=False,
                verification_passed=False,
                checks=checks,
                failures=failures,
                warnings=warnings,
                tolerance_abs=self.abs_tol,
                tolerance_rel=self.rel_tol,
                provenance_verified=True,
                provenance_details=prov_details,
                world_policies=[f"{p.issue_type.value}: {p.selected_action}" for p in world.policies],
                world_assumptions=list(world.assumptions),
            )

        checks.append(
            VerificationCheck(
                check=VerificationCheckName.MATCH_CHECK,
                outcome=CheckOutcome.PASS,
                expected=str(independent_res),
                actual=str(primary_val),
                detail=f"Results match within tolerances: {comp_msg}",
            )
        )

        # ------------------------------------------------------------------
        # 6. Metamorphic Testing Suite
        # ------------------------------------------------------------------
        meta_results = []
        if run_metamorphic:
            meta_results = self.metamorphic_suite.run_all(world, plan, primary_val)
            for m_res in meta_results:
                # Add to formal checks list
                chk_name = getattr(VerificationCheckName, m_res.name, VerificationCheckName.METAMORPHIC_ROW_SHUFFLE)
                checks.append(
                    VerificationCheck(
                        check=chk_name,
                        outcome=m_res.status,
                        expected=m_res.expected,
                        actual=m_res.observed,
                        detail=m_res.details,
                    )
                )
                if m_res.status == CheckOutcome.FAIL:
                    failures.append(
                        f"Metamorphic test '{m_res.name}' failed: expected {m_res.expected}, "
                        f"observed {m_res.observed}. {m_res.details}"
                    )

        if failures:
            return VerificationResult(
                world_id=world.world_id,
                status=VerificationStatus.FAILED,
                pandas_result=primary_val,
                duckdb_result=independent_res,
                primary_result=primary_val,
                independent_result=independent_res,
                results_match=True,
                verification_passed=False,
                checks=checks,
                failures=failures,
                warnings=warnings,
                metamorphic_results=meta_results,
                tolerance_abs=self.abs_tol,
                tolerance_rel=self.rel_tol,
                provenance_verified=True,
                provenance_details=prov_details,
                world_policies=[f"{p.issue_type.value}: {p.selected_action}" for p in world.policies],
                world_assumptions=list(world.assumptions),
            )

        # ------------------------------------------------------------------
        # 7. Final Verification Decision
        # ------------------------------------------------------------------
        final_status = (
            VerificationStatus.VERIFIED_WITH_ASSUMPTION
            if world.assumptions
            else VerificationStatus.VERIFIED
        )

        return VerificationResult(
            world_id=world.world_id,
            status=final_status,
            pandas_result=primary_val,
            duckdb_result=independent_res,
            primary_result=primary_val,
            independent_result=independent_res,
            results_match=True,
            verification_passed=True,
            checks=checks,
            failures=[],
            warnings=warnings,
            metamorphic_results=meta_results,
            tolerance_abs=self.abs_tol,
            tolerance_rel=self.rel_tol,
            provenance_verified=True,
            provenance_details=prov_details,
            world_policies=[f"{p.issue_type.value}: {p.selected_action}" for p in world.policies],
            world_assumptions=list(world.assumptions),
        )


# Global convenience function
def verify_execution(
    world: RepairWorld,
    plan: AnalysisPlan,
    execution_result: ExecutionResult,
    abs_tol: float = 1e-9,
    rel_tol: float = 1e-9,
    run_metamorphic: bool = True,
) -> VerificationResult:
    """
    Convenience function to run independent dual-path verification on an execution result.
    """
    engine = VerificationEngine(abs_tol=abs_tol, rel_tol=rel_tol)
    return engine.verify(world, plan, execution_result, run_metamorphic=run_metamorphic)
