# HackNax — ProofLens

### Repair-Aware Proof-Carrying Data Analyst

[![React](https://img.shields.io/badge/frontend-React%2018%20%2B%20Vite%206-61DAFB?logo=react&logoColor=black)](#)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)](#)
[![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi&logoColor=white)](#)
[![Tests](https://img.shields.io/badge/pytest-379%20passed%2C%201%20skipped-brightgreen)](#)
[![License](https://img.shields.io/badge/license-MIT-blue)](#)

> **LLM PROPOSES. CODE COMPUTES. VERIFICATION DECIDES.**
>
> **NO PROOF = NO NUMBER.**

ProofLens is an agentic data-analysis system engineered for messy real-world datasets where numerical answers must be reproducible, independently verified, and backed by cryptographic, executable proof. While conventional AI analysts generate plausible numbers by unconstrained inference or silent heuristic data cleaning, ProofLens treats the LLM strictly as an untrusted proposal engine. Every single metric presented to a decision-maker is computed deterministically, cross-validated via an independent DuckDB SQL engine, stress-tested with metamorphic relations, and certified by an adversarial Truth Gate. If the underlying data is ambiguous or contradictory, ProofLens refuses to guess—it branches across explicit repair policies and proves the mathematical impact of each assumption.

---

## The Problem

Conventional LLM data analysts (and standard "code interpreter" chatbots) are fundamentally unreliable for high-stakes enterprise decisions. When confronted with real-world enterprise tables and documents, they suffer from critical systemic failure modes:

- **Hallucinated Numerical Answers:** LLMs routinely blend computation with generative text, introducing ungrounded calculations or subtly miscounting aggregated figures.
- **Silent Assumptions on Missing Columns:** When requested metrics or foreign keys are absent, models hallucinate proxy calculations without notifying the user.
- **Duplicate Records & Dirty Keys:** Messy datasets contain partial duplicates, multi-system synchronization artifacts, and orphan keys that skew totals without warning.
- **Ambiguous Date & Time Formats:** `01/02/2024` can represent January 2nd or February 1st; conventional tools silently guess a locale without stating the assumption.
- **Missing Values & Skewed Aggregations:** Dropping `NaN` versus imputing zero can dramatically swing enterprise EBITDA or KPI figures.
- **Contradictory Sources & Untracked Overwrites:** When two uploaded tables disagree, AI agents arbitrate unpredictably without mathematical lineage.
- **Unit & Currency Mismatches:** Combining EUR and USD figures or grams and kilograms without conversion leads to catastrophic reporting errors.
- **Confident Answers Without Reproducible Code:** The user receives a polished natural language explanation, but no executable evidence that another engineer can rerun to confirm the result.

This leads to the central question behind ProofLens:

> **Can another person run the computation and independently obtain the exact same answer?**

ProofLens is built from first principles around this question. If an answer cannot be independently proven, reproduced, and verified, **it is never shown as a valid number.**

---

## The Core Idea

ProofLens decouples analysis into four strict, non-negotiable architectural boundaries:

1. **Reasoning (The LLM):**  
   The LLM (Qwen 2.5 / 3.5 via OpenRouter or offline deterministic planner) understands user intent and proposes a structured, typed `AnalysisPlan`. It does **not** compute numbers.
2. **Computation (Deterministic Python):**  
   An isolated, sandboxed Python subprocess executes generated Pandas code directly against the immutable source dataset. All candidate values originate exclusively from standard output and execution dictionaries.
3. **Verification (Independent DuckDB Path):**  
   An independent SQL-based execution path in DuckDB evaluates the exact same question. If Pandas and DuckDB disagree beyond floating-point epsilon (\(\le 10^{-6}\)), verification fails immediately.
4. **Truth (The Truth Gate & Skeptic Agent):**  
   An adversarial Claim-Level Truth Gate scans every sentence of the draft explanation. Every claimed number, percentage, and metric is mapped to verified execution outputs. If an unverified number appears, the entire explanation is rejected.

```text
USER QUESTION
      │
      ▼
 LLM PROPOSES      (Structured AnalysisPlan + Code Proposals)
      │
      ▼
 CODE COMPUTES     (Sandboxed Python / Pandas Execution)
      │
      ▼
 DUCKDB VERIFIES   (Independent Dual-Path SQL Validation)
      │
      ▼
  TRUTH GATE       (Adversarial Claim Filter + AI Skeptic)
      │
      ▼
  PROOF CARD       (Cryptographic Hash, AST, Code & Audit Ledger)
      │
      ▼
 ANSWER / REFUSE   (Verified Metric OR Defensible Structured Refusal)
```

---

## What Is Innovative?

### Repair-Aware Proof-Carrying Analysis

Messy data often yields multiple legitimate analytical interpretations. Conventional analysts make an opaque decision (e.g., dropping duplicates) and output a single answer, hiding massive variance. ProofLens **never silently modifies original data**.

Instead, ProofLens detects data-quality ambiguities during ingestion and branches execution into **Repair Worlds**:

```text
Messy Data
     │
     ▼
Detect Issue (Data Quality Audit)
     │
     ▼
Repair Decision Center
     │
     ├──► Repair World A (Raw / As-Is Baseline)
     ├──► Repair World B (Conservative / Exact Deduplication)
     └──► Repair World C (Imputed / Normalized Policy)
     │
     ▼
Run SAME Analysis Script Across All Worlds
     │
     ▼
Compare Results & Measure Variance
     │
     ▼
Dual-Path Verification (Pandas + DuckDB)
     │
     ▼
VERIFIED (Single Stable Result) OR AMBIGUOUS (Spread & Sensitivity Matrix)
```

#### Why Multi-World Branching Matters:
- **Decision Invariance:** If World A, World B, and World C all yield the exact same answer (e.g., duplicates were in non-aggregated columns), the metric is proven **Invariant to Data Quality**.
- **Impact & Sensitivity Spread:** If World A yields **$18.42M** while World B yields **$17.91M**, ProofLens flags the status as `AMBIGUOUS`, reporting the exact impact delta (\(\Delta = \$510,000\)) and letting stakeholders choose the policy rather than suffering a silent AI error.

---

## 14-Stage End-to-End Pipeline

```text
 1. DATA INGESTION          ──► Preserves raw CSV, XLSX, and JSON sources with SHA-256 hashes
 2. DATA QUALITY AUDIT      ──► Deterministic profiler (duplicates, nulls, date formats, currencies)
 3. PROMPT & SCHEMA DEFENSE ──► Sanitizes inputs; isolates untrusted tabular content in <UNTRUSTED_DATA>
 4. QWEN JSON PLANNER       ──► Emits typed AnalysisPlan with explicit operations, filters, and metrics
 5. UNANSWERABILITY GATE    ──► Early-exit refusal if columns, tables, or metrics are physically missing
 6. REPAIR DECISION CENTER  ──► Synthesizes explicit RepairWorlds with transparent transformation rules
 7. SECURE CODE GENERATOR   ──► Produces dual-path Python (Pandas) and SQL (DuckDB) scripts
 8. SUBPROCESS EXECUTION    ──► Runs in an isolated subprocess with strict AST validation and timeouts
 9. DUAL-PATH VERIFICATION  ──► Compares primary Pandas execution against independent DuckDB computation
10. METAMORPHIC TESTING     ──► Validates relational invariants (row permutations, scale transformations)
11. CROSS-WORLD IMPACT      ──► Measures metric spread across repair worlds; computes sensitivity matrix
12. ADVERSARIAL SKEPTIC     ──► Independent LLM agent reviews plan logic, query sanity, and edge cases
13. CLAIM TRUTH GATE        ──► Regex and AST claim-extractor blocks any ungrounded numerical claims
14. PROOF CARD SYNTHESIS    ──► Emits self-contained, cryptographically signed, reproducible ProofCard JSON
```

---

## Verification Status Hierarchy

Every query terminates in an explicit, mathematically sound status:

| Status | Definition | Result Behavior |
|---|---|---|
| `VERIFIED` | Primary Pandas and DuckDB agree; metamorphic tests pass; zero ungrounded claims. | Numerical answer released with full proof badge. |
| `VERIFIED_WITH_ASSUMPTION` | Computation is verified under an explicit, documented repair policy. | Answer released with highlighted policy assumption. |
| `AMBIGUOUS` | Results diverge across plausible repair policies. | Single number suppressed; full impact range reported. |
| `UNANSWERABLE` | Requested metric or column does not exist in ingested data. | Clean, structured refusal with missing schema lineage. |
| `CONTRADICTED` | Primary and secondary sources directly contradict one another. | Discrepancy report detailing conflicting rows/tables. |
| `NOT_VERIFIED` | Dual-path mismatch or failed assertion during code execution. | Numeric display strictly blocked by Truth Gate. |

---

## Cryptographic Proof Cards

Every analysis generates a verifiable, self-contained **Proof Card** (`proof_<id>.json`). A Proof Card contains everything an external auditor needs to reproduce the result from scratch:

```json
{
  "proof_id": "prf_8f91c7a2b9",
  "status": "VERIFIED",
  "timestamp": "2026-10-07T12:00:00Z",
  "dataset_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "question": "What is total revenue across all completed orders?",
  "result": 18420000.00,
  "unit": "USD",
  "repair_policy": "EXACT_DEDUPLICATION",
  "verification": {
    "pandas_status": "PASS",
    "duckdb_status": "PASS",
    "metamorphic_status": "PASS",
    "epsilon_difference": 0.0
  },
  "waterfall": {
    "raw_rows": 10000,
    "deduplicated_rows": 9880,
    "filtered_rows": 6988
  },
  "reproducibility": {
    "command": "python scripts/replay.py proofs/prf_8f91c7a2b9.json",
    "execution_time_ms": 142
  }
}
```

---

## Full-Stack Architecture

ProofLens is packaged as a complete, professional product with modern decoupled architecture:

```
ProofLens/
├── app/
│   ├── api/                     # FastAPI REST API & Contracts
│   │   ├── server.py            # API endpoints: upload, analyze, proofs, replay, samples
│   │   └── contracts.py         # Pydantic v2 request/response schemas
│   ├── ingestion/               # Multi-format CSV/XLSX/JSON loaders & schema discovery
│   ├── audit/                   # Deterministic data-quality ledger & issue detector
│   ├── agent/                   # OpenRouter Qwen 2.5/3.5 planner, skeptic, prompt guard
│   ├── execution/               # Sandboxed subprocess execution & AST safety validator
│   ├── verification/            # DuckDB dual-path, metamorphic engine, Truth Gate
│   ├── repair/                  # Multi-world repair policies & sensitivity calculator
│   └── proof/                   # Proof card generation, serialization & signature
│
├── frontend/                    # Modern React 18 + Vite 6 Web Application
│   ├── src/
│   │   ├── api/prooflensApi.js  # Resilient REST client with error shielding
│   │   ├── components/          # Polished enterprise UI components
│   │   │   ├── Navbar.jsx       # Branding, backend status & system pill
│   │   │   ├── AnalysisHero.jsx # Question bar & sample dataset quick-switch
│   │   │   ├── DataHealth.jsx   # Data Quality Ledger with severity badges
│   │   │   ├── RepairDecisionCenter.jsx # Interactive multi-world policy manager
│   │   │   ├── Pipeline.jsx     # Live 14-stage verification visualizer
│   │   │   ├── ResultCard.jsx   # Verified answer display with waterfall metrics
│   │   │   ├── RefusalCard.jsx  # Structured refusal for unanswerable questions
│   │   │   ├── ProofCard.jsx    # Complete cryptographic proof inspector
│   │   │   ├── CodeViewer.jsx   # Dual-tab Python (Pandas) & SQL (DuckDB) viewer
│   │   │   └── ReplayModal.jsx  # One-click isolated sandbox reproduction modal
│   │   └── pages/Workspace.jsx  # Main analytical workbench
│   └── vite.config.js           # Reverse-proxy to FastAPI backend (:8000)
│
├── run.py                       # Concurrent single-command launcher (FastAPI + Vite)
├── scripts/
│   ├── proof.py                 # CLI end-to-end runner, inspector, and verifier
│   ├── verify.py                # Standalone cryptographic verification script
│   └── replay.py                # Standalone air-gapped proof replay runner
└── tests/                       # Comprehensive pytest suite (380 tests)
```

---

## Quickstart & Launch Guide

### 1. Prerequisites
- **Python 3.11+** installed
- **Node.js 18+** & **npm** installed
- Windows, macOS, or Linux

### 2. Setup Virtual Environment
```powershell
# Clone the repository
git clone https://github.com/Rishva-J-404/Hacknax.git
cd Hacknax

# Create and activate Python virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # On Windows
# source .venv/bin/activate    # On Linux / macOS

# Install backend dependencies
pip install -r requirements.txt
```

### 3. Install Frontend Dependencies
```powershell
cd frontend
npm install
cd ..
```

### 4. Configuration (Optional)
Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```
*(ProofLens includes a built-in deterministic offline planner. An `OPENROUTER_API_KEY` is only needed if you want live cloud LLM reasoning with Qwen).*

```env
OPENROUTER_API_KEY=your_key_here
QWEN_MODEL=qwen/qwen-2.5-72b-instruct
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

### 5. Launch the Full Product (One Command)
Run the concurrent launcher to start both the FastAPI backend and the Vite frontend simultaneously:

```powershell
python run.py
```

- **Frontend Interface:** [http://localhost:5173](http://localhost:5173)
- **FastAPI API & Docs:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## Standalone CLI & Offline Replay

ProofLens is fully operable from the terminal for headless pipelines, automated CI, and independent auditing:

### 1. Run Analysis via CLI
```powershell
python scripts/proof.py run --question "What is the total revenue for 2024?" --sources data/sample_clean_orders.csv
```

### 2. Verify an Existing Proof Card
```powershell
python scripts/verify.py proofs/prf_latest.json
```
```text
====================================
PROOFLENS INDEPENDENT VERIFICATION
====================================
Dataset SHA-256 ............. PASS
Sandboxed Execution ......... PASS
Pandas Computation .......... PASS
DuckDB Verification ......... PASS
Metamorphic Invariants ...... PASS
Claim Grounding ............. PASS

Expected:  18420000.0
Computed:  18420000.0
Delta:     0.0

FINAL VERDICT: VERIFIED
====================================
```

### 3. Replay in Isolated Sandbox
Reproduce the exact execution output in an isolated sandbox environment:
```powershell
python scripts/replay.py proofs/prf_latest.json
```

---

## Verification & Test Suite

ProofLens features an exhaustive, production-grade test suite covering API contracts, ingestion parsers, audit heuristics, AST security sandboxing, metamorphic invariants, and truth-gate blockers:

```powershell
pytest -q
```

```text
........................................................................ [ 18%]
........................................................................ [ 37%]
........................................................................ [ 56%]
........................................................................ [ 75%]
........................................................................ [ 94%]
.....................s                                                   [100%]
379 passed, 1 skipped in 16.42s
```

*(The single skipped test is the live cloud OpenRouter smoke test, which gracefully skips when no API key is set in the environment).*

---

## Security & Defense in Depth

- **Sandboxed Subprocess Runner:** Generated code runs in an isolated subprocess with strict AST validation, memory limits, and timeouts. Imports of `os`, `sys`, `subprocess`, `socket`, and `eval` are blocked at parse time.
- **Untrusted Prompt Containment:** Raw tabular data and column names are tagged with `<UNTRUSTED_DATA>` delimiters and prompt-injection defense layers.
- **No Direct Numbers from LLMs:** Final outputs are strictly populated from execution return dictionaries—the LLM's text stream cannot write numbers to the output payload.
- **Strict Anti-Hallucination Gate:** An adversarial regex and AST claim matcher flags and blocks any numerical token in an explanation that does not trace back to verified outputs.
- **Zero Silent Data Mutation:** Ingested source files are strictly immutable; repair transformations exist solely inside policy-isolated runtime worlds.

---

## HackNax 2026 Submission

- **Track:** HNX26PSI08 — Proof-Carrying Data Analyst (Agentic GenAI)
- **Repository:** [https://github.com/Rishva-J-404/Hacknax.git](https://github.com/Rishva-J-404/Hacknax.git)
- **Architecture Core:** Decoupled Agentic Reasoning, Sandboxed Computation, Dual-Path DuckDB Verification, Multi-World Impact Analysis, and Cryptographic Proof Cards.
- **Product Law:** **LLM Proposes. Code Computes. Verification Decides. No Proof = No Number.**
