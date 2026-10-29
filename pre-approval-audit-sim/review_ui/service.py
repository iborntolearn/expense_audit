"""Reviewer-workflow service (Milestone 9).

Wraps the data layer + pipeline for the HITL UI. Runs in its own process
(Streamlit), building its own data layer and pipeline against the same
STORAGE_BACKEND and durable checkpoint store the audit pipeline uses - so a
reviewer decision here resumes the exact checkpointed graph run created during
ingestion (Tech Design 3.2/3.4).
"""
from __future__ import annotations

from typing import Optional

from config.settings import Settings, get_settings
from data.factory import DataLayer, build_data_layer
from pipeline.factory import build_pipeline


class ReviewService:
    def __init__(self, data: DataLayer, pipeline):
        if not hasattr(pipeline, "resume_after_review"):
            raise RuntimeError(
                "reviewer UI requires the LangGraph engine (config/pipeline.yaml "
                "engine: langgraph) so suspended runs can be resumed."
            )
        self._data = data
        self._pipeline = pipeline

    # --- reads ---
    def queue(self) -> list[dict]:
        return self._data.store.list_review_queue()

    def detail(self, submission_id: str) -> Optional[dict]:
        return self._data.store.get_case_detail(submission_id)

    def receipt_bytes(self, receipt_url: str) -> bytes:
        return self._data.blobs.get(receipt_url)

    # --- action ---
    def submit_decision(
        self, submission_id: str, *, reviewer_id: str, approved: bool, notes: str | None = None
    ):
        decision = "approved" if approved else "rejected"
        return self._pipeline.resume_after_review(
            submission_id, reviewer_id=reviewer_id, decision=decision, notes=notes
        )

    def close(self) -> None:
        self._data.close()


def build_review_service(settings: Settings | None = None) -> ReviewService:
    settings = settings or get_settings()
    data = build_data_layer(settings)
    data.migrate()
    pipeline = build_pipeline(data, settings)
    return ReviewService(data, pipeline)
