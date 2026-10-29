"""Policy engine (Milestone 6) - deterministic rule evaluation.

Produces the same verdict for the same input every time (Solution Design 5.4).
This is the ONLY source of a final policy verdict; the learned/advisory layer
(future) is kept separate and never overrides a rule result here. Each triggered
rule is recorded with its id; rule_version is stamped at persistence time.

Evaluation uses the extracted amount where available, falling back to the
employee-entered amount if extraction was illegible - so a missing extraction
never silently drops a policy check.

Rule types fall into two groups (see config/policy_rules.yaml for the full,
categorised library):
  * category-scoped compliance rules (amount_cap, receipt_required_above,
    prohibited_category) - gated by `applies_to.category`.
  * cross-cutting fraud/behavioural/timing checks (weekend_spend_flag,
    round_amount_flag, tax_ratio_check, late_submission_flag,
    currency_mismatch_flag) - typically applied with no category filter, so
    they run against every line.
Any rule that lacks the data it needs to judge a line (e.g. no extracted date)
returns "not applicable" (None) rather than guessing - consistent with the
extraction guardrail of never silently proceeding on missing data.
"""
from __future__ import annotations

import logging

from common.policy import PolicyRuleSet, RuleType
from common.schemas import (
    AuditState,
    PolicyEvaluation,
    RuleResult,
    SubmissionCreatedEvent,
)

logger = logging.getLogger("pipeline.agents.policy")

# Suspiciously round amounts: whole-dollar/euro/pound value that is also an
# exact multiple of this increment (classic fabricated-receipt heuristic).
_ROUND_AMOUNT_INCREMENT = 25


class PolicyAgent:
    def __init__(self, rules: PolicyRuleSet):
        self._rules = rules

    def run(self, state: AuditState, event: SubmissionCreatedEvent) -> None:
        entered_by_line = {l.line_id: l.entered_amount for l in event.report_lines}
        category_by_line = {l.line_id: l.category for l in event.report_lines}
        extracted_by_line = {el.line_id: el for el in state.extracted_lines}

        # rule_id -> passed (AND across all lines the rule applies to)
        results: dict[str, bool] = {}

        for line in event.report_lines:
            category = category_by_line[line.line_id]
            el = extracted_by_line.get(line.line_id)
            amount = el.amount if (el and el.amount is not None) else entered_by_line[line.line_id]
            currency = (el.currency if el and el.currency else event.currency)

            for rule in self._rules.rules:
                if not rule.enabled:
                    continue
                if not rule.applies_to.matches(category=category, oe_code=event.oe_code):
                    continue
                passed = self._evaluate(
                    rule, amount=amount, currency=currency, line=line, el=el, event=event,
                )
                if passed is None:
                    continue  # rule not applicable to this line/currency/data
                results[rule.id] = results.get(rule.id, True) and passed

        rule_results = [RuleResult(rule_id=rid, passed=p) for rid, p in sorted(results.items())]
        violations = [
            f"{rid}: rule failed" for rid, p in sorted(results.items()) if not p
        ]
        state.policy_evaluation = PolicyEvaluation(
            rule_results=rule_results,
            violations=violations,
            advisory_notes=[],  # learned layer slot - intentionally empty (advisory only)
        )
        logger.debug(
            "policy for %s: %d rules, %d violations",
            event.submission_id, len(rule_results), len(violations),
        )

    def _evaluate(self, rule, *, amount, currency, line, el, event) -> bool | None:
        if rule.type is RuleType.amount_cap:
            cap = rule.cap_for(currency)
            if cap is None:
                return None
            return amount <= cap

        if rule.type is RuleType.receipt_required_above:
            threshold = rule.threshold_for(currency)
            if threshold is None:
                return None
            # a receipt is required when amount >= threshold; in this build every
            # line carries a receipt_url, so the requirement is satisfied.
            if amount >= threshold:
                return bool(line.receipt_url)
            return True

        if rule.type is RuleType.prohibited_category:
            # applies_to.category already gated the match; reaching here means
            # this line IS in a prohibited category - always fails.
            return False

        if rule.type is RuleType.weekend_spend_flag:
            txn_date = el.date if el and el.date else None
            if txn_date is None:
                return None
            return txn_date.weekday() < 5  # Mon-Fri pass; Sat/Sun fail

        if rule.type is RuleType.round_amount_flag:
            threshold = rule.threshold_for(currency)
            if threshold is None or amount is None or amount < threshold:
                return None
            is_round = (amount == round(amount)) and (int(amount) % _ROUND_AMOUNT_INCREMENT == 0)
            return not is_round

        if rule.type is RuleType.tax_ratio_check:
            if el is None or el.amount in (None, 0) or el.tax is None:
                return None
            ratio = el.tax / el.amount
            lo = rule.min_ratio if rule.min_ratio is not None else 0.0
            hi = rule.max_ratio if rule.max_ratio is not None else 1.0
            return lo <= ratio <= hi

        if rule.type is RuleType.late_submission_flag:
            txn_date = el.date if el and el.date else None
            if txn_date is None or rule.max_days is None:
                return None
            gap_days = (event.submitted_at.date() - txn_date).days
            return gap_days <= rule.max_days

        if rule.type is RuleType.currency_mismatch_flag:
            line_currency = el.currency if el and el.currency else None
            if line_currency is None:
                return None
            return line_currency == event.currency

        return None
