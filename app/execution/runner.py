"""
app.execution.runner
--------------------
Secure Execution Runner for ProofLens.

CORE PRINCIPLES (PROOFLENS_MASTER_CONTEXT.md §2, §10, §11, §23):
    LLM PROPOSES.
    CODE COMPUTES.
    VERIFICATION DECIDES.

PHASE 6 RESPONSIBILITY:
    Safely execute GeneratedCode against a RepairWorld's repaired datasets.
    Capture stdout, stderr, execution time, and authoritative result.
    Compute cryptographic provenance hashes for code and input tables.

SECURITY ARCHITECTURE:
    1. Static AST inspection (validate_code_safety) rejects dangerous imports,
       eval/exec, open(), and reflection before process launch.
    2. Isolated subprocess worker (app/execution/worker.py) runs in a separate
       process with restricted builtins and no secrets in environment.
    3. Input DataFrames are deep-copied and isolated from host process memory.
    4. Hard execution timeout kills hung processes (infinite loops).
    5. Output size limits prevent memory exhaustion.
    6. Authoritative result is extracted from the computed RESULT variable or stdout.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from app.agent.contracts import AnalysisPlan
from app.execution.code_generator import validate_code_safety
from app.execution.contracts import ExecutionResult, GeneratedCode
from app.repair.contracts import RepairWorld

# ---------------------------------------------------------------------------
# Configuration & Custom Exceptions
# ---------------------------------------------------------------------------

class ExecutionConfig(BaseModel):
    """Configuration options for secure sandboxed execution."""

    timeout_seconds: float = Field(
        default=5.0,
        ge=0.1,
        description="Maximum seconds before the execution subprocess is forcefully terminated.",
    )
    max_output_bytes: int = Field(
        default=100_000,
        ge=100,
        description="Maximum bytes of stdout or stderr captured before truncation.",
    )
    python_executable: str = Field(
        default_factory=lambda: sys.executable,
        description="Path to Python interpreter to launch worker subprocess.",
    )


class ExecutionError(Exception):
    """Base exception for execution runner errors."""
    pass


class UnsafeCodeError(ExecutionError):
    """Raised when generated code contains prohibited constructs."""
    pass


class MissingTableError(ExecutionError):
    """Raised when an expected table is not present in the RepairWorld."""
    pass


class MissingColumnError(ExecutionError):
    """Raised when an expected column is not present in the table."""
    pass


class ExecutionTimeoutError(ExecutionError):
    """Raised when code execution exceeds the configured timeout."""
    pass


class ResultMissingError(ExecutionError):
    """Raised when code executes successfully but fails to define RESULT."""
    pass


# ---------------------------------------------------------------------------
# Environment Sanitization
# ---------------------------------------------------------------------------

_SAFE_ENV_VARS: set[str] = {
    "SYSTEMROOT",
    "PATH",
    "PYTHONPATH",
    "TEMP",
    "TMP",
    "WINDIR",
    "APPDATA",
    "LOCALAPPDATA",
    "USERPROFILE",
    "LANG",
    "LC_ALL",
}

_FORBIDDEN_ENV_SUBSTRINGS: tuple[str, ...] = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "OPENROUTER",
    "API",
)


def _build_clean_environment() -> dict[str, str]:
    """
    Construct a minimal, safe environment for worker subprocesses.
    Guarantees that sensitive secrets (e.g. OPENROUTER_API_KEY) are NEVER exposed.
    """
    clean_env: dict[str, str] = {}
    for k, v in os.environ.items():
        k_upper = k.upper()
        if k_upper in _SAFE_ENV_VARS:
            # Extra safety check: reject if name contains secret indicator
            if not any(sub in k_upper for sub in _FORBIDDEN_ENV_SUBSTRINGS):
                clean_env[k] = v

    # Explicit purge of all known secret names
    for key in list(clean_env.keys()):
        k_upper = key.upper()
        if any(sub in k_upper for sub in ("OPENROUTER", "KEY", "TOKEN", "SECRET")):
            clean_env.pop(key, None)

    # Ensure repository root is on PYTHONPATH so module resolution succeeds
    repo_root = str(Path(__file__).resolve().parent.parent.parent)
    curr_pythonpath = clean_env.get("PYTHONPATH", "")
    if curr_pythonpath:
        clean_env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{curr_pythonpath}"
    else:
        clean_env["PYTHONPATH"] = repo_root

    return clean_env


# ---------------------------------------------------------------------------
# Secure Runner Implementation
# ---------------------------------------------------------------------------

class SecureRunner:
    """
    Sandboxed runner that securely executes generated analysis scripts against
    repaired dataset worlds.
    """

    def __init__(self, config: ExecutionConfig | None = None) -> None:
        self.default_config = config or ExecutionConfig()

    def run(
        self,
        world: RepairWorld,
        plan: AnalysisPlan,
        code: GeneratedCode,
        config: ExecutionConfig | None = None,
        raise_on_error: bool = False,
    ) -> ExecutionResult:
        """
        Execute generated code against world's repaired tables inside an isolated subprocess.

        Returns an ExecutionResult with authoritative values, execution metadata,
        and provenance hashes. Never mutates input datasets.
        """
        cfg = config or self.default_config

        # 1. Retrieve code content
        if code.code_content is not None:
            code_str = code.code_content
        elif code.code_path and Path(code.code_path).exists():
            code_str = Path(code.code_path).read_text(encoding="utf-8")
        else:
            code_str = ""

        # 2. Compute code provenance hash
        code_hash = hashlib.sha256(code_str.encode("utf-8")).hexdigest()

        # 3. Build table map, row counts, and table hashes (deep copies only)
        table_map: dict[str, pd.DataFrame] = {}
        input_hashes: dict[str, str] = {}
        row_counts: dict[str, int] = {}
        table_names: list[str] = []

        for lt in world.repaired_tables:
            table_names.append(lt.table_name)
            # Guarantee input immutability: deep copy DataFrame
            df_copy = lt.dataframe.copy(deep=True)
            table_map[lt.table_name] = df_copy
            row_counts[lt.table_name] = len(df_copy)
            # Deterministic CSV bytes hash of DataFrame contents
            table_csv_bytes = df_copy.to_csv(index=False).encode("utf-8")
            input_hashes[lt.table_name] = hashlib.sha256(table_csv_bytes).hexdigest()

        # 4. Static Code Safety Verification (AST layer)
        is_safe, violations = validate_code_safety(code_str)
        if not is_safe:
            err_msg = f"Static code safety check failed: {'; '.join(violations)}"
            if raise_on_error:
                raise UnsafeCodeError(err_msg)
            return ExecutionResult(
                world_id=world.world_id,
                code_path=code.code_path,
                stdout="",
                stderr=err_msg,
                exit_code=1,
                execution_success=False,
                error_type="UnsafeCodeError",
                execution_error=err_msg,
                result_value=None,
                result_type=None,
                duration_seconds=0.0,
                execution_time_ms=0.0,
                table_names=table_names,
                row_counts=row_counts,
                generated_code_hash=code_hash,
                input_data_hashes=input_hashes,
                output_truncated=False,
            )

        # 5. Schema Pre-check: Required Tables exist in world
        for req_tbl in plan.required_tables:
            if req_tbl not in table_map:
                err_msg = (
                    f"Required table '{req_tbl}' is missing from RepairWorld '{world.world_id}'. "
                    f"Available tables: {table_names}"
                )
                if raise_on_error:
                    raise MissingTableError(err_msg)
                return ExecutionResult(
                    world_id=world.world_id,
                    code_path=code.code_path,
                    stdout="",
                    stderr=err_msg,
                    exit_code=1,
                    execution_success=False,
                    error_type="MissingTableError",
                    execution_error=err_msg,
                    result_value=None,
                    result_type=None,
                    duration_seconds=0.0,
                    execution_time_ms=0.0,
                    table_names=table_names,
                    row_counts=row_counts,
                    generated_code_hash=code_hash,
                    input_data_hashes=input_hashes,
                    output_truncated=False,
                )

        # 6. Schema Pre-check: Required Columns exist in respective tables
        for col_ref in plan.required_columns:
            if col_ref.table in table_map:
                df = table_map[col_ref.table]
                if col_ref.column not in df.columns:
                    err_msg = (
                        f"Required column '{col_ref.column}' is missing from table '{col_ref.table}'. "
                        f"Available columns: {list(df.columns)}"
                    )
                    if raise_on_error:
                        raise MissingColumnError(err_msg)
                    return ExecutionResult(
                        world_id=world.world_id,
                        code_path=code.code_path,
                        stdout="",
                        stderr=err_msg,
                        exit_code=1,
                        execution_success=False,
                        error_type="MissingColumnError",
                        execution_error=err_msg,
                        result_value=None,
                        result_type=None,
                        duration_seconds=0.0,
                        execution_time_ms=0.0,
                        table_names=table_names,
                        row_counts=row_counts,
                        generated_code_hash=code_hash,
                        input_data_hashes=input_hashes,
                        output_truncated=False,
                    )

        # 7. Prepare serialized table payload for worker subprocess
        serialized_tables: dict[str, Any] = {}
        for tbl_name, df in table_map.items():
            serialized_tables[tbl_name] = {
                "columns": list(df.columns),
                "records": df.to_dict(orient="records"),
            }

        worker_payload = {
            "code": code_str,
            "tables": serialized_tables,
            "max_output_bytes": cfg.max_output_bytes,
        }
        payload_bytes = json.dumps(worker_payload, default=str).encode("utf-8")

        # 8. Setup isolated environment and worker path
        worker_script = Path(__file__).resolve().parent / "worker.py"
        clean_env = _build_clean_environment()

        # 9. Launch worker subprocess with hard timeout
        start_time = time.perf_counter()
        stdout_raw: str = ""
        stderr_raw: str = ""
        exit_code: int = 1

        try:
            proc = subprocess.Popen(
                [cfg.python_executable, str(worker_script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=clean_env,
            )

            stdout_bytes, stderr_bytes = proc.communicate(
                input=payload_bytes,
                timeout=cfg.timeout_seconds,
            )
            duration = time.perf_counter() - start_time
            exit_code = proc.returncode
            stdout_raw = stdout_bytes.decode("utf-8", errors="replace")
            stderr_raw = stderr_bytes.decode("utf-8", errors="replace")

        except subprocess.TimeoutExpired:
            duration = time.perf_counter() - start_time
            proc.kill()
            try:
                proc.communicate(timeout=1.0)
            except Exception:
                pass

            err_msg = f"Execution timed out after {cfg.timeout_seconds:.1f} seconds."
            if raise_on_error:
                raise ExecutionTimeoutError(err_msg)

            return ExecutionResult(
                world_id=world.world_id,
                code_path=code.code_path,
                stdout="",
                stderr=f"TimeoutExpired: {err_msg}",
                exit_code=124,
                execution_success=False,
                error_type="TimeoutError",
                execution_error=err_msg,
                result_value=None,
                result_type=None,
                duration_seconds=round(duration, 4),
                execution_time_ms=round(duration * 1000.0, 2),
                table_names=table_names,
                row_counts=row_counts,
                generated_code_hash=code_hash,
                input_data_hashes=input_hashes,
                output_truncated=False,
            )

        except Exception as spawn_err:
            duration = time.perf_counter() - start_time
            err_msg = f"Worker process error: {spawn_err}"
            if raise_on_error:
                raise ExecutionError(err_msg)

            return ExecutionResult(
                world_id=world.world_id,
                code_path=code.code_path,
                stdout="",
                stderr=str(spawn_err),
                exit_code=1,
                execution_success=False,
                error_type=type(spawn_err).__name__,
                execution_error=err_msg,
                result_value=None,
                result_type=None,
                duration_seconds=round(duration, 4),
                execution_time_ms=round(duration * 1000.0, 2),
                table_names=table_names,
                row_counts=row_counts,
                generated_code_hash=code_hash,
                input_data_hashes=input_hashes,
                output_truncated=False,
            )

        # 10. Extract Worker Result Line from stdout
        worker_report: dict[str, Any] | None = None
        for line in stdout_raw.splitlines():
            if line.startswith("__PROOFLENS_WORKER_RESULT__:"):
                raw_json = line[len("__PROOFLENS_WORKER_RESULT__:"):].strip()
                try:
                    worker_report = json.loads(raw_json)
                    break
                except Exception:
                    pass

        if worker_report is None:
            err_msg = f"Worker exited without returning a structured report. Stderr: {stderr_raw}"
            if raise_on_error:
                raise ExecutionError(err_msg)

            return ExecutionResult(
                world_id=world.world_id,
                code_path=code.code_path,
                stdout=stdout_raw,
                stderr=stderr_raw,
                exit_code=exit_code if exit_code != 0 else 1,
                execution_success=False,
                error_type="WorkerFailureError",
                execution_error=err_msg,
                result_value=None,
                result_type=None,
                duration_seconds=round(duration, 4),
                execution_time_ms=round(duration * 1000.0, 2),
                table_names=table_names,
                row_counts=row_counts,
                generated_code_hash=code_hash,
                input_data_hashes=input_hashes,
                output_truncated=False,
            )

        # 11. Process captured report
        success = bool(worker_report.get("success", False))
        error_msg = worker_report.get("error")
        err_type = worker_report.get("error_type")
        res_val = worker_report.get("result")
        res_type = worker_report.get("result_type")
        worker_stdout = str(worker_report.get("stdout", ""))
        worker_stderr = str(worker_report.get("stderr", ""))

        if not success and raise_on_error:
            if err_type == "ResultMissingError":
                raise ResultMissingError(error_msg or "Result missing")
            raise ExecutionError(f"[{err_type}] {error_msg}")

        # 12. Check output size and apply truncation if limits exceeded
        output_truncated = False
        if len(worker_stdout.encode("utf-8")) > cfg.max_output_bytes:
            worker_stdout = worker_stdout[:cfg.max_output_bytes] + "\n[... OUTPUT TRUNCATED ...]"
            output_truncated = True

        if len(worker_stderr.encode("utf-8")) > cfg.max_output_bytes:
            worker_stderr = worker_stderr[:cfg.max_output_bytes] + "\n[... STDERR TRUNCATED ...]"
            output_truncated = True

        return ExecutionResult(
            world_id=world.world_id,
            code_path=code.code_path,
            stdout=worker_stdout,
            stderr=worker_stderr,
            exit_code=0 if success else (exit_code if exit_code != 0 else 1),
            execution_success=success,
            result_value=res_val,
            result_type=res_type,
            execution_error=error_msg,
            error_type=err_type,
            duration_seconds=round(duration, 4),
            execution_time_ms=round(duration * 1000.0, 2),
            table_names=table_names,
            row_counts=row_counts,
            generated_code_hash=code_hash,
            input_data_hashes=input_hashes,
            output_truncated=output_truncated,
        )


# Global convenience function
def run_analysis(
    world: RepairWorld,
    plan: AnalysisPlan,
    code: GeneratedCode,
    config: ExecutionConfig | None = None,
    raise_on_error: bool = False,
) -> ExecutionResult:
    """
    Convenience function to execute analysis code against a RepairWorld.
    """
    runner = SecureRunner(config)
    return runner.run(world=world, plan=plan, code=code, config=config, raise_on_error=raise_on_error)
