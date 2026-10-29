"""Risk-based audit report list (Expense reports page)."""
from __future__ import annotations

import pytest

from common.policy import load_policy_rules
from config.settings import get_settings
from dashboard.queries import compute_expense_reports
from data.factory import build_data_layer
from generator.config import load_generator_config
from generator.synthesize import Synthesizer
from integration.ingest import IngestService
from pipeline.checkpoint import build_memory_checkpointer
from pipeline.config import load_pipeline_config
from pipeline.factory import build_pipeline


@pytest.fixture()
def reports(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite_local")
    monkeypatch.setenv("SIMULATION_MODE", "simulation")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setenv("EMBEDDING_DIM", "256")
    get_settings.cache_clear()
    settings = get_settings()
    data = build_data_layer(settings)
    data.migrate()
    cfg = load_generator_config().model_copy(update={"volume": 80, "seed": 3})
    events, _gt = Synthesizer(cfg, load_policy_rules(), data.blobs).generate()
    pipeline = build_pipeline(data, settings, checkpointer=build_memory_checkpointer())
    ingest = IngestService(data.store, pipeline, is_synthetic=True)
    for ev in events:
        ingest.handle(ev)
    pcfg = load_pipeline_config()
    out = compute_expense_reports(
        data.store.analytics_rows(),
        auto_approve_cutoff=pcfg.risk.auto_approve_cutoff,
        auto_reject_cutoff=pcfg.risk.auto_reject_cutoff,
        subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
        conf_cutoff=pcfg.extraction.confidence_cutoff,
    )
    data.close()
    yield out
    get_settings.cache_clear()


def test_one_row_per_submission(reports):
    assert len(reports) == 80
    assert len({r["submission_id"] for r in reports}) == 80


def test_bands_and_status_valid(reports):
    for r in reports:
        assert r["risk_band"] in {"LOW", "PENDING", "HIGH"}
        assert r["status"] in {"APPROVED", "REJECTED", "SUBMITTED"}
        assert r["total"] >= 0
        assert r["currency"]


def test_approved_reports_are_low_band(reports):
    # auto-approved reports are always low-risk (the converse isn't true: a
    # low-score case can still be routed to review by the low-confidence guardrail)
    approved = [r for r in reports if r["status"] == "APPROVED"]
    assert approved
    assert all(r["risk_band"] == "LOW" for r in approved)


def test_flagged_reports_have_reasons(reports):
    flagged = [r for r in reports if r["status"] == "SUBMITTED"]
    assert flagged
    assert all(r["risk_reason"] for r in flagged)
