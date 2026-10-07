import React from 'react';
import { ShieldCheck, X, Check, AlertTriangle, RefreshCw } from 'lucide-react';

export default function ReplayModal({
  isOpen,
  onClose,
  replayData,
  isLoading,
  proofId,
}) {
  if (!isOpen) return null;

  const isPass = replayData?.overall_status === 'PASS';
  const isIncomplete = replayData?.overall_status === 'INCOMPLETE';

  const checkItems = [
    { label: '1. Source Dataset SHA-256 Hash Matched', passed: replayData?.data_hash_matched },
    { label: '2. Analysis Script SHA-256 Hash Matched', passed: replayData?.code_hash_matched },
    { label: '3. Sandboxed Execution Succeeded', passed: replayData?.execution_succeeded },
    { label: '4. Computed Result Exactly Matches Stored Proof Value', passed: replayData?.result_matched },
    { label: '5. Dual-Path Verification & Metamorphic Checks Passed', passed: replayData?.verification_passed },
  ];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', borderBottom: '1px solid var(--border-subtle)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ShieldCheck size={18} color="var(--color-success)" />
            <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
              Independent Sandbox Proof Replay
            </h3>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
          >
            <X size={18} />
          </button>
        </div>

        <div style={{ padding: '20px' }}>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
            Replaying cryptographic proof in an isolated execution sandbox. Verifying dataset hashes, generated code hashes, and independent DuckDB outputs:
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', margin: '16px 0' }}>
            {checkItems.map((item, idx) => (
              <div
                key={idx}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '10px 14px',
                  borderRadius: 'var(--radius-sm)',
                  background: 'var(--bg-surface-elevated)',
                  border: item.passed ? '1px solid var(--color-success-border)' : '1px solid var(--border-subtle)',
                  fontSize: '12px',
                }}
              >
                <span style={{ color: item.passed ? 'var(--text-primary)' : 'var(--text-secondary)' }}>
                  {item.label}
                </span>
                <div>
                  {isLoading ? (
                    <RefreshCw size={14} className="animate-spin" color="var(--accent-blue)" />
                  ) : item.passed ? (
                    <Check size={14} color="var(--color-success)" />
                  ) : (
                    <span style={{ color: 'var(--text-muted)' }}>⋯</span>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div
            style={{
              padding: '14px',
              borderRadius: 'var(--radius-md)',
              textAlign: 'center',
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              fontSize: '13px',
              background: isPass ? 'var(--color-success-subtle)' : (isIncomplete ? 'var(--color-warning-subtle)' : 'var(--bg-surface-elevated)'),
              border: isPass ? '1px solid var(--color-success-border)' : (isIncomplete ? '1px solid var(--color-warning-border)' : '1px solid var(--border-subtle)'),
              color: isPass ? 'var(--color-success)' : (isIncomplete ? 'var(--color-warning)' : 'var(--accent-blue)'),
            }}
          >
            {isLoading
              ? 'RUNNING SANDBOX REPLAY...'
              : isPass
              ? '✓ REPLAY PASS: VERIFIED RESULT REPRODUCED EXACTLY'
              : isIncomplete
              ? '⚠ REPLAY INCOMPLETE: REPRODUCIBLE BUT ENVIRONMENT DIFFERED'
              : '✗ REPLAY CRITERIA NOT MET'}
          </div>
        </div>
      </div>
    </div>
  );
}
