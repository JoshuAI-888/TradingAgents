"""Live node-event mapping for the Analyze page's reasoning trace."""

from tradingagents_worker.runner import node_event


def test_known_nodes_map_to_trace_stages():
    assert node_event("Market Analyst", {"market_report": "x" * 120}, 42.4) == (
        "analysts",
        "Market Analyst done · 42s in · 120 chars",
    )
    assert node_event("Bull Researcher", {}, 10)[0] == "research_debate"
    assert node_event("Research Manager", {}, 10)[0] == "research_manager"
    assert node_event("Trader", {}, 3)[0] == "trader"
    assert node_event("Aggressive Analyst", {}, 5)[0] == "risk_debate"
    assert node_event("Portfolio Manager", {}, 8)[0] == "portfolio_manager"


def test_plumbing_nodes_are_skipped():
    assert node_event("Msg Clear Market", {}, 0.1) is None
    assert node_event("tools_market", {}, 0.1) is None
    assert node_event("__end__", {}, 0) is None


def test_unknown_nodes_pass_through_readable():
    stage, msg = node_event("Mystery_Node", {}, 5)
    assert stage == "analysts" and msg.startswith("Mystery Node done")


def test_no_report_delta_means_no_suffix():
    _, msg = node_event("Trader", {"unrelated": "x"}, 3)
    assert "chars" not in msg
