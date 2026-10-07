"""
tests/test_ingestion_xlsx.py
-----------------------------
Comprehensive test suite verifying XLSX file ingestion robustness,
including regression tests for whitespace trimming on columns,
multi-sheet workbooks, and corrupt workbook error handling.
"""

from __future__ import annotations

from pathlib import Path
import pandas as pd
import pytest

from app.ingestion.contracts import DataSourceRef, FileType, IngestionError
from app.ingestion.loader import detect_file_type, load_file


def test_detect_file_type_xlsx(tmp_path: Path) -> None:
    xlsx_file = tmp_path / "test.xlsx"
    xlsx_file.touch()
    assert detect_file_type(xlsx_file) == FileType.XLSX


def test_xlsx_columns_stripped_of_whitespace(tmp_path: Path) -> None:
    """
    REGRESSION TEST for BUG-1:
    Verify that column names with leading/trailing whitespace in an XLSX sheet
    are properly stripped, preventing spurious MissingColumnError in planning.
    """
    file_path = tmp_path / "spaced_columns.xlsx"
    df = pd.DataFrame({
        "  order_id ": ["1", "2"],
        " revenue   ": ["100", "200"],
        " customer ": ["Alice", "Bob"],
    })
    df.to_excel(file_path, index=False, engine="openpyxl")

    tables = load_file(DataSourceRef(path=file_path))
    assert len(tables) == 1
    table = tables[0]

    assert table.file_type == FileType.XLSX
    assert table.column_names == ["order_id", "revenue", "customer"]
    assert list(table.dataframe.columns) == ["order_id", "revenue", "customer"]
    assert table.row_count == 2


def test_xlsx_multi_sheet_returns_multiple_tables(tmp_path: Path) -> None:
    """Verify that multi-sheet workbooks produce one LoadedTable per sheet."""
    file_path = tmp_path / "multi_sheet.xlsx"
    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        df1 = pd.DataFrame({"id": ["1", "2"], "amount": ["10", "20"]})
        df1.to_excel(writer, sheet_name="Orders", index=False)
        df2 = pd.DataFrame({"cust_id": ["C1", "C2"], "name": ["Alice", "Bob"]})
        df2.to_excel(writer, sheet_name="Customers", index=False)

    tables = load_file(DataSourceRef(path=file_path))
    assert len(tables) == 2
    sheet_names = [t.sheet_name for t in tables]
    assert "Orders" in sheet_names
    assert "Customers" in sheet_names


def test_xlsx_empty_sheet_loads_empty_table(tmp_path: Path) -> None:
    """Verify that an empty sheet is loaded safely as a 0-row table without crashing."""
    file_path = tmp_path / "empty_sheet.xlsx"
    df = pd.DataFrame(columns=["col_a", "col_b"])
    df.to_excel(file_path, index=False, engine="openpyxl")

    tables = load_file(DataSourceRef(path=file_path))
    assert len(tables) == 1
    assert tables[0].row_count == 0
    assert tables[0].column_names == ["col_a", "col_b"]


def test_xlsx_corrupt_file_raises_ingestion_error(tmp_path: Path) -> None:
    """Verify that a corrupted non-zip XLSX file raises IngestionError with CORRUPT_XLSX."""
    file_path = tmp_path / "corrupt.xlsx"
    file_path.write_bytes(b"NOT_A_VALID_EXCEL_ZIP_BINARY_DATA")

    with pytest.raises(IngestionError) as exc_info:
        load_file(DataSourceRef(path=file_path))
    assert exc_info.value.reason == "CORRUPT_XLSX"
