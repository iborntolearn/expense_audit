"""Business dashboard (Streamlit).

Run from the repo root:  streamlit run dashboard/app.py
Read-only view over the audit store for business users: automation, spend,
exceptions, and a secondary ops/model-health tab. Populate it by running a batch
first (scripts/run_batch.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # bundled with streamlit
import streamlit as st  # noqa: E402

from config.settings import get_settings  # noqa: E402
from dashboard.queries import compute_dashboard  # noqa: E402
from data.factory import build_data_layer  # noqa: E402
from pipeline.config import load_pipeline_config  # noqa: E402


@st.cache_resource
def _data_layer():
    data = build_data_layer(get_settings())
    data.migrate()
    return data


def _load():
    data = _data_layer()
    pcfg = load_pipeline_config()
    rows = data.store.analytics_rows()
    dash = compute_dashboard(
        rows,
        subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
        conf_cutoff=pcfg.extraction.confidence_cutoff,
    )
    return data, dash


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def business_tab(data, dash) -> None:
    k = dash.kpis
    if k["total_submissions"] == 0:
        st.warning("No data yet. Run `python scripts/run_batch.py` to populate the store.")
        return

    r1 = st.columns(4)
    r1[0].metric("Submissions", k["total_submissions"])
    r1[1].metric("Automation rate", _pct(k["automation_rate"]))
    r1[2].metric("Straight-through", _pct(k["straight_through_rate"]))
    r1[3].metric("Exception rate", _pct(k["exception_rate"]))
    r2 = st.columns(4)
    r2[0].metric("Total spend", f"{k['total_spend']:,.0f}")
    r2[1].metric("Flagged spend", f"{k['flagged_spend']:,.0f}")
    r2[2].metric("Avg risk score", k["avg_risk_score"])
    r2[3].metric("Review backlog", k["review_backlog"])

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Routing mix")
        st.bar_chart(pd.Series(dash.routing, name="count"))
        st.subheader("Exception reasons")
        if dash.exception_reasons:
            st.bar_chart(pd.Series(dash.exception_reasons, name="count"))
        else:
            st.caption("No exceptions.")
    with c2:
        st.subheader("Risk score distribution")
        st.bar_chart(pd.Series(dash.risk_histogram, name="count"))
        st.subheader("Top violated rules")
        if dash.top_rules:
            st.dataframe(pd.DataFrame(dash.top_rules), use_container_width=True, hide_index=True)
        else:
            st.caption("No policy violations.")

    st.divider()
    st.subheader("Volume & automation trend")
    if dash.trend:
        tdf = pd.DataFrame(dash.trend).set_index("date")
        st.line_chart(tdf[["submissions"]])
        st.line_chart(tdf[["automation_rate"]])

    st.divider()
    s1, s2, s3 = st.columns(3)
    s1.subheader("Spend by category")
    s1.bar_chart(pd.Series(dash.spend_by_category, name="spend"))
    s2.subheader("Spend by OE")
    s2.bar_chart(pd.Series(dash.spend_by_oe, name="spend"))
    s3.subheader("Spend by currency")
    s3.bar_chart(pd.Series(dash.spend_by_currency, name="spend"))

    st.divider()
    st.subheader("Review queue (open)")
    q = data.store.list_review_queue()
    st.dataframe(pd.DataFrame(q) if q else pd.DataFrame(columns=["submission_id"]),
                 use_container_width=True, hide_index=True)

    st.subheader("Recent decisions")
    st.dataframe(pd.DataFrame(dash.recent_decisions), use_container_width=True, hide_index=True)


def ops_tab(dash) -> None:
    st.subheader("Reviewer outcomes")
    if dash.reviewer_outcomes:
        st.bar_chart(pd.Series(dash.reviewer_outcomes, name="count"))
    else:
        st.caption("No reviewer actions yet.")

    st.subheader("Model & latency report")
    settings = get_settings()
    # newest report.json under .data/synthetic/*/
    reports = sorted(
        settings.resolve("./.data/synthetic").glob("*/report.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ) if settings.resolve("./.data/synthetic").exists() else []
    if not reports:
        st.caption("No report yet. Run `python scripts/report.py`.")
        return
    rep = json.loads(reports[0].read_text(encoding="utf-8"))
    st.caption(f"Source: {reports[0]}")
    st.dataframe(pd.DataFrame(rep["metrics"]), use_container_width=True, hide_index=True)
    per_node = rep.get("latency", {}).get("per_node", {})
    if per_node:
        st.subheader("Per-node latency (p95, s)")
        st.bar_chart(pd.Series({n: v["p95_s"] for n, v in per_node.items()}, name="p95_s"))


def main() -> None:
    st.set_page_config(page_title="Expense Audit - Business Dashboard", layout="wide")
    st.title("Pre-Approval Expense Audit - Business Dashboard")
    st.caption("Simulation data - synthetic submissions only.")
    if st.button("Refresh"):
        st.cache_resource.clear()
        st.rerun()

    data, dash = _load()
    biz, ops = st.tabs(["Business", "Ops / Model health"])
    with biz:
        business_tab(data, dash)
    with ops:
        ops_tab(dash)


main()
