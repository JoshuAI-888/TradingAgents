"""Digest: robust JSON parse/coerce, one OpenRouter call, usage billed to the run."""

import json
from types import SimpleNamespace

from tradingagents_worker import digest

GOOD_JSON = {
    "evidence": [{"claim": "Data center capex up", "stage": "fundamentals", "support": "48% YoY"}],
    "scenarios": {
        "bull": {"thesis": "AI demand", "trigger": "beats", "range": "$220-240"},
        "base": {"thesis": "steady", "trigger": "inline", "range": "$180-200"},
        "bear": {"thesis": "squeeze", "trigger": "miss", "range": "$120-140"},
    },
    "news": [
        {"title": "Nvidia unveils", "class": "catalyst", "impact": "high", "why": "product launch"},
        {"title": "Probe opened", "class": "weird-value", "impact": "huge", "why": "x"},
    ],
    "qc": [
        {"stage": "analyst_market", "score": "88", "verdict": "solid"},
        {"stage": "trader", "score": 250, "verdict": "clamped"},
    ],
}


class FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.upserts, self.updates = [], []

    def select(self, table, query=None, columns="*"):
        return [dict(r) for r in self.rows.get(table, [])]

    def upsert(self, table, on_conflict, row):
        self.upserts.append((table, on_conflict, row))

    def update(self, table, filter, row):
        self.updates.append((table, filter, row))


def _rows():
    return {
        "runs": [
            {
                "id": "run-1",
                "ticker_id": "t",
                "quick_model": "z-ai/glm-5.3-flash",
                "deep_model": "x",
                "prompt_tokens": 100,
                "completion_tokens": 40,
                "cost_usd": 0.01,
            }
        ],
        "agent_reports": [
            {"stage": "analyst_market", "content_markdown": "report " * 100},
            {"stage": "portfolio_manager", "content_markdown": "final"},
        ],
        "debate_messages": [],
        "decisions": [
            {"rating": "Underweight", "signal": "sell", "price_target": None, "time_horizon": "12m"}
        ],
        "news_items": [
            {
                "title": "Nvidia unveils",
                "publisher": "R",
                "published_at": "2026-09-26",
                "summary": "s",
            }
        ],
    }


def _fake_client(content, usage=(500, 200, 0.0012)):
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1], cost=usage[2]),
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: resp))
    )
    return client, resp


def test_parse_and_norm_coerce():
    fenced = "Here you go:\n```json\n" + json.dumps(GOOD_JSON) + "\n```"
    d = digest._norm(digest._parse_json(fenced))
    assert d["evidence"][0]["stage"] == "fundamentals"
    assert d["news"][1]["class"] == "assumption" and d["news"][1]["impact"] == "medium"
    assert d["qc"][0]["score"] == 88 and d["qc"][1]["score"] == 100  # clamped
    assert set(d["scenarios"]) == {"bull", "base", "bear"}


def test_build_digest_stores_and_bills_usage(monkeypatch):
    db = FakeDb(_rows())
    client, _ = _fake_client(json.dumps(GOOD_JSON))
    monkeypatch.setattr(digest, "_client", lambda: client)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    out = digest.build_digest(db, "run-1", "NVDA")
    assert out["stored"] and out["evidence"] == 1 and out["qc"] == 2
    table, on_conflict, row = db.upserts[0]
    assert table == "run_digest" and on_conflict == "run_id" and row["run_id"] == "run-1"
    assert row["digest"]["scenarios"]["bull"]["range"] == "$220-240"
    t, f, patch = db.updates[0]
    assert t == "runs" and f == "id=eq.run-1"
    assert patch["prompt_tokens"] == 600 and patch["completion_tokens"] == 240
    assert patch["cost_usd"] == 0.0112


def test_build_digest_retries_bad_json(monkeypatch):
    db = FakeDb(_rows())
    good = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(GOOD_JSON)))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, cost=0.0),
    )
    bad = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="not json at all"))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, cost=0.0),
    )
    seq = iter([bad, good])
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: next(seq)))
    )
    monkeypatch.setattr(digest, "_client", lambda: client)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    out = digest.build_digest(db, "run-1", "NVDA")
    assert out["stored"]


def test_build_digest_no_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    out = digest.build_digest(FakeDb(_rows()), "run-1", "NVDA")
    assert not out["stored"] and "OPENROUTER" in out["reason"]
