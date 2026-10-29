"""Ground-truth data structures + JSON persistence.

Every synthetic submission ships with an exact ground-truth record: the true
extraction values, whether it is a duplicate (and of which submission), the
expected policy verdict, and whether the receipt was manipulated. Because
anomalies are injected by construction, this needs no manual labelling
(Tech Design 2.4). The Phase 5 accuracy harness scores pipeline output against
this file.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class GTLine(BaseModel):
    line_id: str
    vendor: str
    date: str  # ISO date
    amount: float  # true amount shown ON the receipt
    tax: float
    currency: str
    category: str


class GTPolicy(BaseModel):
    verdict: str  # "pass" | "fail"
    violated_rule_ids: list[str] = Field(default_factory=list)


class GTSubmission(BaseModel):
    submission_id: str
    is_duplicate_of: Optional[str] = None
    manipulated: bool = False
    expected_authenticity_flags: list[str] = Field(default_factory=list)
    # subtotal variance the verification agent should observe (manipulated only)
    expected_subtotal_variance_pct: Optional[float] = None
    # Every line's amount was inflated by anomaly_injection.peer_outlier_multiplier
    # to land far outside the population baseline VerificationAgent._peer_outlier
    # compares against - distinct from `manipulated` (which is about entered-vs-
    # receipt tampering, not amount level).
    peer_outlier: bool = False
    # This submission was the anomaly_injection.policy_violation_rate injection
    # target - i.e. a line was deliberately generated over a rule's cap. Kept
    # distinct from `policy.verdict == "fail"`: a peer_outlier submission can
    # ALSO independently breach a cap (its inflated amount is a real breach,
    # not a fabricated one), so verdict alone no longer identifies which
    # submissions were the deliberate policy_violation injection.
    policy_violation: bool = False
    policy: GTPolicy
    lines: list[GTLine]


class GroundTruth(BaseModel):
    run_id: str
    generator_config: dict
    policy_rule_version: str
    submissions: list[GTSubmission]

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> "GroundTruth":
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
