"""
app.execution.worker
--------------------
Isolated worker process for ProofLens secure execution.

This script runs in a separate subprocess with a controlled namespace.
It communicates exclusively via stdin and stdout using JSON.

Responsibilities:
  - Read input JSON payload containing code and tables.
  - Reconstruct DataFrames from supplied records.
  - Construct restricted globals without dangerous builtins.
  - Execute the code using restricted globals.
  - Extract RESULT or result variable.
  - Emit JSON output report.
"""

from __future__ import annotations

import io
import json
import math
import sys
from typing import Any

import numpy as np
import pandas as pd

def _safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
    """Safe import restricted strictly to allowed data science modules."""
    if name not in {"pandas", "numpy", "math", "datetime", "json", "duckdb"}:
        raise ImportError(f"Importing module '{name}' is forbidden.")
    return __import__(name, *args, **kwargs)


# ---------------------------------------------------------------------------
# Whitelisted Safe Builtins
# ---------------------------------------------------------------------------
_SAFE_BUILTINS: dict[str, Any] = {
    "__import__": _safe_import,
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "format": format,
    "int": int,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "iter": iter,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "next": next,
    "print": print,
    "range": range,
    "repr": repr,
    "reversed": reversed,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
    # Safe Standard Exceptions
    "ArithmeticError": ArithmeticError,
    "AssertionError": AssertionError,
    "AttributeError": AttributeError,
    "Exception": Exception,
    "IndexError": IndexError,
    "KeyError": KeyError,
    "LookupError": LookupError,
    "NameError": NameError,
    "RuntimeError": RuntimeError,
    "TypeError": TypeError,
    "ValueError": ValueError,
    "ZeroDivisionError": ZeroDivisionError,
    # Constants
    "True": True,
    "False": False,
    "None": None,
}


def _normalize_result(val: Any) -> tuple[Any, str]:
    """Convert result to a JSON-serializable structure and determine result type."""
    if val is None:
        return None, "None"
    if isinstance(val, (bool, np.bool_)):
        return bool(val), "bool"
    if isinstance(val, (int, np.integer)):
        return int(val), "int"
    if isinstance(val, (float, np.floating)):
        # Check NaN / inf
        if math.isnan(val) or math.isinf(val):
            return str(val), "float"
        return float(val), "float"
    if isinstance(val, str):
        return str(val), "str"
    if isinstance(val, pd.DataFrame):
        return val.to_dict(orient="records"), "dataframe"
    if isinstance(val, pd.Series):
        return val.to_dict(), "series"
    if isinstance(val, dict):
        # Sort keys deterministically
        return {str(k): v for k, v in sorted(val.items(), key=lambda x: str(x[0]))}, "dict"
    if isinstance(val, (list, tuple, set)):
        return list(val), "list"
    return str(val), type(val).__name__


def main() -> None:
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            out = {
                "success": False,
                "error": "Empty input payload",
                "error_type": "EmptyInputError",
                "stdout": "",
                "stderr": "",
            }
            print("__PROOFLENS_WORKER_RESULT__:" + json.dumps(out))
            return

        payload = json.loads(raw_input)
        code = payload.get("code", "")
        raw_tables = payload.get("tables", {})

        # Reconstruct tables dictionary of deep-copied DataFrames
        tables: dict[str, pd.DataFrame] = {}
        for tbl_name, tbl_data in raw_tables.items():
            if isinstance(tbl_data, dict) and "records" in tbl_data:
                records = tbl_data.get("records", [])
                cols = tbl_data.get("columns", [])
                df = pd.DataFrame(records)
                if cols and df.empty:
                    df = pd.DataFrame(columns=cols)
                tables[tbl_name] = df
            else:
                tables[tbl_name] = pd.DataFrame(tbl_data)

        # Build restricted namespace
        restricted_globals: dict[str, Any] = {
            "__builtins__": _SAFE_BUILTINS,
            "__name__": "__restricted__",
            "tables": tables,
            "pd": pd,
            "pandas": pd,
            "np": np,
            "numpy": np,
            "math": math,
            "json": json,
        }

        # Redirect stdout and stderr during execution
        max_capture = int(payload.get("max_output_bytes", 100_000))
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        # Custom print that writes to our buffer (bounded)
        def safe_print(*args: Any, **kwargs: Any) -> None:
            sep = kwargs.get("sep", " ")
            end = kwargs.get("end", "\n")
            msg = sep.join(str(a) for a in args) + end
            if stdout_capture.tell() <= max_capture * 2:
                stdout_capture.write(msg)

        restricted_globals["print"] = safe_print

        exec_error: Exception | None = None
        try:
            compiled_code = compile(code, "<analysis>", "exec")
            exec(compiled_code, restricted_globals)
        except Exception as e:
            exec_error = e
            stderr_capture.write(str(e))

        captured_stdout = stdout_capture.getvalue()
        captured_stderr = stderr_capture.getvalue()

        if exec_error is not None:
            out = {
                "success": False,
                "error": str(exec_error),
                "error_type": type(exec_error).__name__,
                "stdout": captured_stdout,
                "stderr": captured_stderr,
                "result": None,
                "result_type": None,
            }
        else:
            # Look for RESULT first, then fallback to result
            res_val = restricted_globals.get("RESULT")
            if res_val is None and "RESULT" not in restricted_globals:
                res_val = restricted_globals.get("result")

            if res_val is None and "result" not in restricted_globals and "RESULT" not in restricted_globals:
                out = {
                    "success": False,
                    "error": "Execution completed but no RESULT or result variable was set.",
                    "error_type": "ResultMissingError",
                    "stdout": captured_stdout,
                    "stderr": captured_stderr,
                    "result": None,
                    "result_type": None,
                }
            else:
                norm_res, res_type = _normalize_result(res_val)
                out = {
                    "success": True,
                    "result": norm_res,
                    "result_type": res_type,
                    "stdout": captured_stdout,
                    "stderr": captured_stderr,
                    "error": None,
                    "error_type": None,
                }

        original_stdout.write("__PROOFLENS_WORKER_RESULT__:" + json.dumps(out) + "\n")

    except Exception as fatal_e:
        err_out = {
            "success": False,
            "error": f"Worker fatal error: {fatal_e}",
            "error_type": type(fatal_e).__name__,
            "stdout": "",
            "stderr": str(fatal_e),
        }
        sys.stdout.write("__PROOFLENS_WORKER_RESULT__:" + json.dumps(err_out) + "\n")


if __name__ == "__main__":
    main()
