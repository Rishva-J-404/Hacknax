# =============================================================================
# ProofLens Generated Analysis Script
# Question: Total order amount
# Intent: SUM_AMOUNT
# Rule: LLM PROPOSES. CODE COMPUTES. VERIFICATION DECIDES.
# =============================================================================

import pandas as pd

# ── 1. Load Data ──────────────────────────────────────────────────────────
# Expects 'tables' dictionary of DataFrames or Loads from current environment
df = tables['messy'].copy()

# ── 2. Schema Assertions ──────────────────────────────────────────────────
assert len(df) > 0, 'Input dataset must not be empty'
assert 'amount' in df.columns, 'Required column "amount" is missing from table "messy"'

# ── 5. Deterministic Computation ──────────────────────────────────────────
numeric_series = pd.to_numeric(df['amount'], errors='coerce').dropna()
result = float(numeric_series.sum())

# ── 6. Emit Authoritative Result ─────────────────────────────────────────
RESULT = result
print(result)
