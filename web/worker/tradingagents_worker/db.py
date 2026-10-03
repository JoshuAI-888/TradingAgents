"""Supabase access from the worker: service-role REST (PostgREST) — no ORM dependency.

Uses the service-role key which bypasses RLS. Only this process holds it.
"""

from __future__ import annotations

import json
from http.client import IncompleteRead
from urllib import error as _err, request as _rq
from urllib.parse import urlencode

from .config import SETTINGS


class Db:
    def __init__(self, url: str | None = None, key: str | None = None):
        self.url = (url or SETTINGS.supabase_url).rstrip("/")
        self.key = key or SETTINGS.supabase_service_key

    def _call(
        self,
        method: str,
        path: str,
        body: dict | list | None = None,
        query: dict | None = None,
        prefer: str | None = None,
    ) -> list | dict | None:
        qs = ("?" + urlencode(query)) if query else ""
        req = _rq.Request(
            f"{self.url}/rest/v1/{path}{qs}",
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                **({"Prefer": prefer} if prefer else {}),
            },
        )
        try:
            # Publication has a 45-second database budget; allow time for its receipt.
            timeout = (
                55
                if path in {"rpc/screener_refresh_publish", "rpc/screener_refresh_publish_staged"}
                else 30
            )
            with _rq.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except _err.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise RuntimeError(f"supabase {method} {path} -> {e.code}: {detail}") from e

    # ── jobs queue ────────────────────────────────────────────────────────
    def claim_job(self, worker_id: str, types: list[str] | None = None) -> dict | None:
        """Atomically claim one pending job via RPC (FOR UPDATE SKIP LOCKED)."""
        rows = (
            self._call(
                "POST",
                "rpc/claim_job",
                body={
                    "p_worker": worker_id,
                    "p_types": types,
                },
            )
            or []
        )
        cand = rows[0] if isinstance(rows, list) and rows else (rows or None)
        # An exhausted queue comes back as a null composite; some PostgREST
        # versions serialize that as an empty object instead of null.
        return cand if isinstance(cand, dict) and cand.get("id") else None

    def finish_job(
        self, job_id: str, status: str, error: str | None = None, run_id: str | None = None
    ):
        self._call(
            "PATCH",
            f"jobs?id=eq.{job_id}",
            body={
                "status": status,
                "last_error": error,
                **({"run_id": run_id} if run_id else {}),
                **({"finished_at": "now()"} if status != "running" else {}),
            },
        )

    def requeue_job(self, job_id: str, error: str):
        """Attempts < max_attempts -> back to pending; else failed."""
        self._call("POST", "rpc/requeue_job", body={"p_job": job_id, "p_error": error})

    def generation_rpc(self, name: str, body: dict):
        """Exact-replay refresh RPCs; retry an uncertain transport response once.

        The same UUID and JSON payload are retained. HTTP/SQL errors are not
        retried here; the job retry path may start a new fenced attempt.
        """
        if name not in {
            "screener_refresh_begin",
            "screener_refresh_renew",
            "screener_refresh_publish",
            "screener_refresh_stage",
            "screener_refresh_publish_staged",
            "screener_refresh_abort",
        }:
            raise ValueError("Unsupported generation RPC")
        # Reject non-JSON numbers before sending a publication request.
        json.dumps(body, allow_nan=False)
        for attempt in range(2):
            try:
                return self._call("POST", "rpc/" + name, body=body)
            except (
                _err.URLError,
                TimeoutError,
                ConnectionError,
                IncompleteRead,
                json.JSONDecodeError,
            ):
                if attempt:
                    raise

    # ── runs / events / decisions ─────────────────────────────────────────
    def insert(
        self, table: str, row: dict, prefer: str = "return=representation"
    ) -> list | dict | None:
        return self._call("POST", table, body=row, prefer=prefer)

    def upsert(self, table: str, on_conflict: str, row: dict) -> None:
        self._call(
            "POST",
            f"{table}?on_conflict={on_conflict}",
            body=row,
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def upsert_many(self, table: str, on_conflict: str, rows: list[dict], chunk: int = 400) -> int:
        """Bulk merge-duplicates upsert; returns the number of rows sent.
        Single-row upserts make a 9k-stock universe ~9k HTTP calls — this is ~24."""
        sent = 0
        for i in range(0, len(rows), chunk):
            batch = rows[i : i + chunk]
            self._call(
                "POST",
                f"{table}?on_conflict={on_conflict}",
                body=batch,
                prefer="resolution=merge-duplicates,return=minimal",
            )
            sent += len(batch)
        return sent

    def update(self, table: str, filter: str, row: dict) -> None:
        self._call("PATCH", f"{table}?{filter}", body=row)

    def delete(self, table: str, filter: str) -> None:
        self._call("DELETE", f"{table}?{filter}")

    def select(self, table: str, query: dict | None = None, columns: str = "*") -> list:
        q = {**(query or {}), "select": columns}
        out = self._call("GET", table, query=q)
        return out if isinstance(out, list) else []

    def select_all(
        self,
        table: str,
        query: dict | None = None,
        columns: str = "*",
        page: int = 1000,
        cap: int = 20000,
    ) -> list:
        """Read past PostgREST's default row cap by paging with limit/offset.
        Postgres row-level caps silently truncate big tables (a 5.8k-stock
        universe read back as 1000)."""
        base = {k: v for k, v in (query or {}).items() if k != "limit"}
        out: list = []
        offset = 0
        while offset < cap:
            rows = self.select(table, {**base, "limit": str(page), "offset": str(offset)}, columns)
            out.extend(rows)
            if len(rows) < page:
                return out
            offset += page
        return out

    # ── helper RPCs (installed by 0002) ──────────────────────────────────
    def requeue_rpc_exists(self) -> bool:
        try:
            self._call("GET", "rpc/claim_job", query={"p_worker": "__probe__", "p_types": None})
            return True
        except RuntimeError:
            return False
