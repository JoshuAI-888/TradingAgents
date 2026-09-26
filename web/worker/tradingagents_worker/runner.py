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
    """Real run via tradingagents 0.5.1. Requires an LLM key (see config)."""

    def __init__(self):
        from tradingagents.graph.trading_graph import TradingAgentsGraph  # noqa: F401
        self._graph = None

    def _ensure_graph(self, depth: str):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.default_config import DEFAULT_CONFIG
        import copy
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        for k, v in DEPTH_PRESETS[depth].items():
            cfg[k] = v
        cfg["llm_provider"] = SETTINGS.llm_provider
        cfg["quick_think_llm"] = SETTINGS.quick_model
        cfg["deep_think_llm"] = SETTINGS.deep_model
        cfg["data_cache_dir"] = SETTINGS.cache_dir
        cfg["results_dir"] = SETTINGS.results_dir
        # One graph per depth shape; reuse across runs is safe in 0.5.1.
        self._graph = TradingAgentsGraph(**{"config": cfg})
        return self._graph

    def run(self, ticker, trade_date, depth, instructions, emit, cancel=None):
        emit.emit("analysts", "progress", f"engine run starting ({SETTINGS.llm_provider})")
        ta = self._ensure_graph(depth)
        final_state, signal = ta.propagate(ticker, trade_date)
        if cancel is not None and cancel.is_set():
            raise Cancelled("cancelled by caller")
        reports = {
            "analysts": (final_state.get("market_report") or "") + "\n\n" + (final_state.get("sentiment_report") or ""),
            "research_debate": "\n\n".join(
                m.get("content", "") for m in (final_state.get("investment_debate_state") or {}).get("history", [])
            ),
            "trader": final_state.get("trader_investment_plan") or "",
            "risk_debate": "\n\n".join(
                m.get("content", "") for m in (final_state.get("risk_debate_state") or {}).get("history", [])
            ),
            "portfolio_manager": final_state.get("final_trade_decision") or "",
        }
        for st, md in reports.items():
            emit.stage_done(st, None, {"chars": len(md)})
        usage = getattr(ta, "cost_tracker", None)
        tok = {"prompt": getattr(usage, "prompt_tokens", 0) or 0,
               "completion": getattr(usage, "completion_tokens", 0) or 0,
               "cached": 0, "uncached": 0} if usage else {"prompt": 0, "completion": 0, "cached": 0, "uncached": 0}
        return {
            "signal": str(signal).lower(), "rating": str(signal), "is_review": str(signal).upper() == "REVIEW",
            "decision": {"rating": str(signal), "executive_summary": None,
                         "full_decision": {"raw": str(final_state.get("final_trade_decision", ""))[:20000]}},
            "reports": reports, "tokens": tok, "cost_usd": 0.0, "tool_calls": 0,
            "elapsed_seconds": None,
        }


def get_runner() -> Runner:
    return StubRunner() if SETTINGS.stub_mode else EngineRunner()
