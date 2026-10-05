"""The chart and the debates must argue over the same numbers.

The portal worker computes a verified as-of market snapshot at run start and
puts it on the state as ``price_context``; every debate and synthesis prompt
renders it, and the report chart serves the same rows. These tests pin the
plumbing: the state field exists, every debate/synthesis template carries the
slot, and a node's rendered prompt contains the snapshot text.
"""

from __future__ import annotations

SNAPSHOT = "## Verified market data snapshot for NVDA\n\n| Close | 178.05 |"


def test_every_debate_and_synthesis_prompt_has_a_price_context_slot():
    from tradingagents.agents.prompt_texts import AGENT_PROMPTS

    for key in ("bull_researcher", "bear_researcher", "research_manager", "trader",
                "aggressive_analyst", "conservative_analyst", "neutral_analyst",
                "portfolio_manager"):
        assert "{price_context}" in AGENT_PROMPTS[key], f"{key} has no price_context slot"
    # Analysts gather their own data via tools; they deliberately get no slot.
    for key in ("market_analyst", "sentiment_analyst", "news_analyst", "fundamentals_analyst"):
        assert "{price_context}" not in AGENT_PROMPTS[key], f"{key} should not carry price_context"


def test_initial_state_carries_the_price_context():
    from tradingagents.graph.propagation import Propagator

    state = Propagator().create_initial_state("NVDA", "2026-09-30", price_context=SNAPSHOT)
    assert state["price_context"] == SNAPSHOT
    assert Propagator().create_initial_state("NVDA", "2026-09-30")["price_context"] == ""


def _llm_capturing_prompt():
    from langchain_core.messages import AIMessage

    seen = []

    class _LLM:
        def invoke(self, prompt, *a, **k):
            seen.append(prompt if isinstance(prompt, str) else str(prompt))
            return AIMessage("argument")

    return _LLM(), seen


def _base_state():
    return {
        "company_of_interest": "NVDA", "trade_date": "2026-09-30", "asset_type": "stock",
        "instrument_context": "", "portfolio_context": "", "past_context": "",
        "market_report": "RSI 61, price 178.", "sentiment_report": "", "news_report": "",
        "fundamentals_report": "", "investment_plan": "P", "trader_investment_plan": "T",
        "investment_debate_state": {"bull_history": "", "bear_history": "", "history": "",
                                    "current_response": "", "judge_decision": "", "count": 0},
        "risk_debate_state": {"history": "", "latest_speaker": "", "count": 0,
                              "aggressive_history": "", "conservative_history": "", "neutral_history": "",
                              "current_aggressive_response": "", "current_conservative_response": "",
                              "current_neutral_response": "", "judge_decision": ""},
    }


def test_debate_nodes_render_the_verified_snapshot_into_their_prompt():
    from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
    from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
    from tradingagents.agents.risk_mgmt.aggressive_debator import create_aggressive_debator

    for factory, state in (
        (create_bull_researcher, {**_base_state(), "price_context": SNAPSHOT}),
        (create_bear_researcher, {**_base_state(), "price_context": SNAPSHOT}),
        (create_aggressive_debator, {**_base_state(), "price_context": SNAPSHOT}),
    ):
        llm, seen = _llm_capturing_prompt()
        factory(llm)(state)
        assert seen, "no prompt captured"
        assert SNAPSHOT in seen[0]


def test_debates_without_a_snapshot_render_cleanly():
    """Entry points that don't compute the snapshot (CLI, tests) keep working:
    the slot renders as nothing, never as 'None' or a KeyError."""
    from tradingagents.agents.researchers.bull_researcher import create_bull_researcher

    llm, seen = _llm_capturing_prompt()
    create_bull_researcher(llm)(_base_state())
    assert seen
    assert "None" not in seen[0]
    assert "{price_context}" not in seen[0]  # missing kwarg must not leave the placeholder
