"""Apply schema migrations to the active backend.

Usage (from repo root):
    python scripts/migrate.py
Honours STORAGE_BACKEND from .env / environment.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a plain script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings  # noqa: E402
from data.factory import build_data_layer  # noqa: E402


def main() -> int:
    settings = get_settings()
    data = build_data_layer(settings)
    data.migrate()
    ok = data.health()
    print(f"backend={settings.storage_backend.value} migrated; health={'ok' if ok else 'FAILED'}")
    print("tables:", ", ".join(sorted(data.store.table_names())))
    data.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
