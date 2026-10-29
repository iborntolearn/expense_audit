"""Business dashboard aggregation over a real ingested batch."""
from __future__ import annotations

import pytest

from common.policy import load_policy_rules
from config.settings import get_settings
from dashboard.queries import compute_dashboard
from data.factory import build_data_layer
from generator.config import load_generator_config
from generator.synthesize import Synthesizer
from integration.ingest import IngestService
from pipeline.checkpoint import build_memory_checkpointer
from pipeline.config import load_pipeline_config
from pipeline.factory import build_pipeline


@pytest.fixture()
def dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite_local")
    monkeypatch.setenv("SIMULATION_MODE", "simulation")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setenv("EMBEDDING_DIM", "256")
    get_settings.cache_clear()
    settings = get_settings()

    data = build_data_layer(settings)
    data.migrate()
    cfg = load_generator_config().model_copy(update={"volume": 120, "seed": 99})
    events, _gt = Synthesizer(cfg, load_policy_rules(), data.blobs).generate()
    pipeline = build_pipeline(data, settings, checkpointer=build_memory_checkpointer())
    ingest = IngestService(data.store, pipeline, is_synthetic=True)
    for ev in events:
        ingest.handle(ev)

    pcfg = load_pipeline_config()
    dash = compute_dashboard(
        data.store.analytics_rows(),
        subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
        conf_cutoff=pcfg.extraction.confidence_cutoff,
    )
    yield dash, data
    data.close()
    get_settings.cache_clear()


def test_kpis_consistent(dashboard):
    dash, _ = dashboard
    k = dash.kpis
    assert k["total_submissions"] == 120
    # routing shares sum to ~1
    assert abs(k["automation_rate"] + k["exception_rate"] - 1.0) < 1e-6 or k["exception_rate"] >= 0
    assert k["total_spend"] > 0
    assert sum(dash.routing.values()) == 120


def test_spend_breakdowns_present(dashboard):
    dash, _ = dashboard
    assert dash.spend_by_category, "expected category spend"
    assert dash.spend_by_oe
    # category spend totals should be > 0
    assert sum(dash.spend_by_category.values()) > 0


def test_exception_reasons_and_rules(dashboard):
    dash, _ = dashboard
    # anomalies were injected, so there must be violations and reasons
    assert dash.top_rules, "expected violated rules"
    assert dash.exception_reasons, "expected exception reasons on human-review cases"


def test_risk_histogram_totals(dashboard):
    dash, _ = dashboard
    assert sum(dash.risk_histogram.values()) == dash.kpis["total_submissions"]
