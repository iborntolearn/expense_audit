"""Per-OE override storage for pipeline/generator/thresholds - the base YAML
file (config/{name}.yaml) plus a DB-backed override document per OE,
replacing the old file-based config/oe_overrides/{OE}/{name}.yaml documents.

Validation stays in config_admin.py (the pydantic model differs per config
name); this only owns the merge/persistence primitive. `policy_rules.yaml` is
untouched - see config_admin.py::load_policy/save_policy, which has its own
OE-filtering logic and stays fully YAML-native.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from config.oe_overrides import deep_merge
from data.interfaces import ConfigStore


class OeConfigService:
    def __init__(self, config: ConfigStore):
        self._config = config

    def load_merged(self, base_path: Path, name: str, oe_code: str) -> dict:
        """`oe_code` here is always a real OE code - callers with oe_code=None
        should read the base YAML directly and never reach this service at
        all (see config_admin.py's load_pipeline/load_generator/
        load_thresholds)."""
        base = yaml.safe_load(base_path.read_text(encoding="utf-8"))
        override = self._config.get_override(name, oe_code)
        return deep_merge(base, override) if override else base

    def save(self, name: str, oe_code: str, data: dict) -> None:
        self._config.save_override(name, oe_code, data)
