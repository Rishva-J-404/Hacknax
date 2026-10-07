import React from 'react';
import { Layers, Activity } from 'lucide-react';

export default function MultiWorldTable({ repairWorlds, impactAnalysis }) {
  if (!repairWorlds || repairWorlds.length === 0) return null;

  const results = impactAnalysis?.world_results || {};
  const baselineVal = results[repairWorlds[0]?.world_id];
  const isStable = impactAnalysis?.decision_stable;

  return (
    <section className="card-saas animate-fade-in">
      <div className="section-headline-group">
        <div>
          <h2 className="section-h2">
            <Layers size={18} color="var(--accent-blue)" />
            Multi-World Sensitivity & Impact Analysis
          </h2>
          <p className="section-p">
            Cross-world comparison of results produced under each defensible repair world.
          </p>
        </div>
        <span className={`badge ${isStable ? 'badge-success' : 'badge-warning'}`}>
          {isStable ? 'DECISION STABLE' : 'DECISION SENSITIVE'}
        </span>
      </div>

      <div style={{ overflowX: 'auto', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', background: 'var(--bg-surface-elevated)', marginBottom: '1rem' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
          <thead>
            <tr style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)' }}>
              <th style={{ padding: '10px 16px', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>World</th>
              <th style={{ padding: '10px 16px', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Repair Policy</th>
              <th style={{ padding: '10px 16px', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Result</th>
              <th style={{ padding: '10px 16px', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Delta</th>
              <th style={{ padding: '10px 16px', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Stability</th>
              <th style={{ padding: '10px 16px', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {repairWorlds.map((w, idx) => {
              const val = results[w.world_id];
              const polStr = (w.policies || []).map((p) => `${p.selected_action}`).join(', ') || 'Baseline';
              let delta = '--';
              if (typeof val === 'number' && typeof baselineVal === 'number') {
                const diff = val - baselineVal;
                delta = diff === 0 ? 'Baseline' : (diff > 0 ? `+$${diff.toFixed(2)}` : `-$${Math.abs(diff).toFixed(2)}`);
              }

              return (
                <tr key={idx} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '12px 16px', fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--text-primary)' }}>
                    {w.world_id}
                  </td>
                  <td style={{ padding: '12px 16px', color: 'var(--text-secondary)' }}>
                    {polStr}
                  </td>
                  <td style={{ padding: '12px 16px', fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--text-primary)' }}>
                    {val !== undefined && val !== null ? (typeof val === 'number' ? `$${val.toLocaleString()}` : val) : 'N/A'}
                  </td>
                  <td style={{ padding: '12px 16px', fontFamily: 'var(--font-mono)', fontSize: '12px', color: delta === 'Baseline' ? 'var(--text-muted)' : 'var(--color-warning)' }}>
                    {delta}
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    <span className={`badge ${isStable ? 'badge-success' : 'badge-warning'}`}>
                      {isStable ? 'Stable' : 'Sensitive'}
                    </span>
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    <span className="badge badge-neutral">
                      EVALUATED
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {impactAnalysis && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', background: 'var(--bg-surface-elevated)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', fontSize: '13px' }}>
          <div>
            <span style={{ color: 'var(--text-muted)' }}>Minimum: </span>
            <strong className="font-mono text-primary">${impactAnalysis.minimum ?? '--'}</strong>
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)' }}>Maximum: </span>
            <strong className="font-mono text-primary">${impactAnalysis.maximum ?? '--'}</strong>
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)' }}>Total Spread: </span>
            <strong className="font-mono" style={{ color: impactAnalysis.spread > 0 ? 'var(--color-warning)' : 'var(--color-success)' }}>
              ${impactAnalysis.spread ?? '--'}
            </strong>
          </div>
        </div>
      )}
    </section>
  );
}
