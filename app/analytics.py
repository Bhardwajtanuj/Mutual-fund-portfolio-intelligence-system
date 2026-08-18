"""
Pure Python financial calculations. Nothing in here touches an LLM.
If a number appears in the final output, it was computed by a function
in this file (or is a direct passthrough of investor-supplied data).
"""
from datetime import date, datetime
from typing import Optional
from app.schemas import (
    InvestorPortfolio, Holding, HoldingEvidence, CategoryAllocation,
    AssetClassAllocation, ConcentrationMetrics, OverlapFlag,
    PortfolioReturnMetrics, SuitabilityCheck, DataQualityIssue,
)

try:
    import numpy_financial as npf
except ImportError:
    npf = None


ASSET_CLASS_MAP = {
    "Equity": "Equity",
    "Debt": "Debt",
    "Hybrid": "Hybrid",
}


def asset_class_of(category: str) -> str:
    head = category.split(" - ")[0].strip()
    return ASSET_CLASS_MAP.get(head, head)


def allocation_by_category(holdings: list[Holding], total_value: float) -> list[CategoryAllocation]:
    buckets: dict[str, float] = {}
    for h in holdings:
        buckets[h.category] = buckets.get(h.category, 0.0) + h.market_value
    out = []
    for cat, val in sorted(buckets.items(), key=lambda x: -x[1]):
        pct = round(val / total_value * 100, 2) if total_value else 0.0
        out.append(CategoryAllocation(category=cat, weight_pct=pct, market_value=round(val, 2)))
    return out


def allocation_by_asset_class(holdings: list[Holding], total_value: float) -> list[AssetClassAllocation]:
    buckets: dict[str, float] = {}
    for h in holdings:
        ac = asset_class_of(h.category)
        buckets[ac] = buckets.get(ac, 0.0) + h.market_value
    out = []
    for ac, val in sorted(buckets.items(), key=lambda x: -x[1]):
        pct = round(val / total_value * 100, 2) if total_value else 0.0
        out.append(AssetClassAllocation(asset_class=ac, weight_pct=pct))
    return out


def herfindahl_index(weights_pct: list[float]) -> float:
    """
    HHI on a 0-1 scale (sum of squared weight fractions). Standard finance
    convention: <0.15 low concentration, 0.15-0.25 moderate, >0.25 high.
    Using fund-level weights (not category-level) since a portfolio can be
    "diversified" by category but still concentrated in one fund pick.
    """
    return round(sum((w / 100) ** 2 for w in weights_pct), 4)


def interpret_hhi(hhi: float) -> str:
    if hhi < 0.15:
        return "low"
    if hhi < 0.25:
        return "moderate"
    return "high"


def compute_concentration(holdings: list[Holding], total_value: float) -> ConcentrationMetrics:
    weights = [(h.market_value / total_value * 100 if total_value else 0.0) for h in holdings]
    hhi = herfindahl_index(weights)
    top_idx = max(range(len(holdings)), key=lambda i: weights[i]) if holdings else 0
    return ConcentrationMetrics(
        hhi=hhi,
        hhi_interpretation=interpret_hhi(hhi),
        top_holding_weight_pct=round(weights[top_idx], 2) if holdings else 0.0,
        top_holding_name=holdings[top_idx].scheme_name if holdings else "",
    )


def detect_overlap(holdings: list[Holding]) -> list[OverlapFlag]:
    """
    Prototype-level overlap detection: same category held via more than one
    scheme is flagged as a category-overlap risk (a proxy for actual
    holdings-level overlap, which would need each fund's underlying stock
    list - out of scope for this prototype, noted as a limitation in README).
    """
    flags = []
    by_category: dict[str, list[Holding]] = {}
    for h in holdings:
        by_category.setdefault(h.category, []).append(h)
    for cat, funds in by_category.items():
        if len(funds) > 1:
            for i in range(len(funds)):
                for j in range(i + 1, len(funds)):
                    flags.append(OverlapFlag(
                        fund_a=funds[i].scheme_name,
                        fund_b=funds[j].scheme_name,
                        category=cat,
                        reason=f"Both funds sit in the same category ({cat}); likely overlapping "
                               f"stock/bond exposure, though exact portfolio overlap isn't computed "
                               f"here without underlying constituent data.",
                    ))
    return flags


def xirr(cashflows: list[tuple[date, float]], guess: float = 0.1) -> float | None:
    """
    Simple XIRR via Newton's method on day-count-adjusted cashflows.
    Returns None if it can't converge or if npf isn't usable for this shape.
    """
    if len(cashflows) < 2:
        return None
    cashflows = sorted(cashflows, key=lambda x: x[0])
    t0 = cashflows[0][0]

    def npv(rate):
        return sum(cf / (1 + rate) ** ((d - t0).days / 365.0) for d, cf in cashflows)

    def dnpv(rate):
        return sum(-((d - t0).days / 365.0) * cf / (1 + rate) ** (((d - t0).days / 365.0) + 1)
                   for d, cf in cashflows)

    rate = guess
    for _ in range(100):
        f = npv(rate)
        fp = dnpv(rate)
        if abs(fp) < 1e-10:
            return None
        new_rate = rate - f / fp
        if abs(new_rate - rate) < 1e-6:
            if new_rate <= -0.99:
                return None
            return round(new_rate * 100, 2)
        rate = new_rate
    return None


