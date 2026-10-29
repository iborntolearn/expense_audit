"""Abstract persistence contracts.

Every persistence concern sits behind one of these interfaces so that swapping
the dev fallback (sqlite_local) for the pinned production stack
(Postgres + pgvector) - or later swapping local blob storage for Azure Blob -
is a substitution, not a rewrite (Build Brief 7). No module above the data layer
imports a concrete backend; they depend only on these ABCs and on
`data.factory`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Optional

from common.auth import Role, UserRecord
from common.schemas import (
    AuditDecisionWriteback,
    AuditState,
    ExtractedLine,
    PolicyEvaluation,
    RoutingDecision,
    SubmissionCreatedEvent,
    VerificationResult,
)


# --------------------------------------------------------------------------- #
# Value objects used at the persistence boundary
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class VectorMatch:
    line_item_id: str
    submission_id: str
    score: float  # cosine similarity in [-1, 1]
    employee_id: Optional[str] = None
    amount: Optional[float] = None


# --------------------------------------------------------------------------- #
# Audit / decision store
# --------------------------------------------------------------------------- #
class AuditStore(ABC):
    """System of record for every audit outcome (Solution Design 8).

    Phase 0 defines the full surface; later phases fill in the write paths as
    their agents come online. Persistence methods accept already-validated
    domain objects (Pydantic models / AuditState) rather than raw rows.
    """

    # --- lifecycle ---
    @abstractmethod
    def migrate(self) -> None:
        """Apply the schema migration(s). Idempotent."""

    @abstractmethod
    def health(self) -> bool:
        """Return True if the store is reachable and the schema is present."""

    @abstractmethod
    def table_names(self) -> list[str]:
        """Return the set of tables that currently exist (used by tests)."""

    @abstractmethod
    def close(self) -> None:
        ...

    @abstractmethod
    def purge_all(self) -> dict[str, int]:
        """Delete every row of transactional data (submissions and everything
        derived from them) - NOT schema/config. Returns {table: rows_deleted}
        for UI feedback. Irreversible; callers must gate this behind an
        explicit user confirmation."""

    # --- writes ---
    @abstractmethod
    def save_submission(self, event: SubmissionCreatedEvent, is_synthetic: bool) -> None:
        ...

    # Per-node write-through persistence (Solution Design 8: every decision and
    # its inputs are logged as they are produced; supports P3 checkpointing).
    @abstractmethod
    def save_extracted_lines(self, submission_id: str, lines: list[ExtractedLine]) -> None:
        ...

    @abstractmethod
    def save_verification(self, submission_id: str, verification: VerificationResult) -> None:
        ...

    @abstractmethod
    def save_policy(
        self, submission_id: str, evaluation: PolicyEvaluation, *, rule_version: str
    ) -> None:
        ...

    @abstractmethod
    def save_risk(
        self,
        submission_id: str,
        *,
        risk_score: float,
        routing_decision: RoutingDecision,
        model_version: str,
        explanation: str | None,
    ) -> None:
        ...

    @abstractmethod
    def save_receipt_refs(self, submission_id: str, refs: list[tuple[str, str]]) -> None:
        """Persist (line_id, receipt_url) evidence pointers for a submission."""

    @abstractmethod
    def save_report_lines(
        self, submission_id: str, lines: list[tuple[str, str, float, str]]
    ) -> None:
        """Persist (line_id, category, entered_amount, currency) business fields."""

    @abstractmethod
    def save_writeback(self, decision: AuditDecisionWriteback) -> None:
        ...

    # --- observability: per-node execution trace ---
    @abstractmethod
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
        """Record one node's execution outcome - timing, retry attempts,
        pass/fail, and short human-readable input/output summaries. This is the
        "how did end-to-end processing work" trace (mirrors the SOA Layout
        Agent app's per-run step log, adapted to our per-submission unit of
        work)."""

    @abstractmethod
    def get_pipeline_steps(self, submission_id: str) -> list[dict]:
        """The full step-by-step trace for one submission, in execution order."""

    @abstractmethod
    def get_recent_pipeline_logs(self, limit: int = 1000) -> list[dict]:
        """Recent step-log rows across all submissions, most recent first -
        used by the aggregate observability view."""

    @abstractmethod
    def recent_employee_category_lines(
        self, employee_id: str, category: str, since_date: str,
        *, exclude_submission_id: Optional[str] = None,
    ) -> list[dict]:
        """This employee's OTHER lines in this category with an extracted
        transaction date on/after since_date (ISO date string) - rows
        (submission_id, line_id, entered_amount, currency, txn_date). Used for
        velocity + split-transaction detection (BR-TE-AU-19), which look across
        an employee's history, not just the current submission."""

    @abstractmethod
    def category_amount_stats(
        self, oe_code: str, category: str, *, exclude_employee_id: Optional[str] = None,
    ) -> dict:
        """Population statistics (mean, stddev, n) of entered_amount across
        every report line in this OE+category, across ALL employees (or every
        employee except `exclude_employee_id`, so a submission's own history
        doesn't skew its own peer baseline). This is the live-computed
        baseline peer-group outlier detection compares one submission's
        category spend against - {"mean": float, "stddev": float, "n": int}."""

    @abstractmethod
    def find_by_vendor_invoice(
        self, vendor: str, invoice_number: str, *, exclude_submission_id: str,
    ) -> list[dict]:
        """Other submissions with an extracted line whose normalized
        (lower/trim vendor, invoice_number) exactly matches this pair - rows
        {"submission_id": str, "line_id": str}. Structured sibling of the
        embedding-based duplicate search: catches a resubmission whose image
        was edited enough to drop embedding similarity, but whose printed
        invoice number is identical."""

    # --- merchant registry (BR-TE-AU-03 successor) ---
    @abstractmethod
    def bootstrap_merchant_registry(self, entries: list[dict]) -> None:
        """Seed merchant_registry from config/merchant_blocklist.yaml's
        entries (each {"name", "type", "reason"}) exactly once - a no-op if
        the table already has any rows, so re-running migrate() never resets
        an admin's edits or the pipeline's first-seen tracking. Mirrors
        ConfigStore.bootstrap_policy_ruleset()'s idempotency."""

    @abstractmethod
    def upsert_merchant_seen(self, vendor: str) -> None:
        """First/last-seen tracking: insert a 'clear' row if this normalized
        vendor name has never been seen, else bump last_seen_at and
        submission_count. Callers should wrap this in a non-fatal try/except
        (same pattern as VerificationAgent._index()'s vector-upsert call) - a
        failure here must not affect the submission's own decision."""

    @abstractmethod
    def get_merchant(self, merchant_key: str) -> Optional[dict]:
        """One merchant_registry row by its normalized key, or None."""

    @abstractmethod
    def list_merchant_registry(self, *, status: Optional[str] = None) -> list[dict]:
        """Every merchant_registry row, optionally filtered by status."""

    @abstractmethod
    def set_merchant_status(
        self, merchant_key: str, *, display_name: Optional[str] = None,
        status: Optional[str] = None, risk_tier: Optional[str] = None,
        reason: Optional[str] = None, source: str = "auto",
        updated_by: Optional[str] = None, force: bool = False,
    ) -> None:
        """Admin override or auto-flag write - the same method serves both,
        distinguished by `source`/`updated_by` (admin username vs 'auto'/
        None). Refuses to downgrade a row whose current source is
        'admin_override' unless `force=True`, so an admin's explicit verdict
        on a merchant can't be silently overwritten by the next matching
        submission's auto-flagging. Creates the row if it doesn't exist yet
        (display_name required in that case)."""

    @abstractmethod
    def merchant_employee_spread(self, vendor: str, *, since_date: str) -> dict:
        """Distinct-employee and submission count for this normalized vendor
        since since_date (ISO date string) - {"distinct_employees": int,
        "submissions": int}. Live SQL aggregation (category_amount_stats'
        precedent), not a maintained rolling-stats table. Used to flag a
        rarely-seen merchant suddenly used by many distinct employees in a
        short window."""

    @abstractmethod
    def merchant_near_cap_clustering(
        self, vendor: str, category: str, oe_code: str, cap: float, *,
        tolerance_pct: float, since_date: str,
    ) -> dict:
        """Count of DISTINCT employees whose entered_amount for this
        vendor+category+OE falls within tolerance_pct below cap, since
        since_date - {"distinct_employees_near_cap": int, "n": int}. Cross-
        employee structuring signal, distinct from _structuring's single-
        employee split-transaction check."""

    # --- reviewer UI reads (Milestone 9) ---
    @abstractmethod
    def list_review_queue(self) -> list[dict]:
        """Submissions routed to human_review with no reviewer action yet,
        highest risk first."""

    @abstractmethod
    def get_case_detail(self, submission_id: str) -> Optional[dict]:
        """Full case: submission, extracted lines, verification, policy, risk,
        and receipt evidence pointers."""

    @abstractmethod
    def analytics_rows(self) -> dict[str, list[dict]]:
        """Raw rows for the business dashboard, keyed by table name
        (submissions, risk_decisions, report_lines, policy_evaluations,
        verification, reviewer_actions, extracted_line_items). Array columns are
        returned already parsed to Python lists. Aggregation happens in the
        dashboard layer so this stays dialect-agnostic."""

    # --- case management (BR-TE-AU-13) ---
    @abstractmethod
    def set_case_status(
        self, submission_id: str, *, status: str,
        recovered_amount: Optional[float] = None, updated_by: Optional[str] = None,
    ) -> None:
        """Upsert this case's status (open/in_review/awaiting_traveller/
        resolved/claw_back_pending) - independent of reviewer_actions/
        final_decision; can be set at any point in a case's lifecycle."""

    @abstractmethod
    def get_case_status(self, submission_id: str) -> Optional[dict]:
        """This case's current status row, or None if never set (implicitly
        'open')."""

    @abstractmethod
    def list_case_statuses(self) -> list[dict]:
        """Every case-status row - used for recoverable-funds reporting."""

    def save_audit_state(
        self, state: AuditState, *, rule_version: str, model_version: str
    ) -> None:
        """Convenience: persist a whole AuditState via the per-node writers.
        Used by tests and any caller that has a complete state in hand."""
        self.save_extracted_lines(state.submission_id, state.extracted_lines)
        self.save_verification(state.submission_id, state.verification)
        self.save_policy(state.submission_id, state.policy_evaluation, rule_version=rule_version)
        if state.risk_score is not None and state.routing_decision is not None:
            self.save_risk(
                state.submission_id,
                risk_score=state.risk_score,
                routing_decision=state.routing_decision,
                model_version=model_version,
                explanation=state.explanation,
            )

    # --- reads ---
    @abstractmethod
    def get_submission(self, submission_id: str) -> Optional[dict]:
        ...

    @abstractmethod
    def has_decision(self, submission_id: str) -> bool:
        """True if a risk decision already exists for this submission.

        Used for idempotency: a duplicate webhook delivery must not trigger a
        second audit run (Tech Design 3.4)."""


