"""The pipeline seam.

`AuditPipeline` is the single interface the integration layer depends on. In
Phase 1 the only implementation is `StubPipeline`; in Phase 2/3 the real
LangGraph pipeline (extraction -> verification -> policy -> risk routing)
implements the same interface and is dropped in via `build_pipeline` with no
change to the integration layer.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from common.schemas import AuditState, SubmissionCreatedEvent


@runtime_checkable
class AuditPipeline(Protocol):
    #: version string stamped onto every decision (Solution Design 8 / DDL).
    model_version: str
    rule_version: str

    def run(self, event: SubmissionCreatedEvent) -> AuditState:
        """Audit one submission and return the resulting state (with a routing
        decision set). Persistence is the caller's responsibility."""
        ...
