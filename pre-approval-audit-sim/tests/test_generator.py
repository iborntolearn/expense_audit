"""Milestone 2: generator is config-driven, hits target anomaly rates, and its
ground truth is internally correct."""
from __future__ import annotations

import pytest

from common.policy import PolicyRuleSet, RuleType, load_policy_rules
from data.factory import build_data_layer
from generator.config import GeneratorConfig, load_generator_config
from generator.synthesize import Synthesizer


@pytest.fixture()
def small_config() -> GeneratorConfig:
    cfg = load_generator_config()
    return cfg.model_copy(update={"volume": 100, "seed": 42})


@pytest.fixture()
def rules() -> PolicyRuleSet:
    return load_policy_rules()


def _synth(cfg, rules, sim_settings):
    data = build_data_layer(sim_settings)
    try:
        return Synthesizer(cfg, rules, data.blobs).generate()
    finally:
        data.close()


def test_volume_matches_config(small_config, rules, sim_settings):
    events, gt = _synth(small_config, rules, sim_settings)
    assert len(events) == 100
    assert len(gt.submissions) == 100


def test_anomaly_rates_within_tolerance(small_config, rules, sim_settings):
    _, gt = _synth(small_config, rules, sim_settings)
    n = len(gt.submissions)
    dups = sum(1 for s in gt.submissions if s.is_duplicate_of)
    # `policy_violation` (the deliberate injection target), not
    # `policy.verdict == "fail"` - a peer_outlier submission's inflated
    # amount can ALSO independently breach a cap (a real, not fabricated,
    # violation), so verdict alone no longer identifies just the injected ones.
    pols = sum(1 for s in gt.submissions if s.policy_violation)
    mans = sum(1 for s in gt.submissions if s.manipulated)
    peers = sum(1 for s in gt.submissions if s.peer_outlier)
    # exact counts are round(rate * volume); allow off-by-one for degraded dups
    assert abs(dups - round(0.08 * n)) <= 1
    assert pols == round(0.12 * n)
    assert mans == round(0.05 * n)
    assert peers == round(0.05 * n)


def test_determinism(small_config, rules, sim_settings):
    e1, g1 = _synth(small_config, rules, sim_settings)
    e2, g2 = _synth(small_config, rules, sim_settings)
    assert [e.submission_id for e in e1] == [e.submission_id for e in e2]
    assert g1.model_dump() == g2.model_dump()


def test_ground_truth_consistency(small_config, rules, sim_settings):
    events, gt = _synth(small_config, rules, sim_settings)
    by_id = {e.submission_id: e for e in events}
    rule_by_id = {r.id: r for r in rules.rules}

    for s in gt.submissions:
        ev = by_id[s.submission_id]
        assert len(ev.report_lines) == len(s.lines)
        # every line has a receipt URL in the blob store
        assert all(rl.receipt_url.startswith("blob://") for rl in ev.report_lines)

        if s.policy.verdict == "fail":
            # each violated rule really is an amount_cap the line exceeds
            assert s.policy.violated_rule_ids
            for rid in s.policy.violated_rule_ids:
                rule = rule_by_id[rid]
                assert rule.type is RuleType.amount_cap
                offending = [
                    ln for ln in s.lines
                    if rule.cap_for(ln.currency) is not None
                    and ln.amount > rule.cap_for(ln.currency)
                ]
                assert offending, f"{s.submission_id}: no line exceeds {rid}"
        else:
            assert s.policy.violated_rule_ids == []

        if s.manipulated:
            assert s.expected_authenticity_flags
            assert (s.expected_subtotal_variance_pct or 0) > 0

        if s.is_duplicate_of:
            assert s.is_duplicate_of in by_id
