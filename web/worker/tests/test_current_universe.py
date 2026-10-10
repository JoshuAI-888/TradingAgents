import uuid

import pytest
from tradingagents_worker.current_universe import current_codes
from tradingagents_worker.screener_generations import GenerationError


def test_enrichment_uses_only_complete_current_stock_cohort(fake_db):
    token = str(uuid.uuid4())
    fake_db.upsert(
        "app_settings", "key", {"key": "universe_state_US", "value": {"generation_id": token}}
    )
    fake_db.upsert("screener_generations", "id", {"id": token, "market": "US", "row_count": 2})
    fake_db.upsert_many(
        "screener_generation_rows",
        "generation_id,code",
        [
            {"generation_id": token, "code": "US.NEW", "stock_type": "STOCK"},
            {"generation_id": token, "code": "US.FUND", "stock_type": "ETF"},
            {"generation_id": str(uuid.uuid4()), "code": "US.OLD", "stock_type": "STOCK"},
        ],
    )
    fake_db.upsert("screener_universe", "market,code", {"market": "US", "code": "US.OLD"})
    assert current_codes(fake_db, "US") == ["US.NEW"]
    fake_db.tables["screener_generation_rows"].pop(0)
    with pytest.raises(GenerationError, match="incomplete"):
        current_codes(fake_db, "US")


def test_missing_published_pointer_does_not_admit_historical_codes(fake_db):
    fake_db.upsert("screener_universe", "market,code", {"market": "US", "code": "US.OLD"})
    assert current_codes(fake_db, "US") == []
