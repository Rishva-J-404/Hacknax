import React from 'react';
import { Activity, ShieldAlert, CheckCircle2 } from 'lucide-react';

export default function DataHealth({ auditLedger, uploadedFiles }) {
  const issues = auditLedger?.all_issues || [];
  const totalRows = uploadedFiles.reduce((acc, f) => acc + (f.row_count || 0), 0);
  const totalTables = uploadedFiles.length;
  const integrityScore = issues.length === 0 ? 100 : Math.max(70, 100 - issues.length * 12);

  return (
    <section className="card-saas animate-fade-in">
      <div className="section-headline-group">
        <div>
          <h2 className="section-h2">
            <Activity size={18} color="var(--accent-blue)" />
            Data Quality & Health Audit
          </h2>
          <p className="section-p">
            Automated deterministic audit of schemas, null keys, duplicate tuples, and format ambiguity.
          </p>
        </div>
        <span className={`badge ${issues.length === 0 ? 'badge-success' : 'badge-warning'}`}>
          {issues.length === 0 ? 'CLEAN · 0 ANOMALIES' : `${issues.length} ISSUE(S) DETECTED`}
        </span>
      </div>

      {/* KPI Summary Row */}
      <div className="health-metrics-grid">
        <div className="metric-card">
          <div className="metric-label">Data Integrity</div>
          <div className="metric-num" style={{ color: integrityScore > 85 ? 'var(--color-success)' : 'var(--color-warning)' }}>
            {integrityScore}%
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-label">Audited Tables</div>
          <div className="metric-num">
            {totalTables}
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-label">Total Records</div>
          <div className="metric-num">
            {totalRows.toLocaleString()}
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-label">Detected Issues</div>
          <div className="metric-num" style={{ color: issues.length === 0 ? 'var(--color-success)' : 'var(--color-warning)' }}>
            {issues.length}
          </div>
        </div>
      </div>

      {/* Issues Table or Clean Banner */}
      {issues.length === 0 ? (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          padding: '14px 18px',
          borderRadius: 'var(--radius-md)',
          background: 'var(--color-success-subtle)',
          border: '1px solid var(--color-success-border)',
        }}>
          <CheckCircle2 size={20} color="var(--color-success)" style={{ flexShrink: 0 }} />
          <div>
            <h4 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
              All Ingested Records Meet Schema Integrity Standards
            </h4>
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
              No primary key collisions, duplicate records, unparseable dates, or currency/unit mismatches were detected.
            </p>
          </div>
        </div>
      ) : (
        <div style={{ overflowX: 'auto', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', background: 'var(--bg-surface-elevated)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
            <thead>
              <tr style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)' }}>
                <th style={{ padding: '10px 16px', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Severity</th>
                <th style={{ padding: '10px 16px', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Issue Type</th>
                <th style={{ padding: '10px 16px', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Affected Source / Column</th>
                <th style={{ padding: '10px 16px', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Impact & Description</th>
                <th style={{ padding: '10px 16px', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Repair Options</th>
              </tr>
            </thead>
            <tbody>
              {issues.map((iss, idx) => (
                <tr key={idx} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '12px 16px' }}>
                    <span className={`badge ${iss.severity === 'CRITICAL' ? 'badge-danger' : 'badge-warning'}`}>
                      {iss.severity}
                    </span>
                  </td>
                  <td style={{ padding: '12px 16px', fontWeight: 600, color: 'var(--text-primary)' }}>
                    {iss.issue_type}
                  </td>
                  <td style={{ padding: '12px 16px', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                    {iss.affected_source || 'table'}: {(iss.affected_columns || []).join(', ') || 'all rows'}
                  </td>
                  <td style={{ padding: '12px 16px', color: 'var(--text-secondary)' }}>
                    {iss.description}
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    <span className="badge badge-blue">
                      KEEP / FIX / COMPARE
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
