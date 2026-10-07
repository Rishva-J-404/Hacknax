"""
app.truth.claim_extractor
-------------------------
Deterministic Claim Extractor for ProofLens.

CORE PRINCIPLE (PROOFLENS_MASTER_CONTEXT.md §18, §19):
    Every factual claim made in a draft answer must be explicitly
    identified and extracted as a structured Claim.
    Every numerical statement MUST become a separate Claim.

Operates deterministically without an LLM.
"""

from __future__ import annotations

import re
from typing import Any

from app.agent.contracts import AnalysisPlan
from app.truth.contracts import Claim, ClaimType, TruthStatus
from app.verification.contracts import VerificationResult


# ---------------------------------------------------------------------------
# Scale Multipliers & Currency Tokens
# ---------------------------------------------------------------------------

_SCALE_MULTIPLIERS: dict[str, float] = {
    "cr": 10_000_000.0,
    "crore": 10_000_000.0,
    "crores": 10_000_000.0,
    "lakh": 100_000.0,
    "lakhs": 100_000.0,
    "lac": 100_000.0,
    "lacs": 100_000.0,
    "million": 1_000_000.0,
    "mn": 1_000_000.0,
    "billion": 1_000_000_000.0,
    "bn": 1_000_000_000.0,
    "thousand": 1_000.0,
    "k": 1_000.0,
}

_CURRENCY_SYMBOLS: dict[str, str] = {
    "₹": "INR",
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
}


def normalize_numeric_string(raw: str) -> tuple[float | None, str | None, float | None]:
    """
    Parse a numeric string into (raw_number, unit, canonical_scaled_number).
    Examples:
      '₹18.42 Cr' -> (18.42, 'INR', 184200000.0)
      '14%'       -> (14.0, '%', 14.0)
      '1,000.50'  -> (1000.5, None, 1000.5)
    """
    text = raw.strip()
    unit = None

    # Currency symbol
    for sym, curr in _CURRENCY_SYMBOLS.items():
        if sym in text:
            unit = curr
            text = text.replace(sym, "")
            break

    # Percentage
    if "%" in text:
        unit = "%"
        text = text.replace("%", "")

    # Scale word
    scale_factor = 1.0
    for scale_word, factor in _SCALE_MULTIPLIERS.items():
        pattern = rf"\b{scale_word}\b"
        if re.search(pattern, text, flags=re.IGNORECASE):
            scale_factor = factor
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)
            break

    # Clean commas, whitespace
    cleaned = text.replace(",", "").strip()

    # Extract first float/int token
    match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", cleaned)
    if not match:
        return None, unit, None

    try:
        val = float(match.group(0))
        normalized = round(val * scale_factor, 6)
        return val, unit, normalized
    except ValueError:
        return None, unit, None


# ---------------------------------------------------------------------------
# Deterministic Claim Extractor
# ---------------------------------------------------------------------------

class ClaimExtractor:
    """
    Deterministic extractor of factual and numerical assertions from text.
    """

    def extract_claims(
        self,
        text: str,
        plan: AnalysisPlan | None = None,
        verification_result: VerificationResult | None = None,
    ) -> list[Claim]:
        """
        Parse text into discrete, verifiable Claim objects.
        """
        if not text or not text.strip():
            return []

        claims: list[Claim] = []
        sentences = re.split(r"(?<=[.!?])\s+|\n+", text.strip())

        for raw_sentence in sentences:
            sentence = raw_sentence.strip()
            if not sentence:
                continue

            # Detect dates, periods, and 4-digit years (e.g. 01/02/2024, 2024-01-02, 2024, 2025)
            date_pattern = re.compile(
                r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b|\b(?:19|20)\d{2}\b"
            )
            date_matches = list(date_pattern.finditer(sentence))
            relevant_period = date_matches[0].group(0) if date_matches else None

            # Detect subject entity
            subject = None
            for subj in ["revenue", "sales", "profit", "amount", "orders", "growth", "margin", "count", "items", "transactions"]:
                if subj in sentence.lower():
                    subject = subj
                    break

            # Check if this sentence is primarily a comparison statement
            lower_s = sentence.lower()
            is_comparison_statement = any(
                w in lower_s for w in ["increase", "decrease", "grew", "growth", "higher", "lower", "highest", "lowest", "more than", "less than"]
            )

            # Mask date tokens out of the sentence to avoid extracting date subparts (e.g. 01, 02 in 01/02/2024 or 2024) as financial numbers
            masked_sentence = date_pattern.sub(" __DATE__ ", sentence)

            # Find all numerical candidates in the masked sentence
            num_pattern = re.compile(
                r"(?:[₹\$€£]\s*)?[-+]?\d[\d,]*(?:\.\d+)?\s*(?:%|cr|crore|crores|lakh|lakhs|million|billion|k)?",
                re.IGNORECASE,
            )
            matches = list(num_pattern.finditer(masked_sentence))
            valid_num_matches = [m.group(0).strip() for m in matches if any(c.isdigit() for c in m.group(0))]

            if valid_num_matches:
                for chunk in valid_num_matches:
                    val, unit, scaled = normalize_numeric_string(chunk)
                    if val is None:
                        continue

                    if unit == "%" or "percent" in sentence.lower():
                        claim_type = ClaimType.PERCENTAGE
                        unit = "%"
                    elif any(w in sentence.lower() for w in ["count", "total orders", "number of", "transactions"]):
                        claim_type = ClaimType.COUNT
                    else:
                        claim_type = ClaimType.NUMERICAL_VALUE

                    claim = Claim(
                        claim_text=sentence,
                        claim_type=claim_type,
                        numerical_value=val,
                        unit=unit,
                        evidence_refs=[],
                        supported=False,
                        subject=subject,
                        relevant_period=relevant_period,
                        status=TruthStatus.NOT_VERIFIED,
                        normalized_value=scaled,
                    )
                    claims.append(claim)

            else:
                # Non-numerical assertion: comparison, date reference, or factual statement
                if is_comparison_statement:
                    claim_type = ClaimType.COMPARISON
                elif relevant_period and any(w in lower_s for w in ["in ", "during ", "for the year "]):
                    claim_type = ClaimType.DATE
                else:
                    claim_type = ClaimType.FACTUAL_STATEMENT

                claim = Claim(
                    claim_text=sentence,
                    claim_type=claim_type,
                    numerical_value=None,
                    unit=None,
                    evidence_refs=[],
                    supported=False,
                    subject=subject,
                    relevant_period=relevant_period,
                    status=TruthStatus.NOT_VERIFIED,
                )
                claims.append(claim)

        return claims


def extract_claims(
    text: str,
    plan: AnalysisPlan | None = None,
    verification_result: VerificationResult | None = None,
) -> list[Claim]:
    """Convenience functional wrapper for claim extraction."""
    extractor = ClaimExtractor()
    return extractor.extract_claims(text, plan=plan, verification_result=verification_result)
