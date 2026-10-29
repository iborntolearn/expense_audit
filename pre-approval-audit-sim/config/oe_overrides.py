"""Shared OE (operating-entity) config-override merge primitive.

Used by both `config_admin.py` (the Settings/System-Admin UI's raw-dict
editor - Phase 2 of multi-tenancy) and `pipeline/config.py` (live
per-submission config resolution - Phase 4). Kept dependency-free (no
pydantic models, no admin/UI-facing imports) so the live pipeline never has
to import `config_admin.py`, which would be a layering violation for core
business logic.

Each override file under `config/oe_overrides/{OE}/{name}.yaml` is a PARTIAL
document - only the keys an OE admin actually changed - deep-merged onto the
base `config/{name}.yaml` at read time, so a schema change to the base config
is picked up by every OE automatically instead of needing every override
file touched too.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from config.settings import REPO_ROOT

OE_OVERRIDES_DIR = REPO_ROOT / "config" / "oe_overrides"


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively layer `override` onto a copy of `base` - override wins at
    the leaf level; nested dicts merge key-by-key, everything else (scalars,
    lists) is replaced wholesale rather than combined."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def override_path(name: str, oe_code: str) -> Path:
    return OE_OVERRIDES_DIR / oe_code / f"{name}.yaml"


def load_merged_raw(base_path: Path, name: str, oe_code: Optional[str]) -> dict:
    base = yaml.safe_load(base_path.read_text(encoding="utf-8"))
    if oe_code is None:
        return base
    path = override_path(name, oe_code)
    if not path.exists():
        return base
    override = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return deep_merge(base, override)
