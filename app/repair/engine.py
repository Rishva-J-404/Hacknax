"""
app.repair.engine
-----------------
Deterministic Repair & Ambiguity Decision Center for ProofLens.

CORE RULE (PROOFLENS_MASTER_CONTEXT.md §6):
    INGESTION PRESERVES.
    AUDIT DETECTS.
    REPAIR DECIDES.

The Repair Engine never silently modifies original input data.
Original DataFrames are never mutated in-place.
All transformations are performed on explicit copies and recorded in
a machine-readable repair_history.

When policy = COMPARE, the engine expands the ambiguity into multiple
explicit, controlled RepairWorlds with a deterministic bound (MAX_WORLDS).
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from itertools import product
from pathlib import Path
import re
import statistics
from typing import Any

import pandas as pd

from app.audit.contracts import DataQualityLedger, IssueSeverity, IssueType
from app.audit.profiler import (
    _CURRENCY_CODES,
    _CURRENCY_SYMBOLS,
    _DATE_ISO,
    _DATE_SLASH_DASH_DOT,
    compute_table_sha256,
    is_missing_value,
    is_numeric_value,
)
from app.ingestion.contracts import FileType, LoadedTable
from app.repair.contracts import (
    CurrencyAction,
    DateFormatAction,
    DuplicateAction,
    MissingValueAction,
    RepairError,
    RepairHistoryEntry,
    RepairPolicy,
    RepairWorld,
)

# ---------------------------------------------------------------------------
# Default Maximum World Limit
# ---------------------------------------------------------------------------
DEFAULT_MAX_WORLDS: int = 16


# ---------------------------------------------------------------------------
# Repair Operations on a single DataFrame Copy
# ---------------------------------------------------------------------------

def _apply_duplicate_policy(
    df: pd.DataFrame,
    table_name: str,
    action: str,
    history: list[RepairHistoryEntry],
    assumptions: list[str],
) -> pd.DataFrame:
    """Apply duplicate handling policy to a copied DataFrame."""
    act = action.upper()
    rows_before = len(df)

    if act in {DuplicateAction.KEEP.value, DuplicateAction.KEEP_ALL.value}:
        history.append(
            RepairHistoryEntry(
                operation="KEEP",
                table=table_name,
                rows_before=rows_before,
                rows_after=rows_before,
                affected_rows=0,
                reason="Duplicate policy: KEEP (all rows preserved including duplicates)",
            )
        )
        return df

    if act in {DuplicateAction.EXACT_DEDUP.value, DuplicateAction.DROP_EXACT_DUPLICATES.value}:
        df_after = df.drop_duplicates(keep="first").reset_index(drop=True)
        affected = rows_before - len(df_after)
        history.append(
            RepairHistoryEntry(
                operation="EXACT_DEDUP",
                table=table_name,
                rows_before=rows_before,
                rows_after=len(df_after),
                affected_rows=affected,
                reason="Duplicate policy: EXACT_DEDUP (removed exact full-row duplicates)",
            )
        )
        return df_after

    if act == DuplicateAction.DROP_KEY_DUPLICATES.value:
        # Default or caller parameter key column
        df_after = df.drop_duplicates(keep="first").reset_index(drop=True)
        affected = rows_before - len(df_after)
        history.append(
            RepairHistoryEntry(
                operation="DROP_KEY_DUPLICATES",
                table=table_name,
                rows_before=rows_before,
                rows_after=len(df_after),
                affected_rows=affected,
                reason="Duplicate policy: DROP_KEY_DUPLICATES",
            )
        )
        return df_after

    if act == DuplicateAction.REVIEW.value:
        assumptions.append("Duplicate rows flagged for human review; data kept as-is.")
        history.append(
            RepairHistoryEntry(
                operation="REVIEW",
                table=table_name,
                rows_before=rows_before,
                rows_after=rows_before,
                affected_rows=0,
                reason="Duplicate policy: REVIEW",
            )
        )
        return df

    if "FUZZY" in act:
        raise RepairError(
            f"Unsupported duplicate policy '{action}'. Fuzzy deduplication is not implemented.",
            reason="UNSUPPORTED_REPAIR",
        )

    raise RepairError(
        f"Unknown duplicate action '{action}'.",
        reason="INVALID_POLICY",
    )


def _apply_missing_policy(
    df: pd.DataFrame,
    table_name: str,
    action: str,
    target_column: str | None,
    history: list[RepairHistoryEntry],
    assumptions: list[str],
) -> pd.DataFrame:
    """Apply missing value policy to a copied DataFrame."""
    act = action.upper()
    rows_before = len(df)

    if act in {MissingValueAction.LEAVE.value, MissingValueAction.KEEP_NULLS.value}:
        history.append(
            RepairHistoryEntry(
                operation="LEAVE_MISSING",
                table=table_name,
                column=target_column,
                rows_before=rows_before,
                rows_after=rows_before,
                affected_rows=0,
                reason="Missing-value policy: LEAVE (null/empty values preserved)",
            )
        )
        return df

    if act in {MissingValueAction.DROP.value, MissingValueAction.DROP_ROWS.value}:
        if target_column and target_column in df.columns:
            keep_mask = [not is_missing_value(v) for v in df[target_column]]
        else:
            # Drop rows with ANY missing value across all columns
            keep_mask = [
                not any(is_missing_value(v) for v in row)
                for _, row in df.iterrows()
            ]
        df_after = df[keep_mask].reset_index(drop=True)
        affected = rows_before - len(df_after)
        history.append(
            RepairHistoryEntry(
                operation="DROP_MISSING",
                table=table_name,
                column=target_column,
                rows_before=rows_before,
                rows_after=len(df_after),
                affected_rows=affected,
                reason=f"Missing-value policy: DROP (removed rows with missing values in {target_column or 'any column'})",
            )
        )
        return df_after

    if act == MissingValueAction.FILL_ZERO.value:
        cols_to_fill = [target_column] if target_column and target_column in df.columns else list(df.columns)
        total_filled = 0

        for col in cols_to_fill:
            non_missing = [v for v in df[col] if not is_missing_value(v)]
            if len(non_missing) > 0 and not all(is_numeric_value(v) for v in non_missing):
                raise RepairError(
                    f"Cannot FILL_ZERO on column '{col}': column is not numeric-compatible.",
                    reason="NON_NUMERIC_COLUMN",
                    details={"column": col, "sample_values": non_missing[:5]},
                )

            # Fill missing with "0"
            missing_count = sum(1 for v in df[col] if is_missing_value(v))
            if missing_count > 0:
                new_col = [
                    "0" if is_missing_value(v) else str(v)
                    for v in df[col]
                ]
                df[col] = new_col
                total_filled += missing_count
                history.append(
                    RepairHistoryEntry(
                        operation="FILL_ZERO",
                        table=table_name,
                        column=col,
                        rows_before=rows_before,
                        rows_after=rows_before,
                        affected_rows=missing_count,
                        reason=f"Missing-value policy: FILL_ZERO on '{col}'",
                    )
                )

        if total_filled == 0:
            history.append(
                RepairHistoryEntry(
                    operation="FILL_ZERO",
                    table=table_name,
                    column=target_column,
                    rows_before=rows_before,
                    rows_after=rows_before,
                    affected_rows=0,
                    reason="Missing-value policy: FILL_ZERO (no missing values found)",
                )
            )
        return df

    if act in {MissingValueAction.FILL_MEDIAN.value, MissingValueAction.FILL_COLUMN_MEAN.value}:
        cols_to_fill = [target_column] if target_column and target_column in df.columns else list(df.columns)
        total_filled = 0

        for col in cols_to_fill:
            non_missing = [v for v in df[col] if not is_missing_value(v)]
            if len(non_missing) == 0:
                continue

            if not all(is_numeric_value(v) for v in non_missing):
                raise RepairError(
                    f"Cannot calculate median on non-numeric column '{col}'.",
                    reason="NON_NUMERIC_COLUMN",
                    details={"column": col, "sample_values": non_missing[:5]},
                )

            numeric_values = [
                float(re.sub(r"[,\$₹€£%]", "", str(v)).strip())
                for v in non_missing
            ]
            if act == MissingValueAction.FILL_MEDIAN.value:
                fill_val = statistics.median(numeric_values)
                op_name = "FILL_MEDIAN"
            else:
                fill_val = statistics.mean(numeric_values)
                op_name = "FILL_COLUMN_MEAN"

            fill_str = str(int(fill_val)) if fill_val.is_integer() else f"{fill_val:g}"

            missing_count = sum(1 for v in df[col] if is_missing_value(v))
            if missing_count > 0:
                new_col = [
                    fill_str if is_missing_value(v) else str(v)
                    for v in df[col]
                ]
                df[col] = new_col
                total_filled += missing_count
                history.append(
                    RepairHistoryEntry(
                        operation=op_name,
                        table=table_name,
                        column=col,
                        rows_before=rows_before,
                        rows_after=rows_before,
                        affected_rows=missing_count,
                        reason=f"Missing-value policy: {op_name} on '{col}' (value={fill_str})",
                        details={"fill_value": fill_str},
                    )
                )

        if total_filled == 0:
            history.append(
                RepairHistoryEntry(
                    operation=act,
                    table=table_name,
                    column=target_column,
                    rows_before=rows_before,
                    rows_after=rows_before,
                    affected_rows=0,
                    reason=f"Missing-value policy: {act} (no missing values found)",
                )
            )
        return df

    raise RepairError(
        f"Unknown missing-value action '{action}'.",
        reason="INVALID_POLICY",
    )


def _apply_date_policy(
    df: pd.DataFrame,
    table_name: str,
    action: str,
    target_column: str,
    history: list[RepairHistoryEntry],
    assumptions: list[str],
) -> pd.DataFrame:
    """Apply date interpretation policy to a copied DataFrame."""
    act = action.upper()
    rows_before = len(df)

    if act == DateFormatAction.KEEP_SOURCE.value:
        history.append(
            RepairHistoryEntry(
                operation="KEEP_SOURCE_DATES",
                table=table_name,
                column=target_column,
                rows_before=rows_before,
                rows_after=rows_before,
                affected_rows=0,
                reason=f"Date policy: KEEP_SOURCE on '{target_column}'",
            )
        )
        return df

    if act in {DateFormatAction.DD_MM_YYYY.value, DateFormatAction.MM_DD_YYYY.value, DateFormatAction.YYYY_MM_DD.value}:
        if target_column not in df.columns:
            return df

        new_values: list[str] = []
        modified_count = 0

        for val in df[target_column]:
            if is_missing_value(val):
                new_values.append(str(val))
                continue

            s = str(val).strip()
            m_slash = _DATE_SLASH_DASH_DOT.match(s)
            m_iso = _DATE_ISO.match(s)

            if m_slash:
                p1, p2, p3 = int(m_slash.group(1)), int(m_slash.group(2)), int(m_slash.group(3))
                year = p3 if p3 >= 100 else 2000 + p3

                if act == DateFormatAction.DD_MM_YYYY.value:
                    day, month = p1, p2
                    if not (1 <= month <= 12 and 1 <= day <= 31):
                        raise RepairError(
                            f"Cannot convert date '{s}' in '{target_column}' under policy DD_MM_YYYY: invalid day/month.",
                            reason="UNPARSEABLE_DATE",
                            details={"column": target_column, "value": s, "policy": act},
                        )
                    converted = f"{day:02d}/{month:02d}/{year:04d}"
                elif act == DateFormatAction.MM_DD_YYYY.value:
                    month, day = p1, p2
                    if not (1 <= month <= 12 and 1 <= day <= 31):
                        raise RepairError(
                            f"Cannot convert date '{s}' in '{target_column}' under policy MM_DD_YYYY: invalid day/month.",
                            reason="UNPARSEABLE_DATE",
                            details={"column": target_column, "value": s, "policy": act},
                        )
                    converted = f"{month:02d}/{day:02d}/{year:04d}"
                else:  # YYYY_MM_DD
                    day, month = p1, p2
                    if not (1 <= month <= 12 and 1 <= day <= 31):
                        raise RepairError(
                            f"Cannot convert date '{s}' in '{target_column}' under policy YYYY_MM_DD: invalid day/month.",
                            reason="UNPARSEABLE_DATE",
                            details={"column": target_column, "value": s, "policy": act},
                        )
                    converted = f"{year:04d}-{month:02d}-{day:02d}"

                new_values.append(converted)
                if converted != s:
                    modified_count += 1

            elif m_iso:
                # ISO format: YYYY-MM-DD
                year, month, day = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
                if not (1 <= month <= 12 and 1 <= day <= 31):
                    raise RepairError(
                        f"Cannot convert ISO date '{s}' in '{target_column}': invalid day/month.",
                        reason="UNPARSEABLE_DATE",
                        details={"column": target_column, "value": s},
                    )
                if act == DateFormatAction.DD_MM_YYYY.value:
                    converted = f"{day:02d}/{month:02d}/{year:04d}"
                elif act == DateFormatAction.MM_DD_YYYY.value:
                    converted = f"{month:02d}/{day:02d}/{year:04d}"
                else:
                    converted = f"{year:04d}-{month:02d}-{day:02d}"

                new_values.append(converted)
                if converted != s:
                    modified_count += 1
            else:
                # Non-date string in date column
                raise RepairError(
                    f"Cannot convert date in column '{target_column}': unparseable value '{s}' under policy '{act}'.",
                    reason="UNPARSEABLE_DATE",
                    details={"column": target_column, "value": s},
                )

        df[target_column] = new_values
        assumptions.append(f"Interpreted date column '{target_column}' as {act}.")
        history.append(
            RepairHistoryEntry(
                operation="DATE_CONVERSION",
                table=table_name,
                column=target_column,
                rows_before=rows_before,
                rows_after=rows_before,
                affected_rows=modified_count,
                reason=f"Date policy: {act} applied to '{target_column}'",
            )
        )
        return df

    raise RepairError(
        f"Unknown date action '{action}'.",
        reason="INVALID_POLICY",
    )


def _apply_currency_policy(
    df: pd.DataFrame,
    table_name: str,
    action: str,
    target_column: str | None,
    parameters: dict[str, Any],
    history: list[RepairHistoryEntry],
    assumptions: list[str],
) -> pd.DataFrame:
    """Apply currency handling policy to a copied DataFrame."""
    act = action.upper()
    rows_before = len(df)

    if act == CurrencyAction.KEEP_SEPARATE.value:
        history.append(
            RepairHistoryEntry(
                operation="KEEP_CURRENCIES_SEPARATE",
                table=table_name,
                column=target_column,
                rows_before=rows_before,
                rows_after=rows_before,
                affected_rows=0,
                reason="Currency policy: KEEP_SEPARATE (no cross-currency conversions performed)",
            )
        )
        assumptions.append("Currencies kept separate; no exchange rates applied.")
        return df

    if act in {CurrencyAction.USE_SUPPLIED_RATES.value, CurrencyAction.CONVERT_TO_BASE.value}:
        rates = parameters.get("rates") or parameters.get("exchange_rates")
        base_currency = parameters.get("base_currency") or "INR"

        if not rates or not isinstance(rates, dict):
            raise RepairError(
                "Currency conversion requested without supplied exchange rates.",
                reason="MISSING_EXCHANGE_RATES",
                details={"parameters": parameters},
            )

        cols = [target_column] if target_column and target_column in df.columns else list(df.columns)
        converted_count = 0

        for col in cols:
            new_values: list[str] = []
            for val in df[col]:
                if is_missing_value(val):
                    new_values.append(str(val))
                    continue

                s = str(val).strip()
                # Detect currency in value
                curr = None
                for sym, code in _CURRENCY_SYMBOLS.items():
                    if sym in s:
                        curr = code
                        break
                if not curr:
                    for code in _CURRENCY_CODES:
                        if re.search(rf"\b{code}\b", s, flags=re.IGNORECASE):
                            curr = code.upper()
                            break

                if not curr:
                    new_values.append(s)
                    continue

                # Strip symbol/code for numeric conversion
                cleaned = re.sub(r"[,\$₹€£%]", "", s)
                for code in _CURRENCY_CODES:
                    cleaned = re.sub(rf"\b{code}\b", "", cleaned, flags=re.IGNORECASE)
                cleaned = cleaned.strip()

                try:
                    num = float(cleaned)
                except ValueError:
                    new_values.append(s)
                    continue

                if curr.upper() == base_currency.upper():
                    converted_val = num
                else:
                    rate = rates.get(curr.upper())
                    if rate is None:
                        raise RepairError(
                            f"Missing exchange rate for currency '{curr}' to '{base_currency}'.",
                            reason="MISSING_EXCHANGE_RATES",
                            details={"currency": curr, "base_currency": base_currency, "rates": rates},
                        )
                    converted_val = num * float(rate)

                res_str = f"{converted_val:.2f}" if not converted_val.is_integer() else str(int(converted_val))
                new_values.append(res_str)
                converted_count += 1

            df[col] = new_values

        assumptions.append(f"Converted currencies to {base_currency} using supplied rates: {rates}.")
        history.append(
            RepairHistoryEntry(
                operation="CURRENCY_CONVERSION",
                table=table_name,
                column=target_column,
                rows_before=rows_before,
                rows_after=rows_before,
                affected_rows=converted_count,
                reason=f"Currency policy: converted to {base_currency} with supplied rates",
                details={"base_currency": base_currency, "rates": rates},
            )
        )
        return df

    raise RepairError(
        f"Unknown currency action '{action}'.",
        reason="INVALID_POLICY",
    )


# ---------------------------------------------------------------------------
# Repair Engine Class
# ---------------------------------------------------------------------------

class RepairEngine:
    """
    Repair & Ambiguity Decision Center.

    Produces explicit RepairWorlds from LoadedTables and DataQualityLedger.
    Guarantees:
      - Original input LoadedTable instances are never modified.
      - Transforms are deterministic.
      - COMPARE expands ambiguities up to max_worlds.
    """

    def __init__(self, max_worlds: int = DEFAULT_MAX_WORLDS) -> None:
        self.max_worlds = max_worlds

    def apply_policies_to_tables(
        self,
        tables: list[LoadedTable],
        policies: list[RepairPolicy],
    ) -> tuple[list[LoadedTable], list[RepairHistoryEntry], list[str]]:
        """
        Apply a list of non-COMPARE RepairPolicy objects to deep copies of the tables.

        Returns:
            (repaired_tables, repair_history, assumptions)
        """
        repaired_tables: list[LoadedTable] = []
        full_history: list[RepairHistoryEntry] = []
        all_assumptions: list[str] = []

        for table in tables:
            # PROTECT ORIGINAL: Always make deep copy of the DataFrame
            df_copy = table.dataframe.copy(deep=True)
            table_name = table.table_name

            for policy in policies:
                # Check if policy applies to this table
                if policy.affected_sources and table_name not in policy.affected_sources and table.source_path.name not in policy.affected_sources:
                    continue

                act = policy.selected_action.upper()
                params = policy.parameters

                if policy.issue_type == IssueType.DUPLICATE_ROWS:
                    df_copy = _apply_duplicate_policy(
                        df_copy, table_name, act, full_history, all_assumptions
                    )

                elif policy.issue_type == IssueType.MISSING_VALUES:
                    target_col = params.get("column")
                    df_copy = _apply_missing_policy(
                        df_copy, table_name, act, target_col, full_history, all_assumptions
                    )

                elif policy.issue_type == IssueType.AMBIGUOUS_DATE_FORMAT:
                    target_col = params.get("column") or (
                        policy.affected_sources[0] if policy.affected_sources else None
                    )
                    # If column not in params, pick first date-like column
                    if not target_col:
                        for c in df_copy.columns:
                            if "date" in c.lower() or "time" in c.lower():
                                target_col = c
                                break
                    if target_col:
                        df_copy = _apply_date_policy(
                            df_copy, table_name, act, target_col, full_history, all_assumptions
                        )

                elif policy.issue_type == IssueType.MIXED_CURRENCIES:
                    target_col = params.get("column")
                    df_copy = _apply_currency_policy(
                        df_copy, table_name, act, target_col, params, full_history, all_assumptions
                    )

            # Wrap into a new LoadedTable
            repaired_table = LoadedTable(
                source_path=table.source_path,
                file_type=table.file_type,
                table_name=table.table_name,
                sheet_name=table.sheet_name,
                column_names=list(df_copy.columns),
                row_count=len(df_copy),
                dataframe=df_copy,
            )
            repaired_tables.append(repaired_table)

        return repaired_tables, full_history, all_assumptions

    def expand_compare_policies(
        self,
        policies: list[RepairPolicy],
    ) -> tuple[list[list[RepairPolicy]], bool]:
        """
        Expand any policy with selected_action == 'COMPARE' into combinations
        of concrete single-action policies.

        Returns:
            (concrete_policy_sets, was_bounded)
        """
        expanded_dimensions: list[list[RepairPolicy]] = []

        for p in policies:
            if p.selected_action.upper() != "COMPARE":
                expanded_dimensions.append([p])
                continue

            # Expand COMPARE according to issue_type
            if p.issue_type == IssueType.DUPLICATE_ROWS:
                expanded_dimensions.append([
                    RepairPolicy(
                        issue_type=p.issue_type,
                        selected_action=DuplicateAction.KEEP.value,
                        parameters=p.parameters,
                        affected_sources=p.affected_sources,
                        rationale="World branch: KEEP duplicates",
                    ),
                    RepairPolicy(
                        issue_type=p.issue_type,
                        selected_action=DuplicateAction.EXACT_DEDUP.value,
                        parameters=p.parameters,
                        affected_sources=p.affected_sources,
                        rationale="World branch: EXACT_DEDUP",
                    ),
                ])

            elif p.issue_type == IssueType.MISSING_VALUES:
                expanded_dimensions.append([
                    RepairPolicy(
                        issue_type=p.issue_type,
                        selected_action=MissingValueAction.LEAVE.value,
                        parameters=p.parameters,
                        affected_sources=p.affected_sources,
                        rationale="World branch: LEAVE missing values",
                    ),
                    RepairPolicy(
                        issue_type=p.issue_type,
                        selected_action=MissingValueAction.DROP.value,
                        parameters=p.parameters,
                        affected_sources=p.affected_sources,
                        rationale="World branch: DROP missing rows",
                    ),
                ])

            elif p.issue_type == IssueType.AMBIGUOUS_DATE_FORMAT:
                expanded_dimensions.append([
                    RepairPolicy(
                        issue_type=p.issue_type,
                        selected_action=DateFormatAction.DD_MM_YYYY.value,
                        parameters=p.parameters,
                        affected_sources=p.affected_sources,
                        rationale="World branch: DD/MM/YYYY date interpretation",
                    ),
                    RepairPolicy(
                        issue_type=p.issue_type,
                        selected_action=DateFormatAction.MM_DD_YYYY.value,
                        parameters=p.parameters,
                        affected_sources=p.affected_sources,
                        rationale="World branch: MM/DD/YYYY date interpretation",
                    ),
                ])

            elif p.issue_type == IssueType.MIXED_CURRENCIES:
                branches = [
                    RepairPolicy(
                        issue_type=p.issue_type,
                        selected_action=CurrencyAction.KEEP_SEPARATE.value,
                        parameters=p.parameters,
                        affected_sources=p.affected_sources,
                        rationale="World branch: KEEP_SEPARATE currencies",
                    )
                ]
                if p.parameters.get("rates"):
                    branches.append(
                        RepairPolicy(
                            issue_type=p.issue_type,
                            selected_action=CurrencyAction.USE_SUPPLIED_RATES.value,
                            parameters=p.parameters,
                            affected_sources=p.affected_sources,
                            rationale="World branch: USE_SUPPLIED_RATES for currency conversion",
                        )
                    )
                expanded_dimensions.append(branches)

            else:
                # Fallback for other issues
                expanded_dimensions.append([p])

        # Compute Cartesian product
        all_combinations = list(product(*expanded_dimensions))
        total_combos = len(all_combinations)
        was_bounded = False

        if total_combos > self.max_worlds:
            # Deterministic bounding: take first max_worlds combinations
            all_combinations = all_combinations[: self.max_worlds]
            was_bounded = True

        concrete_sets = [list(combo) for combo in all_combinations]
        return concrete_sets, was_bounded

    def create_worlds(
        self,
        tables: list[LoadedTable],
        policies: list[RepairPolicy],
        output_dir: Path | None = None,
    ) -> list[RepairWorld]:
        """
        Create deterministic RepairWorlds by expanding COMPARE policies and
        applying transformations to copied DataFrames.
        """
        concrete_policy_sets, was_bounded = self.expand_compare_policies(policies)
        worlds: list[RepairWorld] = []

        source_refs = [str(t.source_path) for t in tables]

        for idx, pol_set in enumerate(concrete_policy_sets, start=1):
            world_id = f"world_{idx:03d}"
            desc_parts = [f"{p.issue_type.value}:{p.selected_action}" for p in pol_set]
            description = f"World {idx}: " + "; ".join(desc_parts)

            # Apply policies to copies
            repaired_tables, history, assumptions = self.apply_policies_to_tables(tables, pol_set)

            if was_bounded:
                assumptions.append(
                    f"World space bounded: evaluated {self.max_worlds} representative worlds."
                )

            # Compute deterministic hash of repaired tables
            combined_hashes = "".join(compute_table_sha256(t) for t in repaired_tables)
            world_hash = hashlib.sha256(combined_hashes.encode("utf-8")).hexdigest()

            # Optional persistence
            world_data_path = None
            if output_dir:
                w_dir = output_dir / world_id
                w_dir.mkdir(parents=True, exist_ok=True)
                for rt in repaired_tables:
                    out_csv = w_dir / f"{rt.table_name}.csv"
                    rt.dataframe.to_csv(out_csv, index=False)
                world_data_path = w_dir

            world = RepairWorld(
                world_id=world_id,
                description=description,
                policies=pol_set,
                source_file_refs=source_refs,
                world_data_path=world_data_path,
                world_hash=world_hash,
                repair_history=history,
                repaired_tables=repaired_tables,
                assumptions=assumptions,
                is_safe=True,
                safety_issues=[],
            )
            worlds.append(world)

        return worlds

    def create_worlds_from_ledger(
        self,
        tables: list[LoadedTable],
        ledger: DataQualityLedger,
        parameters: dict[str, Any] | None = None,
        output_dir: Path | None = None,
    ) -> list[RepairWorld]:
        """
        Automatically derive candidate COMPARE policies from audit issues in ledger,
        and generate all corresponding RepairWorlds.
        """
        params = parameters or {}
        policies: list[RepairPolicy] = []

        # Check detected issues in ledger
        has_dups = any(i.issue_type == IssueType.DUPLICATE_ROWS for i in ledger.all_issues)
        has_missing = any(i.issue_type == IssueType.MISSING_VALUES for i in ledger.all_issues)
        has_ambig_date = any(i.issue_type == IssueType.AMBIGUOUS_DATE_FORMAT for i in ledger.all_issues)
        has_mixed_curr = any(i.issue_type == IssueType.MIXED_CURRENCIES for i in ledger.all_issues)

        if has_dups:
            dup_action = params.get("DUPLICATE_ROWS", DuplicateAction.COMPARE.value)
            policies.append(
                RepairPolicy(
                    issue_type=IssueType.DUPLICATE_ROWS,
                    selected_action=dup_action,
                    rationale=f"Audit detected duplicate rows; policy {dup_action}.",
                )
            )

        if has_missing:
            # Find which columns have missing values
            missing_cols = list({
                col
                for i in ledger.all_issues if i.issue_type == IssueType.MISSING_VALUES
                for col in i.affected_columns
            })
            missing_action = params.get("MISSING_VALUES", MissingValueAction.COMPARE.value)
            policies.append(
                RepairPolicy(
                    issue_type=IssueType.MISSING_VALUES,
                    selected_action=missing_action,
                    parameters={"columns": missing_cols},
                    rationale=f"Audit detected missing values; policy {missing_action}.",
                )
            )

        if has_ambig_date:
            date_cols = list({
                col
                for i in ledger.all_issues if i.issue_type == IssueType.AMBIGUOUS_DATE_FORMAT
                for col in i.affected_columns
            })
            date_action = params.get("AMBIGUOUS_DATE_FORMAT", DateFormatAction.COMPARE.value)
            for dcol in date_cols:
                policies.append(
                    RepairPolicy(
                        issue_type=IssueType.AMBIGUOUS_DATE_FORMAT,
                        selected_action=date_action,
                        parameters={"column": dcol},
                        rationale=f"Audit detected ambiguous date format in '{dcol}'; policy {date_action}.",
                    )
                )

        if has_mixed_curr:
            curr_cols = list({
                col
                for i in ledger.all_issues if i.issue_type == IssueType.MIXED_CURRENCIES
                for col in i.affected_columns
            })
            for ccol in curr_cols:
                policies.append(
                    RepairPolicy(
                        issue_type=IssueType.MIXED_CURRENCIES,
                        selected_action=CurrencyAction.COMPARE.value,
                        parameters={"column": ccol, **params},
                        rationale=f"Audit detected mixed currencies in '{ccol}'; comparing KEEP_SEPARATE vs CONVERT.",
                    )
                )

        # If no issues were detected, create a single baseline world
        if not policies:
            policies.append(
                RepairPolicy(
                    issue_type=IssueType.DUPLICATE_ROWS,
                    selected_action=DuplicateAction.KEEP.value,
                    rationale="Data audit clean; using original data as World 1 baseline.",
                )
            )

        return self.create_worlds(tables, policies, output_dir=output_dir)
