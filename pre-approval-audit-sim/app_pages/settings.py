"""Settings page - configure LLMs, business rules, and thresholds.

Every save validates against the pydantic config models before writing, then
reloads cached resources so the change takes effect immediately. Secrets are
never displayed; the API key is written to the gitignored .env only.
"""
from __future__ import annotations

import math

import pandas as pd
import streamlit as st

import auth_ui
import config_admin as ca
from app_common import reload

auth_ui.require_admin()

st.caption("Changes are validated, saved to config/, and applied on save.")

llm_tab, thr_tab, risk_tab, rules_tab, gen_tab = st.tabs(
    ["LLM & extraction", "Thresholds", "Risk & pipeline", "Business rules", "Data generator"]
)

# --------------------------------------------------------------------------- #
# LLM & extraction
# --------------------------------------------------------------------------- #
with llm_tab:
    pcfg = ca.load_raw(ca.PIPELINE_YAML)
    ext = pcfg["extraction"]
    _PROVIDERS = ["simulated", "anthropic", "azure_openai"]
    _cur_provider = ext.get("provider", "simulated")
    if _cur_provider not in _PROVIDERS:
        _cur_provider = "simulated"

    # Provider selection lives OUTSIDE the form so switching it immediately
    # reveals the matching fields below (a form would delay that until submit).
    provider = st.selectbox(
        "Vision extractor provider", _PROVIDERS,
        index=_PROVIDERS.index(_cur_provider),
        help="simulated = offline (no key needed); anthropic = real Claude vision; "
             "azure_openai = Azure OpenAI (e.g. GPT-4.1) vision, same pattern as the SOA app.",
        key="llm_provider_select",
    )

    with st.form("llm_form"):
        embedding_dim = st.number_input("Embedding dimension", min_value=8, max_value=4096,
                                        value=int(ca.env_value("EMBEDDING_DIM") or 1536), step=8)
        conf_cut = st.number_input("Confidence cutoff (route to review below this)",
                                   min_value=0.0, max_value=1.0,
                                   value=float(ext.get("confidence_cutoff", 0.7)), step=0.05)

        model = deployment = endpoint = api_version = ""
        new_anthropic_key = new_azure_key = ""

        if provider == "simulated":
            st.info("No API key needed - offline, deterministic extraction.")

        elif provider == "anthropic":
            model = st.text_input("Vision model", value=ca.env_value("LLM_VISION_MODEL")
                                  or "claude-sonnet-5")
            key_set = bool(ca.env_value("ANTHROPIC_API_KEY"))
            st.caption(f"API key status: {'set' if key_set else 'not set'}")
            new_anthropic_key = st.text_input(
                "Set/replace ANTHROPIC_API_KEY (written to .env only)",
                value="", type="password")

        else:  # azure_openai
            c1, c2 = st.columns(2)
            deployment = c1.text_input("Deployment name",
                                       value=ca.env_value("AZURE_DEPLOYMENT_NAME") or "gpt-4.1")
            api_version = c2.text_input("API version",
                                        value=ca.env_value("AZURE_API_VERSION")
                                        or "2024-08-01-preview")
            endpoint = st.text_input("Azure endpoint", value=ca.env_value("AZURE_OPENAI_ENDPOINT"),
                                     placeholder="https://<resource>.openai.azure.com/")
            key_set = bool(ca.env_value("AZURE_OPENAI_KEY"))
            st.caption(f"API key status: {'set' if key_set else 'not set'}")
            new_azure_key = st.text_input(
                "Set/replace AZURE_OPENAI_KEY (written to .env only)",
                value="", type="password")

        if st.form_submit_button("Save LLM settings", type="primary"):
            ext["provider"] = provider
            ext["confidence_cutoff"] = conf_cut
            ca.save_pipeline(pcfg)

            env_updates = {"EMBEDDING_DIM": str(int(embedding_dim))}
            if provider == "anthropic":
                env_updates["LLM_VISION_MODEL"] = model
                if new_anthropic_key:
                    env_updates["ANTHROPIC_API_KEY"] = new_anthropic_key
            elif provider == "azure_openai":
                env_updates["AZURE_DEPLOYMENT_NAME"] = deployment
                env_updates["AZURE_API_VERSION"] = api_version
                env_updates["AZURE_OPENAI_ENDPOINT"] = endpoint
                if new_azure_key:
                    env_updates["AZURE_OPENAI_KEY"] = new_azure_key
            ca.update_env(env_updates)
            reload()
            st.success("LLM settings saved.")

