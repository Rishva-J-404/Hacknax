import React from 'react';
import { ShieldCheck, Database, History, Settings, FileCheck } from 'lucide-react';

export default function Navbar({ activeTab, setActiveTab, proofsCount, onOpenProofs, onOpenSettings }) {
  return (
    <header className="app-header">
      <div className="brand-wrapper">
        <div className="brand-icon-box">
          <ShieldCheck size={20} />
        </div>
        <div className="brand-meta">
          <div className="brand-name">
            PROOFLENS
            <span className="badge badge-blue">Enterprise Truth Engine</span>
          </div>
          <span className="brand-subtitle">
            LLM PROPOSES · CODE COMPUTES · VERIFICATION DECIDES · NO PROOF = NO NUMBER
          </span>
        </div>
      </div>

      <nav className="nav-tabs-group" aria-label="Main Navigation">
        <button
          className={`nav-tab-item ${activeTab === 'workspace' ? 'active' : ''}`}
          onClick={() => setActiveTab('workspace')}
        >
          Workspace
        </button>
        <button
          className={`nav-tab-item ${activeTab === 'analysis' ? 'active' : ''}`}
          onClick={() => setActiveTab('analysis')}
        >
          Analysis
        </button>
        <button
          className={`nav-tab-item ${activeTab === 'proofs' ? 'active' : ''}`}
          onClick={() => {
            setActiveTab('proofs');
            onOpenProofs?.();
          }}
        >
          Proofs
        </button>
      </nav>

      <div className="header-right">
        <div className="status-badge-live">
          <span className="pulse-dot" />
          <span>Verifier Engine Active</span>
        </div>

        <button
          className="btn btn-secondary"
          onClick={onOpenProofs}
          style={{ fontSize: '12px', padding: '6px 12px' }}
        >
          <FileCheck size={14} />
          <span>Saved Proofs ({proofsCount})</span>
        </button>

        <button
          className="btn btn-secondary"
          onClick={onOpenSettings}
          title="Architecture & Settings"
          style={{ padding: '6px 10px' }}
        >
          <Settings size={14} />
        </button>
      </div>
    </header>
  );
}
