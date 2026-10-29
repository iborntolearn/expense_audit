"""sqlite_local backend: AuditStore + NumPy vector index.

This is the Docker-free dev fallback. It is behaviourally equivalent to the
Postgres backend at the interface level; the differences (JSON arrays instead of
TEXT[], in-Python cosine search instead of ivfflat) are contained entirely
within this module.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import threading
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import yaml

from common.auth import Role, UserRecord
from common.ids import line_item_id
from common.schemas import (
    AuditDecisionWriteback,
    ExtractedLine,
    PolicyEvaluation,
    RoutingDecision,
    SubmissionCreatedEvent,
    VerificationResult,
)
from config.settings import REPO_ROOT
from data.interfaces import AuditStore, ConfigStore, VectorIndex, VectorMatch

_MIGRATION = REPO_ROOT / "data" / "migrations" / "001_init_sqlite.sql"

_EXPECTED_TABLES = [
    "submissions",
    "extracted_line_items",
    "verification_results",
    "policy_evaluations",
    "risk_decisions",
    "reviewer_actions",
    "receipt_refs",
    "report_lines",
    "pipeline_logs",
    "receipt_embeddings",
    "case_status",
]


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _merchant_key(name: str) -> str:
    return name.strip().lower()


class SqliteAuditStore(AuditStore):
    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._conn = _connect(self._db_path)
        self._lock = threading.Lock()

    # --- lifecycle ---
    def migrate(self) -> None:
        sql = _MIGRATION.read_text(encoding="utf-8")
        with self._lock:
            self._conn.executescript(sql)
            self._conn.commit()
            self._add_missing_columns()
            # Must run AFTER _add_missing_columns() - on a pre-existing
            # database, invoice_number was just added above, and an index
            # referencing it in the raw migration script (which only runs
            # CREATE TABLE IF NOT EXISTS, a no-op here) would fail with
            # "no such column" before the column existed.
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS extracted_line_items_vendor_invoice_idx "
                "ON extracted_line_items (vendor, invoice_number)"
            )
            self._conn.commit()
        self._bootstrap_merchant_registry()

    def _bootstrap_merchant_registry(self) -> None:
        from common.blocklist import load_merchant_blocklist

        blocklist = load_merchant_blocklist()
        self.bootstrap_merchant_registry([e.model_dump() for e in blocklist.entries])

    def _add_missing_columns(self) -> None:
        # `CREATE TABLE IF NOT EXISTS` (above) only creates a table on a FRESH
        # database - it never adds columns to a table that already exists on
        # disk. New columns added to an existing table go here instead, each
        # gated on PRAGMA table_info so this stays a no-op once applied.
        additions = [
            ("verification_results", "subtotal_entered_total", "NUMERIC"),
            ("verification_results", "subtotal_receipt_total", "NUMERIC"),
            ("verification_results", "velocity_flags", "TEXT"),
            ("verification_results", "split_transaction_flags", "TEXT"),
            ("verification_results", "merchant_flags", "TEXT"),
            ("verification_results", "compliance_flags", "TEXT"),
            ("verification_results", "peer_outlier_flags", "TEXT"),
            ("verification_results", "duplicate_match_details", "TEXT"),
            ("verification_results", "merchant_network_flags", "TEXT"),
            ("extracted_line_items", "invoice_number", "TEXT"),
        ]
        for table, column, col_type in additions:
            cols = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in cols:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        self._conn.commit()

    def health(self) -> bool:
        try:
            existing = set(self.table_names())
            return set(_EXPECTED_TABLES).issubset(existing)
        except sqlite3.Error:
            return False

    def table_names(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        return [r["name"] for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def purge_all(self) -> dict[str, int]:
        # Children before parents so `PRAGMA foreign_keys = ON` doesn't reject
        # the deletes; `submissions` (the root) goes last. Must cover every
        # entry in _EXPECTED_TABLES - missing one here means it silently
        # survives a "delete everything" purge with a dangling FK to boot.
        order = [
            "receipt_embeddings", "pipeline_logs", "report_lines", "receipt_refs",
            "reviewer_actions", "case_status", "risk_decisions", "policy_evaluations",
            "verification_results", "extracted_line_items", "submissions",
        ]
        assert set(order) == set(_EXPECTED_TABLES), (
            f"purge_all() order is out of sync with _EXPECTED_TABLES: "
            f"missing={set(_EXPECTED_TABLES) - set(order)}, extra={set(order) - set(_EXPECTED_TABLES)}"
        )
        counts: dict[str, int] = {}
        with self._lock:
            for table in order:
                cur = self._conn.execute(f"DELETE FROM {table}")
                counts[table] = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
            self._conn.commit()
        return counts

    # --- writes ---
    def save_submission(self, event: SubmissionCreatedEvent, is_synthetic: bool) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO submissions
                   (submission_id, source_system, source_system_ref, oe_code,
                    employee_id, cost_center, currency, submitted_at, is_synthetic)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    event.submission_id,
                    event.source_system.value,
                    event.source_system_ref,
                    event.oe_code,
                    event.employee_id,
                    event.cost_center,
                    event.currency,
                    event.submitted_at.isoformat(),
                    1 if is_synthetic else 0,
                ),
            )
            self._conn.commit()

    def save_extracted_lines(self, submission_id: str, lines: list[ExtractedLine]) -> None:
        with self._lock:
            for ln in lines:
                self._conn.execute(
                    """INSERT OR REPLACE INTO extracted_line_items
                       (line_item_id, submission_id, vendor, txn_date, amount, tax,
                        category, confidence, invoice_number)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        line_item_id(submission_id, ln.line_id),
                        submission_id,
                        ln.vendor,
                        ln.date.isoformat() if ln.date else None,
                        ln.amount,
                        ln.tax,
                        None,
                        ln.confidence,
                        ln.invoice_number,
                    ),
                )
            self._conn.commit()

    def save_verification(self, submission_id: str, verification: VerificationResult) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO verification_results
                   (submission_id, authenticity_flags, duplicate_match_ids,
                    subtotal_variance_pct, subtotal_entered_total, subtotal_receipt_total,
                    velocity_flags, split_transaction_flags, merchant_validation, merchant_flags,
                    compliance_flags, peer_outlier_flags, duplicate_match_details,
                    merchant_network_flags)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    submission_id,
                    json.dumps(verification.authenticity_flags),
                    json.dumps([m.submission_id for m in verification.duplicate_matches]),
                    verification.subtotal_variance_pct,
                    verification.subtotal_entered_total,
                    verification.subtotal_receipt_total,
                    json.dumps(verification.velocity_flags),
                    json.dumps(verification.split_transaction_flags),
                    verification.merchant_validation.value,
                    json.dumps(verification.merchant_flags),
                    json.dumps(verification.compliance_flags),
                    json.dumps(verification.peer_outlier_flags),
                    json.dumps([m.model_dump(mode="json") for m in verification.duplicate_matches]),
                    json.dumps(verification.merchant_network_flags),
                ),
            )
            self._conn.commit()

    def save_policy(
        self, submission_id: str, evaluation: PolicyEvaluation, *, rule_version: str
    ) -> None:
        with self._lock:
            for rr in evaluation.rule_results:
                self._conn.execute(
                    """INSERT OR REPLACE INTO policy_evaluations
                       (submission_id, rule_id, rule_version, passed)
                       VALUES (?,?,?,?)""",
                    (submission_id, rr.rule_id, rule_version, 1 if rr.passed else 0),
                )
            self._conn.commit()

    def save_risk(
        self,
        submission_id: str,
        *,
        risk_score: float,
        routing_decision: RoutingDecision,
        model_version: str,
        explanation: str | None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO risk_decisions
                   (submission_id, risk_score, routing_decision, model_version, explanation)
                   VALUES (?,?,?,?,?)""",
                (submission_id, risk_score, routing_decision.value, model_version, explanation),
            )
            self._conn.commit()

    def save_receipt_refs(self, submission_id: str, refs: list[tuple[str, str]]) -> None:
        with self._lock:
            for line_id, url in refs:
                self._conn.execute(
                    """INSERT OR REPLACE INTO receipt_refs
                       (submission_id, line_id, receipt_url) VALUES (?,?,?)""",
                    (submission_id, line_id, url),
                )
            self._conn.commit()

    def save_report_lines(
        self, submission_id: str, lines: list[tuple[str, str, float, str]]
    ) -> None:
        with self._lock:
            for line_id, category, entered_amount, currency in lines:
                self._conn.execute(
                    """INSERT OR REPLACE INTO report_lines
                       (submission_id, line_id, category, entered_amount, currency)
                       VALUES (?,?,?,?,?)""",
                    (submission_id, line_id, category, entered_amount, currency),
                )
            self._conn.commit()

    def save_writeback(self, decision: AuditDecisionWriteback) -> None:
        # In simulation mode the write-back is logged, not sent anywhere. We keep
        # the reviewer_actions row only when a reviewer acted; the interim
        # pending_review status is captured in risk_decisions/logs.
        if decision.reviewer_id:
            with self._lock:
                self._conn.execute(
                    """INSERT OR REPLACE INTO reviewer_actions
                       (submission_id, reviewer_id, final_decision, feedback_notes)
                       VALUES (?,?,?,?)""",
                    (
                        decision.submission_id,
                        decision.reviewer_id,
                        decision.decision.value,
                        decision.rationale,
                    ),
                )
                self._conn.commit()

    def log_pipeline_step(
        self,
        submission_id: str,
        *,
        node: str,
        ok: bool,
        attempts: int,
        latency_ms: float,
        input_summary: str = "",
        output_summary: str = "",
        error_message: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO pipeline_logs
                   (submission_id, node, ok, attempts, latency_ms,
                    input_summary, output_summary, error_message)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (submission_id, node, 1 if ok else 0, attempts, latency_ms,
                 input_summary, output_summary, error_message),
            )
            self._conn.commit()

    def get_pipeline_steps(self, submission_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM pipeline_logs WHERE submission_id = ? ORDER BY id ASC",
                (submission_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_pipeline_logs(self, limit: int = 1000) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM pipeline_logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def recent_employee_category_lines(
        self, employee_id: str, category: str, since_date: str,
        *, exclude_submission_id: Optional[str] = None,
    ) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT rl.submission_id, rl.line_id, rl.entered_amount, rl.currency,
                          eli.txn_date
                   FROM report_lines rl
                   JOIN submissions s ON s.submission_id = rl.submission_id
                   JOIN extracted_line_items eli
                     ON eli.submission_id = rl.submission_id
                    AND eli.line_item_id = rl.submission_id || ':' || rl.line_id
                   WHERE s.employee_id = ? AND rl.category = ? AND eli.txn_date >= ?
                     AND (? IS NULL OR rl.submission_id != ?)""",
                (employee_id, category, since_date,
                 exclude_submission_id, exclude_submission_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def category_amount_stats(
        self, oe_code: str, category: str, *, exclude_employee_id: Optional[str] = None,
    ) -> dict:
        with self._lock:
            rows = self._conn.execute(
                """SELECT rl.entered_amount
                   FROM report_lines rl
                   JOIN submissions s ON s.submission_id = rl.submission_id
                   WHERE s.oe_code = ? AND rl.category = ?
                     AND (? IS NULL OR s.employee_id != ?)""",
                (oe_code, category, exclude_employee_id, exclude_employee_id),
            ).fetchall()
        amounts = [r["entered_amount"] for r in rows]
        n = len(amounts)
        if n == 0:
            return {"mean": 0.0, "stddev": 0.0, "n": 0}
        return {
            "mean": statistics.fmean(amounts),
            "stddev": statistics.pstdev(amounts) if n > 1 else 0.0,
            "n": n,
        }

    def find_by_vendor_invoice(
        self, vendor: str, invoice_number: str, *, exclude_submission_id: str,
    ) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT submission_id, line_item_id
                   FROM extracted_line_items
                   WHERE lower(trim(vendor)) = lower(trim(?))
                     AND lower(trim(invoice_number)) = lower(trim(?))
                     AND submission_id != ?""",
                (vendor, invoice_number, exclude_submission_id),
            ).fetchall()
        return [{"submission_id": r["submission_id"], "line_id": r["line_item_id"]} for r in rows]

    def bootstrap_merchant_registry(self, entries: list[dict]) -> None:
        with self._lock:
            (count,) = self._conn.execute("SELECT COUNT(*) FROM merchant_registry").fetchone()
            if count:
                return
            for e in entries:
                self._conn.execute(
                    """INSERT OR IGNORE INTO merchant_registry
                       (merchant_key, display_name, status, risk_tier, source,
                        blocklist_type, reason)
                       VALUES (?,?,?,?,?,?,?)""",
                    (_merchant_key(e["name"]), e["name"], "blocked", "high",
                     "bootstrap_yaml", e.get("type"), e.get("reason")),
                )
            self._conn.commit()

    def upsert_merchant_seen(self, vendor: str) -> None:
        if not vendor:
            return
        key = _merchant_key(vendor)
        with self._lock:
            self._conn.execute(
                """INSERT INTO merchant_registry (merchant_key, display_name, submission_count)
                   VALUES (?,?,1)
                   ON CONFLICT(merchant_key) DO UPDATE SET
                     submission_count = submission_count + 1,
                     last_seen_at = CURRENT_TIMESTAMP""",
                (key, vendor),
            )
            self._conn.commit()

    def get_merchant(self, merchant_key: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM merchant_registry WHERE merchant_key = ?",
                (_merchant_key(merchant_key),),
            ).fetchone()
        return dict(row) if row else None

    def list_merchant_registry(self, *, status: Optional[str] = None) -> list[dict]:
        with self._lock:
            if status is None:
                rows = self._conn.execute(
                    "SELECT * FROM merchant_registry ORDER BY last_seen_at DESC"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM merchant_registry WHERE status = ? ORDER BY last_seen_at DESC",
                    (status,),
                ).fetchall()
        return [dict(r) for r in rows]

    def set_merchant_status(
        self, merchant_key: str, *, display_name: Optional[str] = None,
        status: Optional[str] = None, risk_tier: Optional[str] = None,
        reason: Optional[str] = None, source: str = "auto",
        updated_by: Optional[str] = None, force: bool = False,
    ) -> None:
        key = _merchant_key(merchant_key)
        with self._lock:
            existing = self._conn.execute(
                "SELECT source FROM merchant_registry WHERE merchant_key = ?", (key,)
            ).fetchone()
            if existing and existing["source"] == "admin_override" and not force:
                return
            if existing is None:
                self._conn.execute(
                    """INSERT INTO merchant_registry
                       (merchant_key, display_name, status, risk_tier, source, reason, updated_by)
                       VALUES (?,?,?,?,?,?,?)""",
                    (key, display_name or merchant_key, status or "clear", risk_tier or "low",
                     source, reason, updated_by),
                )
            else:
                sets, params = [], []
                if display_name is not None:
                    sets.append("display_name = ?"); params.append(display_name)
                if status is not None:
                    sets.append("status = ?"); params.append(status)
                if risk_tier is not None:
                    sets.append("risk_tier = ?"); params.append(risk_tier)
                if reason is not None:
                    sets.append("reason = ?"); params.append(reason)
                sets.append("source = ?"); params.append(source)
                sets.append("updated_by = ?"); params.append(updated_by)
                sets.append("updated_at = CURRENT_TIMESTAMP")
                params.append(key)
                self._conn.execute(
                    f"UPDATE merchant_registry SET {', '.join(sets)} WHERE merchant_key = ?",
                    params,
                )
            self._conn.commit()

    def merchant_employee_spread(self, vendor: str, *, since_date: str) -> dict:
        with self._lock:
            rows = self._conn.execute(
                """SELECT DISTINCT s.employee_id, eli.submission_id
                   FROM extracted_line_items eli
                   JOIN submissions s ON s.submission_id = eli.submission_id
                   WHERE lower(trim(eli.vendor)) = lower(trim(?)) AND s.submitted_at >= ?""",
                (vendor, since_date),
            ).fetchall()
        return {
            "distinct_employees": len({r["employee_id"] for r in rows}),
            "submissions": len({r["submission_id"] for r in rows}),
        }

    def merchant_near_cap_clustering(
        self, vendor: str, category: str, oe_code: str, cap: float, *,
        tolerance_pct: float, since_date: str,
    ) -> dict:
        floor = cap * (1 - tolerance_pct / 100.0)
        with self._lock:
            rows = self._conn.execute(
                """SELECT DISTINCT s.employee_id
                   FROM report_lines rl
                   JOIN submissions s ON s.submission_id = rl.submission_id
                   JOIN extracted_line_items eli
                     ON eli.submission_id = rl.submission_id
                    AND eli.line_item_id = rl.submission_id || ':' || rl.line_id
                   WHERE lower(trim(eli.vendor)) = lower(trim(?))
                     AND rl.category = ? AND s.oe_code = ? AND s.submitted_at >= ?
                     AND rl.entered_amount <= ? AND rl.entered_amount >= ?""",
                (vendor, category, oe_code, since_date, cap, floor),
            ).fetchall()
        return {
            "distinct_employees_near_cap": len({r["employee_id"] for r in rows}),
            "n": len(rows),
        }

    def set_case_status(
        self, submission_id: str, *, status: str,
        recovered_amount: Optional[float] = None, updated_by: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO case_status (submission_id, status, recovered_amount, updated_by)
                   VALUES (?,?,?,?)
                   ON CONFLICT(submission_id) DO UPDATE SET
                     status=excluded.status,
                     recovered_amount=excluded.recovered_amount,
                     updated_by=excluded.updated_by,
                     updated_at=CURRENT_TIMESTAMP""",
                (submission_id, status, recovered_amount, updated_by),
            )
            self._conn.commit()

    def get_case_status(self, submission_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM case_status WHERE submission_id = ?", (submission_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_case_statuses(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM case_status").fetchall()
        return [dict(r) for r in rows]

    # --- reads ---
    def get_submission(self, submission_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM submissions WHERE submission_id = ?", (submission_id,)
            ).fetchone()
        return dict(row) if row else None

    def has_decision(self, submission_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM risk_decisions WHERE submission_id = ? LIMIT 1",
                (submission_id,),
            ).fetchone()
        return row is not None

    def list_review_queue(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT s.submission_id, s.oe_code, s.employee_id, s.currency,
                          s.submitted_at, r.risk_score, r.explanation
                   FROM submissions s
                   JOIN risk_decisions r ON s.submission_id = r.submission_id
                   LEFT JOIN reviewer_actions ra ON s.submission_id = ra.submission_id
                   WHERE r.routing_decision = 'human_review' AND ra.submission_id IS NULL
                   ORDER BY r.risk_score DESC, s.submitted_at ASC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def get_case_detail(self, submission_id: str) -> Optional[dict]:
        with self._lock:
            sub = self._conn.execute(
                "SELECT * FROM submissions WHERE submission_id = ?", (submission_id,)
            ).fetchone()
            if not sub:
                return None
            lines = self._conn.execute(
                "SELECT * FROM extracted_line_items WHERE submission_id = ?", (submission_id,)
            ).fetchall()
            ver = self._conn.execute(
                "SELECT * FROM verification_results WHERE submission_id = ?", (submission_id,)
            ).fetchone()
            pol = self._conn.execute(
                "SELECT * FROM policy_evaluations WHERE submission_id = ?", (submission_id,)
            ).fetchall()
            risk = self._conn.execute(
                "SELECT * FROM risk_decisions WHERE submission_id = ?", (submission_id,)
            ).fetchone()
            refs = self._conn.execute(
                "SELECT line_id, receipt_url FROM receipt_refs WHERE submission_id = ?",
                (submission_id,),
            ).fetchall()
        verification = dict(ver) if ver else {}
        if verification:
            verification["authenticity_flags"] = json.loads(
                verification.get("authenticity_flags") or "[]"
            )
            verification["duplicate_match_ids"] = json.loads(
                verification.get("duplicate_match_ids") or "[]"
            )
            verification["velocity_flags"] = json.loads(
                verification.get("velocity_flags") or "[]"
            )
            verification["split_transaction_flags"] = json.loads(
                verification.get("split_transaction_flags") or "[]"
            )
            verification["merchant_flags"] = json.loads(
                verification.get("merchant_flags") or "[]"
            )
            verification["compliance_flags"] = json.loads(
                verification.get("compliance_flags") or "[]"
            )
            verification["peer_outlier_flags"] = json.loads(
                verification.get("peer_outlier_flags") or "[]"
            )
            verification["duplicate_match_details"] = json.loads(
                verification.get("duplicate_match_details") or "[]"
            )
            verification["merchant_network_flags"] = json.loads(
                verification.get("merchant_network_flags") or "[]"
            )
        return {
            "submission": dict(sub),
            "extracted_lines": [dict(r) for r in lines],
            "verification": verification,
            "policy": [dict(r) for r in pol],
            "risk": dict(risk) if risk else {},
            "receipts": [dict(r) for r in refs],
        }

    def analytics_rows(self) -> dict[str, list[dict]]:
        with self._lock:
            def rows(sql: str) -> list[dict]:
                return [dict(r) for r in self._conn.execute(sql).fetchall()]

            submissions = rows("SELECT * FROM submissions")
            risk = rows("SELECT * FROM risk_decisions")
            report_lines = rows("SELECT * FROM report_lines")
            policy = rows("SELECT * FROM policy_evaluations")
            reviewer = rows("SELECT * FROM reviewer_actions")
            extracted = rows("SELECT * FROM extracted_line_items")
            ver_raw = rows("SELECT * FROM verification_results")
        for v in ver_raw:
            v["authenticity_flags"] = json.loads(v.get("authenticity_flags") or "[]")
            v["duplicate_match_ids"] = json.loads(v.get("duplicate_match_ids") or "[]")
            v["velocity_flags"] = json.loads(v.get("velocity_flags") or "[]")
            v["split_transaction_flags"] = json.loads(v.get("split_transaction_flags") or "[]")
            v["merchant_flags"] = json.loads(v.get("merchant_flags") or "[]")
            v["compliance_flags"] = json.loads(v.get("compliance_flags") or "[]")
            v["peer_outlier_flags"] = json.loads(v.get("peer_outlier_flags") or "[]")
            v["duplicate_match_details"] = json.loads(v.get("duplicate_match_details") or "[]")
            v["merchant_network_flags"] = json.loads(v.get("merchant_network_flags") or "[]")
        return {
            "submissions": submissions,
            "risk_decisions": risk,
            "report_lines": report_lines,
            "policy_evaluations": policy,
            "verification": ver_raw,
            "reviewer_actions": reviewer,
            "extracted_line_items": extracted,
        }


class SqliteConfigStore(ConfigStore):
    """Shares SqliteAuditStore's connection/lock (same db file, same WAL mode)
    rather than opening a second connection - mirrors LocalVectorIndex's
    pattern of taking the store instance itself."""

    _MIGRATION = REPO_ROOT / "data" / "migrations" / "002_config_sqlite.sql"
    _USERS_YAML = REPO_ROOT / "config" / "users.yaml"

    def __init__(self, store: SqliteAuditStore):
        self._conn = store._conn
        self._lock = store._lock

    def migrate(self) -> None:
        sql = self._MIGRATION.read_text(encoding="utf-8")
        with self._lock:
            self._conn.executescript(sql)
            self._conn.commit()
        self._bootstrap_users()
        self._bootstrap_policy_rules()

    def _bootstrap_policy_rules(self) -> None:
        # Only on a genuinely-empty table, and only once -
        # config/policy_rules.yaml is the one-time bootstrap source, never
        # re-synced after this (same discipline as _bootstrap_users above).
        from common.policy import load_policy_rules

        ruleset = load_policy_rules()
        self.bootstrap_policy_ruleset(
            ruleset.rule_version, [r.model_dump(mode="json") for r in ruleset.rules],
        )

    def _bootstrap_users(self) -> None:
        # Only on a genuinely-empty table, and only once - config/users.yaml
        # is the one-time bootstrap source, never re-synced after this.
        with self._lock:
            (count,) = self._conn.execute("SELECT COUNT(*) FROM app_users").fetchone()
        if count or not self._USERS_YAML.exists():
            return
        raw = yaml.safe_load(self._USERS_YAML.read_text(encoding="utf-8")) or {}
        users = raw.get("users") or []
        if not users:
            return
        with self._lock:
            for u in users:
                self._conn.execute(
                    """INSERT OR IGNORE INTO app_users
                       (username, display_name, role, oe_code, salt, password_hash)
                       VALUES (?,?,?,?,?,?)""",
                    (u["username"], u["display_name"], u["role"], u.get("oe_code"),
                     u["salt"], u["password_hash"]),
                )
            self._conn.commit()

    def health(self) -> bool:
        try:
            with self._lock:
                self._conn.execute("SELECT 1 FROM app_users LIMIT 1")
            return True
        except sqlite3.Error:
            return False

    def close(self) -> None:
        pass  # shares SqliteAuditStore's connection - that store owns close()

    @staticmethod
    def _to_record(row: sqlite3.Row) -> UserRecord:
        return UserRecord(
            username=row["username"], display_name=row["display_name"],
            role=Role(row["role"]), oe_code=row["oe_code"],
            salt=row["salt"], password_hash=row["password_hash"],
        )

    def list_users(self) -> list[UserRecord]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM app_users ORDER BY username").fetchall()
        return [self._to_record(r) for r in rows]

    def get_user(self, username: str) -> Optional[UserRecord]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM app_users WHERE username = ?", (username,)
            ).fetchone()
        return self._to_record(row) if row else None

    def add_user(self, record: UserRecord) -> None:
        with self._lock:
            existing = self._conn.execute(
                "SELECT 1 FROM app_users WHERE username = ?", (record.username,)
            ).fetchone()
            if existing:
                raise ValueError(f"user {record.username!r} already exists")
            self._conn.execute(
                """INSERT INTO app_users
                   (username, display_name, role, oe_code, salt, password_hash)
                   VALUES (?,?,?,?,?,?)""",
                (record.username, record.display_name, record.role.value,
                 record.oe_code, record.salt, record.password_hash),
            )
            self._conn.commit()

    def _require_exists(self, username: str) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM app_users WHERE username = ?", (username,)
            ).fetchone()
        if not row:
            raise ValueError(f"user {username!r} not found")

    def update_user_password(self, username: str, salt: str, password_hash: str) -> None:
        self._require_exists(username)
        with self._lock:
            self._conn.execute(
                "UPDATE app_users SET salt = ?, password_hash = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE username = ?",
                (salt, password_hash, username),
            )
            self._conn.commit()

    def update_user_role(self, username: str, role: Role) -> None:
        self._require_exists(username)
        with self._lock:
            self._conn.execute(
                "UPDATE app_users SET role = ?, updated_at = CURRENT_TIMESTAMP WHERE username = ?",
                (role.value, username),
            )
            self._conn.commit()

    def update_user_oe(self, username: str, oe_code: Optional[str]) -> None:
        self._require_exists(username)
        with self._lock:
            self._conn.execute(
                "UPDATE app_users SET oe_code = ?, updated_at = CURRENT_TIMESTAMP WHERE username = ?",
                (oe_code, username),
            )
            self._conn.commit()

    def delete_user(self, username: str) -> None:
        with self._lock:
            cur = self._conn.execute("DELETE FROM app_users WHERE username = ?", (username,))
            self._conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"user {username!r} not found")

    # --- OE config overrides ---
    def get_override(self, name: str, oe_code: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM oe_config_overrides WHERE name = ? AND oe_code = ?",
                (name, oe_code),
            ).fetchone()
        return json.loads(row["data"]) if row else None

    def save_override(self, name: str, oe_code: str, data: dict) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO oe_config_overrides (name, oe_code, data, updated_at)
                   VALUES (?,?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(name, oe_code) DO UPDATE SET
                     data = excluded.data, updated_at = CURRENT_TIMESTAMP""",
                (name, oe_code, json.dumps(data)),
            )
            self._conn.commit()

    def delete_override(self, name: str, oe_code: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM oe_config_overrides WHERE name = ? AND oe_code = ?",
                (name, oe_code),
            )
            self._conn.commit()

    # --- business-rule engine ruleset ---
    @staticmethod
    def _rule_row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "description": row["description"],
            "type": row["type"],
            "enabled": bool(row["enabled"]),
            "applies_to": {"category": row["applies_to_category"], "oe_code": row["applies_to_oe_code"]},
            "cap": json.loads(row["cap"]) if row["cap"] else {},
            "threshold": json.loads(row["threshold"]) if row["threshold"] else {},
            "min_ratio": row["min_ratio"],
            "max_ratio": row["max_ratio"],
            "max_days": row["max_days"],
            "window_days": row["window_days"],
        }

    @staticmethod
    def _rule_dict_to_row(rule: dict) -> tuple:
        applies_to = rule.get("applies_to") or {}
        return (
            rule["id"], rule.get("description") or "", rule["type"], bool(rule.get("enabled", True)),
            applies_to.get("category"), applies_to.get("oe_code"),
            json.dumps(rule.get("cap") or {}), json.dumps(rule.get("threshold") or {}),
            rule.get("min_ratio"), rule.get("max_ratio"), rule.get("max_days"), rule.get("window_days"),
        )

    def get_policy_ruleset(self) -> Optional[dict]:
        with self._lock:
            meta = self._conn.execute(
                "SELECT rule_version FROM policy_ruleset_meta WHERE id = 1"
            ).fetchone()
            if meta is None:
                return None
            rows = self._conn.execute("SELECT * FROM policy_rules ORDER BY id").fetchall()
        return {"rule_version": meta["rule_version"], "rules": [self._rule_row_to_dict(r) for r in rows]}

    def replace_policy_ruleset(self, rule_version: str, rules: list[dict]) -> None:
        # No explicit BEGIN needed - sqlite3 opens an implicit transaction
        # before the first DML statement, so everything below commits (or, on
        # error, rolls back) as one atomic unit rather than the old
        # read-modify-write-the-whole-YAML-file race.
        with self._lock:
            self._conn.execute("DELETE FROM policy_rules")
            for rule in rules:
                self._conn.execute(
                    """INSERT INTO policy_rules
                       (id, description, type, enabled, applies_to_category, applies_to_oe_code,
                        cap, threshold, min_ratio, max_ratio, max_days, window_days, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    self._rule_dict_to_row(rule),
                )
            self._conn.execute(
                """INSERT INTO policy_ruleset_meta (id, rule_version) VALUES (1, ?)
                   ON CONFLICT(id) DO UPDATE SET rule_version = excluded.rule_version""",
                (rule_version,),
            )
            self._conn.commit()

    def bootstrap_policy_ruleset(self, rule_version: str, rules: list[dict]) -> None:
        with self._lock:
            (count,) = self._conn.execute("SELECT COUNT(*) FROM policy_rules").fetchone()
        if count:
            return
        self.replace_policy_ruleset(rule_version, rules)


class LocalVectorIndex(VectorIndex):
    """pgvector shim: stores embeddings as JSON and searches with NumPy cosine.

    Correctness-equivalent to the ivfflat cosine index for the dataset sizes in
    simulation mode (hundreds to low thousands of receipts). Not intended for
    production scale - that is what the Postgres backend is for.
    """

    def __init__(self, store: SqliteAuditStore, dim: int):
        self._store = store
        self._dim = dim
        self._conn = store._conn  # shares the same connection/schema
        self._lock = store._lock

    def upsert(
        self,
        line_item_id: str,
        submission_id: str,
        employee_id: str,
        embedding: list[float],
        amount: Optional[float] = None,
        txn_date: Optional[date] = None,
    ) -> None:
        if len(embedding) != self._dim:
            raise ValueError(f"embedding dim {len(embedding)} != expected {self._dim}")
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO receipt_embeddings
                   (line_item_id, submission_id, employee_id, embedding, amount, txn_date)
                   VALUES (?,?,?,?,?,?)""",
                (
                    line_item_id,
                    submission_id,
                    employee_id,
                    json.dumps(embedding),
                    amount,
                    txn_date.isoformat() if txn_date else None,
                ),
            )
            self._conn.commit()

    def search(
        self,
        embedding: list[float],
        k: int = 5,
        exclude_submission_id: Optional[str] = None,
    ) -> list[VectorMatch]:
        query = np.asarray(embedding, dtype=np.float64)
        qnorm = np.linalg.norm(query)
        if qnorm == 0:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT line_item_id, submission_id, employee_id, amount, embedding "
                "FROM receipt_embeddings"
            ).fetchall()
        matches: list[VectorMatch] = []
        for r in rows:
            if exclude_submission_id and r["submission_id"] == exclude_submission_id:
                continue
            vec = np.asarray(json.loads(r["embedding"]), dtype=np.float64)
            vnorm = np.linalg.norm(vec)
            if vnorm == 0:
                continue
            score = float(np.dot(query, vec) / (qnorm * vnorm))
            matches.append(
                VectorMatch(
                    line_item_id=r["line_item_id"],
                    submission_id=r["submission_id"],
                    score=score,
                    employee_id=r["employee_id"],
                    amount=r["amount"],
                )
            )
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:k]
