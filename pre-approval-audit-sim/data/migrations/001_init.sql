-- Postgres reference schema for the decision/audit store.
-- Verbatim from Detailed Technical Design v0.2, Section 4 & 4.1.
-- Every table carries the rule_version and/or model_version active at decision
-- time, per the auditability requirement in the solution design.

CREATE TABLE IF NOT EXISTS submissions (
  submission_id      TEXT PRIMARY KEY,
  source_system      TEXT NOT NULL,   -- 'concur' | 'simulation_harness'
  source_system_ref  TEXT NOT NULL,
  oe_code            TEXT NOT NULL,
  employee_id        TEXT NOT NULL,
  cost_center        TEXT,
  currency           CHAR(3) NOT NULL,
  submitted_at       TIMESTAMPTZ NOT NULL,
  is_synthetic       BOOLEAN NOT NULL DEFAULT false,
  created_at         TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS extracted_line_items (
  line_item_id   TEXT PRIMARY KEY,
  submission_id  TEXT REFERENCES submissions,
  vendor         TEXT,
  txn_date       DATE,
  amount         NUMERIC(12,2),
  tax            NUMERIC(12,2),
  category       TEXT,
  confidence     NUMERIC(4,3),
  invoice_number TEXT,
  extracted_at   TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE extracted_line_items ADD COLUMN IF NOT EXISTS invoice_number TEXT;

CREATE INDEX IF NOT EXISTS extracted_line_items_vendor_invoice_idx
  ON extracted_line_items (vendor, invoice_number)
  WHERE invoice_number IS NOT NULL;

CREATE TABLE IF NOT EXISTS verification_results (
  submission_id         TEXT REFERENCES submissions,
  authenticity_flags    TEXT[],
  duplicate_match_ids   TEXT[],
  subtotal_variance_pct NUMERIC(5,2),
  subtotal_entered_total NUMERIC(12,2),
  subtotal_receipt_total NUMERIC(12,2),
  velocity_flags        TEXT[],  -- BR-TE-AU-19
  split_transaction_flags TEXT[],  -- BR-TE-AU-19
  merchant_validation   TEXT,
  merchant_flags        TEXT[],  -- BR-TE-AU-03
  compliance_flags      TEXT[],  -- BR-TE-AU-04
  peer_outlier_flags    TEXT[],  -- statistical peer-group amount outliers
  merchant_network_flags TEXT[], -- cross-employee merchant network analysis
  duplicate_match_details TEXT,  -- JSON [{submission_id, similarity, match_type}] - richer sibling of duplicate_match_ids, additive
  evaluated_at          TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (submission_id)
);

-- ADD COLUMN IF NOT EXISTS is idempotent on Postgres (unlike SQLite) - safe
-- to also run this against an already-existing table from before these
-- columns existed.
ALTER TABLE verification_results ADD COLUMN IF NOT EXISTS subtotal_entered_total NUMERIC(12,2);
ALTER TABLE verification_results ADD COLUMN IF NOT EXISTS subtotal_receipt_total NUMERIC(12,2);
ALTER TABLE verification_results ADD COLUMN IF NOT EXISTS velocity_flags TEXT[];
ALTER TABLE verification_results ADD COLUMN IF NOT EXISTS split_transaction_flags TEXT[];
ALTER TABLE verification_results ADD COLUMN IF NOT EXISTS merchant_flags TEXT[];
ALTER TABLE verification_results ADD COLUMN IF NOT EXISTS compliance_flags TEXT[];
ALTER TABLE verification_results ADD COLUMN IF NOT EXISTS peer_outlier_flags TEXT[];
ALTER TABLE verification_results ADD COLUMN IF NOT EXISTS duplicate_match_details TEXT;
ALTER TABLE verification_results ADD COLUMN IF NOT EXISTS merchant_network_flags TEXT[];

CREATE TABLE IF NOT EXISTS policy_evaluations (
  submission_id  TEXT REFERENCES submissions,
  rule_id        TEXT NOT NULL,
  rule_version   TEXT NOT NULL,
  passed         BOOLEAN NOT NULL,
  evaluated_at   TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (submission_id, rule_id)
);

CREATE TABLE IF NOT EXISTS risk_decisions (
  submission_id     TEXT REFERENCES submissions,
  risk_score        NUMERIC(4,3) NOT NULL,
  routing_decision  TEXT NOT NULL,
  model_version     TEXT NOT NULL,
  explanation       TEXT,
  decided_at        TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (submission_id)
);

CREATE TABLE IF NOT EXISTS reviewer_actions (
  submission_id  TEXT REFERENCES submissions,
  reviewer_id    TEXT NOT NULL,
  final_decision TEXT NOT NULL,
  feedback_notes TEXT,
  actioned_at    TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (submission_id)
);

-- Case-management layer above the exception engine (BR-TE-AU-13). Independent
-- of reviewer_actions/final_decision - a case can move through
-- open/in_review/awaiting_traveller/resolved/claw_back_pending at any point,
-- before or after (or without ever reaching) a final approve/reject.
CREATE TABLE IF NOT EXISTS case_status (
  submission_id    TEXT REFERENCES submissions,
  status           TEXT NOT NULL DEFAULT 'open',
  recovered_amount NUMERIC(12,2),
  updated_by       TEXT,
  updated_at       TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (submission_id)
);

-- Receipt evidence pointers (blob URLs) so the reviewer UI can retrieve
-- evidence from the system of record rather than generator scratch files.
CREATE TABLE IF NOT EXISTS receipt_refs (
  submission_id TEXT REFERENCES submissions,
  line_id       TEXT NOT NULL,
  receipt_url   TEXT NOT NULL,
  PRIMARY KEY (submission_id, line_id)
);

-- Employee-submitted report line business fields (category + entered amount),
-- persisted so the business dashboard can report spend by category/OE etc.
CREATE TABLE IF NOT EXISTS report_lines (
  submission_id  TEXT REFERENCES submissions,
  line_id        TEXT NOT NULL,
  category       TEXT,
  entered_amount NUMERIC(12,2),
  currency       CHAR(3),
  PRIMARY KEY (submission_id, line_id)
);

-- Per-node pipeline execution trace (observability - "how did end-to-end
-- processing work for this submission?"). One row per node call: timing,
-- retry attempts, pass/fail, and short human-readable input/output summaries.
-- Mirrors the SOA Layout Agent app's `steps` table, adapted to our unit of
-- work being a submission (not a whole-file run).
CREATE TABLE IF NOT EXISTS pipeline_logs (
  id             BIGSERIAL PRIMARY KEY,
  submission_id  TEXT REFERENCES submissions,
  node           TEXT NOT NULL,
  ok             BOOLEAN NOT NULL,
  attempts       INTEGER NOT NULL,
  latency_ms     NUMERIC(10,2) NOT NULL,
  input_summary  TEXT,
  output_summary TEXT,
  error_message  TEXT,
  logged_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pipeline_logs_submission_idx ON pipeline_logs(submission_id);

-- Vector store schema (duplicate detection) - Tech Design 4.1
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS receipt_embeddings (
  line_item_id  TEXT PRIMARY KEY REFERENCES extracted_line_items,
  submission_id TEXT NOT NULL,
  employee_id   TEXT NOT NULL,
  embedding     VECTOR(1536) NOT NULL,
  amount        NUMERIC(12,2),
  txn_date      DATE,
  created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS receipt_embeddings_ivfflat
  ON receipt_embeddings
  USING ivfflat (embedding vector_cosine_ops);

-- Merchant registry (BR-TE-AU-03 successor) - a real per-merchant table
-- replacing the flat merchant_blocklist.yaml as the live source of truth.
-- Bootstrapped from that YAML's entries exactly once (AuditStore.
-- bootstrap_merchant_registry, mirrors ConfigStore.bootstrap_policy_ruleset's
-- idempotency), then updated by the pipeline (first/last-seen tracking on
-- every submission) and by cross-employee network analysis (auto risk-tier),
-- with an admin able to override either via System Admin -> Watchlist.
CREATE TABLE IF NOT EXISTS merchant_registry (
  merchant_key      TEXT PRIMARY KEY,       -- normalized: lower(trim(name))
  display_name      TEXT NOT NULL,
  status            TEXT NOT NULL DEFAULT 'clear',  -- clear | watch | blocked
  risk_tier         TEXT NOT NULL DEFAULT 'low',     -- low | medium | high
  source            TEXT NOT NULL DEFAULT 'auto',    -- bootstrap_yaml | auto | admin_override
  blocklist_type    TEXT,                   -- sanctioned | pep | NULL
  reason            TEXT,
  first_seen_at     TIMESTAMPTZ DEFAULT now(),
  last_seen_at      TIMESTAMPTZ DEFAULT now(),
  submission_count  INTEGER NOT NULL DEFAULT 0,
  updated_by        TEXT,
  updated_at        TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS merchant_registry_status_idx ON merchant_registry(status);
