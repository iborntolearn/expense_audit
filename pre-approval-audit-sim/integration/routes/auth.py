"""POST /auth/login, POST /auth/logout, GET /auth/me.

Tokens are stateless (HMAC-signed, see integration/security.py) - "logout" has
no server-side session to invalidate; the client just discards the token.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from config.settings import Settings, get_settings
from integration.api_schemas import CurrentUserResponse, LoginRequest, LoginResponse
from integration.security import TokenUser, get_current_user, issue_token
from services.user_service import UserService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest, request: Request, settings: Settings = Depends(get_settings),
) -> LoginResponse:
    record = UserService(request.app.state.data.config).authenticate(
        payload.username, payload.password
    )
    if record is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid username or password")
    token = issue_token(
        record.username, record.role, record.display_name,
        settings=settings, oe_code=record.oe_code,
    )
    return LoginResponse(
        access_token=token, username=record.username,
        display_name=record.display_name, role=record.role.value, oe_code=record.oe_code,
    )


@router.post("/logout")
def logout() -> dict:
    return {"ok": True}


@router.get("/me", response_model=CurrentUserResponse)
def me(user: TokenUser = Depends(get_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse(username=user.username, display_name=user.display_name,
                                role=user.role.value, oe_code=user.oe_code)
