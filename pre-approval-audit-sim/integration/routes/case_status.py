"""GET/PUT /case-status/{sid} (BR-TE-AU-13 case management)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from common.auth import Role
from integration.api_schemas import CaseStatusUpdate
from integration.security import TokenUser, get_current_user, require_role

router = APIRouter(prefix="/case-status", tags=["case-status"])


@router.get("/{sid}")
def get_case_status(
    sid: str, request: Request, user: TokenUser = Depends(get_current_user),
) -> dict:
    return request.app.state.data.store.get_case_status(sid) or {
        "submission_id": sid, "status": "open", "recovered_amount": None,
    }


@router.put("/{sid}")
def update_case_status(
    sid: str, payload: CaseStatusUpdate, request: Request,
    user: TokenUser = Depends(require_role(Role.admin, Role.user)),
) -> dict:
    request.app.state.data.store.set_case_status(
        sid, status=payload.status, recovered_amount=payload.recovered_amount,
        updated_by=payload.updated_by,
    )
    return request.app.state.data.store.get_case_status(sid)
