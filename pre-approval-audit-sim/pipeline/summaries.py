"""Short, human-readable output summaries for the pipeline-logs observability
trace (see pipeline/runtime.py::run_node_logged). Shared by SequentialPipeline
and LangGraphPipeline so both engines produce identically-worded traces.
"""
from __future__ import annotations

from common.schemas import AuditState


def summarize_extraction(state: AuditState) -> str:
    lines = state.extracted_lines
    if not lines:
        return "0 line(s) extracted"
    confidences = [l.confidence for l in lines]
    illegible = sum(1 for l in lines if l.amount is None)
    return (
        f"{len(lines)} line(s) extracted, min_confidence={min(confidences):.2f}"
        + (f", {illegible} illegible" if illegible else "")
    )


def summarize_verification(state: AuditState) -> str:
    v = state.verification
    parts = [
        f"duplicates={len(v.duplicate_matches)}",
        f"authenticity_flags={len(v.authenticity_flags)}",
        f"subtotal_variance={v.subtotal_variance_pct}%"
        if v.subtotal_variance_pct is not None else "subtotal_variance=n/a",
        f"merchant={v.merchant_validation.value}",
    ]
    return ", ".join(parts)


def summarize_policy(state: AuditState) -> str:
    pe = state.policy_evaluation
    n_fail = sum(1 for r in pe.rule_results if not r.passed)
    return f"{len(pe.rule_results)} rule(s) evaluated, {n_fail} violation(s)"


def summarize_risk(state: AuditState) -> str:
    return (
        f"score={state.risk_score}, "
        f"routing={state.routing_decision.value if state.routing_decision else 'n/a'}"
    )
