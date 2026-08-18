"""
Two things happen here, and they're the last line of defense before an
insight goes out the door:

1. Schema validation - already partly handled by Pydantic at construction,
   but re-checked explicitly here so callers get a clear pass/fail signal.
2. Groundedness check - every number in Insight.numbers_cited must trace
   back to a value that actually exists somewhere in the evidence bundle.
   This is what stops the LLM from quietly inventing a return figure.
"""
from app.schemas import EvidenceBundle, PortfolioInsightOutput, Insight

TOLERANCE = 0.05  # float rounding slack


def _collect_evidence_numbers(bundle: EvidenceBundle) -> set[float]:
    nums = set()
    nums.add(round(bundle.age, 2))
    nums.add(round(bundle.horizon_years, 2))
    nums.add(round(bundle.monthly_investment_capacity, 2))

    for h in bundle.holdings:
        for v in (h.weight_pct, h.gain_pct, h.invested_amount, h.market_value, h.absolute_gain):
            nums.add(round(v, 2))
        if h.xirr_pct is not None:
            nums.add(round(h.xirr_pct, 2))

    for c in bundle.category_allocation:
        nums.add(round(c.weight_pct, 2))
        nums.add(round(c.market_value, 2))
    for a in bundle.asset_class_allocation:
        nums.add(round(a.weight_pct, 2))

    nums.add(round(bundle.concentration.hhi, 4))
    nums.add(round(bundle.concentration.top_holding_weight_pct, 2))

    r = bundle.portfolio_returns
    for v in (r.total_invested, r.total_market_value, r.absolute_gain, r.absolute_gain_pct):
        nums.add(round(v, 2))
    if r.portfolio_xirr_pct is not None:
        nums.add(round(r.portfolio_xirr_pct, 2))

    return nums


def _is_grounded(value: float, evidence_numbers: set[float]) -> bool:
    return any(abs(value - n) <= TOLERANCE for n in evidence_numbers)


def check_groundedness(insight: Insight, bundle: EvidenceBundle) -> list[str]:
    evidence_numbers = _collect_evidence_numbers(bundle)
    problems = []
    for n in insight.numbers_cited:
        if not _is_grounded(n, evidence_numbers):
            problems.append(f"Insight '{insight.title}' cites {n}, which does not match any "
                             f"value in the evidence bundle.")
    return problems


def validate_output(output: PortfolioInsightOutput, bundle: EvidenceBundle) -> tuple[bool, list[str]]:
    problems = []
    if output.portfolio_no != bundle.portfolio_no:
        problems.append("portfolio_no mismatch between output and evidence bundle.")
    if not output.insights:
        problems.append("No insights produced.")
    if len(output.insights) > 8:
        problems.append("More than 8 insights - output should be prioritized, not exhaustive.")

    for insight in output.insights:
        problems.extend(check_groundedness(insight, bundle))

    return (len(problems) == 0), problems
