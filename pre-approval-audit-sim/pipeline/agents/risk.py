"""Risk scoring & routing agent (Milestone 7).

Composite score from verification signals + policy violations + (stub) employee
history, then threshold-based routing (Solution Design 5.5). Guardrails:
  * an explanation is ALWAYS produced and stored - even for auto-approve;
  * any upstream node error, or any low-confidence extraction, forces
    human_review (fail-safe; never a silent auto-approve on incomplete data).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from common.schemas import AuditState, RoutingDecision, SubmissionCreatedEvent
from pipeline.agents.verification import STRONG_FORENSICS_FLAGS
from pipeline.config import load_pipeline_config

if TYPE_CHECKING:
    from data.interfaces import ConfigStore

logger = logging.getLogger("pipeline.agents.risk")


class RiskAgent:
    def __init__(self, config_store: Optional["ConfigStore"] = None):
        self._config_store = config_store

    def run(self, state: AuditState, event: SubmissionCreatedEvent) -> None:
        # Resolved fresh per submission from event.oe_code (always present -
        # required on SubmissionCreatedEvent) rather than bound once at
        # construction, so an OE's saved risk-weight/cutoff override
        # (Settings -> Risk & pipeline) takes effect live, on the very next
        # submission, with no process restart. A local variable, not an
        # instance attribute - this method has no internal concurrency of its
        # own, but the agent instance IS shared/reused across submissions
        # from every OE, so nothing here may become shared mutable state.
        cfg = load_pipeline_config(event.oe_code, self._config_store)
        w = cfg.risk.weights
        conf_cutoff = cfg.extraction.confidence_cutoff
        subtotal_tol = cfg.verification.subtotal_tolerance_pct

        v = state.verification
        pol = state.policy_evaluation

        n_violations = len(pol.violations)
        has_duplicate = bool(v.duplicate_matches)
        has_authenticity = bool(v.authenticity_flags)
        variance_exceeds = (
            v.subtotal_variance_pct is not None
            and v.subtotal_variance_pct > subtotal_tol
        )
        low_confidence = any(
            (el.amount is None) or (el.confidence < conf_cutoff)
            for el in state.extracted_lines
        ) or not state.extracted_lines

        score = 0.0
        reasons: list[str] = []
        if n_violations:
            score += w["policy_violation"] * n_violations
            reasons.append(f"{n_violations} policy violation(s): {', '.join(pol.violations)}")
        if has_duplicate:
            score += w["duplicate_match"]
            ids = ", ".join(m.submission_id for m in v.duplicate_matches)
            reasons.append(f"duplicate of {ids}")
            if any(m.match_type == "invoice_number" for m in v.duplicate_matches):
                score += w.get("duplicate_match_structured", 0.0)
                reasons.append("structured invoice-number match (high confidence)")
        if has_authenticity:
            score += w["authenticity_flag"]
            reasons.append(f"authenticity flags: {', '.join(v.authenticity_flags)}")
        if variance_exceeds:
            score += w["subtotal_variance"]
            calc = (
                f" (entered {v.subtotal_entered_total} vs receipt amount+tax "
                f"{v.subtotal_receipt_total} = |{v.subtotal_entered_total} - "
                f"{v.subtotal_receipt_total}| / {v.subtotal_receipt_total} * 100)"
                if v.subtotal_entered_total is not None and v.subtotal_receipt_total is not None
                else ""
            )
            reasons.append(
                f"subtotal variance {v.subtotal_variance_pct}% exceeds "
                f"{subtotal_tol}% tolerance{calc}"
            )
        if low_confidence:
            score += w["low_confidence"]
            reasons.append("low-confidence / illegible extraction")
        if v.velocity_flags:
            score += w.get("velocity_flag", 0.0)
            reasons.append(f"velocity: {', '.join(v.velocity_flags)}")
        if v.split_transaction_flags:
            score += w.get("split_transaction_flag", 0.0)
            reasons.append(f"split-transaction: {', '.join(v.split_transaction_flags)}")
        if v.merchant_flags:
            score += w.get("merchant_blocklist", 0.0)
            reasons.append(f"merchant watchlist: {', '.join(v.merchant_flags)}")
        if v.compliance_flags:
            score += w.get("compliance_cumulative", 0.0)
            reasons.append(f"cumulative compliance: {', '.join(v.compliance_flags)}")
        strong_forensics = [f for f in v.authenticity_flags if f in STRONG_FORENSICS_FLAGS]
        if strong_forensics:
            score += w.get("forensics_strong_signal", 0.0)
            reasons.append(f"strong forensics signal: {', '.join(strong_forensics)}")
        if v.peer_outlier_flags:
            score += w.get("peer_amount_outlier", 0.0)
            reasons.append(f"peer-group outlier: {', '.join(v.peer_outlier_flags)}")
        if v.merchant_network_flags:
            score += w.get("merchant_network_flag", 0.0)
            reasons.append(f"merchant network signal: {', '.join(v.merchant_network_flags)}")

        score = round(min(1.0, score), 3)
        state.risk_score = score

        # --- routing (fail-safe ordering) ---
        if state.errors:
            decision = RoutingDecision.human_review
            reasons.insert(0, f"fail-open: {len(state.errors)} upstream node error(s)")
        elif low_confidence:
            decision = RoutingDecision.human_review  # guardrail: never auto-decide on low conf
        elif score >= cfg.risk.auto_reject_cutoff:
            decision = RoutingDecision.auto_reject
        elif score <= cfg.risk.auto_approve_cutoff:
            decision = RoutingDecision.auto_approve
        else:
            decision = RoutingDecision.human_review

        state.routing_decision = decision
        state.explanation = (
            f"risk_score={score}; decision={decision.value}; "
            + ("; ".join(reasons) if reasons else "no risk signals detected")
        )
        logger.debug("risk for %s: %s (%.3f)", event.submission_id, decision.value, score)
