"""POST /assistant/ask - wraps a provider-selected AssistantResponder
(assistant/responder.py).

Default provider is the deterministic rule-based engine over analytics_rows()
(no LLM, no cost); `assistant.provider` in pipeline.yaml can upgrade this to
real LLM tool-calling reasoning (Anthropic/Azure OpenAI) - either way this is
a synchronous request/response, no streaming needed.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, Request

from integration.api_schemas import AssistantAskRequest
from integration.security import TokenUser, get_current_user, resolve_oe_scope
from pipeline.config import load_pipeline_config

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/examples")
def examples(user: TokenUser = Depends(get_current_user)) -> list[str]:
    from assistant.engine import EXAMPLES

    return EXAMPLES


@router.post("/ask")
def ask(
    payload: AssistantAskRequest, request: Request,
    user: TokenUser = Depends(get_current_user), oe_code: Optional[str] = None,
) -> dict:
    from adapters.factory import build_assistant_responder
    from config.settings import get_settings
    from dashboard.queries import filter_rows_by_oe

    scope = resolve_oe_scope(user, oe_code)
    pcfg = load_pipeline_config(scope)
    rows = filter_rows_by_oe(request.app.state.data.store.analytics_rows(), scope)
    responder = build_assistant_responder(get_settings(), pcfg)
    ans = responder.answer(
        payload.question, rows,
        subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
        conf_cutoff=pcfg.extraction.confidence_cutoff,
        auto_approve_cutoff=pcfg.risk.auto_approve_cutoff,
        auto_reject_cutoff=pcfg.risk.auto_reject_cutoff,
        history=[h.model_dump() for h in payload.history],
    )
    return asdict(ans)
