import React, { useRef, useState } from 'react';
import { UploadCloud, FileSpreadsheet, CheckCircle, Database } from 'lucide-react';

export default function DatasetSources({
  samples,
  activeSample,
  onSelectSample,
  onUploadFiles,
  uploadedFiles,
  isAuditing,
}) {
  const fileInputRef = useRef(null);
  const [isDragOver, setIsDragOver] = useState(false);

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files?.length > 0) {
      onUploadFiles(e.dataTransfer.files);
    }
  };

  return (
    <section className="card-saas animate-fade-in">
      <div className="section-headline-group">
        <div>
          <h2 className="section-h2">
            <Database size={18} color="var(--accent-blue)" />
            Data Sources & Workspaces
          </h2>
          <p className="section-p">
            Connect clean records or real-world messy data with known ambiguities.
          </p>
        </div>
        {uploadedFiles.length > 0 && (
          <span className="badge badge-success">
            <CheckCircle size={12} />
            {isAuditing ? 'Auditing...' : 'AUDITED'}
          </span>
        )}
      </div>

      <div className="sources-grid">
        {/* Left: 1-Click Demo Datasets */}
        <div>
          <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)', display: 'block', marginBottom: '8px' }}>
            Try a Preconfigured Demo Dataset:
          </label>
          <div className="sample-cards-list">
            {samples.map((s) => (
              <div
                key={s.id}
                className={`sample-pick-card ${activeSample === s.id ? 'active' : ''}`}
                onClick={() => onSelectSample(s.id)}
                role="button"
                tabIndex={0}
              >
                <div>
                  <h4 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                    {s.name}
                  </h4>
                  <p style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                    {s.description}
                  </p>
                </div>
                <span className="badge badge-neutral font-mono" style={{ fontSize: '10px' }}>
                  {s.id === 'clean_orders' ? 'Baseline' : s.id === 'messy_duplicates' ? 'Multi-World' : 'Ambiguity'}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Right: Upload Dropzone & Loaded Info */}
        <div>
          <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)', display: 'block', marginBottom: '8px' }}>
            Upload Custom Data:
          </label>
          <input
            type="file"
            ref={fileInputRef}
            style={{ display: 'none' }}
            multiple
            accept=".csv,.xlsx,.json"
            onChange={(e) => {
              if (e.target.files?.length > 0) {
                onUploadFiles(e.target.files);
              }
            }}
          />

          <div
            className={`dropzone-box ${isDragOver ? 'dragover' : ''}`}
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragOver(true);
            }}
            onDragLeave={() => setIsDragOver(false)}
            onDrop={handleDrop}
          >
            <UploadCloud size={28} color="var(--text-muted)" style={{ margin: '0 auto 8px' }} />
            <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
              Drop CSV, XLSX, or JSON files here
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
              or click to browse from local disk
            </div>
          </div>

          {/* Active Dataset Cards */}
          {uploadedFiles.map((f, idx) => (
            <div key={idx} className="active-dataset-card">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <FileSpreadsheet size={15} color="var(--accent-blue)" />
                  {f.filename}
                </span>
                <span className="badge badge-success font-mono" style={{ fontSize: '10px' }}>
                  AUDITED
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '14px', fontSize: '12px', color: 'var(--text-secondary)' }}>
                <span><strong>{f.row_count}</strong> rows</span>
                <span>•</span>
                <span><strong>{f.column_count}</strong> columns</span>
                <span>•</span>
                <span className="font-mono" style={{ fontSize: '10px', color: 'var(--text-muted)' }} title={f.sha256}>
                  SHA-256: {f.sha256?.substring(0, 10)}...
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
