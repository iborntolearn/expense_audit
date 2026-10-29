"""Policy rules DB-table migration: ConfigStore bootstrap/CRUD +
PolicyRuleService (services/policy_rule_service.py). Mirrors the
oe_config_overrides/app_users test conventions - sqlite_local backend via the
data_layer fixture, which already runs migrate() (and therefore the one-time
YAML bootstrap) before each test.
"""
from __future__ import annotations

import pytest

from common.policy import load_policy_rules
from services.policy_rule_service import PolicyRuleService


def test_bootstrap_seeds_from_yaml(data_layer):
    yaml_rules = load_policy_rules()
    stored = data_layer.config.get_policy_ruleset()
    assert stored is not None
    assert stored["rule_version"] == yaml_rules.rule_version
    assert len(stored["rules"]) == len(yaml_rules.rules)
    assert {r["id"] for r in stored["rules"]} == {r.id for r in yaml_rules.rules}


def test_bootstrap_is_only_ever_seeded_once(data_layer):
    # A second migrate() (e.g. app restart) must not re-sync from the YAML -
    # a rule deleted via the admin UI should stay gone.
    before = data_layer.config.get_policy_ruleset()
    surviving_id = before["rules"][0]["id"]
    remaining = [r for r in before["rules"] if r["id"] != surviving_id]
    data_layer.config.replace_policy_ruleset(before["rule_version"], remaining)

    data_layer.migrate()

    after = data_layer.config.get_policy_ruleset()
    assert surviving_id not in {r["id"] for r in after["rules"]}
    assert len(after["rules"]) == len(remaining)


def test_service_global_load_matches_store(data_layer):
    svc = PolicyRuleService(data_layer.config)
    loaded = svc.load()
    assert loaded == data_layer.config.get_policy_ruleset()


def test_service_global_save_roundtrip(data_layer):
    svc = PolicyRuleService(data_layer.config)
    data = svc.load()
    data["rules"][0]["enabled"] = not data["rules"][0]["enabled"]
    new_version = data["rule_version"] + "-edited"
    data["rule_version"] = new_version

    svc.save(data)

    reloaded = svc.load()
    assert reloaded["rule_version"] == new_version
    assert reloaded["rules"][0]["enabled"] == data["rules"][0]["enabled"]


def test_service_global_save_rejects_invalid(data_layer):
    svc = PolicyRuleService(data_layer.config)
    with pytest.raises(Exception):
        svc.save({"rule_version": "x", "rules": [{"id": "bad", "type": "not_a_real_type"}]})


def test_oe_scoped_load_hides_other_oes_rules(data_layer):
    svc = PolicyRuleService(data_layer.config)
    data = svc.load()
    data["rules"].append({
        "id": "TEST-DE-ONLY", "description": "", "type": "amount_cap", "enabled": True,
        "applies_to": {"category": None, "oe_code": "DE"},
        "cap": {"EUR": 100.0}, "threshold": {}, "min_ratio": None, "max_ratio": None,
        "max_days": None, "window_days": None,
    })
    data["rules"].append({
        "id": "TEST-US-ONLY", "description": "", "type": "amount_cap", "enabled": True,
        "applies_to": {"category": None, "oe_code": "US"},
        "cap": {"USD": 100.0}, "threshold": {}, "min_ratio": None, "max_ratio": None,
        "max_days": None, "window_days": None,
    })
    data_layer.config.replace_policy_ruleset(data["rule_version"], data["rules"])

    de_view = svc.load(oe_code="DE")
    de_ids = {r["id"] for r in de_view["rules"]}
    assert "TEST-DE-ONLY" in de_ids
    assert "TEST-US-ONLY" not in de_ids
    # global (oe_code=None) rules from the YAML bootstrap remain visible too
    global_rules = [r for r in data["rules"] if (r.get("applies_to") or {}).get("oe_code") is None]
    assert global_rules  # sanity: the fixture data actually has global rules
    assert all(r["id"] in de_ids for r in global_rules)


def test_oe_scoped_save_merges_without_touching_other_oes(data_layer):
    svc = PolicyRuleService(data_layer.config)
    full = svc.load()
    full["rules"].append({
        "id": "TEST-DE-ONLY", "description": "", "type": "amount_cap", "enabled": True,
        "applies_to": {"category": None, "oe_code": "DE"},
        "cap": {"EUR": 100.0}, "threshold": {}, "min_ratio": None, "max_ratio": None,
        "max_days": None, "window_days": None,
    })
    full["rules"].append({
        "id": "TEST-US-ONLY", "description": "", "type": "amount_cap", "enabled": True,
        "applies_to": {"category": None, "oe_code": "US"},
        "cap": {"USD": 100.0}, "threshold": {}, "min_ratio": None, "max_ratio": None,
        "max_days": None, "window_days": None,
    })
    data_layer.config.replace_policy_ruleset(full["rule_version"], full["rules"])

    de_view = svc.load(oe_code="DE")
    for r in de_view["rules"]:
        if r["id"] == "TEST-DE-ONLY":
            r["cap"] = {"EUR": 250.0}
    svc.save(de_view, oe_code="DE")

    whole = data_layer.config.get_policy_ruleset()
    by_id = {r["id"]: r for r in whole["rules"]}
    assert by_id["TEST-DE-ONLY"]["cap"] == {"EUR": 250.0}
    assert by_id["TEST-US-ONLY"]["cap"] == {"USD": 100.0}  # untouched


def test_oe_scoped_save_rejects_foreign_oe_rule(data_layer):
    svc = PolicyRuleService(data_layer.config)
    data = svc.load(oe_code="DE")
    data["rules"].append({
        "id": "TEST-SNEAKY", "description": "", "type": "amount_cap", "enabled": True,
        "applies_to": {"category": None, "oe_code": "US"},
        "cap": {"USD": 1.0}, "threshold": {}, "min_ratio": None, "max_ratio": None,
        "max_days": None, "window_days": None,
    })
    with pytest.raises(ValueError):
        svc.save(data, oe_code="DE")


def test_oe_scoped_save_never_changes_rule_version(data_layer):
    svc = PolicyRuleService(data_layer.config)
    original_version = data_layer.config.get_policy_ruleset()["rule_version"]

    de_view = svc.load(oe_code="DE")
    de_view["rule_version"] = "some-oe-scoped-admin-typo"
    svc.save(de_view, oe_code="DE")

    assert data_layer.config.get_policy_ruleset()["rule_version"] == original_version


def test_replace_is_atomic_full_replace_not_merge(data_layer):
    data_layer.config.replace_policy_ruleset("v-atomic-test", [
        {
            "id": "ONLY-RULE", "description": "", "type": "amount_cap", "enabled": True,
            "applies_to": {"category": None, "oe_code": None},
            "cap": {"EUR": 1.0}, "threshold": {}, "min_ratio": None, "max_ratio": None,
            "max_days": None, "window_days": None,
        }
    ])
    result = data_layer.config.get_policy_ruleset()
    assert result["rule_version"] == "v-atomic-test"
    assert [r["id"] for r in result["rules"]] == ["ONLY-RULE"]
