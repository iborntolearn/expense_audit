"""GET /pipeline-logs, GET /compliance-packs, GET /reports-export/accuracy-latency*
- wraps the remaining 3 tabs of Reports & exports (app_pages/reports.py) that
aren't already covered by GET /reports (the "Decision extract" tab reuses that
endpoint directly - same rows, no separate route needed). Read-only, all
authenticated roles (auditor needs this page per BR-TE-AU-10).
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from config.settings import get_settings
from integration.security import TokenUser, get_current_user, resolve_oe_scope

router = APIRouter(tags=["reports-export"])


@router.get("/pipeline-logs")
def pipeline_logs(
    request: Request, limit: int = 5000, user: TokenUser = Depends(get_current_user),
    oe_code: Optional[str] = None,
) -> list[dict]:
    from dashboard.queries import submission_ids_for_oe

    logs = request.app.state.data.store.get_recent_pipeline_logs(limit=limit)
    scope = resolve_oe_scope(user, oe_code)
    if scope is None:
        return logs
    allowed = submission_ids_for_oe(request.app.state.data.store.analytics_rows(), scope)
    return [l for l in logs if l.get("submission_id") in allowed]


@router.get("/compliance-packs")
def compliance_packs(
    request: Request, user: TokenUser = Depends(get_current_user), oe_code: Optional[str] = None,
) -> dict:
    from dashboard.queries import compute_compliance_packs, filter_cases_by_oe, filter_rows_by_oe

    scope = resolve_oe_scope(user, oe_code)
    all_rows = request.app.state.data.store.analytics_rows()
    rows = filter_rows_by_oe(all_rows, scope)
    cases = filter_cases_by_oe(request.app.state.data.store.list_case_statuses(), all_rows, scope)
    return compute_compliance_packs(rows, cases)


def _latest_report_dir():
    settings = get_settings()
    synth = settings.resolve("./.data/synthetic")
    files = sorted(synth.glob("*/report.json"), key=lambda p: p.stat().st_mtime, reverse=True) \
        if synth.exists() else []
    return files[0] if files else None


@router.get("/reports-export/accuracy-latency")
def accuracy_latency_report(user: TokenUser = Depends(get_current_user)) -> dict:
    latest = _latest_report_dir()
    if latest is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "no accuracy/latency report yet - generate one via `python scripts/report.py`",
        )
    rep = json.loads(latest.read_text(encoding="utf-8"))
    return {"source": str(latest), "metrics": rep["metrics"],
            "markdown_available": latest.with_suffix(".md").exists()}


@router.get("/reports-export/accuracy-latency/download")
def accuracy_latency_download(
    fmt: str = "json", user: TokenUser = Depends(get_current_user),
) -> Response:
    if fmt not in ("json", "markdown"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "fmt must be 'json' or 'markdown'")
    latest = _latest_report_dir()
    if latest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no accuracy/latency report yet")
    if fmt == "json":
        return Response(content=latest.read_bytes(), media_type="application/json")
    md = latest.with_suffix(".md")
    if not md.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no markdown version of this report")
    return Response(content=md.read_bytes(), media_type="text/markdown")
