"""Repair debate rows stored by the pre-fix build (every word space stripped).

The old _join_history bug iterated the debate history char-wise, so stored rows
are one unbroken character stream — spacing is unrecoverable mechanically. The
cheap LLM (same OpenRouter key as the digest) restores it well: this restores
spacing chunk-by-chunk, PRESERVES the original in content_original (audit
integrity: stored outputs are never silently rewritten), and while it is at it
writes a debate_summary into the run's digest so the report page can open with
a readable executive summary of the adversarial reviews. Idempotent: rows with
content_original set, or with normal spacing, are skipped. Bounded per call —
the worker re-runs it after each job until the backlog is drained.
"""
from __future__ import annotations

from .db import Db

_CHUNK = 7000
_MAX_ROWS_PER_PASS = 4


def is_legacy_row(content) -> bool:
    return (isinstance(content, str) and len(content) > 400 and " " not in content)


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


def _restore_spacing(client, text: str) -> str | None:
    _SYSTEM = (
        "You restore text whose word spaces were stripped by a storage bug. "
        "Return the SAME text with single spaces restored between words. Copy "
        "every word, number, ticker and punctuation mark exactly — add nothing, "
        "drop nothing, reorder nothing, explain nothing. Output text only."
    )
    out: list[str] = []
    for chunk in _chunks(text):
        resp = client.chat.completions.create(
            model=_quick_model(), temperature=0, max_tokens=10000,
            messages=[{"role": "system", "content": _SYSTEM},
                      {"role": "user", "content": chunk}])
        fixed = (resp.choices[0].message.content or "").strip()
        # sanity: restoration only ever adds spaces — reject wild rewrites
        if not fixed or not _plausibly_same(chunk, fixed):
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


def _summarize_run(db: Db, run_id: str) -> None:
    """Fold a readable executive summary of the debates into the run's digest
    (the report page renders it as 'Adversarial review — summary')."""
    rows = db.select("run_digest", {"run_id": f"eq.{run_id}"}, "digest")
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
    resp = _client().chat.completions.create(
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
    """Repair up to max_rows legacy debate rows per pass. Returns rows fixed."""
    try:
        if not __import__("os").getenv("OPENROUTER_API_KEY"):
            return 0
    except Exception:
        return 0
    try:
        rows = db.select("debate_messages", {"order": "created_at.desc", "limit": "400"},
                         "id,run_id,content,content_original")
    except Exception:
        return 0  # table/column not migrated yet
    legacy = [r for r in rows if is_legacy_row(r.get("content")) and not r.get("content_original")]
    client = client or _client()
    fixed = 0
    for row in legacy[:max_rows]:
        try:
            restored = _restore_spacing(client, row["content"])
            if not restored:
                continue
            db.update("debate_messages", f"id=eq.{row['id']}",
                      {"content": restored, "content_original": row["content"]})
            fixed += 1
            try:
                _summarize_run(db, row["run_id"])
            except Exception as e:
                print(f"debate summary (non-fatal): {e}", flush=True)
        except Exception as e:
            print(f"rehydrate row (non-fatal): {e}", flush=True)
    return fixed
