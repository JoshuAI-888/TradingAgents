"""Repair debate rows stored by the pre-fix build (every word space stripped).

The old _join_history bug iterated the debate history char-wise, so stored rows
are single characters joined by blank lines — word spacing is unrecoverable
mechanically. The cheap LLM (same OpenRouter key as the digest) restores it:
each row is demangled to a letter stream, sliced into small chunks, and the
model re-inserts word boundaries (near-exact restorations accepted, gross
rewrites rejected). The untouched original is PRESERVED in content_original
(audit integrity: stored outputs are never silently rewritten), and a
debate_summary is folded into the run's digest so the report page opens with a
readable executive summary of the adversarial reviews. Idempotent: normal rows
and already-good repairs are skipped; a first repair that came back unreadable
(letter-spaced) is redone from content_original. Bounded per call — the worker
re-runs it at boot and after each job until the backlog is drained.
"""
from __future__ import annotations

import os
import time

from .db import Db

_CHUNK = 2000  # the echo must be verbatim; flash models start dropping text well above this
_MAX_ROWS_PER_PASS = 4


def is_legacy_row(content) -> bool:
    return (isinstance(content, str) and len(content) > 400 and " " not in content)


def _looks_unreadable(content) -> bool:
    """Letter-spaced form ('A g g r e s s i v e…') — a first repair that fed the
    model the raw \\n\\n-separated chars, so it spaced every letter. Still unreadable."""
    tokens = str(content or "").split()
    return len(tokens) > 40 and sum(len(t) for t in tokens) / len(tokens) < 1.8


def _repairable_row(row: dict) -> bool:
    content = row.get("content") or ""
    if row.get("content_original"):
        return _looks_unreadable(content)  # first repair produced junk: redo from the original
    return is_legacy_row(content)


def _chunks(text: str, cap: int = _CHUNK):
    start = 0
    while start < len(text):
        end = min(start + cap, len(text))
        if end < len(text):
            dot = text.rfind(".", start, end)
            if dot > start + cap // 2:
                end = dot + 1
        yield text[start:end]
        start = end


def _first_divergence(before: str, after: str) -> str:
    sb, sa = "".join(before.split()).lower(), "".join(after.split()).lower()
    i = next((k for k in range(min(len(sb), len(sa))) if sb[k] != sa[k]), min(len(sb), len(sa)))
    return f"at char {i}: ...{sb[max(0, i - 30):i + 30]!r} vs ...{sa[max(0, i - 30):i + 30]!r}"


def _similarity(before: str, after: str) -> float:
    from difflib import SequenceMatcher
    # autojunk=False: its default treats frequent letters as junk on long
    # sequences, collapsing real near-matches to ~0.02
    return SequenceMatcher(None, "".join(before.split()).lower(),
                           "".join(after.split()).lower(), autojunk=False).ratio()


# The model occasionally micro-corrects grammar ("trader says" -> "traders say").
# Chunks at >= ACCEPT_RATIO are accepted and the divergence logged; real content
# loss (dropped sentences) scores far below this and is rejected.
_ACCEPT_RATIO = 0.99


def _restore_spacing(client, text: str) -> str | None:
    _SYSTEM = (
        "You restore text whose word spaces were stripped by a storage bug. "
        "What you receive is a stream of letters with no word boundaries. "
        "Reconstruct the words and return the SAME text with single spaces "
        "between words. Copy every word, number, ticker and punctuation mark "
        "exactly — do NOT fix grammar or spelling, even where it looks wrong "
        "('trader says hold' must stay exactly 'trader says hold'). Add "
        "nothing, drop nothing, reorder nothing, explain nothing. Output text only."
    )
    from .runner import demangle_debate
    text = demangle_debate(text)  # raw form is chars joined by blank lines: collapse to a letter stream
    out: list[str] = []
    chunks = list(_chunks(text))
    for i, chunk in enumerate(chunks, 1):
        fixed = None
        for attempt in (1, 2, 3):  # a retry usually clears gross truncation
            t0 = time.monotonic()
            resp = client.chat.completions.create(
                model=_quick_model(), temperature=0, max_tokens=10000,
                messages=[{"role": "system", "content": _SYSTEM},
                          {"role": "user", "content": chunk}])
            fixed = (resp.choices[0].message.content or "").strip()
            finish = getattr(resp.choices[0], "finish_reason", None)
            print(f"[rehydrate] chunk {i}/{len(chunks)} attempt {attempt} ({len(chunk)} chars) -> "
                  f"{len(fixed)} chars in {time.monotonic() - t0:.0f}s (finish={finish})", flush=True)
            if not fixed:
                continue
            ratio = _similarity(chunk, fixed)
            if ratio == 1.0:
                break
            if ratio >= _ACCEPT_RATIO:
                print(f"[rehydrate] chunk {i} accepted at ratio {ratio:.4f} "
                      f"(micro-divergence: {_first_divergence(chunk, fixed)})", flush=True)
                break
            print(f"[rehydrate] chunk {i} attempt {attempt} rejected (ratio {ratio:.3f}): "
                  f"{_first_divergence(chunk, fixed)}", flush=True)
            fixed = None
        if not fixed:
            print(f"[rehydrate] chunk {i} failed after retries — row abandoned", flush=True)
            return None
        out.append(fixed)
    return "\n\n".join(out)


