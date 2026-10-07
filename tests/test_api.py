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

