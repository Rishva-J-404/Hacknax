"""
app.api.server
--------------
FastAPI backend service exposing ProofLens capabilities to the web interface.
Follows the core law:
LLM PROPOSES. CODE COMPUTES. VERIFICATION DECIDES.
NO PROOF = NO NUMBER.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import shutil
from typing import Any
import uuid

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.agent.planner import DeterministicPlanner
from app.agent.qwen_client import OpenRouterQwenClient
from app.agent.qwen_planner import QwenPlanner
from app.api.contracts import (
    AnalyzeRequest,
    AnalyzeResponse,
    PipelineStepInfo,
    ProofSummary,
    ReplayResponse,
    SampleDataset,
    UploadedFileMeta,
    UploadResponse,
)
from app.audit.profiler import audit_tables
from app.ingestion.contracts import DataSourceRef, LoadedTable
from app.ingestion.loader import load_file
from app.orchestrator import ProofLensOrchestrator
from app.proof.serializer import load_proof_card
from scripts.replay import replay_proof

logger = logging.getLogger("prooflens.api")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="ProofLens API",
    description="Repair-Aware Proof-Carrying Data Analyst",
    version="1.0.0",
)

# Allow CORS for development if web frontend is accessed from another port
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PROOFS_DIR = Path("proofs")
PROOFS_DIR.mkdir(parents=True, exist_ok=True)
SAMPLES_DIR = Path("data/samples")
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)


def _init_samples_if_missing() -> None:
    """Ensure sample CSV datasets exist in data/samples."""
    clean_p = SAMPLES_DIR / "clean_orders.csv"
    if not clean_p.exists():
        clean_p.write_text(
            "order_id,amount,status\n"
            "1,100.0,completed\n"
            "2,200.0,completed\n"
            "3,300.0,completed\n",
            encoding="utf-8",
        )

    messy_p = SAMPLES_DIR / "messy_duplicates.csv"
    if not messy_p.exists():
        messy_p.write_text(
            "order_id,amount,status\n"
            "1,100.0,completed\n"
            "1,100.0,completed\n"
            "2,200.0,completed\n",
            encoding="utf-8",
        )

    dates_p = SAMPLES_DIR / "ambiguous_dates.csv"
    if not dates_p.exists():
        dates_p.write_text(
            "order_id,amount,date\n"
            "1,100.0,01/02/2024\n"
            "2,200.0,03/04/2024\n",
            encoding="utf-8",
        )


_init_samples_if_missing()


# ── 1. POST /api/upload ─────────────────────────────────────────────────────────
@app.post("/api/upload", response_model=UploadResponse)
async def upload_files(files: list[UploadFile] = File(...)) -> UploadResponse:
    """
    Upload CSV/XLSX/JSON files, ingest them deterministically,
    and automatically trigger the ProofLens Data Audit pipeline.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")

    session_id = uuid.uuid4().hex[:12]
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    metas: list[UploadedFileMeta] = []
    loaded_tables: list[LoadedTable] = []

    for file in files:
        if not file.filename:
            continue
        dest_path = session_dir / Path(file.filename).name
        content = await file.read()
        dest_path.write_bytes(content)

        file_sha256 = hashlib.sha256(content).hexdigest()

        try:
            tbls = load_file(DataSourceRef(path=dest_path))
            loaded_tables.extend(tbls)
            for tbl in tbls:
                metas.append(
                    UploadedFileMeta(
                        filename=file.filename,
                        size_bytes=len(content),
                        row_count=tbl.row_count,
                        column_count=len(tbl.column_names),
                        columns=tbl.column_names,
                        sha256=file_sha256,
                    )
                )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to ingest '{file.filename}': {e}")

    # Deterministic Data Audit
    ledger = audit_tables(loaded_tables)
    ledger_dict = ledger.model_dump(mode="json")

    issue_count = len(ledger.all_issues)
    summary_msg = (
        f"Uploaded {len(metas)} table(s). Audit complete: detected {issue_count} data quality issue(s)."
        if issue_count > 0
        else f"Uploaded {len(metas)} table(s). Audit clean: no data quality anomalies detected."
    )

    return UploadResponse(
        session_id=session_id,
        files=metas,
        audit_ledger=ledger_dict,
        summary_message=summary_msg,
    )


