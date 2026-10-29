"""Milestone 9: reviewer workflow. Headless (no browser) - drives the same
service the Streamlit UI calls. Proves a flagged case is visible with evidence
and that a reviewer decision resumes the checkpointed graph across a fresh
process/service instance."""
from __future__ import annotations

import pytest

from common.policy import load_policy_rules
from config.settings import get_settings
from data.factory import build_data_layer
from generator.config import load_generator_config
from generator.synthesize import Synthesizer
from integration.ingest import IngestService
from pipeline.factory import build_pipeline
from review_ui.service import ReviewService, build_review_service


@pytest.fixture()
def ingested(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite_local")
    monkeypatch.setenv("SIMULATION_MODE", "simulation")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setenv("CHECKPOINT_PATH", str(tmp_path / "checkpoints.db"))
    monkeypatch.setenv("EMBEDDING_DIM", "256")
    get_settings.cache_clear()
    settings = get_settings()

    # Ingest a batch exactly as production would (populates receipt_refs +
    # durable checkpoints for the suspended human-review cases).
    data = build_data_layer(settings)
    data.migrate()
    cfg = load_generator_config().model_copy(update={"volume": 60, "seed": 99})
    events, _gt = Synthesizer(cfg, load_policy_rules(), data.blobs).generate()
    pipeline = build_pipeline(data, settings)
    ingest = IngestService(data.store, pipeline, is_synthetic=True)
    for ev in events:
        ingest.handle(ev)
    data.close()
    yield settings
    get_settings.cache_clear()


def test_queue_lists_cases_with_evidence(ingested):
    # Fresh service instance = simulates the separate Streamlit process.
    svc = build_review_service(ingested)
    try:
        q = svc.queue()
        assert q, "expected human-review cases in the queue"
        detail = svc.detail(q[0]["submission_id"])
        assert detail["extracted_lines"], "case should show extracted lines"
        assert detail["receipts"], "case should show receipt evidence"
        # evidence bytes are retrievable from the blob store
        blob = svc.receipt_bytes(detail["receipts"][0]["receipt_url"])
        assert isinstance(blob, (bytes, bytearray)) and len(blob) > 0
    finally:
        svc.close()


def test_decision_resumes_graph_and_leaves_queue(ingested):
    svc = build_review_service(ingested)
    try:
        q = svc.queue()
        sid = q[0]["submission_id"]
        assert svc._pipeline.is_suspended(sid) is True

        svc.submit_decision(sid, reviewer_id="REV-9", approved=True, notes="verified")

        assert svc._pipeline.is_suspended(sid) is False  # graph completed
        remaining = {c["submission_id"] for c in svc.queue()}
        assert sid not in remaining, "resolved case must leave the queue"
    finally:
        svc.close()
