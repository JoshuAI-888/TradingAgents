"""Run execution: wraps the TradingAgents engine behind a Runner protocol.

Two implementations:
  * StubRunner  — offline, deterministic, no network. Used by tests and as
                  the pipeline smoke test (ADR: offline-first discipline).
  * EngineRunner — imports tradingagents (0.5.1) and calls propagate().
                   Coarse stage events until node-level streaming lands.

Depth presets map to engine config knobs ( Debate rounds, analysts, news windows).
"""
from __future__ import annotations

import time
from typing import Protocol

from .config import SETTINGS
from .events import Emitter

DEPTH_PRESETS = {
    "fast":     {"max_debate_rounds": 0, "max_risk_discuss_rounds": 0, "selected_analysts": ["market", "fundamentals"]},
    "standard": {"max_debate_rounds": 1, "max_risk_discuss_rounds": 1},
    "deep":     {"max_debate_rounds": 3, "max_risk_discuss_rounds": 2},
}


class Cancelled(Exception):
    pass


class Runner(Protocol):
    def run(self, ticker: str, trade_date: str, depth: str, instructions: str | None,
            emit: Emitter, cancel: "threading.Event | None" = None) -> dict:
        """Returns {signal, rating, decision, reports{stage: md}, tokens, cost}."""
        ...


class StubRunner:
    """Deterministic offline run: validates the whole pipeline without an LLM key."""

    def run(self, ticker, trade_date, depth, instructions, emit, cancel=None):
        stages = ["analysts", "quality_gate", "research_debate", "research_manager",
                  "trader", "risk_debate", "portfolio_manager", "report_qc"]
        reports = {}
        for st in stages:
            if cancel is not None and cancel.is_set():
                raise Cancelled("cancelled by caller")
            time.sleep(0.05)
            emit.emit(st, "progress", f"stub: {st} complete")
            reports[st] = f"## {st}\nStub report for {ticker} @ {trade_date} (depth={depth})."
            if st == "quality_gate":
                emit.stage_done("quality_gate", "grades: A · B+ · A− · B", {"grades": {"market": "A", "sentiment": "B+"}})
        emit.stage_done("report_qc", "passed 4/4")
        return {
            "signal": "buy", "rating": "Buy", "is_review": False,
            "decision": {"rating": "Buy", "executive_summary": f"Stub decision for {ticker}",
                         "price_target": None, "time_horizon": "12m",
                         "full_decision": {"stub": True, "instructions": instructions}},
            "reports": reports,
            "tokens": {"prompt": 1200, "completion": 340, "cached": 700, "uncached": 500},
            "cost_usd": 0.0, "tool_calls": 3, "elapsed_seconds": 1,
        }


class EngineRunner:
    """Real run via tradingagents 0.5.1. Requires an LLM key (see config).

    The model pair resolves per run: DB app_settings ('models') → env defaults.
    """
    def __init__(self, model_pair_resolver=None):
        self._pair_resolver = model_pair_resolver or (lambda: {
            "provider": SETTINGS.llm_provider, "quick": SETTINGS.quick_model, "deep": SETTINGS.deep_model})
        self._graphs: dict[str, object] = {}

    def _ensure_graph(self, depth: str):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.default_config import DEFAULT_CONFIG
        import copy
        pair = self._pair_resolver()
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        for k, v in DEPTH_PRESETS[depth].items():
            cfg[k] = v
        cfg["llm_provider"] = pair["provider"]
        cfg["quick_think_llm"] = pair["quick"]
        cfg["deep_think_llm"] = pair["deep"]
        cfg["data_cache_dir"] = SETTINGS.cache_dir
        cfg["results_dir"] = SETTINGS.results_dir
        key = f"{pair['provider']}|{pair['quick']}|{pair['deep']}|{depth}"
        if key not in self._graphs:  # one graph per (models, depth) shape; reuse is safe in 0.5.1
            self._graphs[key] = TradingAgentsGraph(**{"config": cfg})
        return self._graphs[key]

    def run(self, ticker, trade_date, depth, instructions, emit, cancel=None):
        emit.emit("analysts", "progress", f"engine run starting ({SETTINGS.llm_provider})")
        from . import llm_usage
        llm_usage.install()
        llm_usage.RECORDER.reset()
        ta = self._ensure_graph(depth)
        started = time.monotonic()

        def on_node(node, delta):
            # Live per-agent progress for the Analyze page's reasoning trace.
            ev = node_event(node, delta or {}, time.monotonic() - started)
            if ev:
                emit.emit(ev[0], "progress", ev[1])

        final_state, signal = ta.propagate(ticker, trade_date, on_node=on_node)
        if cancel is not None and cancel.is_set():
            raise Cancelled("cancelled by caller")
        reports = {
            "analysts": (final_state.get("market_report") or "") + "\n\n" + (final_state.get("sentiment_report") or ""),
            "research_debate": _join_history((final_state.get("investment_debate_state") or {}).get("history")),
            "trader": final_state.get("trader_investment_plan") or "",
            "risk_debate": _join_history((final_state.get("risk_debate_state") or {}).get("history")),
            "portfolio_manager": final_state.get("final_trade_decision") or "",
        }
        for st, md in reports.items():
            emit.stage_done(st, None, {"chars": len(md)})
        # Framework cost_tracker misses OpenRouter traffic; the SDK-level recorder is authoritative.
        used = llm_usage.RECORDER.totals()
        tok = {"prompt": used["prompt"], "completion": used["completion"], "cached": 0, "uncached": 0}
        return {
            "signal": str(signal).lower(), "rating": str(signal), "is_review": str(signal).upper() == "REVIEW",
            "decision": {"rating": str(signal), "executive_summary": None,
                         "full_decision": {"raw": str(final_state.get("final_trade_decision", ""))[:20000]}},
            "reports": reports, "tokens": tok, "cost_usd": used["cost_usd"], "tool_calls": 0,
            "elapsed_seconds": None,
        }


