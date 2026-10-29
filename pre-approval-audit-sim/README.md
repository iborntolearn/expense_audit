# Veriflow — Pre-Approval Expense Audit (Simulation Mode)

Custom agentic AI application that audits 100% of T&E expense submissions
**before approval**. This repository is scope-locked to **Phase 0 — simulation
mode** (synthetic data, mock T&E system, no live integration, no real employee
data), per the Claude Code Build Brief in `docs/`.

> The three reference documents in `docs/` (Solution Design, Detailed Technical
> Design, Feasibility Spike Plan) are **context, not instructions**. The Build
> Brief is the execution artifact.

## Status

| Phase | Milestones | State |
|-------|-----------|-------|
| **P0 — Foundation** | M0 scaffolding, M1 data model | ✅ complete |
| **P1 — Data & backbone** | M2 generator, M3 integration | ✅ complete |
| **P2 — Agent pipeline** | M4–M7 | ✅ complete |
| **P3 — Orchestration** | M8 | ✅ complete |
| **P4 — Human review** | M9 | ✅ complete |
| **P5 — Reporting** | M10 | ✅ complete |

**All 11 milestones (0–10) complete** — the Build Brief's definition of done is met.

## Architecture (modular, microservice-shaped)

```
generator/     synthetic submissions + receipts + ground truth   (P1)
integration/   FastAPI webhook receiver, SIMULATION_MODE, /health
pipeline/      LangGraph nodes: extraction → verification → policy → risk (P2/P3)
data/          storage interfaces + backends (postgres | sqlite_local)
review_ui/     Review-workflow service (resume/decision logic) used by the REST API (P4)
tests/         per-agent unit tests + accuracy scoring harness
config/        settings, policy rules, thresholds — no literals in code
```

### Observability & logging (ported from the SOA Layout Agent app)

Every node call (extraction/verification/policy/risk_scoring) is persisted to
`pipeline_logs` — timing, retry attempts, pass/fail, and a short human-readable
input/output summary — mirroring SOA's per-run `steps` table, adapted to our
per-submission unit of work. This answers "how did end-to-end processing
actually work?" at two levels:
- **Per submission**: Audit → Expense reports → select a row → **🪵 Pipeline
  log** tab shows the full node-by-node trace (icon, duration, attempts,
  input/output summary, error detail if any) — the direct analog of SOA's Log
  Viewer.
- **Aggregate**: Insights → Reports & exports → **Observability** section —
  steps logged, submissions traced, node error rate, avg latency by node,
  outcomes-by-node chart, raw CSV export — the analog of SOA's Observability +
  Processing Statistics tabs.
- The sidebar also shows the most recently processed submission (node +
  latency), mirroring SOA's "active run" sidebar strip.

Wiring: `pipeline/runtime.py::run_node_logged()` wraps `run_node()` and writes
the trace row after every node call, in both `SequentialPipeline` and
`LangGraphPipeline`. `pipeline/summaries.py` builds the short output summaries
shared by both engines.

### Live mode is hardcoded off, not just config-off

`SIMULATION_MODE=live` in `.env` **cannot, by itself, change system behavior**.
Live behavior requires three gates (a real T&E connector, real-data
governance/legal sign-off, completed threat-model remediation — Solution
Design §12, Build Brief §2.2) that are gated by `LIVE_MODE_GATES_SATISFIED`, a
hardcoded Python constant in `config/settings.py` — not an environment
variable, not a config file, not a Settings-UI toggle. Even with
`SIMULATION_MODE=live` set:
- `Settings.is_synthetic_data` stays `True` — every ingested record is still
  tagged `is_synthetic=true`
- the webhook gate (`integration/app.py::_require_simulation`) still returns
  `501` with a clear explanation of the three unmet gates
- `Settings.live_mode_requested` (what `.env` asked for) and
  `Settings.live_mode_active` (what the system actually grants — always
  `False` in this build) are tracked separately everywhere, so no code path can
  accidentally infer "live" from the raw env value alone

Flipping `LIVE_MODE_GATES_SATISFIED` to `True` is a deliberate code change made
by a human who has verified all three gates — never a side effect of editing
`.env`.

### Policy rule library (`config/policy_rules.yaml`)

