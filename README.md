# HackNax — ProofLens

### Repair-Aware Proof-Carrying Data Analyst

[![React](https://img.shields.io/badge/Frontend-React%20%2B%20Vite-61DAFB?logo=react&logoColor=black)](#)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](#)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white)](#)
[![DuckDB](https://img.shields.io/badge/Verification-DuckDB-FFF000)](#)
[![Tests](https://img.shields.io/badge/Tests-400%20Passed-brightgreen)](#)

> **LLM PROPOSES. CODE COMPUTES. VERIFICATION DECIDES.**
>
> **NO PROOF = NO NUMBER.**

ProofLens is an **agentic data-analysis system for messy real-world datasets** where numerical answers must be **computed, independently verified, reproducible, and supported by executable proof**.

Instead of allowing an LLM to directly produce numerical answers, ProofLens separates:

```text
AI REASONING
      ↓
DETERMINISTIC COMPUTATION
      ↓
INDEPENDENT VERIFICATION
      ↓
PROOF
      ↓
ANSWER / REFUSE
```

---

## Problem

AI data-analysis systems can produce confident answers even when data contains:

- Duplicate records
- Missing values
- Ambiguous dates
- Contradictory values
- Unit or currency mismatches
- Missing columns
- Incorrect assumptions
- Unsupported numerical claims

The dangerous failure is:

> **A wrong number presented with confidence.**

ProofLens addresses this by requiring evidence before releasing a numerical answer.

---

## Innovation

### Repair-Aware Proof-Carrying Analysis

ProofLens combines:

```text
DATA QUALITY AUDIT
        +
EXPLICIT REPAIR POLICIES
        +
REPAIR WORLDS
        +
DETERMINISTIC COMPUTATION
        +
INDEPENDENT VERIFICATION
        +
METAMORPHIC TESTING
        +
CLAIM-LEVEL TRUTH CHECKING
        +
REPRODUCIBLE PROOF
```

Instead of silently cleaning data, ProofLens creates explicit **Repair Worlds**.

Example:

```text
Messy Dataset
      ↓
Data Audit
      ↓
Repair Decision Center
      ↓
 ┌───────────────┬────────────────┬──────────────────┐
 │ World A       │ World B        │ World C          │
 │ Keep Duplicates│ Exact Dedup    │ Alternative Rule │
 └───────────────┴────────────────┴──────────────────┘
      ↓
Same Analysis
      ↓
Compare Results
      ↓
Determine Impact
```

The original dataset is never silently modified.

---

## System Architecture

```text
                    USER QUESTION
                          ↓
                    DATA INGESTION
                          ↓
                     DATA AUDIT
                          ↓
                 ANSWERABILITY CHECK
                          ↓
                    QWEN / AI PLAN
                          ↓
                REPAIR DECISION CENTER
                          ↓
                   REPAIR WORLDS
                          ↓
                SECURE CODE GENERATOR
                          ↓
                 SANDBOXED EXECUTION
                          ↓
                  PANDAS COMPUTATION
                          ↓
             INDEPENDENT DUCKDB VERIFY
                          ↓
                METAMORPHIC TESTING
                          ↓
               CROSS-WORLD COMPARISON
                          ↓
                   SKEPTIC REVIEW
                          ↓
                     TRUTH GATE
                          ↓
                     PROOF CARD
                          ↓
                  ┌───────┴───────┐
                  ↓               ↓
                PROVEN        NOT PROVEN
                  ↓               ↓
               ANSWER           REFUSE
```

---

## Core Pipeline

| Stage | Purpose |
| **Ingestion** | Load CSV, JSON and XLSX data |
| **Audit** | Detect duplicates, missing values, ambiguous dates, units and contradictions |
| **Planning** | Convert natural-language questions into structured analysis plans |
| **Repair** | Define explicit data-quality policies |
| **World Generation** | Create alternative valid data interpretations |
| **Computation** | Execute deterministic analysis code |
| **Verification** | Independently verify results using DuckDB |
| **Metamorphic Testing** | Test mathematical and structural properties |
| **Impact Analysis** | Compare results across repair worlds |
| **Skeptic** | Detect unsupported or suspicious reasoning |
| **Truth Gate** | Match claims against verified evidence |
| **Proof Card** | Store reproducible evidence |
| **Decision** | Answer only when sufficiently proven |

---

## Verification

### Deterministic Computation

The numerical result is calculated using executable Python/Pandas code.

### Independent Verification

The result is independently checked using DuckDB.

```text
PANDAS RESULT
      ↓
      ├──────────────┐
      ↓              ↓
PRIMARY PATH     DUCKDB PATH
      ↓              ↓
      └───────┬──────┘
              ↓
        RESULT COMPARE
              ↓
         PASS / FAIL
```

A mismatch prevents the result from being treated as verified.

### Metamorphic Testing

ProofLens tests controlled transformations including:

- Row-order invariance
- Duplicate injection
- Add-zero behavior
- Ratio duplication
- Filter monotonicity
- Grouped-total consistency
- TOP-N consistency

---

## Verification Status

| Status | Meaning |
|---|---|
| `VERIFIED` | Result passed required verification |
| `VERIFIED_WITH_ASSUMPTION` | Result is valid under an explicit assumption |
| `AMBIGUOUS` | Multiple valid interpretations produce different results |
| `CONTRADICTED` | Relevant evidence contains conflicting values |
| `NOT_VERIFIED` | Verification failed or evidence is insufficient |
| `UNANSWERABLE` | Required information is unavailable |

### Fail-Closed Principle

```text
NO EVIDENCE
    ↓
NO PROOF
    ↓
NO NUMBER
```

---

## Proof Cards

Every completed analysis can produce a **Proof Card** containing:

- Question
- Verification status
- Dataset hash
- Analysis plan
- Repair policy
- Assumptions
- Generated code
- Execution result
- Independent verification
- Metamorphic checks
- Claim evidence
- Lineage
- Replay information
- Cryptographic hashes

Example:

```text
┌──────────────────────────────────────┐
│          PROOFLENS PROOF CARD        │
├──────────────────────────────────────┤
│ Metric: Total Revenue                │
│ Status: VERIFIED                     │
│ Policy: Exact Deduplication          │
│                                      │
│ ✓ Deterministic Computation          │
│ ✓ DuckDB Verification                │
│ ✓ Metamorphic Checks                 │
│ ✓ Claim Evidence                     │
│ ✓ Dataset Hash                       │
│ ✓ Replay Information                 │
└──────────────────────────────────────┘
```

---

## Claim-Level Truth Gate

Correct computation alone is not enough.

An AI-generated explanation can still contain unsupported numbers.

ProofLens therefore:

```text
GENERATED EXPLANATION
        ↓
CLAIM EXTRACTION
        ↓
EVIDENCE MATCHING
        ↓
TRUTH GATE
        ↓
SUPPORTED / BLOCKED
```

If a numerical claim does not match verified evidence, the answer is blocked.

---

## Repair-Aware Analysis

ProofLens explicitly handles:

### Duplicate Records

```text
Duplicate Detected
       ↓
Repair Worlds
       ↓
Keep / Deduplicate / Compare
       ↓
Run Same Analysis
       ↓
Compare Impact
```

### Ambiguous Dates

Example:

```text
02/03/2025
```

Possible interpretations are evaluated explicitly rather than silently selecting one.

### Missing Data

If required information is unavailable:

```text
UNANSWERABLE
```

### Contradictory Data

If sources contain conflicting values:

```text
CONTRADICTED
```

### Verification Failure

If independent verification disagrees:

```text
NOT_VERIFIED
```

---

## Security & Defense in Depth

- **Sandboxed Subprocess Execution:** Generated code runs inside a controlled subprocess with strict AST validation, restricted built-ins, execution timeouts, isolated environment variables, and bounded output. Dangerous operations are rejected before execution.

- **Prompt Injection Defense:** Uploaded datasets and documents are treated as untrusted data. Data content and column names cannot directly become system-level instructions.

- **No Direct Numbers from the LLM:** The LLM proposes structured analysis plans and explanations. Numerical results are produced by deterministic execution and verified result objects.

- **Independent Verification:** Primary Pandas calculations are independently checked through DuckDB. Failed comparisons are marked `NOT_VERIFIED`.

- **Strict Truth Gate:** Numerical and important factual claims are matched against verified evidence. Unsupported or contradictory claims are blocked.

- **Deterministic Verification:** Stable execution, dataset hashes, code hashes, and reproducible verification paths make results auditable.

- **Metamorphic Validation:** Controlled transformations test whether calculations behave according to expected mathematical properties.

- **Zero Silent Data Mutation:** Original datasets remain unchanged. All repairs exist only inside explicit Repair Worlds.

- **Fail-Closed Answering:** If the result cannot be proven, ProofLens refuses the answer instead of guessing.

---

## Supported Data

Currently supported:

```text
CSV
JSON
XLSX
```

Data-quality checks include:

```text
Duplicates
Missing Values
Ambiguous Dates
Mixed Types
Currency Issues
Unit Issues
Contradictions
Schema Problems
```

---

## Technology Stack

| Component | Technology |
|---|---|
| Frontend | React + Vite |
| Backend | Python + FastAPI |
| Data Processing | Pandas |
| Independent Verification | DuckDB |
| Validation | Pydantic |
| AI Planner | Qwen / OpenRouter |
| Testing | pytest |
| Code Safety | AST Validation + Sandbox |
| Proof | JSON + SHA-256 |

---

## Project Structure

```text
ProofLens/
│
├── app/
│   ├── agent/
│   ├── api/
│   ├── audit/
│   ├── execution/
│   ├── ingestion/
│   ├── proof/
│   ├── repair/
│   ├── skeptic/
│   ├── truth/
│   └── verification/
│
├── frontend/
│   ├── src/
│   └── vite.config.js
│
├── data/
├── proofs/
├── scripts/
├── tests/
│
├── requirements.txt
├── run.py
├── run.bat
├── run.ps1
└── README.md
```

---

## Quick Start

### Clone

```bash
git clone https://github.com/Rishva-J-404/Hacknax.git
cd Hacknax
```

### Create Python Environment

```bash
python -m venv .venv
```

Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
source .venv/bin/activate
```

### Install Backend

```bash
pip install -r requirements.txt
```

### Install Frontend

```bash
cd frontend
npm install
cd ..
```

### Run

```bash
python run.py
```

---

## Demo Scenarios

### Clean Data

```text
Question:
What is the total order amount?

Expected:
VERIFIED
```

### Duplicate Data

```text
Question:
What is the total revenue?

Expected:
Repair World Comparison
```

### Ambiguous Date

```text
Data:
02/03/2025

Expected:
AMBIGUOUS
```

### Missing Column

```text
Question:
What is the profit?

Dataset:
No profit column

Expected:
UNANSWERABLE
```

### Contradictory Data

```text
Expected:
CONTRADICTED
```

### Verification Mismatch

```text
Pandas ≠ DuckDB

Expected:
NOT_VERIFIED
```

### Unsupported AI Claim

```text
Claim:
A number not present in verified evidence

Expected:
TRUTH GATE → BLOCKED
```

---

## Testing

Run:

```bash
pytest -q
```

Current validation:

```text
400 passed
1 skipped
1 warning
```

The main test suite does not depend on live cloud API availability.

---

## Why ProofLens?

Traditional AI analysis focuses on:

```text
QUESTION → ANSWER
```

ProofLens focuses on:

```text
QUESTION
   ↓
AUDIT
   ↓
PLAN
   ↓
REPAIR
   ↓
COMPUTE
   ↓
VERIFY
   ↓
PROVE
   ↓
ANSWER / REFUSE
```

The project is built around one principle:

> **An AI-generated number is not trustworthy just because it sounds correct.**

A trustworthy result should be:

- Computed
- Verified
- Traceable
- Reproducible
- Explainable
- Supported by evidence

When that cannot be established:

> **ProofLens refuses to guess.**

---

## Project Status

- [x] React + Vite frontend
- [x] FastAPI backend
- [x] CSV / JSON / XLSX ingestion
- [x] Data-quality audit
- [x] Repair Decision Center
- [x] Repair Worlds
- [x] Secure code generation
- [x] Sandboxed execution
- [x] Pandas computation
- [x] DuckDB verification
- [x] Metamorphic testing
- [x] Skeptic review
- [x] Truth Gate
- [x] Proof Cards
- [x] Replay support
- [x] Automated testing

---

## License

MIT License
