-- User accounts + per-OE config overrides (multi-tenancy). A separate
-- migration from 001_init_sqlite.sql since this is a distinct concern
-- (config, not transactional audit data) - run by ConfigStore.migrate(),
-- not AuditStore.migrate(). Semantic notes match 001_init_sqlite.sql:
--   * TIMESTAMPTZ -> TEXT (ISO-8601 strings, UTC)
--   * now()       -> CURRENT_TIMESTAMP

CREATE TABLE IF NOT EXISTS app_users (
  username      TEXT PRIMARY KEY,
  display_name  TEXT NOT NULL,
  role          TEXT NOT NULL,
  oe_code       TEXT,
  salt          TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

-- One partial override document per (config name, OE) - deep-merged onto the
-- matching base config/{name}.yaml at read time (config/oe_overrides.py::
-- deep_merge), replacing the old config/oe_overrides/{OE}/{name}.yaml files.
CREATE TABLE IF NOT EXISTS oe_config_overrides (
  name       TEXT NOT NULL,   -- 'pipeline' | 'generator' | 'thresholds'
  oe_code    TEXT NOT NULL,
  data       TEXT NOT NULL,   -- JSON-encoded partial override dict
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (name, oe_code)
);

-- The business-rule engine's live ruleset (services/policy_rule_service.py),
-- replacing config/policy_rules.yaml as the source of truth the running
-- pipeline and the Business rules admin UI read/write. See 002_config.sql
-- (Postgres) for the full rationale - identical shape, SQLite-translated
-- (BOOLEAN -> INTEGER).
CREATE TABLE IF NOT EXISTS policy_rules (
  id                  TEXT PRIMARY KEY,
  description         TEXT NOT NULL DEFAULT '',
  type                TEXT NOT NULL,
  enabled             INTEGER NOT NULL DEFAULT 1,
  applies_to_category TEXT,
  applies_to_oe_code  TEXT,
  cap                 TEXT,
  threshold           TEXT,
  min_ratio           NUMERIC,
  max_ratio           NUMERIC,
  max_days            INTEGER,
  window_days         INTEGER,
  updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Singleton row (rule_version is one value for the whole ruleset).
CREATE TABLE IF NOT EXISTS policy_ruleset_meta (
  id           INTEGER PRIMARY KEY CHECK (id = 1),
  rule_version TEXT NOT NULL
);