# --------------------------------------------------------------------------- #
# Thresholds
# --------------------------------------------------------------------------- #
with thr_tab:
    thr = ca.load_raw(ca.THRESHOLDS_YAML)
    with st.form("thr_form"):
        c = st.columns(2)
        thr["extraction"]["field_accuracy_min"] = c[0].number_input(
            "Extraction field accuracy min", 0.0, 1.0,
            float(thr["extraction"]["field_accuracy_min"]), 0.01)
        thr["duplicate_detection"]["recall_min"] = c[1].number_input(
            "Duplicate recall min", 0.0, 1.0,
            float(thr["duplicate_detection"]["recall_min"]), 0.01)
        thr["duplicate_detection"]["false_positive_rate_max"] = c[0].number_input(
            "Duplicate FP rate max", 0.0, 1.0,
            float(thr["duplicate_detection"]["false_positive_rate_max"]), 0.01)
        thr["confidence"]["min_accuracy_gap"] = c[1].number_input(
            "Confidence accuracy gap min", 0.0, 1.0,
            float(thr["confidence"]["min_accuracy_gap"]), 0.01)
        thr["confidence"]["low_confidence_cutoff"] = c[0].number_input(
            "Low-confidence cutoff", 0.0, 1.0,
            float(thr["confidence"]["low_confidence_cutoff"]), 0.05)
        thr["latency"]["extraction_p95_seconds_max"] = c[1].number_input(
            "Extraction p95 latency max (s)", 0.0, 600.0,
            float(thr["latency"]["extraction_p95_seconds_max"]), 1.0)
        thr["latency"]["pipeline_p95_seconds_max"] = c[0].number_input(
            "Pipeline p95 latency max (s)", 0.0, 3600.0,
            float(thr["latency"]["pipeline_p95_seconds_max"]), 5.0)
        if st.form_submit_button("Save thresholds", type="primary"):
            ca.save_thresholds(thr)
            reload()
            st.success("Thresholds saved.")

