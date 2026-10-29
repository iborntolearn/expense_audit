"""LangGraph checkpointer factory (Tech Design 3.4).

Durable `SqliteSaver` by default so a human-review suspension survives a process
restart and can resume days later without re-running earlier nodes. Tests use the
in-core `MemorySaver`. The Postgres backend would use `PostgresSaver` here later.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

# The graph state carries our own pydantic types; register them so LangGraph's
# msgpack serde round-trips them without the "unregistered type" warning (and
# stays working once strict mode becomes the default).
_ALLOWED_MODULES = [
    ("common.schemas", "SubmissionCreatedEvent"),
    ("common.schemas", "AuditState"),
    ("common.schemas", "ReportLine"),
    ("common.schemas", "ReceiptRef"),
    ("common.schemas", "ExtractedLine"),
    ("common.schemas", "VerificationResult"),
    ("common.schemas", "DuplicateMatch"),
    ("common.schemas", "PolicyEvaluation"),
    ("common.schemas", "RuleResult"),
    ("common.schemas", "NodeError"),
    ("common.schemas", "SourceSystem"),
    ("common.schemas", "MerchantValidation"),
    ("common.schemas", "RoutingDecision"),
]


def _serde():
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    return JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_MODULES)


def build_sqlite_checkpointer(path: Path):
    from langgraph.checkpoint.sqlite import SqliteSaver

    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: LangGraph may touch the connection from worker
    # threads (our node timeout runs nodes in a ThreadPoolExecutor).
    conn = sqlite3.connect(str(path), check_same_thread=False)
    # WAL lets the reviewer UI process read/resume while other connections write.
    conn.execute("PRAGMA journal_mode=WAL")
    return SqliteSaver(conn, serde=_serde())


def build_memory_checkpointer():
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver(serde=_serde())
