import React, { useState, useEffect } from 'react';
import { prooflensApi } from '../api/prooflensApi';
import Navbar from '../components/Navbar';
import AnalysisHero from '../components/AnalysisHero';
import QuestionInput from '../components/QuestionInput';
import DatasetSources from '../components/DatasetSources';
import DataHealth from '../components/DataHealth';
import RepairDecisionCenter from '../components/RepairDecisionCenter';
import Pipeline from '../components/Pipeline';
import ResultCard from '../components/ResultCard';
import RefusalCard from '../components/RefusalCard';
import MultiWorldTable from '../components/MultiWorldTable';
import ProofCard from '../components/ProofCard';
import CodeViewer from '../components/CodeViewer';
import ReplayModal from '../components/ReplayModal';
import SavedProofsModal from '../components/SavedProofsModal';
import SettingsModal from '../components/SettingsModal';
import { AlertTriangle, X } from 'lucide-react';

export default function Workspace() {
  // Navigation
  const [activeTab, setActiveTab] = useState('workspace');

  // Datasets & Session
  const [samples, setSamples] = useState([]);
  const [activeSample, setActiveSample] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [auditLedger, setAuditLedger] = useState(null);
  const [isAuditing, setIsAuditing] = useState(false);

  // Policies
  const [duplicatePolicy, setDuplicatePolicy] = useState('COMPARE');
  const [datePolicy, setDatePolicy] = useState('COMPARE');

  // Query & Analysis
  const [question, setQuestion] = useState('Total order amount');
  const [isLoading, setIsLoading] = useState(false);
  const [pipelineSteps, setPipelineSteps] = useState([]);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);

  // Modals & Proofs
  const [proofs, setProofs] = useState([]);
  const [isReplayOpen, setIsReplayOpen] = useState(false);
  const [replayData, setReplayData] = useState(null);
  const [isReplaying, setIsReplaying] = useState(false);
  const [isSavedProofsOpen, setIsSavedProofsOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  // Load sample dataset metadata & stored proofs count on mount
  useEffect(() => {
    async function init() {
      await loadSamplesList();
      await refreshProofs();
      // Auto-load Clean Orders so user can analyze immediately
      try {
        await handleSelectSample('clean_orders');
      } catch (_) {}
    }
    init();
  }, []);

  const loadSamplesList = async () => {
    try {
      const data = await prooflensApi.getSamples();
      setSamples(data);
    } catch (_) {
      // Fallback local list if API not yet ready
      setSamples([
        { id: 'clean_orders', name: 'Clean Orders', description: 'Baseline verified computation ($600.0)', filename: 'clean_orders.csv' },
        { id: 'messy_duplicates', name: 'Duplicate Transactions', description: 'Multi-world spread ($300.0 vs $400.0)', filename: 'messy_duplicates.csv' },
        { id: 'ambiguous_dates', name: 'Ambiguous Dates', description: 'DD/MM vs MM/DD calendar interpretation', filename: 'ambiguous_dates.csv' },
      ]);
    }
  };

  const refreshProofs = async () => {
    try {
      const data = await prooflensApi.getProofs();
      setProofs(data);
    } catch (_) {}
  };

  // Sample Selection
  const handleSelectSample = async (sampleId) => {
    try {
      setIsAuditing(true);
      setActiveSample(sampleId);
      setErrorMessage(null);
      const res = await prooflensApi.loadSample(sampleId);
      setSessionId(res.session_id);
      setUploadedFiles(res.files || []);
      setAuditLedger(res.audit_ledger || null);
      setAnalysisResult(null);
      setPipelineSteps([]);
    } catch (err) {
      setErrorMessage(`Error loading sample: ${err.message}`);
    } finally {
      setIsAuditing(false);
    }
  };

  // Upload Custom Files
  const handleUploadFiles = async (files) => {
    try {
      setIsAuditing(true);
      setActiveSample(null);
      setErrorMessage(null);
      const res = await prooflensApi.uploadFiles(files);
      setSessionId(res.session_id);
      setUploadedFiles(res.files || []);
      setAuditLedger(res.audit_ledger || null);
      setAnalysisResult(null);
      setPipelineSteps([]);
    } catch (err) {
      setErrorMessage(`Upload error: ${err.message}`);
    } finally {
      setIsAuditing(false);
    }
  };

  // Execute Analysis
  const handleRunAnalysis = async () => {
    if (!sessionId) {
      setErrorMessage('Please select a demonstration dataset or upload your data first.');
      return;
    }
    if (!question.trim()) {
      setErrorMessage('Please enter a question to analyze.');
      return;
    }

    setIsLoading(true);
    setAnalysisResult(null);
    setPipelineSteps([]);
    setErrorMessage(null);
    const startTime = performance.now();

    const interval = setInterval(() => {
      setElapsedSeconds((performance.now() - startTime) / 1000);
    }, 100);

    try {
      const res = await prooflensApi.analyzeQuestion({
        sessionId,
        question: question.trim(),
        policyOverrides: {
          DUPLICATE_ROWS: duplicatePolicy,
          AMBIGUOUS_DATE_FORMAT: datePolicy,
        },
        plannerType: 'deterministic',
      });

      clearInterval(interval);
      setElapsedSeconds((performance.now() - startTime) / 1000);
      setPipelineSteps(res.pipeline_steps || []);
      setAnalysisResult(res);
      refreshProofs();
    } catch (err) {
      clearInterval(interval);
      setErrorMessage(`Analysis Error: ${err.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  // Replay
  const handleExecuteReplay = async () => {
    const proofId = analysisResult?.proof_id;
    if (!proofId) {
      setErrorMessage('No proof artifact available to replay.');
      return;
    }

    setIsReplayOpen(true);
    setIsReplaying(true);
    setReplayData(null);

    try {
      const res = await prooflensApi.replayProof(proofId);
      setReplayData(res);
    } catch (err) {
      setErrorMessage(`Replay error: ${err.message}`);
    } finally {
      setIsReplaying(false);
    }
  };

  // Inspect existing proof from registry
  const handleLoadSpecificProof = async (proofId) => {
    try {
      setErrorMessage(null);
      const proofObj = await prooflensApi.getProof(proofId);
      setAnalysisResult({
        status: proofObj.status,
        result: proofObj.answer,
        answer: proofObj.answer ? `Result loaded from stored proof: ${proofObj.answer}` : 'Answer blocked by TruthGate.',
        answer_blocked: proofObj.status === 'NOT_VERIFIED' || proofObj.status === 'AMBIGUOUS' || proofObj.status === 'UNANSWERABLE',
        proof_id: proofId,
        proof_card: proofObj,
        repair_worlds: proofObj.repair_worlds || [],
        impact_analysis: proofObj.impact_range ? { minimum: proofObj.impact_range[0], maximum: proofObj.impact_range[1], spread: 0, decision_stable: true } : null,
        generated_code: proofObj.analysis_code_path || null,
        verification_summary: proofObj.verification_results || {},
      });
    } catch (err) {
      setErrorMessage(`Failed to load proof: ${err.message}`);
    }
  };

  const scrollToElement = (id) => {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth' });
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        proofsCount={proofs.length}
        onOpenProofs={() => setIsSavedProofsOpen(true)}
        onOpenSettings={() => setIsSettingsOpen(true)}
      />

      <main className="app-container">
        {/* Error Notification Banner */}
        {errorMessage && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '12px 18px',
            borderRadius: 'var(--radius-md)',
            background: 'var(--color-danger-subtle)',
            border: '1px solid var(--color-danger-border)',
            color: 'var(--color-danger)',
            fontSize: '13px',
            fontWeight: 500,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <AlertTriangle size={18} color="var(--color-danger)" style={{ flexShrink: 0 }} />
              <span>{errorMessage}</span>
            </div>
            <button
              onClick={() => setErrorMessage(null)}
              style={{ background: 'transparent', border: 'none', color: 'var(--color-danger)', cursor: 'pointer', padding: '4px' }}
            >
              <X size={16} />
            </button>
          </div>
        )}

        {/* Hero Section */}
        <AnalysisHero />

        {/* Analytical Command Bar */}
        <QuestionInput
          question={question}
          setQuestion={setQuestion}
          onAnalyze={handleRunAnalysis}
          isLoading={isLoading}
          hasData={!!sessionId}
        />

        {/* 1. Data Sources */}
        <DatasetSources
          samples={samples}
          activeSample={activeSample}
          onSelectSample={handleSelectSample}
          onUploadFiles={handleUploadFiles}
          uploadedFiles={uploadedFiles}
          isAuditing={isAuditing}
        />

        {/* 2. Data Health & Audit */}
        {auditLedger && (
          <DataHealth
            auditLedger={auditLedger}
            uploadedFiles={uploadedFiles}
          />
        )}

        {/* 3. Repair Decision Center */}
        {auditLedger && (
          <RepairDecisionCenter
            duplicatePolicy={duplicatePolicy}
            setDuplicatePolicy={setDuplicatePolicy}
            datePolicy={datePolicy}
            setDatePolicy={setDatePolicy}
            impactAnalysis={analysisResult?.impact_analysis}
            repairWorlds={analysisResult?.repair_worlds}
          />
        )}

        {/* 4. Execution Pipeline Progress */}
        {(isLoading || pipelineSteps.length > 0) && (
          <Pipeline
            steps={pipelineSteps}
            elapsedSeconds={elapsedSeconds}
            isRunning={isLoading}
          />
        )}

        {/* 5. Analytical Verdict Focal Point */}
        {analysisResult && (
          <div>
            {!analysisResult.answer_blocked && analysisResult.result !== null ? (
              <ResultCard
                result={analysisResult.result}
                answer={analysisResult.answer}
                status={analysisResult.status}
                proofId={analysisResult.proof_id}
                onViewProof={() => scrollToElement('proof-card-section')}
                onViewCode={() => scrollToElement('code-viewer-section')}
                onReplay={handleExecuteReplay}
              />
            ) : (
              <RefusalCard
                status={analysisResult.status}
                answer={analysisResult.answer}
                onViewProof={() => scrollToElement('proof-card-section')}
                onViewCode={() => scrollToElement('code-viewer-section')}
              />
            )}
          </div>
        )}

        {/* 6. Multi-World Sensitivity Analysis */}
        {analysisResult?.repair_worlds?.length > 1 && (
          <MultiWorldTable
            repairWorlds={analysisResult.repair_worlds}
            impactAnalysis={analysisResult.impact_analysis}
          />
        )}

        {/* 7. Cryptographic Proof Card */}
        {analysisResult?.proof_card && (
          <ProofCard
            proofCard={analysisResult.proof_card}
            proofId={analysisResult.proof_id}
            onReplay={handleExecuteReplay}
          />
        )}

        {/* 8. Dual-Path Code Viewer */}
        {analysisResult && (
          <CodeViewer
            pythonCode={analysisResult.generated_code}
            duckdbSql={analysisResult.verification_summary?.duckdb_sql}
          />
        )}
      </main>

      {/* Modals */}
      <ReplayModal
        isOpen={isReplayOpen}
        onClose={() => setIsReplayOpen(false)}
        replayData={replayData}
        isLoading={isReplaying}
        proofId={analysisResult?.proof_id}
      />

      <SavedProofsModal
        isOpen={isSavedProofsOpen}
        onClose={() => setIsSavedProofsOpen(false)}
        proofs={proofs}
        onLoadProof={handleLoadSpecificProof}
      />

      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
      />
    </div>
  );
}