# --------------------------------------------------------------------------- #
# Risk & pipeline
# --------------------------------------------------------------------------- #
with risk_tab:
    pc = ca.load_raw(ca.PIPELINE_YAML)
    with st.form("risk_form"):
        pc["engine"] = st.selectbox(
            "Orchestration engine", ["langgraph", "sequential"],
            index=0 if pc.get("engine", "langgraph") == "langgraph" else 1,
        )
        c = st.columns(2)
        pc["risk"]["auto_approve_cutoff"] = c[0].number_input(
            "Auto-approve cutoff (score <=)", 0.0, 1.0,
            float(pc["risk"]["auto_approve_cutoff"]), 0.05)
        pc["risk"]["auto_reject_cutoff"] = c[1].number_input(
            "Auto-reject cutoff (score >=)", 0.0, 1.0,
            float(pc["risk"]["auto_reject_cutoff"]), 0.05)
        pc["retry"]["max_retries"] = c[0].number_input(
            "Max retries (transient)", 0, 10, int(pc["retry"]["max_retries"]), 1)
        backoff_txt = c[1].text_input(
            "Backoff seconds (comma-separated)",
            value=",".join(str(x) for x in pc["retry"]["backoff_seconds"]))

        st.markdown("**Risk weights**")
        wc = st.columns(len(pc["risk"]["weights"]))
        for i, (name, val) in enumerate(list(pc["risk"]["weights"].items())):
            pc["risk"]["weights"][name] = wc[i].number_input(name, 0.0, 5.0, float(val), 0.05)

        st.markdown("**Verification**")
        vc = st.columns(2)
        v = pc["verification"]
        v["subtotal_tolerance_pct"] = vc[0].number_input(
            "Subtotal tolerance %", 0.0, 100.0, float(v["subtotal_tolerance_pct"]), 0.5)
        v["duplicate_similarity_threshold"] = vc[1].number_input(
            "Duplicate similarity threshold", 0.0, 1.0,
            float(v["duplicate_similarity_threshold"]), 0.01)
        v["duplicate_amount_tolerance_pct"] = vc[0].number_input(
            "Duplicate amount tolerance %", 0.0, 100.0,
            float(v["duplicate_amount_tolerance_pct"]), 0.5)
        v["duplicate_top_k"] = vc[1].number_input(
            "Duplicate search top-k", 1, 100, int(v["duplicate_top_k"]), 1)
        v["duplicate_require_same_employee"] = st.checkbox(
            "Require same employee for duplicate", value=bool(v["duplicate_require_same_employee"]))

        st.markdown("**Node timeouts (s)**")
        tc = st.columns(len(pc["node_timeouts"]))
        for i, (node, val) in enumerate(list(pc["node_timeouts"].items())):
            pc["node_timeouts"][node] = tc[i].number_input(node, 1.0, 600.0, float(val), 1.0)

        if st.form_submit_button("Save risk & pipeline", type="primary"):
            try:
                pc["retry"]["backoff_seconds"] = [float(x) for x in backoff_txt.split(",") if x.strip()]
                ca.save_pipeline(pc)
                reload()
                st.success("Risk & pipeline settings saved.")
            except Exception as exc:
                st.error(f"Invalid config: {exc}")

