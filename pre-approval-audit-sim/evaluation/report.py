"""Accuracy & latency report (Milestone 10).

Compares a full batch run against the Feasibility Spike Plan Section 6 thresholds
(config/thresholds.yaml). Per Build Brief 9, meeting the thresholds is
INFORMATIVE, not a go-live gate - simulation data is a mechanics floor, and the
real gate is real-data validation (deferred, Solution Design 12).
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from common.schemas import AuditState
from evaluation.scoring import (
    score_confidence,
    score_duplicates,
    score_extraction,
    score_policy,
)
from generator.ground_truth import GroundTruth

_SIM_BANNER = (
    "SIMULATION DATA - informative only, NOT a go-live gate. Latency reflects the "
    "offline simulated extractor and is not indicative of real vision-LLM latency."
)


@dataclass
class MetricRow:
    metric: str
    measured: float
    threshold: Optional[float]
    comparator: str  # ">=", "<=", "==", "info"
    meets: Optional[bool]


def _meets(measured: float, threshold: float, comparator: str) -> bool:
    if comparator == ">=":
        return measured >= threshold
    if comparator == "<=":
        return measured <= threshold
    if comparator == "==":
        return measured == threshold
    return True


@dataclass
class ReportResult:
    run_id: str
    n_submissions: int
    rows: list[MetricRow]
    latency: dict
    routing_distribution: dict
    banner: str = _SIM_BANNER

    def to_json(self) -> str:
        return json.dumps(
            {
                "run_id": self.run_id,
                "n_submissions": self.n_submissions,
                "banner": self.banner,
                "metrics": [asdict(r) for r in self.rows],
                "latency": self.latency,
                "routing_distribution": self.routing_distribution,
            },
            indent=2,
        )

    def to_markdown(self) -> str:
        lines = [
            f"# Pre-Approval Expense Audit - Accuracy & Latency Report",
            "",
            f"**Run:** `{self.run_id}`  |  **Submissions:** {self.n_submissions}",
            "",
            f"> {self.banner}",
            "",
            "## Metrics vs Feasibility Spike thresholds",
            "",
            "| Metric | Measured | Threshold | Meets bar |",
            "|---|---|---|---|",
        ]
        for r in self.rows:
            thr = "-" if r.threshold is None else f"{r.comparator} {r.threshold}"
            mark = "-" if r.meets is None else ("[PASS]" if r.meets else "[BELOW]")
            lines.append(f"| {r.metric} | {r.measured:.4f} | {thr} | {mark} |")
        lines += ["", "## Latency (simulation timing)", "",
                  "| Stage | p50 (s) | p95 (s) | max (s) | n |", "|---|---|---|---|---|"]
        for node, s in self.latency.get("per_node", {}).items():
            lines.append(
                f"| {node} | {s['p50_s']} | {s['p95_s']} | {s['max_s']} | {s['count']} |"
            )
        e2e = self.latency.get("end_to_end", {})
        if e2e:
            lines.append(
                f"| **end-to-end** | {e2e['p50_s']} | {e2e['p95_s']} | {e2e['max_s']} "
                f"| {e2e['count']} |"
            )
        lines += ["", "## Routing distribution", ""]
        for k, v in sorted(self.routing_distribution.items()):
            lines.append(f"- {k}: {v}")
        lines.append("")
        return "\n".join(lines)


def build_report(
    gt: GroundTruth,
    states: dict[str, AuditState],
    latency_summary: dict,
    thresholds: dict,
    *,
    policy_verdicts: dict[str, tuple[bool, set[str]]] | None = None,
) -> ReportResult:
    ext = score_extraction(gt, states)
    dup = score_duplicates(gt, states)
    conf = score_confidence(gt, states, thresholds["confidence"]["low_confidence_cutoff"])

    rows: list[MetricRow] = [
        MetricRow("Extraction field accuracy", round(ext.field_accuracy, 4),
                  thresholds["extraction"]["field_accuracy_min"], ">=",
                  _meets(ext.field_accuracy, thresholds["extraction"]["field_accuracy_min"], ">=")),
        MetricRow("Extraction amount accuracy", round(ext.amount_accuracy, 4), None, "info", None),
        MetricRow("Duplicate recall", round(dup.recall, 4),
                  thresholds["duplicate_detection"]["recall_min"], ">=",
                  _meets(dup.recall, thresholds["duplicate_detection"]["recall_min"], ">=")),
        MetricRow("Duplicate false-positive rate", round(dup.false_positive_rate, 4),
                  thresholds["duplicate_detection"]["false_positive_rate_max"], "<=",
                  _meets(dup.false_positive_rate,
                         thresholds["duplicate_detection"]["false_positive_rate_max"], "<=")),
        MetricRow("Confidence accuracy gap", round(conf.gap, 4),
                  thresholds["confidence"]["min_accuracy_gap"], ">=",
                  _meets(conf.gap, thresholds["confidence"]["min_accuracy_gap"], ">=")),
    ]

    if policy_verdicts is not None:
        pol = score_policy(gt, policy_verdicts)
        rows.append(
            MetricRow("Policy verdict match (deterministic engine)",
                      round(pol.verdict_match_rate, 4), 1.0, "==",
                      _meets(pol.verdict_match_rate, 1.0, "=="))
        )

    # latency threshold rows
    ext_p95 = latency_summary.get("per_node", {}).get("extraction", {}).get("p95_s", 0.0)
    e2e_p95 = latency_summary.get("end_to_end", {}).get("p95_s", 0.0)
    rows.append(
        MetricRow("Extraction p95 latency (s)", ext_p95,
                  thresholds["latency"]["extraction_p95_seconds_max"], "<=",
                  _meets(ext_p95, thresholds["latency"]["extraction_p95_seconds_max"], "<="))
    )
    rows.append(
        MetricRow("Pipeline p95 latency (s)", e2e_p95,
                  thresholds["latency"]["pipeline_p95_seconds_max"], "<=",
                  _meets(e2e_p95, thresholds["latency"]["pipeline_p95_seconds_max"], "<="))
    )

    routing = Counter(
        st.routing_decision.value for st in states.values() if st.routing_decision
    )
    return ReportResult(
        run_id=gt.run_id,
        n_submissions=len(states),
        rows=rows,
        latency=latency_summary,
        routing_distribution=dict(routing),
    )
