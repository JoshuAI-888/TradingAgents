"""Post-run digest: evidence register, scenario/sensitivity table, news
classification, per-agent QC grades — the structured layer the report dossier
renders. One small LLM call over the stored run artifacts, upserted as JSON in
run_digest. Never fails the job: any error is logged and swallowed upstream.
"""
from __future__ import annotations

import json
import os
import re

from .config import SETTINGS

_SYSTEM = (
    "You are an institutional equity-research editor. You answer ONLY from the "
    "material provided — never invent numbers, tickers or facts. If material is "
    "missing, omit that item. Output a single JSON object, no prose, no code fences."
)

_SCHEMA = """{
  "evidence": [{"claim": "...", "stage": "market|news|social|fundamentals|research|risk", "support": "short quote or figure"}],
  "scenarios": {
    "bull": {"thesis": "...", "trigger": "...", "range": "fair-value band, e.g. $68-72"},
    "base": {"thesis": "...", "trigger": "...", "range": "..."},
    "bear": {"thesis": "...", "trigger": "...", "range": "..."}
  },
  "news": [{"title": "...", "class": "catalyst|risk|assumption", "impact": "high|medium|low", "why": "..."}],
  "qc": [{"stage": "...", "score": 0-100, "verdict": "one line"}]
}
Rules: evidence <= 8 items, the load-bearing claims behind the decision; news
covers only the items listed; qc scores each supplied stage report on
evidence quality, internal consistency and bias, 0-100; ranges are strings."""


