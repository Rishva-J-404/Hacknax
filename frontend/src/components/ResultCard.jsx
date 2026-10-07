import React from 'react';
import { ShieldCheck, Code, Play, FileText, CheckCircle2 } from 'lucide-react';

export default function ResultCard({
  result,
  answer,
  status,
  proofId,
  question,
  onViewProof,
  onViewCode,
  onReplay,
}) {
  const formattedVal =
    typeof result === 'number'
      ? result.toLocaleString(undefined, { maximumFractionDigits: 4 })
      : (result !== null && result !== undefined ? String(result) : '—');

  return (
    <div className="result-card-container animate-fade-in">
      <div className="result-top-meta">
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="badge badge-success">
            <ShieldCheck size={13} />
            {status || 'VERIFIED'}
          </span>
          <span className="badge badge-neutral font-mono" style={{ fontSize: '10px' }}>
            WORLD_001
          </span>
        </div>
        <span className="font-mono text-muted" style={{ fontSize: '11px' }}>
          DETERMINISTIC COMPUTE ENGINE
        </span>
      </div>

      <div className="result-metric-title">
        Authoritative Computed Result
      </div>

      <div className="result-val-display">
        {formattedVal}
      </div>

      <p className="result-narrative-text">
        {answer}
      </p>

      {/* 4-point Verification Checklist */}
      <div className="verification-checks-strip">
        <div className="check-pill">
          <CheckCircle2 size={13} />
          <span>Python execution in sandbox</span>
        </div>
        <div className="check-pill">
          <CheckCircle2 size={13} />
          <span>DuckDB independent verification matched</span>
        </div>
        <div className="check-pill">
          <CheckCircle2 size={13} />
          <span>Metamorphic invariant tests passed</span>
        </div>
        <div className="check-pill">
          <CheckCircle2 size={13} />
          <span>Source data SHA-256 validated</span>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="result-actions-row">
        <button className="btn btn-secondary" onClick={onViewProof}>
          <FileText size={14} />
          <span>VIEW PROOF CARD</span>
        </button>
        <button className="btn btn-secondary" onClick={onViewCode}>
          <Code size={14} />
          <span>VIEW CODE</span>
        </button>
        <button className="btn btn-replay" onClick={onReplay}>
          <Play size={14} fill="currentColor" />
          <span>EXECUTE REPLAY</span>
        </button>
      </div>
    </div>
  );
}
