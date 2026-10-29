"""GET /dashboard, GET /user-analytics - wraps dashboard/queries.py."""
from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from integration.security import TokenUser, get_current_user, resolve_oe_scope
from pipeline.config import load_pipeline_config

router = APIRouter(tags=["analytics"])


@router.get("/dashboard")
def get_dashboard(
    request: Request, user: TokenUser = Depends(get_current_user), oe_code: Optional[str] = None,
) -> dict:
    from dashboard.queries import compute_dashboard, filter_rows_by_oe

    pcfg = load_pipeline_config()
    scope = resolve_oe_scope(user, oe_code)
    rows = filter_rows_by_oe(request.app.state.data.store.analytics_rows(), scope)
    return asdict(compute_dashboard(
        rows,
        subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
        conf_cutoff=pcfg.extraction.confidence_cutoff,
    ))


@router.get("/user-analytics")
def get_user_analytics(
    request: Request, employee_id: str, period_days: Optional[int] = None,
    user: TokenUser = Depends(get_current_user), oe_code: Optional[str] = None,
) -> dict:
    from dashboard.queries import filter_rows_by_oe, list_employees, user_analytics

    pcfg = load_pipeline_config()
    scope = resolve_oe_scope(user, oe_code)
    rows = filter_rows_by_oe(request.app.state.data.store.analytics_rows(), scope)
    if employee_id not in list_employees(rows):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no such employee: {employee_id}")
    return user_analytics(
        rows, employee_id,
        subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
        conf_cutoff=pcfg.extraction.confidence_cutoff,
        auto_reject_cutoff=pcfg.risk.auto_reject_cutoff,
        period_days=period_days,
    )