# ── 2. POST /api/analyze ────────────────────────────────────────────────────────
@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze_question(req: AnalyzeRequest) -> AnalyzeResponse:
    """
    Execute the full 14-stage ProofLens orchestrator pipeline against session data.
    The frontend NEVER calculates the answer or assigns truth statuses.
    """
    session_dir = UPLOAD_DIR / req.session_id
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail=f"Session '{req.session_id}' not found. Please re-select or upload data.")

    sources = [p for p in session_dir.iterdir() if p.is_file()]
    if not sources:
        raise HTTPException(status_code=400, detail="No source data files found for session.")

    try:
        # Configure Planner Backend
        planner = None
        if req.planner_type.lower() == "qwen":
            client = OpenRouterQwenClient()
            if client.is_configured:
                planner = QwenPlanner(client=client)
            else:
                planner = DeterministicPlanner()
        else:
            planner = DeterministicPlanner()

        orchestrator = ProofLensOrchestrator(
            planner=planner,
            proof_output_dir=PROOFS_DIR,
            session_id=req.session_id,
        )

        result = orchestrator.run(
            question=req.question,
            sources=sources,
            output_dir=PROOFS_DIR,
            repair_parameters=req.policy_overrides,
        )

        proof_card = result.proof_card
        ledger = proof_card.data_quality_ledger if proof_card else None
        plan = proof_card.analysis_plan if proof_card else None
        code_str = None
        if proof_card and proof_card.analysis_code_path and Path(proof_card.analysis_code_path).exists():
            try:
                code_str = Path(proof_card.analysis_code_path).read_text(encoding="utf-8")
            except Exception:
                code_str = None
        meta_results = []
        if result.verification and hasattr(result.verification, "metamorphic_results"):
            meta_results = result.verification.metamorphic_results or []
        elif proof_card and proof_card.verification_results:
            for vr in proof_card.verification_results:
                meta_results.extend(getattr(vr, "metamorphic_results", []) or [])
        passed_meta = sum(1 for m in meta_results if getattr(m.status, "value", str(m.status)) == "PASS")
        skipped_meta = sum(1 for m in meta_results if getattr(m.status, "value", str(m.status)) == "SKIPPED")
        failed_meta = sum(1 for m in meta_results if getattr(m.status, "value", str(m.status)) == "FAIL")
        meta_summary = {"passed": passed_meta, "skipped": skipped_meta, "failed": failed_meta, "total": len(meta_results)}

        # Compile pipeline steps for visual tracker
        plan_status_val = getattr(plan.status, "value", str(plan.status)) if plan and hasattr(plan, "status") else "READY"
        steps: list[PipelineStepInfo] = [
            PipelineStepInfo(
                name="AUDIT",
                status="PASSED",
                details=f"Audited {len(sources)} source file(s). Found {len(ledger.all_issues) if ledger else 0} issues.",
            ),
            PipelineStepInfo(
                name="PLAN",
                status="PASSED" if plan and plan_status_val != "UNANSWERABLE" else "BLOCKED",
                details=getattr(plan, "analysis_intent", "") or getattr(plan, "unanswerable_evidence", "") or "Planning step completed",
            ),
            PipelineStepInfo(
                name="REPAIR WORLDS",
                status="PASSED",
                details=f"Generated {len(result.repair_worlds)} repair world(s).",
            ),
            PipelineStepInfo(
                name="COMPUTE",
                status="PASSED" if (result.result is not None or not result.answer_blocked) else ("BLOCKED" if result.answer_blocked else "SKIPPED"),
                details=f"Executed primary analysis against world '{proof_card.result_world_id if proof_card else 'world_001'}'.",
            ),
            PipelineStepInfo(
                name="VERIFY",
                status="PASSED" if result.verification and getattr(result.verification, "verification_passed", False) else ("BLOCKED" if result.verification and not getattr(result.verification, "verification_passed", False) else "SKIPPED"),
                details="Dual-path independent DuckDB SQL verification.",
            ),
            PipelineStepInfo(
                name="METAMORPHIC TESTS",
                status="PASSED" if failed_meta == 0 else "BLOCKED",
                details=f"{passed_meta} passed, {skipped_meta} skipped.",
            ),
            PipelineStepInfo(
                name="TRUTH GATE",
                status="PASSED" if not result.answer_blocked else "BLOCKED",
                details="Skeptic review and claim verification gate.",
            ),
            PipelineStepInfo(
                name="PROOF CARD",
                status="PASSED" if proof_card else "BLOCKED",
                details=f"Proof ID: {proof_card.proof_id if proof_card else 'None'}",
            ),
        ]

        proof_dict = proof_card.model_dump(mode="json") if proof_card and hasattr(proof_card, "model_dump") else proof_card
        impact_dict = result.impact_analysis.model_dump(mode="json") if result.impact_analysis and hasattr(result.impact_analysis, "model_dump") else result.impact_analysis
        worlds_list = [w.model_dump(mode="json") if hasattr(w, "model_dump") else w for w in result.repair_worlds]
        verif_dict = result.verification.model_dump(mode="json") if result.verification and hasattr(result.verification, "model_dump") else (result.verification or {})
        gate_dict = result.truth_gate.model_dump(mode="json") if result.truth_gate and hasattr(result.truth_gate, "model_dump") else (result.truth_gate or {})

        status_str = getattr(result.status, "value", str(result.status))

        return AnalyzeResponse(
            session_id=req.session_id,
            question=req.question,
            status=status_str,
            result=result.result,
            answer=result.answer,
            answer_blocked=result.answer_blocked,
            proof_id=proof_card.proof_id if proof_card else None,
            proof_card=proof_dict,
            impact_analysis=impact_dict,
            repair_worlds=worlds_list,
            generated_code=code_str,
            verification_summary=verif_dict,
            metamorphic_summary=meta_summary,
            truth_gate_summary=gate_dict,
            pipeline_steps=steps,
            errors=result.errors,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error executing analyze pipeline")
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(exc)}")


