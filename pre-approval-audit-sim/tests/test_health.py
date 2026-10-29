"""Milestone 0 exit criterion: FastAPI app responds on /health."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_ok(sim_settings):
    # Build a fresh app against the patched (sqlite_local) settings.
    from integration.app import create_app

    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["simulation_mode"] == "simulation"
        assert body["storage_backend"] == "sqlite_local"
        assert "submissions" in body["tables"]
        assert "receipt_embeddings" in body["tables"]


def test_webhook_routes_live_and_validate(sim_settings):
    # As of Phase 1 the webhook routes are implemented. An empty body fails
    # payload validation (422) rather than returning the Phase-0 501 stub -
    # proving the route now parses a real SubmissionCreatedEvent.
    from integration.app import create_app

    app = create_app()
    with TestClient(app) as client:
        assert client.post("/webhooks/submission-created").status_code == 422
        assert client.post("/webhooks/audit-decision").status_code == 422
