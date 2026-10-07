"""
tests/test_api.py
-----------------
Automated integration tests for the ProofLens FastAPI endpoints.
Verifies upload, audit, analyze, multi-world comparison, refusal,
proof inspection, and replay mechanisms.
"""

from pathlib import Path
import pytest
from starlette.testclient import TestClient

from app.api.server import app

client = TestClient(app)


@pytest.fixture
def clean_orders_csv_bytes() -> bytes:
    return (
        b"order_id,amount,status\n"
        b"1,100.0,completed\n"
        b"2,200.0,completed\n"
        b"3,300.0,completed\n"
    )


@pytest.fixture
def duplicate_orders_csv_bytes() -> bytes:
    return (
        b"order_id,amount,status\n"
        b"1,100.0,completed\n"
        b"1,100.0,completed\n"
        b"2,200.0,completed\n"
    )


# 1. Test Samples Endpoint
def test_api_get_samples():
    response = client.get("/api/samples")
    assert response.status_code == 200
    samples = response.json()
    assert len(samples) >= 3
    ids = [s["id"] for s in samples]
    assert "clean_orders" in ids
    assert "messy_duplicates" in ids
    assert "ambiguous_dates" in ids


# 2. Test Load Sample Endpoint
def test_api_load_sample_dataset():
    response = client.post("/api/samples/clean_orders/load")
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert len(data["files"]) == 1
    file_meta = data["files"][0]
    assert file_meta["filename"] == "clean_orders.csv"
    assert file_meta["row_count"] == 3
    assert file_meta["column_count"] == 3
    assert "audit_ledger" in data


# 3. Test File Upload Endpoint with Multipart Form
def test_api_upload_csv(clean_orders_csv_bytes):
    response = client.post(
        "/api/upload",
        files=[("files", ("test_orders.csv", clean_orders_csv_bytes, "text/csv"))],
    )
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert len(data["files"]) == 1
    meta = data["files"][0]
    assert meta["filename"] == "test_orders.csv"
    assert meta["row_count"] == 3
    assert len(meta["sha256"]) == 64
    assert "audit_ledger" in data


# 4. Test Flow 1: Clean Data -> Verified Analysis -> Proof Card -> Replay PASS
def test_api_analyze_clean_data_verified(clean_orders_csv_bytes):
    up_res = client.post(
        "/api/upload",
        files=[("files", ("orders.csv", clean_orders_csv_bytes, "text/csv"))],
    )
    session_id = up_res.json()["session_id"]

    analyze_res = client.post(
        "/api/analyze",
        json={
            "session_id": session_id,
            "question": "Total order amount",
            "planner_type": "deterministic",
        },
    )
    assert analyze_res.status_code == 200
    data = analyze_res.json()
    assert data["status"] == "VERIFIED"
    assert data["answer_blocked"] is False
    assert data["result"] == 600.0
    assert "600" in data["answer"]
    assert data["proof_id"] is not None
    assert len(data["pipeline_steps"]) == 8

    proof_id = data["proof_id"]

    # Retrieve Proof
    proof_res = client.get(f"/api/proofs/{proof_id}")
    assert proof_res.status_code == 200
    proof_data = proof_res.json()
    assert proof_data["proof_id"] == proof_id
    assert proof_data["status"] == "VERIFIED"

    # Replay Proof
    replay_res = client.post(f"/api/replay/{proof_id}")
    assert replay_res.status_code == 200
    rep = replay_res.json()
    assert rep["overall_status"] in ("PASS", "INCOMPLETE")
    assert "data_hash_matched" in rep


# 5. Test Flow 2: Duplicate Data -> Multi-World Branching -> Spread -> AMBIGUOUS
def test_api_analyze_duplicates_multi_world_ambiguous(duplicate_orders_csv_bytes):
    up_res = client.post(
        "/api/upload",
        files=[("files", ("messy.csv", duplicate_orders_csv_bytes, "text/csv"))],
    )
    session_id = up_res.json()["session_id"]

    analyze_res = client.post(
        "/api/analyze",
        json={
            "session_id": session_id,
            "question": "Total order amount",
            "planner_type": "deterministic",
        },
    )
    assert analyze_res.status_code == 200
    data = analyze_res.json()
    assert data["status"] == "AMBIGUOUS"
    assert data["answer_blocked"] is True
    assert data["result"] is None
    assert len(data["repair_worlds"]) > 1
    assert data["impact_analysis"] is not None
    assert data["impact_analysis"]["spread"] == 100.0
    assert data["impact_analysis"]["decision_stable"] is False


