"""
app.audit.profiler
------------------
Deterministic Data Audit Engine for ProofLens.

CORE RULE (PROOFLENS_MASTER_CONTEXT.md §7):
    INGESTION PRESERVES.
    AUDIT DETECTS.
    REPAIR DECIDES.

This module inspects LoadedTable instances produced by the ingestion layer
and generates a structured, evidence-backed DataQualityLedger.

It NEVER modifies the input DataFrames or files.
All findings are produced deterministically; the LLM does not participate.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Any

import pandas as pd

from app.audit.contracts import (
    ColumnProfile,
    DataIssue,
    DataQualityLedger,
    IssueSeverity,
    IssueType,
    TableProfile,
)
from app.ingestion.contracts import LoadedTable

# ---------------------------------------------------------------------------
# Constants & Regex Patterns
# ---------------------------------------------------------------------------

_DATE_SLASH_DASH_DOT = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$")
_DATE_ISO = re.compile(r"^(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})$")

_CURRENCY_SYMBOLS: dict[str, str] = {
    "₹": "INR",
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
}
_CURRENCY_CODES: set[str] = {"INR", "USD", "EUR", "GBP"}

_UNIT_PATTERNS: dict[str, str] = {
    "kg": "weight",
    "g": "weight",
    "crore": "scale",
    "cr": "scale",
    "lakh": "scale",
    "lakhs": "scale",
    "million": "scale",
    "mn": "scale",
    "thousand": "scale",
    "k": "scale",
    "%": "ratio",
    "percent": "ratio",
    "pct": "ratio",
}

_SENTINEL_MISSING: set[str] = {
    "",
    "na",
    "n/a",
    "null",
    "none",
    "nan",
    "#n/a",
    "n.a.",
    "-",
    ".",
}


# ---------------------------------------------------------------------------
# Helper Inspection Functions
# ---------------------------------------------------------------------------

def is_missing_value(val: Any) -> bool:
    """Return True if val represents a null, empty, or whitespace-only value."""
    if val is None or pd.isna(val):
        return True
    if isinstance(val, str):
        cleaned = val.strip().lower()
        if cleaned in _SENTINEL_MISSING:
            return True
    return False


def is_numeric_value(val: Any) -> bool:
    """Return True if non-missing val can be parsed as a numeric value."""
    if is_missing_value(val):
        return False
    s = str(val).strip()
    # Strip thousands separators, currency symbols, and percent signs
    cleaned = re.sub(r"[,\$₹€£%]", "", s).strip()
    # Also strip common scale words if suffixed
    cleaned = re.sub(r"\b(cr|crore|lakh|lakhs|million|mn|k)\b", "", cleaned, flags=re.IGNORECASE).strip()
    try:
        float(cleaned)
        return True
    except (ValueError, TypeError):
        return False


def extract_currencies(text: str) -> set[str]:
    """Extract all currency codes/symbols found in a string."""
    found: set[str] = set()
    for sym, code in _CURRENCY_SYMBOLS.items():
        if sym in text:
            found.add(code)
    for code in _CURRENCY_CODES:
        if re.search(rf"\b{code}\b", text, flags=re.IGNORECASE):
            found.add(code.upper())
    return found


def extract_units(text: str) -> set[str]:
    """Extract recognized unit tokens from a string."""
    found: set[str] = set()
    # Check symbol % first
    if "%" in text:
        found.add("%")
    for unit in _UNIT_PATTERNS:
        if unit == "%":
            continue
        if re.search(rf"\b{unit}\b", text, flags=re.IGNORECASE):
            found.add(unit.lower())
    return found


def is_candidate_key_name(col_name: str) -> bool:
    """Return True if column name suggests an identifier or primary key."""
    low = col_name.strip().lower()
    return (
        low in {"id", "key", "code", "pk"}
        or low.endswith(("_id", "_key", "_code", "id", "key"))
        or low.startswith(("id_", "key_", "code_"))
    )


def compute_table_sha256(table: LoadedTable) -> str:
    """Compute SHA-256 hash of table's raw file content, or fallback to CSV bytes."""
    if table.source_path and table.source_path.exists() and table.source_path.is_file():
        try:
            return hashlib.sha256(table.source_path.read_bytes()).hexdigest()
        except Exception:
            pass
    # Deterministic fallback based on raw DataFrame values
    csv_bytes = table.dataframe.to_csv(index=False).encode("utf-8")
    return hashlib.sha256(csv_bytes).hexdigest()


