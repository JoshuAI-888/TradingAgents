"""Generation-consistent public readers: publication between requests and corruption."""

import copy
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_api import FakeDb
from tradingagents_api import main as api


class GenerationDb(FakeDb):
    def select_all(self, table, query=None, columns="*", cap=20000):
        return self.select(table, query, columns)[:cap]


def publish(db, codes=("US.A", "US.B"), price=10):
    gid = str(uuid.uuid4())
    stamp = datetime.now(timezone.utc).isoformat()
    result = {"quotes": {"market": "US", "quotes": len(codes)}}
    db._t("screener_generations").append(
        {
            "id": gid,
            "market": "US",
            "row_count": len(codes),
            "started_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            "published_at": stamp,
            "cohort_fingerprint": hashlib.sha256("\n".join(sorted(codes)).encode()).hexdigest(),
            "result": result,
        }
    )
    for i, code in enumerate(codes):
        db._t("screener_generation_rows").append(
            {
                "generation_id": gid,
                "code": code,
                "row": {
                    "code": code,
                    "price": price + i,
                    "market_cap": 100 - i,
                    "stock_type": "ETF",
                    "plate": "WRONG",
                },
                "metadata": {
                    "code": code,
                    "market": "US",
                    "name": code,
                    "stock_type": "STOCK",
                    "plate": "Pinned",
                    "plates": ["Pinned", "Theme"],
                    "exchange": "NASDAQ",
                },
                "quote_cache_at": stamp,
            }
        )
    db.upsert(
        "app_settings",
        "key",
        {
            "key": "universe_state_US",
            "value": {"generation_id": gid, "last_quotes": stamp, "last_result": result},
        },
    )
    return gid


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("DEFAULT_USER_ID", "generation-test-owner")
    db = GenerationDb()
    monkeypatch.setattr(api, "db", db)
    monkeypatch.setattr(api, "_stored_universe_cache", {})
    monkeypatch.setattr(api, "_presets_cache", {})
    monkeypatch.setattr(api, "_market_client", lambda: None)
    monkeypatch.setattr(api, "_watchlist_symbols", lambda: [])
    db._t("screener_quotes").append(
        {"code": "US.LEGACY", "row": {"code": "US.LEGACY", "stock_type": "STOCK"}}
    )
    return db, TestClient(api.app)


def test_pointer_change_bypasses_market_cache_and_old_generation_stays_pinned(setup):
    db, client = setup
    first = publish(db)
    a = client.get("/api/screener?watchlist_only=0&limit=1").json()
    assert a["available"] and a["generation_id"] == first
    assert [r["code"] for r in a["rows"]] == ["US.A"]
    second = publish(db, ("US.C", "US.D"), 20)
    current = client.get("/api/screener?watchlist_only=0&limit=1&offset=1").json()
    original = client.get(
        f"/api/screener?watchlist_only=0&limit=1&offset=1&generation_id={first}"
    ).json()
    assert current["generation_id"] == second and current["rows"][0]["code"] == "US.D"
    assert original["generation_id"] == first and original["rows"][0]["code"] == "US.B"
    assert original["rows"][0]["price"] == 11


def test_metadata_and_mutation_do_not_mix_generations(setup):
    db, _ = setup
    gid = publish(db)
    a, _ = api._stored_universe("US")
    assert a[0]["stock_type"] == "STOCK" and a[0]["plate"] == "Pinned"
    assert a[0]["concepts"] == ["Theme"]
    a[0]["concepts"].append("Uncommitted")
    a[0]["price"] = 999
    db._t("screener_universe").append({"code": "US.A", "stock_type": "ETF", "plate": "Mixed"})
    b, _ = api._stored_universe("US")
    assert b[0]["price"] == 10 and b[0]["concepts"] == ["Theme"]
    assert api._merge_universe_meta(b, "US")[0]["generation_id"] == gid


@pytest.mark.parametrize(
    "damage", ["null_pointer", "missing_header", "missing_row", "fingerprint", "clock", "metadata"]
)
def test_corrupt_generation_fails_closed_without_legacy_or_vendor_fallback(setup, damage):
    db, client = setup
    publish(db)
    if damage == "null_pointer":
        db.tables["app_settings"][0]["value"]["generation_id"] = None
    elif damage == "missing_header":
        db.tables["screener_generations"] = []
    elif damage == "missing_row":
        db.tables["screener_generation_rows"].pop()
    elif damage == "fingerprint":
        db.tables["screener_generations"][0]["cohort_fingerprint"] = "bad"
    elif damage == "clock":
        db.tables["app_settings"][0]["value"]["last_quotes"] = "2026-10-02T06:00:01Z"
    else:
        db.tables["screener_generation_rows"][0]["metadata"]["market"] = "HK"
    assert client.get("/api/screener?watchlist_only=0").status_code == 503
    assert client.get("/api/screener/presets").status_code == 503
    assert client.get("/api/screener/facets?field=plate").status_code == 503


