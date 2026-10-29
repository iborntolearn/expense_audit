"""Minimal placeholder pipeline, retained for fast wiring/idempotency tests.

Like every pipeline it persists its own decision (write-through), so the ingest
service stays persistence-agnostic. The real pipeline is SequentialPipeline
(pipeline/sequential.py, via pipeline/factory.py).
"""
from __future__ import annotations

from common.schemas import AuditState, ReceiptRef, RoutingDecision, SubmissionCreatedEvent
from data.interfaces import AuditStore

_STUB_VERSION = "stub-0"


class StubPipeline:
    model_version = _STUB_VERSION
    rule_version = _STUB_VERSION

    def __init__(self, store: AuditStore):
        self._store = store

    def run(self, event: SubmissionCreatedEvent) -> AuditState:
        state = AuditState(submission_id=event.submission_id)
        state.raw_receipts = [
            ReceiptRef(line_id=line.line_id, blob_url=line.receipt_url)
            for line in event.report_lines
        ]
        state.risk_score = 0.5
        state.routing_decision = RoutingDecision.human_review
        state.explanation = "STUB pipeline: no agents; default human review."
        self._store.save_risk(
            state.submission_id,
            risk_score=state.risk_score,
            routing_decision=state.routing_decision,
            model_version=self.model_version,
            explanation=state.explanation,
        )
        return state


def build_pipeline(store: AuditStore) -> StubPipeline:
    return StubPipeline(store)
