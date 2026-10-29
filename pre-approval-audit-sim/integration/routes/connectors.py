"""GET/PUT /admin/connectors, POST /admin/connectors/{role}/test - wraps the
System Admin Connectors tab. Admin-only. A real (non-simulated) connector's
test-connection call is gated behind settings.live_mode_active, exactly like
integration/app.py's `_require_simulation()` gates the webhook routes - a
real outbound call to Concur/Cytric/Workday/Oracle EBS can never happen by
accident in this build.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from adapters.connectors.config import (
    ConnectorsConfig,
    load_connectors_config,
    save_connectors_config,
)
from adapters.connectors.factory import (
    build_employee_directory_connector,
    build_finance_master_connector,
    build_submission_connector,
)
from common.auth import Role
from config.settings import get_settings
from integration.security import TokenUser, require_role

router = APIRouter(prefix="/admin/connectors", tags=["admin-connectors"])
_admin = require_role(Role.admin)

_ROLE_PROVIDERS: dict[str, list[str]] = {
    "submission_source": ["simulated", "concur", "cytric"],
    "employee_directory": ["simulated", "workday"],
    "finance_master": ["simulated", "oracle_ebs"],
}

# Which Settings fields must be non-empty for a real provider to count as
# "configured" - mirrors each Real*Connector's own __init__ guard.
_REQUIRED_SETTINGS_FIELDS: dict[str, list[str]] = {
    "concur": ["concur_client_id", "concur_client_secret", "concur_base_url"],
    "cytric": ["cytric_client_id", "cytric_client_secret", "cytric_base_url"],
    "workday": ["workday_client_id", "workday_client_secret", "workday_base_url", "workday_tenant"],
    "oracle_ebs": ["oracle_ebs_client_id", "oracle_ebs_client_secret", "oracle_ebs_base_url"],
}


def _configured(provider: str) -> bool:
    if provider == "simulated":
        return True
    settings = get_settings()
    return all(bool(getattr(settings, f, "")) for f in _REQUIRED_SETTINGS_FIELDS.get(provider, []))


@router.get("")
def get_connectors_status(user: TokenUser = Depends(_admin)) -> dict:
    cfg = load_connectors_config()
    return {
        role: {
            "provider": provider,
            "options": _ROLE_PROVIDERS[role],
            "configured": _configured(provider),
        }
        for role, provider in cfg.model_dump().items()
    }


class ConnectorsConfigRequest(BaseModel):
    submission_source: Literal["simulated", "concur", "cytric"]
    employee_directory: Literal["simulated", "workday"]
    finance_master: Literal["simulated", "oracle_ebs"]


@router.put("")
def put_connectors_config(payload: ConnectorsConfigRequest, user: TokenUser = Depends(_admin)) -> dict:
    save_connectors_config(ConnectorsConfig(**payload.model_dump()))
    return {
        "ok": True,
        "note": "settings saved; restart the API process to rebuild the already-built "
                "connector registry (app.state.connectors)",
    }


@router.post("/{role}/test")
def test_connector(role: str, request: Request, user: TokenUser = Depends(_admin)) -> dict:
    if role not in _ROLE_PROVIDERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown connector role: {role!r}")

    settings = get_settings()
    cfg = load_connectors_config()
    provider = getattr(cfg, role)
    if provider != "simulated" and not settings.live_mode_active:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            f"{provider!r} is a real (non-simulated) connector - {settings.live_mode_blocked_reason}",
        )

    # Built fresh from the CURRENT config on every call (not the connector
    # registry cached on app.state at startup) so a just-saved provider
    # change is reflected immediately, without needing a process restart.
    try:
        if role == "submission_source":
            connector = build_submission_connector(provider, settings, request.app.state.data.blobs)
        elif role == "employee_directory":
            connector = build_employee_directory_connector(provider, settings)
        else:
            connector = build_finance_master_connector(provider, settings)
        ok = connector.health_check()
    except Exception as exc:
        return {"provider": provider, "ok": False, "detail": str(exc)}
    return {"provider": provider, "ok": ok, "detail": ""}
