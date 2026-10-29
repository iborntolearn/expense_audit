"""Merchant registry (BR-TE-AU-03 successor) - AuditStore.
bootstrap_merchant_registry/upsert_merchant_seen/get_merchant/
list_merchant_registry/set_merchant_status, and VerificationAgent._merchant's
union of the YAML blocklist with the registry table. The registry replaces
the flat merchant_blocklist.yaml as the live source of truth, bootstrapped
from it once (mirrors the policy_rules.yaml -> DB migration this session).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from adapters.embeddings import SimulatedEmbeddingClient
from common.schemas import AuditState, ExtractedLine, ReportLine, SourceSystem, SubmissionCreatedEvent
from pipeline.agents.verification import VerificationAgent


def _event(sid) -> SubmissionCreatedEvent:
    return SubmissionCreatedEvent(
        submission_id=sid, source_system=SourceSystem.simulation_harness,
        source_system_ref=sid, oe_code="DE", employee_id="EMP-1", currency="EUR",
        submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        report_lines=[ReportLine(line_id="LN-1", category="meals", entered_amount=50.0,
                                  receipt_url=f"blob://{sid}/LN-1")],
    )


# --------------------------------------------------------------------------- #
# Bootstrap - data_layer.migrate() already ran once via the fixture
def test_bootstrap_seeds_from_yaml(data_layer):
    from common.blocklist import load_merchant_blocklist

    blocklist = load_merchant_blocklist()
    rows = data_layer.store.list_merchant_registry()
    assert len(rows) == len(blocklist.entries)
    keys = {r["merchant_key"] for r in rows}
    assert all(e.name.strip().lower() in keys for e in blocklist.entries)
    assert all(r["status"] == "blocked" and r["source"] == "bootstrap_yaml" for r in rows)


def test_bootstrap_is_only_ever_seeded_once(data_layer):
    before = data_layer.store.list_merchant_registry()
    surviving_key = before[0]["merchant_key"]
    data_layer.store.set_merchant_status(surviving_key, status="clear", updated_by="tester", force=True)

    data_layer.migrate()

    after = {r["merchant_key"]: r for r in data_layer.store.list_merchant_registry()}
    assert after[surviving_key]["status"] == "clear"  # bootstrap did NOT reset the edit


# --------------------------------------------------------------------------- #
# upsert_merchant_seen
def test_upsert_merchant_seen_first_time_creates_clear_row(data_layer):
    data_layer.store.upsert_merchant_seen("Brand New Vendor")
    row = data_layer.store.get_merchant("Brand New Vendor")
    assert row is not None
    assert row["status"] == "clear"
    assert row["submission_count"] == 1


def test_upsert_merchant_seen_repeat_increments_count(data_layer):
    data_layer.store.upsert_merchant_seen("Repeat Vendor")
    data_layer.store.upsert_merchant_seen("Repeat Vendor")
    data_layer.store.upsert_merchant_seen("Repeat Vendor")
    row = data_layer.store.get_merchant("Repeat Vendor")
    assert row["submission_count"] == 3


def test_get_merchant_normalizes_key(data_layer):
    data_layer.store.upsert_merchant_seen("  Mixed Case Vendor  ")
    assert data_layer.store.get_merchant("mixed case vendor") is not None
    assert data_layer.store.get_merchant("MIXED CASE VENDOR") is not None


# --------------------------------------------------------------------------- #
# set_merchant_status - admin-override guard
def test_set_merchant_status_creates_new_row(data_layer):
    data_layer.store.set_merchant_status(
        "New Suspicious Vendor", status="watch", risk_tier="medium",
        reason="flagged in testing", source="auto",
    )
    row = data_layer.store.get_merchant("New Suspicious Vendor")
    assert row["status"] == "watch"
    assert row["risk_tier"] == "medium"


def test_admin_override_not_downgraded_by_auto_flag(data_layer):
    data_layer.store.set_merchant_status(
        "Vendor X", status="clear", updated_by="admin1", source="admin_override", force=True,
    )
    # A subsequent auto-flag (source="auto", no force) must NOT override the
    # admin's explicit verdict.
    data_layer.store.set_merchant_status("Vendor X", status="watch", source="auto")
    row = data_layer.store.get_merchant("Vendor X")
    assert row["status"] == "clear"
    assert row["source"] == "admin_override"


def test_admin_override_downgrade_allowed_with_force(data_layer):
    data_layer.store.set_merchant_status(
        "Vendor Y", status="clear", updated_by="admin1", source="admin_override", force=True,
    )
    data_layer.store.set_merchant_status(
        "Vendor Y", status="blocked", updated_by="admin2", source="admin_override", force=True,
    )
    row = data_layer.store.get_merchant("Vendor Y")
    assert row["status"] == "blocked"


def test_list_merchant_registry_filters_by_status(data_layer):
    data_layer.store.set_merchant_status("Watch Vendor", status="watch", source="auto")
    data_layer.store.set_merchant_status("Clear Vendor", status="clear", source="auto")
    watched = data_layer.store.list_merchant_registry(status="watch")
    assert {r["merchant_key"] for r in watched} >= {"watch vendor"}
    assert "clear vendor" not in {r["merchant_key"] for r in watched}


# --------------------------------------------------------------------------- #
# VerificationAgent._merchant - union of YAML blocklist + registry
@pytest.fixture()
def verification_agent(data_layer):
    return VerificationAgent(
        data_layer.blobs, SimulatedEmbeddingClient(8), data_layer.vectors, store=data_layer.store,
    )


def test_merchant_check_catches_registry_only_blocked_vendor(verification_agent, data_layer):
    # NOT in merchant_blocklist.yaml - only in the registry (e.g. auto-flagged
    # by network analysis, or an admin's manual block).
    data_layer.store.set_merchant_status(
        "Shady Vendor Co", status="blocked", risk_tier="high",
        reason="manually blocked", source="admin_override", force=True,
    )
    state = AuditState(submission_id="SUB-1")
    state.extracted_lines = [
        ExtractedLine(line_id="LN-1", vendor="Shady Vendor Co", amount=50.0, tax=0.0,
                      currency="EUR", confidence=1.0),
    ]
    validation, flags = verification_agent._merchant(state, _event("SUB-1"))
    assert validation.value == "fail"
    assert any("Shady Vendor Co" in f for f in flags)


def test_merchant_check_passes_clean_vendor(verification_agent):
    state = AuditState(submission_id="SUB-2")
    state.extracted_lines = [
        ExtractedLine(line_id="LN-1", vendor="Perfectly Normal Vendor", amount=50.0, tax=0.0,
                      currency="EUR", confidence=1.0),
    ]
    validation, flags = verification_agent._merchant(state, _event("SUB-2"))
    assert validation.value == "pass"
    assert flags == []


def test_merchant_check_unverified_with_no_blocklist_and_no_store():
    agent = VerificationAgent(None, SimulatedEmbeddingClient(8), None, store=None, blocklist=None)
    state = AuditState(submission_id="SUB-3")
    state.extracted_lines = [
        ExtractedLine(line_id="LN-1", vendor="Anyone", amount=50.0, tax=0.0,
                      currency="EUR", confidence=1.0),
    ]
    validation, flags = agent._merchant(state, _event("SUB-3"))
    assert validation.value == "unverified"
    assert flags == []


def test_run_tracks_merchant_seen(verification_agent, data_layer):
    state = AuditState(submission_id="SUB-TRACK")
    state.extracted_lines = [
        ExtractedLine(line_id="LN-1", vendor="Tracked Vendor", amount=50.0, tax=0.0,
                      currency="EUR", confidence=1.0),
    ]
    verification_agent.run(state, _event("SUB-TRACK"))
    row = data_layer.store.get_merchant("Tracked Vendor")
    assert row is not None
    assert row["submission_count"] == 1