# ---------------------------------------------------------------------------
# Single-Table Profiler
# ---------------------------------------------------------------------------

def audit_table(table: LoadedTable) -> TableProfile:
    """
    Deterministically profile a single LoadedTable.

    Inspects for:
      - Duplicate rows
      - Missing / null / whitespace values per column
      - Detailed column profiles (inferred types, counts, unique values)
      - Date format ambiguity (e.g. DD/MM vs MM/DD)
      - Mixed numeric and non-numeric representations
      - Mixed currencies in values or headers
      - Incompatible units
      - Duplicate keys in candidate identifier columns
      - Contradictory values for repeated keys

    Guarantees:
      - table.dataframe is never mutated.
      - Repeated calls on identical input produce identical output.
    """
    df = table.dataframe
    total_rows = len(df)
    col_names = list(df.columns)
    issues: list[DataIssue] = []
    col_profiles: list[ColumnProfile] = []

    # ── 1. Duplicate Row Detection ──────────────────────────────────────────
    if total_rows > 0:
        dup_series = df.duplicated()
        dup_count = int(dup_series.sum())
        if dup_count > 0:
            severity = (
                IssueSeverity.CRITICAL if dup_count > total_rows * 0.5
                else IssueSeverity.HIGH
            )
            issues.append(
                DataIssue(
                    issue_type=IssueType.DUPLICATE_ROWS,
                    severity=severity,
                    affected_source=table.table_name,
                    affected_columns=col_names,
                    description=f"{dup_count} exact duplicate rows detected in table '{table.table_name}'.",
                    evidence={
                        "duplicate_row_count": dup_count,
                        "original_row_count": total_rows,
                        "unique_row_count": total_rows - dup_count,
                    },
                )
            )

    # ── 2. Column-by-Column Profiling & Issues ──────────────────────────────
    for col in col_names:
        series = df[col]
        values = series.tolist()

        missing_count = sum(1 for v in values if is_missing_value(v))
        missing_pct = round(missing_count / total_rows, 4) if total_rows > 0 else 0.0

        non_missing = [v for v in values if not is_missing_value(v)]
        unique_non_missing = sorted(list({str(v) for v in non_missing}))
        unique_count = len(unique_non_missing)

        # Flag missing values issue
        if missing_count > 0:
            sev = (
                IssueSeverity.CRITICAL if missing_pct > 0.5
                else IssueSeverity.HIGH if missing_pct > 0.1
                else IssueSeverity.MEDIUM
            )
            issues.append(
                DataIssue(
                    issue_type=IssueType.MISSING_VALUES,
                    severity=sev,
                    affected_source=table.table_name,
                    affected_columns=[col],
                    description=(
                        f"Column '{col}' in '{table.table_name}' contains "
                        f"{missing_count} missing values out of {total_rows} rows "
                        f"({missing_pct * 100:.1f}%)."
                    ),
                    evidence={
                        "column": col,
                        "missing_count": missing_count,
                        "missing_pct": missing_pct,
                        "total_rows": total_rows,
                    },
                )
            )

        # ── Currency Detection for Column ───────────────────────────────────
        col_currencies: set[str] = extract_currencies(col)
        for v in non_missing:
            col_currencies.update(extract_currencies(str(v)))

        if len(col_currencies) > 1:
            issues.append(
                DataIssue(
                    issue_type=IssueType.MIXED_CURRENCIES,
                    severity=IssueSeverity.CRITICAL,
                    affected_source=table.table_name,
                    affected_columns=[col],
                    description=(
                        f"Multiple currencies detected in column '{col}': "
                        f"{', '.join(sorted(col_currencies))}. Calculations across "
                        f"mixed currencies require explicit policy/rates."
                    ),
                    evidence={
                        "column": col,
                        "currencies_detected": sorted(list(col_currencies)),
                        "sample_values": non_missing[:5],
                    },
                )
            )

        # ── Unit Detection for Column ───────────────────────────────────────
        col_units: set[str] = extract_units(col)
        for v in non_missing:
            col_units.update(extract_units(str(v)))

        # Check if units of same dimension conflict (e.g. kg vs g, or crore vs lakh)
        unit_dims: dict[str, set[str]] = {}
        for u in col_units:
            dim = _UNIT_PATTERNS.get(u, "other")
            unit_dims.setdefault(dim, set()).add(u)

        for dim, dim_units in unit_dims.items():
            if len(dim_units) > 1 and dim != "other":
                issues.append(
                    DataIssue(
                        issue_type=IssueType.MIXED_UNITS,
                        severity=IssueSeverity.HIGH,
                        affected_source=table.table_name,
                        affected_columns=[col],
                        description=(
                            f"Multiple conflicting units detected in column '{col}' "
                            f"for {dim}: {', '.join(sorted(dim_units))}."
                        ),
                        evidence={
                            "column": col,
                            "dimension": dim,
                            "units_detected": sorted(list(dim_units)),
                        },
                    )
                )

        # ── Inferred Type & Date / Numeric Specific Checks ──────────────────
        inferred_type = "text"
        if total_rows == 0 or len(non_missing) == 0:
            inferred_type = "empty"
        else:
            # Check boolean-like
            bool_tokens = {"true", "false", "0", "1", "yes", "no", "y", "n"}
            if all(str(v).strip().lower() in bool_tokens for v in non_missing):
                inferred_type = "boolean"

            # Check numeric-like
            num_count = sum(1 for v in non_missing if is_numeric_value(v))
            if num_count == len(non_missing):
                inferred_type = "numeric"
            elif num_count > 0:
                # Mixed numeric and non-numeric
                sample_non_num = [str(v) for v in non_missing if not is_numeric_value(v)][:5]
                issues.append(
                    DataIssue(
                        issue_type=IssueType.ANOMALY,
                        severity=IssueSeverity.MEDIUM,
                        affected_source=table.table_name,
                        affected_columns=[col],
                        description=(
                            f"Column '{col}' in '{table.table_name}' contains mixed "
                            f"numeric and non-numeric values ({num_count} numeric, "
                            f"{len(non_missing) - num_count} non-numeric)."
                        ),
                        evidence={
                            "column": col,
                            "numeric_count": num_count,
                            "non_numeric_count": len(non_missing) - num_count,
                            "sample_non_numeric": sample_non_num,
                        },
                    )
                )

            # Check date-like & Date Ambiguity
            date_matches = 0
            ambiguous_dates: list[str] = []
            has_part1_gt_12 = False
            has_part2_gt_12 = False

            for v in non_missing:
                s = str(v).strip()
                m_slash = _DATE_SLASH_DASH_DOT.match(s)
                m_iso = _DATE_ISO.match(s)
                if m_slash:
                    date_matches += 1
                    p1, p2, p3 = int(m_slash.group(1)), int(m_slash.group(2)), int(m_slash.group(3))
                    if p1 > 12:
                        has_part1_gt_12 = True
                    if p2 > 12:
                        has_part2_gt_12 = True
                    # Ambiguous if both parts <= 12 and not equal
                    if 1 <= p1 <= 12 and 1 <= p2 <= 12 and p1 != p2:
                        ambiguous_dates.append(s)
                elif m_iso:
                    date_matches += 1

            if date_matches == len(non_missing):
                inferred_type = "date"
            elif date_matches > len(non_missing) * 0.5:
                inferred_type = "date"

            if ambiguous_dates:
                # The data contains dates where DD/MM vs MM/DD cannot be deduced without assumptions
                issues.append(
                    DataIssue(
                        issue_type=IssueType.AMBIGUOUS_DATE_FORMAT,
                        severity=IssueSeverity.HIGH,
                        affected_source=table.table_name,
                        affected_columns=[col],
                        description=(
                            f"Column '{col}' in '{table.table_name}' contains values "
                            f"compatible with both DD/MM/YYYY and MM/DD/YYYY "
                            f"(e.g. '{ambiguous_dates[0]}')."
                        ),
                        evidence={
                            "column": col,
                            "ambiguous_count": len(ambiguous_dates),
                            "sample_ambiguous_dates": ambiguous_dates[:5],
                            "possible_interpretations": ["DD/MM/YYYY", "MM/DD/YYYY"],
                            "has_part1_gt_12": has_part1_gt_12,
                            "has_part2_gt_12": has_part2_gt_12,
                        },
                    )
                )

        # ── Candidate Key & Duplicate Key Checks ────────────────────────────
        is_candidate_key = is_candidate_key_name(col) or (
            unique_count == total_rows and total_rows > 0 and missing_count == 0
        )

        if is_candidate_key_name(col) and total_rows > 0:
            key_dup_mask = series.duplicated()
            if key_dup_mask.any():
                dup_key_vals = [
                    str(k) for k in series[key_dup_mask].unique() if not is_missing_value(k)
                ]
                if dup_key_vals:
                    issues.append(
                        DataIssue(
                            issue_type=IssueType.DUPLICATE_KEYS,
                            severity=IssueSeverity.HIGH,
                            affected_source=table.table_name,
                            affected_columns=[col],
                            description=(
                                f"Candidate key column '{col}' in '{table.table_name}' "
                                f"contains {len(dup_key_vals)} duplicate key values across {total_rows} rows."
                            ),
                            evidence={
                                "key_column": col,
                                "duplicate_key_count": len(dup_key_vals),
                                "sample_duplicate_keys": dup_key_vals[:5],
                                "unique_keys": unique_count,
                            },
                        )
                    )

                    # ── Contradictory Values Check on Duplicate Keys ────────
                    conflicts: list[dict[str, Any]] = []
                    for k_val in dup_key_vals[:10]:
                        rows_with_key = df[df[col] == k_val]
                        for other_c in col_names:
                            if other_c == col:
                                continue
                            distinct_other = {
                                str(v).strip()
                                for v in rows_with_key[other_c]
                                if not is_missing_value(v)
                            }
                            if len(distinct_other) > 1:
                                conflicts.append({
                                    "key": str(k_val),
                                    "column": other_c,
                                    "conflicting_values": sorted(list(distinct_other))[:5],
                                })
                    if conflicts:
                        issues.append(
                            DataIssue(
                                issue_type=IssueType.CONTRADICTORY_VALUES,
                                severity=IssueSeverity.CRITICAL,
                                affected_source=table.table_name,
                                affected_columns=[col] + sorted(list({c["column"] for c in conflicts})),
                                description=(
                                    f"Contradictory values detected for candidate key '{col}': "
                                    f"conflicting values found across rows with identical key."
                                ),
                                evidence={
                                    "key_column": col,
                                    "sample_conflicts": conflicts[:5],
                                },
                            )
                        )

        # Assemble ColumnProfile
        col_profiles.append(
            ColumnProfile(
                column_name=col,
                inferred_type=inferred_type,
                total_count=total_rows,
                unique_count=unique_count,
                missing_count=missing_count,
                missing_pct=missing_pct,
                sample_values=unique_non_missing[:5],
                detected_currencies=sorted(list(col_currencies)),
                detected_units=sorted(list(col_units)),
                is_potential_key=is_candidate_key,
            )
        )

    # Compute hash for table
    table_hash = compute_table_sha256(table)

    return TableProfile(
        source=table.table_name,
        row_count=total_rows,
        column_count=len(col_names),
        column_names=col_names,
        column_profiles=col_profiles,
        issues=issues,
        dataset_sha256=table_hash,
    )


