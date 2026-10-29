"""Central configuration loader.

All runtime configuration is read from environment variables (optionally via a
local `.env` file). Nothing in the codebase should read `os.environ` directly or
hardcode a tunable value - import `settings` from here instead. This keeps the
"zero hardcoding" guardrail (Build Brief 7) enforceable in one place.
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root (…/pre-approval-audit-sim). Used to resolve relative paths so
# the app behaves the same regardless of the current working directory.
REPO_ROOT = Path(__file__).resolve().parent.parent


class SimulationMode(str, Enum):
    simulation = "simulation"
    live = "live"  # intentionally unimplemented in this build (Build Brief 2.2)


# Live behavior requires ALL THREE of the following gates to be satisfied
# (Solution Design 12 - the Phase 0 -> A transition), independent of whatever
# SIMULATION_MODE is set to in the environment:
#   1. a real T&E connector is implemented - integration/concur_client.py and
#      integration/harness.py are simulation-only in this build;
#   2. real-data governance / legal sign-off has been obtained;
#   3. threat-model remediation (deprioritised per Build Brief 4.2) is complete.
# None of these exist in this build. This is a deliberate, HARDCODED
# kill-switch - it is a Python constant, not an environment variable or config
# field, so it can never be flipped by editing .env, config/*.yaml, or the
# Settings UI. Setting SIMULATION_MODE=live in .env changes what the system
# *reports* (see Settings.simulation_mode) but never what it *does*: every
# governance-sensitive behavior (is_synthetic tagging, the webhook gate) reads
# LIVE_MODE_GATES_SATISFIED, not the raw env value. Flipping this to True is a
# deliberate code change made by a human who has verified all three gates -
# never a side effect of a config edit.
LIVE_MODE_GATES_SATISFIED = False


class StorageBackend(str, Enum):
    sqlite_local = "sqlite_local"
    postgres = "postgres"


# The JWT-lite session-token default (integration/security.py) - publicly
# known, so any deployment that leaves it unchanged lets anyone forge a valid
# session token (including admin-role claims). Named once here rather than
# repeated as a bare string literal at both the Settings field default below
# and the startup check in integration/app.py that compares against it.
INSECURE_JWT_DEFAULT = "dev-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- mode switches ---
    simulation_mode: SimulationMode = SimulationMode.simulation
    storage_backend: StorageBackend = StorageBackend.sqlite_local

    # --- sqlite_local backend ---
    sqlite_path: str = "./.data/audit.db"

    # --- postgres backend ---
    postgres_dsn: str = "postgresql://audit:audit@localhost:5432/audit"

    # --- blob storage ---
    blob_root: str = "./.data/blobs"

    # --- LangGraph durable checkpoints (Tech Design 3.4) ---
    checkpoint_path: str = "./.data/checkpoints.db"

    # --- models (adapters only; no calls made in Phase 0) ---
    anthropic_api_key: str = ""
    llm_vision_model: str = "claude-sonnet-5"
    embedding_dim: int = 1536

    # --- Azure OpenAI vision (GPT-4.1 etc.) - env var names match the SOA
    # Layout Agent app (AZURE_OPENAI_KEY / AZURE_OPENAI_ENDPOINT /
    # AZURE_DEPLOYMENT_NAME / AZURE_API_VERSION) for config parity across apps.
    azure_openai_key: str = ""
    azure_openai_endpoint: str = ""
    azure_deployment_name: str = "gpt-4.1"
    azure_api_version: str = "2024-08-01-preview"

    # --- integration connectors (adapters/connectors/) - secrets only; which
    # provider is active per connector role lives in config/connectors.yaml,
    # matching the pipeline.yaml (config-as-code) / Settings (secrets) split
    # already used for the vision extractors above. Blank by default - the
    # simulated connectors need none of these. ---
    concur_client_id: str = ""
    concur_client_secret: str = ""
    concur_base_url: str = ""
    cytric_client_id: str = ""
    cytric_client_secret: str = ""
    cytric_base_url: str = ""
    workday_client_id: str = ""
    workday_client_secret: str = ""
    workday_base_url: str = ""
    workday_tenant: str = ""
    oracle_ebs_client_id: str = ""
    oracle_ebs_client_secret: str = ""
    oracle_ebs_base_url: str = ""

    # --- app ---
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"

    # --- REST API session tokens (integration/security.py) ---
    # Dev/sim default, matching the app's existing security posture (baseline
    # local auth, not a real IdP - see common/auth.py) - override via .env for
    # anything beyond local simulation.
    jwt_secret_key: str = INSECURE_JWT_DEFAULT
    jwt_ttl_minutes: int = 480

    # ------------------------------------------------------------------ helpers
    def resolve(self, maybe_relative: str) -> Path:
        """Resolve a possibly-relative path against the repo root."""
        p = Path(maybe_relative)
        return p if p.is_absolute() else (REPO_ROOT / p)

    @property
    def sqlite_file(self) -> Path:
        return self.resolve(self.sqlite_path)

    @property
    def blob_dir(self) -> Path:
        return self.resolve(self.blob_root)

    @property
    def checkpoint_file(self) -> Path:
        return self.resolve(self.checkpoint_path)

    @property
    def jwt_secret_is_insecure_default(self) -> bool:
        return self.jwt_secret_key == INSECURE_JWT_DEFAULT

    @property
    def live_mode_requested(self) -> bool:
        """What SIMULATION_MODE says - a request, not a grant."""
        return self.simulation_mode is SimulationMode.live

    @property
    def live_mode_active(self) -> bool:
        """Whether the system is actually allowed to behave as live. Always
        False in this build: live_mode_requested alone is never sufficient -
        see LIVE_MODE_GATES_SATISFIED."""
        return self.live_mode_requested and LIVE_MODE_GATES_SATISFIED

    @property
    def is_synthetic_data(self) -> bool:
        """Whether newly-ingested data should be tagged is_synthetic=true.
        True unless live mode is both requested AND actually unlocked - so
        SIMULATION_MODE=live alone can never cause real data to be tagged as
        non-synthetic."""
        return not self.live_mode_active

    @property
    def live_mode_blocked_reason(self) -> str:
        return (
            "Live mode requires three gates that are not satisfied in this build "
            "(Solution Design 12, Build Brief 2.2): a real T&E connector, "
            "real-data governance/legal sign-off, and completed threat-model "
            "remediation. Setting SIMULATION_MODE=live alone does not enable live "
            "behavior - it must be unlocked in code "
            "(config/settings.py LIVE_MODE_GATES_SATISFIED) by someone who has "
            "verified all three gates."
        )


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so the .env file is parsed once per process."""
    return Settings()
