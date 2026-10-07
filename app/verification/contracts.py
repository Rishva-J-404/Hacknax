"""
app.verification.contracts
--------------------------
Data structures produced by the independent verification module.

Responsibility:
  Record the result of running two independent computation paths
  (Pandas primary, DuckDB secondary) and comparing them.

Design rules (PROOFLENS_MASTER_CONTEXT.md §12, §13, §14, §15, §16):
  - Verification status is ALWAYS set deterministically by this module.
  - The LLM CANNOT set VerificationStatus to VERIFIED.
  - If the two paths disagree → NOT_VERIFIED, regardless of LLM opinion.
  - Metamorphic, premise, and ambiguity checks are also recorded here.

Core principle:
  VERIFICATION DECIDES — this module's output determines the final
  TruthStatus of the proof card.
  (PROOFLENS_MASTER_CONTEXT.md §2)
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class VerificationStatus(str, Enum):
    """Overall status of independent verification."""

    VERIFIED = "VERIFIED"
    """Primary and independent paths match and all required checks pass."""

    VERIFIED_WITH_ASSUMPTION = "VERIFIED_WITH_ASSUMPTION"
    """Verification passed, but explicit repair-world assumptions were made."""

    NOT_VERIFIED = "NOT_VERIFIED"
    """Verification cannot be completed or prerequisites/provenance are missing."""

    FAILED = "FAILED"
    """Independent computation contradicted primary computation or a critical check failed."""


class VerificationCheckName(str, Enum):
    """Named verification checks the module can perform."""

    PANDAS_PRIMARY = "PANDAS_PRIMARY"
    """Primary Pandas computation path."""

    DUCKDB_SECONDARY = "DUCKDB_SECONDARY"
    """Independent DuckDB SQL computation path."""

    MATCH_CHECK = "MATCH_CHECK"
    """Comparison between Pandas and DuckDB results."""

    PROVENANCE_CHECK = "PROVENANCE_CHECK"
    """Validation of code, table, and world cryptographic hashes."""

    SCHEMA_CHECK = "SCHEMA_CHECK"
    """Validation of required tables and columns in the target RepairWorld."""

    METAMORPHIC_ROW_SHUFFLE = "METAMORPHIC_ROW_SHUFFLE"
    """Row order should not affect order-independent aggregations."""

    METAMORPHIC_DUPLICATE_INJECTION = "METAMORPHIC_DUPLICATE_INJECTION"
    """Injecting duplicates should affect metrics according to mathematical laws."""

    METAMORPHIC_ADD_ZERO = "METAMORPHIC_ADD_ZERO"
    """Adding a zero value row should not alter additive sums."""

    METAMORPHIC_RATIO_DUPLICATION = "METAMORPHIC_RATIO_DUPLICATION"
    """Duplicating all rows should preserve ratios and percentages."""

    METAMORPHIC_FILTER_MONOTONICITY = "METAMORPHIC_FILTER_MONOTONICITY"
    """Additional restrictive filters should not increase count or non-negative sum."""

    METAMORPHIC_GROUP_TOTAL = "METAMORPHIC_GROUP_TOTAL"
    """Sum of grouped aggregations must equal overall aggregation."""

    METAMORPHIC_TOP_N = "METAMORPHIC_TOP_N"
    """Top-1 winner item must correspond to maximum grouped aggregation value."""

    METAMORPHIC_PARTITION = "METAMORPHIC_PARTITION"
    """sum(part_A) + sum(part_B) == sum(full) for applicable aggregates."""

    METAMORPHIC_SCALING = "METAMORPHIC_SCALING"
    """Scaling numeric inputs by k should scale linear results by k."""

    PREMISE_CHECK = "PREMISE_CHECK"
    """Verifies that factual premises in the question are supported by data."""

    AMBIGUITY_IMPACT = "AMBIGUITY_IMPACT"
    """Executes alternative interpretations and measures result impact."""

    CLEAN_REPRODUCTION = "CLEAN_REPRODUCTION"
    """Re-runs the analysis from stored hash to confirm determinism."""


class CheckOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    """
    SKIPPED is used when the preconditions for a check are not satisfied
    (e.g. METAMORPHIC_SCALING is skipped for non-linear metrics).
    (PROOFLENS_MASTER_CONTEXT.md §15)
    """


class VerificationCheck(BaseModel):
    """Result of a single named verification check."""

    check: VerificationCheckName = Field(
        ...,
        description="Which check was performed.",
    )
    outcome: CheckOutcome = Field(
        ...,
        description="Whether the check passed, failed, or was skipped.",
    )
    expected: str | None = Field(
        default=None,
        description="The expected value or condition (as a string for display).",
    )
    actual: str | None = Field(
        default=None,
        description="The actual value or condition observed.",
    )
    detail: str | None = Field(
        default=None,
        description="Additional context about why a check failed or was skipped.",
    )

    model_config = {"frozen": True}


class ImpactAnalysis(BaseModel):
    """
    Impact of repair-world choices on the analytical result.
    (PROOFLENS_MASTER_CONTEXT.md §14)

    All values come from actual execution results across worlds — never
    from LLM estimation.
    """

    world_results: dict[str, float | int | str | None] = Field(
        default_factory=dict,
        description=(
            "Map of world_id → result_value, e.g. "
            "{'world_A': 18610000, 'world_B': 18420000, 'world_C': 17910000}."
        ),
    )
    minimum: float | int | None = Field(
        default=None,
        description="Minimum result across all worlds.",
    )
    maximum: float | int | None = Field(
        default=None,
        description="Maximum result across all worlds.",
    )
    spread: float | int | None = Field(
        default=None,
        description="maximum − minimum.",
    )
    value_stable: bool | None = Field(
        default=None,
        description=(
            "True if the numerical values are close across worlds "
            "(within a tolerance defined by the verification module)."
        ),
    )
    decision_stable: bool | None = Field(
        default=None,
        description=(
            "True if the direction / winner remains the same across worlds "
            "even when the values differ. "
            "(PROOFLENS_MASTER_CONTEXT.md §14)"
        ),
    )


class MetamorphicTestResult(BaseModel):
    """Result of a single metamorphic test on data transformations."""

    name: str = Field(..., description="Name of the metamorphic test.")
    status: CheckOutcome = Field(..., description="Whether the metamorphic test passed, failed, or was skipped.")
    applicable: bool = Field(..., description="Whether the metamorphic transformation is applicable to this metric.")
    expected: str = Field(..., description="Expected mathematical relation or behavior.")
    observed: str = Field(..., description="Observed relation or behavior.")
    details: str = Field(default="", description="Diagnostic details or explanation.")
    transformation: str | None = Field(default=None, description="Description of the controlled transformation applied.")


class VerificationResult(BaseModel):
    """
    Complete verification record for one analysis across all worlds.

    Pipeline position: INDEPENDENT VERIFICATION through METAMORPHIC TESTING
    (stages 11–14 of 18).

    The verification_passed field is the authoritative gate.
    No number may appear in the final answer unless verification_passed is True.
    The LLM cannot set this field.
    """

    world_id: str = Field(
        ...,
        description="The RepairWorld this verification corresponds to.",
    )
    status: VerificationStatus = Field(
        default=VerificationStatus.NOT_VERIFIED,
        description="Overall verification status: VERIFIED, VERIFIED_WITH_ASSUMPTION, NOT_VERIFIED, FAILED.",
    )
    pandas_result: Any = Field(
        default=None,
        description="Result from the Pandas primary computation path.",
    )
    duckdb_result: Any = Field(
        default=None,
        description="Result from the DuckDB secondary computation path.",
    )
    primary_result: Any = Field(
        default=None,
        description="Authoritative value from primary execution result.",
    )
    independent_result: Any = Field(
        default=None,
        description="Authoritative value from independent secondary computation.",
    )
    results_match: bool | None = Field(
        default=None,
        description=(
            "True if pandas_result and duckdb_result are equal (within tolerance). "
            "None if one or both paths did not produce a result."
        ),
    )
    tolerance_abs: float = Field(
        default=1e-9,
        description="Absolute numeric tolerance used for comparison.",
    )
    tolerance_rel: float = Field(
        default=1e-9,
        description="Relative numeric tolerance used for comparison.",
    )
    verification_passed: bool = Field(
        ...,
        description=(
            "True only if all mandatory checks passed. "
            "Set deterministically by the verification engine. "
            "The LLM cannot set this field to True."
        ),
    )
    checks: list[VerificationCheck] = Field(
        default_factory=list,
        description="One entry per check performed.",
    )
    failures: list[str] = Field(
        default_factory=list,
        description=(
            "Human-readable descriptions of every check that failed. "
            "Empty if verification_passed is True."
        ),
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal warnings emitted during verification.",
    )
    metamorphic_results: list[MetamorphicTestResult] = Field(
        default_factory=list,
        description="Detailed results of each metamorphic property test.",
    )
    provenance_verified: bool = Field(
        default=False,
        description="True if all code, data, and world provenance hashes passed validation.",
    )
    provenance_details: dict[str, Any] = Field(
        default_factory=dict,
        description="Diagnostic details from cryptographic provenance verification.",
    )
    world_policies: list[str] = Field(
        default_factory=list,
        description="Summary of repair policies applied to this world.",
    )
    world_assumptions: list[str] = Field(
        default_factory=list,
        description="Assumptions associated with this world.",
    )
    impact: ImpactAnalysis | None = Field(
        default=None,
        description=(
            "Cross-world impact analysis. "
            "Populated after all worlds have been executed and verified."
        ),
    )
