"""postgres backend: the pinned production path (Build Brief 4).

Uses Postgres + pgvector exactly as specified in the Detailed Technical Design.
`psycopg` is imported lazily inside `__init__` so that selecting the
sqlite_local fallback never requires a working libpq on the machine.

This backend is committed and ready but is NOT exercised on a machine without
Postgres/Docker. When `docker-compose up` (scripts/docker-compose.yml) brings up
Postgres+pgvector, set STORAGE_BACKEND=postgres and it becomes active with no
other code change.
"""
from __future__ import annotations

import json
import statistics
from datetime import date
from typing import Optional

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

_MIGRATION = REPO_ROOT / "data" / "migrations" / "001_init.sql"


def _merchant_key(name: str) -> str:
    return name.strip().lower()

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


def _vector_literal(embedding: list[float]) -> str:
    # pgvector accepts a textual literal like '[0.1,0.2,...]'
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


class PostgresAuditStore(AuditStore):
    def __init__(self, dsn: str):
        try:
            import psycopg  # noqa: F401
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise RuntimeError(
                "STORAGE_BACKEND=postgres requires the 'psycopg' package and a "
                "reachable Postgres+pgvector instance. Use STORAGE_BACKEND=sqlite_local "
                "for the Docker-free dev fallback."
            ) from exc
        import psycopg

        self._psycopg = psycopg
        self._conn = psycopg.connect(dsn, autocommit=True)

    # --- lifecycle ---
    def migrate(self) -> None:
        sql = _MIGRATION.read_text(encoding="utf-8")
        with self._conn.cursor() as cur:
            cur.execute(sql)
        self._bootstrap_merchant_registry()

    def _bootstrap_merchant_registry(self) -> None:
        from common.blocklist import load_merchant_blocklist

        blocklist = load_merchant_blocklist()
        self.bootstrap_merchant_registry([e.model_dump() for e in blocklist.entries])

    def health(self) -> bool:
        try:
            return set(_EXPECTED_TABLES).issubset(set(self.table_names()))
        except self._psycopg.Error:
            return False

    def table_names(self) -> list[str]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
            return [r[0] for r in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()

    def purge_all(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self._conn.cursor() as cur:
            for table in _EXPECTED_TABLES:
                cur.execute(f"SELECT count(*) FROM {table}")
                counts[table] = cur.fetchone()[0]
            # TRUNCATE ... CASCADE handles the FK ordering in one statement
            # instead of deleting children before parents by hand.
            cur.execute(f"TRUNCATE {', '.join(_EXPECTED_TABLES)} CASCADE")
        return counts

    # --- writes ---
    def save_submission(self, event: SubmissionCreatedEvent, is_synthetic: bool) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO submissions
                   (submission_id, source_system, source_system_ref, oe_code,
                    employee_id, cost_center, currency, submitted_at, is_synthetic)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (submission_id) DO NOTHING""",
                (
                    event.submission_id,
                    event.source_system.value,
                    event.source_system_ref,
                    event.oe_code,
                    event.employee_id,
                    event.cost_center,
                    event.currency,
                    event.submitted_at,
                    is_synthetic,
                ),
            )

    def save_extracted_lines(self, submission_id: str, lines: list[ExtractedLine]) -> None:
        with self._conn.cursor() as cur:
            for ln in lines:
                cur.execute(
                    """INSERT INTO extracted_line_items
                       (line_item_id, submission_id, vendor, txn_date, amount, tax,
                        category, confidence, invoice_number)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (line_item_id) DO UPDATE SET
                         vendor=EXCLUDED.vendor, txn_date=EXCLUDED.txn_date,
                         amount=EXCLUDED.amount, tax=EXCLUDED.tax,
                         confidence=EXCLUDED.confidence, invoice_number=EXCLUDED.invoice_number""",
                    (
                        line_item_id(submission_id, ln.line_id),
                        submission_id,
                        ln.vendor,
                        ln.date,
                        ln.amount,
                        ln.tax,
                        None,
                        ln.confidence,
                        ln.invoice_number,
                    ),
                )

    def save_verification(self, submission_id: str, verification: VerificationResult) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO verification_results
                   (submission_id, authenticity_flags, duplicate_match_ids,
                    subtotal_variance_pct, subtotal_entered_total, subtotal_receipt_total,
                    velocity_flags, split_transaction_flags, merchant_validation, merchant_flags,
                    compliance_flags, peer_outlier_flags, duplicate_match_details,
                    merchant_network_flags)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (submission_id) DO UPDATE SET
                     authenticity_flags=EXCLUDED.authenticity_flags,
                     duplicate_match_ids=EXCLUDED.duplicate_match_ids,
                     subtotal_variance_pct=EXCLUDED.subtotal_variance_pct,
                     subtotal_entered_total=EXCLUDED.subtotal_entered_total,
                     subtotal_receipt_total=EXCLUDED.subtotal_receipt_total,
                     velocity_flags=EXCLUDED.velocity_flags,
                     split_transaction_flags=EXCLUDED.split_transaction_flags,
                     merchant_validation=EXCLUDED.merchant_validation,
                     merchant_flags=EXCLUDED.merchant_flags,
                     compliance_flags=EXCLUDED.compliance_flags,
                     peer_outlier_flags=EXCLUDED.peer_outlier_flags,
                     duplicate_match_details=EXCLUDED.duplicate_match_details,
                     merchant_network_flags=EXCLUDED.merchant_network_flags""",
                (
                    submission_id,
                    verification.authenticity_flags,
                    [m.submission_id for m in verification.duplicate_matches],
                    verification.subtotal_variance_pct,
                    verification.subtotal_entered_total,
                    verification.subtotal_receipt_total,
                    verification.velocity_flags,
                    verification.split_transaction_flags,
                    verification.merchant_validation.value,
                    verification.merchant_flags,
                    verification.compliance_flags,
                    verification.peer_outlier_flags,
                    json.dumps([m.model_dump(mode="json") for m in verification.duplicate_matches]),
                    verification.merchant_network_flags,
                ),
            )

    def save_policy(
        self, submission_id: str, evaluation: PolicyEvaluation, *, rule_version: str
    ) -> None:
        with self._conn.cursor() as cur:
            for rr in evaluation.rule_results:
                cur.execute(
                    """INSERT INTO policy_evaluations
                       (submission_id, rule_id, rule_version, passed)
                       VALUES (%s,%s,%s,%s)
                       ON CONFLICT (submission_id, rule_id) DO UPDATE SET
                         rule_version=EXCLUDED.rule_version, passed=EXCLUDED.passed""",
                    (submission_id, rr.rule_id, rule_version, rr.passed),
                )

    def save_risk(
        self,
        submission_id: str,
        *,
        risk_score: float,
        routing_decision: RoutingDecision,
        model_version: str,
        explanation: str | None,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO risk_decisions
                   (submission_id, risk_score, routing_decision, model_version, explanation)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (submission_id) DO UPDATE SET
                     risk_score=EXCLUDED.risk_score,
                     routing_decision=EXCLUDED.routing_decision,
                     model_version=EXCLUDED.model_version,
                     explanation=EXCLUDED.explanation""",
                (submission_id, risk_score, routing_decision.value, model_version, explanation),
            )

    def save_receipt_refs(self, submission_id: str, refs: list[tuple[str, str]]) -> None:
        with self._conn.cursor() as cur:
            for line_id, url in refs:
                cur.execute(
                    """INSERT INTO receipt_refs (submission_id, line_id, receipt_url)
                       VALUES (%s,%s,%s)
                       ON CONFLICT (submission_id, line_id) DO UPDATE SET
                         receipt_url = EXCLUDED.receipt_url""",
                    (submission_id, line_id, url),
                )

    def save_report_lines(
        self, submission_id: str, lines: list[tuple[str, str, float, str]]
    ) -> None:
        with self._conn.cursor() as cur:
            for line_id, category, entered_amount, currency in lines:
                cur.execute(
                    """INSERT INTO report_lines
                       (submission_id, line_id, category, entered_amount, currency)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (submission_id, line_id) DO UPDATE SET
                         category=EXCLUDED.category,
                         entered_amount=EXCLUDED.entered_amount,
                         currency=EXCLUDED.currency""",
                    (submission_id, line_id, category, entered_amount, currency),
                )

    def save_writeback(self, decision: AuditDecisionWriteback) -> None:
        if decision.reviewer_id:
            with self._conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO reviewer_actions
                       (submission_id, reviewer_id, final_decision, feedback_notes)
                       VALUES (%s,%s,%s,%s)
                       ON CONFLICT (submission_id) DO UPDATE SET
                         reviewer_id=EXCLUDED.reviewer_id,
                         final_decision=EXCLUDED.final_decision,
                         feedback_notes=EXCLUDED.feedback_notes""",
                    (
                        decision.submission_id,
                        decision.reviewer_id,
                        decision.decision.value,
                        decision.rationale,
                    ),
                )

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
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO pipeline_logs
                   (submission_id, node, ok, attempts, latency_ms,
                    input_summary, output_summary, error_message)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (submission_id, node, ok, attempts, latency_ms,
                 input_summary, output_summary, error_message),
            )

    def get_pipeline_steps(self, submission_id: str) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM pipeline_logs WHERE submission_id = %s ORDER BY id ASC",
                (submission_id,),
            )
            return self._rows(cur)

    def get_recent_pipeline_logs(self, limit: int = 1000) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT * FROM pipeline_logs ORDER BY id DESC LIMIT %s", (limit,))
            return self._rows(cur)

    def recent_employee_category_lines(
        self, employee_id: str, category: str, since_date: str,
        *, exclude_submission_id: Optional[str] = None,
    ) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                """SELECT rl.submission_id, rl.line_id, rl.entered_amount, rl.currency,
                          eli.txn_date
                   FROM report_lines rl
                   JOIN submissions s ON s.submission_id = rl.submission_id
                   JOIN extracted_line_items eli
                     ON eli.submission_id = rl.submission_id
                    AND eli.line_item_id = rl.submission_id || ':' || rl.line_id
                   WHERE s.employee_id = %s AND rl.category = %s AND eli.txn_date >= %s
                     AND (%s::text IS NULL OR rl.submission_id != %s)""",
                (employee_id, category, since_date,
                 exclude_submission_id, exclude_submission_id),
            )
            return self._rows(cur)

    def category_amount_stats(
        self, oe_code: str, category: str, *, exclude_employee_id: Optional[str] = None,
    ) -> dict:
        with self._conn.cursor() as cur:
            cur.execute(
                """SELECT rl.entered_amount
                   FROM report_lines rl
                   JOIN submissions s ON s.submission_id = rl.submission_id
                   WHERE s.oe_code = %s AND rl.category = %s
                     AND (%s::text IS NULL OR s.employee_id != %s)""",
                (oe_code, category, exclude_employee_id, exclude_employee_id),
            )
            amounts = [r[0] for r in cur.fetchall()]
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
        with self._conn.cursor() as cur:
            cur.execute(
                """SELECT submission_id, line_item_id
                   FROM extracted_line_items
                   WHERE lower(trim(vendor)) = lower(trim(%s))
                     AND lower(trim(invoice_number)) = lower(trim(%s))
                     AND submission_id != %s""",
                (vendor, invoice_number, exclude_submission_id),
            )
            rows = self._rows(cur)
        return [{"submission_id": r["submission_id"], "line_id": r["line_item_id"]} for r in rows]

    def bootstrap_merchant_registry(self, entries: list[dict]) -> None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM merchant_registry")
            (count,) = cur.fetchone()
            if count:
                return
            for e in entries:
                cur.execute(
                    """INSERT INTO merchant_registry
                       (merchant_key, display_name, status, risk_tier, source,
                        blocklist_type, reason)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (merchant_key) DO NOTHING""",
                    (_merchant_key(e["name"]), e["name"], "blocked", "high",
                     "bootstrap_yaml", e.get("type"), e.get("reason")),
                )

    def upsert_merchant_seen(self, vendor: str) -> None:
        if not vendor:
            return
        key = _merchant_key(vendor)
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO merchant_registry (merchant_key, display_name, submission_count)
                   VALUES (%s,%s,1)
                   ON CONFLICT (merchant_key) DO UPDATE SET
                     submission_count = merchant_registry.submission_count + 1,
                     last_seen_at = now()""",
                (key, vendor),
            )

    def get_merchant(self, merchant_key: str) -> Optional[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM merchant_registry WHERE merchant_key = %s",
                (_merchant_key(merchant_key),),
            )
            rows = self._rows(cur)
        return rows[0] if rows else None

    def list_merchant_registry(self, *, status: Optional[str] = None) -> list[dict]:
        with self._conn.cursor() as cur:
            if status is None:
                cur.execute("SELECT * FROM merchant_registry ORDER BY last_seen_at DESC")
            else:
                cur.execute(
                    "SELECT * FROM merchant_registry WHERE status = %s ORDER BY last_seen_at DESC",
                    (status,),
                )
            return self._rows(cur)

    def set_merchant_status(
        self, merchant_key: str, *, display_name: Optional[str] = None,
        status: Optional[str] = None, risk_tier: Optional[str] = None,
        reason: Optional[str] = None, source: str = "auto",
        updated_by: Optional[str] = None, force: bool = False,
    ) -> None:
        key = _merchant_key(merchant_key)
        with self._conn.cursor() as cur:
            cur.execute("SELECT source FROM merchant_registry WHERE merchant_key = %s", (key,))
            existing = cur.fetchone()
            if existing and existing[0] == "admin_override" and not force:
                return
            if existing is None:
                cur.execute(
                    """INSERT INTO merchant_registry
                       (merchant_key, display_name, status, risk_tier, source, reason, updated_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (key, display_name or merchant_key, status or "clear", risk_tier or "low",
                     source, reason, updated_by),
                )
            else:
                sets, params = [], []
                if display_name is not None:
                    sets.append("display_name = %s"); params.append(display_name)
                if status is not None:
                    sets.append("status = %s"); params.append(status)
                if risk_tier is not None:
                    sets.append("risk_tier = %s"); params.append(risk_tier)
                if reason is not None:
                    sets.append("reason = %s"); params.append(reason)
                sets.append("source = %s"); params.append(source)
                sets.append("updated_by = %s"); params.append(updated_by)
                sets.append("updated_at = now()")
                params.append(key)
                cur.execute(
                    f"UPDATE merchant_registry SET {', '.join(sets)} WHERE merchant_key = %s",
                    params,
                )

    def merchant_employee_spread(self, vendor: str, *, since_date: str) -> dict:
        with self._conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT s.employee_id, eli.submission_id
                   FROM extracted_line_items eli
                   JOIN submissions s ON s.submission_id = eli.submission_id
                   WHERE lower(trim(eli.vendor)) = lower(trim(%s)) AND s.submitted_at >= %s""",
                (vendor, since_date),
            )
            rows = self._rows(cur)
        return {
            "distinct_employees": len({r["employee_id"] for r in rows}),
            "submissions": len({r["submission_id"] for r in rows}),
        }

    def merchant_near_cap_clustering(
        self, vendor: str, category: str, oe_code: str, cap: float, *,
        tolerance_pct: float, since_date: str,
    ) -> dict:
        floor = cap * (1 - tolerance_pct / 100.0)
        with self._conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT s.employee_id
                   FROM report_lines rl
                   JOIN submissions s ON s.submission_id = rl.submission_id
                   JOIN extracted_line_items eli
                     ON eli.submission_id = rl.submission_id
                    AND eli.line_item_id = rl.submission_id || ':' || rl.line_id
                   WHERE lower(trim(eli.vendor)) = lower(trim(%s))
                     AND rl.category = %s AND s.oe_code = %s AND s.submitted_at >= %s
                     AND rl.entered_amount <= %s AND rl.entered_amount >= %s""",
                (vendor, category, oe_code, since_date, cap, floor),
            )
            rows = self._rows(cur)
        return {
            "distinct_employees_near_cap": len({r["employee_id"] for r in rows}),
            "n": len(rows),
        }

    def set_case_status(
        self, submission_id: str, *, status: str,
        recovered_amount: Optional[float] = None, updated_by: Optional[str] = None,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO case_status (submission_id, status, recovered_amount, updated_by)
                   VALUES (%s,%s,%s,%s)
                   ON CONFLICT (submission_id) DO UPDATE SET
                     status=EXCLUDED.status,
                     recovered_amount=EXCLUDED.recovered_amount,
                     updated_by=EXCLUDED.updated_by,
                     updated_at=now()""",
                (submission_id, status, recovered_amount, updated_by),
            )

    def get_case_status(self, submission_id: str) -> Optional[dict]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT * FROM case_status WHERE submission_id = %s", (submission_id,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))

    def list_case_statuses(self) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT * FROM case_status")
            return self._rows(cur)

    # --- reads ---
    def get_submission(self, submission_id: str) -> Optional[dict]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT * FROM submissions WHERE submission_id = %s", (submission_id,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))

    def has_decision(self, submission_id: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM risk_decisions WHERE submission_id = %s LIMIT 1",
                (submission_id,),
            )
            return cur.fetchone() is not None

    def _rows(self, cur) -> list[dict]:
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def list_review_queue(self) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                """SELECT s.submission_id, s.oe_code, s.employee_id, s.currency,
                          s.submitted_at, r.risk_score, r.explanation
                   FROM submissions s
                   JOIN risk_decisions r ON s.submission_id = r.submission_id
                   LEFT JOIN reviewer_actions ra ON s.submission_id = ra.submission_id
                   WHERE r.routing_decision = 'human_review' AND ra.submission_id IS NULL
                   ORDER BY r.risk_score DESC, s.submitted_at ASC"""
            )
            return self._rows(cur)

    def get_case_detail(self, submission_id: str) -> Optional[dict]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT * FROM submissions WHERE submission_id = %s", (submission_id,))
            sub = self._rows(cur)
            if not sub:
                return None
            cur.execute(
                "SELECT * FROM extracted_line_items WHERE submission_id = %s", (submission_id,)
            )
            lines = self._rows(cur)
            cur.execute(
                "SELECT * FROM verification_results WHERE submission_id = %s", (submission_id,)
            )
            ver = self._rows(cur)
            cur.execute(
                "SELECT * FROM policy_evaluations WHERE submission_id = %s", (submission_id,)
            )
            pol = self._rows(cur)
            cur.execute("SELECT * FROM risk_decisions WHERE submission_id = %s", (submission_id,))
            risk = self._rows(cur)
            cur.execute(
                "SELECT line_id, receipt_url FROM receipt_refs WHERE submission_id = %s",
                (submission_id,),
            )
            refs = self._rows(cur)
        verification = ver[0] if ver else {}
        if verification:
            verification["duplicate_match_details"] = json.loads(
                verification.get("duplicate_match_details") or "[]"
            )
            verification["merchant_network_flags"] = verification.get("merchant_network_flags") or []
        return {
            "submission": sub[0],
            "extracted_lines": lines,
            "verification": verification,
            "policy": pol,
            "risk": risk[0] if risk else {},
            "receipts": refs,
        }

    def analytics_rows(self) -> dict[str, list[dict]]:
        with self._conn.cursor() as cur:
            def rows(sql: str) -> list[dict]:
                cur.execute(sql)
                return self._rows(cur)

            data = {
                "submissions": rows("SELECT * FROM submissions"),
                "risk_decisions": rows("SELECT * FROM risk_decisions"),
                "report_lines": rows("SELECT * FROM report_lines"),
                "policy_evaluations": rows("SELECT * FROM policy_evaluations"),
                "verification": rows("SELECT * FROM verification_results"),
                "reviewer_actions": rows("SELECT * FROM reviewer_actions"),
                "extracted_line_items": rows("SELECT * FROM extracted_line_items"),
            }
        # Postgres TEXT[] already deserialises to Python lists; normalise nulls.
        for v in data["verification"]:
            v["authenticity_flags"] = v.get("authenticity_flags") or []
            v["duplicate_match_ids"] = v.get("duplicate_match_ids") or []
            v["velocity_flags"] = v.get("velocity_flags") or []
            v["split_transaction_flags"] = v.get("split_transaction_flags") or []
            v["merchant_flags"] = v.get("merchant_flags") or []
            v["compliance_flags"] = v.get("compliance_flags") or []
            v["peer_outlier_flags"] = v.get("peer_outlier_flags") or []
            v["duplicate_match_details"] = json.loads(v.get("duplicate_match_details") or "[]")
            v["merchant_network_flags"] = v.get("merchant_network_flags") or []
        return data


class PostgresConfigStore(ConfigStore):
    """Shares PostgresAuditStore's connection, mirroring PgVectorIndex's
    pattern of taking the store instance rather than opening a second
    connection to the same dsn."""

    _MIGRATION = REPO_ROOT / "data" / "migrations" / "002_config.sql"
    _USERS_YAML = REPO_ROOT / "config" / "users.yaml"

    def __init__(self, store: PostgresAuditStore):
        self._conn = store._conn
        self._psycopg = store._psycopg

    def migrate(self) -> None:
        sql = self._MIGRATION.read_text(encoding="utf-8")
        with self._conn.cursor() as cur:
            cur.execute(sql)
        self._bootstrap_users()
        self._bootstrap_policy_rules()

    def _bootstrap_policy_rules(self) -> None:
        from common.policy import load_policy_rules

        ruleset = load_policy_rules()
        self.bootstrap_policy_ruleset(
            ruleset.rule_version, [r.model_dump(mode="json") for r in ruleset.rules],
        )

    def _bootstrap_users(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM app_users")
            (count,) = cur.fetchone()
        if count or not self._USERS_YAML.exists():
            return
        import yaml

        raw = yaml.safe_load(self._USERS_YAML.read_text(encoding="utf-8")) or {}
        users = raw.get("users") or []
        if not users:
            return
        with self._conn.cursor() as cur:
            for u in users:
                cur.execute(
                    """INSERT INTO app_users
                       (username, display_name, role, oe_code, salt, password_hash)
                       VALUES (%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (username) DO NOTHING""",
                    (u["username"], u["display_name"], u["role"], u.get("oe_code"),
                     u["salt"], u["password_hash"]),
                )

    def health(self) -> bool:
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT 1 FROM app_users LIMIT 1")
            return True
        except self._psycopg.Error:
            return False

    def close(self) -> None:
        pass  # shares PostgresAuditStore's connection - that store owns close()

    def _to_record(self, cols: list[str], row: tuple) -> UserRecord:
        d = dict(zip(cols, row))
        return UserRecord(
            username=d["username"], display_name=d["display_name"],
            role=Role(d["role"]), oe_code=d["oe_code"],
            salt=d["salt"], password_hash=d["password_hash"],
        )

    def list_users(self) -> list[UserRecord]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT * FROM app_users ORDER BY username")
            cols = [d[0] for d in cur.description]
            return [self._to_record(cols, r) for r in cur.fetchall()]

    def get_user(self, username: str) -> Optional[UserRecord]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT * FROM app_users WHERE username = %s", (username,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return self._to_record(cols, row)

    def add_user(self, record: UserRecord) -> None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT 1 FROM app_users WHERE username = %s", (record.username,))
            if cur.fetchone():
                raise ValueError(f"user {record.username!r} already exists")
            cur.execute(
                """INSERT INTO app_users
                   (username, display_name, role, oe_code, salt, password_hash)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (record.username, record.display_name, record.role.value,
                 record.oe_code, record.salt, record.password_hash),
            )

    def _require_exists(self, username: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT 1 FROM app_users WHERE username = %s", (username,))
            if not cur.fetchone():
                raise ValueError(f"user {username!r} not found")

    def update_user_password(self, username: str, salt: str, password_hash: str) -> None:
        self._require_exists(username)
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE app_users SET salt = %s, password_hash = %s, updated_at = now() "
                "WHERE username = %s",
                (salt, password_hash, username),
            )

    def update_user_role(self, username: str, role: Role) -> None:
        self._require_exists(username)
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE app_users SET role = %s, updated_at = now() WHERE username = %s",
                (role.value, username),
            )

    def update_user_oe(self, username: str, oe_code: Optional[str]) -> None:
        self._require_exists(username)
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE app_users SET oe_code = %s, updated_at = now() WHERE username = %s",
                (oe_code, username),
            )

    def delete_user(self, username: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM app_users WHERE username = %s", (username,))
            if cur.rowcount == 0:
                raise ValueError(f"user {username!r} not found")

    def get_override(self, name: str, oe_code: str) -> Optional[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT data FROM oe_config_overrides WHERE name = %s AND oe_code = %s",
                (name, oe_code),
            )
            row = cur.fetchone()
        return json.loads(row[0]) if row else None

    def save_override(self, name: str, oe_code: str, data: dict) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO oe_config_overrides (name, oe_code, data, updated_at)
                   VALUES (%s,%s,%s,now())
                   ON CONFLICT (name, oe_code) DO UPDATE SET
                     data = EXCLUDED.data, updated_at = now()""",
                (name, oe_code, json.dumps(data)),
            )

    def delete_override(self, name: str, oe_code: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "DELETE FROM oe_config_overrides WHERE name = %s AND oe_code = %s",
                (name, oe_code),
            )

    # --- business-rule engine ruleset ---
    @staticmethod
    def _rule_row_to_dict(cols: list[str], row: tuple) -> dict:
        d = dict(zip(cols, row))
        return {
            "id": d["id"],
            "description": d["description"],
            "type": d["type"],
            "enabled": bool(d["enabled"]),
            "applies_to": {"category": d["applies_to_category"], "oe_code": d["applies_to_oe_code"]},
            "cap": json.loads(d["cap"]) if d["cap"] else {},
            "threshold": json.loads(d["threshold"]) if d["threshold"] else {},
            "min_ratio": float(d["min_ratio"]) if d["min_ratio"] is not None else None,
            "max_ratio": float(d["max_ratio"]) if d["max_ratio"] is not None else None,
            "max_days": d["max_days"],
            "window_days": d["window_days"],
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
        with self._conn.cursor() as cur:
            cur.execute("SELECT rule_version FROM policy_ruleset_meta WHERE id = 1")
            meta = cur.fetchone()
            if meta is None:
                return None
            cur.execute("SELECT * FROM policy_rules ORDER BY id")
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        return {"rule_version": meta[0], "rules": [self._rule_row_to_dict(cols, r) for r in rows]}

    def replace_policy_ruleset(self, rule_version: str, rules: list[dict]) -> None:
        # The connection defaults to autocommit=True (see __init__) -
        # `.transaction()` temporarily suspends that for this block so the
        # delete-all/insert-all/meta-upsert commits (or rolls back) as one
        # atomic unit, same guarantee as the SQLite implementation's implicit
        # transaction.
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute("DELETE FROM policy_rules")
                for rule in rules:
                    cur.execute(
                        """INSERT INTO policy_rules
                           (id, description, type, enabled, applies_to_category, applies_to_oe_code,
                            cap, threshold, min_ratio, max_ratio, max_days, window_days, updated_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())""",
                        self._rule_dict_to_row(rule),
                    )
                cur.execute(
                    """INSERT INTO policy_ruleset_meta (id, rule_version) VALUES (1, %s)
                       ON CONFLICT (id) DO UPDATE SET rule_version = EXCLUDED.rule_version""",
                    (rule_version,),
                )

    def bootstrap_policy_ruleset(self, rule_version: str, rules: list[dict]) -> None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM policy_rules")
            (count,) = cur.fetchone()
        if count:
            return
        self.replace_policy_ruleset(rule_version, rules)


class PgVectorIndex(VectorIndex):
    def __init__(self, store: PostgresAuditStore, dim: int):
        self._store = store
        self._conn = store._conn
        self._dim = dim

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
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO receipt_embeddings
                   (line_item_id, submission_id, employee_id, embedding, amount, txn_date)
                   VALUES (%s,%s,%s,%s::vector,%s,%s)
                   ON CONFLICT (line_item_id) DO UPDATE SET embedding=EXCLUDED.embedding""",
                (
                    line_item_id,
                    submission_id,
                    employee_id,
                    _vector_literal(embedding),
                    amount,
                    txn_date,
                ),
            )

    def search(
        self,
        embedding: list[float],
        k: int = 5,
        exclude_submission_id: Optional[str] = None,
    ) -> list[VectorMatch]:
        # 1 - cosine_distance = cosine similarity. The vector literal is bound
        # twice (SELECT score + ORDER BY), so it heads the params list both times.
        vec = _vector_literal(embedding)
        where = "WHERE submission_id <> %s" if exclude_submission_id else ""
        params: list = [vec]
        if exclude_submission_id:
            params.append(exclude_submission_id)
        params.extend([vec, k])
        with self._conn.cursor() as cur:
            cur.execute(
                f"""SELECT line_item_id, submission_id,
                          1 - (embedding <=> %s::vector) AS score,
                          employee_id, amount
                    FROM receipt_embeddings
                    {where}
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s""",
                params,
            )
            return [
                VectorMatch(
                    line_item_id=r[0], submission_id=r[1], score=float(r[2]),
                    employee_id=r[3], amount=(float(r[4]) if r[4] is not None else None),
                )
                for r in cur.fetchall()
            ]
