"""LangGraph orchestration (Milestone 8).

Wires the Phase 2 agents into a checkpointed LangGraph state machine
(Tech Design 3.1-3.2). Node bodies reuse the agents and the resilience runtime
verbatim; the graph adds:
  * checkpointing keyed on submission_id (Tech Design 3.4);
  * a conditional edge after risk scoring (auto -> writeback, human -> handoff);
  * suspend at the human-review handoff, resumable later via resume_after_review.

Implements the AuditPipeline seam, so it drops into the integration layer in
place of SequentialPipeline with no caller change.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

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

logger = logging.getLogger("pipeline.graph")

_HANDOFF = "human_review_handoff"


class GraphState(TypedDict, total=False):
    # A TypedDict (not a pydantic model) on purpose: LangGraph re-coerces the
    # state schema when resuming from a durable checkpoint, and pydantic would
    # reject the rebuilt nested model instances on class-identity. A TypedDict is
    # a plain dict at runtime, so there is no re-coercion/validation step.
    event: SubmissionCreatedEvent
    audit: AuditState
    reviewer_id: Optional[str]
    reviewer_decision: Optional[str]  # "approved" | "rejected"
    reviewer_notes: Optional[str]


class LangGraphPipeline:
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
        checkpointer,
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
        self._compiled = self._build().compile(
            checkpointer=checkpointer, interrupt_after=[_HANDOFF]
        )

    # ------------------------------------------------------------------ public
    def run(self, event: SubmissionCreatedEvent) -> AuditState:
        import time

        config = {"configurable": {"thread_id": event.submission_id}}
        initial = {
            "event": event,
            "audit": AuditState(submission_id=event.submission_id),
        }
        started = time.perf_counter()
        self._compiled.invoke(initial, config)
        if self._sink is not None:
            self._sink.record_end_to_end(time.perf_counter() - started)
        return self._current_audit(config)

    def resume_after_review(
        self,
        submission_id: str,
        *,
        reviewer_id: str,
        decision: str,
        notes: str | None = None,
    ) -> AuditState:
        """Resume a suspended human-review run from its checkpoint and finalise
        it with the reviewer's decision (Tech Design 3.2/3.4)."""
        config = {"configurable": {"thread_id": submission_id}}
        try:
            snap = self._compiled.get_state(config)
            suspended = bool(snap.next)
        except Exception as exc:
            # An incompatible/older checkpoint (e.g. written before a schema
            # change) can fail to reload. Rather than block the reviewer, fall
            # back to finalising the decision directly against the store.
            logger.warning("checkpoint for %s unreadable (%s); finalising directly",
                           submission_id, exc)
            return self._finalize_without_graph(submission_id, reviewer_id, decision, notes)

        if not suspended:
            return self._finalize_without_graph(submission_id, reviewer_id, decision, notes)

        self._compiled.update_state(
            config,
            {"reviewer_id": reviewer_id, "reviewer_decision": decision,
             "reviewer_notes": notes},
        )
        self._compiled.invoke(None, config)
        return self._current_audit(config)

    def _finalize_without_graph(
        self, submission_id: str, reviewer_id: str, decision: str, notes: str | None
    ) -> AuditState:
        """Record a reviewer decision without resuming the graph - used when the
        checkpoint is missing or unreadable. Only valid for a case still routed
        to human review."""
        detail = self._store.get_case_detail(submission_id)
        if not detail:
            raise ValueError(f"unknown submission {submission_id}")
        risk = detail.get("risk") or {}
        if risk.get("routing_decision") != RoutingDecision.human_review.value:
            raise ValueError(
                f"{submission_id} is not awaiting review "
                f"(routing={risk.get('routing_decision')})"
            )
        audit = AuditState(submission_id=submission_id)
        audit.risk_score = risk.get("risk_score")
        audit.explanation = risk.get("explanation")
        audit.routing_decision = RoutingDecision.human_review
        final = DecisionStatus.approved if decision == "approved" else DecisionStatus.rejected
        self._send_writeback(audit, final, reviewer_id=reviewer_id, notes=notes)
        return audit

    def is_suspended(self, submission_id: str) -> bool:
        """True if the run is checkpointed awaiting a reviewer decision. Returns
        False (rather than raising) if the checkpoint is missing/unreadable."""
        config = {"configurable": {"thread_id": submission_id}}
        try:
            return bool(self._compiled.get_state(config).next)
        except Exception:
            return False

    def _current_audit(self, config) -> AuditState:
        values = self._compiled.get_state(config).values
        audit = values["audit"]
        return audit if isinstance(audit, AuditState) else AuditState.model_validate(audit)

    # ------------------------------------------------------------------ graph
    def _build(self) -> StateGraph:
        g = StateGraph(GraphState)
        g.add_node("ingest", self._ingest)
        g.add_node("extraction", self._extraction_node)
        g.add_node("verification", self._verification_node)
        g.add_node("policy", self._policy_node)
        g.add_node("risk_scoring", self._risk_node)
        g.add_node(_HANDOFF, self._handoff_node)
        g.add_node("decision_writeback", self._writeback_node)

        g.add_edge(START, "ingest")
        g.add_edge("ingest", "extraction")
        g.add_edge("extraction", "verification")
        g.add_edge("verification", "policy")
        g.add_edge("policy", "risk_scoring")
        g.add_conditional_edges(
            "risk_scoring",
            self._route,
            {"auto": "decision_writeback", "human": _HANDOFF},
        )
        # human path resumes here after the interrupt
        g.add_edge(_HANDOFF, "decision_writeback")
        g.add_edge("decision_writeback", END)
        return g

    # ------------------------------------------------------------------ nodes
    @staticmethod
    def _audit(state: GraphState) -> AuditState:
        a = state["audit"]
        return a if isinstance(a, AuditState) else AuditState.model_validate(a)

    @staticmethod
    def _event(state: GraphState) -> SubmissionCreatedEvent:
        e = state["event"]
        return e if isinstance(e, SubmissionCreatedEvent) else SubmissionCreatedEvent.model_validate(e)

    def _ingest(self, state: GraphState) -> dict:
        audit, event = self._audit(state), self._event(state)
        audit.raw_receipts = [
            ReceiptRef(line_id=l.line_id, blob_url=l.receipt_url)
            for l in event.report_lines
        ]
        return {"audit": audit}

    def _extraction_node(self, state: GraphState) -> dict:
        audit, event = self._audit(state), self._event(state)
        run_node_logged(
            "extraction", lambda: self._extraction.run(audit, event),
            state=audit, timeout_s=self._cfg.timeout("extraction"), retry=self._cfg.retry,
            on_latency=self._on_latency, store=self._store, submission_id=audit.submission_id,
            input_summary=f"{len(event.report_lines)} receipt(s)",
            output_summary_fn=lambda: summarize_extraction(audit),
        )
        self._store.save_extracted_lines(audit.submission_id, audit.extracted_lines)
        return {"audit": audit}

    def _verification_node(self, state: GraphState) -> dict:
        audit, event = self._audit(state), self._event(state)
        run_node_logged(
            "verification", lambda: self._verification.run(audit, event),
            state=audit, timeout_s=self._cfg.timeout("verification"), retry=self._cfg.retry,
            on_latency=self._on_latency, store=self._store, submission_id=audit.submission_id,
            input_summary=f"{len(audit.extracted_lines)} extracted line(s)",
            output_summary_fn=lambda: summarize_verification(audit),
        )
        self._store.save_verification(audit.submission_id, audit.verification)
        return {"audit": audit}

    def _policy_node(self, state: GraphState) -> dict:
        audit, event = self._audit(state), self._event(state)
        run_node_logged(
            "policy", lambda: self._policy.run(audit, event),
            state=audit, timeout_s=self._cfg.timeout("policy"), retry=self._cfg.retry,
            on_latency=self._on_latency, store=self._store, submission_id=audit.submission_id,
            input_summary=f"{len(event.report_lines)} line(s) vs {self.rule_version}",
            output_summary_fn=lambda: summarize_policy(audit),
        )
        self._store.save_policy(audit.submission_id, audit.policy_evaluation,
                                rule_version=self.rule_version)
        return {"audit": audit}

    def _risk_node(self, state: GraphState) -> dict:
        audit, event = self._audit(state), self._event(state)
        run_node_logged(
            "risk_scoring", lambda: self._risk.run(audit, event),
            state=audit, timeout_s=self._cfg.timeout("risk_scoring"), retry=self._cfg.retry,
            on_latency=self._on_latency, store=self._store, submission_id=audit.submission_id,
            input_summary="verification + policy outputs",
            output_summary_fn=lambda: summarize_risk(audit),
        )
        # Fail-open backstop: unresolved/failed risk lands in human review.
        if audit.errors or audit.routing_decision is None:
            audit.routing_decision = RoutingDecision.human_review
            if audit.risk_score is None:
                audit.risk_score = 1.0
            note = f"fail-open: {len(audit.errors)} node error(s)"
            audit.explanation = (audit.explanation + "; " + note) if audit.explanation else note
        self._store.save_risk(
            audit.submission_id,
            risk_score=audit.risk_score,
            routing_decision=audit.routing_decision,
            model_version=self.model_version,
            explanation=audit.explanation,
        )
        return {"audit": audit}

    def _route(self, state: GraphState) -> str:
        decision = self._audit(state).routing_decision or RoutingDecision.human_review
        return "human" if decision is RoutingDecision.human_review else "auto"

    def _handoff_node(self, state: GraphState) -> dict:
        # Write the interim pending_review status so the approval flow is not
        # blocked, then the graph suspends (interrupt_after) until a reviewer acts.
        audit = self._audit(state)
        self._send_writeback(audit, DecisionStatus.pending_review, reviewer_id=None, notes=None)
        return {"audit": audit}

    def _writeback_node(self, state: GraphState) -> dict:
        audit = self._audit(state)
        reviewer_decision = state.get("reviewer_decision")
        if reviewer_decision:  # resumed human-review path -> final status
            final = (
                DecisionStatus.approved
                if reviewer_decision == "approved"
                else DecisionStatus.rejected
            )
            self._send_writeback(
                audit, final, reviewer_id=state.get("reviewer_id"),
                notes=state.get("reviewer_notes"),
            )
        else:  # auto path
            final = (
                DecisionStatus.approved
                if audit.routing_decision is RoutingDecision.auto_approve
                else DecisionStatus.rejected
            )
            self._send_writeback(audit, final, reviewer_id=None, notes=None)
        return {"audit": audit}

    # ------------------------------------------------------------------ helpers
    def _send_writeback(
        self, audit: AuditState, status: DecisionStatus, *, reviewer_id, notes
    ) -> None:
        self._writeback.send(
            AuditDecisionWriteback(
                submission_id=audit.submission_id,
                decision=status,
                decision_timestamp=datetime.now(timezone.utc),
                risk_score=audit.risk_score,
                rule_ids_triggered=[
                    r.rule_id for r in audit.policy_evaluation.rule_results if not r.passed
                ],
                rationale=notes or audit.explanation,
                model_version=self.model_version,
                rule_version=self.rule_version,
                reviewer_id=reviewer_id,
            )
        )
