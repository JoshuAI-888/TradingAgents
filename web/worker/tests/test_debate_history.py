"""Debate-transcript regression: 0.5.1 debate history is one accumulated
string; iterating it char-wise stored transcripts one character per line."""
from __future__ import annotations

from tradingagents_worker.runner import _join_history, demangle_debate

HISTORY_STR = (
    "Bull Analyst: #The Bull Case for VLVCY — cash flows keep compounding.\n"
    "Bear Analyst: #The Bear Case for VLVCY — debt wall in 2029."
)


def test_join_history_accepts_accumulated_string():
    out = _join_history(HISTORY_STR)
    assert out.startswith("Bull Analyst: #The Bull Case")
    assert "\n\n" not in out  # no per-char blank lines
    assert out.count("\n") == HISTORY_STR.count("\n")


def test_join_history_still_accepts_message_list():
    out = _join_history(["Bull Analyst: hi", {"content": "Bear Analyst: bye"}, ""])
    assert out == "Bull Analyst: hi\n\nBear Analyst: bye"


def mangle_like_the_old_writer(text: str) -> str:
    """Reproduce the pre-fix storage: every non-whitespace char became its own
    'message' (the p.strip() filter dropped spaces and newlines), blank-line joined."""
    return "\n\n".join(c for c in text if c.strip())


def test_demangle_repairs_char_wise_rows():
    mangled = mangle_like_the_old_writer(HISTORY_STR)
    assert demangle_debate(mangled) == "BullAnalyst:#TheBullCaseforVLVCY—cashflowskeepcompounding.BearAnalyst:#TheBearCaseforVLVCY—debtwallin2029."


def test_demangle_leaves_normal_transcripts_alone():
    assert demangle_debate(HISTORY_STR) == HISTORY_STR
    assert demangle_debate("") == ""
    assert demangle_debate("Bull\n\nBear\n\nshort") == "Bull\n\nBear\n\nshort"


def test_demangle_rejects_short_or_spaced_runs():
    # under the 40-token floor, or a 2-char token: leave untouched, don't guess
    assert demangle_debate(mangle_like_the_old_writer("ok!")) == mangle_like_the_old_writer("ok!")
    assert demangle_debate("a\n\nb\n\n" + "c\n\n" * 38 + "cd") == "a\n\nb\n\n" + "c\n\n" * 38 + "cd"
