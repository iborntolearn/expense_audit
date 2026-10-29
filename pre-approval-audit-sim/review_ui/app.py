"""Streamlit reviewer dashboard (Milestone 9).

Run from the repo root:  streamlit run review_ui/app.py
Shows the queue of submissions the pipeline routed to human review, with the
extracted data, verification signals, policy result, risk explanation, and
receipt evidence together. An approve/reject resumes the checkpointed graph.

Note: reviewer identity is a plain sidebar field here - real SSO/RBAC is the
seam this plugs into (baseline-only in simulation, Solution Design 10).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from review_ui.service import build_review_service  # noqa: E402


@st.cache_resource
def get_service():
    return build_review_service()


def _fmt_money(v, cur) -> str:
    return f"{v:.2f} {cur}" if v is not None else "-"


def main() -> None:
    st.set_page_config(page_title="Expense Audit - Review Queue", layout="wide")
    svc = get_service()

    st.sidebar.header("Reviewer")
    reviewer_id = st.sidebar.text_input("Reviewer ID", value="REV-1")
    st.sidebar.caption("Simulation mode - synthetic data only.")
    if st.sidebar.button("Refresh queue"):
        st.rerun()

    queue = svc.queue()
    st.title("Pre-Approval Expense Audit - Review Queue")
    st.caption(f"{len(queue)} submission(s) awaiting review")

    if not queue:
        st.success("Queue is empty - no submissions awaiting review.")
        return

    labels = {
        f"{q['submission_id']}  |  risk {q['risk_score']:.2f}  |  {q['oe_code']}  |  {q['employee_id']}": q[
            "submission_id"
        ]
        for q in queue
    }
    choice = st.selectbox("Select a case", list(labels.keys()))
    sid = labels[choice]
    detail = svc.detail(sid)
    if not detail:
        st.error("Case not found.")
        return

    sub = detail["submission"]
    risk = detail["risk"]
    ver = detail["verification"]

    top = st.columns(4)
    top[0].metric("Risk score", f"{risk.get('risk_score', 0):.2f}")
    top[1].metric("OE", sub["oe_code"])
    top[2].metric("Employee", sub["employee_id"])
    top[3].metric("Currency", sub["currency"])

    st.subheader("Why this was flagged")
    st.info(risk.get("explanation") or "(no explanation)")

    left, right = st.columns([3, 2])

    with left:
        st.subheader("Extracted line items")
        st.dataframe(
            [
                {
                    "line": r["line_item_id"].split(":")[-1],
                    "vendor": r["vendor"],
                    "date": r["txn_date"],
                    "amount": _fmt_money(r["amount"], sub["currency"]),
                    "confidence": r["confidence"],
                }
                for r in detail["extracted_lines"]
            ],
            use_container_width=True,
        )

        st.subheader("Verification signals")
        st.write(
            {
                "authenticity_flags": ver.get("authenticity_flags", []),
                "duplicate_of": ver.get("duplicate_match_ids", []),
                "subtotal_variance_pct": ver.get("subtotal_variance_pct"),
                "merchant_validation": ver.get("merchant_validation"),
            }
        )

        st.subheader("Policy evaluation")
        st.dataframe(
            [
                {"rule_id": p["rule_id"], "passed": bool(p["passed"]),
                 "rule_version": p["rule_version"]}
                for p in detail["policy"]
            ],
            use_container_width=True,
        )

    with right:
        st.subheader("Receipt evidence")
        for ref in detail["receipts"]:
            url = ref["receipt_url"]
            st.caption(f"{ref['line_id']} - {url}")
            try:
                data = svc.receipt_bytes(url)
                if url.endswith(".pdf"):
                    st.download_button("Download PDF", data, file_name=f"{ref['line_id']}.pdf")
                else:
                    st.image(data, use_container_width=True)
            except Exception as exc:  # evidence retrieval is best-effort in the UI
                st.warning(f"could not load receipt: {exc}")

    st.divider()
    st.subheader("Decision")
    notes = st.text_area("Reviewer notes", "")
    c1, c2 = st.columns(2)
    if c1.button("Approve", type="primary", use_container_width=True):
        svc.submit_decision(sid, reviewer_id=reviewer_id, approved=True, notes=notes)
        st.success(f"{sid} approved.")
        st.rerun()
    if c2.button("Reject", use_container_width=True):
        svc.submit_decision(sid, reviewer_id=reviewer_id, approved=False, notes=notes)
        st.error(f"{sid} rejected.")
        st.rerun()


main()