# --------------------------------------------------------------------------- #
# Business rules
# --------------------------------------------------------------------------- #
with rules_tab:
    policy = ca.load_raw(ca.POLICY_YAML)
    gen = ca.load_raw(ca.GENERATOR_YAML)
    currencies = gen.get("currency_mix", ["EUR", "USD", "GBP"])

    _RULE_TYPES = [
        "amount_cap", "receipt_required_above", "prohibited_category",
        "weekend_spend_flag", "round_amount_flag", "tax_ratio_check",
        "late_submission_flag", "currency_mismatch_flag",
    ]

    def _num_or_none(v):
        if v is None:
            return None
        if isinstance(v, float) and math.isnan(v):
            return None
        return v

    rule_version = st.text_input("Rule version", value=policy.get("rule_version", ""))

    # flatten rules for editing - every column exists for every row regardless
    # of type, so switching a row's type never silently drops the fields it
    # needs (cap_*/thr_* for amount_cap/receipt_required_above/round_amount_flag,
    # min_ratio/max_ratio for tax_ratio_check, max_days for late_submission_flag).
    flat = []
    for r in policy.get("rules", []):
        row = {
            "id": r["id"],
            "description": r.get("description", ""),
            "type": r["type"],
            "category": (r.get("applies_to") or {}).get("category", ""),
            "oe_code": (r.get("applies_to") or {}).get("oe_code", ""),
            "min_ratio": r.get("min_ratio"),
            "max_ratio": r.get("max_ratio"),
            "max_days": r.get("max_days"),
        }
        for cur in currencies:
            row[f"cap_{cur}"] = (r.get("cap") or {}).get(cur)
            row[f"thr_{cur}"] = (r.get("threshold") or {}).get(cur)
        flat.append(row)

    st.caption(
        "Edit caps/thresholds per currency, then Save. Which columns matter depends on "
        "**type**: `amount_cap` → cap_*; `receipt_required_above` / `round_amount_flag` → "
        "thr_*; `tax_ratio_check` → min_ratio/max_ratio; `late_submission_flag` → max_days; "
        "`prohibited_category` / `weekend_spend_flag` / `currency_mismatch_flag` → category/oe_code "
        "only (leave the rest blank). Add/remove rows as needed."
    )
    edited = st.data_editor(
        pd.DataFrame(flat),
        num_rows="dynamic",
        width="stretch",
        column_config={
            "type": st.column_config.SelectboxColumn(options=_RULE_TYPES),
        },
        key="rules_editor",
    )

    if st.button("Save business rules", type="primary"):
        rules = []
        for _, row in edited.iterrows():
            if not str(row.get("id") or "").strip():
                continue
            applies_to = {}
            if str(row.get("category") or "").strip():
                applies_to["category"] = row["category"]
            if str(row.get("oe_code") or "").strip():
                applies_to["oe_code"] = row["oe_code"]
            rtype = row["type"]
            rule = {"id": row["id"], "description": row.get("description") or "",
                    "type": rtype, "applies_to": applies_to}

            if rtype in ("amount_cap",):
                rule["cap"] = {cur: float(row[f"cap_{cur}"]) for cur in currencies
                              if _num_or_none(row.get(f"cap_{cur}")) is not None}
            elif rtype in ("receipt_required_above", "round_amount_flag"):
                rule["threshold"] = {cur: float(row[f"thr_{cur}"]) for cur in currencies
                                     if _num_or_none(row.get(f"thr_{cur}")) is not None}
            elif rtype == "tax_ratio_check":
                if _num_or_none(row.get("min_ratio")) is not None:
                    rule["min_ratio"] = float(row["min_ratio"])
                if _num_or_none(row.get("max_ratio")) is not None:
                    rule["max_ratio"] = float(row["max_ratio"])
            elif rtype == "late_submission_flag":
                if _num_or_none(row.get("max_days")) is not None:
                    rule["max_days"] = int(row["max_days"])
            # prohibited_category, weekend_spend_flag, currency_mismatch_flag:
            # no extra fields - applies_to (category/oe_code) is everything.
            rules.append(rule)
        try:
            ca.save_policy({"rule_version": rule_version, "rules": rules})
            reload()
            st.success(f"Saved {len(rules)} rules.")
        except Exception as exc:
            st.error(f"Invalid rules: {exc}")

# --------------------------------------------------------------------------- #
# Data generator
# --------------------------------------------------------------------------- #
with gen_tab:
    g = ca.load_raw(ca.GENERATOR_YAML)
    with st.form("gen_form"):
        c = st.columns(2)
        g["volume"] = c[0].number_input("Volume", 1, 100000, int(g["volume"]), 10)
        g["seed"] = c[1].number_input("Seed", 0, 2_147_483_647, int(g["seed"]), 1)
        a = g["anomaly_injection"]
        a["duplicate_rate"] = c[0].number_input("Duplicate rate", 0.0, 1.0,
                                                float(a["duplicate_rate"]), 0.01)
        a["policy_violation_rate"] = c[1].number_input("Policy violation rate", 0.0, 1.0,
                                                       float(a["policy_violation_rate"]), 0.01)
        a["manipulated_receipt_rate"] = c[0].number_input("Manipulated receipt rate", 0.0, 1.0,
                                                          float(a["manipulated_receipt_rate"]), 0.01)
        g["currency_mix"] = [s.strip() for s in st.text_input(
            "Currency mix (comma)", ",".join(g["currency_mix"])).split(",") if s.strip()]
        g["language_mix"] = [s.strip() for s in st.text_input(
            "Language mix (comma)", ",".join(g["language_mix"])).split(",") if s.strip()]
        g["oe_codes"] = [s.strip() for s in st.text_input(
            "OE codes (comma)", ",".join(g["oe_codes"])).split(",") if s.strip()]
        if st.form_submit_button("Save generator", type="primary"):
            try:
                ca.save_generator(g)
                reload()
                st.success("Generator settings saved.")
            except Exception as exc:
                st.error(f"Invalid config: {exc}")
