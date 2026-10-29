"""Cytric (Amadeus Cytric Travel & Expense) connector (SubmissionConnector).

Cytric combines trip booking with expense capture, so a real submission
often carries trip-level context (booking date, cabin class, trip start/end)
that this app's `SubmissionCreatedEvent`/`ReportLine` contracts don't have
fields for today - extending those schemas is a separate, deliberate change
(it would also need Advanced Fraud Detection / policy-rule work upstream),
not bundled into this connector. `_to_event` below maps only the fields the
existing contract already has room for.

Cytric's real API surface is a REST + OAuth2 flow, but exact endpoint paths
vary more by tenant/deployment than Concur's - confirm against the target
tenant's API documentation before going live. Real, runnable code, not a
stub - just unverified against a live tenant (`pragma: no cover - requires
live API`, same convention as every other real connector/extractor here).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from adapters.connectors.base import SubmissionConnector
from common.policy import PolicyRuleSet, load_policy_rules
from common.schemas import AuditDecisionWriteback, ReportLine, SourceSystem, SubmissionCreatedEvent
from data.interfaces import BlobStore
from generator.config import load_generator_config
from generator.synthesize import Synthesizer

logger = logging.getLogger("adapters.connectors.cytric")


class SimulatedCytricConnector(SubmissionConnector):
    """Offline, deterministic - reuses the same synthetic generator as
    SimulatedConcurConnector (same underlying `SubmissionCreatedEvent` shape),
    tagged as `source_system=cytric` so downstream reporting can tell the two
    simulated sources apart."""

    def __init__(self, blobs: BlobStore, rules: PolicyRuleSet | None = None, batch_size: int = 5):
        self._blobs = blobs
        self._rules = rules or load_policy_rules()
        self._batch_size = batch_size
        self._poll_count = 0

    def health_check(self) -> bool:
        return True

    def fetch_new_submissions(self) -> list[SubmissionCreatedEvent]:
        self._poll_count += 1
        cfg = load_generator_config().model_copy(
            update={"volume": self._batch_size, "seed": 10_000 + self._poll_count}
        )
        events, _gt = Synthesizer(cfg, self._rules, self._blobs).generate()
        for ev in events:
            ev.source_system = SourceSystem.cytric
        return events

    def post_decision(self, decision: AuditDecisionWriteback) -> None:
        logger.info(
            "SimulatedCytricConnector: decision for %s -> %s",
            decision.submission_id, decision.decision.value,
        )


class RealCytricConnector(SubmissionConnector):
    """Real Cytric integration - OAuth2 client-credentials token, then a
    REST pull of submitted expense reports. Lazy-imports httpx so the
    simulated path never needs it installed for an offline-only dev setup."""

    def __init__(self, client_id: str, client_secret: str, base_url: str):
        if not client_id or not client_secret or not base_url:
            raise RuntimeError(
                "Cytric connector requires cytric_client_id, cytric_client_secret, "
                "and cytric_base_url. Use the simulated connector for offline dev."
            )
        import httpx  # noqa: F401

        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self._base_url, timeout=30.0)
        self._token: str | None = None

    def _access_token(self) -> str:  # pragma: no cover - requires live API
        if self._token is None:
            resp = self._client.post(
                "/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            resp.raise_for_status()
            self._token = resp.json()["access_token"]
        return self._token

    def health_check(self) -> bool:  # pragma: no cover - requires live API
        try:
            self._access_token()
            return True
        except Exception as exc:
            logger.warning("Cytric health check failed: %s", exc)
            return False

    def fetch_new_submissions(self) -> list[SubmissionCreatedEvent]:  # pragma: no cover - requires live API
        token = self._access_token()
        resp = self._client.get(
            "/api/v1/expense-reports",
            headers={"Authorization": f"Bearer {token}"},
            params={"status": "submitted"},
        )
        resp.raise_for_status()
        return [self._to_event(item) for item in resp.json().get("reports", [])]

    def _to_event(self, item: dict) -> SubmissionCreatedEvent:  # pragma: no cover - requires live API
        lines = [
            ReportLine(
                line_id=str(entry.get("id")),
                category=entry.get("expenseType", "misc"),
                entered_amount=float(entry["amount"]),
                receipt_url=entry.get("receiptUrl") or "",
            )
            for entry in item.get("lines", [])
        ]
        return SubmissionCreatedEvent(
            submission_id=str(item["id"]),
            source_system=SourceSystem.cytric,
            source_system_ref=item.get("reference", str(item["id"])),
            oe_code=item.get("legalEntityCode", ""),
            employee_id=item["travelerId"],
            cost_center=item.get("costCenter"),
            currency=item.get("currency", "USD"),
            submitted_at=datetime.fromisoformat(item["submittedAt"]) if item.get("submittedAt")
            else datetime.now(timezone.utc),
            report_lines=lines,
        )

    def post_decision(self, decision: AuditDecisionWriteback) -> None:  # pragma: no cover - requires live API
        token = self._access_token()
        resp = self._client.post(
            f"/api/v1/expense-reports/{decision.submission_id}/decision",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "decision": decision.decision.value,
                "comment": decision.rationale or "",
            },
        )
        resp.raise_for_status()