A categorised library of ~35 rules across meals/per-diem, lodging, ground
transport, air travel & rental vehicles, entertainment & client relations,
misc/office, professional development & travel documentation, prohibited &
restricted spend, itemisation & documentation, fraud & behavioural indicators
(round-amount, tax-ratio, currency-mismatch), and timing/submission compliance.
Rules are marked `[ACTIVE]` (exercised by the current synthetic categories) or
`[FORWARD-LOOKING]` (real rule logic, but references a category the generator
doesn't yet produce — e.g. gifts, alcohol, communications — so it stays dormant
against synthetic data until real data or a matching generator category
exists). New rule types (`prohibited_category`, `weekend_spend_flag`,
`round_amount_flag`, `tax_ratio_check`, `late_submission_flag`,
`currency_mismatch_flag`) are implemented in `pipeline/agents/policy.py`. The
Settings → Business rules editor supports all 8 types.

### Storage backends

All persistence sits behind the interfaces in `data/interfaces.py`. Two
implementations, chosen by `STORAGE_BACKEND`:

- **`postgres`** — the pinned production stack (Postgres + pgvector). Bring it up
  with `docker compose -f scripts/docker-compose.yml up -d`.
- **`sqlite_local`** — Docker-free dev fallback (SQLite + NumPy cosine index).
  Behaviourally equivalent at the interface; used when Docker isn't available.

Swapping backends — or later swapping the simulation harness for a live T&E
connector — is a configuration change, not a rewrite (Build Brief §7).

## Quick start (no Docker required)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

copy .env.example .env          # sqlite_local backend by default
python scripts/migrate.py       # create schema
pytest -q                       # run the full test suite
# to use Azure OpenAI (GPT-4.1) vision instead of the offline simulator, set
# AZURE_OPENAI_KEY / AZURE_OPENAI_ENDPOINT in .env (or via Settings in the app)
# and set config/pipeline.yaml extraction.provider: azure_openai

python scripts/generate.py      # generate a synthetic run
python scripts/run_batch.py     # replay it end-to-end through the pipeline
python scripts/report.py        # accuracy & latency report (report.md/json)
./scripts/run_react.ps1         # start the app: API (8002) + web UI (5173)
```

### Frontend (`web/` — React + TypeScript + Vite, backed by FastAPI)

The operator app is a React SPA (`web/`) talking to the FastAPI backend
(`integration/app.py`) over a REST API with bearer-token sessions
(`integration/security.py`). Same grouped navigation the app has always had —
**Overview** (Dashboard), **Audit** (Expense reports), **Insights** (User
analytics, Ask AI, Reports & exports), **Configuration** (Settings, System
admin) — gated by role (admin / user / auditor).

- **Expense reports** (default) — risk-based audit list and review queue:
  summary tiles, a filterable colour-coded table, a "Pending review only"
  toggle, and a detail panel (evidence, extracted data, risk explanation,
  approve/reject) that resumes the checkpointed graph.
- **User analytics** — per-employee T&E spend, ABI behavioural score,
  auto-approved/total, spend by expense type, behavioural trends, spend by
  geography.
- **Dashboard** — business KPIs, routing mix, exception reasons, top violated
  rules, risk histogram, spend by category/OE/currency, trend, review queue,
  recent decisions, plus an Ops/model-health view.
- **Ask AI** — conversational Q&A over the audit data via the deterministic
  intent engine (`assistant/engine.py`) — offline, no API key.
- **Reports & exports** — decision extract (CSV) and accuracy/latency report.
- **System admin** — environment/connector status, run an audit batch, Users
  management, a **Concur simulator** (POSTs synthetic submissions to this
  service's own `/webhooks/submission-created`, with a payload inspector and
  a custom-submission builder), and the **Connectors** tab (Concur/Cytric/
  Workday/Oracle EBS status + test-connection).

Design tokens (dark theme, accent/purple gradients, KPI-card and status-chip
styling) live in `web/src/index.css`'s `@theme` block. Page bodies live under
`web/src/pages/`; shared backend logic behind every page stays in
`dashboard/queries.py`, `review_ui/service.py`, `assistant/engine.py`, and
`config_admin.py` — none of that changed when the UI moved off Streamlit.
Populate the store with a batch run first.

> **Retired: the original Streamlit UI.** `streamlit_app.py`, `auth_ui.py`,
> `ui_kit.py`, `app_common.py`, `app_pages/`, and `.streamlit/` have been moved
> to `_streamlit_backup/` (source preserved for reference, not deleted) now
> that the React frontend covers every page. They are not part of the running
> application and must not be started.

## Guardrails (Build Brief §7)

- Zero hardcoding — currency mix, anomaly rates, policy rules, thresholds live in `config/`.
- Every external model call sits behind a thin adapter.
- No secrets in code/config — environment variables only.
- **No real employee data, receipts, or T&E credentials anywhere**, incl. tests/fixtures.
- Every decision (incl. auto-approvals) writes to the audit store with
  `is_synthetic = true` and rule/model version stamped.
