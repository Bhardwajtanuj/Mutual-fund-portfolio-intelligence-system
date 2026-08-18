from datetime import date
from app.schemas import Holding
from app import analytics


def h(name, code, cat, invested, value, dt=None):
    return Holding(scheme_name=name, scheme_code=code, category=cat,
                    invested_amount=invested, market_value=value, investment_date=dt)


def test_herfindahl_index_equal_split():
    # 4 equal 25% holdings -> HHI = 4 * 0.25^2 = 0.25
    assert analytics.herfindahl_index([25, 25, 25, 25]) == 0.25


def test_herfindahl_index_single_holding():
    # 100% in one fund -> HHI = 1.0, max concentration
    assert analytics.herfindahl_index([100]) == 1.0


def test_interpret_hhi_thresholds():
    assert analytics.interpret_hhi(0.10) == "low"
    assert analytics.interpret_hhi(0.20) == "moderate"
    assert analytics.interpret_hhi(0.30) == "high"


def test_allocation_by_category_sums_to_100():
    holdings = [
        h("A", "1", "Equity - Large Cap", 100, 120),
        h("B", "2", "Equity - Mid Cap", 100, 90),
    ]
    total = sum(x.market_value for x in holdings)
    alloc = analytics.allocation_by_category(holdings, total)
    assert round(sum(a.weight_pct for a in alloc), 2) == 100.00


def test_concentration_identifies_top_holding():
    holdings = [
        h("Small", "1", "Equity - Small Cap", 10, 10),
        h("Big", "2", "Equity - Large Cap", 90, 90),
    ]
    total = sum(x.market_value for x in holdings)
    c = analytics.compute_concentration(holdings, total)
    assert c.top_holding_name == "Big"
    assert c.top_holding_weight_pct == 90.0


def test_overlap_detects_same_category():
    holdings = [
        h("Fund A", "1", "Equity - Large Cap", 100, 100),
        h("Fund B", "2", "Equity - Large Cap", 100, 100),
        h("Fund C", "3", "Debt - Short Duration", 100, 100),
    ]
    flags = analytics.detect_overlap(holdings)
    assert len(flags) == 1
    assert flags[0].category == "Equity - Large Cap"


def test_overlap_no_flags_when_all_categories_distinct():
    holdings = [
        h("A", "1", "Equity - Large Cap", 100, 100),
        h("B", "2", "Debt - Short Duration", 100, 100),
    ]
    assert analytics.detect_overlap(holdings) == []


def test_xirr_known_case():
    # invest 100000 on day 0, worth 110000 exactly 1 year later -> ~10% XIRR
    cf = [(date(2023, 1, 1), -100000), (date(2024, 1, 1), 110000)]
    rate = analytics.xirr(cf)
    assert rate is not None
    assert abs(rate - 10.0) < 0.5


def test_xirr_none_with_insufficient_cashflows():
    assert analytics.xirr([(date(2023, 1, 1), -100000)]) is None


def test_holding_evidence_skips_xirr_when_date_missing():
    holdings = [h("Fund X", "1", "Equity - Mid Cap", 100000, 129500, dt=None)]
    evidence, issues = analytics.compute_holding_evidence(holdings, 129500, {}, date(2024, 1, 1))
    assert evidence[0].xirr_pct is None
    assert evidence[0].xirr_unavailable_reason is not None
    assert any(i.issue_type == "missing_investment_date" for i in issues)


def test_holding_evidence_flags_unknown_risk_grade():
    holdings = [h("Unknown Fund", "999999", "Equity - Large Cap", 100, 110, dt=date(2023, 1, 1))]
    evidence, issues = analytics.compute_holding_evidence(holdings, 110, {}, date(2024, 1, 1))
    assert evidence[0].risk_source == "unavailable"
    assert any(i.issue_type == "risk_grade_unavailable" for i in issues)


def test_gain_pct_calculation():
    holdings = [h("A", "1", "Equity - Large Cap", 100000, 125000, dt=date(2023, 1, 1))]
    evidence, _ = analytics.compute_holding_evidence(holdings, 125000, {}, date(2024, 1, 1))
    assert evidence[0].gain_pct == 25.0
    assert evidence[0].absolute_gain == 25000.0
