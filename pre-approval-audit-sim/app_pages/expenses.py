"""Expense reports page - risk-based audit list (AppZen-style, SOA-styled).

Summary tiles + a filterable, colour-coded table of every audited submission -
this is also the review queue (previously a separate page): a submission
awaiting a human decision has status SUBMITTED, and the "Pending review only"
filter below narrows to exactly that set (same rows `ReviewService.queue()`
returns). Selecting a row opens its detail (evidence + risk explanation, in
sub-tabs); if still awaiting review, the reviewer can approve/reject inline
(resumes the graph).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import auth_ui
import ui_kit
from app_common import get_data_layer, get_review_service
from dashboard.queries import compute_expense_reports, consolidated_insights
from pipeline.config import load_pipeline_config

# Risk/status badge colours reuse the same tokens as the injected theme's
# st.success/st.warning/st.error alert boxes (ui_kit.COLORS), so table chips
# read as the same design language as native Streamlit alerts.
_RISK_BG = {"LOW": ui_kit.COLORS["success_bg"], "PENDING": ui_kit.COLORS["warning_bg"],
            "HIGH": ui_kit.COLORS["error_bg"]}
_RISK_FG = {"LOW": ui_kit.COLORS["success_text"], "PENDING": ui_kit.COLORS["warning_text"],
            "HIGH": ui_kit.COLORS["error_text"]}
_STATUS_FG = {"APPROVED": ui_kit.COLORS["success_text"], "REJECTED": ui_kit.COLORS["error_text"],
              "SUBMITTED": ui_kit.COLORS["accent_bright"]}


@st.cache_data(ttl=30)
def _reports():
    pcfg = load_pipeline_config()
    return compute_expense_reports(
        get_data_layer().store.analytics_rows(),
        auto_approve_cutoff=pcfg.risk.auto_approve_cutoff,
        auto_reject_cutoff=pcfg.risk.auto_reject_cutoff,
        subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
        conf_cutoff=pcfg.extraction.confidence_cutoff,
    )


@st.cache_data(ttl=30)
def _analytics_rows():
    return get_data_layer().store.analytics_rows()


st.sidebar.header("Reviewer")
reviewer_id = st.sidebar.text_input("Reviewer ID", value="REV-1")
st.sidebar.caption("SSO/RBAC is the integration seam this plugs into (baseline-only in this environment).")

reports = _reports()
if not reports:
    st.warning("No expense reports yet. Run `python scripts/run_batch.py` to populate the store.")
    st.stop()

total = len(reports)
viol = sum(1 for r in reports if r["violations"] > 0)
manual = sum(1 for r in reports if r["routing_decision"] == "human_review")

ui_kit.kpi_row([
    {"value": total, "label": "Total expense reports"},
    {"value": f"{viol / total * 100:.0f}%", "label": "Policy violations", "bad": viol > 0},
    {"value": f"{manual / total * 100:.0f}%", "label": "Manual audit", "bad": manual > 0},
])

# --- filters ---
ui_kit.section_label("Filters")
pending_only = st.checkbox(
    "Pending review only", value=False,
    help="Submissions routed to human_review with no reviewer decision yet - "
         "the same set the review queue used to show.",
)
with st.container(border=True):
    f = st.columns([1.4, 1.4, 1.2, 1.2, 0.6])
    q_user = f[0].text_input("User", "", placeholder="employee id")
    q_report = f[1].text_input("Report", "", placeholder="submission id")
    q_status = f[2].multiselect("Status", ["APPROVED", "REJECTED", "SUBMITTED"])
    q_risk = f[3].multiselect("Risk", ["LOW", "PENDING", "HIGH"])
    f[4].markdown("&nbsp;")
    go = f[4].button("Go", type="primary", width="stretch")

rows = [
    r for r in reports
    if (not pending_only or r["status"] == "SUBMITTED")
    and (not q_user or q_user.lower() in r["employee_id"].lower())
    and (not q_report or q_report.lower() in r["submission_id"].lower())
    and (not q_status or r["status"] in q_status)
    and (not q_risk or r["risk_band"] in q_risk)
]

df = pd.DataFrame([
    {
        "Report": r["submission_id"],
        "User": r["employee_id"],
        "Submission date": r["submitted_at"],
        "Total": f"{r['total']:.2f} {r['currency']}",
        "Risk": r["risk_band"],
        "Risk reason": r["risk_reason"],
        "Approver": r["approver"],
        "Violations": r["violations"],
        "Flags": r["flags"],
        "Insights": r["insight_count"],
        "Status": r["status"],
    }
    for r in rows
])

st.caption(f"Showing {len(rows)} of {total} reports")


def _style(col: pd.Series) -> list[str]:
    if col.name == "Risk":
        return [f"background-color:{_RISK_BG.get(v, '')};color:{_RISK_FG.get(v, '')};font-weight:600"
                for v in col]
    if col.name == "Status":
        return [f"color:{_STATUS_FG.get(v, '')};font-weight:600" for v in col]
    return ["" for _ in col]


event = st.dataframe(
    df.style.apply(_style, axis=0),
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    key="reports_table",
)

sel = event.selection.rows
if not sel:
    st.info("Select a report to view details.")
    st.stop()

sid = rows[sel[0]]["submission_id"]
svc = get_review_service()
detail = svc.detail(sid)
sub = detail["submission"]
risk = detail["risk"]
ver = detail["verification"]

st.divider()
ui_kit.section_label("Report detail")
st.subheader(sid)
top = st.columns(4)
top[0].metric("Risk score", f"{risk.get('risk_score', 0):.2f}")
top[1].metric("OE", sub["oe_code"])
top[2].metric("Employee", sub["employee_id"])
top[3].metric("Currency", sub["currency"])
st.info(risk.get("explanation") or "(no explanation)")

# --- Consolidated insight summary (BR-TE-AU-20): every distinct insight  ---
# --- type that fired on this ONE submission, merged into a single view - ---
# --- so a case tripping several independent checks at once (e.g. a       ---
# --- duplicate match AND a merchant watchlist hit) is reviewed and       ---
# --- resolved as one case, not pieced together across separate tabs.     ---
_pcfg = load_pipeline_config()
_insights = consolidated_insights(
    sid, _analytics_rows(),
    subtotal_tol=_pcfg.verification.subtotal_tolerance_pct,
    conf_cutoff=_pcfg.extraction.confidence_cutoff,
)
ui_kit.section_label(f"Consolidated insight summary ({len(_insights)})")
if not _insights:
    st.caption("No insight types fired on this submission.")
else:
    st.dataframe(
        [{"Insight type": i["label"], "Detail": i["detail"]} for i in _insights],
        hide_index=True, width="stretch",
    )
    if len(_insights) > 1:
        st.caption(
            f"{len(_insights)} distinct insight types fired on this one case - "
            "resolved together with a single approve/reject/case-status action below."
        )

lines_tab, verify_tab, policy_tab, evidence_tab, trace_tab = st.tabs(
    ["📄 Extracted lines", "🔍 Verification", "📐 Policy", "🧾 Evidence", "🪵 Pipeline log"]
)
with lines_tab:
    st.dataframe(
        [{"line": r["line_item_id"].split(":")[-1], "vendor": r["vendor"], "date": r["txn_date"],
          "amount": r["amount"], "confidence": r["confidence"]} for r in detail["extracted_lines"]],
        hide_index=True, width="stretch",
    )
with verify_tab:
    st.write({
        "authenticity_flags": ver.get("authenticity_flags", []),
        "duplicate_of": ver.get("duplicate_match_ids", []),
        "subtotal_variance_pct": ver.get("subtotal_variance_pct"),
        "subtotal_entered_total": ver.get("subtotal_entered_total"),
        "subtotal_receipt_total (amount + tax)": ver.get("subtotal_receipt_total"),
        "velocity_flags": ver.get("velocity_flags", []),
        "split_transaction_flags": ver.get("split_transaction_flags", []),
        "merchant_validation": ver.get("merchant_validation"),
        "merchant_flags (sanctions/PEP watchlist)": ver.get("merchant_flags", []),
        "compliance_flags (cumulative/FCPA)": ver.get("compliance_flags", []),
    })
    if ver.get("subtotal_variance_pct") is not None and ver.get("subtotal_entered_total") is not None:
        st.caption(
            f"Calculation: \\|entered − receipt\\| / receipt × 100 = "
            f"\\|{ver['subtotal_entered_total']} − {ver['subtotal_receipt_total']}\\| / "
            f"{ver['subtotal_receipt_total']} × 100 = **{ver['subtotal_variance_pct']}%** "
            f"(receipt total = extracted amount + extracted tax, summed across lines)"
        )
with policy_tab:
    st.dataframe(
        [{"rule_id": p["rule_id"], "passed": bool(p["passed"])} for p in detail["policy"]],
        hide_index=True, width="stretch",
    )
with evidence_tab:
    for ref in detail["receipts"]:
        url = ref["receipt_url"]
        st.caption(ref["line_id"])
        try:
            data = svc.receipt_bytes(url)
            if url.endswith(".pdf"):
                st.download_button(f"Download {ref['line_id']} (PDF)", data,
                                   file_name=f"{ref['line_id']}.pdf", mime="application/pdf",
                                   key=f"dl_{sid}_{ref['line_id']}")
                ui_kit.render_pdf_viewer(data)
            else:
                st.image(data, width="stretch")
        except Exception as exc:
            st.warning(f"could not load receipt: {exc}")
with trace_tab:
    st.caption("How this submission was actually processed, node by node.")
    steps = get_data_layer().store.get_pipeline_steps(sid)
    ui_kit.render_pipeline_trace(steps)

# --- Case management (BR-TE-AU-13): status workflow, claw-back/recoverable- ---
# --- funds tracking, and an email-template library for auditor<->traveller ---
# --- communications. Read-only for the auditor role, same as approve/reject.--
st.divider()
ui_kit.section_label("Case management")
_case = get_data_layer().store.get_case_status(sid) or {}
_case_statuses = ["open", "in_review", "awaiting_traveller", "resolved", "claw_back_pending"]
_current_status = _case.get("status", "open")
_current_recovered = _case.get("recovered_amount")

if auth_ui.is_auditor():
    st.caption(
        f"Case status: **{_current_status}**"
        + (f" · Recovered: {_current_recovered:.2f} {sub['currency']}" if _current_recovered else "")
    )
else:
    cc1, cc2, cc3 = st.columns([2, 2, 1])
    _status_idx = _case_statuses.index(_current_status) if _current_status in _case_statuses else 0
    new_status = cc1.selectbox("Case status", _case_statuses, index=_status_idx, key=f"case_status_{sid}")
    new_recovered = cc2.number_input(
        "Recovered amount (claw-back)", min_value=0.0, value=float(_current_recovered or 0.0),
        step=1.0, key=f"case_recovered_{sid}",
    )
    if cc3.button("Update case", width="stretch", key=f"case_update_{sid}"):
        get_data_layer().store.set_case_status(
            sid, status=new_status, recovered_amount=new_recovered or None, updated_by=reviewer_id,
        )
        st.success("Case updated.")
        st.rerun()

    with st.expander("✉️ Compose email to traveller (simulated - not actually sent)"):
        from common.email_templates import load_email_templates

        _lib = load_email_templates()
        _tmpl_names = [t.name for t in _lib.templates]
        if not _tmpl_names:
            st.caption("No email templates configured - add some in System admin.")
        else:
            _picked = st.selectbox("Template", _tmpl_names, key=f"email_tmpl_{sid}")
            _reason_txt = st.text_input(
                "Reason (fills {reason})", value=risk.get("explanation") or "",
                key=f"email_reason_{sid}",
            )
            _tmpl = _lib.get(_picked)
            _subj, _body = _tmpl.render(
                employee_id=sub["employee_id"], submission_id=sid,
                amount=rows[sel[0]]["total"], currency=sub["currency"], reason=_reason_txt,
            )
            # No `key=` here on purpose: these are pure, disabled mirrors of
            # _tmpl.render() output (never edited by the user), and a fixed
            # key would make Streamlit keep serving the stale session_state
            # value from before the template/reason changed instead of the
            # freshly computed one - the actual bug this replaced.
            st.text_input("Subject", value=_subj, disabled=True)
            st.text_area("Body", value=_body, height=220, disabled=True)
            st.caption("Simulated - no real email is sent. Copy this into your mail client.")

# inline decision only for cases still open in the review queue - never for
# the read-only auditor role (BR-TE-AU-10), even if the case is pending.
_pending_ids = {q["submission_id"] for q in svc.queue()}
if auth_ui.is_auditor():
    st.divider()
    st.caption("Read-only auditor view - approve/reject is not available for this role.")
elif sid in _pending_ids:
    st.divider()
    notes = st.text_input("Reviewer notes", "")
    d1, d2 = st.columns(2)
    if d1.button("Approve", type="primary", icon=":material/check:", width="stretch"):
        svc.submit_decision(sid, reviewer_id=reviewer_id, approved=True, notes=notes)
        _reports.clear()
        st.success(f"{sid} approved.")
        st.rerun()
    if d2.button("Reject", icon=":material/close:", width="stretch"):
        svc.submit_decision(sid, reviewer_id=reviewer_id, approved=False, notes=notes)
        _reports.clear()
        st.error(f"{sid} rejected.")
        st.rerun()
else:
    st.caption(f"Status: {detail['risk'].get('routing_decision')} - no action required.")
