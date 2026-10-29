"""Integration-connector contracts (Cytric, Oracle E-Business Suite, Workday,
SAP Concur) - the seam a real integration engineer plugs credentials into.

Three ABCs, not one uniform interface, because the four systems do genuinely
different jobs (Solution Design 2.1/2.2):
  * SubmissionConnector          - Concur, Cytric: pull new expense/travel
                                   submissions in, push audit decisions back
                                   out. Maps directly onto the existing
                                   SubmissionCreatedEvent/AuditDecisionWriteback
                                   webhook contracts (common/schemas.py).
  * EmployeeDirectoryConnector   - Workday: read-only employee master-data
                                   lookup (manager/cost-center/department).
  * FinanceMasterConnector       - Oracle EBS: read-only cost-center/vendor
                                   master-data lookup.

Scope boundary (deliberate, not an oversight): these are reference-data
lookups only - no write-back beyond SubmissionConnector.post_decision, and
nothing in pipeline/agents/*.py calls these yet. Wiring a real check (e.g.
RiskAgent using a real Workday manager for segregation-of-duty) is a natural
follow-up once the connectors themselves exist, kept separate so this stays a
clean integration seam rather than a policy/risk-engine redesign.

Each connector role gets a Simulated* implementation (offline, deterministic,
reuses this app's own synthetic/fixture data - safe to run with zero
credentials) and a Real* implementation (lazy-imports httpx, real OAuth2 +
REST, raises a clear RuntimeError if credentials are missing) - the exact
same shape as adapters/vision.py's VisionExtractor/Simulated/Anthropic/
AzureOpenAI split.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from common.schemas import (
    AuditDecisionWriteback,
    CostCenterRecord,
    EmployeeRecord,
    SubmissionCreatedEvent,
    VendorRecord,
)


class SubmissionConnector(ABC):
    """Expense/travel submission source (Concur, Cytric)."""

    @abstractmethod
    def health_check(self) -> bool:
        """True if the connector can reach the remote system (or, for a
        Simulated* implementation, always True - there is no remote system)."""

    @abstractmethod
    def fetch_new_submissions(self) -> list[SubmissionCreatedEvent]:
        """Pull submissions created/updated since the last call. A real
        implementation is responsible for its own since-cursor bookkeeping."""

    @abstractmethod
    def post_decision(self, decision: AuditDecisionWriteback) -> None:
        """Push a final audit decision back to the source system."""


class EmployeeDirectoryConnector(ABC):
    """Employee master-data lookup (Workday). Read-only - see module
    docstring for the scope boundary."""

    @abstractmethod
    def health_check(self) -> bool:
        ...

    @abstractmethod
    def get_employee(self, employee_id: str) -> Optional[EmployeeRecord]:
        ...


class FinanceMasterConnector(ABC):
    """Cost-center/vendor master-data lookup (Oracle E-Business Suite).
    Read-only - see module docstring for the scope boundary."""

    @abstractmethod
    def health_check(self) -> bool:
        ...

    @abstractmethod
    def get_cost_center(self, cost_center: str, oe_code: str) -> Optional[CostCenterRecord]:
        ...

    @abstractmethod
    def get_vendor(self, vendor_id: str) -> Optional[VendorRecord]:
        ...