# ── 3. GET /api/proofs ──────────────────────────────────────────────────────────
@app.get("/api/proofs", response_model=list[ProofSummary])
def list_proofs() -> list[ProofSummary]:
    """List all stored cryptographic ProofCards."""
    summaries: list[ProofSummary] = []
    if not PROOFS_DIR.exists():
        return summaries

    for path in sorted(PROOFS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            card = load_proof_card(path)
            summaries.append(
                ProofSummary(
                    proof_id=card.proof_id,
                    question=card.question,
                    status=card.status.value,
                    result=card.result,
                    result_world_id=card.result_world_id,
                    created_at=card.created_at.isoformat() if hasattr(card.created_at, "isoformat") else str(card.created_at),
                    replay_count=card.replay_count,
                    file_path=str(path),
                )
            )
        except Exception:
            continue
    return summaries


# ── 4. GET /api/proofs/{proof_id} ──────────────────────────────────────────────
@app.get("/api/proofs/{proof_id}")
def get_proof(proof_id: str) -> dict[str, Any]:
    """Retrieve full ProofCard artifact JSON by ID."""
    p = PROOFS_DIR / f"{proof_id}.json"
    if not p.exists():
        # Try finding anywhere in PROOFS_DIR matching stem
        matches = list(PROOFS_DIR.glob(f"*{proof_id}*.json"))
        if matches:
            p = matches[0]
        else:
            raise HTTPException(status_code=404, detail=f"Proof '{proof_id}' not found.")

    try:
        card = load_proof_card(p)
        return card.model_dump(mode="json")
    except Exception as e:
        logger.exception("Failed to read proof card %s", proof_id)
        raise HTTPException(status_code=500, detail="Failed to read the requested cryptographic proof card.")


# ── 5. POST /api/replay/{proof_id} ─────────────────────────────────────────────
@app.post("/api/replay/{proof_id}", response_model=ReplayResponse)
def replay_proof_endpoint(proof_id: str) -> ReplayResponse:
    """
    Rerun and validate an existing ProofCard using the independent replay sandbox.
    Verifies data hashes, code hash, execution output, and verification match.
    """
    p = PROOFS_DIR / f"{proof_id}.json"
    if not p.exists():
        matches = list(PROOFS_DIR.glob(f"*{proof_id}*.json"))
        if matches:
            p = matches[0]
        else:
            raise HTTPException(status_code=404, detail=f"Proof '{proof_id}' not found.")

    replay_res = replay_proof(p)
    det = replay_res.details or {}

    is_pass = replay_res.status == "PASS"

    return ReplayResponse(
        proof_id=proof_id,
        overall_status=replay_res.status,
        data_hash_matched=det.get("data_hash_matched", is_pass),
        code_hash_matched=det.get("code_hash_matched", is_pass),
        execution_succeeded=det.get("execution_succeeded", is_pass),
        result_matched=det.get("result_matched", is_pass),
        verification_passed=det.get("verification_passed", is_pass),
        details={"message": replay_res.message, **det},
    )


# ── 6. GET /api/samples & POST /api/samples/{sample_id}/load ───────────────────
SAMPLE_REGISTRY: list[SampleDataset] = [
    SampleDataset(
        id="clean_orders",
        name="Clean E-Commerce Orders",
        description="Clean, well-formed 3-row dataset with zero data quality issues.",
        filename="clean_orders.csv",
        sample_questions=["Total order amount", "What is the average order amount?"],
        expected_verdict="VERIFIED",
    ),
    SampleDataset(
        id="messy_duplicates",
        name="Duplicate Transactions",
        description="Dataset containing duplicate rows that branch into KEEP vs DEDUP worlds with spread.",
        filename="messy_duplicates.csv",
        sample_questions=["Total order amount"],
        expected_verdict="AMBIGUOUS",
    ),
    SampleDataset(
        id="ambiguous_dates",
        name="Ambiguous Date Formats",
        description="Mixed DD/MM/YYYY vs MM/DD/YYYY date formats requiring repair interpretation.",
        filename="ambiguous_dates.csv",
        sample_questions=["Total amount in February 2024", "Total amount in January 2024"],
        expected_verdict="AMBIGUOUS",
    ),
]


@app.get("/api/samples", response_model=list[SampleDataset])
def get_samples() -> list[SampleDataset]:
    """List bundled sample datasets for demonstration."""
    return SAMPLE_REGISTRY


@app.post("/api/samples/{sample_id}/load", response_model=UploadResponse)
def load_sample_dataset(sample_id: str) -> UploadResponse:
    """Pre-load a sample dataset into a new session and trigger audit immediately."""
    sample = next((s for s in SAMPLE_REGISTRY if s.id == sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail=f"Sample '{sample_id}' not found.")

    src_path = SAMPLES_DIR / sample.filename
    if not src_path.exists():
        _init_samples_if_missing()

    session_id = f"demo_{sample_id}_{uuid.uuid4().hex[:6]}"
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    dest_path = session_dir / sample.filename
    shutil.copy2(src_path, dest_path)

    content = dest_path.read_bytes()
    file_sha256 = hashlib.sha256(content).hexdigest()

    try:
        tbls = load_file(DataSourceRef(path=dest_path))
        ledger = audit_tables(tbls)
    except Exception as e:
        logger.exception("Failed to ingest demo sample %s", sample_id)
        raise HTTPException(status_code=400, detail=f"Failed to ingest demo sample '{sample.name}': {e}")

    metas = [
        UploadedFileMeta(
            filename=sample.filename,
            size_bytes=len(content),
            row_count=tbl.row_count,
            column_count=len(tbl.column_names),
            columns=tbl.column_names,
            sha256=file_sha256,
        )
        for tbl in tbls
    ]

    return UploadResponse(
        session_id=session_id,
        files=metas,
        audit_ledger=ledger.model_dump(mode="json"),
        summary_message=f"Loaded demo dataset '{sample.name}'. Audit detected {len(ledger.all_issues)} issue(s).",
    )


# ── 7. Static UI Files Mounting ────────────────────────────────────────────────
FRONTEND_DIST = Path("frontend/dist")
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")

