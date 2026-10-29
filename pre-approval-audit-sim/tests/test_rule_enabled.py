"""Business-rule enable/disable toggle (common/policy.py's PolicyRule.enabled).

A disabled rule must be skipped entirely - by PolicyAgent's own evaluation,
and by the amount_cap/cumulative_cap lookup helpers the generator and
VerificationAgent's structuring checks also read - rather than merely
excluded from the violations list.
"""
from __future__ import annotations

from datetime import datetime, timezone

from common.policy import AppliesTo, PolicyRule, PolicyRuleSet, RuleType
from common.schemas import (
    AuditState,
    ExtractedLine,
    ReportLine,
    SourceSystem,
    SubmissionCreatedEvent,
)
from pipeline.agents.policy import PolicyAgent


def _rule(**kwargs) -> PolicyRule:
    base = dict(id="TEST-CAP-01", type=RuleType.amount_cap,
                applies_to=AppliesTo(category="meals"), cap={"EUR": 50.0})
    base.update(kwargs)
    return PolicyRule(**base)


def _event(amount: float) -> SubmissionCreatedEvent:
    return SubmissionCreatedEvent(
        submission_id="SUB-1", source_system=SourceSystem.simulation_harness,
        source_system_ref="SUB-1", oe_code="DE", employee_id="EMP-1", currency="EUR",
        submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        report_lines=[ReportLine(line_id="LN-1", category="meals", entered_amount=amount,
                                  receipt_url="blob://SUB-1/LN-1")],
    )


def test_enabled_defaults_true_when_omitted():
    rule = PolicyRule(id="R1", type=RuleType.weekend_spend_flag)
    assert rule.enabled is True


def test_enabled_true_defaults_still_load_from_yaml_dict():
    # Simulates an existing policy_rules.yaml entry with no `enabled` key at
    # all (every rule authored before this feature existed) - must still
    # validate and behave as enabled, not fail validation or default to off.
    raw = {"id": "R2", "type": "amount_cap", "applies_to": {"category": "meals"}, "cap": {"EUR": 50.0}}
    rule = PolicyRule.model_validate(raw)
    assert rule.enabled is True


def test_disabled_amount_cap_rule_is_skipped_by_policy_agent():
    rules = PolicyRuleSet(rule_version="v1", rules=[_rule(enabled=False)])
    agent = PolicyAgent(rules)
    state = AuditState(submission_id="SUB-1")
    event = _event(999.0)  # comfortably over the 50 EUR cap
    state.extracted_lines = [ExtractedLine(line_id="LN-1", amount=999.0, tax=0.0, currency="EUR", confidence=1.0)]
    agent.run(state, event)
    assert state.policy_evaluation.rule_results == []
    assert state.policy_evaluation.violations == []


def test_enabled_amount_cap_rule_still_fires():
    rules = PolicyRuleSet(rule_version="v1", rules=[_rule(enabled=True)])
    agent = PolicyAgent(rules)
    state = AuditState(submission_id="SUB-1")
    event = _event(999.0)
    state.extracted_lines = [ExtractedLine(line_id="LN-1", amount=999.0, tax=0.0, currency="EUR", confidence=1.0)]
    agent.run(state, event)
    assert state.policy_evaluation.violations == ["TEST-CAP-01: rule failed"]


def test_disabled_rule_excluded_from_amount_cap_rules_for():
    rules = PolicyRuleSet(rule_version="v1", rules=[_rule(enabled=False)])
    assert rules.amount_cap_rules_for(category="meals", oe_code="DE", currency="EUR") == []


def test_enabled_rule_included_in_amount_cap_rules_for():
    rules = PolicyRuleSet(rule_version="v1", rules=[_rule(enabled=True)])
    found = rules.amount_cap_rules_for(category="meals", oe_code="DE", currency="EUR")
    assert [r.id for r in found] == ["TEST-CAP-01"]


def test_disabled_cumulative_rule_excluded_from_cumulative_cap_rules_for():
    rules = PolicyRuleSet(rule_version="v1", rules=[
        _rule(id="TEST-CUM-01", type=RuleType.cumulative_amount_cap, window_days=365, enabled=False),
    ])
    assert rules.cumulative_cap_rules_for(category="meals", oe_code="DE", currency="EUR") == []
