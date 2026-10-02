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
    # Legacy per-share helper and current aggregate market-cap ratios.
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


def test_transforms_reject_bad_numeric_legs_and_nonfinite_results():
    for raw in [True,{},[],10**400,float('inf'),float('nan'),'2',1e308]:
        assert ef.apply_transform(raw,'pct') is None
    for numerator in [True,'100',float('inf'),10**400,0,-10]:
        assert ef.apply_transform(4,'div_mcap_flow',market_cap=numerator) is None
    assert ef.apply_transform(1e-320,'div_mcap_flow',market_cap=1e308) is None
    assert ef.apply_transform({'lt':True,'eq':4},'best_effort_lt_de') is None
    assert ef.apply_transform({'lt':1e308,'eq':1e-320},'best_effort_lt_de') is None
    assert ef.apply_transform(0,'pct')==0


def test_debt_ratios_require_nonnegative_debt_and_positive_equity():
    for equity in [0,-40,None,True,'40',float('inf'),float('nan')]:
        assert ef.apply_transform({'lt':10,'eq':equity},'best_effort_lt_de') is None
    for debt in [-10,None,True,'10',float('inf'),float('nan')]:
        assert ef.apply_transform({'lt':debt,'eq':40},'best_effort_lt_de') is None
    assert ef.apply_transform({'lt':0,'eq':40},'best_effort_lt_de')==0
    for value in [-25,True,'25',float('inf'),float('nan'),10**400]:
        assert ef.apply_transform(value,'nonnegative') is None
    assert ef.apply_transform(0,'nonnegative')==0
    assert ef.apply_transform(25,'nonnegative')==25
