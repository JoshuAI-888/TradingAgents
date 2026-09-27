"""Event emission: every pipeline happening lands in job_events (Realtime feed).

Stage naming matches the portal's pipeline visualization.
"""
from __future__ import annotations

from .db import Db

STAGES = [
    ("analysts", "Analyst team (parallel)"),
    ("quality_gate", "Quality gate"),
    ("research_debate", "Bull vs Bear"),
    ("research_manager", "Research manager"),
    ("trader", "Trader"),
    ("risk_debate", "Risk debate"),
    ("portfolio_manager", "Portfolio manager"),
    ("report_qc", "Report QC"),
]


class Emitter:
    def __init__(self, db: Db, job_id: str):
        self.db = db
        self.job_id = job_id
        # Continue the job's event numbering across re-attempts: a retry that
        # restarts at 1 collides with the previous attempt's rows and scrambles
        # every order-by-seq reader (live trace, report dossier). Best-effort:
        # if the max-seq read fails, number from 1 rather than block the job.
        try:
            rows = db.select("job_events", {"job_id": f"eq.{job_id}", "order": "seq.desc", "limit": "1"}, "seq")
            self._seq = int(rows[0]["seq"] or 0) if rows else 0
        except Exception:
            self._seq = 0

    def emit(self, stage: str, status: str, message: str | None = None, payload: dict | None = None):
        self._seq += 1
        self.db.insert("job_events", {
            "job_id": self.job_id,
            "seq": self._seq,
            "stage": stage,
            "status": status,
            "message": message,
            "payload": payload or {},
        }, prefer="return=minimal")

    def stage_done(self, stage: str, message: str | None = None, payload: dict | None = None):
        self.emit(stage, "done", message, payload)
