"""SequentialPipeline - the real agent pipeline (Phase 2).

Chains extraction -> verification -> policy -> risk, each wrapped by the
resilience runtime (timeout, retry, fail-open) and each write-through persisted
as it completes. This implements the AuditPipeline seam, so it drops into the
integration layer in place of StubPipeline with no caller change.

Phase 3 replaces this with a LangGraph pipeline that adds checkpointing and the
conditional human-review edge - reusing the same agents and the same runtime.
"""
from __future__ import annotations

import logging

from datetime import datetime, timezone

from common.schemas import (
    AuditDecisionWriteback,
    AuditState,
    DecisionStatus,
    ReceiptRef,
    RoutingDecision,
    SubmissionCreatedEvent,
)
from data.interfaces import AuditStore
from integration.writeback import DecisionWriteback
from pipeline.agents.extraction import ExtractionAgent
from pipeline.agents.policy import PolicyAgent
from pipeline.agents.risk import RiskAgent
from pipeline.agents.verification import VerificationAgent
from pipeline.config import PipelineConfig
from pipeline.runtime import run_node_logged
from pipeline.summaries import (
    summarize_extraction,
    summarize_policy,
    summarize_risk,
    summarize_verification,
)

_ROUTING_TO_STATUS = {
    RoutingDecision.auto_approve: DecisionStatus.approved,
    RoutingDecision.auto_reject: DecisionStatus.rejected,
    RoutingDecision.human_review: DecisionStatus.pending_review,
}

logger = logging.getLogger("pipeline.sequential")


class SequentialPipeline:
    def __init__(
        self,
        store: AuditStore,
        writeback: DecisionWriteback,
        extraction: ExtractionAgent,
        verification: VerificationAgent,
        policy: PolicyAgent,
        risk: RiskAgent,
        cfg: PipelineConfig,
        rule_version: str,
        latency_sink=None,
    ):
        self._store = store
        self._writeback = writeback
        self._extraction = extraction
        self._verification = verification
        self._policy = policy
        self._risk = risk
        self._cfg = cfg
        self.rule_version = rule_version
        self.model_version = cfg.risk.model_version
        self._sink = latency_sink
        self._on_latency = latency_sink.record_node if latency_sink else None

    def run(self, event: SubmissionCreatedEvent) -> AuditState:
        import time

        state = AuditState(submission_id=event.submission_id)
        state.raw_receipts = [
            ReceiptRef(line_id=l.line_id, blob_url=l.receipt_url) for l in event.report_lines
        ]
        retry = self._cfg.retry
        started = time.perf_counter()

        # extraction -> persist lines (must precede vector writes in verification)
        run_node_logged(
            "extraction", lambda: self._extraction.run(state, event),
            state=state, timeout_s=self._cfg.timeout("extraction"), retry=retry,
            on_latency=self._on_latency, store=self._store, submission_id=state.submission_id,
            input_summary=f"{len(event.report_lines)} receipt(s)",
            output_summary_fn=lambda: summarize_extraction(state),
        )
        self._store.save_extracted_lines(state.submission_id, state.extracted_lines)

        run_node_logged(
            "verification", lambda: self._verification.run(state, event),
            state=state, timeout_s=self._cfg.timeout("verification"), retry=retry,
            on_latency=self._on_latency, store=self._store, submission_id=state.submission_id,
            input_summary=f"{len(state.extracted_lines)} extracted line(s)",
            output_summary_fn=lambda: summarize_verification(state),
        )
        self._store.save_verification(state.submission_id, state.verification)

        run_node_logged(
            "policy", lambda: self._policy.run(state, event),
            state=state, timeout_s=self._cfg.timeout("policy"), retry=retry,
            on_latency=self._on_latency, store=self._store, submission_id=state.submission_id,
            input_summary=f"{len(event.report_lines)} line(s) vs {self.rule_version}",
            output_summary_fn=lambda: summarize_policy(state),
        )
        self._store.save_policy(
            state.submission_id, state.policy_evaluation, rule_version=self.rule_version
        )

        run_node_logged(
            "risk_scoring", lambda: self._risk.run(state, event),
            state=state, timeout_s=self._cfg.timeout("risk_scoring"), retry=retry,
            on_latency=self._on_latency, store=self._store, submission_id=state.submission_id,
            input_summary="verification + policy outputs",
            output_summary_fn=lambda: summarize_risk(state),
        )

        # Fail-open backstop: if any node failed (incl. the risk node itself) the
        # submission must land in human review, never an unattended auto-decision.
        if state.errors or state.routing_decision is None:
            state.routing_decision = RoutingDecision.human_review
            if state.risk_score is None:
                state.risk_score = 1.0  # unknown risk treated as high
            note = f"fail-open: {len(state.errors)} node error(s)"
            state.explanation = (state.explanation + "; " + note) if state.explanation else note

        self._store.save_risk(
            state.submission_id,
            risk_score=state.risk_score,
            routing_decision=state.routing_decision,
            model_version=self.model_version,
            explanation=state.explanation,
        )

        # Decision write-back. Auto paths get a final status; human_review gets an
        # interim pending_review (this fallback engine has no suspend/resume, so
        # the final human status is recorded when the reviewer acts elsewhere).
        status = _ROUTING_TO_STATUS.get(state.routing_decision, DecisionStatus.pending_review)
        self._writeback.send(
            AuditDecisionWriteback(
                submission_id=state.submission_id,
                decision=status,
                decision_timestamp=datetime.now(timezone.utc),
                risk_score=state.risk_score,
                rule_ids_triggered=[
                    r.rule_id for r in state.policy_evaluation.rule_results if not r.passed
                ],
                rationale=state.explanation,
                model_version=self.model_version,
                rule_version=self.rule_version,
                reviewer_id=None,
            )
        )
        if self._sink is not None:
            self._sink.record_end_to_end(time.perf_counter() - started)
        return state
