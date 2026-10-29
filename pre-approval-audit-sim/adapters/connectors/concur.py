"""SAP Concur connector (SubmissionConnector) - Concur Expense's OAuth2 +
REST API.

This app already has a Concur-flavoured demo path (`integration/
concur_client.py`, the System Admin "Concur simulator" tabs) - that path
POSTs the app's OWN synthetic payload to its OWN webhook, purely to
demonstrate the over-the-wire contract. This module is the first connector
that would actually talk to a real Concur tenant.

Endpoint paths below follow Concur's OAuth2 client-credentials + Expense
Reports v4 REST shape as publicly documented, but Concur's API surface (v3
vs v4 vs the newer Cloud APIs) varies by tenant/contract - confirm the exact
paths and field names against the target tenant's API documentation before
going live. This is real, runnable code, not a stub - just unverified against
a live tenant, same caveat as `adapters/vision.py`'s AzureOpenAI/Anthropic
extractors (`pragma: no cover - requires live API`).
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

logger = logging.getLogger("adapters.connectors.concur")


class SimulatedConcurConnector(SubmissionConnector):
    """Offline, deterministic - reuses this app's own synthetic generator
    (generator/synthesize.py::Synthesizer) so simulation-mode behaviour needs
    no real Concur credentials at all. Each fetch_new_submissions() call
    generates one small fresh batch, standing in for "reports submitted
    since the last poll"."""

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
            update={"volume": self._batch_size, "seed": self._poll_count}
        )
        events, _gt = Synthesizer(cfg, self._rules, self._blobs).generate()
        for ev in events:
            ev.source_system = SourceSystem.concur
        return events

    def post_decision(self, decision: AuditDecisionWriteback) -> None:
        logger.info(
            "SimulatedConcurConnector: decision for %s -> %s",
            decision.submission_id, decision.decision.value,
        )


class RealConcurConnector(SubmissionConnector):
    """Real SAP Concur integration - OAuth2 client-credentials token, then
    Expense Reports v4 REST calls. Lazy-imports httpx so the simulated path
    never needs it installed for an offline-only dev setup."""

    def __init__(self, client_id: str, client_secret: str, base_url: str):
        if not client_id or not client_secret or not base_url:
            raise RuntimeError(
                "Concur connector requires concur_client_id, concur_client_secret, "
                "and concur_base_url. Use the simulated connector for offline dev."
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
                "/oauth2/v0/token",
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
            logger.warning("Concur health check failed: %s", exc)
            return False

    def fetch_new_submissions(self) -> list[SubmissionCreatedEvent]:  # pragma: no cover - requires live API
        token = self._access_token()
        resp = self._client.get(
            "/api/v4.0/expense/reports",
            headers={"Authorization": f"Bearer {token}"},
            params={"approvalStatusCode": "A_PEND"},  # pending-approval reports only
        )
        resp.raise_for_status()
        return [self._to_event(item) for item in resp.json().get("Reports", [])]

    def _to_event(self, item: dict) -> SubmissionCreatedEvent:  # pragma: no cover - requires live API
        # Concur's report-line detail lives on a separate /expense/entries
        # call in the real v4 API - fetched per report here rather than
        # assuming the report payload embeds lines inline (it usually doesn't).
        token = self._access_token()
        entries_resp = self._client.get(
            "/api/v4.0/expense/entries",
            headers={"Authorization": f"Bearer {token}"},
            params={"reportID": item["ReportID"]},
        )
        entries_resp.raise_for_status()
        lines = [
            ReportLine(
                line_id=entry["ExpenseEntryID"],
                category=entry.get("ExpenseTypeName", "misc"),
                entered_amount=float(entry["TransactionAmount"]),
                receipt_url=entry.get("ReceiptURI") or "",
            )
            for entry in entries_resp.json().get("Items", [])
        ]
        return SubmissionCreatedEvent(
            submission_id=item["ReportID"],
            source_system=SourceSystem.concur,
            source_system_ref=item.get("ReportName", item["ReportID"]),
            oe_code=item.get("LedgerCode") or item.get("CountryCode", ""),
            employee_id=item["EmployeeID"],
            cost_center=item.get("CostCenter"),
            currency=item.get("CurrencyCode", "USD"),
            submitted_at=datetime.fromisoformat(item["SubmitDate"]) if item.get("SubmitDate")
            else datetime.now(timezone.utc),
            report_lines=lines,
        )

    def post_decision(self, decision: AuditDecisionWriteback) -> None:  # pragma: no cover - requires live API
        token = self._access_token()
        resp = self._client.post(
            f"/api/v4.0/expense/reports/{decision.submission_id}/workflowaction",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "Action": "Approve" if decision.decision.value == "approved" else "SendBack",
                "Comment": decision.rationale or "",
            },
        )
        resp.raise_for_status()
