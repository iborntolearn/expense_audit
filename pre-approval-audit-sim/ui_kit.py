"""Shared visual design system - ported from the SOA Layout Agent app for
look-and-feel parity across both applications (dark theme, tab styling, KPI
cards, step-flow messages, status chips).

Call `inject_theme()` once per script run (done in streamlit_app.py, before
`page.run()`) and `register_altair_theme()` once so Altair charts pick up the
same palette. The rest of this module is small render helpers pages can reuse.
"""
from __future__ import annotations

import streamlit as st

COLORS = {
    "bg_base": "#0c0f18",
    "bg_surface": "#111520",
    "bg_elevated": "#161b28",
    "bg_overlay": "#1d2436",
    "border": "#232c3e",
    "border_focus": "#3b6bca",
    "accent": "#3b7be8",
    "accent_bright": "#60a5fa",
    "accent_glow": "#3b7be820",
    "purple": "#8b5cf6",
    "text_primary": "#e8edf8",
    "text_secondary": "#8fa3c0",
    "text_muted": "#4a5a74",
    "success": "#22c55e",
    "success_bg": "#0d2218", "success_border": "#166534", "success_text": "#86efac",
    "warning": "#f59e0b",
    "warning_bg": "#1c1505", "warning_border": "#92400e", "warning_text": "#fcd34d",
    "error": "#ef4444",
    "error_bg": "#1c0505", "error_border": "#991b1b", "error_text": "#fca5a5",
    "info_bg": "#0c1628", "info_border": "#1e3a5f", "info_text": "#93c5fd",
}

# Display-only relabelling: internal identifiers (the SIMULATION_MODE env var,
# SimulationMode/SourceSystem enum values, etc.) keep their real names in code
# and config - only what's actually shown to the user is reworded here, in one
# place, so the UI wording can't drift between pages.
MODE_DISPLAY = {"simulation": "Sandbox", "live": "Live"}
SOURCE_SYSTEM_DISPLAY = {"concur": "Concur", "simulation_harness": "Internal harness"}


def mode_label(value: str) -> str:
    return MODE_DISPLAY.get(value, value)


def source_system_label(value: str) -> str:
    return SOURCE_SYSTEM_DISPLAY.get(value, value)


_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
    --bg-base:      #0c0f18;
    --bg-surface:   #111520;
    --bg-elevated:  #161b28;
    --bg-overlay:   #1d2436;
    --border:       #232c3e;
    --border-focus: #3b6bca;
    --accent:       #3b7be8;
    --accent-bright:#60a5fa;
    --accent-glow:  #3b7be820;
    --text-primary: #e8edf8;
    --text-secondary:#8fa3c0;
    --text-muted:   #4a5a74;
    --success:      #22c55e;
    --warning:      #f59e0b;
    --error:        #ef4444;
    --radius-sm:    6px;
    --radius-md:    10px;
    --radius-lg:    14px;
    --transition:   all 0.15s ease;
}

html, body, [class*="css"] {
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 14px;
    color: var(--text-primary);
}
.stApp { background: var(--bg-base); min-height: 100vh; }
header[data-testid="stHeader"] {
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border);
    backdrop-filter: blur(8px);
}
.block-container {
    padding-top: 1.6rem;
    padding-left: 2rem;
    padding-right: 2rem;
    max-width: 1380px;
}

section[data-testid="stSidebar"] {
    background: var(--bg-surface);
    border-right: 1px solid var(--border);
}
section[data-testid="stSidebar"] .block-container {
    padding-top: 0.8rem;
    padding-left: 1rem;
    padding-right: 1rem;
}

