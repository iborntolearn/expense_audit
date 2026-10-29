"""GET/PUT /admin/config/{pipeline,generator,thresholds,policy,env} - wraps
config_admin.py's validated YAML saves (System admin/Settings pages).
Admin-only. Every save is validated by constructing the matching pydantic
model BEFORE writing (config_admin.py's own guarantee) - a 400 here means the
same thing it would in the Streamlit UI: the pipeline would have rejected it
at startup, so the write never happened.
"""
from __future__ import annotations

from typing import Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

import config_admin as ca
from common.auth import Role
from config.settings import get_settings
from generator.config import GeneratorConfig
from integration.api_schemas import EnvUpdateRequest
from integration.security import TokenUser, require_role, resolve_oe_scope
from pipeline.config import PipelineConfig
from services.oe_config_service import OeConfigService
from services.policy_rule_service import PolicyRuleService

router = APIRouter(prefix="/admin/config", tags=["admin-config"])
_admin = require_role(Role.admin)


def _save(fn, data: dict) -> None:
    try:
        fn(data)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _load(request: Request, base_path, name: str, scope: Optional[str]) -> dict:
    if scope is None:
        return ca.load_raw(base_path)
    return OeConfigService(request.app.state.data.config).load_merged(base_path, name, scope)


def _put(request: Request, base_path, name: str, scope: Optional[str], data: dict) -> None:
    if scope is None:
        base_path.write_text(
            yaml.safe_dump(data, sort_keys=False, default_flow_style=False), encoding="utf-8"
        )
    else:
        OeConfigService(request.app.state.data.config).save(name, scope, data)


@router.get("/pipeline")
def get_pipeline_config(request: Request, user: TokenUser = Depends(_admin), oe: Optional[str] = None) -> dict:
    return _load(request, ca.PIPELINE_YAML, "pipeline", resolve_oe_scope(user, oe))


@router.put("/pipeline")
def put_pipeline_config(
    data: dict, request: Request, user: TokenUser = Depends(_admin), oe: Optional[str] = None,
) -> dict:
    scope = resolve_oe_scope(user, oe)

    def _do(d: dict) -> None:
        PipelineConfig.model_validate(d)  # the merged result must be valid, whichever scope
        _put(request, ca.PIPELINE_YAML, "pipeline", scope, d)

    _save(_do, data)
    return {"ok": True, "oe": scope}


@router.get("/generator")
def get_generator_config(request: Request, user: TokenUser = Depends(_admin), oe: Optional[str] = None) -> dict:
    return _load(request, ca.GENERATOR_YAML, "generator", resolve_oe_scope(user, oe))


@router.put("/generator")
def put_generator_config(
    data: dict, request: Request, user: TokenUser = Depends(_admin), oe: Optional[str] = None,
) -> dict:
    scope = resolve_oe_scope(user, oe)

    def _do(d: dict) -> None:
        GeneratorConfig.model_validate(d)
        _put(request, ca.GENERATOR_YAML, "generator", scope, d)

    _save(_do, data)
    return {"ok": True, "oe": scope}


@router.get("/thresholds")
def get_thresholds(request: Request, user: TokenUser = Depends(_admin), oe: Optional[str] = None) -> dict:
    return _load(request, ca.THRESHOLDS_YAML, "thresholds", resolve_oe_scope(user, oe))


@router.put("/thresholds")
def put_thresholds(
    data: dict, request: Request, user: TokenUser = Depends(_admin), oe: Optional[str] = None,
) -> dict:
    scope = resolve_oe_scope(user, oe)

    def _do(d: dict) -> None:
        ca.validate_thresholds(d)
        _put(request, ca.THRESHOLDS_YAML, "thresholds", scope, d)

    _save(_do, data)
    return {"ok": True, "oe": scope}


@router.get("/policy")
def get_policy(request: Request, user: TokenUser = Depends(_admin), oe: Optional[str] = None) -> dict:
    return PolicyRuleService(request.app.state.data.config).load(resolve_oe_scope(user, oe))


@router.put("/policy")
def put_policy(
    data: dict, request: Request, user: TokenUser = Depends(_admin), oe: Optional[str] = None,
) -> dict:
    scope = resolve_oe_scope(user, oe)
    _save(lambda d: PolicyRuleService(request.app.state.data.config).save(d, scope), data)
    return {"ok": True, "oe": scope}


@router.get("/env/{key}")
def get_env_value(key: str, user: TokenUser = Depends(_admin)) -> dict:
    return {"key": key, "value": ca.env_value(key)}


@router.put("/env")
def put_env_values(payload: EnvUpdateRequest, user: TokenUser = Depends(_admin)) -> dict:
    ca.update_env(payload.updates)
    # Anything already baked into this process's app.state (data layer,
    # pipeline, vision provider) was constructed once at startup and won't
    # pick up a changed env var without a process restart - same limitation
    # the real Streamlit app has for anything not behind its reload()
    # cache-clear. Settings.get_settings() itself IS safe to refresh live.
    get_settings.cache_clear()
    return {"ok": True, "note": "settings cache cleared; restart the API process "
                                 "to fully apply changes to already-built resources "
                                 "(data layer, pipeline, vision provider)"}
