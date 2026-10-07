// ProofLens Web Application State & Logic

class ProofLensApp {
  constructor() {
    this.sessionId = null;
    this.lastAnalysis = null;
    this.initElements();
    this.bindEvents();
    this.loadProofsCount();
  }

  initElements() {
    this.sessionBadge = document.getElementById('session-badge');
    this.dropZone = document.getElementById('drop-zone');
    this.fileInput = document.getElementById('file-input');
    this.filesTableContainer = document.getElementById('files-table-container');
    this.filesTbody = document.getElementById('files-tbody');
    
    this.auditBadge = document.getElementById('audit-badge');
    this.auditPlaceholder = document.getElementById('audit-placeholder');
    this.auditContent = document.getElementById('audit-content');
    this.issuesList = document.getElementById('issues-list');

    this.inputQuestion = document.getElementById('input-question');
    this.btnRun = document.getElementById('btn-run');
    this.stepperPanel = document.getElementById('pipeline-stepper');
    this.stepperStages = document.getElementById('stepper-stages');
    this.pipelineTimer = document.getElementById('pipeline-timer');

    this.resultContainer = document.getElementById('result-card-container');
    this.verdictBadge = document.getElementById('verdict-status-badge');
    this.resultPermittedBox = document.getElementById('result-permitted-box');
    this.resultBlockedBox = document.getElementById('result-blocked-box');
    this.resultNumber = document.getElementById('result-number');
    this.resultAnswerText = document.getElementById('result-answer-text');
    this.blockedTitle = document.getElementById('blocked-title');
    this.blockedExplanation = document.getElementById('blocked-explanation');
    this.blockedRemediation = document.getElementById('blocked-remediation');

    this.worldsPanel = document.getElementById('worlds-panel');
    this.worldsTbody = document.getElementById('worlds-tbody');
    this.btnWorldsCount = document.getElementById('btn-worlds-count');
    this.stabilityBadge = document.getElementById('stability-badge');
    this.metricMin = document.getElementById('metric-min');
    this.metricMax = document.getElementById('metric-max');
    this.metricSpread = document.getElementById('metric-spread');

    this.codePanel = document.getElementById('code-panel');
    this.codeBlock = document.getElementById('code-content-block');
    this.btnCopyCode = document.getElementById('btn-copy-code');

    this.proofPanel = document.getElementById('proof-panel');
    this.proofJsonBlock = document.getElementById('proof-json-block');
    this.btnDownloadProof = document.getElementById('btn-download-proof');

    this.replayModal = document.getElementById('replay-modal');
    this.modalClose = document.getElementById('modal-close');
    this.btnRunReplay = document.getElementById('btn-run-replay');
    this.proofsCount = document.getElementById('proofs-count');
  }

