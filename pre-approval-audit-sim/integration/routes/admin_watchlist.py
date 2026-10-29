"""GET/POST/DELETE /admin/watchlist - wraps config_admin.py's merchant
blocklist CRUD (System admin -> Merchant watchlist tab), plus the
merchant_registry sub-routes (a real DB-backed table the live pipeline
actually reads/writes - see VerificationAgent._merchant/_track_merchants_seen
- vs. the YAML blocklist above, which remains only its one-time bootstrap
seed, same treatment as policy_rules.yaml). Global-admin-only: sanctions/PEP
screening is a shared, company-wide list (mirrors how this is usually
centrally managed in a real org), not something to fragment per-OE."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

import config_admin as ca
from integration.api_schemas import AddBlocklistEntryRequest, UpdateMerchantStatusRequest
from integration.security import TokenUser, require_global_admin

router = APIRouter(prefix="/admin/watchlist", tags=["admin-watchlist"])
_admin = require_global_admin()


@router.get("")
def list_entries(user: TokenUser = Depends(_admin)) -> list[dict]:
    return ca.load_blocklist_raw()["entries"]


@router.post("")
def add_entry(payload: AddBlocklistEntryRequest, user: TokenUser = Depends(_admin)) -> dict:
    try:
        ca.add_blocklist_entry(payload.name, payload.entry_type, payload.reason)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"name": payload.name, "ok": True}


@router.delete("/{name}")
def delete_entry(name: str, user: TokenUser = Depends(_admin)) -> dict:
    try:
        ca.delete_blocklist_entry(name)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"name": name, "ok": True}


@router.get("/registry")
def list_registry(
    request: Request, user: TokenUser = Depends(_admin), status_filter: Optional[str] = None,
) -> list[dict]:
    return request.app.state.data.store.list_merchant_registry(status=status_filter)


@router.patch("/registry/{merchant_key}")
def update_registry_entry(
    merchant_key: str, payload: UpdateMerchantStatusRequest,
    request: Request, user: TokenUser = Depends(_admin),
) -> dict:
    request.app.state.data.store.set_merchant_status(
        merchant_key,
        status=payload.status,
        risk_tier=payload.risk_tier,
        reason=payload.reason,
        source="admin_override",
        updated_by=user.username,
        force=True,
    )
    return {"merchant_key": merchant_key, "ok": True}
