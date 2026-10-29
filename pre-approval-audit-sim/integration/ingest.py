"""Ingest service - the entry point for every submission (Milestone 3).

Responsibilities:
  * validate & accept a submission-created event
  * idempotency keyed on submission_id (Tech Design 3.4) - a duplicate delivery
    no-ops against the existing run
  * persist the submission
  * run the audit pipeline

The pipeline owns its own write-through persistence AND the decision write-back
(so the behaviour is identical whether the engine is the LangGraph graph, which
must emit pending_review then a final status, or the sequential fallback). Ingest
therefore stays engine-agnostic.
"""
from __future__ import annotations

import logging

from common.schemas import AuditState, SubmissionCreatedEvent
from data.interfaces import AuditStore
from pipeline.base import AuditPipeline

logger = logging.getLogger("integration.ingest")


class IngestResult:
    __slots__ = ("state", "accepted", "reason")

    def __init__(self, state: AuditState | None, accepted: bool, reason: str):
        self.state = state
        self.accepted = accepted  # False when idempotency short-circuited
        self.reason = reason


class IngestService:
    def __init__(
        self,
        store: AuditStore,
        pipeline: AuditPipeline,
        *,
        is_synthetic: bool,
    ):
        self._store = store
        self._pipeline = pipeline
        self._is_synthetic = is_synthetic

    def handle(self, event: SubmissionCreatedEvent) -> IngestResult:
        # 1. Idempotency: absorb webhook retries without a second audit run.
        if self._store.has_decision(event.submission_id):
            logger.info("idempotent no-op for %s (decision exists)", event.submission_id)
            return IngestResult(None, accepted=False, reason="already_processed")

        # 2. Persist the submission + receipt evidence pointers (must precede any
        #    line/decision writes: FK).
        self._store.save_submission(event, is_synthetic=self._is_synthetic)
        self._store.save_receipt_refs(
            event.submission_id,
            [(l.line_id, l.receipt_url) for l in event.report_lines],
        )
        self._store.save_report_lines(
            event.submission_id,
            [(l.line_id, l.category, l.entered_amount, event.currency)
             for l in event.report_lines],
        )

        # 3. Run the audit pipeline (persists node outputs and emits write-back).
        state = self._pipeline.run(event)
        logger.info(
            "processed %s -> %s", event.submission_id,
            state.routing_decision.value if state.routing_decision else "?",
        )
        return IngestResult(state, accepted=True, reason="processed")
