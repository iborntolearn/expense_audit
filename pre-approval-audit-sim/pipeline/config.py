"""Pipeline runtime configuration model (loads config/pipeline.yaml)."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

import yaml
from pydantic import BaseModel, Field

from config.oe_overrides import deep_merge, load_merged_raw
from config.settings import REPO_ROOT

if TYPE_CHECKING:
    from data.interfaces import ConfigStore

_DEFAULT_PATH = REPO_ROOT / "config" / "pipeline.yaml"


class RetryConfig(BaseModel):
    max_retries: int = Field(ge=0)
    backoff_seconds: list[float]


class ExtractionSimConfig(BaseModel):
    base_confidence: float
    error_rate: float = Field(ge=0, le=1)
    illegible_rate: float = Field(ge=0, le=1)
    low_conf_range: list[float]
    illegible_conf_max: float


class ExtractionConfig(BaseModel):
    provider: str = "simulated"
    confidence_cutoff: float
    simulation: ExtractionSimConfig


class ForensicsConfig(BaseModel):
    """Real (non-simulated) receipt forensics - common/forensics.py's EXIF/
    PDF-metadata + Error-Level-Analysis checks, plus an optional real
    vision-model AI-generation second opinion (VisionExtractor.
    assess_forensics). Distinct from `_authenticity()`'s `.sim.json`-based
    signal, which stays simulation-only for backward test compatibility."""

    enabled: bool = True
    # Only "photo"-format lines are held to "must have camera EXIF" - an
    # e-receipt or scanned PDF legitimately has none and must never be
    # penalised for it.
    require_camera_exif_for_formats: list[str] = Field(default_factory=lambda: ["photo"])
    ela_quality: int = 90
    # These two are a starting point, not a calibrated production value - JPEG
    # recompression error depends heavily on the source image's own noise
    # floor (a real camera photo has far more natural high-frequency texture
    # than a flat synthetic test image), so this genuinely needs re-tuning
    # against a corpus of real receipt photos before relying on it in
    # production; too low and ordinary photo noise trips it, too high and it
    # misses real pastes.
    ela_diff_threshold: int = 15
    ela_region_frac_threshold: float = 0.02
    # A real second model call per line - off by default (cost control).
    vision_second_opinion_enabled: bool = False
    vision_second_opinion_gate: str = "on_suspicion"  # "on_suspicion" | "always"
    vision_ai_generated_threshold: float = 0.5


class PeerOutlierConfig(BaseModel):
    """Statistical peer-group outlier detection - flags a submission's
    category spend when it's far above the population baseline (mean/stddev
    computed live across every OTHER employee in the same OE+category via
    AuditStore.category_amount_stats), independent of any flat authored cap.
    No Python defaults (unlike ForensicsConfig above): every value here is a
    genuine business tunable, so it must come from pipeline.yaml or fail
    validation - not silently fall back to a value baked into this class."""

    enabled: bool
    z_score_threshold: float
    min_peer_sample_size: int


class MerchantNetworkConfig(BaseModel):
    """Cross-employee merchant network analysis - distinct from the per-line
    YAML/registry blocklist match (common/blocklist.py, merchant_registry
    table): this looks at how a merchant is used ACROSS employees. No Python
    defaults (same rationale as PeerOutlierConfig): every value here is a
    genuine business tunable."""

    enabled: bool
    # "Rarely seen" merchant suddenly claimed by many distinct employees in a
    # short window - a possible collusion/shell-vendor signal a single-
    # employee check can't see.
    new_merchant_employee_spread_window_days: int
    new_merchant_employee_spread_threshold: int
    new_merchant_max_prior_submissions: int
    # Several different employees' amounts for the same vendor+category
    # clustering just under an applicable cap - cross-employee structuring,
    # distinct from _structuring's single-employee split-transaction check.
    near_cap_clustering_window_days: int
    near_cap_tolerance_pct: float
    near_cap_min_distinct_employees: int
    # Fuzzy name-variant match (stdlib difflib) against merchant_registry rows
    # already marked 'blocked' - catches a watchlisted merchant reappearing
    # under a slightly different spelling.
    fuzzy_match_threshold: float


class VerificationConfig(BaseModel):
    subtotal_tolerance_pct: float
    duplicate_similarity_threshold: float
    duplicate_top_k: int
    duplicate_amount_tolerance_pct: float
    duplicate_require_same_employee: bool
    velocity_window_days: int = 1
    velocity_count_threshold: int = 3
    split_window_days: int = 3
    forensics: ForensicsConfig = Field(default_factory=ForensicsConfig)
    peer_outlier: PeerOutlierConfig
    merchant_network: MerchantNetworkConfig


class RiskConfig(BaseModel):
    weights: dict[str, float]
    auto_approve_cutoff: float
    auto_reject_cutoff: float
    model_version: str


class AssistantConfig(BaseModel):
    """Ask AI provider selection - mirrors extraction.provider's config-as-code
    / Settings-secrets split. "simulated" (default) keeps today's deterministic,
    zero-cost intent-matching engine; "anthropic"/"azure_openai" upgrade to
    real LLM tool-calling reasoning over the same read-only dashboard.queries
    aggregations (adapters/factory.py::build_assistant_responder)."""

    provider: str = "simulated"


class PipelineConfig(BaseModel):
    engine: str = "langgraph"
    node_timeouts: dict[str, float]
    retry: RetryConfig
    extraction: ExtractionConfig
    verification: VerificationConfig
    risk: RiskConfig
    assistant: AssistantConfig = Field(default_factory=AssistantConfig)

    def timeout(self, node: str) -> float:
        return self.node_timeouts[node]


def load_pipeline_config(
    oe_code: Optional[str] = None,
    config_store: "ConfigStore | None" = None,
    path: Path | None = None,
) -> PipelineConfig:
    """`oe_code=None` (the default, and every startup-time/topology call site's
    behavior) loads config/pipeline.yaml unchanged. Passing a real OE code
    deep-merges that OE's override on top - used per-submission by
    VerificationAgent/RiskAgent so an OE's saved threshold/weight overrides
    take effect live, not just in the admin config API's read/write view.

    `config_store=None` (every call site except the live pipeline agents)
    reads the override from the legacy config/oe_overrides/{OE}/pipeline.yaml
    file, if any - kept for callers with no DataLayer in hand (Streamlit
    pages, tests). Passing the DataLayer's ConfigStore reads the DB-backed
    override instead (services/oe_config_service.py's persistence target)."""
    base_path = path or _DEFAULT_PATH
    if oe_code is None:
        raw = yaml.safe_load(base_path.read_text(encoding="utf-8"))
    elif config_store is not None:
        base = yaml.safe_load(base_path.read_text(encoding="utf-8"))
        override = config_store.get_override("pipeline", oe_code)
        raw = deep_merge(base, override) if override else base
    else:
        raw = load_merged_raw(base_path, "pipeline", oe_code)
    return PipelineConfig.model_validate(raw)
