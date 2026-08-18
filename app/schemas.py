"""
Three schemas, on purpose, not one:
  InvestorPortfolio  -> what comes in
  EvidenceBundle      -> what the analytics engine produces (LLM's ONLY input)
  PortfolioInsightOutput -> what goes out (validated against the evidence bundle)

Keeping these separate is what makes the numeric grounding check in
validator.py possible - the LLM literally cannot see or produce numbers
that didn't pass through EvidenceBundle first.
"""
from __future__ import annotations
from datetime import date
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class RiskAppetite(str, Enum):
    conservative = "conservative"
    moderate = "moderate"
    moderate_aggressive = "moderate-aggressive"
    aggressive = "aggressive"


class Holding(BaseModel):
    scheme_name: str
    scheme_code: str
    category: str
    invested_amount: float = Field(gt=0)
    market_value: float = Field(ge=0)
    investment_date: Optional[date] = None

    @field_validator("market_value")
    @classmethod
    def sanity_check_value(cls, v, info):
        # not a hard reject, just something downstream logic can flag as an anomaly
        return v


class InvestorPortfolio(BaseModel):
    # --- compulsory fields, no defaults, request fails without them ---
    portfolio_no: str
    investor_name: str
    age: int = Field(gt=0, lt=100)
    goal: str
    horizon_years: int = Field(gt=0)
    risk_appetite: RiskAppetite
    monthly_investment_capacity: float = Field(gt=0)
    holdings: list[Holding] = Field(min_length=1)

    # --- optional, improves personalization, never blocks a run ---
    dependents: Optional[int] = None
    other_investments: Optional[str] = None
    emergency_fund_months: Optional[float] = None
    tax_bracket: Optional[str] = None
    notes: Optional[str] = None  # free text - treated as untrusted, see sanitizer.py


# ---------------------------------------------------------------------------
# Evidence bundle: everything below this line is a NUMBER OR FACT THAT WAS
# COMPUTED, not generated. The LLM layer is only ever handed a serialized
# version of this object.
# ---------------------------------------------------------------------------

class HoldingEvidence(BaseModel):
    scheme_name: str
    scheme_code: str
    category: str
    weight_pct: float
    gain_pct: float
    invested_amount: float
    market_value: float
    absolute_gain: float
    xirr_pct: Optional[float] = None
    xirr_unavailable_reason: Optional[str] = None
    risk_grade: Optional[str] = None
    risk_source: str  # "seed_data" | "unavailable"


class CategoryAllocation(BaseModel):
    category: str
    weight_pct: float
    market_value: float


class AssetClassAllocation(BaseModel):
    asset_class: str  # Equity / Debt / Hybrid
    weight_pct: float


class OverlapFlag(BaseModel):
    fund_a: str
    fund_b: str
    category: str
    reason: str


class ConcentrationMetrics(BaseModel):
    hhi: float
    hhi_interpretation: str  # "low" | "moderate" | "high"
    top_holding_weight_pct: float
    top_holding_name: str


class PortfolioReturnMetrics(BaseModel):
    total_invested: float
    total_market_value: float
    absolute_gain: float
    absolute_gain_pct: float
    portfolio_xirr_pct: Optional[float] = None
    xirr_note: Optional[str] = None


class SuitabilityCheck(BaseModel):
    check_name: str
    result: str  # "aligned" | "mismatch" | "insufficient_data"
    detail: str


class DataQualityIssue(BaseModel):
    scheme_name: Optional[str] = None
    issue_type: str
    detail: str


class EvidenceBundle(BaseModel):
    portfolio_no: str
    investor_name: str
    age: int
    goal: str
    horizon_years: int
    risk_appetite: str
    monthly_investment_capacity: float

    holdings: list[HoldingEvidence]
    category_allocation: list[CategoryAllocation]
    asset_class_allocation: list[AssetClassAllocation]
    concentration: ConcentrationMetrics
    overlap_flags: list[OverlapFlag]
    portfolio_returns: PortfolioReturnMetrics
    suitability_checks: list[SuitabilityCheck]
    data_quality_issues: list[DataQualityIssue]

    generated_at: str
    nav_data_as_of: str
    data_freshness_note: str


# ---------------------------------------------------------------------------
# Output: what the LLM (or fallback) layer produces, schema-enforced.
# ---------------------------------------------------------------------------

class Insight(BaseModel):
    title: str
    category: str  # e.g. "concentration risk", "suitability", "overlap"
    priority: int = Field(ge=1, le=8)
    explanation: str
    evidence_refs: list[str]  # e.g. ["concentration.hhi", "holdings[0].weight_pct"]
    numbers_cited: list[float]  # every number appearing in explanation, for the groundedness check


class PortfolioInsightOutput(BaseModel):
    portfolio_no: str
    investor_name: str
    insights: list[Insight]
    disclaimer: str
    generation_mode: str  # "llm" | "fallback_template"
    warnings: list[str]  # e.g. injection attempt stripped, LLM output rejected once and regenerated