# ---------------------------------------------------------------------------
# Multi-Table Audit & Cross-Table Observations
# ---------------------------------------------------------------------------

def audit_tables(
    tables: list[LoadedTable],
    session_id: str | None = None,
) -> DataQualityLedger:
    """
    Deterministically profile one or more LoadedTables and conduct cross-table audits.

    Cross-table checks include:
      - Orphan foreign key detection between candidate key columns
      - Schema naming similarity observations (e.g. customer_id vs cust_id)

    Guarantees:
      - Input DataFrames are NEVER mutated.
      - Produces an explainable, deterministic DataQualityLedger.
    """
    table_profiles: list[TableProfile] = []
    cross_issues: list[DataIssue] = []

    # 1. Profile each table individually
    for t in tables:
        try:
            profile = audit_table(t)
            table_profiles.append(profile)
        except Exception as exc:
            col_names = [str(c) for c in t.dataframe.columns]
            table_profiles.append(
                TableProfile(
                    source=t.table_name,
                    row_count=len(t.dataframe),
                    column_count=len(col_names),
                    column_names=col_names,
                    column_profiles=[],
                    issues=[
                        DataIssue(
                            issue_type=IssueType.ANOMALY,
                            severity=IssueSeverity.HIGH,
                            affected_source=t.table_name,
                            affected_columns=col_names[:5],
                            description=f"Automated audit profiling error on table '{t.table_name}': {str(exc)}",
                        )
                    ],
                    dataset_sha256=compute_table_sha256(t),
                )
            )

    # 2. Cross-table checks across pairs
    if len(tables) > 1:
        for i in range(len(tables)):
            t1 = tables[i]
            df1 = t1.dataframe
            cols1 = set(df1.columns)

            for j in range(i + 1, len(tables)):
                t2 = tables[j]
                df2 = t2.dataframe
                cols2 = set(df2.columns)

                common_cols = cols1.intersection(cols2)
                for common_col in common_cols:
                    if is_candidate_key_name(common_col):
                        # Check foreign key relationships
                        # If t1 has unique keys in common_col, check if t2 has orphan keys
                        t1_non_missing = {v for v in df1[common_col] if not is_missing_value(v)}
                        t2_non_missing = {v for v in df2[common_col] if not is_missing_value(v)}

                        if len(t1_non_missing) > 0 and len(t2_non_missing) > 0:
                            # Check orphans in t2 relative to t1
                            if df1[common_col].nunique() == len(df1) and len(df1) > 0:
                                orphans = t2_non_missing - t1_non_missing
                                if orphans:
                                    cross_issues.append(
                                        DataIssue(
                                            issue_type=IssueType.ORPHAN_FOREIGN_KEY,
                                            severity=IssueSeverity.HIGH,
                                            affected_source=f"{t2.table_name} -> {t1.table_name}",
                                            affected_columns=[common_col],
                                            description=(
                                                f"Table '{t2.table_name}' contains {len(orphans)} "
                                                f"orphan foreign key values in column '{common_col}' "
                                                f"that do not exist in '{t1.table_name}.{common_col}'."
                                            ),
                                            evidence={
                                                "child_table": t2.table_name,
                                                "parent_table": t1.table_name,
                                                "column": common_col,
                                                "orphan_count": len(orphans),
                                                "sample_orphans": sorted(list(str(x) for x in orphans))[:5],
                                            },
                                        )
                                    )

                # Schema name similarity check (e.g. cust_id vs customer_id)
                for c1 in cols1:
                    norm1 = re.sub(r"[_ -]", "", c1.lower())
                    for c2 in cols2:
                        if c1 != c2:
                            norm2 = re.sub(r"[_ -]", "", c2.lower())
                            if norm1 == norm2 or (
                                norm1 in norm2 or norm2 in norm1
                            ) and (is_candidate_key_name(c1) or is_candidate_key_name(c2)):
                                cross_issues.append(
                                    DataIssue(
                                        issue_type=IssueType.CROSS_TABLE_MISMATCH,
                                        severity=IssueSeverity.INFO,
                                        affected_source=f"{t1.table_name}, {t2.table_name}",
                                        affected_columns=[c1, c2],
                                        description=(
                                            f"Possible related key columns with differing names: "
                                            f"'{t1.table_name}.{c1}' and '{t2.table_name}.{c2}'."
                                        ),
                                        evidence={
                                            "table_1": t1.table_name,
                                            "column_1": c1,
                                            "table_2": t2.table_name,
                                            "column_2": c2,
                                        },
                                    )
                                )

    # Combine all issues: table-level issues + cross-table issues
    all_issues: list[DataIssue] = []
    for tp in table_profiles:
        all_issues.extend(tp.issues)
    all_issues.extend(cross_issues)

    has_critical = any(issue.severity == IssueSeverity.CRITICAL for issue in all_issues)
    now_iso = datetime.now(timezone.utc).isoformat()

    return DataQualityLedger(
        session_id=session_id,
        audit_timestamp=now_iso,
        table_profiles=table_profiles,
        all_issues=all_issues,
        has_critical_issues=has_critical,
    )
