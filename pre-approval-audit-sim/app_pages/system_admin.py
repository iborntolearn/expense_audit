"""System admin page - environment, run controls, and access (system config).

Distinct from Settings (business policy: rules/thresholds/LLM). This page covers
operational/system concerns: what environment is active, running audit batches,
and the RBAC/connector seams.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import auth_ui
import config_admin as ca
import ui_kit
from adapters.vision import save_itemization
from app_common import get_data_layer, get_pipeline, get_vision_extractor, reload
from common.policy import load_policy_rules
from common.schemas import ItemizedEntry, ReportLine, SourceSystem, SubmissionCreatedEvent
from config.settings import get_settings
from data.factory import purge_all_transactional_data
from generator.config import load_generator_config
from generator.synthesize import Synthesizer
from integration.ingest import IngestService
from pipeline.config import load_pipeline_config

auth_ui.require_admin()

settings = get_settings()
pcfg = load_pipeline_config()


def _render_manual_submission(gen_cfg, base_url: str) -> None:
    if "custom_sid_default" not in st.session_state:
        # Computed once and cached in session_state - NOT inline in the widget's
        # value= default, which would re-evaluate uuid.uuid4() on every rerun and
        # silently discard any submission_id the user typed over it (the widget's
        # implicit identity would change each time its default value changed).
        st.session_state["custom_sid_default"] = f"SUB-CUSTOM-{uuid.uuid4().hex[:8].upper()}"

    with st.form("custom_submission_form"):
        f1, f2, f3 = st.columns(3)
        custom_sid = f1.text_input("Submission ID", value=st.session_state["custom_sid_default"],
                                   key="custom_submission_id")
        custom_oe = f2.selectbox("OE code", gen_cfg.oe_codes, key="custom_oe_code")
        custom_currency = f3.selectbox("Currency", gen_cfg.currency_mix, key="custom_currency")

        f4, f5, f6 = st.columns(3)
        custom_employee = f4.text_input("Employee ID", value="EMP-DEMO", key="custom_employee_id")
        custom_cc = f5.text_input("Cost center", value="", key="custom_cost_center")
        custom_source = f6.selectbox(
            "Source system", ["concur", "simulation_harness"], key="custom_source_system",
            format_func=ui_kit.source_system_label,
            help="'concur' labels this as if a real Concur webhook sent it.",
        )

        st.markdown("**Line item** (this quick-build form supports one line — see "
                    "**Auto-detect** mode above for a multi-charge invoice)")
        l1, l2 = st.columns(2)
        custom_category = l1.selectbox("Category", gen_cfg.categories, key="custom_category")
        custom_amount = l2.number_input("Entered amount", min_value=0.0, value=25.00, step=1.0,
                                        key="custom_amount")
        custom_receipt = st.file_uploader(
            "Receipt (image or PDF)", type=["png", "jpg", "jpeg", "pdf"], key="custom_receipt_upload"
        )

        st.markdown("**Testing helpers** (optional)")
        st.caption(
            "The authenticity check (duplicate/tamper/AI-generation signals) reads a hidden "
            "metadata sidecar the synthetic generator writes — a plain uploaded file has none, "
            "so it can never trip that check on its own. Check this to attach one for testing."
        )
        sim_authenticity = st.checkbox(
            "Simulate AI-generated / tampered receipt (forces an authenticity flag)",
            key="custom_sim_authenticity",
        )

        st.caption(
            "Preview — this is the JSON that will be POSTed to `/webhooks/submission-created` "
            "on send (receipt_url is assigned once you click Send)."
        )
        st.json({
            "event_type": "submission.created",
            "submission_id": custom_sid,
            "source_system": custom_source,
            "source_system_ref": f"MANUAL-{custom_sid}",
            "oe_code": custom_oe,
            "employee_id": custom_employee,
            "cost_center": custom_cc or None,
            "currency": custom_currency,
            "submitted_at": "<assigned on send>",
            "report_lines": [{
                "line_id": "LN-1",
                "category": custom_category,
                "entered_amount": custom_amount,
                "receipt_url": custom_receipt.name if custom_receipt else "<upload a receipt>",
            }],
        })

        send_custom = st.form_submit_button(
            "Send to webhook", type="primary", icon=":material/send:"
        )

    if send_custom:
        if not custom_receipt:
            st.error("Attach a receipt file before sending.")
        else:
            from integration.concur_client import post_submission

            data = get_data_layer()
            key = f"manual/{custom_sid}/LN-1_{custom_receipt.name}"
            receipt_url = data.blobs.put(key, custom_receipt.getvalue(),
                                         custom_receipt.type or "application/octet-stream")
            if sim_authenticity:
                import json as _json

                data.blobs.put(
                    key + ".sim.json",
                    _json.dumps({"metadata": {"edited": True, "ai_generated_score": 0.9}}).encode(),
                    "application/json",
                )

            event = SubmissionCreatedEvent(
                submission_id=custom_sid,
                source_system=SourceSystem(custom_source),
                source_system_ref=f"MANUAL-{custom_sid}",
                oe_code=custom_oe,
                employee_id=custom_employee,
                cost_center=custom_cc or None,
                currency=custom_currency,
                submitted_at=datetime.now(timezone.utc),
                report_lines=[ReportLine(
                    line_id="LN-1", category=custom_category,
                    entered_amount=custom_amount, receipt_url=receipt_url,
                )],
            )
            result = post_submission(event, base_url)
            st.session_state["_concur_sim_last_events"] = [event]
            st.cache_data.clear()
            if result.ok and result.accepted:
                # Suggest a fresh submission_id for the next one instead of the
                # same value (which would now just no-op as already_processed).
                del st.session_state["custom_sid_default"]

            if result.ok:
                st.success(
                    f"Sent. HTTP {result.status_code} · accepted={result.accepted} · "
                    f"reason={result.reason} · routing={result.routing_decision}. "
                    f"Look it up in **Expense reports** as `{custom_sid}` "
                    f"(check \"Pending review only\" if it routed to human_review)."
                )
            else:
                st.error(
                    f"Webhook call failed: {result.detail or 'no response'}. Is the API service "
                    f"running? Start it with `./scripts/dev_run.ps1`."
                )
            with st.expander("Payload actually sent"):
                st.json(event.model_dump(mode="json"))


def _render_auto_detect_submission(gen_cfg, base_url: str) -> None:
    st.caption(
        "Upload one real invoice — even if it lists several charges (airfare, hotel, "
        "meals, ...) on a single page — and the vision model will split it into "
        "separate categorized line items, then run each one through policy, "
        "verification, and risk scoring exactly like a manually-built submission."
    )

    if "auto_sid_default" not in st.session_state:
        st.session_state["auto_sid_default"] = f"SUB-AUTO-{uuid.uuid4().hex[:8].upper()}"

    f1, f2, f3 = st.columns(3)
    auto_sid = f1.text_input("Submission ID", value=st.session_state["auto_sid_default"],
                             key="auto_submission_id")
    auto_oe = f2.selectbox("OE code", gen_cfg.oe_codes, key="auto_oe_code")
    auto_currency = f3.selectbox("Currency", gen_cfg.currency_mix, key="auto_currency")

    f4, f5, f6 = st.columns(3)
    auto_employee = f4.text_input("Employee ID", value="EMP-DEMO", key="auto_employee_id")
    auto_cc = f5.text_input("Cost center", value="", key="auto_cost_center")
    auto_source = f6.selectbox(
        "Source system", ["concur", "simulation_harness"], key="auto_source_system",
        format_func=ui_kit.source_system_label,
        help="'concur' labels this as if a real Concur webhook sent it.",
    )

    auto_receipt = st.file_uploader(
        "Invoice (image or PDF) — may contain multiple charges",
        type=["png", "jpg", "jpeg", "pdf"], key="auto_receipt_upload",
    )

    st.markdown("**Testing helpers** (optional)")
    auto_sim_authenticity = st.checkbox(
        "Simulate AI-generated / tampered receipt (forces an authenticity flag)",
        key="auto_sim_authenticity",
    )

    detect_clicked = st.button(
        "Detect line items", icon=":material/auto_awesome:", key="auto_detect_go",
        disabled=auto_receipt is None,
    )

    if detect_clicked:
        data = get_data_layer()
        key = f"manual/{auto_sid}/AUTO_{auto_receipt.name}"
        receipt_url = data.blobs.put(
            key, auto_receipt.getvalue(), auto_receipt.type or "application/octet-stream"
        )
        extractor = get_vision_extractor()
        with st.spinner("Reading the invoice and splitting it into line items…"):
            items = extractor.extract_items(
                data.blobs, receipt_url, auto_currency, gen_cfg.categories
            )
        if not items:
            st.error("No line items could be read from this file. Try a clearer image/PDF, "
                     "or switch to Manual mode.")
            st.session_state.pop("_auto_detect_items", None)
        else:
            save_itemization(data.blobs, key, items)
            st.session_state["_auto_detect_items"] = [i.model_dump(mode="json") for i in items]
            st.session_state["_auto_detect_receipt_url"] = receipt_url
            st.session_state["_auto_detect_receipt_key"] = key

    detected = st.session_state.get("_auto_detect_items")
    if detected:
        st.success(f"Detected {len(detected)} line item(s) — review/correct below before sending.")
        edit_df = pd.DataFrame(detected)[["description", "category", "amount", "tax"]]
        edited = st.data_editor(
            edit_df,
            column_config={
                "category": st.column_config.SelectboxColumn(
                    "Category", options=gen_cfg.categories, required=True
                ),
                "amount": st.column_config.NumberColumn("Amount", min_value=0.0, step=1.0),
                "tax": st.column_config.NumberColumn("Tax", min_value=0.0, step=0.1),
            },
            hide_index=True, width="stretch", key="auto_detect_editor",
        )
        st.caption(
            f"Detected currency/vendor read: {detected[0].get('currency') or auto_currency} · "
            f"{detected[0].get('vendor') or '(unknown)'}"
        )

        send_auto = st.button("Send to webhook", type="primary", icon=":material/send:",
                              key="auto_detect_send")
        if send_auto:
            from integration.concur_client import post_submission

            data = get_data_layer()
            receipt_url = st.session_state["_auto_detect_receipt_url"]
            receipt_key = st.session_state["_auto_detect_receipt_key"]
            if auto_sim_authenticity:
                import json as _json

                data.blobs.put(
                    receipt_key + ".sim.json",
                    _json.dumps({"metadata": {"edited": True, "ai_generated_score": 0.9}}).encode(),
                    "application/json",
                )

            valid = edited.dropna(subset=["amount"])
            if len(valid) < len(edited):
                st.warning(f"{len(edited) - len(valid)} item(s) had no amount and were skipped.")

            corrected_items, report_lines = [], []
            for i, row in enumerate(valid.itertuples(index=False), start=1):
                original = detected[valid.index[i - 1]] if valid.index[i - 1] < len(detected) else {}
                corrected_items.append(ItemizedEntry(
                    description=row.description,
                    vendor=original.get("vendor"),
                    date=original.get("date"),
                    amount=float(row.amount),
                    tax=float(row.tax) if row.tax is not None else None,
                    currency=original.get("currency") or auto_currency,
                    category=row.category,
                    confidence=original.get("confidence", 0.0),
                ))
                report_lines.append(ReportLine(
                    line_id=f"LN-{i}", category=row.category,
                    entered_amount=float(row.amount), receipt_url=receipt_url,
                ))
            # Once a reviewer has confirmed/corrected an amount or category, THAT
            # becomes the authoritative reading for policy/verification too - not
            # the model's original raw guess (see save_itemization/load_itemization
            # in adapters/vision.py, reused by pipeline/agents/extraction.py).
            save_itemization(data.blobs, receipt_key, corrected_items)

            event = SubmissionCreatedEvent(
                submission_id=auto_sid,
                source_system=SourceSystem(auto_source),
                source_system_ref=f"MANUAL-{auto_sid}",
                oe_code=auto_oe,
                employee_id=auto_employee,
                cost_center=auto_cc or None,
                currency=auto_currency,
                submitted_at=datetime.now(timezone.utc),
                report_lines=report_lines,
            )
            result = post_submission(event, base_url)
            st.session_state["_concur_sim_last_events"] = [event]
            st.cache_data.clear()
            if result.ok and result.accepted:
                del st.session_state["auto_sid_default"]
                st.session_state.pop("_auto_detect_items", None)
                st.session_state.pop("_auto_detect_receipt_url", None)
                st.session_state.pop("_auto_detect_receipt_key", None)

            if result.ok:
                st.success(
                    f"Sent. HTTP {result.status_code} · accepted={result.accepted} · "
                    f"reason={result.reason} · routing={result.routing_decision} · "
                    f"{len(report_lines)} line(s) detected. Look it up in **Expense reports** "
                    f"as `{auto_sid}` (check \"Pending review only\" if it routed to human_review)."
                )
            else:
                st.error(
                    f"Webhook call failed: {result.detail or 'no response'}. Is the API "
                    f"service running? Start it with `./scripts/dev_run.ps1`."
                )
            with st.expander("Payload actually sent"):
                st.json(event.model_dump(mode="json"))


(custom_tab, env_tab, conn_tab, run_tab, webhook_tab, roles_tab, users_tab,
 watchlist_tab, email_tab, danger_tab) = st.tabs([
    "Concur simulator — custom submission", "Environment", "Connectors", "Run audit batch",
    "Concur simulator — webhook", "Roles & access", "Users", "Merchant watchlist",
    "Email templates", "Reset DB",
])

# --------------------------------------------------------------------------- #
# Concur simulator: custom submission (upload your own data)
# --------------------------------------------------------------------------- #
with custom_tab:
    st.caption(
        "Hand-build ONE submission-created payload and send it to the same webhook — useful "
        "to see exactly what data triggers an audit and to try it with your own receipt."
    )
    gen_cfg = load_generator_config()
    default_base = f"http://{settings.app_host}:{settings.app_port}"
    base_url = st.session_state.get("concur_sim_base_url", default_base)

    if pcfg.extraction.provider == "simulated":
        st.warning(
            "Vision provider is **simulated** (Settings → LLM & extraction). The simulator "
            "reads a synthetic answer-key it generates itself, not the actual pixels of a "
            "real receipt — so an uploaded file here will fail extraction and fail-open to "
            "human review, rather than being read for real. Switch to **anthropic** or "
            "**azure_openai** to see real vision extraction on your own receipt."
        )

    MANUAL_MODE = "Manual — I specify category & amount"
    AUTO_MODE = "Auto-detect — AI itemizes the invoice"
    custom_mode = st.radio(
        "Line item mode", [AUTO_MODE, MANUAL_MODE], key="custom_line_mode", horizontal=True,
        help="Auto-detect reads one uploaded invoice and splits it into several "
             "categorized line items on its own — use this for a real multi-charge "
             "invoice (airfare + hotel + meals on one PDF, for example).",
    )

    if custom_mode == MANUAL_MODE:
        _render_manual_submission(gen_cfg, base_url)
    else:
        _render_auto_detect_submission(gen_cfg, base_url)

# --------------------------------------------------------------------------- #
# Environment
# --------------------------------------------------------------------------- #
with env_tab:
    env = {
        "Mode (requested)": ui_kit.mode_label(settings.simulation_mode.value),
        "Live mode active": settings.live_mode_active,
        "Storage backend": settings.storage_backend.value,
        "Orchestration engine": pcfg.engine,
        "Vision provider": pcfg.extraction.provider,
        "Embedding dim": settings.embedding_dim,
    }
    if pcfg.extraction.provider == "azure_openai":
        env.update({
            "Azure deployment": ca.env_value("AZURE_DEPLOYMENT_NAME") or settings.azure_deployment_name,
            "Azure API version": ca.env_value("AZURE_API_VERSION") or settings.azure_api_version,
            "Azure endpoint": ca.env_value("AZURE_OPENAI_ENDPOINT") or "(not set)",
            "Azure OpenAI key": "set" if ca.env_value("AZURE_OPENAI_KEY") else "not set",
        })
    else:
        env.update({
            "Vision model": ca.env_value("LLM_VISION_MODEL") or settings.llm_vision_model,
            "Anthropic API key": "set" if ca.env_value("ANTHROPIC_API_KEY") else "not set",
        })
    env.update({
        "SQLite path": str(settings.sqlite_file),
        "Checkpoint path": str(settings.checkpoint_file),
    })
    st.dataframe(pd.DataFrame({"Setting": list(env), "Value": [str(v) for v in env.values()]}),
                 hide_index=True, width="stretch")
    if settings.live_mode_requested and not settings.live_mode_active:
        st.warning(
            f"`SIMULATION_MODE=live` is set but has **no effect** — {settings.live_mode_blocked_reason}"
        )

    st.divider()
    if st.button("Reload configuration & caches", icon=":material/refresh:"):
        reload()
        st.success("Reloaded.")

# --------------------------------------------------------------------------- #
# Connectors
# --------------------------------------------------------------------------- #
with conn_tab:
    st.dataframe(
        pd.DataFrame([
            {"Connector": "T&E system (in-process)", "Type": "Internal harness (mock)",
             "Status": "active (SIMULATION_MODE)"},
            {"Connector": "T&E system (REST webhook)", "Type": "Concur simulator → POST /webhooks/submission-created",
             "Status": "available in the Concur simulator tabs"},
            {"Connector": "Decision write-back", "Type": "Mock logger", "Status": "active"},
            {"Connector": "Live SAP Concur / Workday", "Type": "—",
             "Status": "not implemented (Build Brief 2.2)"},
        ]),
        hide_index=True, width="stretch",
    )

# --------------------------------------------------------------------------- #
# Run an audit batch (in-process)
# --------------------------------------------------------------------------- #
with run_tab:
    st.caption("Generates synthetic submissions and runs them through the full pipeline "
               "directly inside this Streamlit process (bypasses HTTP). Keep the sample "
               "small for an interactive run.")
    c = st.columns([1, 1, 3])
    n = c[0].number_input("Sample size", min_value=5, max_value=100, value=20, step=5)
    if c[1].button("Generate & audit", type="primary", icon=":material/play_arrow:"):
        data = get_data_layer()
        pipeline = get_pipeline()
        seed = int(datetime.now(timezone.utc).timestamp())  # unique run each click

        with st.status("Running audit batch…", expanded=True) as status:
            ui_kit.step_msg("🧬", "Step 1 / 3 — Generate",
                            f"Creating {int(n)} synthetic submissions + receipts…")
            cfg = load_generator_config().model_copy(update={"volume": int(n), "seed": seed})
            events, _gt = Synthesizer(cfg, load_policy_rules(), data.blobs).generate()
            ui_kit.step_ok("Generate complete", f"{len(events)} submission(s), seed={seed}")

            ui_kit.step_msg("🔎", "Step 2 / 3 — Audit",
                            "Extraction → verification → policy → risk scoring…")
            ingest = IngestService(data.store, pipeline, is_synthetic=settings.is_synthetic_data)
            for ev in events:
                ingest.handle(ev)
            ui_kit.step_ok("Audit complete", f"{len(events)} submission(s) processed")

            ui_kit.step_msg("💾", "Step 3 / 3 — Persist",
                            "Decisions written to the audit store…")
            st.cache_data.clear()
            ui_kit.step_ok("Persist complete", "dashboards will reflect the new run")
            status.update(label="✅ Batch complete", state="complete")

        st.success(f"Audited {int(n)} submissions (run seed {seed}). Dashboards updated.")

# --------------------------------------------------------------------------- #
# Concur simulator (REST webhook)
# --------------------------------------------------------------------------- #
with webhook_tab:
    st.caption(
        "Demonstrates the real integration seam (Tech Design 2.1): generates synthetic "
        "submissions and POSTs each one over HTTP to this service's own "
        "`/webhooks/submission-created` endpoint — the same route a live Concur connector "
        "would call in Phase A. Requires the API service to be running "
        "(`./scripts/dev_run.ps1`) and reachable at the URL below."
    )
    sc = st.columns([1, 2, 1])
    sim_n = sc[0].number_input("Sample size", min_value=1, max_value=50, value=5, step=1,
                               key="concur_sim_n")
    default_base = f"http://{settings.app_host}:{settings.app_port}"
    base_url = sc[1].text_input("API base URL", value=default_base, key="concur_sim_base_url")
    go_sim = sc[2].button("Generate & POST", type="primary", icon=":material/cloud_upload:",
                          key="concur_sim_go")

    if go_sim:
        from integration.concur_client import post_batch

        data = get_data_layer()
        seed = int(datetime.now(timezone.utc).timestamp())

        with st.status("Sending Concur webhook calls…", expanded=True) as status:
            ui_kit.step_msg("🧬", "Step 1 / 2 — Generate",
                            f"Creating {int(sim_n)} synthetic submissions + receipts…")
            cfg = load_generator_config().model_copy(update={"volume": int(sim_n), "seed": seed})
            events, _gt = Synthesizer(cfg, load_policy_rules(), data.blobs).generate()
            ui_kit.step_ok("Generate complete", f"{len(events)} submission(s), seed={seed}")

            ui_kit.step_msg("🌐", "Step 2 / 2 — POST to webhook",
                            f"Sending each submission to {base_url}/webhooks/submission-created…")
            results = post_batch(events, base_url)
            ok_count = sum(1 for r in results if r.ok)
            if ok_count:
                ui_kit.step_ok("Webhook calls complete", f"{ok_count}/{len(results)} accepted by the API")
            all_ok = ok_count == len(results)
            status.update(
                label="✅ Batch complete" if all_ok else "⚠️ Batch finished with errors",
                state="complete" if all_ok else "error",
            )

        st.session_state["_concur_sim_last_events"] = events
        st.cache_data.clear()

        failed = [r for r in results if not r.ok]
        if failed:
            st.error(
                f"{len(failed)} of {len(results)} webhook call(s) failed. Is the API service "
                f"running? Start it with `./scripts/dev_run.ps1`, then retry."
            )
        elif ok_count:
            st.success(f"{ok_count} submission(s) sent to the live webhook and audited.")

        st.dataframe(
            pd.DataFrame([
                {
                    "Submission": r.submission_id,
                    "HTTP status": r.status_code if r.status_code is not None else "no response",
                    "Accepted": r.accepted,
                    "Reason": r.reason,
                    "Routing": r.routing_decision,
                    "Detail": (r.detail or "")[:120],
                }
                for r in results
            ]),
            hide_index=True, width="stretch",
        )

    if st.session_state.get("_concur_sim_last_events"):
        _last_events = st.session_state["_concur_sim_last_events"]
        with st.expander(
            f"🔎 Inspect a webhook payload ({len(_last_events)} submission(s) in last batch)"
        ):
            st.caption(
                "This is the exact JSON body POSTed to `/webhooks/submission-created` for the "
                "selected submission — the same payload a live Concur connector would send "
                "(Tech Design §2.1)."
            )
            _pick = st.selectbox(
                "Submission", [e.submission_id for e in _last_events], key="concur_sim_inspect_pick"
            )
            _picked_event = next(e for e in _last_events if e.submission_id == _pick)
            st.json(_picked_event.model_dump(mode="json"))

        st.caption(
            "Idempotency check: re-send the exact same batch. A real T&E system may retry a "
            "webhook delivery; the platform must not audit it twice."
        )
        if st.button("Resend last batch (idempotency check)", icon=":material/replay:",
                     key="concur_sim_resend"):
            from integration.concur_client import post_batch as _post_batch_resend

            prior = st.session_state["_concur_sim_last_events"]
            resend_results = _post_batch_resend(prior, base_url)
            dup = sum(1 for r in resend_results if r.ok and r.reason == "already_processed")
            st.info(f"{dup} of {len(resend_results)} re-delivered submission(s) were "
                    f"correctly no-op'd (`already_processed`) — idempotency holds.")
            st.dataframe(
                pd.DataFrame([
                    {"Submission": r.submission_id, "HTTP status": r.status_code,
                     "Accepted": r.accepted, "Reason": r.reason}
                    for r in resend_results
                ]),
                hide_index=True, width="stretch",
            )

# --------------------------------------------------------------------------- #
# Access control (seam)
# --------------------------------------------------------------------------- #
with roles_tab:
    st.caption("Full SSO (SAML/OIDC) is the integration seam this build stands in for "
               "(Solution Design 10) - login here is real (username/password, checked "
               "against config/users.yaml), just not federated to a real IdP yet. "
               "Two roles are enforced - see the **Users** tab to manage accounts:")
    st.dataframe(
        pd.DataFrame([
            {"Role": "admin", "Access": "Everything - Overview, Audit, Insights, "
                                        "AND Configuration (Settings, System admin)"},
            {"Role": "user", "Access": "Overview, Audit, Insights only - Configuration "
                                       "(Settings/System admin) is not in their "
                                       "navigation at all, not just hidden"},
        ]),
        hide_index=True, width="stretch",
    )

# --------------------------------------------------------------------------- #
# Users: manage login accounts (config/users.yaml)
# --------------------------------------------------------------------------- #
with users_tab:
    st.caption("Accounts that can log in to this app. Passwords are salted + hashed "
               "(PBKDF2-HMAC-SHA256) - never stored or shown in plain text.")

    users_data = ca.load_users_raw()
    st.dataframe(
        pd.DataFrame([
            {"Username": u["username"], "Display name": u["display_name"], "Role": u["role"]}
            for u in users_data["users"]
        ]),
        hide_index=True, width="stretch",
    )

    st.markdown("**Add a user**")
    with st.form("add_user_form"):
        c1, c2, c3 = st.columns(3)
        new_username = c1.text_input("Username")
        new_display = c2.text_input("Display name")
        new_role = c3.selectbox("Role", ["user", "admin", "auditor"])
        new_password = st.text_input("Password", type="password")
        if st.form_submit_button("Add user", type="primary"):
            if not new_username.strip() or not new_password:
                st.error("Username and password are required.")
            else:
                try:
                    ca.add_user(new_username.strip(), new_display.strip() or new_username.strip(),
                               new_role, new_password)
                    st.success(f"User {new_username!r} added.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    st.markdown("**Reset a password / change a role**")
    usernames = [u["username"] for u in users_data["users"]]
    if usernames:
        c1, c2, c3 = st.columns(3)
        sel_user = c1.selectbox("Username", usernames, key="reset_pw_user")
        new_pw = c2.text_input("New password", type="password", key="reset_pw_value")
        if c3.button("Reset password", width="stretch"):
            if not new_pw:
                st.error("Enter a new password.")
            else:
                ca.reset_password(sel_user, new_pw)
                st.success(f"Password reset for {sel_user!r}.")

        r1, r2 = st.columns(2)
        role_user = r1.selectbox("Username", usernames, key="role_change_user")
        role_new = r2.selectbox("New role", ["user", "admin", "auditor"], key="role_change_value")
        if st.button("Change role", width="stretch"):
            current = next(u for u in users_data["users"] if u["username"] == role_user)
            if current["role"] == "admin" and role_new != "admin" and \
               sum(1 for u in users_data["users"] if u["role"] == "admin") <= 1:
                st.error("Cannot demote the last admin account.")
            else:
                ca.set_user_role(role_user, role_new)
                st.success(f"{role_user!r} is now {role_new!r}.")
                st.rerun()

    st.markdown("**Delete a user**")
    if usernames:
        del_user = st.selectbox("Username", usernames, key="del_user")
        if st.button("Delete user", icon=":material/delete:"):
            try:
                ca.delete_user(del_user)
                st.success(f"User {del_user!r} deleted.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

# --------------------------------------------------------------------------- #
# Merchant watchlist: simulated sanctions/PEP screening (BR-TE-AU-03)
# --------------------------------------------------------------------------- #
with watchlist_tab:
    st.caption(
        "Vendor names extracted off a receipt are matched case-insensitively as a "
        "substring against this list. **Simulated watchlist** - not a real OFAC/PEP data "
        "feed (that's an integration seam, same as the real T&E connector and real SSO). "
        "A match forces auto_reject regardless of other signals."
    )

    bl_data = ca.load_blocklist_raw()
    st.dataframe(
        pd.DataFrame([
            {"Name": e["name"], "Type": e["type"], "Reason": e["reason"]}
            for e in bl_data["entries"]
        ]),
        hide_index=True, width="stretch",
    )

    st.markdown("**Add a watchlist entry**")
    with st.form("add_blocklist_form"):
        c1, c2 = st.columns(2)
        new_name = c1.text_input("Vendor name (or substring)")
        new_type = c2.selectbox("Type", ["sanctioned", "pep"])
        new_reason = st.text_input("Reason", value="Simulated watchlist entry")
        if st.form_submit_button("Add entry", type="primary"):
            if not new_name.strip():
                st.error("Vendor name is required.")
            else:
                try:
                    ca.add_blocklist_entry(new_name.strip(), new_type, new_reason.strip())
                    st.success(f"Added {new_name!r} to the watchlist.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    st.markdown("**Remove a watchlist entry**")
    entry_names = [e["name"] for e in bl_data["entries"]]
    if entry_names:
        del_entry = st.selectbox("Vendor name", entry_names, key="del_blocklist_entry")
        if st.button("Remove entry", icon=":material/delete:"):
            try:
                ca.delete_blocklist_entry(del_entry)
                st.success(f"Removed {del_entry!r} from the watchlist.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

# --------------------------------------------------------------------------- #
# Email templates: auditor-to-traveller library (BR-TE-AU-13)
# --------------------------------------------------------------------------- #
with email_tab:
    st.caption(
        "Simulated - no real SMTP send exists in this build. Reviewers render and copy these "
        "from Expense reports -> Case management. Placeholders: {employee_id}, "
        "{submission_id}, {amount}, {currency}, {reason}."
    )
    et_data = ca.load_email_templates_raw()
    tmpl_names = [t["name"] for t in et_data["templates"]]
    if not tmpl_names:
        st.info("No templates configured.")
    else:
        sel_tmpl = st.selectbox("Template", tmpl_names, key="edit_email_tmpl")
        current = next(t for t in et_data["templates"] if t["name"] == sel_tmpl)
        with st.form("edit_email_form"):
            edit_subject = st.text_input("Subject", value=current["subject"])
            edit_body = st.text_area("Body", value=current["body"], height=260)
            if st.form_submit_button("Save template", type="primary"):
                ca.save_email_template_body(sel_tmpl, edit_subject, edit_body)
                st.success(f"Saved {sel_tmpl!r}.")
                st.rerun()

# --------------------------------------------------------------------------- #
# Danger zone: purge all transactional data (mirrors the SOA Layout Agent
# app's "Delete Operational Data" reset)
# --------------------------------------------------------------------------- #
with danger_tab:
    # Must run BEFORE the checkbox widget below is instantiated - Streamlit
    # forbids writing to a widget's session_state key in the same run AFTER
    # that widget has already rendered, so the confirm checkbox can only be
    # reset here, at the top of the NEXT run following a successful purge.
    if st.session_state.pop("_purge_just_ran", False):
        st.session_state.pop("purge_all_confirm", None)

    st.caption(
        "Deletes every submission and everything derived from it - extracted lines, "
        "verification results, policy evaluations, risk decisions, reviewer actions, "
        "report lines, receipt references, the pipeline execution log, and the "
        "duplicate-detection vector index - plus every stored receipt/blob file and "
        "the LangGraph checkpoint database. **Config is untouched**: "
        "`config/*.yaml`, `.env`, and policy rules are all kept."
    )

    data = get_data_layer()
    rows = data.store.analytics_rows()
    n_submissions = len(rows.get("submissions", []))
    try:
        n_blobs = len([p for p in settings.blob_dir.rglob("*") if p.is_file()])
    except Exception:
        n_blobs = 0
    checkpoint_present = settings.checkpoint_file.exists()

    c = st.columns(3)
    c[0].metric("Submissions", n_submissions)
    c[1].metric("Blob files", n_blobs)
    c[2].metric("Checkpoint db", "present" if checkpoint_present else "none")

    st.markdown(
        f"""
    <div style="margin-top:1rem;padding:.75rem 1rem;border:1px solid {ui_kit.COLORS['error_border']};
                border-radius:8px;background:{ui_kit.COLORS['error_bg']}">
        <span style="color:{ui_kit.COLORS['error_text']};font-size:.8rem;font-weight:600">
            ⛔ Danger zone — this cannot be undone
        </span>
    </div>
    """,
        unsafe_allow_html=True,
    )

    confirm_purge = st.checkbox(
        "I understand this will permanently delete all submissions, decisions, "
        "receipt files, and checkpoints",
        key="purge_all_confirm",
    )
    if confirm_purge:
        if st.button("🗑 Delete all transactional data", type="primary",
                     width="stretch", key="purge_all_btn"):
            # Drop cached resources (and their open sqlite connections) BEFORE
            # touching the checkpoint file - on Windows an open connection
            # would otherwise block its deletion.
            reload()
            import gc
            gc.collect()

            fresh_settings = get_settings()
            fresh_data = get_data_layer()
            summary = purge_all_transactional_data(fresh_data, fresh_settings)
            st.cache_data.clear()
            st.session_state["_purge_just_ran"] = True

            st.success(
                f"Deleted {summary['rows_deleted']} row(s) across "
                f"{len(summary['table_counts'])} table(s), {summary['blobs_deleted']} "
                f"blob file(s)." + (" Checkpoint db cleared." if summary["checkpoint_cleared"] else "")
            )
            if summary.get("checkpoint_error"):
                st.warning(
                    f"Checkpoint db could not be cleared (still locked): "
                    f"{summary['checkpoint_error']}. Restart the app to clear it."
                )
            with st.expander("Rows deleted per table"):
                st.json(summary["table_counts"])
            st.rerun()
