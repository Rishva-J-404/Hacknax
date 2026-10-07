"""
tests/test_audit.py
-------------------
Tests for the ProofLens deterministic Data Audit engine (Phase 3).

Verifies all requirements:
1. Clean table produces no false critical issues.
2. Exact duplicate detection.
3. Duplicate count is correct.
4. Missing values detection.
5. Empty strings detection.
6. Whitespace-only values detection.
7. Numeric-like detection.
8. Mixed numeric/non-numeric detection.
9. Currency detection.
10. Unit detection.
11. Date detection.
12. Ambiguous date detection.
13. ID/key detection.
14. Multiple-table audit (cross-table orphan foreign keys, schema observations).
15. Original DataFrame is unchanged (read-only invariant).
16. DataQualityLedger JSON serialization and roundtrip.
17. Deterministic repeated audit produces equivalent results.

Uses deterministic fixtures in pytest tmp_path.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.audit import (
    ColumnProfile,
    DataIssue,
    DataQualityLedger,
    IssueSeverity,
    IssueType,
    TableProfile,
    audit_table,
    audit_tables,
)
from app.ingestion.contracts import DataSourceRef, FileType, LoadedTable
from app.ingestion.loader import load_file


# ---------------------------------------------------------------------------
# Helper: create LoadedTable from in-memory DataFrame
# ---------------------------------------------------------------------------

def _make_table(
    name: str,
    data: dict[str, list[str]],
    tmp_path: Path,
) -> LoadedTable:
    """Create a real LoadedTable written to a temporary CSV."""
    csv_file = tmp_path / f"{name}.csv"
    df = pd.DataFrame(data)
    df.to_csv(csv_file, index=False)
    # Load through real loader
    ref = DataSourceRef(path=csv_file, alias=name)
    return load_file(ref)[0]


# ---------------------------------------------------------------------------
# 1. Clean table test
# ---------------------------------------------------------------------------

def test_clean_table_produces_no_critical_issues(tmp_path: Path):
    table = _make_table(
        "clean_orders",
        {
            "order_id": ["101", "102", "103"],
            "amount": ["100", "200", "300"],
            "currency": ["INR", "INR", "INR"],
            "order_date": ["2025-01-15", "2025-01-16", "2025-01-17"],
        },
        tmp_path,
    )
    profile = audit_table(table)
    assert profile.row_count == 3
    assert profile.column_count == 4
    # No critical or high issues
    critical_issues = [i for i in profile.issues if i.severity == IssueSeverity.CRITICAL]
    assert len(critical_issues) == 0


# ---------------------------------------------------------------------------
# 2 & 3. Exact duplicate row detection & count
# ---------------------------------------------------------------------------

def test_exact_duplicate_detection_and_count(tmp_path: Path):
    table = _make_table(
        "dup_table",
        {
            "id": ["1", "2", "1", "3", "2"],
            "val": ["A", "B", "A", "C", "B"],
        },
        tmp_path,
    )
    profile = audit_table(table)
    dup_issues = [i for i in profile.issues if i.issue_type == IssueType.DUPLICATE_ROWS]
    assert len(dup_issues) == 1
    issue = dup_issues[0]
    assert issue.evidence["duplicate_row_count"] == 2
    assert issue.evidence["original_row_count"] == 5
    assert issue.evidence["unique_row_count"] == 3


# ---------------------------------------------------------------------------
# 4, 5, 6. Missing values, empty strings, whitespace-only values
# ---------------------------------------------------------------------------

def test_missing_values_detection(tmp_path: Path):
    table = _make_table(
        "missing_table",
        {
            "id": ["1", "2", "3", "4", "5"],
            "notes": ["ok", "N/A", "null", "none", "fine"],
        },
        tmp_path,
    )
    profile = audit_table(table)
    missing_issues = [
        i for i in profile.issues
        if i.issue_type == IssueType.MISSING_VALUES and "notes" in i.affected_columns
    ]
    assert len(missing_issues) == 1
    assert missing_issues[0].evidence["missing_count"] == 3


def test_empty_strings_and_whitespace_only_detected_as_missing(tmp_path: Path):
    table = _make_table(
        "empty_strings_table",
        {
            "id": ["1", "2", "3", "4"],
            "remarks": ["good", "", "   ", "   \t  "],
        },
        tmp_path,
    )
    profile = audit_table(table)
    missing_issues = [
        i for i in profile.issues
        if i.issue_type == IssueType.MISSING_VALUES and "remarks" in i.affected_columns
    ]
    assert len(missing_issues) == 1
    assert missing_issues[0].evidence["missing_count"] == 3
    assert missing_issues[0].evidence["missing_pct"] == 0.75


# ---------------------------------------------------------------------------
# 7. Numeric-like column detection
# ---------------------------------------------------------------------------

def test_numeric_like_detection(tmp_path: Path):
    table = _make_table(
        "numeric_table",
        {
            "price": ["10", "20.5", "1,000", "-5"],
        },
        tmp_path,
    )
    profile = audit_table(table)
    price_prof = next(p for p in profile.column_profiles if p.column_name == "price")
    assert price_prof.inferred_type == "numeric"
    assert price_prof.missing_count == 0


# ---------------------------------------------------------------------------
# 8. Mixed numeric and non-numeric detection
# ---------------------------------------------------------------------------

def test_mixed_numeric_non_numeric_detection(tmp_path: Path):
    table = _make_table(
        "mixed_num_table",
        {
            "id": ["1", "2", "3"],
            "score": ["100", "pending", "200"],
        },
        tmp_path,
    )
    profile = audit_table(table)
    mixed_issues = [
        i for i in profile.issues
        if i.issue_type == IssueType.ANOMALY and "score" in i.affected_columns
    ]
    assert len(mixed_issues) == 1
    assert mixed_issues[0].evidence["numeric_count"] == 2
    assert mixed_issues[0].evidence["non_numeric_count"] == 1
    assert "pending" in mixed_issues[0].evidence["sample_non_numeric"]


# ---------------------------------------------------------------------------
# 9. Currency indicators and mixed currencies detection
# ---------------------------------------------------------------------------

def test_mixed_currencies_detection(tmp_path: Path):
    table = _make_table(
        "currency_table",
        {
            "id": ["1", "2", "3"],
            "amount": ["₹500", "$100", "₹1200"],
        },
        tmp_path,
    )
    profile = audit_table(table)
    curr_issues = [
        i for i in profile.issues
        if i.issue_type == IssueType.MIXED_CURRENCIES
    ]
    assert len(curr_issues) == 1
    assert curr_issues[0].severity == IssueSeverity.CRITICAL
    assert "INR" in curr_issues[0].evidence["currencies_detected"]
    assert "USD" in curr_issues[0].evidence["currencies_detected"]


def test_dedicated_currency_column_detected(tmp_path: Path):
    table = _make_table(
        "curr_col_table",
        {
            "id": ["1", "2", "3"],
            "currency": ["USD", "EUR", "USD"],
        },
        tmp_path,
    )
    profile = audit_table(table)
    curr_issues = [
        i for i in profile.issues
        if i.issue_type == IssueType.MIXED_CURRENCIES and "currency" in i.affected_columns
    ]
    assert len(curr_issues) == 1
    assert "USD" in curr_issues[0].evidence["currencies_detected"]
    assert "EUR" in curr_issues[0].evidence["currencies_detected"]


# ---------------------------------------------------------------------------
# 10. Unit detection and conflicting mixed units
# ---------------------------------------------------------------------------

def test_unit_detection_and_inconsistency(tmp_path: Path):
    table = _make_table(
        "units_table",
        {
            "id": ["1", "2", "3"],
            "weight": ["5 kg", "500 g", "10 kg"],
        },
        tmp_path,
    )
    profile = audit_table(table)
    unit_issues = [
        i for i in profile.issues
        if i.issue_type == IssueType.MIXED_UNITS
    ]
    assert len(unit_issues) == 1
    assert "kg" in unit_issues[0].evidence["units_detected"]
    assert "g" in unit_issues[0].evidence["units_detected"]


# ---------------------------------------------------------------------------
# 11 & 12. Date detection and ambiguous date detection
# ---------------------------------------------------------------------------

def test_unambiguous_iso_date_detection(tmp_path: Path):
    table = _make_table(
        "iso_date_table",
        {
            "created_at": ["2025-01-02", "2025-02-03", "2025-03-04"],
        },
        tmp_path,
    )
    profile = audit_table(table)
    date_prof = next(p for p in profile.column_profiles if p.column_name == "created_at")
    assert date_prof.inferred_type == "date"
    # ISO date has 4-digit year first, so it is unambiguous
    ambig_issues = [i for i in profile.issues if i.issue_type == IssueType.AMBIGUOUS_DATE_FORMAT]
    assert len(ambig_issues) == 0


def test_ambiguous_date_detection(tmp_path: Path):
    table = _make_table(
        "ambig_date_table",
        {
            "transaction_date": ["01/02/2025", "03/04/2025", "05/06/2025"],
        },
        tmp_path,
    )
    profile = audit_table(table)
    ambig_issues = [
        i for i in profile.issues
        if i.issue_type == IssueType.AMBIGUOUS_DATE_FORMAT
    ]
    assert len(ambig_issues) == 1
    assert "01/02/2025" in ambig_issues[0].evidence["sample_ambiguous_dates"]
    assert "DD/MM/YYYY" in ambig_issues[0].evidence["possible_interpretations"]
    assert "MM/DD/YYYY" in ambig_issues[0].evidence["possible_interpretations"]


# ---------------------------------------------------------------------------
# 13. ID/Key detection & Duplicate Key & Contradictory values
# ---------------------------------------------------------------------------

def test_candidate_key_and_duplicate_key_detection(tmp_path: Path):
    table = _make_table(
        "keys_table",
        {
            "customer_id": ["C01", "C02", "C01"],
            "name": ["Alice", "Bob", "Alice"],
        },
        tmp_path,
    )
    profile = audit_table(table)
    key_issues = [
        i for i in profile.issues
        if i.issue_type == IssueType.DUPLICATE_KEYS and "customer_id" in i.affected_columns
    ]
    assert len(key_issues) == 1
    assert key_issues[0].evidence["duplicate_key_count"] == 1
    assert "C01" in key_issues[0].evidence["sample_duplicate_keys"]


def test_contradictory_values_under_duplicate_key(tmp_path: Path):
    table = _make_table(
        "conflict_table",
        {
            "order_id": ["1001", "1002", "1001"],
            "customer_name": ["Alice", "Bob", "Charlie"],  # 1001 mapped to Alice and Charlie
        },
        tmp_path,
    )
    profile = audit_table(table)
    conflict_issues = [
        i for i in profile.issues
        if i.issue_type == IssueType.CONTRADICTORY_VALUES
    ]
    assert len(conflict_issues) == 1
    assert conflict_issues[0].severity == IssueSeverity.CRITICAL


# ---------------------------------------------------------------------------
# 14. Multiple-table audit (Cross-table checks)
# ---------------------------------------------------------------------------

def test_multiple_table_audit_and_orphan_keys(tmp_path: Path):
    t_orders = _make_table(
        "orders",
        {
            "order_id": ["101", "102"],
            "amount": ["50", "80"],
        },
        tmp_path,
    )
    t_shipments = _make_table(
        "shipments",
        {
            "shipment_id": ["S1", "S2", "S3"],
            "order_id": ["101", "102", "999"],  # 999 does not exist in orders!
        },
        tmp_path,
    )
    ledger = audit_tables([t_orders, t_shipments], session_id="test_multi")
    assert len(ledger.table_profiles) == 2

    orphan_issues = [
        i for i in ledger.all_issues
        if i.issue_type == IssueType.ORPHAN_FOREIGN_KEY
    ]
    assert len(orphan_issues) == 1
    assert "999" in orphan_issues[0].evidence["sample_orphans"]


# ---------------------------------------------------------------------------
# 15. Invariant: Original DataFrame is NEVER modified
# ---------------------------------------------------------------------------

def test_original_dataframe_is_unchanged(tmp_path: Path):
    table = _make_table(
        "unchanged_check",
        {
            "order_id": ["101", "102", "101"],
            "amount": ["$50", "₹100", "NA"],
            "date": ["01/02/2025", "03/04/2025", "2025-01-01"],
        },
        tmp_path,
    )
    df_before = table.dataframe.copy(deep=True)
    _ = audit_table(table)
    _ = audit_tables([table])

    pd.testing.assert_frame_equal(table.dataframe, df_before)


# ---------------------------------------------------------------------------
# 16. DataQualityLedger JSON serialization and roundtrip
# ---------------------------------------------------------------------------

def test_ledger_json_serialization_and_roundtrip(tmp_path: Path):
    table = _make_table(
        "ledger_roundtrip",
        {
            "id": ["1", "2"],
            "val": ["A", "B"],
        },
        tmp_path,
    )
    ledger = audit_tables([table], session_id="sess_123")
    json_str = ledger.model_dump_json()
    restored = DataQualityLedger.model_validate_json(json_str)

    assert restored.session_id == "sess_123"
    assert len(restored.table_profiles) == 1
    assert restored.table_profiles[0].source == "ledger_roundtrip"
    assert restored.has_critical_issues == ledger.has_critical_issues


# ---------------------------------------------------------------------------
# 17. Deterministic repeated audit produces equivalent results
# ---------------------------------------------------------------------------

def test_deterministic_repeated_audit(tmp_path: Path):
    table = _make_table(
        "repeatable_table",
        {
            "col_a": ["1", "2", "1", "4"],
            "col_b": ["₹100", "$200", "₹100", "€300"],
            "date": ["01/02/2025", "15/01/2025", "01/02/2025", "2025-05-01"],
        },
        tmp_path,
    )
    ledger1 = audit_tables([table], session_id="run_1")
    ledger2 = audit_tables([table], session_id="run_1")

    assert ledger1.has_critical_issues == ledger2.has_critical_issues
    assert len(ledger1.all_issues) == len(ledger2.all_issues)
    for i1, i2 in zip(ledger1.all_issues, ledger2.all_issues):
        assert i1.issue_type == i2.issue_type
        assert i1.severity == i2.severity
        assert i1.affected_source == i2.affected_source
        assert i1.description == i2.description
        assert i1.evidence == i2.evidence