def _join_history(items) -> str:
    """Debate history entries are plain strings in 0.5.1 (dicts in some forks) — accept both."""
    parts: list[str] = []
    for m in items or []:
        if isinstance(m, dict):
            parts.append(str(m.get("content") or m.get("message") or ""))
        elif m:
            parts.append(str(m))
    return "\n\n".join(p for p in parts if p.strip())


# Graph node → (trace stage, human label) for the live reasoning trace.
_NODE_LABELS = {
    "Market Analyst": ("analysts", "Market Analyst"),
    "Sentiment Analyst": ("analysts", "Sentiment Analyst"),
    "News Analyst": ("analysts", "News Analyst"),
    "Fundamentals Analyst": ("analysts", "Fundamentals Analyst"),
    "Bull Researcher": ("research_debate", "Bull researcher"),
    "Bear Researcher": ("research_debate", "Bear researcher"),
    "Research Manager": ("research_manager", "Research Manager"),
    "Trader": ("trader", "Trader"),
    "Aggressive Analyst": ("risk_debate", "Aggressive risk analyst"),
    "Neutral Analyst": ("risk_debate", "Neutral risk analyst"),
    "Conservative Analyst": ("risk_debate", "Conservative risk analyst"),
    "Risk Manager": ("risk_debate", "Risk Manager"),
    "Portfolio Manager": ("portfolio_manager", "Portfolio Manager"),
}
_NODE_SKIP = ("Msg Clear ", "tools_", "__end__")
_REPORT_KEYS = ("market_report", "sentiment_report", "news_report", "fundamentals_report")


def node_event(node: str, delta: dict, elapsed_s: float) -> tuple[str, str] | None:
    """Map a finished graph node to (stage, message) for the live trace; None to skip."""
    if node.startswith(_NODE_SKIP):
        return None
    stage, label = _NODE_LABELS.get(node, ("analysts", node.replace("_", " ").title()))
    extra = ""
    for key in _REPORT_KEYS:
        if delta.get(key):
            extra = f" · {len(str(delta[key])):,} chars"
            break
    return stage, f"{label} done · {elapsed_s:.0f}s in{extra}"


def get_runner(model_pair_resolver=None, stub_resolver=None) -> Runner:
    if stub_resolver is not None:
        return RuntimeRunner(model_pair_resolver, stub_resolver)
    return StubRunner() if SETTINGS.stub_mode else EngineRunner(model_pair_resolver)


class RuntimeRunner:
    """Picks stub or engine per run from a live flag (Settings toggle; env is the default)."""

    def __init__(self, model_pair_resolver=None, stub_resolver=None):
        self._pair_resolver = model_pair_resolver
        self._stub_resolver = stub_resolver or (lambda: SETTINGS.stub_mode)
        self._stub = StubRunner()
        self._engine: EngineRunner | None = None

    def run(self, ticker, trade_date, depth, instructions, emit, cancel=None):
        if self._stub_resolver():
            return self._stub.run(ticker, trade_date, depth, instructions, emit, cancel)
        if self._engine is None:
            self._engine = EngineRunner(self._pair_resolver)
        return self._engine.run(ticker, trade_date, depth, instructions, emit, cancel)
