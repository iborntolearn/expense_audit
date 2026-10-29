"""REST API session tokens - the auth seam for a non-Streamlit frontend.

Streamlit's `auth_ui.py` gates pages via `st.session_state`, which only works
inside a Streamlit script rerun. A React (or any HTTP) client instead needs a
bearer token issued at login and verified on every request - this module is
that seam, wrapping the SAME `common/auth.py` username/password check the
Streamlit app already uses (one user store, two front doors).

Token format is a minimal HMAC-SHA256-signed payload ("JWT-lite"): it is
NOT a spec-compliant JWT (no header, no alg negotiation) - just enough to
authenticate a request without pulling in a new third-party dependency,
matching this codebase's existing convention of implementing auth primitives
directly with stdlib (see common/auth.py's hand-rolled PBKDF2, not passlib).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from common.auth import Role
from config.settings import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(payload_b64: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()


def issue_token(
    username: str, role: Role, display_name: str, *, settings: Settings,
    oe_code: Optional[str] = None,
) -> str:
    payload = {
        "sub": username,
        "role": role.value,
        "name": display_name,
        "oe": oe_code,
        "exp": int(time.time()) + settings.jwt_ttl_minutes * 60,
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _sign(payload_b64, settings.jwt_secret_key)
    return f"{payload_b64}.{sig}"


class TokenUser:
    def __init__(
        self, username: str, role: Role, display_name: str = "",
        oe_code: Optional[str] = None,
    ):
        self.username = username
        self.role = role
        self.display_name = display_name or username
        # None = global/unscoped (only meaningful for role=admin - a super-admin
        # spanning every OE); every other role always carries a real OE code.
        self.oe_code = oe_code


def decode_token(token: str, *, settings: Settings) -> Optional[TokenUser]:
    try:
        payload_b64, sig = token.split(".", 1)
    except ValueError:
        return None
    expected_sig = _sign(payload_b64, settings.jwt_secret_key)
    if not hmac.compare_digest(sig, expected_sig):
        return None
    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, UnicodeDecodeError):
        return None
    if payload.get("exp", 0) < time.time():
        return None
    try:
        return TokenUser(username=payload["sub"], role=Role(payload["role"]),
                          display_name=payload.get("name", ""), oe_code=payload.get("oe"))
    except (KeyError, ValueError):
        return None


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> TokenUser:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    user = decode_token(creds.credentials, settings=settings)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
    return user


def require_role(*roles: Role):
    """Dependency factory - e.g. Depends(require_role(Role.admin, Role.user))
    to block the read-only auditor role from a mutating endpoint, mirroring
    the same role gates auth_ui.py enforces in the Streamlit app."""

    def _check(user: TokenUser = Depends(get_current_user)) -> TokenUser:
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"role '{user.role.value}' is not permitted to perform this action",
            )
        return user

    return _check


def require_global_admin():
    """Dependency factory - only a GLOBAL admin (role=admin, oe_code=None) may
    pass, even though an OE-scoped admin also holds the 'admin' role. Reserved
    for actions that shouldn't be fragmentable per-OE: the merchant watchlist
    (a shared sanctions/PEP list, typically centrally managed rather than
    per-country) and the danger-zone purge (irreversible and system-wide;
    scoping a correct partial purge across every table + blob storage is a
    materially riskier change than the read-side OE scoping elsewhere, so it's
    deliberately out of scope here - an OE admin gets no purge capability at
    all rather than a half-built one)."""

    def _check(user: TokenUser = Depends(require_role(Role.admin))) -> TokenUser:
        if user.oe_code is not None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "this action requires a global admin account, not one scoped to a single OE",
            )
        return user

    return _check


def resolve_oe_scope(user: TokenUser, requested_oe: Optional[str] = None) -> Optional[str]:
    """The oe_code to filter list/aggregate data by for this request.

    A tenant-scoped user (oe_code set) is ALWAYS restricted to their own OE,
    regardless of what they ask for - `requested_oe` is only ever honored for
    a global admin (oe_code is None), letting them narrow to one OE or pass
    None to see every OE combined."""
    if user.oe_code is not None:
        return user.oe_code
    return requested_oe


def check_oe_access(user: TokenUser, resource_oe_code: Optional[str]) -> None:
    """Raise 404 (not 403 - a scoped user shouldn't learn a resource exists in
    a different tenant just from the status code) if a tenant-scoped user
    reaches for a single resource that belongs to a different OE."""
    if user.oe_code is not None and resource_oe_code is not None and resource_oe_code != user.oe_code:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such submission")
