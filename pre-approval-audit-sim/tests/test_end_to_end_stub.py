"""Milestone 3 exit criterion: a harness-generated submission event reaches the
(stub) pipeline end-to-end and a decision is written to the store. Also covers
idempotency and the SIMULATION_MODE gate."""
from __future__ import annotations

import pytest

from common.policy import load_policy_rules
from data.factory import build_data_layer
from generator.config import load_generator_config
from generator.synthesize import Synthesizer
from integration.ingest import IngestService
from pipeline.stub import build_pipeline


@pytest.fixture()
def events(sim_settings):
    cfg = load_generator_config().model_copy(update={"volume": 20, "seed": 7})
    data = build_data_layer(sim_settings)
    try:
        evs, _ = Synthesizer(cfg, load_policy_rules(), data.blobs).generate()
    finally:
        data.close()
    return evs


def test_event_reaches_pipeline_and_decision_persisted(events, data_layer):
    ingest = IngestService(
        data_layer.store,
        build_pipeline(data_layer.store),
        is_synthetic=True,
    )
    ev = events[0]
    result = ingest.handle(ev)

    assert result.accepted is True
    assert result.state.routing_decision is not None
    # decision is durable
    assert data_layer.store.has_decision(ev.submission_id) is True
    row = data_layer.store.get_submission(ev.submission_id)
    assert row is not None
    assert row["is_synthetic"] in (1, True)


def test_idempotent_redelivery(events, data_layer):
    ingest = IngestService(
        data_layer.store,
        build_pipeline(data_layer.store),
        is_synthetic=True,
    )
    ev = events[0]
    first = ingest.handle(ev)
    second = ingest.handle(ev)  # webhook retry
    assert first.accepted is True
    assert second.accepted is False
    assert second.reason == "already_processed"


def test_full_batch_via_harness(events, data_layer):
    from integration.bus import InProcessBus
    from integration.harness import SimulationHarness  # noqa: F401 (import parity)

    ingest = IngestService(
        data_layer.store,
        build_pipeline(data_layer.store),
        is_synthetic=True,
    )
    bus = InProcessBus()
    bus.subscribe(lambda e: ingest.handle(e))
    for ev in events:
        bus.publish(ev)

    # every submission now has a decision
    assert all(data_layer.store.has_decision(ev.submission_id) for ev in events)


def test_live_mode_gate_rejects(sim_settings, monkeypatch):
    monkeypatch.setenv("SIMULATION_MODE", "live")
    from config.settings import get_settings

    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from integration.app import create_app

    app = create_app()
    with TestClient(app) as client:
        # a minimal valid payload; the gate should reject before processing
        payload = {
            "submission_id": "SUB-LIVE-1",
            "source_system": "concur",
            "source_system_ref": "X",
            "oe_code": "DE",
            "employee_id": "EMP-1",
            "currency": "EUR",
            "submitted_at": "2026-07-16T08:41:00Z",
            "report_lines": [],
        }
        resp = client.post("/webhooks/submission-created", json=payload)
        assert resp.status_code == 501
    get_settings.cache_clear()
