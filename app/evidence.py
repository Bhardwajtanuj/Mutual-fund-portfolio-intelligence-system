from datetime import date, datetime, timezone
from app import analytics
from app.schemas import InvestorPortfolio, EvidenceBundle


def build_evidence_bundle(portfolio: InvestorPortfolio, risk_seed: dict,
                           nav_as_of: str, today: date | None = None) -> EvidenceBundle:
    today = today or date.today()
    total_value = sum(h.market_value for h in portfolio.holdings)

    holding_evidence, holding_issues = analytics.compute_holding_evidence(
        portfolio.holdings, total_value, risk_seed, today)
    category_alloc = analytics.allocation_by_category(portfolio.holdings, total_value)
    asset_alloc = analytics.allocation_by_asset_class(portfolio.holdings, total_value)
    concentration = analytics.compute_concentration(portfolio.holdings, total_value)
    overlap = analytics.detect_overlap(portfolio.holdings)
    port_returns, _ = analytics.compute_portfolio_returns(portfolio.holdings, today)
    suitability = analytics.run_suitability_checks(portfolio, asset_alloc, concentration)

    data_issues = list(holding_issues)

    return EvidenceBundle(
        portfolio_no=portfolio.portfolio_no,
        investor_name=portfolio.investor_name,
        age=portfolio.age,
        goal=portfolio.goal,
        horizon_years=portfolio.horizon_years,
        risk_appetite=portfolio.risk_appetite.value,
        monthly_investment_capacity=portfolio.monthly_investment_capacity,
        holdings=holding_evidence,
        category_allocation=category_alloc,
        asset_class_allocation=asset_alloc,
        concentration=concentration,
        overlap_flags=overlap,
        portfolio_returns=port_returns,
        suitability_checks=suitability,
        data_quality_issues=data_issues,
        generated_at=datetime.now(timezone.utc).isoformat(),
        nav_data_as_of=nav_as_of,
        data_freshness_note="Market values taken as supplied in the input; not re-fetched from a "
                             "live NAV source in this prototype run (see README, AMFI integration).",
    )
