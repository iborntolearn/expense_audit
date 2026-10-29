"""Connector selection - mirrors adapters/factory.py::build_vision_extractor()'s
string-switch pattern, one switch per connector role."""
from __future__ import annotations

from dataclasses import dataclass

from adapters.connectors.base import (
    EmployeeDirectoryConnector,
    FinanceMasterConnector,
    SubmissionConnector,
)
from adapters.connectors.config import ConnectorsConfig
from config.settings import Settings
from data.interfaces import BlobStore


@dataclass
class ConnectorRegistry:
    submission_source: SubmissionConnector
    employee_directory: EmployeeDirectoryConnector
    finance_master: FinanceMasterConnector


def build_submission_connector(provider: str, settings: Settings, blobs: BlobStore) -> SubmissionConnector:
    provider = provider.lower()
    if provider == "simulated":
        from adapters.connectors.concur import SimulatedConcurConnector

        return SimulatedConcurConnector(blobs)
    if provider == "concur":
        from adapters.connectors.concur import RealConcurConnector

        return RealConcurConnector(
            settings.concur_client_id, settings.concur_client_secret, settings.concur_base_url,
        )
    if provider == "cytric":
        from adapters.connectors.cytric import RealCytricConnector

        return RealCytricConnector(
            settings.cytric_client_id, settings.cytric_client_secret, settings.cytric_base_url,
        )
    raise ValueError(f"unknown submission_source provider: {provider!r}")


def build_employee_directory_connector(provider: str, settings: Settings) -> EmployeeDirectoryConnector:
    provider = provider.lower()
    if provider == "simulated":
        from adapters.connectors.workday import SimulatedWorkdayConnector

        return SimulatedWorkdayConnector()
    if provider == "workday":
        from adapters.connectors.workday import RealWorkdayConnector

        return RealWorkdayConnector(
            settings.workday_client_id, settings.workday_client_secret,
            settings.workday_base_url, settings.workday_tenant,
        )
    raise ValueError(f"unknown employee_directory provider: {provider!r}")


def build_finance_master_connector(provider: str, settings: Settings) -> FinanceMasterConnector:
    provider = provider.lower()
    if provider == "simulated":
        from adapters.connectors.oracle_ebs import SimulatedOracleEbsConnector

        return SimulatedOracleEbsConnector()
    if provider == "oracle_ebs":
        from adapters.connectors.oracle_ebs import RealOracleEbsConnector

        return RealOracleEbsConnector(
            settings.oracle_ebs_client_id, settings.oracle_ebs_client_secret,
            settings.oracle_ebs_base_url,
        )
    raise ValueError(f"unknown finance_master provider: {provider!r}")


def build_connectors(settings: Settings, cfg: ConnectorsConfig, blobs: BlobStore) -> ConnectorRegistry:
    return ConnectorRegistry(
        submission_source=build_submission_connector(cfg.submission_source, settings, blobs),
        employee_directory=build_employee_directory_connector(cfg.employee_directory, settings),
        finance_master=build_finance_master_connector(cfg.finance_master, settings),
    )
