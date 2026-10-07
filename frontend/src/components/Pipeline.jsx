import React from 'react';
import { Check, Clock, AlertCircle, PlayCircle } from 'lucide-react';

export default function Pipeline({ steps, elapsedSeconds, isRunning }) {
  // Canonical 7 stages
  const defaultStages = [
    { num: '01', name: 'AUDIT', key: 'AUDIT' },
    { num: '02', name: 'PLAN', key: 'PLAN' },
    { num: '03', name: 'REPAIR', key: 'REPAIR WORLDS' },
    { num: '04', name: 'COMPUTE', key: 'COMPUTE' },
    { num: '05', name: 'VERIFY', key: 'VERIFY' },
    { num: '06', name: 'TRUTH GATE', key: 'TRUTH GATE' },
    { num: '07', name: 'PROOF', key: 'PROOF CARD' },
  ];

  const getStepStatus = (stageKey) => {
    if (!steps || steps.length === 0) {
      return isRunning ? 'running' : 'pending';
    }
    const found = steps.find(
      (s) => s.name?.toUpperCase().includes(stageKey) || stageKey.includes(s.name?.toUpperCase())
    );
    if (!found) return 'pending';
    if (found.status === 'PASSED') return 'passed';
    if (found.status === 'BLOCKED') return 'blocked';
    return found.status?.toLowerCase() || 'pending';
  };

  return (
    <section className="pipeline-card animate-fade-in">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <PlayCircle size={16} color="var(--accent-blue)" />
          <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.01em' }}>
            Deterministic 7-Stage Execution Pipeline
          </span>
        </div>
        <div className="font-mono text-muted" style={{ fontSize: '12px' }}>
          Duration: <strong style={{ color: 'var(--text-primary)' }}>{elapsedSeconds.toFixed(1)}s</strong>
        </div>
      </div>

      <div className="pipeline-steps-track">
        {defaultStages.map((stage, idx) => {
          const status = getStepStatus(stage.key);
          return (
            <div
              key={idx}
              className={`pipeline-step-item ${status}`}
              title={`${stage.name}: ${status.toUpperCase()}`}
            >
              <span className="pipeline-step-num font-mono">{stage.num}</span>
              <span className="step-text-name" style={{ fontSize: '12px', fontWeight: 600 }}>
                {stage.name}
              </span>
              <div style={{ marginLeft: 'auto' }}>
                {status === 'passed' && <Check size={14} color="var(--color-success)" />}
                {status === 'blocked' && <AlertCircle size={14} color="var(--color-danger)" />}
                {status === 'running' && <span className="pulse-dot" style={{ width: '6px', height: '6px' }} />}
                {status === 'pending' && <Clock size={12} color="var(--text-muted)" />}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
