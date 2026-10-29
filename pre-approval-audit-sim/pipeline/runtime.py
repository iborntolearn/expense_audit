"""Node execution runtime: timeout, retry, and fail-open (Tech Design 3.3).

Every agent runs inside `run_node`, which is the single place the pipeline's
resilience policy lives. Node functions mutate the shared `AuditState`; the
runtime handles *how* they are invoked:

  * a per-node timeout (thread-based, so one slow node can't wedge the process);
  * up to N retries on TRANSIENT errors with exponential backoff;
  * NO retry on permanent/validation errors (retrying them just wastes the SLA);
  * on final failure: record a NodeError on the state and signal the caller to
    FAIL OPEN to human review - never stall, never silently auto-approve.

The same runtime is reused verbatim by the LangGraph nodes in Phase 3.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Callable

from common.schemas import AuditState, NodeError
from pipeline.config import RetryConfig

logger = logging.getLogger("pipeline.runtime")


class TransientError(Exception):
    """Raise (or wrap) for failures that are worth retrying: LLM API timeouts,
    5xx, transient connection issues."""


# Exceptions treated as transient (retryable). Everything else is permanent.
_TRANSIENT = (TransientError, TimeoutError, ConnectionError, FutureTimeout)


@dataclass
class NodeOutcome:
    node: str
    ok: bool
    attempts: int
    latency_s: float
    error: NodeError | None = None


def _call_with_timeout(fn: Callable[[], None], timeout_s: float) -> None:
    """Run fn in a worker thread, enforcing a wall-clock timeout.

    Note: on timeout the worker thread is not forcibly killed (Python can't), but
    the pipeline moves on and the node is treated as failed. Agents should keep
    their own external calls bounded; this timeout is the backstop.
    """
    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(fn)
        try:
            future.result(timeout=timeout_s)
        except FutureTimeout as exc:
            raise TransientError(f"node exceeded {timeout_s}s timeout") from exc


def run_node(
    name: str,
    fn: Callable[[], None],
    *,
    state: AuditState,
    timeout_s: float,
    retry: RetryConfig,
    on_latency: Callable[[str, float], None] | None = None,
) -> NodeOutcome:
    started = time.perf_counter()
    attempts = 0
    last_exc: Exception | None = None

    def _emit(latency: float) -> None:
        if on_latency is not None:
            on_latency(name, latency)

    while attempts <= retry.max_retries:
        attempts += 1
        try:
            _call_with_timeout(fn, timeout_s)
            latency = time.perf_counter() - started
            logger.debug("node %s ok in %.3fs (attempt %d)", name, latency, attempts)
            _emit(latency)
            return NodeOutcome(node=name, ok=True, attempts=attempts, latency_s=latency)
        except _TRANSIENT as exc:
            last_exc = exc
            if attempts > retry.max_retries:
                break
            backoff = _backoff_for(retry, attempts)
            logger.warning(
                "node %s transient failure (attempt %d/%d): %s; retrying in %.1fs",
                name, attempts, retry.max_retries + 1, exc, backoff,
            )
            if backoff > 0:
                time.sleep(backoff)
        except Exception as exc:  # permanent - do not retry
            last_exc = exc
            logger.error("node %s permanent failure: %s", name, exc)
            break

    latency = time.perf_counter() - started
    err = NodeError(
        node=name,
        message=f"{type(last_exc).__name__}: {last_exc}",
        recoverable=isinstance(last_exc, _TRANSIENT),
    )
    state.errors.append(err)
    logger.error("node %s failed after %d attempt(s) in %.3fs", name, attempts, latency)
    _emit(latency)
    return NodeOutcome(node=name, ok=False, attempts=attempts, latency_s=latency, error=err)


def run_node_logged(
    name: str,
    fn: Callable[[], None],
    *,
    state: AuditState,
    timeout_s: float,
    retry: RetryConfig,
    store,
    submission_id: str,
    input_summary: str = "",
    output_summary_fn: Callable[[], str] | None = None,
    on_latency: Callable[[str, float], None] | None = None,
) -> NodeOutcome:
    """`run_node` plus a persisted execution-trace row (observability - "how did
    end-to-end processing work for this submission?"). `output_summary_fn` is
    called AFTER `fn()` runs, so it can describe the now-updated state; a
    failure in the summary itself never breaks the pipeline or hides the node
    outcome. `store` is any AuditStore (duck-typed here to avoid a hard import
    cycle with data.interfaces)."""
    outcome = run_node(name, fn, state=state, timeout_s=timeout_s, retry=retry, on_latency=on_latency)

    output_summary = ""
    if outcome.ok and output_summary_fn is not None:
        try:
            output_summary = output_summary_fn()
        except Exception as exc:  # summarising must never break the pipeline
            output_summary = f"(summary failed: {exc})"

    try:
        store.log_pipeline_step(
            submission_id,
            node=name,
            ok=outcome.ok,
            attempts=outcome.attempts,
            latency_ms=round(outcome.latency_s * 1000, 2),
            input_summary=input_summary,
            output_summary=output_summary,
            error_message=outcome.error.message if outcome.error else None,
        )
    except Exception:
        logger.warning("failed to persist pipeline_logs row for %s/%s", submission_id, name)

    return outcome


def _backoff_for(retry: RetryConfig, attempt: int) -> float:
    # attempt is 1-based; the first retry uses backoff_seconds[0].
    idx = attempt - 1
    if not retry.backoff_seconds:
        return 0.0
    return retry.backoff_seconds[min(idx, len(retry.backoff_seconds) - 1)]
