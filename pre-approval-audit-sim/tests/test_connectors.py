"""Integration connectors (Cytric, Oracle E-Business Suite, Workday, SAP
Concur) - Simulated* classes tested directly (deterministic, offline); Real*
classes get a construction-only test (missing credentials raises
RuntimeError, same as adapters/vision.py's real extractors) - no live-API
test, matching this repo's `pragma: no cover` convention."""
from __future__ import annotations

import pytest

from adapters.connectors.concur import RealConcurConnector, SimulatedConcurConnector
from adapters.connectors.config import ConnectorsConfig, load_connectors_config, save_connectors_config
from adapters.connectors.cytric import RealCytricConnector, SimulatedCytricConnector
from adapters.connectors.factory import build_connectors
from adapters.connectors.oracle_ebs import RealOracleEbsConnector, SimulatedOracleEbsConnector
from adapters.connectors.workday import RealWorkdayConnector, SimulatedWorkdayConnector
from common.schemas import AuditDecisionWriteback, DecisionStatus, SourceSystem


@pytest.fixture()
def sim_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite_local")
    monkeypatch.setenv("SIMULATION_MODE", "simulation")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setenv("EMBEDDING_DIM", "8")

    from config.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    yield settings
    get_settings.cache_clear()


@pytest.fixture()
def blobs(sim_settings):
    from data.backends.local_blob import LocalBlobStore

    return LocalBlobStore(sim_settings.blob_dir)


# --------------------------------------------------------------------- Concur/Cytric
def test_simulated_concur_connector(blobs):
    connector = SimulatedConcurConnector(blobs, batch_size=3)
    assert connector.health_check() is True
    events = connector.fetch_new_submissions()
    assert len(events) == 3
    assert all(e.source_system == SourceSystem.concur for e in events)
    # post_decision must not raise, even with no real system behind it.
    connector.post_decision(AuditDecisionWriteback(
        submission_id=events[0].submission_id, decision=DecisionStatus.approved,
        decision_timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    ))


def test_simulated_cytric_connector(blobs):
    connector = SimulatedCytricConnector(blobs, batch_size=2)
    assert connector.health_check() is True
    events = connector.fetch_new_submissions()
    assert len(events) == 2
    assert all(e.source_system == SourceSystem.cytric for e in events)


def test_real_concur_connector_requires_credentials():
    with pytest.raises(RuntimeError):
        RealConcurConnector("", "", "")


def test_real_cytric_connector_requires_credentials():
    with pytest.raises(RuntimeError):
        RealCytricConnector("", "", "")


# --------------------------------------------------------------------- Workday
def test_simulated_workday_connector_deterministic():
    connector = SimulatedWorkdayConnector()
    assert connector.health_check() is True
    first = connector.get_employee("EMP-0007")
    second = connector.get_employee("EMP-0007")
    assert first == second
    assert first.employee_id == "EMP-0007"
    assert first.manager_id != "EMP-0007"  # never its own manager


def test_simulated_workday_connector_empty_id():
    assert SimulatedWorkdayConnector().get_employee("") is None


def test_real_workday_connector_requires_credentials():
    with pytest.raises(RuntimeError):
        RealWorkdayConnector("", "", "", "")


# --------------------------------------------------------------------- Oracle EBS
def test_simulated_oracle_ebs_connector():
    connector = SimulatedOracleEbsConnector()
    assert connector.health_check() is True
    cc = connector.get_cost_center("CC-001", "US")
    assert cc.cost_center == "CC-001" and cc.oe_code == "US"
    vendor = connector.get_vendor("V-123")
    assert vendor.vendor_id == "V-123"


def test_real_oracle_ebs_connector_requires_credentials():
    with pytest.raises(RuntimeError):
        RealOracleEbsConnector("", "", "")


# --------------------------------------------------------------------- config + factory
def test_load_connectors_config_defaults_to_simulated(tmp_path):
    missing = tmp_path / "nonexistent.yaml"
    cfg = load_connectors_config(missing)
    assert cfg == ConnectorsConfig()


def test_save_and_load_connectors_config_roundtrip(tmp_path):
    path = tmp_path / "connectors.yaml"
    cfg = ConnectorsConfig(submission_source="concur", employee_directory="workday",
                           finance_master="oracle_ebs")
    save_connectors_config(cfg, path)
    reloaded = load_connectors_config(path)
    assert reloaded == cfg


def test_build_connectors_all_simulated(sim_settings, blobs):
    cfg = ConnectorsConfig()
    registry = build_connectors(sim_settings, cfg, blobs)
    assert registry.submission_source.health_check() is True
    assert registry.employee_directory.health_check() is True
    assert registry.finance_master.health_check() is True


def test_build_connectors_unknown_provider_raises(sim_settings, blobs):
    cfg = ConnectorsConfig(submission_source="bogus")
    with pytest.raises(ValueError):
        build_connectors(sim_settings, cfg, blobs)
