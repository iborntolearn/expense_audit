"""User analytics profile page - per-employee behavioural view (AppZen-style)."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import ui_kit
from app_common import get_data_layer
from dashboard.queries import list_employees, user_analytics
from pipeline.config import load_pipeline_config

# rough OE -> map centroid for the geography view
_OE_GEO = {
    "DE": (51.16, 10.45), "US": (39.5, -98.35), "GB": (54.0, -2.0),
    "FR": (46.6, 2.2), "IN": (22.0, 79.0),
}
_PERIODS = {"All time": None, "Last 30 days": 30, "Last 90 days": 90}


@st.cache_data(ttl=30)
def _rows():
    return get_data_layer().store.analytics_rows()


rows = _rows()
employees = list_employees(rows)
if not employees:
    st.warning("No data yet. Run `python scripts/run_batch.py` to populate the store.")
    st.stop()

c = st.columns([1, 2, 6])
period_label = c[0].selectbox("Period", list(_PERIODS.keys()))
employee = c[1].selectbox("Employee", employees)

pcfg = load_pipeline_config()
ua = user_analytics(
    rows, employee,
    subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
    conf_cutoff=pcfg.extraction.confidence_cutoff,
    auto_reject_cutoff=pcfg.risk.auto_reject_cutoff,
    period_days=_PERIODS[period_label],
)
k = ua["kpis"]

# --- KPI row + behavioural trends ---
main, trends_col = st.columns([3, 1])
with main:
    m = st.columns(4)
    m[0].metric("T&E spend", f"{k['te_spend']:,.0f}")
    m[1].metric("Rejected high-risk spend", f"{k['rejected_high_risk_spend']:,.0f}")
    m[2].metric("ABI score", k["abi_score"], help="Behavioural integrity, 0-100 (higher is cleaner)")
    m[3].metric("Auto-approved / total", f"{k['auto_approved']} / {k['total_reports']}")
with trends_col:
    st.markdown("**Behavioural trends**")
    if ua["behavioral_trends"]:
        st.dataframe(pd.DataFrame(ua["behavioral_trends"]), hide_index=True, width="stretch")
    else:
        st.caption("No behavioural flags.")

st.divider()
c1, c2 = st.columns(2)

# --- spend by expense type (bar spend + line #lines) ---
with c1:
    st.markdown("**Spend by expense type**")
    sdt = ua["spend_by_type"]
    if sdt:
        df = pd.DataFrame(
            [{"category": kk, "spend": v["spend"], "lines": v["lines"]} for kk, v in sdt.items()]
        )
        base = alt.Chart(df).encode(x=alt.X("category:N", title="Expense type", sort="-y"))
        bars = base.mark_bar(color=ui_kit.COLORS["accent"]).encode(
            y=alt.Y("spend:Q", title="Spend amount"))
        line = base.mark_line(point=True, color=ui_kit.COLORS["purple"]).encode(
            y=alt.Y("lines:Q", title="No. of expense lines"))
        st.altair_chart(alt.layer(bars, line).resolve_scale(y="independent"))
    else:
        st.caption("No spend.")

# --- ABI score company comparison ---
with c2:
    st.markdown("**ABI score - company comparison**")
    abi_df = pd.DataFrame({"abi": ua["company_abi"]})
    hist = alt.Chart(abi_df).mark_bar(color=ui_kit.COLORS["accent"]).encode(
        x=alt.X("abi:Q", bin=alt.Bin(step=10), title="ABI score"),
        y=alt.Y("count():Q", title="No. of employees"),
    )
    rule = alt.Chart(pd.DataFrame({"abi": [ua["my_abi"]]})).mark_rule(
        color=ui_kit.COLORS["error"], size=2).encode(x="abi:Q")
    st.altair_chart(hist + rule)
    st.caption(f"Red line = {employee}'s ABI ({ua['my_abi']}).")

st.divider()
c3, c4 = st.columns(2)

# --- high risk spend by category ---
with c3:
    st.markdown("**High-risk spend**")
    hr = ua["high_risk_spend_by_type"]
    if hr:
        hdf = pd.DataFrame([{"category": kk, "spend": v} for kk, v in hr.items()])
        st.altair_chart(
            alt.Chart(hdf).mark_bar(color=ui_kit.COLORS["warning"]).encode(
                x=alt.X("category:N", title="Expense type", sort="-y"),
                y=alt.Y("spend:Q", title="Spend amount"),
            )
        )
    else:
        st.caption("No high-risk spend.")

# --- spend by geography ---
with c4:
    st.markdown("**Spend by geography**")
    geo = ua["spend_by_geo"]
    pts = [{"oe": oe, "lat": _OE_GEO[oe][0], "lon": _OE_GEO[oe][1], "spend": sp}
           for oe, sp in geo.items() if oe in _OE_GEO]
    if pts:
        gdf = pd.DataFrame(pts)
        mx = gdf["spend"].max() or 1
        gdf["size"] = gdf["spend"] / mx * 400000  # metres, for visibility
        st.map(gdf, latitude="lat", longitude="lon", size="size")
        st.dataframe(gdf[["oe", "spend"]], hide_index=True, width="stretch")
    else:
        st.caption("No geography data.")