def _plausibly_same(before: str, after: str) -> bool:
    strip = lambda s: "".join(s.split()).lower()  # noqa: E731
    return strip(before) == strip(after)


def _quick_model() -> str:
    from .config import SETTINGS
    return SETTINGS.quick_model


def _client():
    from .digest import _client as _openrouter_client
    return _openrouter_client()


def _summarize_run(db: Db, run_id: str, client) -> None:
    """Fold a readable executive summary of the debates into the run's digest
    (the report page renders it as 'Adversarial review — summary')."""
    rows = db.select("run_digest", {"run_id": f"eq.{run_id}"}, "digest,model")
    if rows and (rows[0].get("digest") or {}).get("debate_summary"):
        return  # new-run digests already carry one
    debates = db.select("debate_messages", {"run_id": f"eq.{run_id}",
                                            "order": "created_at.asc"},
                        "debate_type,content")
    parts = []
    for m in debates:
        content = m.get("content") or ""
        if is_legacy_row(content):
            continue  # not repaired yet; summarize once it is
        parts.append(f"[{m['debate_type']} debate]\n{content[:6000]}")
    decisions = db.select("decisions", {"run_id": f"eq.{run_id}"}, "rating,signal")
    material = "\n\n".join(parts) + (f"\n\nFinal decision: {decisions[0]}" if decisions else "")
    if not parts:
        return
    resp = client.chat.completions.create(
        model=_quick_model(), temperature=0.2, max_tokens=400,
        messages=[
            {"role": "system", "content":
                "You are an equity-research editor. In one short plain-English "
                "paragraph (<=120 words, no bullets), summarize what the bull "
                "case argued, what the bear case argued, and how the risk debate "
                "resolved. Answer only from the material provided."},
            {"role": "user", "content": material}])
    summary = (resp.choices[0].message.content or "").strip()
    if not summary:
        return
    digest_value = (rows[0].get("digest") or {}) if rows else {}
    digest_value["debate_summary"] = summary[:1200]
    db.upsert("run_digest", "run_id", {"run_id": run_id, "digest": digest_value,
                                       **({"model": rows[0]["model"]} if rows and rows[0].get("model") else {})})


def rehydrate_debates(db: Db, max_rows: int = _MAX_ROWS_PER_PASS, client=None) -> int:
    """Repair up to max_rows unreadable debate rows per pass. Returns rows fixed."""
    if not os.getenv("OPENROUTER_API_KEY"):
        return 0
    try:
        rows = db.select("debate_messages", {"order": "created_at.desc", "limit": "400"},
                         "id,run_id,content,content_original")
    except Exception:
        return 0  # table/column not migrated yet
    backlog = [r for r in rows if _repairable_row(r)]
    backlog.sort(key=lambda r: len(r.get("content_original") or r.get("content") or ""))
    client = client or _client()
    if backlog:
        print(f"[rehydrate] {len(backlog)} unreadable debate row(s) in backlog; repairing up to {max_rows}", flush=True)
    fixed = 0
    for row in backlog[:max_rows]:
        try:
            source = row.get("content_original") or row["content"]  # redo case: repair the original again
            redo = bool(row.get("content_original"))
            print(f"[rehydrate] repairing row {row['id']} ({len(row['content'])} chars, "
                  f"run {str(row.get('run_id'))[:8]}{', redo' if redo else ''})", flush=True)
            restored = _restore_spacing(client, source)
            if not restored:
                continue
            db.update("debate_messages", f"id=eq.{row['id']}",
                      {"content": restored, "content_original": source})
            fixed += 1
            try:
                if redo:
                    # the first repair also summarized letter-spaced junk: regenerate
                    drows = db.select("run_digest", {"run_id": f"eq.{row['run_id']}"}, "digest,model")
                    if drows and (drows[0].get("digest") or {}).get("debate_summary"):
                        dv = drows[0]["digest"]
                        dv.pop("debate_summary", None)
                        db.update("run_digest", f"run_id=eq.{row['run_id']}", {"digest": dv})
                _summarize_run(db, row["run_id"], client)
            except Exception as e:
                print(f"debate summary (non-fatal): {e}", flush=True)
        except Exception as e:
            print(f"rehydrate row (non-fatal): {e}", flush=True)
    return fixed
