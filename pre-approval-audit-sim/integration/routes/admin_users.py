"""GET/POST/PUT/DELETE /admin/users - wraps config_admin.py's user CRUD
(the System admin -> Users tab). Any admin (global or OE-scoped) can reach
these routes, but an OE-scoped admin only ever sees/manages users in their
OWN oe_code - enforced here, not just hidden in the UI:
  - list: filtered to their own OE
  - add: their new user is always created in their own OE, regardless of
    what oe_code is requested (resolve_oe_scope - same rule as every other
    OE-scoped endpoint)
  - password reset / role change / delete: 404 on a user outside their OE
    (matches check_oe_access's "don't confirm existence" pattern)
  - reassigning a user's OE (`set_oe`) is global-admin-only - moving someone
    between tenants is a cross-OE action that shouldn't be delegable
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from common.auth import Role, UserRecord
from integration.api_schemas import AddUserRequest, ResetPasswordRequest, SetOeRequest, SetRoleRequest
from integration.security import TokenUser, require_global_admin, require_role, resolve_oe_scope
from services.user_service import UserService

router = APIRouter(prefix="/admin/users", tags=["admin-users"])
_admin = require_role(Role.admin)


def _check_user_in_scope(user: TokenUser, target: UserRecord) -> None:
    if user.oe_code is not None and target.oe_code != user.oe_code:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {target.username!r} not found")


@router.get("")
def list_users(request: Request, user: TokenUser = Depends(_admin)) -> list[dict]:
    svc = UserService(request.app.state.data.config)
    return [
        {"username": u.username, "display_name": u.display_name, "role": u.role.value, "oe_code": u.oe_code}
        for u in svc.list_users()
        if user.oe_code is None or u.oe_code == user.oe_code
    ]


@router.post("")
def add_user(payload: AddUserRequest, request: Request, user: TokenUser = Depends(_admin)) -> dict:
    oe_code = resolve_oe_scope(user, payload.oe_code)
    svc = UserService(request.app.state.data.config)
    try:
        svc.add_user(payload.username, payload.display_name, payload.role, payload.password, oe_code=oe_code)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"username": payload.username, "oe_code": oe_code, "ok": True}


@router.put("/{username}/password")
def reset_password(
    username: str, payload: ResetPasswordRequest, request: Request, user: TokenUser = Depends(_admin),
) -> dict:
    svc = UserService(request.app.state.data.config)
    target = svc.get_user(username)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {username!r} not found")
    _check_user_in_scope(user, target)
    svc.reset_password(username, payload.new_password)
    return {"username": username, "ok": True}


@router.put("/{username}/role")
def set_role(
    username: str, payload: SetRoleRequest, request: Request, user: TokenUser = Depends(_admin),
) -> dict:
    svc = UserService(request.app.state.data.config)
    current = svc.get_user(username)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {username!r} not found")
    _check_user_in_scope(user, current)
    try:
        svc.set_role(username, payload.role)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"username": username, "role": payload.role, "ok": True}


@router.put("/{username}/oe")
def set_oe(
    username: str, payload: SetOeRequest, request: Request,
    user: TokenUser = Depends(require_global_admin()),
) -> dict:
    svc = UserService(request.app.state.data.config)
    try:
        svc.set_oe(username, payload.oe_code)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"username": username, "oe_code": payload.oe_code, "ok": True}


@router.delete("/{username}")
def delete_user(username: str, request: Request, user: TokenUser = Depends(_admin)) -> dict:
    svc = UserService(request.app.state.data.config)
    target = svc.get_user(username)
    if target is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"user {username!r} not found")
    _check_user_in_scope(user, target)
    try:
        svc.delete_user(username)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"username": username, "ok": True}
