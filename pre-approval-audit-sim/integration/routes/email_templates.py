"""GET /email-templates, POST /email-templates/render.

Simulated - this only renders subject/body text (common/email_templates.py);
no real email is sent, same scope as the Streamlit "Compose email" expander.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

import config_admin as ca
from common.auth import Role
from common.email_templates import load_email_templates
from integration.api_schemas import EmailRenderRequest, EmailRenderResponse, SaveEmailTemplateRequest
from integration.security import TokenUser, check_oe_access, require_role
from pipeline.config import load_pipeline_config

router = APIRouter(prefix="/email-templates", tags=["email-templates"])
_admin = require_role(Role.admin)


@router.get("")
def list_templates(user: TokenUser = Depends(require_role(Role.admin, Role.user))) -> list[str]:
    return [t.name for t in load_email_templates().templates]


@router.post("/render", response_model=EmailRenderResponse)
def render_template(
    payload: EmailRenderRequest, request: Request,
    user: TokenUser = Depends(require_role(Role.admin, Role.user)),
) -> EmailRenderResponse:
    from dashboard.queries import compute_expense_reports

    tmpl = load_email_templates().get(payload.template_name)
    if tmpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no such template: {payload.template_name}")

    pcfg = load_pipeline_config()
    rows = request.app.state.data.store.analytics_rows()
    reports = compute_expense_reports(
        rows,
        auto_approve_cutoff=pcfg.risk.auto_approve_cutoff,
        auto_reject_cutoff=pcfg.risk.auto_reject_cutoff,
        subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
        conf_cutoff=pcfg.extraction.confidence_cutoff,
    )
    row = next((r for r in reports if r["submission_id"] == payload.submission_id), None)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no such submission: {payload.submission_id}")
    sub = request.app.state.data.store.get_submission(payload.submission_id)
    check_oe_access(user, sub.get("oe_code") if sub else None)

    subj, body = tmpl.render(
        employee_id=row["employee_id"], submission_id=payload.submission_id,
        amount=row["total"], currency=row["currency"], reason=payload.reason,
    )
    return EmailRenderResponse(subject=subj, body=body)


# --- admin-only: raw template editing (System admin -> Email templates tab) ---
@router.get("/admin/raw")
def list_templates_raw(user: TokenUser = Depends(_admin)) -> list[dict]:
    return ca.load_email_templates_raw()["templates"]


@router.put("/admin/raw/{name}")
def save_template(
    name: str, payload: SaveEmailTemplateRequest, user: TokenUser = Depends(_admin),
) -> dict:
    try:
        ca.save_email_template_body(name, payload.subject, payload.body)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"name": name, "ok": True}
