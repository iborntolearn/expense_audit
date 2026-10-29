"""Event bus abstraction.

Decouples webhook receipt from audit processing (Solution Design 7.3: Service
Bus / SQS). In simulation the `InProcessBus` dispatches synchronously, which is
enough for batch replay and keeps behaviour easy to reason about in tests. A
real broker-backed bus implements the same interface later without touching the
ingest service.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from common.schemas import SubmissionCreatedEvent

Handler = Callable[[SubmissionCreatedEvent], None]


class EventBus(ABC):
    @abstractmethod
    def subscribe(self, handler: Handler) -> None:
        ...

    @abstractmethod
    def publish(self, event: SubmissionCreatedEvent) -> None:
        ...


class InProcessBus(EventBus):
    def __init__(self) -> None:
        self._handler: Handler | None = None

    def subscribe(self, handler: Handler) -> None:
        self._handler = handler

    def publish(self, event: SubmissionCreatedEvent) -> None:
        if self._handler is None:
            raise RuntimeError("InProcessBus.publish called before subscribe")
        self._handler(event)
