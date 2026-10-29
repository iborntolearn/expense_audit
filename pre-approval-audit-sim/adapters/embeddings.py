"""Embedding adapter for duplicate detection (Solution Design 5.3, 7.3).

`SimulatedEmbeddingClient` builds a deterministic feature-hashed vector from the
receipt's salient fields (vendor, currency, category, amount bucket). Genuine
near-duplicates share those features and land close in cosine space; unrelated
receipts land far. Date is deliberately excluded from the signature - a resubmit
of the same expense typically carries a different submission date, so keying on
it would hurt recall.

This makes duplicate recall and false-positive rate real, measurable quantities
offline. A real embedding model implements the same interface later.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Optional


class EmbeddingClient(ABC):
    def __init__(self, dim: int):
        self.dim = dim

    @abstractmethod
    def embed_receipt(
        self,
        *,
        vendor: Optional[str],
        currency: Optional[str],
        category: Optional[str],
        amount: Optional[float],
    ) -> list[float]:
        ...


class SimulatedEmbeddingClient(EmbeddingClient):
    # Weights emphasise vendor and amount - the fields that actually characterise
    # a duplicate expense.
    _WEIGHTS = {"vendor": 2.0, "amount": 2.0, "currency": 1.0, "category": 1.0}
    _AMOUNT_BUCKET = 5.0  # absorbs the small jitter of a near-duplicate

    def _bump(self, vec: list[float], token: str, weight: float) -> None:
        idx = int(hashlib.sha256(token.encode()).hexdigest(), 16) % self.dim
        vec[idx] += weight

    def embed_receipt(
        self,
        *,
        vendor: Optional[str],
        currency: Optional[str],
        category: Optional[str],
        amount: Optional[float],
    ) -> list[float]:
        vec = [0.0] * self.dim
        if vendor:
            self._bump(vec, f"vendor:{vendor.strip().lower()}", self._WEIGHTS["vendor"])
        if currency:
            self._bump(vec, f"cur:{currency}", self._WEIGHTS["currency"])
        if category:
            self._bump(vec, f"cat:{category}", self._WEIGHTS["category"])
        if amount is not None:
            bucket = round(amount / self._AMOUNT_BUCKET)
            self._bump(vec, f"amt:{bucket}", self._WEIGHTS["amount"])
        return vec
