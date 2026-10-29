"""Ask engine intent coverage."""
from __future__ import annotations

import pytest

from assistant.engine import answer
from common.policy import load_policy_rules
from config.settings import get_settings
from data.factory import build_data_layer
from generator.config import load_generator_config
from generator.synthesize import Synthesizer
from integration.ingest import IngestService
from pipeline.checkpoint import build_memory_checkpointer
from pipeline.config import load_pipeline_config
from pipeline.factory import build_pipeline


@pytest.fixture()
def rows(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite_local")
    monkeypatch.setenv("SIMULATION_MODE", "simulation")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setenv("EMBEDDING_DIM", "256")
    get_settings.cache_clear()
    settings = get_settings()
    data = build_data_layer(settings)
    data.migrate()
    cfg = load_generator_config().model_copy(update={"volume": 80, "seed": 13})
    events, _gt = Synthesizer(cfg, load_policy_rules(), data.blobs).generate()
    pipeline = build_pipeline(data, settings, checkpointer=build_memory_checkpointer())
    ingest = IngestService(data.store, pipeline, is_synthetic=True)
    for ev in events:
        ingest.handle(ev)
    out = data.store.analytics_rows()
    data.close()
    yield out
    get_settings.cache_clear()


def _ask(rows, q):
    pcfg = load_pipeline_config()
    return answer(q, rows, subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
                  conf_cutoff=pcfg.extraction.confidence_cutoff,
                  auto_reject_cutoff=pcfg.risk.auto_reject_cutoff)


def test_unauthorized_spend(rows):
    a = _ask(rows, "Show me all employee unauthorized spend")
    assert a.metric and a.metric[0] == "Total unauthorized spend"
    assert a.chart and a.chart["data"]
    assert a.table


def test_unauthorized_by_category(rows):
    a = _ask(rows, "unauthorized spend by category")
    assert a.table and "Unauthorized category" in a.table[0]


def test_duplicates(rows):
    a = _ask(rows, "how many duplicates were found?")
    assert a.metric and a.metric[0] == "Duplicate reports"


def test_automation(rows):
    a = _ask(rows, "what is the automation rate?")
    assert a.metric and a.metric[0] == "Automation rate"
    assert a.metric[1].endswith("%")


def test_top_spenders(rows):
    a = _ask(rows, "top spenders")
    assert a.chart and a.chart["value"] == "Spend"


def test_fallback(rows):
    a = _ask(rows, "make me a sandwich")
    assert a.suggestions