def compute_holding_evidence(holdings: list[Holding], total_value: float,
                              risk_seed: dict, today: date) -> tuple[list[HoldingEvidence], list[DataQualityIssue]]:
    out = []
    issues = []
    for h in holdings:
        weight = round(h.market_value / total_value * 100, 2) if total_value else 0.0
        gain_abs = round(h.market_value - h.invested_amount, 2)
        gain_pct = round((gain_abs / h.invested_amount) * 100, 2) if h.invested_amount else 0.0

        fund_xirr = None
        xirr_reason = None
        if h.investment_date is None:
            xirr_reason = "investment_date missing - XIRR cannot be computed without a cashflow date"
            issues.append(DataQualityIssue(
                scheme_name=h.scheme_name, issue_type="missing_investment_date",
                detail="No investment date supplied; return-rate (XIRR) skipped for this holding.",
            ))
        else:
            cf = [(h.investment_date, -h.invested_amount), (today, h.market_value)]
            fund_xirr = xirr(cf)
            if fund_xirr is None:
                xirr_reason = "XIRR calculation did not converge for this cashflow pattern"
                issues.append(DataQualityIssue(
                    scheme_name=h.scheme_name, issue_type="xirr_failed",
                    detail="XIRR solver did not converge; excluded from return-based insights.",
                ))

        seed = risk_seed.get(h.scheme_code)
        risk_grade = seed["risk_grade"] if seed else None
        risk_source = "seed_data" if seed else "unavailable"
        if not seed:
            issues.append(DataQualityIssue(
                scheme_name=h.scheme_name, issue_type="risk_grade_unavailable",
                detail="Scheme not present in curated risk seed file; risk grade omitted rather than guessed.",
            ))

        out.append(HoldingEvidence(
            scheme_name=h.scheme_name, scheme_code=h.scheme_code, category=h.category,
            weight_pct=weight, gain_pct=gain_pct, invested_amount=h.invested_amount,
            market_value=h.market_value, absolute_gain=gain_abs,
            xirr_pct=fund_xirr, xirr_unavailable_reason=xirr_reason,
            risk_grade=risk_grade, risk_source=risk_source,
        ))
    return out, issues


def compute_portfolio_returns(holdings: list[Holding], today: date) -> tuple[PortfolioReturnMetrics, Optional[str]]:
    total_invested = sum(h.invested_amount for h in holdings)
    total_value = sum(h.market_value for h in holdings)
    abs_gain = total_value - total_invested
    abs_gain_pct = round((abs_gain / total_invested) * 100, 2) if total_invested else 0.0

    cashflows = []
    skipped = 0
    for h in holdings:
        if h.investment_date is None:
            skipped += 1
            continue
        cashflows.append((h.investment_date, -h.invested_amount))
    cashflows.append((today, total_value))

    note = None
    port_xirr = None
    if skipped > 0:
        note = f"{skipped} holding(s) missing an investment date; portfolio-level XIRR is computed " \
               f"on the remaining cashflows only and should be read as approximate."
    if len(cashflows) >= 2:
        port_xirr = xirr(cashflows)
        if port_xirr is None and note is None:
            note = "Portfolio XIRR could not be reliably computed from the available cashflow dates."

    return PortfolioReturnMetrics(
        total_invested=round(total_invested, 2),
        total_market_value=round(total_value, 2),
        absolute_gain=round(abs_gain, 2),
        absolute_gain_pct=abs_gain_pct,
        portfolio_xirr_pct=port_xirr,
        xirr_note=note,
    ), note


def run_suitability_checks(portfolio: InvestorPortfolio,
                            asset_alloc: list[AssetClassAllocation],
                            concentration: ConcentrationMetrics) -> list[SuitabilityCheck]:
    checks = []
    equity_pct = next((a.weight_pct for a in asset_alloc if a.asset_class == "Equity"), 0.0)

    # age/horizon vs equity exposure - a widely used rule of thumb, stated as such, not as fact
    years_to_goal = portfolio.horizon_years
    if years_to_goal <= 7 and equity_pct > 60:
        checks.append(SuitabilityCheck(
            check_name="horizon_vs_equity_exposure",
            result="mismatch",
            detail=f"Only {years_to_goal} years to the stated goal but {equity_pct}% of the portfolio "
                   f"is in equity. A common rule of thumb for a sub-7-year horizon is to reduce equity "
                   f"exposure to limit drawdown risk close to the goal date.",
        ))
    elif years_to_goal <= 7:
        checks.append(SuitabilityCheck(
            check_name="horizon_vs_equity_exposure", result="aligned",
            detail=f"Equity exposure ({equity_pct}%) is reasonably contained for a {years_to_goal}-year horizon.",
        ))
    else:
        checks.append(SuitabilityCheck(
            check_name="horizon_vs_equity_exposure", result="aligned",
            detail=f"{years_to_goal}-year horizon comfortably supports the current {equity_pct}% equity exposure.",
        ))

    # stated risk appetite vs concentration
    if portfolio.risk_appetite.value == "conservative" and concentration.hhi_interpretation == "high":
        checks.append(SuitabilityCheck(
            check_name="risk_appetite_vs_concentration", result="mismatch",
            detail=f"Investor self-declared 'conservative' but portfolio concentration is high "
                   f"(HHI {concentration.hhi}), driven by {concentration.top_holding_name} at "
                   f"{concentration.top_holding_weight_pct}% of the portfolio.",
        ))
    else:
        checks.append(SuitabilityCheck(
            check_name="risk_appetite_vs_concentration", result="aligned",
            detail=f"Portfolio concentration ({concentration.hhi_interpretation}, HHI {concentration.hhi}) "
                   f"is broadly consistent with a '{portfolio.risk_appetite.value}' risk appetite.",
        ))

    # monthly capacity vs current run-rate is not knowable from a point-in-time snapshot -
    # explicitly marked insufficient rather than guessed
    checks.append(SuitabilityCheck(
        check_name="sip_capacity_utilization", result="insufficient_data",
        detail="No SIP/transaction history was supplied, only point-in-time invested and market "
               "values, so whether the stated monthly capacity is being fully utilized can't be determined.",
    ))

    return checks
