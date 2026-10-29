"""Shared policy-rule model and loader.

Loads `config/policy_rules.yaml` into typed rule objects and provides rule
*selection* + cap lookup. This is deliberately just the data + selection layer,
shared by the synthetic generator (to construct known violations) and, from
Milestone 6, by the deterministic policy engine. The *verdict* computation
(amount-over-cap etc.) belongs to the engine and is not implemented here.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from config.settings import REPO_ROOT

_DEFAULT_PATH = REPO_ROOT / "config" / "policy_rules.yaml"


class RuleType(str, Enum):
    amount_cap = "amount_cap"
    receipt_required_above = "receipt_required_above"
    # Hard-blocks any line in a prohibited/restricted category (e.g. alcohol,
    # personal expenses, political contributions) - always fails when matched.
    prohibited_category = "prohibited_category"
    # Flags a line whose transaction date falls on a Saturday/Sunday.
    weekend_spend_flag = "weekend_spend_flag"
    # Flags a suspiciously round amount at/above a threshold (fabrication signal).
    round_amount_flag = "round_amount_flag"
    # Flags a tax/amount ratio outside an expected band (VAT/tax irregularity).
    tax_ratio_check = "tax_ratio_check"
    # Flags an expense submitted too long after its transaction date.
    late_submission_flag = "late_submission_flag"
    # Flags a receipt whose currency doesn't match the submission's currency.
    currency_mismatch_flag = "currency_mismatch_flag"
    # Cumulative amount cap over a rolling window (e.g. annual FCPA/anti-bribery
    # gift-and-entertainment aggregate limits, BR-TE-AU-04) - unlike amount_cap
    # (per-line), this sums the employee's spend in this category across
    # submissions within `window_days`.
    cumulative_amount_cap = "cumulative_amount_cap"


class AppliesTo(BaseModel):
    category: Optional[str] = None
    oe_code: Optional[str] = None

    def matches(self, *, category: str, oe_code: str) -> bool:
        if self.category is not None and self.category != category:
            return False
        if self.oe_code is not None and self.oe_code != oe_code:
            return False
        return True


class PolicyRule(BaseModel):
    id: str
    description: str = ""
    type: RuleType
    # A disabled rule is skipped entirely (PolicyAgent, and the cap-lookup
    # helpers below that the generator and VerificationAgent's structuring
    # checks also read) - kept rather than deleted, so re-enabling it later
    # doesn't require re-authoring its configuration.
    enabled: bool = True
    applies_to: AppliesTo = Field(default_factory=AppliesTo)
    cap: dict[str, float] = Field(default_factory=dict)        # amount_cap
    threshold: dict[str, float] = Field(default_factory=dict)  # receipt_required_above, round_amount_flag
    min_ratio: Optional[float] = None                          # tax_ratio_check
    max_ratio: Optional[float] = None                          # tax_ratio_check
    max_days: Optional[int] = None                             # late_submission_flag
    window_days: Optional[int] = None                          # cumulative_amount_cap

    def cap_for(self, currency: str) -> Optional[float]:
        return self.cap.get(currency)

    def threshold_for(self, currency: str) -> Optional[float]:
        return self.threshold.get(currency)


class PolicyRuleSet(BaseModel):
    rule_version: str
    rules: list[PolicyRule]

    def amount_cap_rules_for(
        self, *, category: str, oe_code: str, currency: str
    ) -> list[PolicyRule]:
        """Amount-cap rules that apply to this line and define a cap in its currency."""
        return [
            r
            for r in self.rules
            if r.enabled
            and r.type is RuleType.amount_cap
            and r.applies_to.matches(category=category, oe_code=oe_code)
            and r.cap_for(currency) is not None
        ]

    def cumulative_cap_rules_for(
        self, *, category: str, oe_code: str, currency: str
    ) -> list[PolicyRule]:
        """Cumulative (rolling-window) cap rules for this line's category/OE
        that define a cap in its currency - BR-TE-AU-04."""
        return [
            r
            for r in self.rules
            if r.enabled
            and r.type is RuleType.cumulative_amount_cap
            and r.applies_to.matches(category=category, oe_code=oe_code)
            and r.cap_for(currency) is not None
        ]


def load_policy_rules(path: Path | None = None) -> PolicyRuleSet:
    raw = yaml.safe_load((path or _DEFAULT_PATH).read_text(encoding="utf-8"))
    return PolicyRuleSet.model_validate(raw)
