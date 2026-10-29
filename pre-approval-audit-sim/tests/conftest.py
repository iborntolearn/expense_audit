"""Shared test fixtures.

Forces the sqlite_local backend into a throwaway temp directory so tests never
touch a developer's real .data/ or require Docker/Postgres. Monkeypatched env
vars outrank the .env file in pydantic-settings, so no module reload is needed -
clearing the settings cache is sufficient.
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def sim_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite_local")
    monkeypatch.setenv("SIMULATION_MODE", "simulation")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setenv("EMBEDDING_DIM", "8")  # tiny dim keeps vector tests fast

    from config.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    yield settings
    get_settings.cache_clear()


@pytest.fixture()
def data_layer(sim_settings):
    from data.factory import build_data_layer

    dl = build_data_layer(sim_settings)
    dl.migrate()
    yield dl
    dl.close()
