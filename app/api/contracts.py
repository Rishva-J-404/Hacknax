"""
app.api.contracts
-----------------
Pydantic contracts for the ProofLens API layer.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class UploadedFileMeta(BaseModel):
    """Metadata describing an uploaded and ingested data file."""
    filename: str
    size_bytes: int
    row_count: int
    column_count: int
    columns: list[str]
    sha256: str


class UploadResponse(BaseModel):
    """Response returned upon uploading source files."""
    session_id: str
    files: list[UploadedFileMeta]
    audit_ledger: dict[str, Any]
    summary_message: str


class AnalyzeRequest(BaseModel):
    """Request payload to analyze data with a question."""
    session_id: str
    question: str
    policy_overrides: dict[str, str] | None = None
    planner_type: str = Field(default="deterministic", description="'deterministic' or 'qwen'")


class PipelineStepInfo(BaseModel):
    """Status information for a single stage in the 8-stage pipeline."""
    name: str
    status: str  # "PASSED", "BLOCKED", "SKIPPED", "RUNNING"
    details: str = ""


class AnalyzeResponse(BaseModel):
    """Complete, audited analytical response from the ProofLens orchestrator."""
    session_id: str
    question: str
    status: str  # TruthStatus value
    result: Any | None = None
    answer: str
    answer_blocked: bool
    proof_id: str | None = None
    proof_card: dict[str, Any] | None = None
    impact_analysis: dict[str, Any] | None = None
    repair_worlds: list[dict[str, Any]] = Field(default_factory=list)
    generated_code: str | None = None
    verification_summary: dict[str, Any] = Field(default_factory=dict)
    metamorphic_summary: dict[str, Any] = Field(default_factory=dict)
    truth_gate_summary: dict[str, Any] = Field(default_factory=dict)
    pipeline_steps: list[PipelineStepInfo] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProofSummary(BaseModel):
    """Lightweight summary of a stored ProofCard."""
    proof_id: str
    question: str
    status: str
    result: Any | None = None
    result_world_id: str | None = None
    created_at: str
    replay_count: int = 0
    file_path: str


class ReplayResponse(BaseModel):
    """Detailed outcome from executing replay_proof on a ProofCard."""
    proof_id: str
    overall_status: str  # "PASS", "FAIL", "INCOMPLETE"
    data_hash_matched: bool
    code_hash_matched: bool
    execution_succeeded: bool
    result_matched: bool
    verification_passed: bool
    details: dict[str, Any] = Field(default_factory=dict)


class SampleDataset(BaseModel):
    """Preconfigured demonstration dataset for testing."""
    id: str
    name: str
    description: str
    filename: str
    sample_questions: list[str]
    expected_verdict: str
