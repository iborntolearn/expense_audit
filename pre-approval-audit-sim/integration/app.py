"""Integration layer - FastAPI application.

Phase 0: app skeleton + /health.
Phase 1 (Milestone 3): the submission-created webhook receiver, the mock
decision write-back sink, the SIMULATION_MODE gate, and an in-process bus wired
to the ingest service so the Simulation Harness can replay a run end to end.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware

from adapters.connectors.config import load_connectors_config
from adapters.connectors.factory import build_connectors
from common.schemas import AuditDecisionWriteback, SubmissionCreatedEvent
from config.settings import get_settings
from data.factory import DataLayer, build_data_layer
from integration.bus import InProcessBus
from integration.ingest import IngestService
from integration.routes import (
    admin_config,
    admin_danger,
    admin_devtools,
    admin_environment,
    admin_users,
    admin_watchlist,
    analytics,
    assistant,
    auth,
    case_status,
    connectors,
    email_templates,
    reports,
    reports_export,
)
from pipeline.factory import build_pipeline
from review_ui.service import ReviewService

logger = logging.getLogger("integration.app")


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        data: DataLayer = build_data_layer(settings)
        data.migrate()

        pipeline = build_pipeline(data, settings)
        ingest = IngestService(
            data.store,
            pipeline,
            is_synthetic=settings.is_synthetic_data,
        )
        bus = InProcessBus()
        bus.subscribe(ingest.handle)

        app.state.data = data
        app.state.ingest = ingest
        app.state.bus = bus
        try:
            app.state.review_service = ReviewService(data, pipeline)
        except RuntimeError as exc:
            # Sequential engine (config/pipeline.yaml engine != langgraph) can't
            # resume a suspended run - the /reports review routes need
            # request.app.state.review_service to exist, so degrade explicitly
            # rather than crash startup; each route surfaces 503 instead.
            logger.warning("review routes disabled: %s", exc)
            app.state.review_service = None
        try:
            app.state.connectors = build_connectors(settings, load_connectors_config(), data.blobs)
        except RuntimeError as exc:
            # A real connector selected in config/connectors.yaml but missing
            # its credentials (e.g. concur_client_id unset) - degrade rather
            # than crash startup; /admin/connectors builds a fresh connector
            # per test-connection call anyway, so this cached registry isn't
            # load-bearing for anything yet (see connectors.router's docstring
            # - no pipeline wiring in this pass).
            logger.warning("connector registry incomplete at startup: %s", exc)
            app.state.connectors = None
        if settings.live_mode_requested and not settings.live_mode_active:
            logger.warning(
                "SIMULATION_MODE=live was requested but is NOT active - %s",
                settings.live_mode_blocked_reason,
            )
        if settings.jwt_secret_is_insecure_default:
            # Hard-fail only when live mode is actually ACTIVE, not merely
            # requested - SIMULATION_MODE=live alone must stay completely
            # inert in this build (see live_mode_active's own docstring and
            # test_live_mode_gate_rejects, which relies on setting it alone
            # never changing app behavior). live_mode_active additionally
            # requires the hardcoded LIVE_MODE_GATES_SATISFIED flip, which is
            # itself a deliberate code change made by someone who has
            # verified the other two gates - that's the one point where
            # "this is a real deployment, not local simulation" is an
            # actually-earned signal, so it's the right gate for this too.
            if settings.live_mode_active:
                raise RuntimeError(
                    "Live mode is active but jwt_secret_key is still the public "
                    "default ('dev-insecure-secret-change-me') - anyone who knows "
                    "this default can forge a valid session token, including an "
                    "admin-role one. Set JWT_SECRET_KEY to a real random secret in "
                    ".env before running with live mode active."
                )
            logger.warning(
                "jwt_secret_key is still the insecure default "
                "('dev-insecure-secret-change-me') - fine for local simulation-mode "
                "use, but MUST be changed before this service is reachable from "
                "anywhere other than your own machine. Set JWT_SECRET_KEY in .env."
            )
        logger.info(
            "startup complete: simulation_mode=%s (active=%s) storage_backend=%s pipeline=%s",
            settings.simulation_mode.value,
            settings.live_mode_active,
            settings.storage_backend.value,
            type(pipeline).__name__,
        )
        try:
            yield
        finally:
            data.close()

    app = FastAPI(
        title="Veriflow - Pre-Approval Expense Audit (Simulation)",
        version="0.1.0",
        lifespan=lifespan,
    )
    for r in (auth.router, reports.router, case_status.router, email_templates.router,
              analytics.router, assistant.router, admin_users.router, admin_watchlist.router,
              admin_config.router, admin_danger.router, reports_export.router,
              admin_environment.router, admin_devtools.router, connectors.router):
        app.include_router(r)

    # React dev server (Vite default port) - sim/dev-only origin list, not a
    # wildcard, so this stays honest about what's actually allowed rather than
    # silently permitting any origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _require_simulation() -> None:
        # Gated on live_mode_active (requires the hardcoded
        # LIVE_MODE_GATES_SATISFIED kill-switch), not the raw SIMULATION_MODE
        # env value - so SIMULATION_MODE=live alone can never enable this path.
        if not settings.live_mode_active and settings.live_mode_requested:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail=settings.live_mode_blocked_reason,
            )

    @app.get("/health")
    def health(response: Response) -> dict:
        data: DataLayer = app.state.data
        ok = data.health()
        response.status_code = status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ok" if ok else "degraded",
            "simulation_mode": settings.simulation_mode.value,
            "live_mode_active": settings.live_mode_active,
            "storage_backend": settings.storage_backend.value,
            "tables": sorted(data.store.table_names()),
        }

    @app.post("/webhooks/submission-created")
    def submission_created(event: SubmissionCreatedEvent) -> dict:
        _require_simulation()
        result = app.state.ingest.handle(event)
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

    @app.post("/webhooks/audit-decision")
    def audit_decision(decision: AuditDecisionWriteback) -> dict:
        # Mock sink standing in for the source T&E system receiving a decision.
        _require_simulation()
        logger.info(
            "mock source-system received decision for %s: %s",
            decision.submission_id,
            decision.decision.value,
        )
        return {"acknowledged": True, "submission_id": decision.submission_id}

    return app


app = create_app()
