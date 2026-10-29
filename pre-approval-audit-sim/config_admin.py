"""Config administration for the Settings page.

Loads/validates/saves the YAML config files that drive the pipeline, plus a
small .env updater for model selection and the (optional) API key. Every save is
validated by constructing the matching pydantic model BEFORE writing, so the
Settings UI can never persist a config the pipeline would reject at startup.

Note: saves use yaml.safe_dump and therefore drop file comments. The config
files remain valid and complete; only inline documentation is lost on UI edit.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from config.settings import REPO_ROOT
from generator.config import GeneratorConfig
from pipeline.config import PipelineConfig
from common.blocklist import MerchantBlocklist
from common.email_templates import EmailTemplateLibrary

PIPELINE_YAML = REPO_ROOT / "config" / "pipeline.yaml"
THRESHOLDS_YAML = REPO_ROOT / "config" / "thresholds.yaml"
POLICY_YAML = REPO_ROOT / "config" / "policy_rules.yaml"
GENERATOR_YAML = REPO_ROOT / "config" / "generator.yaml"
USERS_YAML = REPO_ROOT / "config" / "users.yaml"
BLOCKLIST_YAML = REPO_ROOT / "config" / "merchant_blocklist.yaml"
EMAIL_TEMPLATES_YAML = REPO_ROOT / "config" / "email_templates.yaml"
ENV_FILE = REPO_ROOT / ".env"


def load_raw(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
                    encoding="utf-8")


def _oe_config_service():
    # Imported lazily, and only ever called from the oe_code-is-not-None
    # branch below, so an oe_code=None caller (every Streamlit call site
    # today) never opens a ConfigStore connection at all.
    from data.factory import get_default_config_store
    from services.oe_config_service import OeConfigService

    return OeConfigService(get_default_config_store())


# --- validated saves ---------------------------------------------------------
def load_pipeline(oe_code: Optional[str] = None) -> dict:
    if oe_code is None:
        return load_raw(PIPELINE_YAML)
    return _oe_config_service().load_merged(PIPELINE_YAML, "pipeline", oe_code)


def save_pipeline(data: dict, oe_code: Optional[str] = None) -> None:
    PipelineConfig.model_validate(data)  # the merged result must be valid, whichever scope
    if oe_code is None:
        _write(PIPELINE_YAML, data)
    else:
        _oe_config_service().save("pipeline", oe_code, data)


def load_generator(oe_code: Optional[str] = None) -> dict:
    if oe_code is None:
        return load_raw(GENERATOR_YAML)
    return _oe_config_service().load_merged(GENERATOR_YAML, "generator", oe_code)


def save_generator(data: dict, oe_code: Optional[str] = None) -> None:
    GeneratorConfig.model_validate(data)
    if oe_code is None:
        _write(GENERATOR_YAML, data)
    else:
        _oe_config_service().save("generator", oe_code, data)


# NOTE: policy rules are no longer read/written here - see
# services/policy_rule_service.py::PolicyRuleService, which implements the
# exact same OE-visibility/merge semantics that used to live in this module's
# load_policy/save_policy, but persists to the policy_rules/
# policy_ruleset_meta DB tables instead of read-modify-writing the whole
# config/policy_rules.yaml file. POLICY_YAML remains below only as the
# one-time bootstrap seed path (ConfigStore.migrate()) and reference copy.


def load_thresholds(oe_code: Optional[str] = None) -> dict:
    if oe_code is None:
        return load_raw(THRESHOLDS_YAML)
    return _oe_config_service().load_merged(THRESHOLDS_YAML, "thresholds", oe_code)


def validate_thresholds(data: dict) -> None:
    # light validation: required sections + numeric leaves
    for section in ("extraction", "duplicate_detection", "latency", "confidence"):
        if section not in data:
            raise ValueError(f"thresholds missing section: {section}")


def save_thresholds(data: dict, oe_code: Optional[str] = None) -> None:
    validate_thresholds(data)
    if oe_code is None:
        _write(THRESHOLDS_YAML, data)
    else:
        _oe_config_service().save("thresholds", oe_code, data)


# --- .env updates ------------------------------------------------------------
def update_env(updates: dict[str, str]) -> None:
    """Insert/replace KEY=value lines in .env (created from example if missing)."""
    if not ENV_FILE.exists():
        example = REPO_ROOT / ".env.example"
        ENV_FILE.write_text(example.read_text(encoding="utf-8") if example.exists() else "",
                            encoding="utf-8")
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    keys = set(updates)
    out = []
    seen = set()
    for line in lines:
        k = line.split("=", 1)[0].strip() if "=" in line and not line.strip().startswith("#") else None
        if k in keys:
            out.append(f"{k}={updates[k]}")
            seen.add(k)
        else:
            out.append(line)
    for k in keys - seen:
        out.append(f"{k}={updates[k]}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")


# --- users (DB-backed via ConfigStore/UserService - config/users.yaml is now
# only the one-time bootstrap source, see data/factory.py::
# get_default_config_store) ---------------------------------------------------
def _user_service():
    from data.factory import get_default_config_store
    from services.user_service import UserService

    return UserService(get_default_config_store())


def load_users_raw() -> dict:
    """Kept as a dict-of-dicts (not UserRecord objects) for Streamlit
    compat - app_pages/system_admin.py indexes these by string key."""
    return {"users": [
        {
            "username": u.username, "display_name": u.display_name, "role": u.role.value,
            "oe_code": u.oe_code, "salt": u.salt, "password_hash": u.password_hash,
        }
        for u in _user_service().list_users()
    ]}


def add_user(
    username: str, display_name: str, role: str, password: str,
    oe_code: Optional[str] = None,
) -> None:
    _user_service().add_user(username, display_name, role, password, oe_code=oe_code)


def reset_password(username: str, new_password: str) -> None:
    _user_service().reset_password(username, new_password)


def set_user_role(username: str, role: str) -> None:
    _user_service().set_role(username, role)


def set_user_oe(username: str, oe_code: Optional[str]) -> None:
    """Assign (or clear, via oe_code=None) a user's OE scope. None is only a
    meaningful choice for role=admin - it makes them a global super-admin
    spanning every OE; every other role should always carry a real OE code."""
    _user_service().set_oe(username, oe_code)


def delete_user(username: str) -> None:
    _user_service().delete_user(username)


# --- merchant watchlist (config/merchant_blocklist.yaml) ---------------------
def load_blocklist_raw() -> dict:
    if not BLOCKLIST_YAML.exists():
        return {"entries": []}
    return yaml.safe_load(BLOCKLIST_YAML.read_text(encoding="utf-8")) or {"entries": []}


def _save_blocklist(data: dict) -> None:
    MerchantBlocklist.model_validate(data)  # raises on invalid
    _write(BLOCKLIST_YAML, data)


def add_blocklist_entry(name: str, entry_type: str, reason: str) -> None:
    data = load_blocklist_raw()
    if any(e["name"].lower() == name.lower() for e in data["entries"]):
        raise ValueError(f"watchlist entry {name!r} already exists")
    data["entries"].append({"name": name, "type": entry_type, "reason": reason})
    _save_blocklist(data)


def delete_blocklist_entry(name: str) -> None:
    data = load_blocklist_raw()
    remaining = [e for e in data["entries"] if e["name"] != name]
    if len(remaining) == len(data["entries"]):
        raise ValueError(f"watchlist entry {name!r} not found")
    data["entries"] = remaining
    _save_blocklist(data)


# --- email templates (config/email_templates.yaml) ---------------------------
def load_email_templates_raw() -> dict:
    if not EMAIL_TEMPLATES_YAML.exists():
        return {"templates": []}
    return yaml.safe_load(EMAIL_TEMPLATES_YAML.read_text(encoding="utf-8")) or {"templates": []}


def save_email_template_body(name: str, subject: str, body: str) -> None:
    data = load_email_templates_raw()
    for t in data["templates"]:
        if t["name"] == name:
            t["subject"], t["body"] = subject, body
            EmailTemplateLibrary.model_validate(data)  # raises on invalid
            _write(EMAIL_TEMPLATES_YAML, data)
            return
    raise ValueError(f"template {name!r} not found")


def env_value(key: str) -> str:
    if not ENV_FILE.exists():
        return ""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == key:
            return v.strip()
    return ""
