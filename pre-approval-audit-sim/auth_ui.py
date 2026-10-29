"""Login gate for the operator app - renders a centered login form and halts
the script (st.stop()) until `common.auth.authenticate()` succeeds against
`config/users.yaml`. Call `require_login()` once, right after page config +
theme injection, before building navigation; every page after that point can
assume `st.session_state[SESSION_KEY]` is populated.
"""
from __future__ import annotations

import streamlit as st

import ui_kit
from common.auth import authenticate

SESSION_KEY = "auth_user"

ADMIN_ROLE = "admin"
AUDITOR_ROLE = "auditor"


def current_user() -> dict | None:
    return st.session_state.get(SESSION_KEY)


def is_admin() -> bool:
    user = current_user()
    return bool(user and user["role"] == ADMIN_ROLE)


def is_auditor() -> bool:
    user = current_user()
    return bool(user and user["role"] == AUDITOR_ROLE)


def require_login() -> dict:
    """Returns the authenticated user dict ({username, display_name, role}).
    Renders the login form and calls st.stop() if not yet authenticated -
    nothing after this call in the caller's script runs until login succeeds."""
    user = current_user()
    if user:
        return user

    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown(
            f"""
        <div style="text-align:center;padding:1.5rem 0 .5rem">
            <span style="background:{ui_kit.COLORS['bg_overlay']};border:1px solid {ui_kit.COLORS['accent']};
                         border-radius:8px;padding:6px 12px;font-size:1.3rem">▣</span>
            <div style="margin-top:.6rem;font-size:1.3rem;font-weight:800;
                        color:{ui_kit.COLORS['accent_bright']};letter-spacing:-.02em">
                Veriflow
            </div>
            <div style="font-size:.75rem;color:{ui_kit.COLORS['text_secondary']};margin-top:1px">
                Pre-Approval Expense Audit
            </div>
            <div style="font-size:.7rem;color:{ui_kit.COLORS['text_muted']};font-family:'JetBrains Mono',monospace;
                        text-transform:uppercase;letter-spacing:.12em;margin-top:2px">
                Sandbox
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in", type="primary", width="stretch")

        if submitted:
            record = authenticate(username.strip(), password)
            if record:
                st.session_state[SESSION_KEY] = {
                    "username": record.username,
                    "display_name": record.display_name,
                    "role": record.role.value,
                }
                st.rerun()
            else:
                st.error("Invalid username or password.")

    st.stop()


def render_sidebar_identity() -> None:
    """Logged-in-as strip + logout button - call from the sidebar, after
    require_login() has already run."""
    user = current_user()
    if not user:
        return
    st.markdown(
        f"""
    <div style="margin:.4rem 0 .3rem;padding:.5rem .7rem;background:{ui_kit.COLORS['bg_overlay']};
                border:1px solid {ui_kit.COLORS['border']};border-radius:8px">
        <div style="font-size:.6rem;color:{ui_kit.COLORS['text_muted']};text-transform:uppercase;
                    letter-spacing:.1em;line-height:1;margin-bottom:3px">Logged in as</div>
        <div style="font-size:.8rem;font-weight:600;color:{ui_kit.COLORS['text_primary']};line-height:1.3">
            {user['display_name']}
        </div>
        <div style="font-size:.68rem;color:{ui_kit.COLORS['text_secondary']}">
            {user['role']}
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )
    if st.button("Log out", icon=":material/logout:", width="stretch", key="logout_btn"):
        st.session_state.pop(SESSION_KEY, None)
        st.rerun()


def require_admin() -> None:
    """Defense-in-depth guard for admin-only pages: even if a non-admin user
    somehow reaches this page (bookmarked URL, race during a role change),
    the page's own script blocks rather than relying solely on it being
    absent from st.navigation."""
    if not is_admin():
        st.error("This page requires an admin account.")
        st.stop()
