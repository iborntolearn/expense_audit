"""User analytics profile aggregation."""
from __future__ import annotations

import pytest

from common.policy import load_policy_rules
from config.settings import get_settings
from dashboard.queries import compute_company_abi, list_employees, user_analytics
from data.factory import build_data_layer
from generator.config import load_generator_config
from generator.synthesize import Synthesizer
from integration.ingest import IngestService
from pipeline.checkpoint import build_memory_checkpointer
from pipeline.config import load_pipeline_config
from pipeline.factory import build_pipeline


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite_local")
    monkeypatch.setenv("SIMULATION_MODE", "simulation")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setenv("EMBEDDING_DIM", "256")
    get_settings.cache_clear()
    settings = get_settings()
    data = build_data_layer(settings)
    data.migrate()
    cfg = load_generator_config().model_copy(update={"volume": 80, "seed": 11})
    events, _gt = Synthesizer(cfg, load_policy_rules(), data.blobs).generate()
    pipeline = build_pipeline(data, settings, checkpointer=build_memory_checkpointer())
    ingest = IngestService(data.store, pipeline, is_synthetic=True)
    for ev in events:
        ingest.handle(ev)
    rows = data.store.analytics_rows()
    data.close()
    yield rows
    get_settings.cache_clear()


def test_employees_listed(env):
    emps = list_employees(env)
    assert emps and all(e.startswith("EMP-") for e in emps)


def test_user_analytics_shape(env):
    pcfg = load_pipeline_config()
    emp = list_employees(env)[0]
    ua = user_analytics(
        env, emp,
        subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
        conf_cutoff=pcfg.extraction.confidence_cutoff,
        auto_reject_cutoff=pcfg.risk.auto_reject_cutoff,
    )
    k = ua["kpis"]
    assert k["total_reports"] > 0
    assert 0 <= k["abi_score"] <= 100
    assert k["te_spend"] >= 0
    assert k["auto_approved"] <= k["total_reports"]
    assert isinstance(ua["spend_by_type"], dict)
    assert isinstance(ua["behavioral_trends"], list)
    assert ua["company_abi"]  # non-empty distribution


def test_company_abi_covers_all_employees(env):
    pcfg = load_pipeline_config()
    abi = compute_company_abi(
        env, subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
        conf_cutoff=pcfg.extraction.confidence_cutoff,
    )
    assert set(abi) == set(list_employees(env))
    assert all(0 <= v <= 100 for v in abi.values())
