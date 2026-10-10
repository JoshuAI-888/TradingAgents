"""RPC orchestration double only; native SQL tests prove the storage contract."""

import copy
from datetime import datetime, timedelta, timezone

from conftest import FakeSupa
from tradingagents_worker.universe_refresh import cohort_fingerprint


class GenerationDb(FakeSupa):
    def __init__(self):
        super().__init__()
        self.leases = {}
        self.receipts = {}
        self.staged = {}
        self.rpc_calls = []

    def generation_rpc(self, name, body):
        self.rpc_calls.append((name, copy.deepcopy(body)))
        if name == "screener_refresh_capacity":
            return {
                "version": "screener_capacity_v2",
                "market": body["p_market"],
                "used_bytes": 0,
                "limit_bytes": 450000000,
                "reserved_bytes": 0,
                "required_bytes": 150000000 if body["p_market"] == "US" else 50000000,
                "allowed": True,
                "relation_bytes": {"generation_rows": 0, "staged_rows": 0, "generations": 0},
            }
        market, token = body["p_market"], body["p_run"]
        now = datetime.now(timezone.utc).isoformat()
        state_rows = self.select("app_settings", {"key": f"eq.universe_state_{market}"})
        state = copy.deepcopy(state_rows[0]["value"]) if state_rows else {}
        lease = self.leases.get(market)
        if name == "screener_refresh_begin":
            if lease and lease["active"]:
                if lease["run_id"] == token:
                    return {k: v for k, v in lease.items() if k != "active"}
                raise RuntimeError("market lease already owned")
            lease = {
                "run_id": token,
                "market": market,
                "started_at": now,
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
                "base_generation_id": state.get("generation_id"),
                "active": True,
            }
            self.leases[market] = lease
            state["last_attempt"] = {"run_id": token, "started_at": now, "status": "running"}
        elif name == "screener_refresh_renew":
            if not lease or not lease["active"] or lease["run_id"] != token:
                raise RuntimeError("refresh expired or superseded")
            return lease["expires_at"]
        elif name == "screener_refresh_stage":
            if not lease or not lease["active"] or lease["run_id"] != token:
                raise RuntimeError("refresh expired or superseded")
            batch = body["p_rows"]
            assert 0 < len(batch) <= 400
            staged = self.staged.setdefault(token, {})
            for item in batch:
                if item["code"] in staged and staged[item["code"]] != item:
                    raise RuntimeError("conflicting staged row")
                staged[item["code"]] = copy.deepcopy(item)
            return {"run_id": token, "market": market, "staged": len(batch)}
        elif name in {"screener_refresh_publish", "screener_refresh_publish_staged"}:
            if name == "screener_refresh_publish_staged":
                staged = self.staged.get(token, {})
                if set(staged) != set(body["p_codes"]):
                    raise RuntimeError("incomplete staged cohort")
                body = {**body, "p_rows": [staged[code] for code in body["p_codes"]]}
            if token in self.receipts:
                payload, receipt = self.receipts[token]
                if payload != body:
                    raise RuntimeError("conflicting replay")
                return copy.deepcopy(receipt)
            if not lease or not lease["active"] or lease["run_id"] != token:
                raise RuntimeError("refresh expired or superseded")
            items = body["p_rows"]
            count = len(items)
            fingerprint = cohort_fingerprint(body["p_codes"])
            result = {
                **body["p_result"],
                "market": market,
                "quotes": {
                    "quotes": count,
                    "requested": count,
                    "batches": (count + 399) // 400,
                    "cohort_fingerprint": fingerprint,
                    "scope": "requested_stored_universe",
                },
            }
            header = {
                "id": token,
                "market": market,
                "started_at": lease["started_at"],
                "published_at": now,
                "row_count": count,
                "cohort_fingerprint": fingerprint,
                "result": result,
            }
            self._t("screener_generations").append(header)
            for item in items:
                self._t("screener_generation_rows").append(
                    {"generation_id": token, **copy.deepcopy(item)}
                )
                self.upsert("screener_universe", "market,code", copy.deepcopy(item["metadata"]))
                self.upsert(
                    "screener_quotes",
                    "code",
                    {
                        "code": item["code"],
                        "market": market,
                        "row": copy.deepcopy(item["row"]),
                        "updated_at": item["quote_cache_at"],
                    },
                )
            state.update(
                {
                    "generation_id": token,
                    "last_quotes": now,
                    "last_result": result,
                    "last_attempt": {"run_id": token, "status": "succeeded", "finished_at": now},
                }
            )
            if body["p_enumerated"]:
                state["last_enum"] = now
            receipt = {
                "generation_id": token,
                "market": market,
                "published_at": now,
                "row_count": count,
                "cohort_fingerprint": fingerprint,
                "result": result,
            }
            self.receipts[token] = (copy.deepcopy(body), copy.deepcopy(receipt))
            lease["active"] = False
        elif name == "screener_refresh_abort":
            if not lease or not lease["active"] or lease["run_id"] != token:
                return False
            state["last_attempt"] = {
                "run_id": token,
                "started_at": lease["started_at"],
                "finished_at": now,
                "status": "failed",
                "stage": body["p_stage"],
                "reason": body["p_reason"],
            }
            lease["active"] = False
        else:
            raise AssertionError(name)
        self.upsert("app_settings", "key", {"key": f"universe_state_{market}", "value": state})
        if name == "screener_refresh_begin":
            return {k: v for k, v in lease.items() if k != "active"}
        if name in {"screener_refresh_publish", "screener_refresh_publish_staged"}:
            return receipt
        return True
