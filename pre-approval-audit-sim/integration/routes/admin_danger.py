"""GET /admin/danger/summary, POST /admin/danger/purge - wraps
data.factory.purge_all_transactional_data (System admin -> Reset DB tab).
Global-admin-only, irreversible - the caller must pass {"confirm": true},
mirroring the Streamlit UI's checkbox-then-button double confirmation. Not
opened up to OE-scoped admins: this purges EVERY OE's data in one shot, and a
correctly-scoped partial purge (across every table + blob storage) is a
materially riskier change than the read-side OE scoping used elsewhere.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from config.settings import get_settings
from data.factory import purge_all_transactional_data
from integration.api_schemas import PurgeRequest
from integration.security import TokenUser, require_global_admin

router = APIRouter(prefix="/admin/danger", tags=["admin-danger"])
_admin = require_global_admin()


@router.get("/summary")
def danger_summary(request: Request, user: TokenUser = Depends(_admin)) -> dict:
    settings = get_settings()
    data = request.app.state.data
    n_submissions = len(data.store.analytics_rows().get("submissions", []))
    try:
        n_blobs = len([p for p in settings.blob_dir.rglob("*") if p.is_file()])
    except Exception:
        n_blobs = 0
    return {
        "submissions": n_submissions,
        "blob_files": n_blobs,
        "checkpoint_present": settings.checkpoint_file.exists(),
    }


@router.post("/purge")
def purge(payload: PurgeRequest, request: Request, user: TokenUser = Depends(_admin)) -> dict:
    if not payload.confirm:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "irreversible - resend with {\"confirm\": true} to proceed",
        )
    summary = purge_all_transactional_data(request.app.state.data, get_settings())
    return summary
