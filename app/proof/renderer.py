"""
app.proof.renderer
------------------
Human-readable text rendering for ProofLens ProofCard artifacts.

CORE PRINCIPLE (PROOFLENS_MASTER_CONTEXT.md §20, §24):
    The text representation provides a transparent, auditable report
    summarizing every step from question to proof verdict.
    The structured JSON file remains authoritative.
"""

from __future__ import annotations

from pathlib import Path

from app.proof.contracts import ProofCard


def render_proof_card_text(proof_card: ProofCard) -> str:
    """
    Format a ProofCard into a structured, human-readable ASCII card.
    """
    lines: list[str] = [
        "=" * 50,
        "PROOFLENS PROOF CARD",
        "=" * 50,
        f"Proof ID:       {proof_card.proof_id}",
        f"Created At:     {proof_card.created_at.isoformat() if proof_card.created_at else 'N/A'}",
        f"Session ID:     {proof_card.session_id or 'None'}",
        "",
        "Question:",
        f"  {proof_card.question}",
        "",
        "Status:",
        f"  {proof_card.status.value}",
        "",
        "Result:",
    ]

    # Result & Decision Details
    if proof_card.answer_blocked:
        lines.append("  [ANSWER BLOCKED - NO PROOF = NO NUMBER]")
        lines.append(f"  Decision:             {proof_card.deterministic_decision}")
        if proof_card.result is not None:
            lines.append(f"  Candidate Result:     {proof_card.result} ({proof_card.result_unit or 'No unit'})")
        if proof_card.blocking_reasons:
            lines.append("  Blocking Reasons:")
            for r in proof_card.blocking_reasons:
                lines.append(f"    - {r}")
    else:
        disp_val = proof_card.formatted_result or str(proof_card.result)
        lines.append(f"  {disp_val}")
        if proof_card.result_unit:
            lines.append(f"  Unit:                 {proof_card.result_unit}")
        if proof_card.relevant_period:
            lines.append(f"  Period:               {proof_card.relevant_period}")
        lines.append(f"  Decision:             {proof_card.deterministic_decision}")

    # Policy
    lines.extend(["", "Policy:"])
    if proof_card.lineage and proof_card.lineage.repair_policy_summary:
        lines.append(f"  {proof_card.lineage.repair_policy_summary}")
    else:
        lines.append("  No repair policies applied (source data untouched).")

    # Repair World
    lines.extend(["", "Repair World:"])
    lines.append(f"  World ID:             {proof_card.result_world_id or 'world_source'}")
    if proof_card.repair_worlds:
        lines.append(f"  Total Worlds Tested:  {len(proof_card.repair_worlds)}")
        for w in proof_card.repair_worlds:
            lines.append(f"    * {w.world_id}: {w.description or 'Default world'}")
    if proof_card.assumptions:
        lines.append("  Assumptions:")
        for a in proof_card.assumptions:
            lines.append(f"    - {a}")

    # Data & Lineage
    lines.extend(["", "Data:"])
    if proof_card.data_quality_ledger:
        dql = proof_card.data_quality_ledger
        lines.append(f"  Quality Ledger:       {len(dql.issues)} issues detected")
        for tp in dql.table_profiles:
            lines.append(f"    * Table: {tp.table_name} ({tp.row_count} rows, {tp.column_count} cols)")
    if proof_card.hashes and proof_card.hashes.dataset_sha256:
        lines.append("  Dataset SHA-256 Hashes:")
        for tbl, h in proof_card.hashes.dataset_sha256.items():
            lines.append(f"    * {tbl}: {h[:16]}...")

    # Analysis Plan
    lines.extend(["", "Analysis:"])
    if proof_card.analysis_plan:
        plan = proof_card.analysis_plan
        lines.append(f"  Required Tables:      {', '.join(plan.required_tables)}")
        if plan.aggregation:
            lines.append(
                f"  Aggregation:          {plan.aggregation.operation.upper()}({plan.aggregation.column.table}.{plan.aggregation.column.column})"
            )
        if plan.filters:
            lines.append(f"  Filters:              {len(plan.filters)} active filters")
    elif proof_card.lineage and proof_card.lineage.tables_used:
        lines.append(f"  Tables Used:          {', '.join(proof_card.lineage.tables_used)}")
        lines.append(f"  Columns Used:         {', '.join(proof_card.lineage.columns_used)}")
    else:
        lines.append("  Plan:                 Direct execution")

    # Execution & Code Hash
    code_hash = proof_card.hashes.analysis_code_sha256 if proof_card.hashes else None
    lines.extend([
        "",
        "Generated Code Hash:",
        f"  {code_hash or 'None'}",
    ])

    # Verification
    vr = proof_card.verification_results[0] if proof_card.verification_results else None
    p_res = vr.primary_result if vr else (proof_card.result if not proof_card.answer_blocked else None)
    d_res = vr.duckdb_result if vr else None
    v_stat = "PASS" if (vr and vr.verification_passed) else ("FAIL" if vr else "NOT RUN")

    lines.extend([
        "",
        "Primary Result:",
        f"  {p_res if p_res is not None else 'None'}",
        "",
        "Independent Result (DuckDB):",
        f"  {d_res if d_res is not None else 'None'}",
        "",
        "Verification:",
        f"  {v_stat}",
    ])
    if vr and vr.failures:
        lines.append("  Failures:")
        for f in vr.failures:
            lines.append(f"    - {f}")

    # Metamorphic Tests
    lines.extend(["", "Metamorphic Tests:"])
    if proof_card.metamorphic_summary:
        for m in proof_card.metamorphic_summary:
            lines.append(f"  [{m.get('status', 'SKIPPED')}] {m.get('name', 'TEST')}: {m.get('transformation', '')}")
    else:
        lines.append("  No metamorphic tests executed.")

    # Claims
    lines.extend(["", "Claims:"])
    if proof_card.claims:
        for c in proof_card.claims:
            stat_icon = "SUPPORTED" if c.supported else "UNSUPPORTED"
            lines.append(f"  [{stat_icon}] [{c.claim_type.value}] '{c.claim_text}'")
            if c.mismatch_reason:
                lines.append(f"      Reason: {c.mismatch_reason}")
    else:
        lines.append("  No claims extracted.")

    # Skeptic Review
    lines.extend(["", "Skeptic Review:"])
    if proof_card.skeptic_review and proof_card.skeptic_review.concerns:
        for sc in proof_card.skeptic_review.concerns:
            lines.append(f"  [{sc.severity.upper()}] [{sc.concern_type.value}] {sc.description}")
    else:
        lines.append("  Zero blocking skeptic concerns.")

    # Truth Gate
    lines.extend(["", "Truth Gate:"])
    if proof_card.truth_gate_result:
        tgr = proof_card.truth_gate_result
        lines.append(f"  Overall Status:       {tgr.overall_status.value}")
        lines.append(f"  Gate Decision:        {tgr.deterministic_decision}")
        lines.append(f"  Answer Blocked:       {tgr.answer_blocked}")
        lines.append(f"  Verified Claims:      {len(tgr.verified_claims)}")
        lines.append(f"  Unsupported Claims:   {len(tgr.unsupported_claims)}")
    else:
        lines.append(f"  Status:               {proof_card.status.value}")
        lines.append(f"  Decision:             {proof_card.deterministic_decision}")

    # Replay
    lines.extend([
        "",
        "Replay:",
        f"  {proof_card.reproduction_command or f'python scripts/replay.py proofs/{proof_card.proof_id}.json'}",
        "=" * 50,
    ])

    return "\n".join(lines)


def save_proof_card_text(
    proof_card: ProofCard,
    output_dir: Path | str | None = None,
    file_path: Path | str | None = None,
) -> Path:
    """
    Format and save the human-readable text ProofCard to disk.
    Default path: proofs/<proof_id>.txt
    """
    if file_path is not None:
        target = Path(file_path)
    else:
        out_directory = Path(output_dir) if output_dir else Path("proofs")
        target = out_directory / f"{proof_card.proof_id}.txt"

    target.parent.mkdir(parents=True, exist_ok=True)
    text_content = render_proof_card_text(proof_card)
    target.write_text(text_content, encoding="utf-8")
    return target
