"""Per-run LLM usage capture.

The framework's cost_tracker only counts providers it hooks itself; OpenRouter
calls flow through the openai SDK (LangChain ChatOpenAI → Completions.create)
and were invisible, so runs recorded 0 tokens. We wrap the SDK's
Completions.create once per process and accumulate into a recorder that
EngineRunner drains after each run. OpenRouter's per-response cost is only
returned when the request opts in via extra_body {"usage": {"include": True}},
so the wrapper injects it for openrouter.ai traffic.
"""
from __future__ import annotations

import threading


class UsageRecorder:
    def __init__(self):
        self._lock = threading.Lock()
        self._reset()

    def _reset(self):
        self.calls = 0
        self.prompt = 0
        self.completion = 0
        self.cost_usd = 0.0

    def reset(self):
        with self._lock:
            self._reset()

    def add(self, prompt_tokens, completion_tokens, cost=0.0):
        with self._lock:
            self.calls += 1
            self.prompt += int(prompt_tokens or 0)
            self.completion += int(completion_tokens or 0)
            try:
                self.cost_usd += float(cost or 0.0)
            except (TypeError, ValueError):
                pass

    def totals(self) -> dict:
        with self._lock:
            return {"calls": self.calls, "prompt": self.prompt,
                    "completion": self.completion, "cost_usd": round(self.cost_usd, 6)}


RECORDER = UsageRecorder()
_installed = False


def _wrap_create(original):
    """Return a Completions.create replacement that records usage (and opts
    OpenRouter responses into per-call cost accounting)."""

    def _openrouter(client) -> bool:
        try:
            return "openrouter.ai" in str(client._client.base_url)
        except Exception:
            return False

    class _UsageStream:
        """Transparent stream wrapper that harvests usage from the final chunk."""

        def __init__(self, stream):
            self._stream = stream

        def __iter__(self):
            for chunk in self._stream:
                u = getattr(chunk, "usage", None)
                if u is not None:
                    RECORDER.add(getattr(u, "prompt_tokens", 0),
                                 getattr(u, "completion_tokens", 0),
                                 getattr(u, "cost", 0) or 0)
                yield chunk

        def __getattr__(self, name):
            return getattr(self._stream, name)

    def wrapped(client_self, *args, **kwargs):
        if _openrouter(client_self):
            extra = dict(kwargs.get("extra_body") or {})
            if "usage" not in extra:
                extra["usage"] = {"include": True}
            kwargs["extra_body"] = extra
        resp = original(client_self, *args, **kwargs)
        try:
            if kwargs.get("stream"):
                return _UsageStream(resp)
            u = getattr(resp, "usage", None)
            if u is not None:
                RECORDER.add(getattr(u, "prompt_tokens", 0),
                             getattr(u, "completion_tokens", 0),
                             getattr(u, "cost", 0) or 0)
        except Exception:
            pass
        return resp

    return wrapped


def install() -> bool:
    """Wrap openai SDK Completions.create to record usage. Idempotent; no-op if the SDK is absent."""
    global _installed
    if _installed:
        return True
    try:
        from openai.resources.chat import completions as oc
    except Exception:
        return False
    oc.Completions.create = _wrap_create(oc.Completions.create)
    _installed = True
    return True
