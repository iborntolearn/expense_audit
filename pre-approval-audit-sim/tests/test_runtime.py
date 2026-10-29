"""Resilience layer: timeout, retry on transient only, fail-open (Tech Design 3.3)."""
from __future__ import annotations

import time

from common.schemas import AuditState
from pipeline.config import RetryConfig
from pipeline.runtime import TransientError, run_node

# zero backoff so tests don't sleep
_RETRY = RetryConfig(max_retries=2, backoff_seconds=[0, 0])


def _state() -> AuditState:
    return AuditState(submission_id="SUB-X")


def test_success_first_try():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1

    st = _state()
    out = run_node("n", fn, state=st, timeout_s=5, retry=_RETRY)
    assert out.ok and out.attempts == 1
    assert st.errors == []


def test_transient_retried_then_succeeds():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("temporary")

    st = _state()
    out = run_node("n", fn, state=st, timeout_s=5, retry=_RETRY)
    assert out.ok is True
    assert out.attempts == 3  # 1 + 2 retries
    assert st.errors == []


def test_transient_exhausted_fails_open():
    def fn():
        raise TransientError("always")

    st = _state()
    out = run_node("n", fn, state=st, timeout_s=5, retry=_RETRY)
    assert out.ok is False
    assert out.attempts == 3
    assert len(st.errors) == 1
    assert st.errors[0].recoverable is True


def test_permanent_not_retried():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise ValueError("bad input")

    st = _state()
    out = run_node("n", fn, state=st, timeout_s=5, retry=_RETRY)
    assert out.ok is False
    assert out.attempts == 1  # no retry on permanent errors
    assert st.errors[0].recoverable is False


def test_timeout_is_transient_and_fails_open():
    def fn():
        time.sleep(0.5)

    st = _state()
    out = run_node("n", fn, state=st, timeout_s=0.1, retry=RetryConfig(max_retries=1, backoff_seconds=[0]))
    assert out.ok is False
    assert out.attempts == 2
    assert st.errors[0].recoverable is True
