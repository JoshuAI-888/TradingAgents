"""Usage capture: the SDK-level recorder feeds runs.prompt/completion/cost."""

from types import SimpleNamespace

from tradingagents_worker import llm_usage

OR_CLIENT = SimpleNamespace(_client=SimpleNamespace(base_url="https://openrouter.ai/api/v1"))
OA_CLIENT = SimpleNamespace(_client=SimpleNamespace(base_url="https://api.openai.com/v1"))


def _fake_create(rec):
    def fake_create(self, *a, **kw):
        rec["kw"] = kw
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, cost=0.0002)
        )

    return fake_create


def test_recorder_totals_coerce_junk():
    llm_usage.RECORDER.reset()
    llm_usage.RECORDER.add(100, 50, 0.001)
    llm_usage.RECORDER.add("30", None, None)
    t = llm_usage.RECORDER.totals()
    assert t == {"calls": 2, "prompt": 130, "completion": 50, "cost_usd": 0.001}


def test_wrapper_records_usage_and_opts_into_cost():
    rec = {}
    w = llm_usage._wrap_create(_fake_create(rec))
    llm_usage.RECORDER.reset()
    resp = w(OR_CLIENT, model="m")
    assert resp.usage.prompt_tokens == 11
    assert rec["kw"]["extra_body"]["usage"] == {"include": True}
    assert llm_usage.RECORDER.totals() == {
        "calls": 1,
        "prompt": 11,
        "completion": 7,
        "cost_usd": 0.0002,
    }


def test_wrapper_no_injection_off_openrouter():
    rec = {}
    w = llm_usage._wrap_create(_fake_create(rec))
    llm_usage.RECORDER.reset()
    w(OA_CLIENT, model="m")
    assert "extra_body" not in rec["kw"]
    assert llm_usage.RECORDER.totals()["calls"] == 1


def test_wrapper_passes_through_no_usage():
    w = llm_usage._wrap_create(lambda self, *a, **kw: SimpleNamespace(usage=None))
    llm_usage.RECORDER.reset()
    assert w(OR_CLIENT, model="m").usage is None
    assert llm_usage.RECORDER.totals()["calls"] == 0


def test_install_is_idempotent(monkeypatch):
    from openai.resources.chat import completions as oc

    monkeypatch.setattr(oc.Completions, "create", _fake_create({}))
    assert llm_usage.install() is True
    wrapper = oc.Completions.create
    assert llm_usage.install() is True
    assert oc.Completions.create is wrapper


def test_callback_totals_from_llm_end():
    from types import SimpleNamespace as NS

    h = llm_usage.LLMUsageCallback()
    h.on_llm_end(NS(llm_output={"token_usage": {"prompt_tokens": 500, "completion_tokens": 120}}))
    h.on_llm_end(NS(llm_output={"token_usage": {"prompt_tokens": 300, "completion_tokens": 80}}))
    h.on_llm_end(NS(llm_output=None))  # tolerant of missing output
    assert h.totals() == {"calls": 3, "prompt": 800, "completion": 200}


def test_reconcile_prefers_best_source_and_estimates_cost(monkeypatch):
    monkeypatch.setattr(llm_usage, "estimate_cost", lambda m, p, c: 0.0025 if (p or c) else 0.0)
    # SDK went silent (the TSLA-run failure mode), callback saw everything.
    out = llm_usage.reconcile(
        {"calls": 0, "prompt": 0, "completion": 0, "cost_usd": 0.0},
        {"calls": 9, "prompt": 4000, "completion": 1000},
        "z-ai/glm-5.3-flash",
    )
    assert out == {"calls": 9, "prompt": 4000, "completion": 1000, "cost_usd": 0.0025}
    # SDK has real OpenRouter cost → it wins over the estimate.
    out2 = llm_usage.reconcile(
        {"calls": 9, "prompt": 4000, "completion": 1000, "cost_usd": 0.0069},
        {"calls": 9, "prompt": 4000, "completion": 1000},
        "z-ai/glm-5.3-flash",
    )
    assert out2["cost_usd"] == 0.0069
