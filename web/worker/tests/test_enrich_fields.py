"""Field registry invariants + transform behavior."""
from tradingagents_worker import enrich_fields as ef


def test_registry_consistency():
    ours = [k for k, _ in ef.YF_FIELDS.values() if not k.startswith("_")]
    assert len(ours) == len(set(ours)), "duplicate our-keys in YF_FIELDS"
    assert set(ours) == ef.YF_ONLY_FIELDS
    for src in ef.FIELD_SOURCE.values():
        assert src in ("moo", "calc", "yf")
    for f in ef.TECH_FIELDS:
        assert ef.FIELD_SOURCE[f] == "calc"


def test_transforms():
    assert ef.apply_transform(0.1234, "pct") == 12.34          # ratio → %
    assert ef.apply_transform(0.037, "pct_of_float") == 3.7
    assert ef.apply_transform(1735689600, "unix_date") == "2025-01-01"
    assert ef.apply_transform(None, "pct") is None
    # price/cash and P/FCF derive from stored price / market cap
    assert ef.apply_transform(4.0, "div_price", price=100.0) == 25.0   # 100 ÷ 4
    assert ef.apply_transform(1_000.0, "div_mcap_flow", market_cap=50_000.0) == 50.0
    assert ef.apply_transform(1_000.0, "div_mcap_flow", market_cap=None) is None
    # best-effort LT debt / equity: needs both legs
    assert ef.apply_transform({"lt": 10.0, "eq": 40.0}, "best_effort_lt_de") == 25.0
    assert ef.apply_transform({"lt": 10.0, "eq": None}, "best_effort_lt_de") is None


def test_labels_exist_for_every_field():
    for k in list(ef.YF_ONLY_FIELDS) + ef.TECH_FIELDS + ef.MOO_FREE_FIELDS:
        assert k in ef.FIELD_LABELS, f"missing label for {k}"


def test_financial_fields_present():
    """Phase B: the Financial tab's fundamentals are yf-sourced percent fields."""
    expected = {"roe": "pct", "gross_margin": "pct", "operating_margin": "pct",
                "net_margin": "pct", "revenue_growth": "pct", "eps_growth": "pct"}
    for key, tr in expected.items():
        assert key in ef.YF_ONLY_FIELDS, f"{key} missing from registry"
        assert tr in [t for k, t in ef.YF_FIELDS.values() if k == key], f"{key} wrong transform"
