import pytest
from pydantic import ValidationError
from app.schemas import InvestorPortfolio


VALID = {
    "portfolio_no": "PF-9999",
    "investor_name": "Test Investor",
    "age": 30,
    "goal": "wealth creation",
    "horizon_years": 10,
    "risk_appetite": "moderate",
    "monthly_investment_capacity": 10000,
    "holdings": [
        {"scheme_name": "Fund A", "scheme_code": "1", "category": "Equity - Large Cap",
         "invested_amount": 1000, "market_value": 1100, "investment_date": "2023-01-01"}
    ],
}


def test_valid_portfolio_parses():
    p = InvestorPortfolio(**VALID)
    assert p.portfolio_no == "PF-9999"


def test_missing_age_rejected():
    bad = {k: v for k, v in VALID.items() if k != "age"}
    with pytest.raises(ValidationError):
        InvestorPortfolio(**bad)


def test_missing_risk_appetite_rejected():
    bad = {k: v for k, v in VALID.items() if k != "risk_appetite"}
    with pytest.raises(ValidationError):
        InvestorPortfolio(**bad)


def test_invalid_risk_appetite_value_rejected():
    bad = dict(VALID, risk_appetite="yolo")
    with pytest.raises(ValidationError):
        InvestorPortfolio(**bad)


def test_empty_holdings_rejected():
    bad = dict(VALID, holdings=[])
    with pytest.raises(ValidationError):
        InvestorPortfolio(**bad)


def test_negative_invested_amount_rejected():
    bad_holding = dict(VALID["holdings"][0], invested_amount=-500)
    bad = dict(VALID, holdings=[bad_holding])
    with pytest.raises(ValidationError):
        InvestorPortfolio(**bad)


def test_missing_investment_date_allowed():
    # optional at the holding level - shouldn't block ingestion, just flagged downstream
    holding = dict(VALID["holdings"][0])
    holding.pop("investment_date")
    ok = dict(VALID, holdings=[holding])
    p = InvestorPortfolio(**ok)
    assert p.holdings[0].investment_date is None


def test_optional_fields_default_to_none():
    p = InvestorPortfolio(**VALID)
    assert p.dependents is None
    assert p.notes is None
