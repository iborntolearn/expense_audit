"""Connectors configuration model (loads config/connectors.yaml).

Which provider is active per connector role - "simulated" or a real one.
Credentials themselves live in Settings/.env (config/settings.py), matching
the existing pipeline.yaml (config-as-code) / Settings (secrets) split.
Connector selection is NOT OE-scoped (unlike pipeline.yaml) - a single set of
external-system credentials serves the whole deployment.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from config.settings import REPO_ROOT

_DEFAULT_PATH = REPO_ROOT / "config" / "connectors.yaml"


class ConnectorsConfig(BaseModel):
    submission_source: str = "simulated"    # "simulated" | "concur" | "cytric"
    employee_directory: str = "simulated"   # "simulated" | "workday"
    finance_master: str = "simulated"       # "simulated" | "oracle_ebs"


def load_connectors_config(path: Path | None = None) -> ConnectorsConfig:
    p = path or _DEFAULT_PATH
    if not p.exists():
        return ConnectorsConfig()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return ConnectorsConfig.model_validate(raw)


def save_connectors_config(cfg: ConnectorsConfig, path: Path | None = None) -> None:
    p = path or _DEFAULT_PATH
    p.write_text(
        yaml.safe_dump(cfg.model_dump(), sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
