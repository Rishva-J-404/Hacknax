import React, { useState } from 'react';
import { Code2, Copy, Check } from 'lucide-react';

export default function CodeViewer({ pythonCode, duckdbSql }) {
  const [activeTab, setActiveTab] = useState('python');
  const [copied, setCopied] = useState(false);

  const currentCode =
    activeTab === 'python'
      ? pythonCode || '# Primary sandboxed Python analysis script.'
      : duckdbSql || '-- Independent secondary DuckDB SQL verification query.\nSELECT SUM(amount) FROM loaded_table;';

  const handleCopy = () => {
    navigator.clipboard.writeText(currentCode);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <section className="code-viewer-box animate-fade-in" id="code-viewer-section">
      <div className="code-viewer-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Code2 size={16} color="var(--accent-blue)" />
          <button
            className={`code-tab-btn ${activeTab === 'python' ? 'active' : ''}`}
            onClick={() => setActiveTab('python')}
          >
            PRIMARY COMPUTATION (Python Sandbox)
          </button>
          <button
            className={`code-tab-btn ${activeTab === 'duckdb' ? 'active' : ''}`}
            onClick={() => setActiveTab('duckdb')}
          >
            INDEPENDENT VERIFICATION (DuckDB SQL)
          </button>
        </div>

        <button className="btn btn-secondary" onClick={handleCopy} style={{ fontSize: '11px', padding: '4px 10px' }}>
          {copied ? <Check size={12} color="var(--color-success)" /> : <Copy size={12} />}
          <span>{copied ? 'Copied!' : 'Copy Code'}</span>
        </button>
      </div>

      <pre className="code-pre-block">
        <code>{currentCode}</code>
      </pre>
    </section>
  );
}
