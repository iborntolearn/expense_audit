"""HTTP client simulating a live T&E system's webhook call (Tech Design 2.1).

Where `SimulationHarness` (integration/harness.py) replays events in-process by
publishing directly onto the event bus, this module POSTs the identical
submission-created payload over real HTTP to the platform's own webhook
receiver (POST /webhooks/submission-created). It demonstrates the actual
over-the-wire integration seam that a live Concur connector would use in
Phase A - the same route, same payload shape, same idempotency behaviour -
without inventing a new contract.

Requires the FastAPI service to be running and reachable (e.g. via
scripts/dev_run.ps1) and, in simulation mode, the receipt blob store to be on a
filesystem the API process can also read (true by construction when both run
on the same machine against the same BLOB_ROOT).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from common.schemas import SubmissionCreatedEvent

DEFAULT_TIMEOUT_S = 15.0


@dataclass
class PostResult:
    submission_id: str
    ok: bool
    status_code: Optional[int]
    accepted: Optional[bool]
    reason: Optional[str]
    routing_decision: Optional[str]
    detail: str = ""


def post_submission(
    event: SubmissionCreatedEvent, base_url: str, timeout_s: float = DEFAULT_TIMEOUT_S
) -> PostResult:
    """POST one submission-created event to the live webhook endpoint."""
    url = base_url.rstrip("/") + "/webhooks/submission-created"
    body = event.model_dump_json().encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return PostResult(
                submission_id=event.submission_id,
                ok=True,
                status_code=resp.status,
                accepted=payload.get("accepted"),
                reason=payload.get("reason"),
                routing_decision=payload.get("routing_decision"),
            )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return PostResult(event.submission_id, False, exc.code, None, None, None, detail=detail)
    except urllib.error.URLError as exc:
        return PostResult(
            event.submission_id, False, None, None, None, None, detail=str(exc.reason)
        )


def post_batch(events: list[SubmissionCreatedEvent], base_url: str) -> list[PostResult]:
    """POST each event in order; a connection failure on one does not stop the rest."""
    return [post_submission(ev, base_url) for ev in events]