.stButton > button {
    background: var(--bg-elevated);
    color: var(--text-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    font-family: 'Inter', sans-serif;
    font-size: 0.82rem;
    font-weight: 500;
    padding: 0.5rem 0.9rem;
    letter-spacing: 0.01em;
    transition: var(--transition);
    min-height: 36px;
}
.stButton > button:hover {
    background: var(--bg-overlay);
    border-color: var(--accent);
    color: var(--accent-bright);
    box-shadow: 0 0 0 1px var(--accent-glow);
}
.stButton > button:active { background: var(--accent-glow); transform: translateY(1px); }
.stButton > button[kind="primary"],
.stButton > button[data-testid*="primary"] {
    background: var(--accent);
    border-color: var(--accent);
    color: #ffffff;
    font-weight: 600;
}
.stButton > button[kind="primary"]:hover {
    background: #2d6dd4;
    border-color: #2d6dd4;
    box-shadow: 0 2px 12px #3b7be840;
}

h1, h2, h3, h4 { color: var(--text-primary); letter-spacing: -0.02em; font-weight: 700; }
h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
h2 { font-size: 1.2rem; }
h3 { font-size: 1rem; }
h4 { font-size: 0.9rem; color: var(--text-secondary); }
p, li { color: var(--text-secondary); line-height: 1.6; }
code, pre {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.78rem;
    background: var(--bg-overlay);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 2px 6px;
    color: var(--accent-bright);
}

/* Top nav renders as st.tabs under the hood */
.stTabs [data-baseweb="tab-list"] {
    gap: 2px;
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border);
    padding: 0 4px;
}
.stTabs [data-baseweb="tab"] {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    font-family: 'Inter', sans-serif;
    font-size: 0.8rem;
    font-weight: 500;
    color: var(--text-muted);
    padding: 0.6rem 1rem;
    transition: var(--transition);
    margin-bottom: -1px;
}
.stTabs [data-baseweb="tab"]:hover { color: var(--text-secondary); background: var(--bg-elevated); }
.stTabs [aria-selected="true"] {
    background: transparent;
    color: var(--accent-bright);
    border-bottom-color: var(--accent);
    font-weight: 600;
}
.stTabs [data-baseweb="tab-panel"] { padding-top: 1.2rem; }

[data-testid="stMetric"] {
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 0.9rem 1rem;
    transition: var(--transition);
}
[data-testid="stMetric"]:hover { border-color: var(--border-focus); }
[data-testid="stMetricLabel"] { color: var(--text-muted) !important; font-size: 0.72rem !important; text-transform: uppercase; letter-spacing: 0.06em; }
[data-testid="stMetricValue"] { color: var(--text-primary) !important; font-size: 1.4rem !important; font-weight: 700; }
[data-testid="stMetricDelta"] { font-size: 0.72rem !important; }

.stDataFrame { border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden; }
.stDataFrame [data-testid="stDataFrameResizable"] { background: var(--bg-surface); }

.stTextInput input, .stNumberInput input, .stTextArea textarea {
    background: var(--bg-elevated) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-sm) !important;
    color: var(--text-primary) !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.84rem !important;
    padding: 0.45rem 0.75rem !important;
    transition: var(--transition);
}
.stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 2px var(--accent-glow) !important;
    outline: none !important;
}
.stTextInput label, .stNumberInput label, .stTextArea label,
.stSelectbox label, .stSlider label, .stMultiSelect label {
    color: var(--text-secondary) !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 4px;
}

.stSelectbox > div > div, .stMultiSelect > div > div {
    background: var(--bg-elevated) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-sm) !important;
    color: var(--text-primary) !important;
}
.stSelectbox > div > div:focus-within, .stMultiSelect > div > div:focus-within {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 2px var(--accent-glow) !important;
}

.stSlider [data-baseweb="slider"] [role="slider"] { background: var(--accent) !important; border-color: var(--accent) !important; }
.stSlider [data-baseweb="slider"] [data-testid="stSliderTrackFill"] { background: var(--accent) !important; }

.streamlit-expanderHeader {
    background: var(--bg-elevated) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-sm) !important;
    color: var(--text-secondary) !important;
    font-size: 0.84rem !important;
    font-weight: 500 !important;
    padding: 0.55rem 0.9rem !important;
    transition: var(--transition);
}
.streamlit-expanderHeader:hover { background: var(--bg-overlay) !important; color: var(--text-primary) !important; border-color: var(--border-focus) !important; }
.streamlit-expanderContent {
    background: var(--bg-elevated) !important;
    border: 1px solid var(--border) !important;
    border-top: none !important;
    border-radius: 0 0 var(--radius-sm) var(--radius-sm) !important;
    padding: 0.75rem 0.9rem !important;
}

