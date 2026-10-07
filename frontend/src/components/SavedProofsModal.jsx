import React from 'react';
import { FileCheck, X, Eye, ExternalLink } from 'lucide-react';

export default function SavedProofsModal({ isOpen, onClose, proofs, onLoadProof }) {
  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog" style={{ maxWidth: '680px' }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', borderBottom: '1px solid var(--border-subtle)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <FileCheck size={18} color="var(--accent-blue)" />
            <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
              Proof Registry ({proofs.length})
            </h3>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
          >
            <X size={18} />
          </button>
        </div>

        <div style={{ padding: '20px', maxHeight: '480px', overflowY: 'auto' }}>
          {proofs.length === 0 ? (
            <p style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px', padding: '24px 0' }}>
              No proofs generated yet in this session. Run an analysis to generate an authoritative Proof Card.
            </p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {proofs.map((p, idx) => (
                <div
                  key={idx}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '12px 16px',
                    borderRadius: 'var(--radius-md)',
                    background: 'var(--bg-surface-elevated)',
                    border: '1px solid var(--border-subtle)',
                  }}
                >
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span className="font-mono" style={{ fontSize: '12px', fontWeight: 700, color: 'var(--accent-blue)' }}>
                        {p.proof_id}
                      </span>
                      <span className={`badge ${p.status === 'VERIFIED' ? 'badge-success' : 'badge-danger'}`} style={{ fontSize: '10px' }}>
                        {p.status}
                      </span>
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                      "{p.question}"
                    </div>
                    <div className="font-mono text-muted" style={{ fontSize: '10px', marginTop: '2px' }}>
                      Result: <strong style={{ color: 'var(--text-primary)' }}>{p.result ?? 'BLOCKED'}</strong> • {new Date(p.created_at).toLocaleString()}
                    </div>
                  </div>

                  <button
                    className="btn btn-secondary"
                    onClick={() => {
                      onLoadProof(p.proof_id);
                      onClose();
                    }}
                    style={{ fontSize: '12px', padding: '6px 12px' }}
                  >
                    <Eye size={13} />
                    <span>Inspect</span>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
