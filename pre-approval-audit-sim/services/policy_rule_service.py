"""Business-rule engine ruleset - the service-based layer between
integration/routes/admin_config.py and ConfigStore persistence
(data/backends/*.py's policy_rules/policy_ruleset_meta tables).

Replaces config_admin.py's old load_policy/save_policy YAML read-modify-write
with the exact same OE-visibility/merge semantics, but backed by a real table
- concurrent saves are now one atomic transaction (ConfigStore.
replace_policy_ruleset) instead of a race across the whole
config/policy_rules.yaml file, and saves no longer strip that file's
hand-authored comments, since it's no longer written to at all (it remains
the one-time bootstrap seed - see ConfigStore.migrate()).
"""
from __future__ import annotations

from typing import Optional

from common.policy import PolicyRuleSet
from data.interfaces import ConfigStore


class PolicyRuleService:
    def __init__(self, config: ConfigStore):
        self._config = config

    def load(self, oe_code: Optional[str] = None) -> dict:
        """Full ruleset for a global admin (oe_code=None). For an OE-scoped
        admin, only the rules that actually apply to them - company-wide
        rules (applies_to.oe_code is null) plus rules scoped to their own OE
        - so they never see, and can't accidentally touch, another OE's
        rules."""
        data = self._config.get_policy_ruleset()
        if data is None:
            # Shouldn't happen after ConfigStore.migrate()'s bootstrap, but
            # degrade to the YAML reference copy rather than erroring.
            from common.policy import load_policy_rules

            ruleset = load_policy_rules()
            data = {
                "rule_version": ruleset.rule_version,
                "rules": [r.model_dump(mode="json") for r in ruleset.rules],
            }
        if oe_code is None:
            return data
        visible = [
            r for r in data["rules"]
            if (r.get("applies_to") or {}).get("oe_code") in (None, oe_code)
        ]
        return {**data, "rules": visible}

    def save(self, data: dict, oe_code: Optional[str] = None) -> None:
        """Validates the FULL merged result before persisting - same
        guardrail the old config_admin.py::save_policy had."""
        if oe_code is None:
            PolicyRuleSet.model_validate(data)  # raises on invalid
            self._config.replace_policy_ruleset(data["rule_version"], data.get("rules", []))
            return
        # An OE-scoped admin only ever submits the global/own-OE subset
        # load() showed them - reject outright if a rule scoped to a
        # DIFFERENT OE snuck in (defense in depth, not just relying on the
        # UI), then merge their submission back in with every other OE's
        # untouched rules before writing.
        for rule in data.get("rules", []):
            rule_oe = (rule.get("applies_to") or {}).get("oe_code")
            if rule_oe not in (None, oe_code):
                raise ValueError(
                    f"cannot save a rule scoped to OE {rule_oe!r} as an admin scoped to {oe_code!r}"
                )
        current = self._config.get_policy_ruleset() or {"rule_version": data.get("rule_version", ""), "rules": []}
        other_oes_rules = [
            r for r in current["rules"]
            if (r.get("applies_to") or {}).get("oe_code") not in (None, oe_code)
        ]
        # rule_version is whole-ruleset metadata, not per-OE - keep the
        # currently-stored version rather than whatever an OE-scoped admin's
        # submission happens to carry (same behavior the old YAML-based
        # save_policy had: `{**current, "rules": ...}` never let an OE-scoped
        # save change it).
        merged = {"rule_version": current["rule_version"], "rules": other_oes_rules + data.get("rules", [])}
        PolicyRuleSet.model_validate(merged)  # the merged whole-set result must still validate
        self._config.replace_policy_ruleset(merged["rule_version"], merged["rules"])