# 6. Test Flow 3: Unanswerable Metric -> UNANSWERABLE -> No Fabricated Number
def test_api_analyze_unanswerable_missing_column(clean_orders_csv_bytes):
    up_res = client.post(
        "/api/upload",
        files=[("files", ("orders.csv", clean_orders_csv_bytes, "text/csv"))],
    )
    session_id = up_res.json()["session_id"]

    analyze_res = client.post(
        "/api/analyze",
        json={
            "session_id": session_id,
            "question": "What is the customer churn rate?",
            "planner_type": "deterministic",
        },
    )
    assert analyze_res.status_code == 200
    data = analyze_res.json()
    assert data["status"] == "UNANSWERABLE"
    assert data["answer_blocked"] is True
    assert data["result"] is None
    assert "cannot answer" in data["answer"].lower()


# 7. Test Flow 4: Duplicate Data with Policy Override ("EXACT_DEDUP") -> Result 300.0
def test_api_analyze_policy_override_exact_dedup(duplicate_orders_csv_bytes):
    up_res = client.post(
        "/api/upload",
        files=[("files", ("messy.csv", duplicate_orders_csv_bytes, "text/csv"))],
    )
    session_id = up_res.json()["session_id"]

    analyze_res = client.post(
        "/api/analyze",
        json={
            "session_id": session_id,
            "question": "Total order amount",
            "policy_overrides": {"DUPLICATE_ROWS": "EXACT_DEDUP"},
            "planner_type": "deterministic",
        },
    )
    assert analyze_res.status_code == 200
    data = analyze_res.json()
    assert data["status"] == "VERIFIED_WITH_ASSUMPTION"
    assert data["answer_blocked"] is False
    assert data["result"] == 300.0
    assert len(data["repair_worlds"]) == 1


# 8. Test List Proofs Endpoint
def test_api_list_proofs():
    response = client.get("/api/proofs")
    assert response.status_code == 200
    proofs = response.json()
    assert isinstance(proofs, list)


# 9. Test Static React Frontend Endpoint
def test_api_serves_frontend():
    response = client.get("/")
    assert response.status_code == 200
    assert "root" in response.text


# 10. Test Custom Filename with Special Characters and Column Spaces
def test_api_upload_and_analyze_custom_columns():
    csv_bytes = (
        b"Employee ID,Department,Total Salary\n"
        b"101,Engineering,150000\n"
        b"102,Product,120000\n"
        b"103,Design,90000\n"
    )
    up_res = client.post(
        "/api/upload",
        files=[("files", ("employee-data 2026.csv", csv_bytes, "text/csv"))],
    )
    assert up_res.status_code == 200
    session_id = up_res.json()["session_id"]
    file_info = up_res.json()["files"][0]
    assert file_info["row_count"] == 3
    assert "Total Salary" in file_info["columns"]

    # Analyze with column name
    analyze_res = client.post(
        "/api/analyze",
        json={
            "session_id": session_id,
            "question": "What is the Total Salary?",
            "planner_type": "deterministic",
        },
    )
    assert analyze_res.status_code == 200
    data = analyze_res.json()
    assert data["status"] == "VERIFIED"
    assert data["result"] == 360000.0


# 11. Test JSON Array Upload and Row Count Question
def test_api_upload_json_and_row_count():
    json_bytes = b'[{"item": "Laptop", "stock": 10}, {"item": "Mouse", "stock": 50}]'
    up_res = client.post(
        "/api/upload",
        files=[("files", ("inventory.json", json_bytes, "application/json"))],
    )
    assert up_res.status_code == 200
    session_id = up_res.json()["session_id"]
    file_info = up_res.json()["files"][0]
    assert file_info["row_count"] == 2

    # Analyze row count
    analyze_res = client.post(
        "/api/analyze",
        json={
            "session_id": session_id,
            "question": "How many records are in this dataset?",
            "planner_type": "deterministic",
        },
    )
    assert analyze_res.status_code == 200
    data = analyze_res.json()
    assert data["status"] == "VERIFIED"
    assert data["result"] == 2.0


