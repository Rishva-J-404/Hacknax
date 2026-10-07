"""
tests/test_repair.py
--------------------
Tests for Phase 4: ProofLens Repair & Ambiguity Decision Center.

Verifies all required behaviors:
1. KEEP preserves row count and values.
2. EXACT_DEDUP removes only exact duplicate rows.
3. Original dataframe is unchanged (read-only invariant).
4. DROP removes rows with missing values.
5. FILL_ZERO works only on numeric-compatible columns.
6. FILL_MEDIAN works on numeric-compatible columns.
7. Invalid median fill is rejected.
8. Ambiguous DD/MM dates can be represented.
9. Ambiguous MM/DD dates can be represented.
10. Invalid date conversion is rejected.
11. Currency conversion without rates is rejected.
12. Currency conversion with explicit supplied rates works.
13. COMPARE generates multiple worlds.
14. World IDs are deterministic.
15. Same input + same policy produces identical result.
16. Repair history records transformations.
17. MAX_WORLDS prevents uncontrolled explosion.
18. Original source data remains unchanged across ALL worlds.
19. No silent repair occurs (every operation recorded in history).
20. Unsupported fuzzy deduplication is rejected.
21. Integration with Phase 3 DataQualityLedger.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.audit import audit_tables
from app.audit.contracts import IssueType
from app.ingestion.contracts import FileType, LoadedTable
from app.repair import (
    CurrencyAction,
    DateFormatAction,
    DuplicateAction,
    MissingValueAction,
    RepairEngine,
    RepairError,
    RepairPolicy,
    RepairWorld,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_table(name: str, data: dict[str, list[str]]) -> LoadedTable:
    """Create in-memory LoadedTable with string DataFrame."""
    df = pd.DataFrame(data).astype(str)
    return LoadedTable(
        source_path=Path(f"data/{name}.csv"),
        file_type=FileType.CSV,
        table_name=name,
        sheet_name=None,
        column_names=list(df.columns),
        row_count=len(df),
        dataframe=df,
    )


# ---------------------------------------------------------------------------
# 1. KEEP preserves row count and values
# ---------------------------------------------------------------------------

def test_keep_preserves_rows_and_values():
    table = _make_table("test_keep", {"id": ["1", "1", "2"], "val": ["A", "A", "B"]})
    engine = RepairEngine()
    policy = RepairPolicy(
        issue_type=IssueType.DUPLICATE_ROWS,
        selected_action=DuplicateAction.KEEP.value,
        rationale="Keep all duplicates",
    )
    worlds = engine.create_worlds([table], [policy])
    assert len(worlds) == 1
    repaired_df = worlds[0].repaired_tables[0].dataframe
    assert len(repaired_df) == 3
    assert repaired_df["id"].tolist() == ["1", "1", "2"]


# ---------------------------------------------------------------------------
# 2. EXACT_DEDUP removes only exact duplicate rows
# ---------------------------------------------------------------------------

def test_exact_dedup_removes_exact_duplicates():
    table = _make_table("test_dedup", {"id": ["1", "1", "2"], "val": ["A", "A", "B"]})
    engine = RepairEngine()
    policy = RepairPolicy(
        issue_type=IssueType.DUPLICATE_ROWS,
        selected_action=DuplicateAction.EXACT_DEDUP.value,
        rationale="Exact complete-row deduplication",
    )
    worlds = engine.create_worlds([table], [policy])
    assert len(worlds) == 1
    repaired_df = worlds[0].repaired_tables[0].dataframe
    assert len(repaired_df) == 2
    assert repaired_df["id"].tolist() == ["1", "2"]
    assert repaired_df["val"].tolist() == ["A", "B"]


# ---------------------------------------------------------------------------
# 3. Original dataframe is unchanged
# ---------------------------------------------------------------------------

def test_original_dataframe_is_unchanged():
    table = _make_table("test_immutability", {"id": ["1", "1"], "val": ["A", "A"]})
    df_before = table.dataframe.copy(deep=True)
    engine = RepairEngine()
    policy = RepairPolicy(
        issue_type=IssueType.DUPLICATE_ROWS,
        selected_action=DuplicateAction.EXACT_DEDUP.value,
        rationale="Dedup",
    )
    _ = engine.create_worlds([table], [policy])
    pd.testing.assert_frame_equal(table.dataframe, df_before)


# ---------------------------------------------------------------------------
# 4. DROP removes rows with missing values
# ---------------------------------------------------------------------------

def test_drop_removes_missing_rows():
    table = _make_table(
        "test_drop",
        {"id": ["1", "2", "3", "4"], "val": ["A", "", "C", "NA"]},
    )
    engine = RepairEngine()
    policy = RepairPolicy(
        issue_type=IssueType.MISSING_VALUES,
        selected_action=MissingValueAction.DROP.value,
        parameters={"column": "val"},
        rationale="Drop missing values in val",
    )
    worlds = engine.create_worlds([table], [policy])
    repaired_df = worlds[0].repaired_tables[0].dataframe
    assert len(repaired_df) == 2
    assert repaired_df["id"].tolist() == ["1", "3"]


# ---------------------------------------------------------------------------
# 5. FILL_ZERO works only on numeric-compatible columns
# ---------------------------------------------------------------------------

def test_fill_zero_works_on_numeric():
    table = _make_table(
        "test_fill_zero",
        {"id": ["1", "2", "3"], "amount": ["100", "", "300"]},
    )
    engine = RepairEngine()
    policy = RepairPolicy(
        issue_type=IssueType.MISSING_VALUES,
        selected_action=MissingValueAction.FILL_ZERO.value,
        parameters={"column": "amount"},
        rationale="Fill missing amounts with 0",
    )
    worlds = engine.create_worlds([table], [policy])
    repaired_df = worlds[0].repaired_tables[0].dataframe
    assert repaired_df["amount"].tolist() == ["100", "0", "300"]


def test_fill_zero_rejected_on_text_column():
    table = _make_table(
        "test_fill_zero_fail",
        {"id": ["1", "2", "3"], "status": ["Active", "", "Pending"]},
    )
    engine = RepairEngine()
    policy = RepairPolicy(
        issue_type=IssueType.MISSING_VALUES,
        selected_action=MissingValueAction.FILL_ZERO.value,
        parameters={"column": "status"},
        rationale="Try fill zero on text",
    )
    with pytest.raises(RepairError) as exc_info:
        engine.create_worlds([table], [policy])
    assert exc_info.value.reason == "NON_NUMERIC_COLUMN"


# ---------------------------------------------------------------------------
# 6 & 7. FILL_MEDIAN works on numeric and is rejected on text
# ---------------------------------------------------------------------------

def test_fill_median_works_on_numeric():
    # values: 10, 20, 30 -> median = 20
    table = _make_table(
        "test_median",
        {"id": ["1", "2", "3", "4"], "val": ["10", "20", "", "30"]},
    )
    engine = RepairEngine()
    policy = RepairPolicy(
        issue_type=IssueType.MISSING_VALUES,
        selected_action=MissingValueAction.FILL_MEDIAN.value,
        parameters={"column": "val"},
        rationale="Fill median",
    )
    worlds = engine.create_worlds([table], [policy])
    repaired_df = worlds[0].repaired_tables[0].dataframe
    assert repaired_df["val"].tolist() == ["10", "20", "20", "30"]


def test_fill_median_rejected_on_non_numeric():
    table = _make_table(
        "test_median_fail",
        {"id": ["1", "2"], "name": ["Alice", ""]},
    )
    engine = RepairEngine()
    policy = RepairPolicy(
        issue_type=IssueType.MISSING_VALUES,
        selected_action=MissingValueAction.FILL_MEDIAN.value,
        parameters={"column": "name"},
        rationale="Try median on text",
    )
    with pytest.raises(RepairError) as exc_info:
        engine.create_worlds([table], [policy])
    assert exc_info.value.reason == "NON_NUMERIC_COLUMN"


# ---------------------------------------------------------------------------
# 8 & 9. Ambiguous DD/MM and MM/DD date representation
# ---------------------------------------------------------------------------

def test_ambiguous_dates_dd_mm():
    table = _make_table("test_date_dd", {"date": ["01/02/2025"]})
    engine = RepairEngine()
    policy = RepairPolicy(
        issue_type=IssueType.AMBIGUOUS_DATE_FORMAT,
        selected_action=DateFormatAction.DD_MM_YYYY.value,
        parameters={"column": "date"},
        rationale="DD/MM/YYYY",
    )
    worlds = engine.create_worlds([table], [policy])
    repaired_df = worlds[0].repaired_tables[0].dataframe
    # 01/02/2025 as DD/MM -> 01/02/2025 (day 1, month 2)
    assert repaired_df["date"].iloc[0] == "01/02/2025"
    assert "Interpreted date column 'date' as DD_MM_YYYY." in worlds[0].assumptions


def test_ambiguous_dates_mm_dd():
    table = _make_table("test_date_mm", {"date": ["01/02/2025"]})
    engine = RepairEngine()
    policy = RepairPolicy(
        issue_type=IssueType.AMBIGUOUS_DATE_FORMAT,
        selected_action=DateFormatAction.MM_DD_YYYY.value,
        parameters={"column": "date"},
        rationale="MM/DD/YYYY",
    )
    worlds = engine.create_worlds([table], [policy])
    repaired_df = worlds[0].repaired_tables[0].dataframe
    # 01/02/2025 as MM/DD -> formatted as MM/DD/YYYY = month 1, day 2 -> 01/02/2025
    # Let's test with 05/10/2025
    table2 = _make_table("test_date_mm2", {"date": ["05/10/2025"]})
    # If policy is MM_DD_YYYY, 05 is month, 10 is day
    w2 = engine.create_worlds([table2], [policy])[0]
    assert w2.repaired_tables[0].dataframe["date"].iloc[0] == "05/10/2025"


# ---------------------------------------------------------------------------
# 10. Invalid date conversion is rejected
# ---------------------------------------------------------------------------

def test_invalid_date_conversion_rejected():
    table = _make_table("test_bad_date", {"date": ["not-a-date", "99/99/9999"]})
    engine = RepairEngine()
    policy = RepairPolicy(
        issue_type=IssueType.AMBIGUOUS_DATE_FORMAT,
        selected_action=DateFormatAction.DD_MM_YYYY.value,
        parameters={"column": "date"},
        rationale="Try convert invalid date",
    )
    with pytest.raises(RepairError) as exc_info:
        engine.create_worlds([table], [policy])
    assert exc_info.value.reason == "UNPARSEABLE_DATE"


# ---------------------------------------------------------------------------
# 11 & 12. Currency conversion with and without supplied rates
# ---------------------------------------------------------------------------

def test_currency_conversion_without_rates_rejected():
    table = _make_table("test_curr_fail", {"amount": ["$100", "₹500"]})
    engine = RepairEngine()
    policy = RepairPolicy(
        issue_type=IssueType.MIXED_CURRENCIES,
        selected_action=CurrencyAction.USE_SUPPLIED_RATES.value,
        parameters={"column": "amount"},  # No rates provided!
        rationale="Convert without rates",
    )
    with pytest.raises(RepairError) as exc_info:
        engine.create_worlds([table], [policy])
    assert exc_info.value.reason == "MISSING_EXCHANGE_RATES"


def test_currency_conversion_with_supplied_rates():
    table = _make_table("test_curr_ok", {"amount": ["$100", "₹500"]})
    engine = RepairEngine()
    policy = RepairPolicy(
        issue_type=IssueType.MIXED_CURRENCIES,
        selected_action=CurrencyAction.USE_SUPPLIED_RATES.value,
        parameters={
            "column": "amount",
            "base_currency": "INR",
            "rates": {"USD": 80.0, "INR": 1.0},
        },
        rationale="Convert to INR at 80",
    )
    worlds = engine.create_worlds([table], [policy])
    repaired_df = worlds[0].repaired_tables[0].dataframe
    # $100 * 80 = 8000; ₹500 * 1 = 500
    assert repaired_df["amount"].tolist() == ["8000", "500"]


# ---------------------------------------------------------------------------
# 13. COMPARE generates multiple worlds
# ---------------------------------------------------------------------------

def test_compare_generates_multiple_worlds():
    table = _make_table("test_compare", {"id": ["1", "1", "2"], "val": ["A", "A", "B"]})
    engine = RepairEngine()
    policy = RepairPolicy(
        issue_type=IssueType.DUPLICATE_ROWS,
        selected_action=DuplicateAction.COMPARE.value,
        rationale="Compare KEEP vs EXACT_DEDUP",
    )
    worlds = engine.create_worlds([table], [policy])
    assert len(worlds) == 2
    # World 1: KEEP (3 rows)
    assert len(worlds[0].repaired_tables[0].dataframe) == 3
    # World 2: EXACT_DEDUP (2 rows)
    assert len(worlds[1].repaired_tables[0].dataframe) == 2


# ---------------------------------------------------------------------------
# 14 & 15. World IDs are deterministic & same input produces identical result
# ---------------------------------------------------------------------------

def test_world_ids_and_results_are_deterministic():
    table = _make_table("test_det", {"id": ["1", "1", "2"]})
    engine = RepairEngine()
    policy = RepairPolicy(
        issue_type=IssueType.DUPLICATE_ROWS,
        selected_action=DuplicateAction.COMPARE.value,
        rationale="Compare",
    )
    worlds_run_1 = engine.create_worlds([table], [policy])
    worlds_run_2 = engine.create_worlds([table], [policy])

    assert [w.world_id for w in worlds_run_1] == ["world_001", "world_002"]
    assert [w.world_id for w in worlds_run_1] == [w.world_id for w in worlds_run_2]
    assert worlds_run_1[0].world_hash == worlds_run_2[0].world_hash
    assert worlds_run_1[1].world_hash == worlds_run_2[1].world_hash


# ---------------------------------------------------------------------------
# 16 & 19. Repair history records transformations (no silent repair)
# ---------------------------------------------------------------------------

def test_repair_history_records_transformations():
    table = _make_table("test_hist", {"id": ["1", "1", "2"], "v": ["10", "", "30"]})
    engine = RepairEngine()
    policies = [
        RepairPolicy(
            issue_type=IssueType.DUPLICATE_ROWS,
            selected_action=DuplicateAction.EXACT_DEDUP.value,
            rationale="Dedup",
        ),
        RepairPolicy(
            issue_type=IssueType.MISSING_VALUES,
            selected_action=MissingValueAction.FILL_ZERO.value,
            parameters={"column": "v"},
            rationale="Fill 0",
        ),
    ]
    worlds = engine.create_worlds([table], policies)
    hist = worlds[0].repair_history
    assert len(hist) >= 2
    ops = [h.operation for h in hist]
    assert "EXACT_DEDUP" in ops
    assert "FILL_ZERO" in ops
    dedup_entry = next(h for h in hist if h.operation == "EXACT_DEDUP")
    assert dedup_entry.rows_before == 3
    assert dedup_entry.rows_after == 3  # not exact full-row duplicate
    fill_entry = next(h for h in hist if h.operation == "FILL_ZERO")
    assert fill_entry.affected_rows == 1


# ---------------------------------------------------------------------------
# 17. MAX_WORLDS prevents uncontrolled explosion
# ---------------------------------------------------------------------------

def test_max_worlds_bounds_explosion():
    table = _make_table("test_multidim", {"a": ["1", "1"], "b": ["", "2"], "c": ["01/02/2025", "03/04/2025"]})
    engine = RepairEngine(max_worlds=4)
    # 3 COMPARE dimensions: 2 * 2 * 2 = 8 combinations
    policies = [
        RepairPolicy(issue_type=IssueType.DUPLICATE_ROWS, selected_action="COMPARE", rationale="d"),
        RepairPolicy(issue_type=IssueType.MISSING_VALUES, selected_action="COMPARE", rationale="m"),
        RepairPolicy(issue_type=IssueType.AMBIGUOUS_DATE_FORMAT, selected_action="COMPARE", parameters={"column": "c"}, rationale="dt"),
    ]
    worlds = engine.create_worlds([table], policies)
    assert len(worlds) == 4
    # All worlds record bounded world space assumption
    assert any("World space bounded" in a for a in worlds[0].assumptions)


# ---------------------------------------------------------------------------
# 18. Original source data remains unchanged across ALL worlds
# ---------------------------------------------------------------------------

def test_original_data_unchanged_across_all_worlds():
    table = _make_table("test_multiworld_immut", {"a": ["1", "1", "2"], "b": ["10", "", "30"]})
    df_orig = table.dataframe.copy(deep=True)
    engine = RepairEngine()
    policies = [
        RepairPolicy(issue_type=IssueType.DUPLICATE_ROWS, selected_action="COMPARE", rationale="d"),
        RepairPolicy(issue_type=IssueType.MISSING_VALUES, selected_action="COMPARE", rationale="m"),
    ]
    worlds = engine.create_worlds([table], policies)
    assert len(worlds) == 4
    # Invariant check
    pd.testing.assert_frame_equal(table.dataframe, df_orig)


# ---------------------------------------------------------------------------
# 20. Unsupported fuzzy deduplication is rejected
# ---------------------------------------------------------------------------

def test_unsupported_fuzzy_dedup_rejected():
    table = _make_table("test_fuzzy", {"a": ["Alice", "Alce"]})
    engine = RepairEngine()
    policy = RepairPolicy(
        issue_type=IssueType.DUPLICATE_ROWS,
        selected_action="FUZZY_DEDUP",
        rationale="Fuzzy deduplication",
    )
    with pytest.raises(RepairError) as exc_info:
        engine.create_worlds([table], [policy])
    assert exc_info.value.reason == "UNSUPPORTED_REPAIR"


# ---------------------------------------------------------------------------
# 21. Integration with Phase 3 DataQualityLedger
# ---------------------------------------------------------------------------

def test_integration_with_data_quality_ledger():
    table = _make_table(
        "orders_audit",
        {
            "order_id": ["101", "101", "102"],
            "amount": ["100", "", "300"],
            "date": ["01/02/2025", "01/02/2025", "05/06/2025"],
        },
    )
    ledger = audit_tables([table], session_id="test_sess")
    assert len(ledger.all_issues) > 0

    engine = RepairEngine()
    worlds = engine.create_worlds_from_ledger([table], ledger)
    assert len(worlds) >= 2
    # Verify each world has distinct policies and non-empty repaired_tables
    for w in worlds:
        assert isinstance(w, RepairWorld)
        assert len(w.repaired_tables) == 1
        assert len(w.repair_history) > 0
        assert w.world_hash is not None