def _clip(s: str | None, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + " …[truncated]"


def _client():
    from openai import OpenAI
    return OpenAI(api_key=os.environ["OPENROUTER_API_KEY"],
                  base_url="https://openrouter.ai/api/v1", timeout=120, max_retries=1)


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in response")
    return json.loads(text[start:end + 1])


def _norm(d: dict) -> dict:
    """Coerce the model's JSON to the portal's shape; never trust it blindly."""
    out = {"evidence": [], "scenarios": {}, "news": [], "qc": []}
    for ev in (d.get("evidence") or [])[:8]:
        if isinstance(ev, dict) and ev.get("claim"):
            out["evidence"].append({
                "claim": str(ev["claim"])[:300],
                "stage": str(ev.get("stage") or "research").lower(),
                "support": str(ev.get("support") or "")[:300]})
    sc = d.get("scenarios") or {}
    for k in ("bull", "base", "bear"):
        v = sc.get(k)
        if isinstance(v, dict) and (v.get("thesis") or v.get("range")):
            out["scenarios"][k] = {"thesis": str(v.get("thesis") or "")[:300],
                                   "trigger": str(v.get("trigger") or "")[:200],
                                   "range": str(v.get("range") or "")[:80]}
    for it in (d.get("news") or [])[:12]:
        if isinstance(it, dict) and it.get("title"):
            cls = str(it.get("class") or "assumption").lower()
            imp = str(it.get("impact") or "medium").lower()
            out["news"].append({
                "title": str(it["title"])[:220],
                "class": cls if cls in ("catalyst", "risk", "assumption") else "assumption",
                "impact": imp if imp in ("high", "medium", "low") else "medium",
                "why": str(it.get("why") or "")[:220]})
    for q in (d.get("qc") or [])[:8]:
        if isinstance(q, dict) and q.get("stage"):
            try:
                score = max(0, min(100, int(q.get("score") or 0)))
            except (TypeError, ValueError):
                score = 0
            out["qc"].append({"stage": str(q["stage"])[:60], "score": score,
                              "verdict": str(q.get("verdict") or "")[:200]})
    return out


def build_digest(db, run_id: str, ticker: str) -> dict:
    """Generate + store the digest for a stored run. Returns {"stored": bool, ...}."""
    if not os.getenv("OPENROUTER_API_KEY"):
        return {"stored": False, "reason": "no OPENROUTER_API_KEY"}
    runs = db.select("runs", {"id": f"eq.{run_id}"},
                     "id,ticker_id,quick_model,deep_model,prompt_tokens,completion_tokens,cost_usd")
    if not runs:
        return {"stored": False, "reason": "run not found"}
    run = runs[0]
    reports = db.select("agent_reports", {"run_id": f"eq.{run_id}", "order": "created_at.asc"},
                        "stage,content_markdown")
    debates = db.select("debate_messages", {"run_id": f"eq.{run_id}", "order": "created_at.asc"},
                        "debate_type,speaker,round,content")
    decision = db.select("decisions", {"run_id": f"eq.{run_id}"}, "rating,signal,price_target,time_horizon")
    news = db.select("news_items", {"tickers": f'cs.{{"{ticker}"}}', "order": "published_at.desc"},
                     "title,publisher,published_at,summary")

    parts = [f"Ticker: {ticker}",
             f"Decision: {json.dumps(decision[0]) if decision else 'none'}",
             "=== Stage reports ==="]
    for r in reports:
        cap = 9000 if r["stage"] == "portfolio_manager" else 4500
        parts.append(f"--- {r['stage']} ---\n{_clip(r['content_markdown'], cap)}")
    if debates:
        parts.append("=== Debate excerpts ===")
        for m in debates[:6]:
            parts.append(f"[{m['debate_type']} r{m['round']}] {_clip(m['content'], 1200)}")
    if news:
        parts.append("=== Recent news ===")
        for n in news[:12]:
            parts.append(f"- {n['title']} ({n.get('publisher') or 'unknown'}, {str(n['published_at'])[:10]})"
                         + (f" — {_clip(n.get('summary'), 160)}" if n.get("summary") else ""))
    material = "\n".join(parts)

    model = run.get("quick_model") or SETTINGS.quick_model
    client = _client()
    messages = [{"role": "system", "content": _SYSTEM},
                {"role": "user", "content": material + "\n\nReturn JSON exactly in this schema:\n" + _SCHEMA}]
    usage_total = {"prompt": 0, "completion": 0, "cost": 0.0}

    def _acc(r):
        u = getattr(r, "usage", None)
        if u is not None:
            usage_total["prompt"] += int(getattr(u, "prompt_tokens", 0) or 0)
            usage_total["completion"] += int(getattr(u, "completion_tokens", 0) or 0)
            usage_total["cost"] += float(getattr(u, "cost", 0) or 0)

    resp = client.chat.completions.create(
        model=model, temperature=0.2, max_tokens=2000, messages=messages,
        extra_body={"usage": {"include": True}})
    _acc(resp)
    text = resp.choices[0].message.content or ""
    try:
        digest = _norm(_parse_json(text))
    except Exception:
        retry = client.chat.completions.create(
            model=model, temperature=0, max_tokens=2000,
            messages=messages + [{"role": "assistant", "content": text[:800]},
                                 {"role": "user", "content": "That was not valid JSON per the schema. Return ONLY the JSON object."}],
            extra_body={"usage": {"include": True}})
        _acc(retry)
        text = retry.choices[0].message.content or ""
        digest = _norm(_parse_json(text))

    db.upsert("run_digest", "run_id", {"run_id": run_id, "digest": digest, "model": model})

    # Fold the digest call's own usage into the run's totals.
    if usage_total["prompt"] or usage_total["completion"]:
        db.update("runs", f"id=eq.{run_id}", {
            "prompt_tokens": (run.get("prompt_tokens") or 0) + usage_total["prompt"],
            "completion_tokens": (run.get("completion_tokens") or 0) + usage_total["completion"],
            "cost_usd": round(float(run.get("cost_usd") or 0) + usage_total["cost"], 4)})
    return {"stored": True, "evidence": len(digest["evidence"]),
            "scenarios": len(digest["scenarios"]), "news": len(digest["news"]),
            "qc": len(digest["qc"])}