def test_empty_filter_and_download_keep_generation_identity(setup):
    db, client = setup
    gid = publish(db)
    empty = client.get(
        "/api/screener", params={"watchlist_only": 0, "filters": '[{"field":"price","min":999}]'}
    ).json()
    assert empty["count"] == 0 and empty["generation_id"] == gid
    csv = client.get(
        "/api/screener", params={"watchlist_only": 0, "export": "csv", "generation_id": gid}
    )
    assert csv.status_code == 200 and csv.headers["X-Screener-Generation"] == gid
    assert "US.LEGACY" not in csv.text and gid in csv.text


def test_generation_bound_to_market_and_watchlist(setup):
    db, client = setup
    gid = publish(db)
    assert (
        client.get(f"/api/screener?market=HK&watchlist_only=0&generation_id={gid}").status_code
        == 503
    )
    # Reject explicit market generation before making any watchlist request.
    assert client.get(f"/api/screener?watchlist_only=1&generation_id={gid}").status_code == 400


def test_read_full_cohort_over_postgrest_page_size(setup):
    db, _ = setup
    codes = tuple(f"US.A{i:04}" for i in range(1201))
    publish(db, codes)
    rows, _ = api._stored_universe("US")
    assert len(rows) == 1201 and {r["code"] for r in rows} == set(codes)


def test_schedule_and_groups_exclude_retained_legacy_rows(setup):
    db, client = setup
    gid = publish(db)
    db._t("screener_universe").append({"code": "US.LEGACY", "market": "US", "stock_type": "STOCK"})
    counts = client.get("/api/screener/schedule").json()
    assert counts["generation_id"] == gid
    assert counts["quote_rows"] == counts["universe_rows"] == counts["stock_rows"] == 2
    group = client.get("/api/groups?group_by=plate").json()
    assert group["available"] and group["rows"][0]["stocks"] == 2 and group["generation_id"] == gid


def test_cached_preview_cannot_mask_corrupt_success_state(setup):
    db, client = setup
    publish(db)
    assert client.get("/api/screener/presets").status_code == 200
    db.tables["app_settings"][0]["value"]["last_quotes"] = "2026-10-02T06:00:01Z"
    assert client.get("/api/screener/presets").status_code == 503


