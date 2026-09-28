"""Transcript repair: LLM-restored spacing for pre-fix debate rows, originals
preserved, debate summary folded into the run digest."""
from __future__ import annotations

from types import SimpleNamespace

from tradingagents_worker import rehydrate
from tradingagents_worker.rehydrate import (
    _chunks,
    _plausibly_same,
    is_legacy_row,
    rehydrate_debates,
)

MANGLED = ("BullAnalyst:" + "thebullcaserestsonmarginexpansionandpricingpower." * 12
           + "BearAnalyst:" + "thedebtwallin2029outweighsthebullcase." * 12)
RESTORED = ("Bull Analyst: " + "the bull case rests on margin expansion and pricing power. " * 12
            + "Bear Analyst: " + "the debt wall in 2029 outweighs the bull case. " * 12)


class _FakeCompletions:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply))])


def _fake_client(reply=None):
    return SimpleNamespace(chat=SimpleNamespace(
        completions=_FakeCompletions(reply if reply is not None else RESTORED)))


def _seed(db):
    db._t("debate_messages").append({"id": "dm-legacy", "run_id": "run-1",
                                     "debate_type": "research", "content": MANGLED})
    db._t("debate_messages").append({"id": "dm-ok", "run_id": "run-1",
                                     "debate_type": "risk", "content": "Aggressive Analyst: spaced text here. " * 40})
    db._t("run_digest").append({"run_id": "run-1", "model": "z-ai/glm-5.3-flash",
                                "digest": {"qc": []}})
    db._t("decisions").append({"run_id": "run-1", "rating": "hold", "signal": "hold"})


def test_legacy_detector_and_sanity():
    assert is_legacy_row(MANGLED) and not is_legacy_row("normal spaced text " * 40)
    assert _plausibly_same("AB cdef.", "ab CD ef . ")
    assert not _plausibly_same("abcdef", "abcxef")
    assert list(_chunks("a" * 50, cap=20)) == ["a" * 20, "a" * 20, "a" * 10]


def test_rehydrate_restores_preserves_and_summarizes(monkeypatch, fake_db):
    _seed(fake_db)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    client = _fake_client()
    fixed = rehydrate_debates(fake_db, client=client)
    assert fixed == 1
    rows = {r["id"]: r for r in fake_db.select("debate_messages", {}, "id,content,content_original")}
    assert rows["dm-legacy"]["content"].startswith("Bull Analyst: the bull case rests")
    assert rows["dm-legacy"]["content_original"] == MANGLED      # untouched original kept
    assert rows["dm-ok"].get("content_original") is None        # normal row untouched
    # debate summary folded into the run's digest
    digest = fake_db.select("run_digest", {"run_id": "eq.run-1"}, "digest")[0]["digest"]
    assert digest["debate_summary"] == RESTORED.strip()[:1200]
    assert client.chat.completions.calls[0]["messages"][1]["content"].startswith("BullAnalyst:")


def test_rehydrate_skips_already_repaired(monkeypatch, fake_db):
    _seed(fake_db)
    fake_db._t("debate_messages")[0]["content_original"] = MANGLED  # already done
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    client = _fake_client()
    assert rehydrate_debates(fake_db, client=client) == 0
    assert client.chat.completions.calls == []


def test_rehydrate_rejects_rewrites(monkeypatch, fake_db):
    _seed(fake_db)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    client = _fake_client(reply="Totally different text the model invented.")
    assert rehydrate_debates(fake_db, client=client) == 0
    row = fake_db.select("debate_messages", {"id": "eq.dm-legacy"}, "content,content_original")[0]
    assert row["content"] == MANGLED and not row.get("content_original")


def test_rehydrate_needs_key(fake_db, monkeypatch):
    _seed(fake_db)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert rehydrate_debates(fake_db, client=_fake_client()) == 0


def test_digest_norm_carries_debate_summary():
    from tradingagents_worker.digest import _norm
    out = _norm({"debate_summary": "Bull said grow, bear said debt.", "qc": []})
    assert out["debate_summary"] == "Bull said grow, bear said debt."
    assert _norm({})["debate_summary"] == ""
