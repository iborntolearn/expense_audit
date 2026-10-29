"""Settings config-admin: validated round-trip saves + .env updates."""
from __future__ import annotations

import shutil

import pytest

import config_admin as ca
from config.settings import REPO_ROOT


@pytest.fixture()
def temp_configs(tmp_path, monkeypatch):
    # copy real configs to a temp dir and point config_admin at them
    src = REPO_ROOT / "config"
    for name in ("pipeline.yaml", "thresholds.yaml", "generator.yaml"):
        shutil.copy(src / name, tmp_path / name)
    monkeypatch.setattr(ca, "PIPELINE_YAML", tmp_path / "pipeline.yaml")
    monkeypatch.setattr(ca, "THRESHOLDS_YAML", tmp_path / "thresholds.yaml")
    monkeypatch.setattr(ca, "GENERATOR_YAML", tmp_path / "generator.yaml")
    monkeypatch.setattr(ca, "ENV_FILE", tmp_path / ".env")
    return tmp_path


def test_pipeline_roundtrip(temp_configs):
    pc = ca.load_raw(ca.PIPELINE_YAML)
    pc["risk"]["auto_reject_cutoff"] = 0.66
    ca.save_pipeline(pc)
    assert ca.load_raw(ca.PIPELINE_YAML)["risk"]["auto_reject_cutoff"] == 0.66


def test_pipeline_invalid_rejected(temp_configs):
    pc = ca.load_raw(ca.PIPELINE_YAML)
    del pc["risk"]  # required section
    with pytest.raises(Exception):
        ca.save_pipeline(pc)


def test_generator_invalid_rejected(temp_configs):
    g = ca.load_raw(ca.GENERATOR_YAML)
    g["volume"] = 0  # ge=1
    with pytest.raises(Exception):
        ca.save_generator(g)


def test_env_update_and_read(temp_configs):
    ca.update_env({"LLM_VISION_MODEL": "claude-test-x", "EMBEDDING_DIM": "512"})
    assert ca.env_value("LLM_VISION_MODEL") == "claude-test-x"
    assert ca.env_value("EMBEDDING_DIM") == "512"
    # secret not echoed anywhere except the file it was written to
    ca.update_env({"ANTHROPIC_API_KEY": "sk-secret"})
    assert ca.env_value("ANTHROPIC_API_KEY") == "sk-secret"
