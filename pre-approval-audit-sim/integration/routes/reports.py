"""GET /reports, GET /reports/{sid}, POST /reports/{sid}/decision,
GET /reports/{sid}/receipt/{line_id}.

Wraps review_ui.service.ReviewService and dashboard.queries.compute_expense_reports
- the exact same calls app_pages/expenses.py makes - so this is a REST mirror
of that page, not new business logic.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from common.auth import Role
from integration.api_schemas import DecisionRequest
from integration.security import (
    TokenUser,
    check_oe_access,
    get_current_user,
    require_role,
    resolve_oe_scope,
)
from pipeline.config import load_pipeline_config
from review_ui.service import ReviewService

router = APIRouter(prefix="/reports", tags=["reports"])


def _review_service(request: Request) -> ReviewService:
    svc = request.app.state.review_service
    if svc is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "review routes require config/pipeline.yaml engine: langgraph",
        )
    return svc


def _submission_oe(request: Request, sid: str) -> Optional[str]:
    """oe_code for a single submission (for the sid-scoped routes below,
    which don't go through compute_expense_reports/analytics_rows)."""
    sub = request.app.state.data.store.get_submission(sid)
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no such submission: {sid}")
    return sub.get("oe_code")


@router.get("")
def list_reports(
    request: Request,
    user: TokenUser = Depends(get_current_user),
    employee_id: Optional[str] = None,
    submission_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    risk_band: Optional[str] = None,
    pending_only: bool = False,
    oe_code: Optional[str] = None,
) -> list[dict]:
    from dashboard.queries import compute_expense_reports, filter_rows_by_oe

    pcfg = load_pipeline_config()
    scope = resolve_oe_scope(user, oe_code)
    rows = filter_rows_by_oe(request.app.state.data.store.analytics_rows(), scope)
    reports = compute_expense_reports(
        rows,
        auto_approve_cutoff=pcfg.risk.auto_approve_cutoff,
        auto_reject_cutoff=pcfg.risk.auto_reject_cutoff,
        subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
        conf_cutoff=pcfg.extraction.confidence_cutoff,
    )
    return [
        r for r in reports
        if (not pending_only or r["status"] == "SUBMITTED")
        and (not employee_id or employee_id.lower() in r["employee_id"].lower())
        and (not submission_id or submission_id.lower() in r["submission_id"].lower())
        and (not status_filter or r["status"] == status_filter)
        and (not risk_band or r["risk_band"] == risk_band)
    ]


@router.get("/{sid}")
def get_report_detail(
    sid: str, svc: ReviewService = Depends(_review_service),
    user: TokenUser = Depends(get_current_user),
) -> dict:
    detail = svc.detail(sid)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no such submission: {sid}")
    check_oe_access(user, detail["submission"].get("oe_code"))
    return detail


@router.post("/{sid}/decision")
def submit_decision(
    sid: str, payload: DecisionRequest, svc: ReviewService = Depends(_review_service),
    user: TokenUser = Depends(require_role(Role.admin, Role.user)),
) -> dict:
    detail = svc.detail(sid)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no such submission: {sid}")
    check_oe_access(user, detail["submission"].get("oe_code"))
    state = svc.submit_decision(
        sid, reviewer_id=payload.reviewer_id, approved=payload.approved, notes=payload.notes,
    )
    return {
        "submission_id": sid,
        "final_decision": "approved" if payload.approved else "rejected",
        "routing_decision": state.routing_decision.value if state.routing_decision else None,
    }


@router.get("/{sid}/insights")
def get_consolidated_insights(
    sid: str, request: Request, user: TokenUser = Depends(get_current_user),
) -> list[dict]:
    from dashboard.queries import consolidated_insights

    check_oe_access(user, _submission_oe(request, sid))
    pcfg = load_pipeline_config()
    rows = request.app.state.data.store.analytics_rows()
    return consolidated_insights(
        sid, rows,
        subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
        conf_cutoff=pcfg.extraction.confidence_cutoff,
    )


@router.get("/{sid}/pipeline-log")
def get_pipeline_log(
    sid: str, request: Request, user: TokenUser = Depends(get_current_user),
) -> list[dict]:
    check_oe_access(user, _submission_oe(request, sid))
    return request.app.state.data.store.get_pipeline_steps(sid)


@router.get("/{sid}/receipt/{line_id}")
def get_receipt(
    sid: str, line_id: str, svc: ReviewService = Depends(_review_service),
    user: TokenUser = Depends(get_current_user),
) -> Response:
    detail = svc.detail(sid)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no such submission: {sid}")
    check_oe_access(user, detail["submission"].get("oe_code"))
    ref = next((r for r in detail["receipts"] if r["line_id"] == line_id), None)
    if ref is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no receipt for line {line_id}")
    try:
        data = svc.receipt_bytes(ref["receipt_url"])
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"could not load receipt: {exc}") from exc
    media_type = "application/pdf" if ref["receipt_url"].endswith(".pdf") else "image/png"
    return Response(content=data, media_type=media_type)
