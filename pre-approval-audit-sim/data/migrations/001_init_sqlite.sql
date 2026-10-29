-- SQLite-translated equivalent of 001_init.sql for the sqlite_local dev
-- fallback (no Docker / Postgres required). Semantic notes:
--   * TIMESTAMPTZ  -> TEXT (ISO-8601 strings, UTC)
--   * NUMERIC(p,s) -> NUMERIC (SQLite affinity; precision enforced in app layer)
--   * TEXT[]       -> TEXT holding a JSON array
--   * BOOLEAN      -> INTEGER (0/1)
--   * now()        -> CURRENT_TIMESTAMP
--   * VECTOR(1536) -> embedding stored as JSON in receipt_embeddings; similarity
--                     search is performed in Python (NumPy cosine), see
--                     data/backends/sqlite_store.py LocalVectorIndex.

CREATE TABLE IF NOT EXISTS submissions (
  submission_id      TEXT PRIMARY KEY,
  source_system      TEXT NOT NULL,
  source_system_ref  TEXT NOT NULL,
  oe_code            TEXT NOT NULL,
  employee_id        TEXT NOT NULL,
  cost_center        TEXT,
  currency           TEXT NOT NULL,
  submitted_at       TEXT NOT NULL,
  is_synthetic       INTEGER NOT NULL DEFAULT 0,
  created_at         TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS extracted_line_items (
  line_item_id   TEXT PRIMARY KEY,
  submission_id  TEXT REFERENCES submissions(submission_id),
  vendor         TEXT,
  txn_date       TEXT,
  amount         NUMERIC,
  tax            NUMERIC,
  category       TEXT,
  confidence     NUMERIC,
  invoice_number TEXT,
  extracted_at   TEXT DEFAULT CURRENT_TIMESTAMP
);

-- NOTE: the (vendor, invoice_number) index is NOT created here. On a
-- pre-existing database (invoice_number added after the table already
-- existed), this whole script's CREATE TABLE IF NOT EXISTS above is a no-op,
-- so a CREATE INDEX referencing invoice_number in this same script would run
-- BEFORE SqliteAuditStore._add_missing_columns() has a chance to add that
-- column - "no such column: invoice_number". The index is created in Python
-- instead, after _add_missing_columns() runs - see migrate().

CREATE TABLE IF NOT EXISTS verification_results (
  submission_id         TEXT PRIMARY KEY REFERENCES submissions(submission_id),
  authenticity_flags    TEXT,   -- JSON array
  duplicate_match_ids   TEXT,   -- JSON array
  subtotal_variance_pct NUMERIC,
  subtotal_entered_total  NUMERIC,  -- sum of employee-entered amounts
  subtotal_receipt_total  NUMERIC,  -- sum of extracted amount+tax
  velocity_flags        TEXT,   -- JSON array (BR-TE-AU-19)
  split_transaction_flags TEXT, -- JSON array (BR-TE-AU-19)
  merchant_validation   TEXT,
  merchant_flags        TEXT,   -- JSON array (BR-TE-AU-03)
  compliance_flags      TEXT,   -- JSON array (BR-TE-AU-04)
  peer_outlier_flags    TEXT,   -- JSON array (statistical peer-group amount outliers)
  merchant_network_flags TEXT, -- JSON array (cross-employee merchant network analysis)
  duplicate_match_details TEXT, -- JSON [{submission_id, similarity, match_type}] - richer sibling of duplicate_match_ids, additive
  evaluated_at          TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS policy_evaluations (
  submission_id  TEXT REFERENCES submissions(submission_id),
  rule_id        TEXT NOT NULL,
  rule_version   TEXT NOT NULL,
  passed         INTEGER NOT NULL,
  evaluated_at   TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (submission_id, rule_id)
);

CREATE TABLE IF NOT EXISTS risk_decisions (
  submission_id     TEXT PRIMARY KEY REFERENCES submissions(submission_id),
  risk_score        NUMERIC NOT NULL,
  routing_decision  TEXT NOT NULL,
  model_version     TEXT NOT NULL,
  explanation       TEXT,
  decided_at        TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reviewer_actions (
  submission_id  TEXT PRIMARY KEY REFERENCES submissions(submission_id),
  reviewer_id    TEXT NOT NULL,
  final_decision TEXT NOT NULL,
  feedback_notes TEXT,
  actioned_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Case-management layer above the exception engine (BR-TE-AU-13). Independent
-- of reviewer_actions/final_decision - a case can move through
-- open/in_review/awaiting_traveller/resolved/claw_back_pending at any point,
-- before or after (or without ever reaching) a final approve/reject.
CREATE TABLE IF NOT EXISTS case_status (
  submission_id    TEXT PRIMARY KEY REFERENCES submissions(submission_id),
  status           TEXT NOT NULL DEFAULT 'open',
  recovered_amount NUMERIC,
  updated_by       TEXT,
  updated_at       TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS receipt_refs (
  submission_id TEXT REFERENCES submissions(submission_id),
  line_id       TEXT NOT NULL,
  receipt_url   TEXT NOT NULL,
  PRIMARY KEY (submission_id, line_id)
);

CREATE TABLE IF NOT EXISTS report_lines (
  submission_id  TEXT REFERENCES submissions(submission_id),
  line_id        TEXT NOT NULL,
  category       TEXT,
  entered_amount NUMERIC,
  currency       TEXT,
  PRIMARY KEY (submission_id, line_id)
);

-- Per-node pipeline execution trace (observability - "how did end-to-end
-- processing work for this submission?"). One row per node call: timing,
-- retry attempts, pass/fail, and short human-readable input/output summaries.
-- Mirrors the SOA Layout Agent app's `steps` table, adapted to our unit of
-- work being a submission (not a whole-file run).
CREATE TABLE IF NOT EXISTS pipeline_logs (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  submission_id  TEXT REFERENCES submissions(submission_id),
  node           TEXT NOT NULL,
  ok             INTEGER NOT NULL,
  attempts       INTEGER NOT NULL,
  latency_ms     NUMERIC NOT NULL,
  input_summary  TEXT,
  output_summary TEXT,
  error_message  TEXT,
  logged_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS pipeline_logs_submission_idx ON pipeline_logs(submission_id);

CREATE TABLE IF NOT EXISTS receipt_embeddings (
  line_item_id  TEXT PRIMARY KEY REFERENCES extracted_line_items(line_item_id),
  submission_id TEXT NOT NULL,
  employee_id   TEXT NOT NULL,
  embedding     TEXT NOT NULL,   -- JSON array of floats (length = EMBEDDING_DIM)
  amount        NUMERIC,
  txn_date      TEXT,
  created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Merchant registry (BR-TE-AU-03 successor) - see 001_init.sql for the full
-- rationale comment.
CREATE TABLE IF NOT EXISTS merchant_registry (
  merchant_key      TEXT PRIMARY KEY,
  display_name      TEXT NOT NULL,
  status            TEXT NOT NULL DEFAULT 'clear',
  risk_tier         TEXT NOT NULL DEFAULT 'low',
  source            TEXT NOT NULL DEFAULT 'auto',
  blocklist_type    TEXT,
  reason            TEXT,
  first_seen_at     TEXT DEFAULT CURRENT_TIMESTAMP,
  last_seen_at      TEXT DEFAULT CURRENT_TIMESTAMP,
  submission_count  INTEGER NOT NULL DEFAULT 0,
  updated_by        TEXT,
  updated_at        TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS merchant_registry_status_idx ON merchant_registry(status);