# --------------------------------------------------------------------------- #
# Vector index (duplicate detection)
# --------------------------------------------------------------------------- #
class VectorIndex(ABC):
    """Embedding store + nearest-neighbour search (Tech Design 4.1)."""

    @abstractmethod
    def upsert(
        self,
        line_item_id: str,
        submission_id: str,
        employee_id: str,
        embedding: list[float],
        amount: Optional[float] = None,
        txn_date: Optional[date] = None,
    ) -> None:
        ...

    @abstractmethod
    def search(
        self,
        embedding: list[float],
        k: int = 5,
        exclude_submission_id: Optional[str] = None,
    ) -> list[VectorMatch]:
        """Return up to k nearest neighbours by cosine similarity, most similar first."""


# --------------------------------------------------------------------------- #
# Blob storage (raw receipts)
# --------------------------------------------------------------------------- #
class BlobStore(ABC):
    """Raw receipt image/PDF storage (Solution Design 7.2)."""

    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Store bytes under `key`; return a URL/URI usable by `get`."""

    @abstractmethod
    def get(self, url: str) -> bytes:
        ...

    @abstractmethod
    def exists(self, url: str) -> bool:
        ...

    @abstractmethod
    def purge_all(self) -> int:
        """Delete every stored blob (receipts, sidecars). Returns the count of
        files deleted. Irreversible; callers must gate this behind an explicit
        user confirmation."""


# --------------------------------------------------------------------------- #
# Config store (user accounts + per-OE config overrides - multi-tenancy)
# --------------------------------------------------------------------------- #
class ConfigStore(ABC):
    """User account + OE config-override persistence.

    `pipeline.yaml`/`policy_rules.yaml`/`thresholds.yaml`/`generator.yaml`
    themselves stay plain YAML (rarely-written config-as-code); only the two
    pieces with real write contention - user accounts and per-OE override
    documents - live here, behind the same swappable-backend seam as
    `AuditStore`.
    """

    @abstractmethod
    def migrate(self) -> None:
        """Apply the schema migration(s); idempotent. Also bootstraps
        app_users from config/users.yaml exactly once, the first time the
        table is empty, so the existing seeded accounts keep working."""

    @abstractmethod
    def health(self) -> bool:
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    # --- users ---
    @abstractmethod
    def list_users(self) -> list[UserRecord]:
        ...

    @abstractmethod
    def get_user(self, username: str) -> Optional[UserRecord]:
        ...

    @abstractmethod
    def add_user(self, record: UserRecord) -> None:
        """Raises ValueError if the username already exists."""

    @abstractmethod
    def update_user_password(self, username: str, salt: str, password_hash: str) -> None:
        """Raises ValueError if the user does not exist."""

    @abstractmethod
    def update_user_role(self, username: str, role: Role) -> None:
        """Raises ValueError if the user does not exist."""

    @abstractmethod
    def update_user_oe(self, username: str, oe_code: Optional[str]) -> None:
        """Raises ValueError if the user does not exist."""

    @abstractmethod
    def delete_user(self, username: str) -> None:
        """Raises ValueError if the user does not exist."""

    # --- OE config overrides (pipeline/generator/thresholds only -
    # policy_rules.yaml has its own OE-filtering logic and stays fully
    # YAML-native, see config_admin.py::load_policy/save_policy) ---
    @abstractmethod
    def get_override(self, name: str, oe_code: str) -> Optional[dict]:
        ...

    @abstractmethod
    def save_override(self, name: str, oe_code: str, data: dict) -> None:
        """Upsert."""

    @abstractmethod
    def delete_override(self, name: str, oe_code: str) -> None:
        ...

    # --- business-rule engine ruleset (services/policy_rule_service.py) ---
    @abstractmethod
    def get_policy_ruleset(self) -> Optional[dict]:
        """The full ruleset as {"rule_version": str, "rules": [...]}, or None
        if the table has never been bootstrapped (callers fall back to
        config/policy_rules.yaml - see common/policy.py::load_policy_rules)."""

    @abstractmethod
    def replace_policy_ruleset(self, rule_version: str, rules: list[dict]) -> None:
        """Atomically replace the ENTIRE ruleset (delete-all/insert-all in one
        transaction) - the write half of what used to be a read-modify-write
        race across the whole config/policy_rules.yaml file. OE-scoped
        partial-save semantics (only touch one OE's slice, leave the rest
        untouched) are the caller's responsibility (services/
        policy_rule_service.py) - this method always receives the complete,
        already-merged rule list to persist."""

    @abstractmethod
    def bootstrap_policy_ruleset(self, rule_version: str, rules: list[dict]) -> None:
        """Seed the table from config/policy_rules.yaml exactly once, only if
        genuinely empty - mirrors ConfigStore.migrate()'s app_users bootstrap.
        A no-op if the table already has rows."""