def test_capture_pins_viewed_generation_across_publication_and_retry(setup):
    db, client = setup
    first = publish(db)
    second = publish(db, ("US.C", "US.D"), 20)
    request = str(uuid.uuid4())
    headers = {"Idempotency-Key": request, "X-Screener-Generation": first}
    definition = {"market": "US", "filters": []}
    response = client.post("/api/screener/snapshots", json=definition, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["source_generation_id"] == first
    snapshot = db.tables["screen_captures"][-1]["snapshot"]
    assert {r["code"] for r in snapshot["members"]} == {"US.A", "US.B"}
    assert snapshot["source_clock"] == "generation_publication"
    assert {r["generation_id"] for r in snapshot["observations"]} == {first}
    assert client.post("/api/screener/snapshots", json=definition, headers=headers).json()[
        "idempotent"
    ]
    wrong = client.post(
        "/api/screener/snapshots",
        json=definition,
        headers={**headers, "X-Screener-Generation": second},
    )
    assert wrong.status_code == 409 and len(db.tables["screen_captures"]) == 1
    missing = copy.deepcopy(snapshot)
    missing.pop("source_generation_id")
    with pytest.raises(ValueError, match="Generation identity"):
        api.validate_observation_capture(missing, snapshot["definition"])
    tampered = copy.deepcopy(snapshot)
    tampered["observations"][0]["generation_id"] = second
    with pytest.raises(ValueError, match="generation"):
        api.validate_observation_capture(tampered, snapshot["definition"])


def test_pinned_generation_rejected_for_provider_and_watchlist_captures(setup):
    db, client = setup
    gid = publish(db)
    for definition in [{"watchlist_only": True}, {"preset": api.PRESET_SCREENERS[0]["key"]}]:
        result = client.post(
            "/api/screener/snapshots", json=definition, headers={"X-Screener-Generation": gid}
        )
        assert result.status_code == 400


class ScreenProvider:
    def __init__(self, codes=("US.A", "US.OUT"), price=None, malformed=""):
        self.codes = codes
        self.price = price
        self.malformed = malformed

    def call(self, method, path, body):
        if path.endswith("stock-basicinfo"):
            codes = ["US.WRONG"] if self.malformed == "classification" else body["code_list"]
            return {
                "basic_list": [
                    {"code": c, "stock_type": "STOCK", "exchange": "NASDAQ"} for c in codes
                ]
            }
        return {
            "items": [
                {
                    "code": c,
                    "results": []
                    if self.price is None
                    else [
                        {
                            "simple_property_result": {
                                "property": {"name": 2201},
                                "res": {"ival": self.price},
                            }
                        }
                    ],
                }
                for c in self.codes
            ]
        }

    def snapshot(self, codes):
        codes = ["US.WRONG"] if self.malformed == "snapshot" else codes
        return {"snapshot_list": [{"code": c, "last_price": 7, "stock_type": None} for c in codes]}


def test_provider_membership_keeps_pinned_quote_and_outside_live_sources(setup, monkeypatch):
    db, _ = setup
    gid = publish(db)
    db._t("screener_quotes").append(
        {
            "market": "US",
            "code": "US.OUT",
            "row": {"code": "US.OUT", "price": 999, "stock_type": "ETF"},
        }
    )
    monkeypatch.setattr(api, "_market_client", lambda: ScreenProvider())
    result = api.screener_execute("penny", "US", 300)
    assert result["available"] and result["quote_generation_id"] == gid
    assert result["outside_quote_cohort"] == 1 and result["unclassified_count"] == 0
    a, out = result["rows"]
    assert a["price"] == 10 and a["stock_type"] == "STOCK"
    assert a["display_field_sources"]["price"]["generation_id"] == gid
    assert out["price"] == 7 and out["quote_generation_id"] is None and out["stock_type"] == "STOCK"
    assert out["display_field_sources"]["price"]["source"] == "live_snapshot"
    assert out["display_field_sources"]["stock_type"]["source"] == "provider_basicinfo"
    assert out["provider_stock_type"] == "STOCK"
    from tradingagents_worker.instrument_classification import validate

    assert validate(out["instrument_classification"], out["code"], out["quote_cache_at"])
    assert "generation_id" not in a and "generation_id" not in out


def test_outside_cohort_trust_fund_category_is_not_claimed_as_exact_etf(setup, monkeypatch):
    db, _ = setup
    gid = publish(db)

    class TrustProvider(ScreenProvider):
        def call(self, method, path, body):
            if path.endswith("stock-basicinfo"):
                return {
                    "basic_list": [
                        {"code": code, "stock_type": "ETF", "exchange": "NYSE"}
                        for code in body["code_list"]
                    ]
                }
            return super().call(method, path, body)

    monkeypatch.setattr(api, "_market_client", lambda: TrustProvider())
    result = api.screener_execute("penny", "US", 300)
    a, out = result["rows"]
    assert a["stock_type"] == "STOCK" and result["quote_generation_id"] == gid
    assert out["stock_type"] == "UNKNOWN" and out["provider_stock_type"] == "ETF"
    assert out["instrument_classification"]["reason"] == "trust_fund_subtype_unavailable"
    assert out["quote_generation_id"] is None
    assert result["unclassified_count"] == 1 and result["outside_quote_cohort"] == 1
    assert out["display_field_sources"]["price"]["source"] == "live_snapshot"
    from tradingagents_worker.instrument_classification import validate

    assert validate(out["instrument_classification"], out["code"], out["quote_cache_at"])


def test_malformed_raw_classification_cannot_partially_assign_types(setup, monkeypatch):
    db, _ = setup
    publish(db)

    class BadTypes(ScreenProvider):
        def call(self, method, path, body):
            if path.endswith("stock-basicinfo"):
                return {
                    "basic_list": [
                        {"code": code, "stock_type": ("STOCK" if i == 0 else True)}
                        for i, code in enumerate(body["code_list"])
                    ]
                }
            return super().call(method, path, body)

    monkeypatch.setattr(api, "_market_client", lambda: BadTypes(("US.OUT1", "US.OUT2")))
    result = api.screener_execute("penny", "US", 300)
    assert result["available"] and result["hydration_warnings"]
    assert result["unclassified_count"] == 2
    assert all(
        not r.get("stock_type") and "instrument_classification" not in r for r in result["rows"]
    )


def test_provider_zero_and_screen_observation_do_not_inherit_other_quote_value(setup, monkeypatch):
    db, _ = setup
    gid = publish(db)
    row = db.tables["screener_generation_rows"][0]["row"]
    row["field_observations"] = {"price": {"code": "US.A", "field": "price", "value": 10}}
    monkeypatch.setattr(api, "_market_client", lambda: ScreenProvider(("US.A",), price="0"))
    result = api.screener_execute("penny", "US", 300)
    a = result["rows"][0]
    assert a["price"] == 0 and a["display_field_sources"]["price"]["source"] == "provider_screen"
    assert "price" not in a["field_observations"]
    assert result["quote_generation_id"] == gid


@pytest.mark.parametrize("malformed", ["snapshot", "classification"])
def test_invalid_hydration_cannot_fill_from_wrong_identity(setup, monkeypatch, malformed):
    db, _ = setup
    publish(db)
    monkeypatch.setattr(api, "_market_client", lambda: ScreenProvider(malformed=malformed))
    result = api.screener_execute("penny", "US", 300)
    assert result["available"] and result["hydration_warnings"]
    outside = result["rows"][1]
    if malformed == "snapshot":
        assert outside["price"] is None
    else:
        assert outside.get("stock_type") is None and result["unclassified_count"] == 1


def test_execute_cache_and_later_page_pin_quote_cohort(setup, monkeypatch):
    db, _ = setup
    first = publish(db)
    monkeypatch.setattr(api, "_execute_cache", {})
    monkeypatch.setattr(api, "_market_client", lambda: ScreenProvider(("US.A",)))
    result = api.screener_execute("penny", "US", 300)
    result["rows"][0]["price"] = 999
    assert api.screener_execute("penny", "US", 300)["rows"][0]["price"] == 10
    second = publish(db, price=20)
    assert api.screener_execute("penny", "US", 300)["quote_generation_id"] == second
    old = api.screener_execute("penny", "US", 300, "page2", quote_generation_id=first)
    assert old["quote_generation_id"] == first and old["rows"][0]["price"] == 10
    db.tables["app_settings"][0]["value"]["last_quotes"] = "2000-01-01T00:00:00Z"
    with pytest.raises(HTTPException) as error:
        api.screener_execute("penny", "US", 300)
    assert error.value.status_code == 503


def test_invalid_provider_membership_is_not_silently_deduplicated(setup, monkeypatch):
    db, _ = setup
    publish(db)
    monkeypatch.setattr(api, "_execute_cache", {})
    monkeypatch.setattr(api, "_market_client", lambda: ScreenProvider(("US.A", "US.A")))
    result = api.screener_execute("penny", "US", 300)
    assert not result["available"] and result["rows"] == []


@pytest.mark.parametrize(
    "bad_results",
    [{}, [None], [{}], [{"value": 3}], [{"value": {"property": 3}}], [{"value": {"res": "wrong"}}]],
)
def test_malformed_criterion_records_fail_closed(setup, monkeypatch, bad_results):
    db, _ = setup
    publish(db)

    class Malformed(ScreenProvider):
        def call(self, method, path, body):
            return {"items": [{"code": "US.A", "results": bad_results}]}

    monkeypatch.setattr(api, "_execute_cache", {})
    monkeypatch.setattr(api, "_market_client", lambda: Malformed())
    result = api.screener_execute("penny", "US", 300)
    assert not result["available"] and result["rows"] == []
    assert result["reason"] == "Provider criterion response is invalid"


def test_malformed_pagination_is_not_a_complete_result(setup, monkeypatch):
    db, _ = setup
    publish(db)

    class Malformed(ScreenProvider):
        def call(self, method, path, body):
            return {"items": [{"code": "US.A", "results": []}], "pagination": []}

    monkeypatch.setattr(api, "_execute_cache", {})
    monkeypatch.setattr(api, "_market_client", lambda: Malformed())
    result = api.screener_execute("penny", "US", 300)
    assert not result["available"] and result["rows"] == []
    assert result["reason"] == "Provider pagination response is invalid"


@pytest.mark.parametrize(
    "metadata",
    [
        {"pagination": {"has_more": "false"}},
        {"pagination": {"next_key": {"page": 2}}},
        {"pagination": {"total": True}},
        {"pagination": {"total": 0}},
        {"pagination": {"next_key": "p2"}, "nextKey": "p3"},
        {"pagination": {"has_more": False}, "hasMore": True},
    ],
)
def test_invalid_paging_fields_do_not_authorize_membership_counts(setup, monkeypatch, metadata):
    db, _ = setup
    publish(db)

    class Malformed(ScreenProvider):
        def call(self, method, path, body):
            return {"items": [{"code": "US.A", "results": []}], **metadata}

    monkeypatch.setattr(api, "_execute_cache", {})
    monkeypatch.setattr(api, "_market_client", lambda: Malformed())
    result = api.screener_execute("penny", "US", 300)
    assert result == {
        "available": False,
        "rows": [],
        "reason": "Provider pagination response is invalid",
    }


@pytest.mark.parametrize(
    "metadata,available,truncated",
    [
        ({"pagination": {"total": 5}}, True, True),
        ({"pagination": {"total": 5, "has_more": False}}, False, None),
        ({"pagination": {"next_key": "p2", "has_more": False}}, False, None),
        ({"pagination": {"total": 1, "next_key": "-1", "has_more": False}}, True, False),
    ],
)
def test_provider_paging_completion_must_agree_with_count_and_cursor(
    setup, monkeypatch, metadata, available, truncated
):
    db, _ = setup
    publish(db)

    class Page(ScreenProvider):
        def call(self, method, path, body):
            return {"items": [{"code": "US.A", "results": []}], **metadata}

    monkeypatch.setattr(api, "_execute_cache", {})
    monkeypatch.setattr(api, "_market_client", lambda: Page())
    result = api.screener_execute("penny", "US", 300)
    assert result["available"] is available
    if available:
        assert result["possibly_truncated"] is truncated
        assert result["next_key"] is None
        assert result["provider_total"] == metadata["pagination"]["total"]
    else:
        assert result["rows"] == []
        assert result["reason"] == "Provider pagination response is inconsistent"


def test_missing_membership_array_is_not_an_empty_complete_screen(setup, monkeypatch):
    db, _ = setup
    publish(db)

    class Missing(ScreenProvider):
        def call(self, method, path, body):
            return {}

    monkeypatch.setattr(api, "_execute_cache", {})
    monkeypatch.setattr(api, "_market_client", lambda: Missing())
    result = api.screener_execute("penny", "US", 300)
    assert not result["available"] and result["rows"] == []


@pytest.mark.parametrize("initial", [None, "11111111-1111-4111-8111-111111111111"])
def test_provider_capture_pins_later_hydration_and_refuses_changed_cohort(
    setup, monkeypatch, initial
):
    calls = []

    def execute(key, market, limit, next_key="", **kwargs):
        calls.append((next_key, kwargs))
        return {
            "available": True,
            "rows": [],
            "quote_generation_id": initial
            if not next_key
            else "22222222-2222-4222-8222-222222222222",
            "possibly_truncated": not next_key,
            "next_key": "page2" if not next_key else None,
        }

    monkeypatch.setattr(api, "screener_execute", execute)
    with pytest.raises(HTTPException) as error:
        api.capture_screen_snapshot(api.ScreenDefinition(preset="penny"))
    assert error.value.status_code == 409 and "cohort changed" in error.value.detail
    assert calls == [("", {}), ("page2", {"quote_generation_id": initial} if initial else {})]
    assert not setup[0]._t("screen_captures")


def test_explicit_refresh_bypasses_provider_cache_but_preserves_quote_generation(
    setup, monkeypatch
):
    db, _ = setup
    gid = publish(db)
    provider = ScreenProvider(("US.A",), price="1000")
    calls = []
    original = provider.call

    def counted(method, path, body):
        calls.append(path)
        return original(method, path, body)

    provider.call = counted
    monkeypatch.setattr(api, "_execute_cache", {})
    monkeypatch.setattr(api, "_market_client", lambda: provider)
    assert api.screener_execute("penny", "US", 300)["rows"][0]["price"] == 1
    provider.price = "2000"
    assert api.screener_execute("penny", "US", 300)["rows"][0]["price"] == 1
    fresh = api.screener_execute("penny", "US", 300, refresh=True)
    assert fresh["rows"][0]["price"] == 2 and fresh["quote_generation_id"] == gid
    assert calls.count("/quote/stock-screen") == 2
