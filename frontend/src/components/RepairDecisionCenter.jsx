import React from 'react';
import { GitBranch, Sliders, AlertTriangle, Layers, TrendingUp } from 'lucide-react';

export default function RepairDecisionCenter({
  duplicatePolicy,
  setDuplicatePolicy,
  datePolicy,
  setDatePolicy,
  impactAnalysis,
  repairWorlds,
}) {
  const hasWorlds = repairWorlds && repairWorlds.length > 0;
  const isStable = impactAnalysis?.decision_stable;

  return (
    <section className="card-saas animate-fade-in" style={{ border: '1px solid rgba(59, 130, 246, 0.3)' }}>
      <div className="section-headline-group">
        <div>
          <h2 className="section-h2">
            <GitBranch size={18} color="var(--accent-blue)" />
            Repair Decision Center
          </h2>
          <p className="section-p">
            ProofLens never silently modifies your source data. Choose how uncertainty should be handled.
          </p>
        </div>
        <span className="badge badge-success font-mono" style={{ fontSize: '11px' }}>
          NON-DESTRUCTIVE REPAIR POLICY
        </span>
      </div>

      <div className="repair-policies-grid">
        {/* Policy 1: Duplicates */}
        <div className="policy-card">
          <div className="policy-card-title">
            <span>Duplicate Records Policy</span>
            <span className="badge badge-warning">High Impact</span>
          </div>
          <p className="policy-card-impact">
            Duplicate rows alter aggregation sums, averages, and group counts. Select handling policy:
          </p>

          <div className="policy-options-list">
            <label
              className={`policy-option-row ${duplicatePolicy === 'COMPARE' ? 'active' : ''}`}
              onClick={() => setDuplicatePolicy('COMPARE')}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <input
                  type="radio"
                  name="dup_policy"
                  checked={duplicatePolicy === 'COMPARE'}
                  onChange={() => setDuplicatePolicy('COMPARE')}
                  style={{ accentColor: 'var(--accent-blue)' }}
                />
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                    Compare Worlds (Recommended)
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    Branch into parallel worlds to measure duplicate sensitivity
                  </div>
                </div>
              </div>
              <span className="badge badge-blue">MULTI-WORLD</span>
            </label>

            <label
              className={`policy-option-row ${duplicatePolicy === 'EXACT_DEDUP' ? 'active' : ''}`}
              onClick={() => setDuplicatePolicy('EXACT_DEDUP')}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <input
                  type="radio"
                  name="dup_policy"
                  checked={duplicatePolicy === 'EXACT_DEDUP'}
                  onChange={() => setDuplicatePolicy('EXACT_DEDUP')}
                  style={{ accentColor: 'var(--accent-blue)' }}
                />
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                    Fix: Exact Deduplication
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    Drop exact duplicate rows from downstream compute
                  </div>
                </div>
              </div>
              <span className="badge badge-neutral">DEDUP</span>
            </label>

            <label
              className={`policy-option-row ${duplicatePolicy === 'KEEP' ? 'active' : ''}`}
              onClick={() => setDuplicatePolicy('KEEP')}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <input
                  type="radio"
                  name="dup_policy"
                  checked={duplicatePolicy === 'KEEP'}
                  onChange={() => setDuplicatePolicy('KEEP')}
                  style={{ accentColor: 'var(--accent-blue)' }}
                />
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                    Keep: Preserve All Duplicates
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    Retain duplicate rows as legitimate separate events
                  </div>
                </div>
              </div>
              <span className="badge badge-neutral">KEEP</span>
            </label>
          </div>
        </div>

        {/* Policy 2: Dates */}
        <div className="policy-card">
          <div className="policy-card-title">
            <span>Date Format Disambiguation</span>
            <span className="badge badge-purple">Format Ambiguity</span>
          </div>
          <p className="policy-card-impact">
            Unspecified date strings (e.g. 01/02/2024) produce conflicting monthly periods.
          </p>

          <div className="policy-options-list">
            <label
              className={`policy-option-row ${datePolicy === 'COMPARE' ? 'active' : ''}`}
              onClick={() => setDatePolicy('COMPARE')}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <input
                  type="radio"
                  name="date_policy"
                  checked={datePolicy === 'COMPARE'}
                  onChange={() => setDatePolicy('COMPARE')}
                  style={{ accentColor: 'var(--accent-blue)' }}
                />
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                    Compare Worlds (Recommended)
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    Evaluate under both DD/MM and MM/DD conventions
                  </div>
                </div>
              </div>
              <span className="badge badge-purple">MULTI-WORLD</span>
            </label>

            <label
              className={`policy-option-row ${datePolicy === 'DD_MM_YYYY' ? 'active' : ''}`}
              onClick={() => setDatePolicy('DD_MM_YYYY')}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <input
                  type="radio"
                  name="date_policy"
                  checked={datePolicy === 'DD_MM_YYYY'}
                  onChange={() => setDatePolicy('DD_MM_YYYY')}
                  style={{ accentColor: 'var(--accent-blue)' }}
                />
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                    Enforce DD/MM/YYYY (Day First)
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    Standard European / Global chronological convention
                  </div>
                </div>
              </div>
              <span className="badge badge-neutral">EU FORMAT</span>
            </label>

            <label
              className={`policy-option-row ${datePolicy === 'MM_DD_YYYY' ? 'active' : ''}`}
              onClick={() => setDatePolicy('MM_DD_YYYY')}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <input
                  type="radio"
                  name="date_policy"
                  checked={datePolicy === 'MM_DD_YYYY'}
                  onChange={() => setDatePolicy('MM_DD_YYYY')}
                  style={{ accentColor: 'var(--accent-blue)' }}
                />
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                    Enforce MM/DD/YYYY (Month First)
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    Standard United States calendar convention
                  </div>
                </div>
              </div>
              <span className="badge badge-neutral">US FORMAT</span>
            </label>
          </div>
        </div>
      </div>

      {/* When multi-world results exist, show World A / World B values & stability */}
      {hasWorlds && impactAnalysis && (
        <div style={{ background: 'var(--bg-surface-elevated)', borderRadius: 'var(--radius-md)', padding: '16px', border: '1px solid var(--border-subtle)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
            <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Layers size={15} color="var(--accent-blue)" />
              Branching Repair Worlds Computed:
            </span>
            <span className={`badge ${isStable ? 'badge-success' : 'badge-warning'}`}>
              {isStable ? 'DECISION STABLE' : 'DECISION SENSITIVE'}
            </span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '10px', marginBottom: '14px' }}>
            {repairWorlds.map((w, idx) => {
              const val = impactAnalysis.world_results?.[w.world_id];
              const polSummary = (w.policies || []).map(p => `${p.selected_action}`).join(', ') || 'Original';
              return (
                <div key={idx} style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', padding: '10px 14px' }}>
                  <div style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                    {w.world_id} • {polSummary}
                  </div>
                  <div style={{ fontSize: '18px', fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', marginTop: '4px' }}>
                    {val !== undefined && val !== null ? (typeof val === 'number' ? `$${val.toLocaleString()}` : val) : 'N/A'}
                  </div>
                </div>
              );
            })}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', background: 'var(--bg-surface)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', fontSize: '12px' }}>
            <div>
              <span style={{ color: 'var(--text-muted)' }}>Value Range: </span>
              <strong className="font-mono text-primary">${impactAnalysis.minimum ?? '--'} — ${impactAnalysis.maximum ?? '--'}</strong>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)' }}>Spread: </span>
              <strong className="font-mono" style={{ color: impactAnalysis.spread > 0 ? 'var(--color-warning)' : 'var(--color-success)' }}>
                ${impactAnalysis.spread ?? '--'}
              </strong>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
