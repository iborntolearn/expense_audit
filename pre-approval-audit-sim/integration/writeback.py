"""Decision write-back (mock, simulation only).

In a live deployment this calls the source T&E system's API (Tech Design 2.2).
In simulation there is no external system, so the write-back is logged and the
reviewer-action path is persisted. The source system remains the system of
record in live mode; here the logger stands in for it.
"""
from __future__ import annotations

import logging

from common.schemas import AuditDecisionWriteback
from data.interfaces import AuditStore

logger = logging.getLogger("integration.writeback")


class DecisionWriteback:
    def __init__(self, store: AuditStore):
        self._store = store

    def send(self, decision: AuditDecisionWriteback) -> None:
        logger.info(
            "writeback submission=%s decision=%s risk=%s rules=%s reviewer=%s",
            decision.submission_id,
            decision.decision.value,
            decision.risk_score,
            decision.rule_ids_triggered,
            decision.reviewer_id,
        )
        # Persist reviewer actions; interim pending_review is logged only.
        self._store.save_writeback(decision)
