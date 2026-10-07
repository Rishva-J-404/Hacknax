"""
tests/test_ingestion.py
-----------------------
Tests for the ProofLens ingestion layer (Phase 2).

Scope:
  - File-type detection (supported and unsupported extensions).
  - CSV loading: columns, rows, values, empty file.
  - XLSX loading: single sheet, multiple sheets.
  - JSON loading: flat array-of-objects, empty array.
  - Error paths: missing file, unsupported type, nested JSON.
  - Value preservation: leading zeros, spaces, "NA" strings, mixed case
    are all stored exactly as they appear in the source file.

NOT tested here:
  - Data cleaning (not implemented — by design).
  - Audit, repair, execution, verification (not yet implemented).

All test files are written to pytest's tmp_path fixture directory.
No files are written permanently to data/original/.

Run with:
  .venv\\Scripts\\pytest tests/test_ingestion.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from app.ingestion.contracts import (
    AnalysisRequest,
    DataSourceRef,
    FileType,
    IngestionError,
    LoadedTable,
)
from app.ingestion.loader import detect_file_type, load_file


# =============================================================================
# Helpers
# =============================================================================

def _write_csv(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _write_xlsx(path: Path, sheets: dict[str, list[dict]]) -> None:
    """Write an XLSX workbook with one sheet per key in *sheets*."""
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, rows in sheets.items():
            df = pd.DataFrame(rows)
            df.to_excel(writer, sheet_name=sheet_name, index=False)


# =============================================================================
# 1. File-type detection
# =============================================================================

class TestFileTypeDetection:
    def test_csv_extension(self, tmp_path: Path):
        p = tmp_path / "orders.csv"
        p.write_text("a,b\n1,2\n")
        assert detect_file_type(p) == FileType.CSV

    def test_xlsx_extension(self, tmp_path: Path):
        p = tmp_path / "orders.xlsx"
        p.write_bytes(b"")          # content not read by detect_file_type
        assert detect_file_type(p) == FileType.XLSX

    def test_xls_extension(self, tmp_path: Path):
        p = tmp_path / "legacy.xls"
        p.write_bytes(b"")
        assert detect_file_type(p) == FileType.XLSX

    def test_json_extension(self, tmp_path: Path):
        p = tmp_path / "records.json"
        p.write_text("[]")
        assert detect_file_type(p) == FileType.JSON

    def test_pdf_raises_ingestion_error(self, tmp_path: Path):
        p = tmp_path / "report.pdf"
        p.write_bytes(b"%PDF-1.4")
        with pytest.raises(IngestionError) as exc_info:
            detect_file_type(p)
        assert exc_info.value.reason == "UNSUPPORTED_FILE_TYPE"

    def test_txt_raises_ingestion_error(self, tmp_path: Path):
        p = tmp_path / "notes.txt"
        p.write_text("hello")
        with pytest.raises(IngestionError) as exc_info:
            detect_file_type(p)
        assert exc_info.value.reason == "UNSUPPORTED_FILE_TYPE"

    def test_extension_is_case_insensitive(self, tmp_path: Path):
        p = tmp_path / "data.CSV"
        p.write_text("a,b\n1,2\n")
        assert detect_file_type(p) == FileType.CSV


# =============================================================================
# 2. CSV loading
# =============================================================================

class TestCSVLoading:
    def test_basic_csv(self, tmp_path: Path):
        p = tmp_path / "orders.csv"
        _write_csv(p, "order_id,revenue,currency\n1001,500,INR\n1002,300,USD\n")
        ref = DataSourceRef(path=p)
        tables = load_file(ref)

        assert len(tables) == 1
        t = tables[0]
        assert isinstance(t, LoadedTable)
        assert t.file_type == FileType.CSV
        assert t.sheet_name is None
        assert t.table_name == "orders"
        assert t.column_names == ["order_id", "revenue", "currency"]
        assert t.row_count == 2

    def test_csv_with_alias(self, tmp_path: Path):
        p = tmp_path / "raw_data.csv"
        _write_csv(p, "x,y\n1,2\n")
        ref = DataSourceRef(path=p, alias="my_table")
        tables = load_file(ref)
        assert tables[0].table_name == "my_table"

    def test_csv_source_path_preserved(self, tmp_path: Path):
        p = tmp_path / "orders.csv"
        _write_csv(p, "a,b\n1,2\n")
        ref = DataSourceRef(path=p)
        t = load_file(ref)[0]
        assert t.source_path == p

    def test_csv_row_count_matches_dataframe(self, tmp_path: Path):
        p = tmp_path / "data.csv"
        _write_csv(p, "col\n" + "\n".join(str(i) for i in range(100)))
        ref = DataSourceRef(path=p)
        t = load_file(ref)[0]
        assert t.row_count == 100
        assert t.row_count == len(t.dataframe)

    def test_csv_column_names_match_dataframe(self, tmp_path: Path):
        p = tmp_path / "data.csv"
        _write_csv(p, "Alpha,Beta,Gamma\n1,2,3\n")
        ref = DataSourceRef(path=p)
        t = load_file(ref)[0]
        assert t.column_names == list(t.dataframe.columns)
        assert t.column_names == ["Alpha", "Beta", "Gamma"]

    def test_csv_to_records(self, tmp_path: Path):
        p = tmp_path / "data.csv"
        _write_csv(p, "name,val\nfoo,10\nbar,20\n")
        ref = DataSourceRef(path=p)
        t = load_file(ref)[0]
        records = t.to_records()
        assert records == [{"name": "foo", "val": "10"}, {"name": "bar", "val": "20"}]


# =============================================================================
# 3. XLSX single-sheet loading
# =============================================================================

class TestXLSXSingleSheet:
    def test_single_sheet(self, tmp_path: Path):
        p = tmp_path / "sales.xlsx"
        _write_xlsx(p, {"Sheet1": [{"product": "A", "qty": 10}, {"product": "B", "qty": 5}]})
        ref = DataSourceRef(path=p)
        tables = load_file(ref)

        assert len(tables) == 1
        t = tables[0]
        assert t.file_type == FileType.XLSX
        assert t.sheet_name == "Sheet1"
        assert t.table_name == "sales.Sheet1"
        assert t.column_names == ["product", "qty"]
        assert t.row_count == 2

    def test_single_sheet_source_path_preserved(self, tmp_path: Path):
        p = tmp_path / "report.xlsx"
        _write_xlsx(p, {"Data": [{"x": 1}]})
        ref = DataSourceRef(path=p)
        t = load_file(ref)[0]
        assert t.source_path == p

    def test_single_sheet_row_count_matches_dataframe(self, tmp_path: Path):
        rows = [{"id": i, "val": i * 2} for i in range(50)]
        p = tmp_path / "big.xlsx"
        _write_xlsx(p, {"Records": rows})
        ref = DataSourceRef(path=p)
        t = load_file(ref)[0]
        assert t.row_count == 50
        assert t.row_count == len(t.dataframe)

    def test_single_sheet_with_alias(self, tmp_path: Path):
        p = tmp_path / "raw.xlsx"
        _write_xlsx(p, {"Sheet1": [{"a": 1}]})
        ref = DataSourceRef(path=p, alias="clean_name")
        t = load_file(ref)[0]
        assert t.table_name == "clean_name.Sheet1"


# =============================================================================
# 4. XLSX multi-sheet loading
# =============================================================================

class TestXLSXMultiSheet:
    def test_two_sheets_returns_two_tables(self, tmp_path: Path):
        p = tmp_path / "workbook.xlsx"
        _write_xlsx(p, {
            "Orders": [{"order_id": "1001", "amount": "500"}],
            "Products": [{"product_id": "P01", "name": "Widget"}],
        })
        ref = DataSourceRef(path=p)
        tables = load_file(ref)

        assert len(tables) == 2
        names = {t.sheet_name for t in tables}
        assert names == {"Orders", "Products"}

    def test_sheet_names_preserved(self, tmp_path: Path):
        p = tmp_path / "wb.xlsx"
        _write_xlsx(p, {
            "Revenue 2024": [{"month": "Jan", "rev": "100"}],
            "Revenue 2025": [{"month": "Jan", "rev": "120"}],
        })
        ref = DataSourceRef(path=p)
        tables = load_file(ref)
        sheet_names = [t.sheet_name for t in tables]
        assert "Revenue 2024" in sheet_names
        assert "Revenue 2025" in sheet_names

    def test_table_names_include_stem_and_sheet(self, tmp_path: Path):
        p = tmp_path / "report.xlsx"
        _write_xlsx(p, {"Alpha": [{"x": 1}], "Beta": [{"y": 2}]})
        ref = DataSourceRef(path=p)
        tables = load_file(ref)
        table_names = {t.table_name for t in tables}
        assert "report.Alpha" in table_names
        assert "report.Beta" in table_names

    def test_each_sheet_has_correct_columns(self, tmp_path: Path):
        p = tmp_path / "multi.xlsx"
        _write_xlsx(p, {
            "Employees": [{"name": "Alice", "dept": "Eng"}],
            "Departments": [{"dept": "Eng", "head": "Bob"}],
        })
        ref = DataSourceRef(path=p)
        tables = {t.sheet_name: t for t in load_file(ref)}

        assert tables["Employees"].column_names == ["name", "dept"]
        assert tables["Departments"].column_names == ["dept", "head"]

    def test_three_sheets(self, tmp_path: Path):
        p = tmp_path / "three.xlsx"
        _write_xlsx(p, {
            "A": [{"v": 1}],
            "B": [{"v": 2}],
            "C": [{"v": 3}],
        })
        ref = DataSourceRef(path=p)
        tables = load_file(ref)
        assert len(tables) == 3


# =============================================================================
# 5. JSON loading
# =============================================================================

class TestJSONLoading:
    def test_basic_json(self, tmp_path: Path):
        p = tmp_path / "records.json"
        _write_json(p, [{"id": "1", "name": "Alice"}, {"id": "2", "name": "Bob"}])
        ref = DataSourceRef(path=p)
        tables = load_file(ref)

        assert len(tables) == 1
        t = tables[0]
        assert t.file_type == FileType.JSON
        assert t.sheet_name is None
        assert t.table_name == "records"
        assert t.column_names == ["id", "name"]
        assert t.row_count == 2

    def test_json_with_alias(self, tmp_path: Path):
        p = tmp_path / "raw.json"
        _write_json(p, [{"a": 1}])
        ref = DataSourceRef(path=p, alias="events")
        t = load_file(ref)[0]
        assert t.table_name == "events"

    def test_json_source_path_preserved(self, tmp_path: Path):
        p = tmp_path / "data.json"
        _write_json(p, [{"x": 1}])
        ref = DataSourceRef(path=p)
        t = load_file(ref)[0]
        assert t.source_path == p

    def test_json_row_count_matches_dataframe(self, tmp_path: Path):
        p = tmp_path / "data.json"
        _write_json(p, [{"n": i} for i in range(25)])
        ref = DataSourceRef(path=p)
        t = load_file(ref)[0]
        assert t.row_count == 25
        assert t.row_count == len(t.dataframe)

    def test_json_numeric_values_become_strings(self, tmp_path: Path):
        """Numeric JSON values must be cast to str — consistent with CSV loader."""
        p = tmp_path / "nums.json"
        _write_json(p, [{"amount": 42, "rate": 3.14}])
        ref = DataSourceRef(path=p)
        t = load_file(ref)[0]
        row = t.to_records()[0]
        assert isinstance(row["amount"], str)
        assert isinstance(row["rate"], str)

    def test_nested_json_object_raises_ingestion_error(self, tmp_path: Path):
        p = tmp_path / "nested.json"
        _write_json(p, [{"id": 1, "address": {"city": "Mumbai", "pin": "400001"}}])
        ref = DataSourceRef(path=p)
        with pytest.raises(IngestionError) as exc_info:
            load_file(ref)
        assert exc_info.value.reason == "NON_TABULAR_JSON"

    def test_nested_json_array_raises_ingestion_error(self, tmp_path: Path):
        p = tmp_path / "nested.json"
        _write_json(p, [{"id": 1, "tags": ["a", "b"]}])
        ref = DataSourceRef(path=p)
        with pytest.raises(IngestionError) as exc_info:
            load_file(ref)
        assert exc_info.value.reason == "NON_TABULAR_JSON"

    def test_json_root_object_raises_ingestion_error(self, tmp_path: Path):
        """JSON root must be a list, not an object."""
        p = tmp_path / "obj.json"
        _write_json(p, {"key": "value"})
        ref = DataSourceRef(path=p)
        with pytest.raises(IngestionError) as exc_info:
            load_file(ref)
        assert exc_info.value.reason == "NON_TABULAR_JSON"

    def test_json_array_of_scalars_raises_ingestion_error(self, tmp_path: Path):
        p = tmp_path / "scalars.json"
        _write_json(p, [1, 2, 3])
        ref = DataSourceRef(path=p)
        with pytest.raises(IngestionError) as exc_info:
            load_file(ref)
        assert exc_info.value.reason == "NON_TABULAR_JSON"


# =============================================================================
# 6. Unsupported file type
# =============================================================================

class TestUnsupportedFile:
    def test_pdf_raises_unsupported(self, tmp_path: Path):
        p = tmp_path / "invoice.pdf"
        p.write_bytes(b"%PDF-1.4")
        ref = DataSourceRef(path=p)
        with pytest.raises(IngestionError) as exc_info:
            load_file(ref)
        assert exc_info.value.reason == "UNSUPPORTED_FILE_TYPE"
        assert exc_info.value.path == p

    def test_docx_raises_unsupported(self, tmp_path: Path):
        p = tmp_path / "letter.docx"
        p.write_bytes(b"PK")  # zip magic bytes, but wrong extension
        ref = DataSourceRef(path=p)
        with pytest.raises(IngestionError) as exc_info:
            load_file(ref)
        assert exc_info.value.reason == "UNSUPPORTED_FILE_TYPE"

    def test_parquet_raises_unsupported(self, tmp_path: Path):
        p = tmp_path / "data.parquet"
        p.write_bytes(b"PAR1")
        ref = DataSourceRef(path=p)
        with pytest.raises(IngestionError) as exc_info:
            load_file(ref)
        assert exc_info.value.reason == "UNSUPPORTED_FILE_TYPE"


# =============================================================================
# 7. Missing file
# =============================================================================

class TestMissingFile:
    def test_missing_csv_raises_file_not_found(self, tmp_path: Path):
        p = tmp_path / "does_not_exist.csv"
        ref = DataSourceRef(path=p)
        with pytest.raises(IngestionError) as exc_info:
            load_file(ref)
        assert exc_info.value.reason == "FILE_NOT_FOUND"
        assert exc_info.value.path == p

    def test_missing_xlsx_raises_file_not_found(self, tmp_path: Path):
        p = tmp_path / "phantom.xlsx"
        ref = DataSourceRef(path=p)
        with pytest.raises(IngestionError) as exc_info:
            load_file(ref)
        assert exc_info.value.reason == "FILE_NOT_FOUND"

    def test_missing_json_raises_file_not_found(self, tmp_path: Path):
        p = tmp_path / "ghost.json"
        ref = DataSourceRef(path=p)
        with pytest.raises(IngestionError) as exc_info:
            load_file(ref)
        assert exc_info.value.reason == "FILE_NOT_FOUND"


# =============================================================================
# 8. Empty table
# =============================================================================

class TestEmptyTable:
    def test_csv_header_only(self, tmp_path: Path):
        """A CSV with only a header row and no data rows must load with row_count == 0."""
        p = tmp_path / "empty.csv"
        _write_csv(p, "order_id,revenue,currency\n")
        ref = DataSourceRef(path=p)
        t = load_file(ref)[0]
        assert t.row_count == 0
        assert t.column_names == ["order_id", "revenue", "currency"]
        assert len(t.dataframe) == 0

    def test_xlsx_empty_sheet(self, tmp_path: Path):
        """An XLSX sheet with headers but no data rows must load with row_count == 0."""
        p = tmp_path / "empty.xlsx"
        _write_xlsx(p, {"Sheet1": []})  # DataFrame() with no rows
        ref = DataSourceRef(path=p)
        t = load_file(ref)[0]
        assert t.row_count == 0
        assert len(t.dataframe) == 0

    def test_json_empty_array(self, tmp_path: Path):
        """An empty JSON array must load with row_count == 0 and no columns."""
        p = tmp_path / "empty.json"
        _write_json(p, [])
        ref = DataSourceRef(path=p)
        t = load_file(ref)[0]
        assert t.row_count == 0
        assert t.column_names == []


# =============================================================================
# 9. Value preservation
# =============================================================================

class TestValuePreservation:
    """
    These tests verify the core anti-hallucination rule:
    the loader must NOT alter any cell value.

    PROOFLENS_MASTER_CONTEXT.md §6: Original data must remain unchanged.
    Cleaning belongs to later stages.
    """

    def test_leading_zeros_preserved_in_csv(self, tmp_path: Path):
        p = tmp_path / "codes.csv"
        _write_csv(p, "code\n01\n007\n00100\n")
        t = load_file(DataSourceRef(path=p))[0]
        values = t.dataframe["code"].tolist()
        assert values == ["01", "007", "00100"], (
            "Leading zeros must be preserved. "
            "If this fails, dtype=str is not being applied."
        )

    def test_na_string_not_converted_to_nan(self, tmp_path: Path):
        """'NA', 'N/A', 'nan', 'NaN', '' must all remain as plain strings."""
        p = tmp_path / "nullish.csv"
        _write_csv(p, "val\nNA\nN/A\nnan\nNaN\n\n")
        t = load_file(DataSourceRef(path=p))[0]
        values = t.dataframe["val"].tolist()
        # None of these should be NaN (which would show up as float 'nan')
        for v in values:
            assert isinstance(v, str), (
                f"Value {v!r} was converted from string. "
                "keep_default_na=False must be set."
            )

    def test_spaces_preserved_in_values(self, tmp_path: Path):
        p = tmp_path / "spaces.csv"
        _write_csv(p, "name\n Alice \n Bob\n")
        t = load_file(DataSourceRef(path=p))[0]
        # Leading/trailing spaces in cell values must NOT be stripped.
        assert " Alice " in t.dataframe["name"].tolist()

    def test_mixed_case_preserved(self, tmp_path: Path):
        p = tmp_path / "case.csv"
        _write_csv(p, "region\nNorth\nnorth\nNORTH\n")
        t = load_file(DataSourceRef(path=p))[0]
        values = t.dataframe["region"].tolist()
        assert "North" in values
        assert "north" in values
        assert "NORTH" in values

    def test_numeric_strings_not_coerced(self, tmp_path: Path):
        """Values that look numeric must remain as strings."""
        p = tmp_path / "nums.csv"
        _write_csv(p, "amount\n100\n200.5\n1000000\n")
        t = load_file(DataSourceRef(path=p))[0]
        for v in t.dataframe["amount"].tolist():
            assert isinstance(v, str), f"{v!r} was coerced to a non-string type."

    def test_original_dataframe_not_mutated_by_to_records(self, tmp_path: Path):
        """Calling to_records() must not change the LoadedTable's DataFrame."""
        p = tmp_path / "data.csv"
        _write_csv(p, "x\n1\n2\n3\n")
        t = load_file(DataSourceRef(path=p))[0]
        before = t.dataframe.copy()
        _ = t.to_records()
        pd.testing.assert_frame_equal(t.dataframe, before)

    def test_xlsx_leading_zeros_preserved(self, tmp_path: Path):
        """XLSX cells with leading zeros must not be auto-cast to integers."""
        p = tmp_path / "codes.xlsx"
        # Write as strings to avoid Excel auto-formatting
        _write_xlsx(p, {"Sheet1": [{"code": "007"}, {"code": "042"}]})
        t = load_file(DataSourceRef(path=p))[0]
        values = t.dataframe["code"].tolist()
        assert "007" in values
        assert "042" in values

    def test_json_string_values_preserved(self, tmp_path: Path):
        """JSON string values must not be altered."""
        p = tmp_path / "data.json"
        _write_json(p, [{"city": "  Mumbai  ", "code": "MUM"}])
        t = load_file(DataSourceRef(path=p))[0]
        row = t.to_records()[0]
        assert row["city"] == "  Mumbai  "
        assert row["code"] == "MUM"

    def test_column_names_not_stripped_or_renamed(self, tmp_path: Path):
        """Column names with spaces or special characters must be preserved."""
        p = tmp_path / "cols.csv"
        _write_csv(p, "Order ID,Revenue (INR),Ship Date\n1,500,2025-01-01\n")
        t = load_file(DataSourceRef(path=p))[0]
        assert t.column_names == ["Order ID", "Revenue (INR)", "Ship Date"]
