import React from 'react';
import { AlertOctagon, HelpCircle, FileText, Code } from 'lucide-react';

export default function RefusalCard({
  status,
  answer,
  impactAnalysis,
  onViewProof,
  onViewCode,
}) {
  const isAmbiguous = status === 'AMBIGUOUS';
  const isUnanswerable = status === 'UNANSWERABLE';

  let reason = answer;
  if (isAmbiguous) {
    if (
      impactAnalysis &&
      impactAnalysis.minimum !== undefined &&
      impactAnalysis.maximum !== undefined &&
      impactAnalysis.spread !== undefined
    ) {
      reason = `${answer || 'Alternative repair policies produce diverging analytical numbers across repair worlds.'} Evaluated range across worlds: ${impactAnalysis.minimum} to ${impactAnalysis.maximum} (Spread: ${impactAnalysis.spread}).`;
    } else {
      reason = answer || 'Alternative repair policies produce diverging analytical numbers across repair worlds. TruthGate blocked asserting a single speculative result.';
    }
  } else if (!reason) {
    reason = isUnanswerable
      ? 'One or more required fields or metrics cannot be constructed from the ingested source schemas.'
      : 'Independent DuckDB verification or metamorphic checks did not reach mathematical consensus.';
  }

  const remediation = isAmbiguous
    ? 'Choose an explicit policy in the Repair Decision Center (e.g. Exact Dedup) or inspect the spread in the Compare Worlds panel.'
    : isUnanswerable
    ? 'Provide tables containing the required baseline columns or rephrase the query around available fields.'
    : 'Review generated execution code and verification discrepancy logs in the Proof Card.';

  return (
    <div className="refusal-card-container animate-fade-in">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
        <span className="refusal-badge">
          <AlertOctagon size={13} />
          {status || 'NOT VERIFIED'}
        </span>
        <span className="badge badge-danger font-mono" style={{ fontSize: '10px' }}>
          ANSWER BLOCKED (NO PROOF = NO NUMBER)
        </span>
      </div>

      <h3 className="refusal-title">
        ProofLens Cannot Provide a Trustworthy Numerical Answer
      </h3>

      <div className="refusal-reason-box">
        <h5>Verification & Truth Gate Reason</h5>
        <p>{reason}</p>
      </div>

      <div className="refusal-remediation-box">
        <h5>Remediation Guidance</h5>
        <p>{remediation}</p>
      </div>

      <div className="result-actions-row">
        <button className="btn btn-secondary" onClick={onViewProof}>
          <FileText size={14} />
          <span>INSPECT TRUTH GATE PROOF</span>
        </button>
        <button className="btn btn-secondary" onClick={onViewCode}>
          <Code size={14} />
          <span>INSPECT GENERATED CODE</span>
        </button>
      </div>
    </div>
  );
}
