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
