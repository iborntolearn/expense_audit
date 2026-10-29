-- User accounts + per-OE config overrides (multi-tenancy). A separate
-- migration from 001_init.sql since this is a distinct concern (config, not
-- transactional audit data) - run by ConfigStore.migrate(), not
-- AuditStore.migrate().

CREATE TABLE IF NOT EXISTS app_users (
  username      TEXT PRIMARY KEY,
  display_name  TEXT NOT NULL,
  role          TEXT NOT NULL,
  oe_code       TEXT,
  salt          TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at    TIMESTAMPTZ DEFAULT now(),
  updated_at    TIMESTAMPTZ DEFAULT now()
);

-- One partial override document per (config name, OE) - deep-merged onto the
-- matching base config/{name}.yaml at read time (config/oe_overrides.py::
-- deep_merge), replacing the old config/oe_overrides/{OE}/{name}.yaml files.
CREATE TABLE IF NOT EXISTS oe_config_overrides (
  name       TEXT NOT NULL,   -- 'pipeline' | 'generator' | 'thresholds'
  oe_code    TEXT NOT NULL,
  data       TEXT NOT NULL,   -- JSON-encoded partial override dict
  updated_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (name, oe_code)
);

-- The business-rule engine's live ruleset (services/policy_rule_service.py),
-- replacing config/policy_rules.yaml as the source of truth the running
-- pipeline and the Business rules admin UI read/write. That YAML file still
-- exists as the one-time bootstrap seed below (mirrors app_users' own
-- bootstrap-from-config/users.yaml pattern) and as a reference/rollback copy
-- - it is no longer written to, so it stops losing its hand-authored
-- comments on every admin save (yaml.safe_dump used to strip them), and
-- saves are now one real transaction instead of a read-modify-write race
-- across the whole file.
CREATE TABLE IF NOT EXISTS policy_rules (
  id                  TEXT PRIMARY KEY,
  description         TEXT NOT NULL DEFAULT '',
  type                TEXT NOT NULL,
  enabled             BOOLEAN NOT NULL DEFAULT true,
  applies_to_category TEXT,
  applies_to_oe_code  TEXT,
  cap                 TEXT,     -- JSON dict {currency: amount}
  threshold           TEXT,     -- JSON dict {currency: amount}
  min_ratio           NUMERIC,
  max_ratio           NUMERIC,
  max_days            INTEGER,
  window_days         INTEGER,
  updated_at          TIMESTAMPTZ DEFAULT now()
);

-- Singleton row (rule_version is one value for the whole ruleset, not
-- per-rule) - id is always 1, enforced by the CHECK.
CREATE TABLE IF NOT EXISTS policy_ruleset_meta (
  id           INTEGER PRIMARY KEY CHECK (id = 1),
  rule_version TEXT NOT NULL
);
