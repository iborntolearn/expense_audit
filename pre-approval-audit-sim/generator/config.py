"""Generator configuration model (loads config/generator.yaml)."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from config.settings import REPO_ROOT

_DEFAULT_PATH = REPO_ROOT / "config" / "generator.yaml"


class AnomalyInjection(BaseModel):
    duplicate_rate: float = Field(ge=0, le=1)
    policy_violation_rate: float = Field(ge=0, le=1)
    manipulated_receipt_rate: float = Field(ge=0, le=1)
    # Statistical peer-group outliers - every line in the submission draws its
    # normal category amount as usual, then multiplies it by
    # `peer_outlier_multiplier` so it lands far outside the population this
    # generator itself produces, exercising VerificationAgent._peer_outlier's
    # live-computed baseline against real (if synthetic) peer data.
    peer_outlier_rate: float = Field(ge=0, le=1)
    peer_outlier_multiplier: float = Field(gt=1)


class LinesPerSubmission(BaseModel):
    min: int = Field(ge=1)
    max: int = Field(ge=1)

    @model_validator(mode="after")
    def _check(self) -> "LinesPerSubmission":
        if self.max < self.min:
            raise ValueError("lines_per_submission.max must be >= min")
        return self


class GeneratorConfig(BaseModel):
    volume: int = Field(ge=1)
    seed: int
    anomaly_injection: AnomalyInjection
    currency_mix: list[str] = Field(min_length=1)
    language_mix: list[str] = Field(min_length=1)
    receipt_format_mix: list[str] = Field(min_length=1)
    categories: list[str] = Field(min_length=1)
    lines_per_submission: LinesPerSubmission
    oe_codes: list[str] = Field(min_length=1)

    @property
    def run_id(self) -> str:
        return f"run-{self.seed}-{self.volume}"


def load_generator_config(path: Path | None = None) -> GeneratorConfig:
    raw = yaml.safe_load((path or _DEFAULT_PATH).read_text(encoding="utf-8"))
    return GeneratorConfig.model_validate(raw)
