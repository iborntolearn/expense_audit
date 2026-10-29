"""Auditor-to-traveller email template library (BR-TE-AU-13).

SIMULATED - renders a subject/body for the reviewer to copy/send through
their own mail client; there is no real SMTP integration in this build (same
treatment as every other 3rd-party integration - Solution Design 10).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from config.settings import REPO_ROOT

_DEFAULT_PATH = REPO_ROOT / "config" / "email_templates.yaml"


class EmailTemplate(BaseModel):
    name: str
    subject: str
    body: str

    def render(self, **kwargs) -> tuple[str, str]:
        """Returns (subject, body) with {placeholders} filled in. Any
        placeholder not supplied is left as-is rather than raising, so a
        template with an unexpected field never crashes the page."""
        class _Default(dict):
            def __missing__(self, key):
                return "{" + key + "}"

        ctx = _Default(**kwargs)
        return self.subject.format_map(ctx), self.body.format_map(ctx)


class EmailTemplateLibrary(BaseModel):
    templates: list[EmailTemplate] = Field(default_factory=list)

    def get(self, name: str) -> Optional[EmailTemplate]:
        return next((t for t in self.templates if t.name == name), None)


def load_email_templates(path: Path = _DEFAULT_PATH) -> EmailTemplateLibrary:
    if not path.exists():
        return EmailTemplateLibrary(templates=[])
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return EmailTemplateLibrary.model_validate(raw)