.stSuccess { background: #0d2218 !important; border: 1px solid #166534 !important; border-radius: var(--radius-sm) !important; color: #86efac !important; }
.stWarning { background: #1c1505 !important; border: 1px solid #92400e !important; border-radius: var(--radius-sm) !important; color: #fcd34d !important; }
.stError   { background: #1c0505 !important; border: 1px solid #991b1b !important; border-radius: var(--radius-sm) !important; color: #fca5a5 !important; }
.stInfo    { background: #0c1628 !important; border: 1px solid #1e3a5f !important; border-radius: var(--radius-sm) !important; color: #93c5fd !important; }

.stProgress > div > div > div { background: var(--accent) !important; border-radius: 99px; }
.stProgress > div > div { background: var(--bg-overlay) !important; border-radius: 99px; height: 6px !important; }

hr { border: none; border-top: 1px solid var(--border); margin: 1rem 0; }
.stCaption, small, .caption { color: var(--text-muted) !important; font-size: 0.75rem !important; }
.stCheckbox label, .stRadio label { color: var(--text-secondary) !important; font-size: 0.84rem !important; }
.stRadio [data-testid="stMarkdownContainer"] p { color: var(--text-secondary) !important; }

[data-testid="stFileUploader"] {
    background: var(--bg-elevated);
    border: 2px dashed var(--border);
    border-radius: var(--radius-md);
    transition: var(--transition);
}
[data-testid="stFileUploader"]:hover { border-color: var(--accent); background: var(--accent-glow); }

::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: var(--bg-surface); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 99px; }
::-webkit-scrollbar-thumb:hover { background: var(--border-focus); }

[data-testid="column"] { gap: 12px; }
div[data-testid="column"] > div { gap: 8px; }

.chip {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 2px 10px; border-radius: 99px;
    font-size: 0.72rem; font-weight: 600; letter-spacing: 0.03em;
    border: 1px solid currentColor;
}
</style>
"""


def inject_theme() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def register_altair_theme() -> None:
    """Registers + enables an Altair theme matching the dark palette above.
    Call once per script run; cheap to call repeatedly (re-registers)."""
    import altair as alt

    def _theme():
        return {
            "config": {
                "background": "transparent",
                "title": {"color": COLORS["text_primary"]},
                "axis": {
                    "labelColor": COLORS["text_secondary"],
                    "titleColor": COLORS["text_secondary"],
                    "gridColor": COLORS["border"],
                    "domainColor": COLORS["border"],
                    "tickColor": COLORS["border"],
                },
                "legend": {
                    "labelColor": COLORS["text_secondary"],
                    "titleColor": COLORS["text_secondary"],
                },
                "view": {"stroke": "transparent"},
            }
        }

    alt.themes.register("expense_audit_dark", _theme)
    alt.themes.enable("expense_audit_dark")


def kpi_row(items: list[dict]) -> None:
    """Renders a row of SOA-style KPI cards.

    Each item: {"value": ..., "label": str, "bad": bool (optional)}. `bad=True`
    renders the card with the error accent (border + value colour) - use for a
    metric that should draw attention when non-zero (e.g. "Needs review").
    """
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        bad = item.get("bad", False)
        border = f"{COLORS['error']}40" if bad else COLORS["border"]
        vcol = COLORS["error"] if bad else COLORS["text_primary"]
        col.markdown(
            f'<div style="background:{COLORS["bg_elevated"]};border:1px solid {border};'
            f'border-radius:10px;padding:12px 8px;text-align:center;min-height:80px;'
            f'display:flex;flex-direction:column;align-items:center;justify-content:center">'
            f'<div style="font-size:1.4rem;font-weight:700;color:{vcol};line-height:1">'
            f'{item["value"]}</div>'
            f'<div style="font-size:.65rem;color:{COLORS["text_muted"]};text-transform:uppercase;'
            f'letter-spacing:.06em;margin-top:5px">{item["label"]}</div></div>',
            unsafe_allow_html=True,
        )


def section_label(text: str) -> None:
    """Small uppercase eyebrow label, used above a group of charts/tables."""
    st.markdown(
        f'<div style="font-size:.72rem;color:{COLORS["text_muted"]};text-transform:uppercase;'
        f'letter-spacing:.08em;margin:1rem 0 .5rem">{text}</div>',
        unsafe_allow_html=True,
    )


_CHIP_TOKENS = {
    "success": (COLORS["success_bg"], COLORS["success_border"], COLORS["success_text"]),
    "warning": (COLORS["warning_bg"], COLORS["warning_border"], COLORS["warning_text"]),
    "error": (COLORS["error_bg"], COLORS["error_border"], COLORS["error_text"]),
    "info": (COLORS["info_bg"], COLORS["info_border"], COLORS["info_text"]),
    "neutral": (COLORS["bg_elevated"], COLORS["border"], COLORS["text_secondary"]),
}


def chip_html(text: str, kind: str = "neutral") -> str:
    """Returns a styled <span> chip. kind: success|warning|error|info|neutral."""
    bg, bd, fg = _CHIP_TOKENS.get(kind, _CHIP_TOKENS["neutral"])
    return (
        f'<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 10px;'
        f'border-radius:99px;font-size:.72rem;font-weight:600;letter-spacing:.03em;'
        f'background:{bg};border:1px solid {bd};color:{fg}">{text}</span>'
    )


def step_msg(icon: str, label: str, detail: str = "") -> None:
    """A pipeline-step-in-progress line (icon + bold label + muted detail)."""
    detail_html = f'<span style="color:{COLORS["text_muted"]}">{detail}</span>' if detail else ""
    st.markdown(
        f'<div style="display:flex;align-items:baseline;gap:8px;padding:4px 0;font-size:.8rem">'
        f'<span style="font-size:.9rem">{icon}</span>'
        f'<span style="color:{COLORS["text_primary"]};font-weight:600">{label}</span>'
        f'{detail_html}</div>',
        unsafe_allow_html=True,
    )


def step_ok(label: str, detail: str = "") -> None:
    """A completed pipeline-step line (green check + label + muted detail)."""
    detail_html = f'<span style="color:{COLORS["text_muted"]}"> · {detail}</span>' if detail else ""
    st.markdown(
        f'<div style="display:flex;align-items:baseline;gap:8px;padding:3px 0;font-size:.78rem">'
        f'<span style="color:{COLORS["success"]}">✓</span>'
        f'<span style="color:{COLORS["success_text"]};font-weight:600">{label}</span>'
        f'{detail_html}</div>',
        unsafe_allow_html=True,
    )


def render_pipeline_trace(steps: list[dict]) -> None:
    """Renders a per-submission execution trace as expandable rows - one per
    pipeline node call - mirroring the SOA Layout Agent app's Log Viewer
    (icon + node + duration + attempts, expandable input/output/error).
    `steps` is the list returned by AuditStore.get_pipeline_steps(), in
    execution order.
    """
    if not steps:
        st.info("No pipeline trace recorded yet for this submission.")
        return
    for s in steps:
        ok = bool(s.get("ok"))
        icon = "✅" if ok else "❌"
        attempts = s.get("attempts", 1)
        retry_note = f", {attempts} attempt(s)" if attempts and attempts > 1 else ""
        label = f"{icon} **{s.get('node', '?')}** — {s.get('latency_ms', 0):.0f} ms{retry_note}"
        with st.expander(label, expanded=not ok):
            c1, c2 = st.columns(2)
            c1.caption(f"**Input:** {s.get('input_summary') or '—'}")
            c2.caption(f"**Output:** {s.get('output_summary') or '—'}")
            if s.get("error_message"):
                st.error(s["error_message"])
            st.caption(f"Logged at {s.get('logged_at', '—')}")


def render_pdf_viewer(pdf_bytes: bytes, *, height: int = 700) -> None:
    """Renders a PDF inline via an embedded base64 data-URI iframe - Streamlit
    has no native PDF viewer widget. Caller is still responsible for offering
    a download button alongside this; a browser's built-in PDF plugin can be
    disabled or the iframe can fail silently in unusual embedding contexts."""
    import base64

    b64 = base64.standard_b64encode(pdf_bytes).decode()
    st.markdown(
        f'<iframe src="data:application/pdf;base64,{b64}" width="100%" '
        f'height="{height}" style="border:1px solid {COLORS["border"]};border-radius:8px" '
        f'type="application/pdf"></iframe>',
        unsafe_allow_html=True,
    )
