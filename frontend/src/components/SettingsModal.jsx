import React from 'react';
import { Settings, X, Cpu, CheckCircle } from 'lucide-react';

export default function SettingsModal({ isOpen, onClose }) {
  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', borderBottom: '1px solid var(--border-subtle)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Cpu size={18} color="var(--accent-blue)" />
            <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
              System Architecture & Core Laws
            </h3>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
          >
            <X size={18} />
          </button>
        </div>

        <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '14px', fontSize: '13px' }}>
          <div style={{ background: 'var(--bg-surface-elevated)', padding: '12px 14px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
              Core Invariant Law
            </div>
            <div style={{ fontSize: '14px', fontWeight: 700, color: '#38bdf8', marginTop: '4px', fontFamily: 'var(--font-mono)' }}>
              LLM PROPOSES. CODE COMPUTES. VERIFICATION DECIDES. NO PROOF = NO NUMBER.
            </div>
          </div>

          <div>
            <span style={{ color: 'var(--text-muted)' }}>Backend Engine: </span>
            <strong>FastAPI + DuckDB + Deterministic Planner</strong>
          </div>

          <div>
            <span style={{ color: 'var(--text-muted)' }}>Sandbox Isolation: </span>
            <span className="badge badge-success">Active Subprocess Worker</span>
          </div>

          <div>
            <span style={{ color: 'var(--text-muted)' }}>Dual-Path Verifier: </span>
            <span className="badge badge-success">DuckDB Independent SQL</span>
          </div>

          <div>
            <span style={{ color: 'var(--text-muted)' }}>Truth Gate: </span>
            <span className="badge badge-success">Multi-World Skeptic Review</span>
          </div>
        </div>
      </div>
    </div>
  );
}
