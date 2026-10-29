"""Veriflow - Pre-Approval Expense Audit, unified operator application.

Single Streamlit app, grouped top-nav via st.navigation. Requires login
(auth_ui.require_login(), backed by config/users.yaml) before anything else
renders; the nav below is then built based on the logged-in user's role
(admin / user / auditor - BR-TE-AU-10):
  * Overview      - Dashboard                                admin, user, auditor
  * Audit         - Expense reports (also the review queue - a "Pending
                    review only" filter narrows to submissions awaiting a
                    decision; approve/reject hidden for auditor - read-only)
                                                               admin, user, auditor
  * Insights      - User analytics, Ask                       admin, user
                  - Reports & exports (incl. compliance packs) admin, user, auditor
  * Configuration - Settings, System admin                     admin only

Visual design (dark theme, tabs, KPI cards, step-flow) is ported from the SOA
Layout Agent app for look-and-feel parity across both applications - see
ui_kit.py.

Run from the repo root:  streamlit run streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402

import auth_ui  # noqa: E402
import ui_kit  # noqa: E402
from app_common import get_data_layer  # noqa: E402
from config.settings import get_settings  # noqa: E402

st.set_page_config(page_title="Veriflow — Pre-Approval Expense Audit", page_icon="▣", layout="wide")

ui_kit.inject_theme()
ui_kit.register_altair_theme()

user = auth_ui.require_login()  # halts here (st.stop()) until logged in

# ─── Sidebar: brand + mode + pending-review badge ──────────────────────────────
with st.sidebar:
    st.markdown(
        f"""
    <div style="padding:.6rem 0 1rem;border-bottom:1px solid {ui_kit.COLORS['border']};margin-bottom:.75rem">
        <div style="font-size:1.15rem;font-weight:800;color:{ui_kit.COLORS['accent_bright']};
                    letter-spacing:-.03em;display:flex;align-items:center;gap:6px">
            <span style="background:{ui_kit.COLORS['bg_overlay']};border:1px solid {ui_kit.COLORS['accent']};
                         border-radius:6px;padding:2px 7px;font-size:.85rem">▣</span>
            Veriflow
        </div>
        <div style="font-size:.65rem;color:{ui_kit.COLORS['text_muted']};font-family:'JetBrains Mono',monospace;
                    text-transform:uppercase;letter-spacing:.12em;margin-top:4px;padding-left:2px">
            Pre-Approval · Sandbox
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    settings = get_settings()
    mode_line = f"{ui_kit.mode_label(settings.simulation_mode.value)} · {settings.storage_backend.value}"
    st.markdown(
        f"""
    <div style="margin:.4rem 0 .3rem;padding:.55rem .8rem;background:{ui_kit.COLORS['success_bg']};
                border:1px solid {ui_kit.COLORS['success']}40;border-radius:8px;
                display:flex;align-items:center;gap:10px">
        <span style="font-size:1.1rem;color:{ui_kit.COLORS['success']};line-height:1">◉</span>
        <div style="min-width:0">
            <div style="font-size:.6rem;color:{ui_kit.COLORS['text_muted']};text-transform:uppercase;
                        letter-spacing:.1em;line-height:1;margin-bottom:3px">Mode</div>
            <div style="font-size:.76rem;font-weight:600;color:{ui_kit.COLORS['success_text']};
                        font-family:'JetBrains Mono',monospace;line-height:1;white-space:nowrap;
                        overflow:hidden;text-overflow:ellipsis">{mode_line}</div>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    try:
        _recent_logs = get_data_layer().store.get_recent_pipeline_logs(limit=4)
    except Exception:
        _recent_logs = []
    if _recent_logs:
        _last = _recent_logs[0]
        _icon = "✓" if _last.get("ok") else "✗"
        _color = ui_kit.COLORS["success_text"] if _last.get("ok") else ui_kit.COLORS["error_text"]
        st.markdown(
            f"""
        <div style="margin-top:.5rem;font-family:'JetBrains Mono',monospace;font-size:.68rem;
                    color:{ui_kit.COLORS['text_muted']}">
            Last processed<br>
            <span style="color:{_color}">{_icon} {_last.get('submission_id','')}</span>
            <span style="color:{ui_kit.COLORS['text_muted']}"> · {_last.get('node','')} · """
            f"""{_last.get('latency_ms', 0):.0f}ms</span>
        </div>
        """,
            unsafe_allow_html=True,
        )

    try:
        pending = len(get_data_layer().store.list_review_queue())
    except Exception:
        pending = 0
    if pending:
        st.markdown(
            f"""
        <div style="background:{ui_kit.COLORS['warning_bg']};border:1px solid {ui_kit.COLORS['warning']};
                    border-radius:8px;padding:.4rem .7rem;margin-top:.5rem;font-size:.75rem;
                    color:{ui_kit.COLORS['warning_text']}">
            ⚠ {pending} report(s) need review
        </div>
        """,
            unsafe_allow_html=True,
        )

    st.divider()
    auth_ui.render_sidebar_identity()

# ─── Navigation (role-gated: Configuration only registers for admins - a ───────
# ─── non-admin can't reach Settings/System admin even via a direct URL) ────────
_nav = {
    "Overview": [
        st.Page("app_pages/dashboard.py", title="Dashboard", icon=":material/dashboard:"),
    ],
    "Audit": [
        st.Page("app_pages/expenses.py", title="Expense reports",
                icon=":material/receipt_long:", default=True),
    ],
}
if user["role"] == "auditor":
    # Read-only external-audit view (BR-TE-AU-10): decisions + evidence +
    # compliance report packs only - no behavioural analytics, no assistant,
    # no approve/reject (expenses.py itself hides that action for this role).
    _nav["Insights"] = [
        st.Page("app_pages/reports.py", title="Reports & exports",
                icon=":material/summarize:"),
    ]
else:
    _nav["Insights"] = [
        st.Page("app_pages/user_analytics.py", title="User analytics",
                icon=":material/person_search:"),
        st.Page("app_pages/assistant.py", title="Ask", icon=":material/chat:"),
        st.Page("app_pages/reports.py", title="Reports & exports",
                icon=":material/summarize:"),
    ]
if user["role"] == "admin":
    _nav["Configuration"] = [
        st.Page("app_pages/settings.py", title="Settings", icon=":material/settings:"),
        st.Page("app_pages/system_admin.py", title="System admin",
                icon=":material/admin_panel_settings:"),
    ]

page = st.navigation(_nav, position="top")

st.title(f"{page.icon} {page.title}")
st.caption("Sandbox mode - synthetic data only.")
page.run()
