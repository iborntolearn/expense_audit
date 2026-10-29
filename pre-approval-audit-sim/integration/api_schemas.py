"""Pydantic request/response models for the REST API (integration/routes/*).

Read-heavy aggregation endpoints (dashboard, reports list, user analytics)
return the plain dict/dataclass shape dashboard/queries.py already produces
rather than a re-declared duplicate schema - FastAPI serializes those directly.
These models cover the inputs (what a request body must contain) and the few
outputs worth a stable, documented shape.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    display_name: str
    role: str
    oe_code: Optional[str] = None


class CurrentUserResponse(BaseModel):
    username: str
    display_name: str
    role: str
    oe_code: Optional[str] = None


class DecisionRequest(BaseModel):
    reviewer_id: str
    approved: bool
    notes: Optional[str] = None


class CaseStatusUpdate(BaseModel):
    status: str
    recovered_amount: Optional[float] = None
    updated_by: str


class EmailRenderRequest(BaseModel):
    template_name: str
    submission_id: str
    reason: str = ""


class EmailRenderResponse(BaseModel):
    subject: str
    body: str


class AssistantHistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AssistantAskRequest(BaseModel):
    question: str
    history: list[AssistantHistoryTurn] = Field(default_factory=list)


# --- config-admin (admin-only) ---
class AddUserRequest(BaseModel):
    username: str
    display_name: str
    role: str
    password: str
    oe_code: Optional[str] = None


class ResetPasswordRequest(BaseModel):
    new_password: str


class SetRoleRequest(BaseModel):
    role: str


class SetOeRequest(BaseModel):
    oe_code: Optional[str] = None


class AddBlocklistEntryRequest(BaseModel):
    name: str
    entry_type: str
    reason: str = "Simulated watchlist entry"


class UpdateMerchantStatusRequest(BaseModel):
    """Admin override for one merchant_registry row (System admin ->
    Watchlist -> Merchant registry). Any field left unset leaves that column
    unchanged."""
    status: Optional[Literal["clear", "watch", "blocked"]] = None
    risk_tier: Optional[Literal["low", "medium", "high"]] = None
    reason: Optional[str] = None


class SaveEmailTemplateRequest(BaseModel):
    subject: str
    body: str


class EnvUpdateRequest(BaseModel):
    updates: dict[str, str]


class PurgeRequest(BaseModel):
    confirm: bool = False

