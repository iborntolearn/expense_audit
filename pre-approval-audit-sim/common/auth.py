"""Local username/password auth for the operator app (Solution Design 10:
SSO/RBAC is a baseline-only integration seam in this build - this is that
baseline, not a real IdP integration).

Users live in `config/users.yaml` (username, display_name, role, salted
PBKDF2 hash) - edited via System admin -> Users like any other config in this
app, never hand-rolled elsewhere. Three roles exist - see streamlit_app.py for
how each gates page navigation:
  * admin    - full access, including Settings/System admin.
  * user     - business pages (Dashboard, Expense reports incl. approve/
               reject, User analytics, Ask, Reports & exports).
  * auditor  - read-only external-audit view (BR-TE-AU-10): Dashboard,
               Expense reports (no approve/reject), Reports & exports (incl.
               the compliance report packs) - nothing else.
"""
from __future__ import annotations

import hashlib
import secrets
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from config.settings import REPO_ROOT

_DEFAULT_PATH = REPO_ROOT / "config" / "users.yaml"
_PBKDF2_ITERATIONS = 200_000


class Role(str, Enum):
    admin = "admin"
    user = "user"
    auditor = "auditor"


class UserRecord(BaseModel):
    username: str
    display_name: str
    role: Role
    salt: str      # hex
    password_hash: str  # hex, pbkdf2_hmac-sha256(password, salt, _PBKDF2_ITERATIONS)
    # Tenant scope (multi-OE rollout). None = unscoped/global - only meaningful
    # for role=admin (a global super-admin who can see/manage every OE); every
    # other role is expected to carry a real OE code. An admin WITH an oe_code
    # set is an "OE admin" scoped to just that one operating entity - this is
    # deliberately not a 4th Role value, just an orthogonal field, so the
    # existing 3-role gating (require_role) is untouched.
    oe_code: Optional[str] = None


class UsersConfig(BaseModel):
    users: list[UserRecord] = Field(default_factory=list)


def hash_password(password: str, salt_hex: Optional[str] = None) -> tuple[str, str]:
    """Returns (salt_hex, hash_hex). Pass salt_hex to verify against an
    existing salt; omit it to generate a fresh one for a new/reset password."""
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, expected_hash_hex: str) -> bool:
    _, computed = hash_password(password, salt_hex)
    return secrets.compare_digest(computed, expected_hash_hex)


def load_users(path: Path = _DEFAULT_PATH) -> UsersConfig:
    if not path.exists():
        return UsersConfig(users=[])
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return UsersConfig.model_validate(raw)


def authenticate(username: str, password: str, path: Path = _DEFAULT_PATH) -> Optional[UserRecord]:
    """Users now live in the DB-backed ConfigStore (services/user_service.py),
    not config/users.yaml - this signature stays unchanged so callers that
    still exist outside the REST API (auth_ui.py's Streamlit login gate) keep
    working with zero changes. A non-default `path` is a test/tooling escape
    hatch: it bypasses the DB entirely and authenticates straight against
    that YAML file, exactly like this function did before the DB migration."""
    if path != _DEFAULT_PATH:
        cfg = load_users(path)
        for u in cfg.users:
            if u.username == username:
                return u if verify_password(password, u.salt, u.password_hash) else None
        return None

    from data.factory import get_default_config_store
    from services.user_service import UserService

    return UserService(get_default_config_store()).authenticate(username, password)
