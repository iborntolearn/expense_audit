"""Workday connector (EmployeeDirectoryConnector) - read-only employee
master-data lookup (Workday REST API v1, Workers resource).

Scope boundary: reference-data lookup only, matching every other connector
here - see adapters/connectors/base.py's module docstring. Nothing in
pipeline/agents/*.py calls this yet (e.g. a real APPR-02 segregation-of-duty
check against a real manager hierarchy is a natural, separate follow-up).
"""
from __future__ import annotations

import logging
import random
from typing import Optional

from adapters.connectors.base import EmployeeDirectoryConnector
from common.schemas import EmployeeRecord

logger = logging.getLogger("adapters.connectors.workday")

# Deterministic small fixture, keyed to match generator/synthesize.py's
# synthetic employee_id pattern (f"EMP-{(i % 40) + 1:04d}") so a simulated
# lookup succeeds for every employee_id the synthetic generator can produce,
# without needing a real Workday tenant.
_MANAGERS = ["EMP-0001", "EMP-0002", "EMP-0003", "EMP-0004"]
_DEPARTMENTS = ["Finance", "Sales", "Engineering", "Operations", "Legal"]


class SimulatedWorkdayConnector(EmployeeDirectoryConnector):
    """Offline, deterministic - every lookup is derived from a fixed seed on
    the employee_id itself, so the same employee_id always returns the same
    record, with no real Workday tenant involved."""

    def health_check(self) -> bool:
        return True

    def get_employee(self, employee_id: str) -> Optional[EmployeeRecord]:
        if not employee_id:
            return None
        rng = random.Random(employee_id)
        manager_candidates = [m for m in _MANAGERS if m != employee_id] or _MANAGERS
        return EmployeeRecord(
            employee_id=employee_id,
            display_name=f"Employee {employee_id}",
            manager_id=rng.choice(manager_candidates),
            cost_center=f"CC-{(rng.randrange(12)) + 1:03d}",
            department=rng.choice(_DEPARTMENTS),
            active=True,
        )


class RealWorkdayConnector(EmployeeDirectoryConnector):
    """Real Workday integration - OAuth2 client-credentials token (Workday's
    API Client / Integration System User pattern), then a REST GET against
    the Workers resource. Lazy-imports httpx so the simulated path never
    needs it installed for an offline-only dev setup."""

    def __init__(self, client_id: str, client_secret: str, base_url: str, tenant: str):
        if not client_id or not client_secret or not base_url or not tenant:
            raise RuntimeError(
                "Workday connector requires workday_client_id, workday_client_secret, "
                "workday_base_url, and workday_tenant. Use the simulated connector "
                "for offline dev."
            )
        import httpx  # noqa: F401

        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._tenant = tenant
        self._client = httpx.Client(base_url=self._base_url, timeout=30.0)
        self._token: str | None = None

    def _access_token(self) -> str:  # pragma: no cover - requires live API
        if self._token is None:
            resp = self._client.post(
                "/ccx/oauth2/token",
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
            logger.warning("Workday health check failed: %s", exc)
            return False

    def get_employee(self, employee_id: str) -> Optional[EmployeeRecord]:  # pragma: no cover - requires live API
        token = self._access_token()
        resp = self._client.get(
            f"/ccx/api/v1/{self._tenant}/workers/{employee_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return EmployeeRecord(
            employee_id=employee_id,
            display_name=data.get("descriptor"),
            manager_id=(data.get("manager") or {}).get("id"),
            cost_center=(data.get("costCenter") or {}).get("id"),
            department=(data.get("organization") or {}).get("descriptor"),
            active=bool(data.get("active", True)),
        )
