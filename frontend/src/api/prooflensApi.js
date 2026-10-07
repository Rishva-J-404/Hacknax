/**
 * ProofLens API Client
 * Centralized, type-safe API communication layer.
 * Communicates with FastAPI backend through the /api prefix (proxied in Vite).
 */

const BASE_URL = '/api';

async function handleResponse(res, defaultMsg) {
  if (!res.ok) {
    let errorMsg = `Server error (${res.status} ${res.statusText})`;
    try {
      const text = await res.text();
      try {
        const json = JSON.parse(text);
        if (typeof json.detail === 'string') {
          errorMsg = json.detail;
        } else if (Array.isArray(json.detail)) {
          errorMsg = json.detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
        } else if (json.detail) {
          errorMsg = JSON.stringify(json.detail);
        } else if (json.message) {
          errorMsg = json.message;
        }
      } catch (_) {
        if (text) {
          errorMsg = `${errorMsg}: ${text.slice(0, 150)}`;
        }
      }
    } catch (_) {}
    throw new Error(errorMsg || defaultMsg);
  }
  return res.json();
}

export const prooflensApi = {
  /**
   * Fetch preloaded demonstration datasets.
   */
  async getSamples() {
    let res;
    try {
      res = await fetch(`${BASE_URL}/samples`);
    } catch (netErr) {
      throw new Error(`Cannot connect to backend: ${netErr.message}. Ensure FastAPI is running on port 8000.`);
    }
    return handleResponse(res, 'Failed to fetch sample datasets');
  },

  /**
   * Load a specific sample dataset into a new session and trigger auto-audit.
   */
  async loadSample(sampleId) {
    let res;
    try {
      res = await fetch(`${BASE_URL}/samples/${sampleId}/load`, {
        method: 'POST',
      });
    } catch (netErr) {
      throw new Error(`Cannot connect to backend: ${netErr.message}. Ensure FastAPI is running on port 8000.`);
    }
    return handleResponse(res, `Failed to load sample '${sampleId}'`);
  },

  /**
   * Upload user files (CSV, XLSX, JSON) and perform immediate deterministic audit.
   */
  async uploadFiles(files) {
    const fileList = Array.from(files || []);
    if (fileList.length === 0) {
      throw new Error('Please select at least one file to upload.');
    }
    const formData = new FormData();
    for (const file of fileList) {
      formData.append('files', file);
    }

    let res;
    try {
      res = await fetch(`${BASE_URL}/upload`, {
        method: 'POST',
        body: formData,
      });
    } catch (netErr) {
      throw new Error(`Cannot connect to backend: ${netErr.message}. Ensure FastAPI is running on port 8000.`);
    }
    return handleResponse(res, 'Failed to upload files');
  },

  /**
   * Run the end-to-end analytical query through the orchestrator.
   */
  async analyzeQuestion({ sessionId, question, policyOverrides, plannerType = 'deterministic' }) {
    let res;
    try {
      res = await fetch(`${BASE_URL}/analyze`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          session_id: sessionId,
          question,
          policy_overrides: policyOverrides || null,
          planner_type: plannerType,
        }),
      });
    } catch (netErr) {
      throw new Error(`Cannot connect to backend: ${netErr.message}. Ensure FastAPI is running on port 8000.`);
    }
    return handleResponse(res, 'Analysis execution failed');
  },

  /**
   * Retrieve list of stored proof summaries.
   */
  async getProofs() {
    let res;
    try {
      res = await fetch(`${BASE_URL}/proofs`);
    } catch (netErr) {
      throw new Error(`Cannot connect to backend: ${netErr.message}. Ensure FastAPI is running on port 8000.`);
    }
    return handleResponse(res, 'Failed to fetch stored proofs');
  },

  /**
   * Retrieve a specific ProofCard by proof_id.
   */
  async getProof(proofId) {
    let res;
    try {
      res = await fetch(`${BASE_URL}/proofs/${proofId}`);
    } catch (netErr) {
      throw new Error(`Cannot connect to backend: ${netErr.message}. Ensure FastAPI is running on port 8000.`);
    }
    return handleResponse(res, `Proof '${proofId}' not found`);
  },

  /**
   * Execute independent sandbox replay of a stored proof.
   */
  async replayProof(proofId) {
    let res;
    try {
      res = await fetch(`${BASE_URL}/replay/${proofId}`, {
        method: 'POST',
      });
    } catch (netErr) {
      throw new Error(`Cannot connect to backend: ${netErr.message}. Ensure FastAPI is running on port 8000.`);
    }
    return handleResponse(res, 'Replay execution failed');
  },
};
