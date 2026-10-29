"""GET /admin/environment, POST /admin/reload - wraps System admin ->
Environment tab (app_pages/system_admin.py env_tab). Admin-only, read-only
diagnostic info plus a settings-cache-clear action.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

import config_admin as ca
from common.auth import Role
from config.settings import get_settings
from integration.security import TokenUser, require_role
from pipeline.config import load_pipeline_config

router = APIRouter(prefix="/admin", tags=["admin-environment"])
_admin = require_role(Role.admin)


@router.get("/environment")
def get_environment(user: TokenUser = Depends(_admin)) -> dict:
    settings = get_settings()
    pcfg = load_pipeline_config()
    env: dict = {
        "mode_requested": settings.simulation_mode.value,
        "live_mode_active": settings.live_mode_active,
        "storage_backend": settings.storage_backend.value,
        "engine": pcfg.engine,
        "vision_provider": pcfg.extraction.provider,
        "embedding_dim": settings.embedding_dim,
    }
    if pcfg.extraction.provider == "azure_openai":
        env.update({
            "azure_deployment": ca.env_value("AZURE_DEPLOYMENT_NAME") or settings.azure_deployment_name,
            "azure_api_version": ca.env_value("AZURE_API_VERSION") or settings.azure_api_version,
            "azure_endpoint": ca.env_value("AZURE_OPENAI_ENDPOINT") or "(not set)",
            "azure_openai_key_set": bool(ca.env_value("AZURE_OPENAI_KEY")),
        })
    else:
        env.update({
            "vision_model": ca.env_value("LLM_VISION_MODEL") or settings.llm_vision_model,
            "anthropic_key_set": bool(ca.env_value("ANTHROPIC_API_KEY")),
        })
    env.update({
        "sqlite_path": str(settings.sqlite_file),
        "checkpoint_path": str(settings.checkpoint_file),
        "live_mode_blocked_reason": None if settings.live_mode_active or not settings.live_mode_requested
        else settings.live_mode_blocked_reason,
    })
    return env


@router.post("/reload")
def reload_config(user: TokenUser = Depends(_admin)) -> dict:
    # Mirrors app_common.py's reload(): drop the settings cache so the next
    # request re-reads .env. Resources already baked into this process's
    # app.state (data layer, pipeline, vision provider) still need a process
    # restart - there's no Streamlit-style st.cache_resource.clear() equivalent
    # for an already-running API process.
    get_settings.cache_clear()
    return {"ok": True, "note": "settings cache cleared; restart the API process to rebuild "
                                 "already-built resources (data layer, pipeline, vision provider)"}