# 12. Test Impossible Date World Handling: 02/17/2025 under COMPARE (No HTTP 500)
def test_api_analyze_impossible_date_world_no_500():
    csv_bytes = (
        b"order_id,amount,date\n"
        b"1,150.0,01/02/2025\n"
        b"2,250.0,02/17/2025\n"
    )
    up_res = client.post(
        "/api/upload",
        files=[("files", ("dates_02_17.csv", csv_bytes, "text/csv"))],
    )
    assert up_res.status_code == 200
    session_id = up_res.json()["session_id"]

    analyze_res = client.post(
        "/api/analyze",
        json={
            "session_id": session_id,
            "question": "Total order amount",
            "planner_type": "deterministic",
        },
    )
    assert analyze_res.status_code == 200
    data = analyze_res.json()
    assert data["status"] in ("VERIFIED", "VERIFIED_WITH_ASSUMPTION")
    assert data["result"] == 400.0
    assert data["answer_blocked"] is False
    assert len(data["repair_worlds"]) >= 1


# 13. Test Single Impossible Policy Override Returns Controlled Refusal (No HTTP 500)
def test_api_analyze_impossible_date_single_policy_refusal():
    csv_bytes = (
        b"order_id,amount,date\n"
        b"1,150.0,01/02/2025\n"
        b"2,250.0,02/17/2025\n"
    )
    up_res = client.post(
        "/api/upload",
        files=[("files", ("dates_single.csv", csv_bytes, "text/csv"))],
    )
    assert up_res.status_code == 200
    session_id = up_res.json()["session_id"]

    analyze_res = client.post(
        "/api/analyze",
        json={
            "session_id": session_id,
            "question": "Total order amount",
            "policy_overrides": {"AMBIGUOUS_DATE_FORMAT": "DD_MM_YYYY"},
            "planner_type": "deterministic",
        },
    )
    assert analyze_res.status_code == 200
    data = analyze_res.json()
    assert data["status"] == "UNANSWERABLE"
    assert data["answer_blocked"] is True
    assert data["result"] is None
    assert "cannot convert date" in data["answer"].lower() or "impossible" in data["answer"].lower()


# 14. Test Completely Invalid Date Returns Controlled Refusal (No HTTP 500)
def test_api_analyze_completely_invalid_date_refusal():
    csv_bytes = (
        b"order_id,amount,date\n"
        b"1,150.0,01/02/2025\n"
        b"2,250.0,99/99/9999\n"
    )
    up_res = client.post(
        "/api/upload",
        files=[("files", ("dates_bad.csv", csv_bytes, "text/csv"))],
    )
    assert up_res.status_code == 200
    session_id = up_res.json()["session_id"]

    analyze_res = client.post(
        "/api/analyze",
        json={
            "session_id": session_id,
            "question": "Total order amount",
            "planner_type": "deterministic",
        },
    )
    assert analyze_res.status_code == 200
    data = analyze_res.json()
    assert data["status"] == "UNANSWERABLE"
    assert data["answer_blocked"] is True
    assert data["result"] is None


# 15. Test XLSX Upload with Whitespace Columns and Full Analysis
def test_api_upload_xlsx_with_whitespace_columns_and_analyze():
    import io
    import pandas as pd

    df = pd.DataFrame({
        "  order_id ": ["1", "2"],
        " revenue   ": ["100", "200"],
    })
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    xlsx_bytes = buf.getvalue()

    up_res = client.post(
        "/api/upload",
        files=[("files", ("sales.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
    )
    assert up_res.status_code == 200
    res_data = up_res.json()
    session_id = res_data["session_id"]
    file_info = res_data["files"][0]
    # Verify column name was stripped of leading/trailing whitespace
    assert "revenue" in file_info["columns"]

    # Execute analysis on stripped column
    analyze_res = client.post(
        "/api/analyze",
        json={
            "session_id": session_id,
            "question": "What is the total revenue?",
            "planner_type": "deterministic",
        },
    )
    assert analyze_res.status_code == 200
    data = analyze_res.json()
    assert data["status"] == "VERIFIED"
    assert data["result"] == 300.0
    assert data["answer_blocked"] is False


# 16. Test Corrupted XLSX Upload Returns 400 (Not 500)
def test_api_upload_corrupted_xlsx_returns_400():
    up_res = client.post(
        "/api/upload",
        files=[("files", ("corrupted.xlsx", b"NOT_A_VALID_EXCEL_ZIP", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
    )
    assert up_res.status_code == 400
    assert "Failed to ingest" in up_res.json()["detail"]


# 17. Test Non-Existent Sample Load Returns 404 (Not 500)
def test_api_load_nonexistent_sample_returns_404():
    res = client.post("/api/samples/does_not_exist/load")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()




