# Hacknax — ProofLens: Repair-Aware Proof-Carrying Data Analyst

[![Tests](https://img.shields.io/badge/pytest-379%20passing-brightgreen)](#)
[![React](https://img.shields.io/badge/frontend-React%20%2B%20Vite-blue)](#)
[![Python](https://img.shields.io/badge/python-3.11+-blue)](#)
[![License](https://img.shields.io/badge/license-MIT-green)](#)

> **Core Architectural Law:**
> ```text
> LLM PROPOSES.
> CODE COMPUTES.
> VERIFICATION DECIDES.
> 
> NO PROOF = NO NUMBER.
> ```

---

## Overview

**ProofLens** is an agentic, proof-carrying data analysis engine designed for messy, real-world data across multiple tables and documents.

Conventional LLM data analysts hallucinate aggregations, invent values when columns are missing, and guess when data is ambiguous. ProofLens inverts this model:

1. **Untrusted LLM proposals:** The LLM (Qwen via OpenRouter or deterministic planner) is treated strictly as an untrusted proposal engine. It proposes a structured `AnalysisPlan` and drafts human-readable explanations.
2. **Deterministic execution:** All numbers come strictly from sandboxed Python execution against controlled datasets.
3. **Dual-path independent verification:** The primary Pandas execution is independently validated against a secondary DuckDB SQL computation.
4. **Repair-aware multi-world branching:** When data quality issues (such as duplicate rows, conflicting dates, or missing values) introduce ambiguity, ProofLens constructs explicit **RepairWorlds** and runs cross-world impact analysis. If different worlds produce conflicting results, ProofLens declares `AMBIGUOUS` with the full spread rather than guessing.
5. **Strict Truth Gate:** Natural language answers pass through an adversarial Claim-Level Truth Gate and AI Skeptic Agent before publication. Any unsupported or hallucinatory number causes immediate blocking.
6. **Self-contained Proof Cards:** Every verified answer is serialized into a verifiable `ProofCard` containing the exact question, hashes, generated code, dual-path checks, and replay commands.

---

## Pipeline Architecture

```text
USER QUESTION
      │
      ▼
 1. INGESTION                ← Preserves raw source data (CSV / XLSX / JSON)
      │
      ▼
 2. DATA QUALITY AUDIT       ← Deterministic table profiler & issue detector
      │
      ▼
 3. QWEN / JSON PLANNER      ← Proposes structured AnalysisPlan
      │
      ▼
 4. SCHEMA & PROMPT DEFENSE  ← Authoritative PlanValidator & untrusted boundary
      │
      ▼
 5. UNANSWERABILITY GATE     ← Early refusal if columns/tables missing
      │
      ▼
 6. REPAIR DECISION CENTER   ← Explicit, defensible RepairWorlds
      │
      ▼
 7. CODE GENERATOR           ← Deterministic Python analysis script
      │
      ▼
 8. SANDBOXED EXECUTION      ← Subprocess runner across repair worlds
      │
      ▼
 9. DUAL-PATH VERIFICATION   ← Independent DuckDB validation
      │
      ▼
10. METAMORPHIC TESTS        ← Invariant validation under data transformations
      │
      ▼
11. CROSS-WORLD IMPACT       ← Value & decision stability across worlds
      │
      ▼
12. CLAIM TRUTH GATE         ← Claim extraction, Skeptic review, anti-hallucination
      │
      ▼
13. ANSWER DRAFTING          ← Strictly gated natural language answer
      │
      ▼
14. PROOF CARD SYNTHESIS     ← Cryptographically hashed, replayable artifact
```

---

## Installation & Setup

### Prerequisites
- Python 3.11+
- Virtual environment recommended

### Setup Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Configuration
Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```
Configure your OpenRouter API key (optional for offline deterministic mode):
```env
OPENROUTER_API_KEY=your_key_here
QWEN_MODEL=qwen/qwen-2.5-72b-instruct
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

---

## CLI Usage

### 1. Run End-to-End Analysis
Execute a question against one or more data files:
```powershell
python scripts/proof.py run --question "Total order amount" --sources data/orders.csv --output-dir proofs
```

With OpenRouter Qwen planner:
```powershell
python scripts/proof.py run --question "Total revenue in 2024" --sources data/orders.csv --model qwen/qwen-2.5-72b-instruct
```

### 2. Inspect a Generated Proof Card
```powershell
python scripts/proof.py inspect proofs/proof_<id>.json
```

### 3. Verify a Proof Card
Validate hashes, re-run generated code, and verify claims:
```powershell
python scripts/proof.py verify proofs/proof_<id>.json
```

### 4. Replay Proofs
Safely reproduce a result in an isolated sandbox:
```powershell
python scripts/replay.py proofs/proof_<id>.json
```

---

## Running the Test Suite

The test suite runs 100% offline without requiring external network access or OpenRouter credentials:

```powershell
pytest -q
```

Expected output:
```text
370 passed, 1 skipped in ~17s
```

*(The 1 skipped test is the live OpenRouter smoke test, which automatically skips when `OPENROUTER_API_KEY` is unset).*

---

## Security & Guardrails

- **Subprocess Isolation:** Generated code runs in an isolated worker process with strict timeouts, no shell access, and forbidden imports.
- **Untrusted Prompt Isolation:** Source data and column values are enclosed in `<UNTRUSTED_DATA>` XML tags and neutralized to prevent prompt injection.
- **Strict Anti-Hallucination Gate:** An LLM explanation can never introduce a number that is not backed by verifiable code execution output.
- **API Key Protection:** API keys are never logged, stored in proof cards, or exposed in error messages.
"# Hacknax" 