  bindEvents() {
    // Sample datasets
    document.querySelectorAll('.btn-sample').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const sampleId = e.currentTarget.dataset.sample;
        this.loadSample(sampleId);
      });
    });

    // File drop & select
    this.dropZone.addEventListener('click', () => this.fileInput.click());
    this.dropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      this.dropZone.classList.add('dragover');
    });
    this.dropZone.addEventListener('dragleave', () => this.dropZone.classList.remove('dragover'));
    this.dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      this.dropZone.classList.remove('dragover');
      if (e.dataTransfer.files.length > 0) {
        this.uploadFiles(e.dataTransfer.files);
      }
    });
    this.fileInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        this.uploadFiles(e.target.files);
      }
    });

    // Suggestion pills
    document.querySelectorAll('.pill-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this.inputQuestion.value = btn.dataset.q;
      });
    });

    // Run Analysis
    this.btnRun.addEventListener('click', () => this.runAnalysis());
    this.inputQuestion.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.runAnalysis();
    });

    // Toggles
    document.getElementById('btn-toggle-worlds').addEventListener('click', () => {
      this.worldsPanel.classList.toggle('hidden');
    });
    document.getElementById('btn-toggle-code').addEventListener('click', () => {
      this.codePanel.classList.toggle('hidden');
    });
    document.getElementById('btn-toggle-proof').addEventListener('click', () => {
      this.proofPanel.classList.toggle('hidden');
    });

    // Code copy
    this.btnCopyCode.addEventListener('click', () => {
      navigator.clipboard.writeText(this.codeBlock.textContent);
      this.btnCopyCode.textContent = 'Copied!';
      setTimeout(() => { this.btnCopyCode.textContent = 'Copy Code'; }, 1500);
    });

    // Proof Download
    this.btnDownloadProof.addEventListener('click', () => {
      if (!this.lastAnalysis || !this.lastAnalysis.proof_card) return;
      const blob = new Blob([JSON.stringify(this.lastAnalysis.proof_card, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${this.lastAnalysis.proof_id || 'proof'}.json`;
      a.click();
    });

    // Replay Modal
    this.btnRunReplay.addEventListener('click', () => this.executeReplay());
    this.modalClose.addEventListener('click', () => this.replayModal.classList.add('hidden'));
  }

  async loadProofsCount() {
    try {
      const res = await fetch('/api/proofs');
      if (res.ok) {
        const proofs = await res.json();
        this.proofsCount.textContent = proofs.length;
      }
    } catch (_) {}
  }

  async loadSample(sampleId) {
    try {
      this.auditBadge.textContent = 'Auditing...';
      this.auditBadge.className = 'badge badge-accent';
      const res = await fetch(`/api/samples/${sampleId}/load`, { method: 'POST' });
      if (!res.ok) throw new Error('Failed to load sample');
      const data = await res.json();
      this.handleUploadSuccess(data);
    } catch (err) {
      alert(`Error loading sample: ${err.message}`);
    }
  }

  async uploadFiles(fileList) {
    const formData = new FormData();
    for (let f of fileList) {
      formData.append('files', f);
    }

    try {
      this.auditBadge.textContent = 'Auditing...';
      this.auditBadge.className = 'badge badge-accent';
      const res = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) throw new Error('Upload failed');
      const data = await res.json();
      this.handleUploadSuccess(data);
    } catch (err) {
      alert(`Upload error: ${err.message}`);
    }
  }

  handleUploadSuccess(data) {
    this.sessionId = data.session_id;
    this.sessionBadge.textContent = `Session: ${this.sessionId}`;
    this.sessionBadge.classList.add('text-cyan-400');

    // Render files
    this.filesTbody.innerHTML = '';
    data.files.forEach(f => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="font-bold text-white">${f.filename}</td>
        <td>${f.row_count}</td>
        <td>${f.column_count}</td>
        <td class="text-secondary" title="${f.sha256}">${f.sha256.substring(0, 10)}...</td>
      `;
      this.filesTbody.appendChild(tr);
    });
    this.filesTableContainer.classList.remove('hidden');

    // Render Audit
    const issues = data.audit_ledger?.all_issues || [];
    this.auditPlaceholder.classList.add('hidden');
    this.auditContent.classList.remove('hidden');
    this.issuesList.innerHTML = '';

    if (issues.length === 0) {
      this.auditBadge.textContent = 'CLEAN · 0 ISSUES';
      this.auditBadge.className = 'badge badge-success';
      this.issuesList.innerHTML = `
        <div class="p-2.5 rounded bg-emerald-950/30 border border-emerald-900/50 text-xs text-emerald-300">
          ✓ All loaded columns and records meet schema integrity criteria. No duplicates or ambiguities detected.
        </div>
      `;
    } else {
      this.auditBadge.textContent = `${issues.length} ISSUE(S)`;
      this.auditBadge.className = 'badge badge-warning';

      issues.forEach(iss => {
        const card = document.createElement('div');
        card.className = `issue-card severity-${iss.severity}`;
        card.innerHTML = `
          <div class="flex items-center justify-between">
            <span class="font-bold text-xs text-white">${iss.issue_type}</span>
            <span class="badge ${iss.severity === 'CRITICAL' ? 'badge-danger' : 'badge-warning'}">${iss.severity}</span>
          </div>
          <p class="text-xs text-secondary mt-1">${iss.description || 'Data quality issue detected.'}</p>
          <div class="text-[11px] text-muted font-mono mt-1">Source: ${iss.affected_source || 'table'} | Cols: ${(iss.affected_columns || []).join(', ') || 'N/A'}</div>
        `;
        this.issuesList.appendChild(card);
      });
    }
  }

  async runAnalysis() {
    const question = this.inputQuestion.value.trim();
    if (!question) {
      alert('Please enter a question to analyze.');
      return;
    }
    if (!this.sessionId) {
      alert('Please upload data or select a sample dataset first.');
      return;
    }

    // Get policy overrides
    const dupPolicy = document.querySelector('input[name="policy_duplicates"]:checked')?.value || 'COMPARE';
    const datePolicy = document.querySelector('input[name="policy_dates"]:checked')?.value || 'COMPARE';
    const policyOverrides = {
      DUPLICATE_ROWS: dupPolicy,
      AMBIGUOUS_DATE_FORMAT: datePolicy,
    };

    // Show Stepper
    this.stepperPanel.classList.remove('hidden');
    this.stepperStages.innerHTML = '';
    const stages = ['AUDIT', 'PLAN', 'REPAIR WORLDS', 'COMPUTE', 'VERIFY', 'METAMORPHIC', 'TRUTH GATE', 'PROOF CARD'];
    stages.forEach(st => {
      const box = document.createElement('div');
      box.className = 'step-box status-RUNNING';
      box.id = `step-${st.replace(/\s+/g, '-')}`;
      box.innerHTML = `
        <div class="text-[11px] text-white font-bold">${st}</div>
        <div class="text-[10px] text-cyan-400 mt-1">Processing...</div>
      `;
      this.stepperStages.appendChild(box);
    });

    const startTime = performance.now();
    const timerInterval = setInterval(() => {
      this.pipelineTimer.textContent = `${((performance.now() - startTime) / 1000).toFixed(1)}s`;
    }, 100);

    try {
      this.btnRun.disabled = true;
      this.btnRun.innerHTML = '<span>Verifying...</span>';

      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: this.sessionId,
          question: question,
          policy_overrides: policyOverrides,
          planner_type: 'deterministic',
        }),
      });

      clearInterval(timerInterval);
      this.btnRun.disabled = false;
      this.btnRun.innerHTML = '<span>Analyze & Prove</span>';

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Analysis request failed');
      }

      const data = await res.json();
      this.lastAnalysis = data;
      this.renderAnalysisResult(data);
      this.loadProofsCount();

    } catch (err) {
      clearInterval(timerInterval);
      this.btnRun.disabled = false;
      this.btnRun.innerHTML = '<span>Analyze & Prove</span>';
      alert(`Execution error: ${err.message}`);
    }
  }

  renderAnalysisResult(data) {
    // 1. Update Stepper stages
    (data.pipeline_steps || []).forEach(step => {
      const stepId = `step-${step.name.replace(/\s+/g, '-')}`;
      const el = document.getElementById(stepId);
      if (el) {
        el.className = `step-box status-${step.status}`;
        el.innerHTML = `
          <div class="text-[11px] text-white font-bold">${step.name}</div>
          <div class="text-[10px] ${step.status === 'PASSED' ? 'text-emerald-400' : 'text-red-400'} mt-1">${step.status}</div>
        `;
      }
    });

    // 2. Result Verdict Card
    this.resultContainer.classList.remove('hidden');
    this.verdictBadge.textContent = data.status;
    
    // Status colors
    const statusClasses = {
      'VERIFIED': 'badge-success',
      'VERIFIED_WITH_ASSUMPTION': 'badge-warning',
      'AMBIGUOUS': 'badge-purple',
      'CONTRADICTED': 'badge-danger',
      'UNANSWERABLE': 'badge-neutral',
      'NOT_VERIFIED': 'badge-danger',
    };
    this.verdictBadge.className = `badge ${statusClasses[data.status] || 'badge-neutral'}`;

    if (!data.answer_blocked && data.result !== null) {
      // PERMITTED AUTHORITATIVE NUMBER
      this.resultPermittedBox.classList.remove('hidden');
      this.resultBlockedBox.classList.add('hidden');
      this.resultNumber.textContent = typeof data.result === 'number' ? data.result.toLocaleString() : data.result;
      this.resultAnswerText.textContent = data.answer;
    } else {
      // BLOCKED / REFUSED VIEW
      this.resultPermittedBox.classList.add('hidden');
      this.resultBlockedBox.classList.remove('hidden');

      if (data.status === 'AMBIGUOUS') {
        this.blockedTitle.textContent = 'Ambiguous Data: Multiple Defensible Interpretations';
        this.blockedExplanation.textContent = 'Dropping vs keeping records produces distinct analytical values across repair worlds. TruthGate blocked asserting a single guess.';
        this.blockedRemediation.textContent = 'Remediation: Choose an explicit policy in the Repair Decision Center or inspect the spread in the Compare Worlds panel.';
      } else if (data.status === 'UNANSWERABLE') {
        this.blockedTitle.textContent = 'Question Unanswerable From Available Data';
        this.blockedExplanation.textContent = data.answer || 'One or more required metrics or baseline columns are absent from the ingested tables.';
        this.blockedRemediation.textContent = 'Remediation: Provide tables containing the missing fields or rephrase query using existing schema.';
      } else {
        this.blockedTitle.textContent = 'Answer Blocked by Independent Truth Gate';
        this.blockedExplanation.textContent = data.answer || 'Independent verification or claim checks did not confirm the proposed result.';
        this.blockedRemediation.textContent = 'Remediation: Review generated code and verification discrepancy logs.';
      }
    }

    // 3. Multi-World Panel
    this.btnWorldsCount.textContent = data.repair_worlds?.length || 0;
    this.worldsTbody.innerHTML = '';
    (data.repair_worlds || []).forEach(w => {
      const tr = document.createElement('tr');
      const policiesStr = (w.policies || []).map(p => `${p.issue_type}: ${p.selected_action}`).join(', ') || 'Original baseline';
      const val = data.impact_analysis?.world_results?.[w.world_id];
      tr.innerHTML = `
        <td class="font-bold text-white">${w.world_id}</td>
        <td>${policiesStr}</td>
        <td class="font-bold text-cyan-400 font-mono">${val !== undefined && val !== null ? val : 'N/A'}</td>
        <td><span class="badge badge-neutral">Evaluated</span></td>
      `;
      this.worldsTbody.appendChild(tr);
    });

    if (data.impact_analysis) {
      this.metricMin.textContent = data.impact_analysis.minimum ?? '--';
      this.metricMax.textContent = data.impact_analysis.maximum ?? '--';
      this.metricSpread.textContent = data.impact_analysis.spread ?? '--';
      this.stabilityBadge.textContent = data.impact_analysis.decision_stable ? 'Decision Stable' : 'Decision Sensitive';
      this.stabilityBadge.className = `badge ${data.impact_analysis.decision_stable ? 'badge-success' : 'badge-warning'}`;
    }

    // 4. Code Block
    this.codeBlock.textContent = data.generated_code || '# No generated Python script available.';

    // 5. Proof Card JSON
    this.proofJsonBlock.textContent = JSON.stringify(data.proof_card || {}, null, 2);
  }

  async executeReplay() {
    if (!this.lastAnalysis || !this.lastAnalysis.proof_id) {
      alert('No proof card available to replay.');
      return;
    }

    this.replayModal.classList.remove('hidden');
    const proofId = this.lastAnalysis.proof_id;

    // Reset checklist
    const checkItems = ['check-data-hash', 'check-code-hash', 'check-exec', 'check-result', 'check-verify'];
    checkItems.forEach(id => {
      const el = document.getElementById(id);
      el.className = 'check-item';
      el.querySelector('.check-icon').textContent = '⋯';
    });

    const verdictBox = document.getElementById('replay-verdict-box');
    verdictBox.textContent = 'RUNNING REPLAY SANDBOX...';
    verdictBox.className = 'p-3 rounded text-center font-mono font-bold text-sm bg-surface-2 border border-border text-cyan-400';

    try {
      const res = await fetch(`/api/replay/${proofId}`, { method: 'POST' });
      const data = await res.json();

      const pass = data.overall_status === 'PASS';
      const incomplete = data.overall_status === 'INCOMPLETE';

      document.getElementById('check-data-hash').className = `check-item ${data.data_hash_matched ? 'item-pass' : 'item-fail'}`;
      document.getElementById('check-data-hash').querySelector('.check-icon').textContent = data.data_hash_matched ? '✓' : '✗';

      document.getElementById('check-code-hash').className = `check-item ${data.code_hash_matched ? 'item-pass' : 'item-fail'}`;
      document.getElementById('check-code-hash').querySelector('.check-icon').textContent = data.code_hash_matched ? '✓' : '✗';

      document.getElementById('check-exec').className = `check-item ${data.execution_succeeded ? 'item-pass' : 'item-fail'}`;
      document.getElementById('check-exec').querySelector('.check-icon').textContent = data.execution_succeeded ? '✓' : '✗';

      document.getElementById('check-result').className = `check-item ${data.result_matched ? 'item-pass' : 'item-fail'}`;
      document.getElementById('check-result').querySelector('.check-icon').textContent = data.result_matched ? '✓' : '✗';

      document.getElementById('check-verify').className = `check-item ${data.verification_passed ? 'item-pass' : 'item-fail'}`;
      document.getElementById('check-verify').querySelector('.check-icon').textContent = data.verification_passed ? '✓' : '✗';

      if (pass) {
        verdictBox.textContent = '✓ REPLAY PASS: VERIFIED RESULT REPRODUCED EXACTLY';
        verdictBox.className = 'p-3 rounded text-center font-mono font-bold text-sm bg-emerald-950/60 border border-emerald-500 text-emerald-400';
      } else if (incomplete) {
        verdictBox.textContent = '⚠ REPLAY INCOMPLETE: ORIGINAL INPUTS UNMODIFIED';
        verdictBox.className = 'p-3 rounded text-center font-mono font-bold text-sm bg-amber-950/60 border border-amber-500 text-amber-400';
      } else {
        verdictBox.textContent = '✗ REPLAY FAILED';
        verdictBox.className = 'p-3 rounded text-center font-mono font-bold text-sm bg-red-950/60 border border-red-500 text-red-400';
      }

    } catch (err) {
      verdictBox.textContent = `REPLAY ERROR: ${err.message}`;
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  window.proofLensApp = new ProofLensApp();
});
