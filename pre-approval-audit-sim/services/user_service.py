"""User account CRUD - the service-based layer between routes/config_admin
and ConfigStore persistence.
"""
from __future__ import annotations

from typing import Optional

from common.auth import Role, UserRecord, hash_password, verify_password
from data.interfaces import ConfigStore


class UserService:
    def __init__(self, config: ConfigStore):
        self._config = config

    def list_users(self) -> list[UserRecord]:
        return self._config.list_users()

    def get_user(self, username: str) -> Optional[UserRecord]:
        return self._config.get_user(username)

    def authenticate(self, username: str, password: str) -> Optional[UserRecord]:
        record = self._config.get_user(username)
        if record is None:
            return None
        return record if verify_password(password, record.salt, record.password_hash) else None

    def add_user(
        self, username: str, display_name: str, role: str, password: str,
        oe_code: Optional[str] = None,
    ) -> None:
        salt, pw_hash = hash_password(password)
        self._config.add_user(UserRecord(
            username=username, display_name=display_name, role=Role(role),
            oe_code=oe_code, salt=salt, password_hash=pw_hash,
        ))

    def reset_password(self, username: str, new_password: str) -> None:
        if self._config.get_user(username) is None:
            raise ValueError(f"user {username!r} not found")
        salt, pw_hash = hash_password(new_password)
        self._config.update_user_password(username, salt, pw_hash)

    def set_role(self, username: str, role: str) -> None:
        current = self._config.get_user(username)
        if current is None:
            raise ValueError(f"user {username!r} not found")
        # Same last-GLOBAL-admin-demotion guard the Streamlit Users tab and the
        # REST admin_users route enforce, refined to count only global admins
        # (oe_code=None) - an OE-scoped 'admin' isn't the tier this protects.
        global_admin_count = sum(
            1 for u in self._config.list_users() if u.role == Role.admin and u.oe_code is None
        )
        if (
            current.role == Role.admin and current.oe_code is None
            and Role(role) != Role.admin and global_admin_count <= 1
        ):
            raise ValueError("cannot demote the last global admin account")
        self._config.update_user_role(username, Role(role))

    def set_oe(self, username: str, oe_code: Optional[str]) -> None:
        if self._config.get_user(username) is None:
            raise ValueError(f"user {username!r} not found")
        self._config.update_user_oe(username, oe_code)

    def delete_user(self, username: str) -> None:
        if self._config.get_user(username) is None:
            raise ValueError(f"user {username!r} not found")
        remaining_has_global_admin = any(
            u.role == Role.admin and u.oe_code is None
            for u in self._config.list_users() if u.username != username
        )
        if not remaining_has_global_admin:
            raise ValueError("cannot delete the last global admin account")
        self._config.delete_user(username)
