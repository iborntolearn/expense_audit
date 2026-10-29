"""Oracle E-Business Suite connector (FinanceMasterConnector) - read-only
cost-center/vendor master-data lookup.

Oracle EBS is an on-prem ERP, not natively REST - unlike Concur/Workday
there's no single universal "Oracle EBS REST API" every tenant exposes the
same way. Real integrations typically go through Oracle's Integrated SOA
Gateway (REST-wrapped PL/SQL APIs) or Oracle Integration Cloud (OIC) sitting
in front of EBS. This module targets the Integrated SOA Gateway REST shape
(the most common path for a net-new integration) behind the same OAuth2 +
httpx pattern as every other real connector here - confirm the exact
resource paths against the target EBS instance's actual SOA Gateway/OIC
configuration before going live.

Scope boundary: reference-data lookup only, matching every other connector
here - see adapters/connectors/base.py's module docstring. No reimbursement
journal-entry posting in this pass (a natural, separate follow-up).
"""
from __future__ import annotations

import logging
import random
from typing import Optional

from adapters.connectors.base import FinanceMasterConnector
from common.schemas import CostCenterRecord, VendorRecord

logger = logging.getLogger("adapters.connectors.oracle_ebs")


class SimulatedOracleEbsConnector(FinanceMasterConnector):
    """Offline, deterministic - every lookup is derived from a fixed seed on
    the lookup key itself, so the same cost_center/vendor_id always returns
    the same record, with no real EBS instance involved."""

    def health_check(self) -> bool:
        return True

    def get_cost_center(self, cost_center: str, oe_code: str) -> Optional[CostCenterRecord]:
        if not cost_center or not oe_code:
            return None
        return CostCenterRecord(cost_center=cost_center, oe_code=oe_code, active=True)

    def get_vendor(self, vendor_id: str) -> Optional[VendorRecord]:
        if not vendor_id:
            return None
        rng = random.Random(vendor_id)
        return VendorRecord(
            vendor_id=vendor_id, name=f"Vendor {vendor_id}",
            blocked=rng.random() < 0.05,  # a small, deterministic fraction flagged blocked
        )


class RealOracleEbsConnector(FinanceMasterConnector):
    """Real Oracle EBS integration via Integrated SOA Gateway REST services -
    OAuth2 client-credentials token, then a REST GET against the cost-center
    and vendor-master resources. Lazy-imports httpx so the simulated path
    never needs it installed for an offline-only dev setup."""

    def __init__(self, client_id: str, client_secret: str, base_url: str):
        if not client_id or not client_secret or not base_url:
            raise RuntimeError(
                "Oracle EBS connector requires oracle_ebs_client_id, "
                "oracle_ebs_client_secret, and oracle_ebs_base_url. Use the "
                "simulated connector for offline dev."
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
                "/oauth2/token",
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
            logger.warning("Oracle EBS health check failed: %s", exc)
            return False

    def get_cost_center(self, cost_center: str, oe_code: str) -> Optional[CostCenterRecord]:  # pragma: no cover - requires live API
        token = self._access_token()
        resp = self._client.get(
            "/webservices/rest/GLCostCenterService/costCenters",
            headers={"Authorization": f"Bearer {token}"},
            params={"costCenterCode": cost_center, "ledgerCode": oe_code},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            return None
        item = items[0]
        return CostCenterRecord(
            cost_center=cost_center, oe_code=oe_code,
            active=str(item.get("status", "ACTIVE")).upper() == "ACTIVE",
        )

    def get_vendor(self, vendor_id: str) -> Optional[VendorRecord]:  # pragma: no cover - requires live API
        token = self._access_token()
        resp = self._client.get(
            f"/webservices/rest/APVendorService/vendors/{vendor_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return VendorRecord(
            vendor_id=vendor_id, name=data.get("vendorName", vendor_id),
            blocked=str(data.get("holdFlag", "N")).upper() == "Y",
        )
