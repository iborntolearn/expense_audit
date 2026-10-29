"""Reports & exports page - downloadable audit outputs + observability."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import ui_kit
from app_common import get_data_layer
from config.settings import get_settings
from dashboard.queries import compute_compliance_packs, compute_expense_reports
from pipeline.config import load_pipeline_config


@st.cache_data(ttl=30)
def _report_rows():
    pcfg = load_pipeline_config()
    return compute_expense_reports(
        get_data_layer().store.analytics_rows(),
        auto_approve_cutoff=pcfg.risk.auto_approve_cutoff,
        auto_reject_cutoff=pcfg.risk.auto_reject_cutoff,
        subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
        conf_cutoff=pcfg.extraction.confidence_cutoff,
    )


decisions_tab, accuracy_tab, observability_tab, compliance_tab = st.tabs(
    ["Decision extract", "Accuracy & latency report", "Observability", "Compliance packs"]
)

# --------------------------------------------------------------------------- #
# Decision extract
# --------------------------------------------------------------------------- #
with decisions_tab:
    reports = _report_rows()
    if not reports:
        st.warning("No data yet. Run a batch first (System admin, or `python scripts/run_batch.py`).")
    else:
        df = pd.DataFrame(reports)
        st.caption(f"{len(df)} audited reports")
        st.download_button(
            "Download decisions (CSV)", df.to_csv(index=False).encode("utf-8"),
            file_name="expense_audit_decisions.csv", mime="text/csv", icon=":material/download:",
        )
        st.dataframe(df, hide_index=True, width="stretch")

# --------------------------------------------------------------------------- #
# Accuracy & latency report
# --------------------------------------------------------------------------- #
with accuracy_tab:
    synth = get_settings().resolve("./.data/synthetic")
    files = sorted(synth.glob("*/report.json"), key=lambda p: p.stat().st_mtime, reverse=True) \
        if synth.exists() else []
    if not files:
        st.caption("No accuracy/latency report yet. Generate one from System admin, or run "
                   "`python scripts/report.py`.")
    else:
        latest = files[0]
        rep = json.loads(latest.read_text(encoding="utf-8"))
        st.caption(f"Source: {latest}")
        c = st.columns(2)
        c[0].download_button("Download report (JSON)", latest.read_bytes(),
                             file_name="report.json", mime="application/json")
        md = latest.with_suffix(".md")
        if md.exists():
            c[1].download_button("Download report (Markdown)", md.read_bytes(),
                                 file_name="report.md", mime="text/markdown")
        st.dataframe(pd.DataFrame(rep["metrics"]), hide_index=True, width="stretch")

# --------------------------------------------------------------------------- #
# Observability
# --------------------------------------------------------------------------- #
with observability_tab:
    st.caption(
        "How end-to-end processing actually ran, across every submission: per-node "
        "timing, retry attempts, and error rate. Drill into a single submission's "
        "trace from Audit → Expense reports → 🪵 Pipeline log."
    )

    logs = get_data_layer().store.get_recent_pipeline_logs(limit=5000)
    if not logs:
        st.info("No pipeline runs logged yet. Run a batch first.")
    else:
        log_df = pd.DataFrame(logs)
        total_steps = len(log_df)
        n_submissions = log_df["submission_id"].nunique()
        n_errors = int((~log_df["ok"].astype(bool)).sum())
        error_rate = n_errors / total_steps if total_steps else 0.0
        avg_latency = log_df["latency_ms"].astype(float).mean()

        ui_kit.kpi_row([
            {"value": total_steps, "label": "Steps logged"},
            {"value": n_submissions, "label": "Submissions traced"},
            {"value": f"{error_rate * 100:.1f}%", "label": "Node error rate", "bad": n_errors > 0},
            {"value": f"{avg_latency:.0f} ms", "label": "Avg node latency"},
        ])

        st.markdown("<br>", unsafe_allow_html=True)
        oc1, oc2 = st.columns(2)
        with oc1:
            st.markdown("**Avg latency by node**")
            by_node_latency = log_df.groupby("node")["latency_ms"].mean().round(1)
            st.bar_chart(by_node_latency)
        with oc2:
            st.markdown("**Outcomes by node**")
            outcome_counts = (
                log_df.assign(outcome=log_df["ok"].astype(bool).map({True: "ok", False: "error"}))
                .groupby(["node", "outcome"]).size().unstack(fill_value=0)
            )
            st.bar_chart(outcome_counts)

        retried = log_df[log_df["attempts"].astype(int) > 1]
        if len(retried):
            st.caption(f"{len(retried)} step(s) needed a retry before succeeding or failing.")

        with st.expander(f"Raw pipeline log ({total_steps} rows)"):
            st.dataframe(log_df, hide_index=True, width="stretch")

        st.download_button(
            "Download pipeline log (CSV)", log_df.to_csv(index=False).encode("utf-8"),
            file_name=f"pipeline_log_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv",
            mime="text/csv", icon=":material/download:",
        )

# --------------------------------------------------------------------------- #
# Compliance packs - canned exports for external auditors (BR-TE-AU-10).
# Built entirely from data already captured elsewhere in this app - not a
# real SOX/ICFR/FCPA certification, but a starting evidence pack an auditor
# can pull without database access.
# --------------------------------------------------------------------------- #
with compliance_tab:
    rows = get_data_layer().store.analytics_rows()
    cases = get_data_layer().store.list_case_statuses()
    packs = compute_compliance_packs(rows, cases)
    sox_icfr = packs["sox_icfr"]
    fcpa = packs["fcpa_sanctions"]
    recoverable = packs["recoverable_funds"]

    st.markdown("### SOX / ICFR summary")
    st.caption(
        "Automation mix, policy-violation counts by rule, and the full decision trail - a "
        "starting evidence pack for SOX/ICFR walkthroughs, not a certified report."
    )
    if not sox_icfr["total_submissions"]:
        st.info("No submissions audited yet.")
    else:
        ui_kit.kpi_row([
            {"value": sox_icfr["total_submissions"], "label": "Total submissions audited"},
            {"value": f"{sox_icfr['auto_approved_pct'] * 100:.0f}%", "label": "Auto-approved"},
            {"value": f"{sox_icfr['auto_rejected_pct'] * 100:.0f}%", "label": "Auto-rejected",
             "bad": sox_icfr["auto_rejected_pct"] > 0},
            {"value": f"{sox_icfr['human_review_pct'] * 100:.0f}%", "label": "Routed to human review"},
        ])

        st.markdown("**Policy violations by rule**")
        if sox_icfr["violations_by_rule"]:
            df_rules = pd.DataFrame(sox_icfr["violations_by_rule"])
            st.dataframe(df_rules, hide_index=True, width="stretch")
            st.download_button(
                "Download SOX/ICFR evidence pack (CSV)", df_rules.to_csv(index=False).encode("utf-8"),
                file_name="sox_icfr_violations_by_rule.csv", mime="text/csv",
                icon=":material/download:", key="dl_sox",
            )
        else:
            st.caption("No policy violations recorded.")

    st.divider()
    st.markdown("### FCPA / anti-bribery & sanctions summary")
    st.caption(
        "Every submission with a cumulative-compliance flag (BR-TE-AU-04, e.g. an annual "
        "gift/entertainment aggregate breach) or a merchant sanctions/PEP watchlist hit "
        "(BR-TE-AU-03, simulated watchlist)."
    )
    if fcpa["flagged"]:
        df_fcpa = pd.DataFrame([
            {**f, "compliance_flags": "; ".join(f["compliance_flags"]),
             "merchant_flags": "; ".join(f["merchant_flags"])}
            for f in fcpa["flagged"]
        ])
        st.dataframe(df_fcpa, hide_index=True, width="stretch")
        st.download_button(
            "Download FCPA/sanctions evidence pack (CSV)", df_fcpa.to_csv(index=False).encode("utf-8"),
            file_name="fcpa_sanctions_evidence.csv", mime="text/csv",
            icon=":material/download:", key="dl_fcpa",
        )
    else:
        st.info("No FCPA/anti-bribery or sanctions/PEP signals recorded yet.")

    st.divider()
    st.markdown("### Recoverable funds (case management - BR-TE-AU-13)")
    st.caption("Cases tracked through the case-management workflow (Expense reports -> "
               "Case management), with amounts recovered through audit claw-back.")
    if not recoverable["cases_tracked"]:
        st.info("No cases have a tracked status yet.")
    else:
        ui_kit.kpi_row([
            {"value": recoverable["cases_tracked"], "label": "Cases tracked"},
            {"value": recoverable["claw_back_pending"], "label": "Claw-back pending",
             "bad": recoverable["claw_back_pending"] > 0},
            {"value": recoverable["resolved"], "label": "Resolved"},
            {"value": f"{recoverable['total_recovered']:,.2f}",
             "label": "Total recovered (all currencies)"},
        ])
        df_cases = pd.DataFrame(recoverable["cases"])
        st.dataframe(df_cases, hide_index=True, width="stretch")
        st.download_button(
            "Download case-status report (CSV)", df_cases.to_csv(index=False).encode("utf-8"),
            file_name="case_status_recoverable_funds.csv", mime="text/csv",
            icon=":material/download:", key="dl_cases",
        )
