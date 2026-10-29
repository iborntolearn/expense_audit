"""Concur simulator + Run audit batch - wraps System admin's dev-tooling tabs
(app_pages/system_admin.py: custom_tab manual/auto-detect modes, run_tab).
Admin-only. These generate/ingest data directly - not part of the "real"
audited business workflow, same scope as the Streamlit page they mirror.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

from adapters.factory import build_vision_extractor
from adapters.vision import ITEMIZE_CATEGORIES, save_itemization
from common.auth import Role
from common.policy import load_policy_rules
from common.schemas import ItemizedEntry, SubmissionCreatedEvent
from config.settings import get_settings
from generator.config import load_generator_config
from generator.synthesize import Synthesizer
from integration.security import TokenUser, require_role
from pipeline.config import load_pipeline_config

router = APIRouter(prefix="/admin", tags=["admin-devtools"])
_admin = require_role(Role.admin)

_SIM_AUTHENTICITY_SIDECAR = {"metadata": {"edited": True, "ai_generated_score": 0.9}}


def _key_to_url(key: str) -> str:
    return f"blob://{key}"


@router.post("/receipts/upload")
async def upload_receipt(
    request: Request,
    submission_id: str = Form(...),
    mode: Literal["manual", "auto"] = Form(...),
    file: UploadFile = File(...),
    user: TokenUser = Depends(_admin),
) -> dict:
    prefix = "LN-1_" if mode == "manual" else "AUTO_"
    key = f"manual/{submission_id}/{prefix}{file.filename}"
    content = await file.read()
    receipt_url = request.app.state.data.blobs.put(
        key, content, file.content_type or "application/octet-stream",
    )
    return {"key": key, "receipt_url": receipt_url}


@router.post("/receipts/simulate-authenticity")
def simulate_authenticity(payload: dict, request: Request, user: TokenUser = Depends(_admin)) -> dict:
    key = payload["key"]
    request.app.state.data.blobs.put(
        key + ".sim.json", json.dumps(_SIM_AUTHENTICITY_SIDECAR).encode(), "application/json",
    )
    return {"ok": True}


class AutoDetectRequest(BaseModel):
    key: str
    currency: str


@router.post("/receipts/auto-detect")
def auto_detect_items(
    payload: AutoDetectRequest, request: Request, user: TokenUser = Depends(_admin),
) -> dict:
    settings = get_settings()
    pcfg = load_pipeline_config()
    extractor = build_vision_extractor(settings, pcfg)
    receipt_url = _key_to_url(payload.key)
    try:
        items = extractor.extract_items(
            request.app.state.data.blobs, receipt_url, payload.currency, ITEMIZE_CATEGORIES,
        )
    except Exception as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"could not read line items from this file: {exc}",
        ) from exc
    if not items:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "no line items could be read from this file")
    save_itemization(request.app.state.data.blobs, payload.key, items)
    return {"items": [i.model_dump(mode="json") for i in items]}


class SaveItemizationRequest(BaseModel):
    key: str
    items: list[ItemizedEntry]


@router.post("/receipts/save-itemization")
def save_itemization_route(
    payload: SaveItemizationRequest, request: Request, user: TokenUser = Depends(_admin),
) -> dict:
    save_itemization(request.app.state.data.blobs, payload.key, payload.items)
    return {"ok": True}


class GenerateEventsRequest(BaseModel):
    sample_size: int = 20


@router.post("/generate-synthetic-events")
def generate_synthetic_events(
    payload: GenerateEventsRequest, request: Request, user: TokenUser = Depends(_admin),
) -> dict:
    seed = int(datetime.now(timezone.utc).timestamp())
    cfg = load_generator_config().model_copy(update={"volume": payload.sample_size, "seed": seed})
    rules = load_policy_rules()
    events, _ground_truth = Synthesizer(cfg, rules, request.app.state.data.blobs).generate()
    return {"seed": seed, "events": [e.model_dump(mode="json") for e in events]}


@router.post("/ingest-event")
def ingest_event(event: SubmissionCreatedEvent, request: Request, user: TokenUser = Depends(_admin)) -> dict:
    # In-process ingest (bypasses HTTP) - used by "Run audit batch", which runs
    # generated events directly through app.state.ingest the same way the real
    # webhook route does internally, just without the network hop.
    result = request.app.state.ingest.handle(event)
    return {
        "submission_id": event.submission_id,
        "accepted": result.accepted,
        "reason": result.reason,
        "routing_decision": (
            result.state.routing_decision.value
            if result.state and result.state.routing_decision
            else None
        ),
    }
