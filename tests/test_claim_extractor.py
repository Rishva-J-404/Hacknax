"""
tests.test_claim_extractor
--------------------------
Comprehensive unit test suite for deterministic ClaimExtractor.
"""

from __future__ import annotations

import pytest

from app.truth.claim_extractor import ClaimExtractor, extract_claims, normalize_numeric_string
from app.truth.contracts import ClaimType


@pytest.fixture
def extractor() -> ClaimExtractor:
    return ClaimExtractor()


def test_extract_basic_number(extractor: ClaimExtractor):
    text = "Total revenue was 1000.0."
    claims = extractor.extract_claims(text)
    assert len(claims) == 1
    assert claims[0].numerical_value == 1000.0
    assert claims[0].claim_type == ClaimType.NUMERICAL_VALUE


def test_extract_currency_and_crore_scale(extractor: ClaimExtractor):
    text = "Total revenue was ₹18.42 Cr."
    claims = extractor.extract_claims(text)
    assert len(claims) == 1
    c = claims[0]
    assert c.numerical_value == 18.42
    assert c.unit == "INR"
    assert c.normalized_value == 184200000.0
    assert c.claim_type == ClaimType.NUMERICAL_VALUE


def test_extract_percentage(extractor: ClaimExtractor):
    text = "Revenue grew by 14%."
    claims = extractor.extract_claims(text)
    assert len(claims) == 1
    c = claims[0]
    assert c.claim_type == ClaimType.PERCENTAGE
    assert c.numerical_value == 14.0
    assert c.unit == "%"


def test_extract_count(extractor: ClaimExtractor):
    text = "Total count of orders was 42."
    claims = extractor.extract_claims(text)
    assert len(claims) == 1
    c = claims[0]
    assert c.claim_type == ClaimType.COUNT
    assert c.numerical_value == 42.0


def test_extract_multiple_claims_in_paragraph(extractor: ClaimExtractor):
    text = "Total sales reached ₹10.5 Cr in 2024. Total orders count was 500. Return rate was 5%."
    claims = extractor.extract_claims(text)
    assert len(claims) == 3

    assert claims[0].numerical_value == 10.5
    assert claims[0].unit == "INR"
    assert claims[0].relevant_period == "2024"

    assert claims[1].numerical_value == 500.0
    assert claims[1].claim_type == ClaimType.COUNT

    assert claims[2].numerical_value == 5.0
    assert claims[2].claim_type == ClaimType.PERCENTAGE


def test_extract_dollar_currency(extractor: ClaimExtractor):
    text = "The product price was $250.50."
    claims = extractor.extract_claims(text)
    assert len(claims) == 1
    assert claims[0].unit == "USD"
    assert claims[0].numerical_value == 250.5


def test_extract_lakh_scale(extractor: ClaimExtractor):
    text = "Revenue in region was 50 lakh."
    claims = extractor.extract_claims(text)
    assert len(claims) == 1
    assert claims[0].normalized_value == 5_000_000.0


def test_extract_comparison_claim(extractor: ClaimExtractor):
    text = "Revenue was significantly higher in 2025 than 2024."
    claims = extractor.extract_claims(text)
    assert len(claims) == 1
    assert claims[0].claim_type == ClaimType.COMPARISON
    assert claims[0].numerical_value is None


def test_extract_date_period_detection(extractor: ClaimExtractor):
    text = "In the year 2025, total revenue was 900."
    claims = extractor.extract_claims(text)
    assert len(claims) == 1
    assert claims[0].relevant_period == "2025"
    assert claims[0].numerical_value == 900.0


def test_extract_empty_or_whitespace(extractor: ClaimExtractor):
    assert extractor.extract_claims("") == []
    assert extractor.extract_claims("   \n\t  ") == []


def test_normalize_numeric_string_helper():
    val, unit, scaled = normalize_numeric_string("₹1,000.50")
    assert val == 1000.5
    assert unit == "INR"
    assert scaled == 1000.5

    val, unit, scaled = normalize_numeric_string("2.5 million")
    assert val == 2.5
    assert scaled == 2_500_000.0


def test_convenience_extract_claims():
    claims = extract_claims("Order count is 10.")
    assert len(claims) == 1
    assert claims[0].numerical_value == 10.0
