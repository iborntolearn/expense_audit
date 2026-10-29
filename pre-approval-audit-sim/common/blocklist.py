"""Merchant sanctions/PEP watchlist (BR-TE-AU-03).

A SIMULATED local watchlist, not a real OFAC/PEP data feed - same treatment as
every other 3rd-party integration in this build (Solution Design 10: real
sanctions/PEP screening services are an integration seam, not implemented
here). Vendor names extracted off a receipt are matched case-insensitively as
substrings against each entry's name.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from config.settings import REPO_ROOT

_DEFAULT_PATH = REPO_ROOT / "config" / "merchant_blocklist.yaml"


class BlocklistEntry(BaseModel):
    name: str
    type: str  # "sanctioned" | "pep"
    reason: str


class MerchantBlocklist(BaseModel):
    entries: list[BlocklistEntry] = Field(default_factory=list)

    def match(self, vendor: str) -> list[BlocklistEntry]:
        vendor_lower = vendor.lower()
        return [e for e in self.entries if e.name.lower() in vendor_lower]


def load_merchant_blocklist(path: Path = _DEFAULT_PATH) -> MerchantBlocklist:
    if not path.exists():
        return MerchantBlocklist(entries=[])
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return MerchantBlocklist.model_validate(raw)
