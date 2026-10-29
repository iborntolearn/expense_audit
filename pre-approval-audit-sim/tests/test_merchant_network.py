"""Cross-employee merchant network analysis - AuditStore.
merchant_employee_spread/merchant_near_cap_clustering (live SQL aggregation,
category_amount_stats' precedent), VerificationAgent._merchant_network, and
RiskAgent's merchant_network_flag weight. Distinct from _merchant()'s
per-line blocklist/registry lookup (tests/test_merchant_registry.py) - this
looks at how a merchant is used ACROSS employees.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from adapters.embeddings import SimulatedEmbeddingClient
from common.policy import load_policy_rules
from common.schemas import AuditState, ExtractedLine, ReportLine, RoutingDecision, SourceSystem, SubmissionCreatedEvent, VerificationResult
from pipeline.agents.risk import RiskAgent
from pipeline.agents.verification import VerificationAgent
from pipeline.config import MerchantNetworkConfig, load_pipeline_config


def _event(sid, employee_id, category="meals", amount=50.0, oe="DE", currency="EUR",
           submitted_at=datetime(2026, 6, 1, tzinfo=timezone.utc)) -> SubmissionCreatedEvent:
    return SubmissionCreatedEvent(
        submission_id=sid, source_system=SourceSystem.simulation_harness,
        source_system_ref=sid, oe_code=oe, employee_id=employee_id, currency=currency,
        submitted_at=submitted_at,
        report_lines=[ReportLine(line_id="LN-1", category=category, entered_amount=amount,
                                  receipt_url=f"blob://{sid}/LN-1")],
    )


def _seed_line(data_layer, sid, *, vendor, employee_id, category="meals", amount=50.0, oe="DE",
               currency="EUR", submitted_at=datetime(2026, 6, 1, tzinfo=timezone.utc)):
    ev = _event(sid, employee_id, category=category, amount=amount, oe=oe, currency=currency,
                submitted_at=submitted_at)
    data_layer.store.save_submission(ev, is_synthetic=True)
    data_layer.store.save_extracted_lines(sid, [
        ExtractedLine(line_id="LN-1", vendor=vendor, amount=amount, tax=0.0, currency=currency, confidence=1.0),
    ])
    data_layer.store.save_report_lines(sid, [("LN-1", category, amount, currency)])


DEFAULT_CFG = MerchantNetworkConfig(
    enabled=True,
    new_merchant_employee_spread_window_days=7,
    new_merchant_employee_spread_threshold=5,
    new_merchant_max_prior_submissions=3,
    near_cap_clustering_window_days=30,
    near_cap_tolerance_pct=10.0,
    near_cap_min_distinct_employees=3,
    fuzzy_match_threshold=0.85,
)


# --------------------------------------------------------------------------- #
# AuditStore.merchant_employee_spread
def test_merchant_employee_spread_counts_distinct_employees(data_layer):
    for i in range(3):
        _seed_line(data_layer, f"SUB-SPREAD-{i}", vendor="Shell Co", employee_id=f"EMP-{i}")
    spread = data_layer.store.merchant_employee_spread("Shell Co", since_date="2026-01-01")
    assert spread["distinct_employees"] == 3
    assert spread["submissions"] == 3


def test_merchant_employee_spread_respects_since_date(data_layer):
    _seed_line(data_layer, "SUB-OLD", vendor="Old Vendor", employee_id="EMP-1",
               submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    spread = data_layer.store.merchant_employee_spread("Old Vendor", since_date="2026-06-01")
    assert spread["distinct_employees"] == 0


def test_merchant_employee_spread_normalizes_vendor(data_layer):
    _seed_line(data_layer, "SUB-NORM", vendor="  Mixed Case Co  ", employee_id="EMP-1")
    spread = data_layer.store.merchant_employee_spread("mixed case co", since_date="2026-01-01")
    assert spread["distinct_employees"] == 1


# --------------------------------------------------------------------------- #
# AuditStore.merchant_near_cap_clustering
def test_merchant_near_cap_clustering_counts_distinct_employees_near_cap(data_layer):
    # cap=100, tolerance 10% -> floor=90. Amounts at 95 count; 50 does not.
    for i in range(3):
        _seed_line(data_layer, f"SUB-CLUSTER-{i}", vendor="Cap Vendor", employee_id=f"EMP-{i}",
                   category="transport", amount=95.0)
    _seed_line(data_layer, "SUB-CLUSTER-LOW", vendor="Cap Vendor", employee_id="EMP-LOW",
               category="transport", amount=50.0)
    result = data_layer.store.merchant_near_cap_clustering(
        "Cap Vendor", "transport", "DE", 100.0, tolerance_pct=10.0, since_date="2026-01-01",
    )
    assert result["distinct_employees_near_cap"] == 3


def test_merchant_near_cap_clustering_scoped_by_oe_and_category(data_layer):
    _seed_line(data_layer, "SUB-OE-A", vendor="Cap Vendor 2", employee_id="EMP-A",
               category="transport", amount=95.0, oe="DE")
    _seed_line(data_layer, "SUB-OE-B", vendor="Cap Vendor 2", employee_id="EMP-B",
               category="transport", amount=95.0, oe="US")
    result = data_layer.store.merchant_near_cap_clustering(
        "Cap Vendor 2", "transport", "DE", 100.0, tolerance_pct=10.0, since_date="2026-01-01",
    )
    assert result["distinct_employees_near_cap"] == 1


# --------------------------------------------------------------------------- #
# VerificationAgent._merchant_network
@pytest.fixture()
def verification_agent(data_layer):
    rules = load_policy_rules()
    return VerificationAgent(
        data_layer.blobs, SimulatedEmbeddingClient(8), data_layer.vectors,
        store=data_layer.store, rules=rules,
    )


def test_new_vendor_multi_employee_flag_fires(verification_agent, data_layer):
    for i in range(5):
        _seed_line(data_layer, f"SUB-MULTI-{i}", vendor="Rare Shell Vendor", employee_id=f"EMP-{i}")

    state = AuditState(submission_id="SUB-MULTI-TEST")
    state.extracted_lines = [
        ExtractedLine(line_id="LN-1", vendor="Rare Shell Vendor", amount=50.0, tax=0.0,
                      currency="EUR", confidence=1.0),
    ]
    event = _event("SUB-MULTI-TEST", "EMP-TEST")
    flags = verification_agent._merchant_network(state, event, DEFAULT_CFG)
    assert any("new_vendor_multi_employee" in f for f in flags)

    # Registry should now reflect the auto-flag.
    row = data_layer.store.get_merchant("Rare Shell Vendor")
    assert row["status"] == "watch"


def test_new_vendor_flag_does_not_fire_for_well_established_vendor(verification_agent, data_layer):
    for i in range(10):
        _seed_line(data_layer, f"SUB-ESTABLISHED-{i}", vendor="Established Vendor", employee_id=f"EMP-{i}")
    # Bump submission_count above new_merchant_max_prior_submissions.
    for _ in range(10):
        data_layer.store.upsert_merchant_seen("Established Vendor")

    state = AuditState(submission_id="SUB-EST-TEST")
    state.extracted_lines = [
        ExtractedLine(line_id="LN-1", vendor="Established Vendor", amount=50.0, tax=0.0,
                      currency="EUR", confidence=1.0),
    ]
    event = _event("SUB-EST-TEST", "EMP-TEST")
    flags = verification_agent._merchant_network(state, event, DEFAULT_CFG)
    assert not any("new_vendor_multi_employee" in f for f in flags)


def test_cross_employee_threshold_clustering_flag_fires(verification_agent, data_layer):
    # Look up the REAL transport cap (USD) rather than hardcoding a value
    # that may not match config/policy_rules.yaml, and seed amounts just
    # under it (within DEFAULT_CFG's 10% near_cap_tolerance_pct).
    rules = load_policy_rules()
    caps = rules.amount_cap_rules_for(category="transport", oe_code="DE", currency="USD")
    cap = caps[0].cap_for("USD")
    near_cap_amount = round(cap * 0.96, 2)

    for i in range(3):
        _seed_line(data_layer, f"SUB-STRUCT-{i}", vendor="Threshold Vendor", employee_id=f"EMP-{i}",
                   category="transport", amount=near_cap_amount, currency="USD")

    state = AuditState(submission_id="SUB-STRUCT-TEST")
    state.extracted_lines = [
        ExtractedLine(line_id="LN-1", vendor="Threshold Vendor", amount=near_cap_amount, tax=0.0,
                      currency="USD", confidence=1.0),
    ]
    event = _event("SUB-STRUCT-TEST", "EMP-TEST", category="transport", amount=near_cap_amount,
                   currency="USD")
    flags = verification_agent._merchant_network(state, event, DEFAULT_CFG)
    assert any("cross_employee_threshold_clustering" in f for f in flags)


def test_fuzzy_watchlist_match_fires_for_near_variant(verification_agent, data_layer):
    data_layer.store.set_merchant_status(
        "Sanctioned Trading Co", status="blocked", risk_tier="high",
        reason="test seed", source="admin_override", force=True,
    )
    state = AuditState(submission_id="SUB-FUZZY")
    state.extracted_lines = [
        ExtractedLine(line_id="LN-1", vendor="Sanctioned Trading Company", amount=50.0, tax=0.0,
                      currency="EUR", confidence=1.0),
    ]
    event = _event("SUB-FUZZY", "EMP-TEST")
    flags = verification_agent._merchant_network(state, event, DEFAULT_CFG)
    assert any("fuzzy_watchlist_match" in f for f in flags)


def test_fuzzy_watchlist_match_no_false_positive_for_unrelated_vendor(verification_agent, data_layer):
    data_layer.store.set_merchant_status(
        "Sanctioned Trading Co", status="blocked", source="admin_override", force=True,
    )
    state = AuditState(submission_id="SUB-UNRELATED")
    state.extracted_lines = [
        ExtractedLine(line_id="LN-1", vendor="Totally Different Grocery Store", amount=50.0, tax=0.0,
                      currency="EUR", confidence=1.0),
    ]
    event = _event("SUB-UNRELATED", "EMP-TEST")
    flags = verification_agent._merchant_network(state, event, DEFAULT_CFG)
    assert not any("fuzzy_watchlist_match" in f for f in flags)


def test_admin_override_not_downgraded_by_network_auto_flag(verification_agent, data_layer):
    data_layer.store.set_merchant_status(
        "Protected Vendor", status="clear", updated_by="admin1", source="admin_override", force=True,
    )
    for i in range(5):
        _seed_line(data_layer, f"SUB-PROTECTED-{i}", vendor="Protected Vendor", employee_id=f"EMP-{i}")

    state = AuditState(submission_id="SUB-PROTECTED-TEST")
    state.extracted_lines = [
        ExtractedLine(line_id="LN-1", vendor="Protected Vendor", amount=50.0, tax=0.0,
                      currency="EUR", confidence=1.0),
    ]
    event = _event("SUB-PROTECTED-TEST", "EMP-TEST")
    verification_agent._merchant_network(state, event, DEFAULT_CFG)

    row = data_layer.store.get_merchant("Protected Vendor")
    assert row["status"] == "clear"
    assert row["source"] == "admin_override"


def test_disabled_config_returns_no_flags(verification_agent, data_layer):
    for i in range(5):
        _seed_line(data_layer, f"SUB-DIS-{i}", vendor="Disabled Check Vendor", employee_id=f"EMP-{i}")
    cfg = DEFAULT_CFG.model_copy(update={"enabled": False})
    state = AuditState(submission_id="SUB-DIS-TEST")
    state.extracted_lines = [
        ExtractedLine(line_id="LN-1", vendor="Disabled Check Vendor", amount=50.0, tax=0.0,
                      currency="EUR", confidence=1.0),
    ]
    event = _event("SUB-DIS-TEST", "EMP-TEST")
    assert verification_agent._merchant_network(state, event, cfg) == []


def test_no_store_degrades_quietly(data_layer):
    agent = VerificationAgent(data_layer.blobs, SimulatedEmbeddingClient(8), data_layer.vectors, store=None)
    state = AuditState(submission_id="SUB-NO-STORE")
    state.extracted_lines = [
        ExtractedLine(line_id="LN-1", vendor="Anyone", amount=50.0, tax=0.0,
                      currency="EUR", confidence=1.0),
    ]
    event = _event("SUB-NO-STORE", "EMP-TEST")
    assert agent._merchant_network(state, event, DEFAULT_CFG) == []


# --------------------------------------------------------------------------- #
# RiskAgent weight wiring
def test_risk_agent_applies_merchant_network_weight():
    state = AuditState(submission_id="SUB-RISK-1")
    state.verification = VerificationResult(
        merchant_network_flags=["new_vendor_multi_employee: 'X' used by 5 distinct employees..."],
    )
    event = _event("SUB-RISK-1", "EMP-1")
    RiskAgent().run(state, event)
    weight = load_pipeline_config().risk.weights["merchant_network_flag"]
    assert state.risk_score >= weight
    assert "merchant network signal" in state.explanation
