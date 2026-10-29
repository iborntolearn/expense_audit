"""Pipeline assembly.

Builds the active AuditPipeline from config + the data layer. The `engine` config
key selects the LangGraph graph (default, with checkpointing + suspend/resume) or
the sequential fallback. Both reuse the same agents, resilience runtime, and
write-through persistence, and both satisfy the AuditPipeline seam.
"""
from __future__ import annotations

from adapters.factory import build_embedding_client, build_vision_extractor
from common.blocklist import load_merchant_blocklist
from common.policy import PolicyRuleSet, load_policy_rules
from config.settings import Settings, get_settings
from data.factory import DataLayer
from integration.writeback import DecisionWriteback
from pipeline.agents.extraction import ExtractionAgent
from pipeline.agents.policy import PolicyAgent
from pipeline.agents.risk import RiskAgent
from pipeline.agents.verification import VerificationAgent
from pipeline.config import load_pipeline_config


def _load_live_policy_rules(data: DataLayer) -> PolicyRuleSet:
    """The live, admin-editable ruleset from the DB (policy_rules/
    policy_ruleset_meta - see services/policy_rule_service.py), falling back
    to the config/policy_rules.yaml reference copy if the store hasn't been
    bootstrapped yet (shouldn't happen post-ConfigStore.migrate(), but this
    keeps startup resilient rather than crashing on it)."""
    stored = data.config.get_policy_ruleset()
    if stored is None:
        return load_policy_rules()
    return PolicyRuleSet.model_validate(stored)


def build_pipeline(
    data: DataLayer, settings: Settings | None = None, *, checkpointer=None, latency_sink=None
):
    settings = settings or get_settings()
    pcfg = load_pipeline_config()
    rules = _load_live_policy_rules(data)
    blocklist = load_merchant_blocklist()

    vision = build_vision_extractor(settings, pcfg)
    embeddings = build_embedding_client(settings)
    writeback = DecisionWriteback(data.store)

    extraction = ExtractionAgent(data.blobs, vision)
    # VerificationAgent/RiskAgent take no pipeline config here - `pcfg` above
    # is topology only (engine, vision provider, timeouts/retry), fixed for
    # this process's lifetime. Both agents resolve their OWN effective
    # verification/risk config fresh on every submission from event.oe_code
    # (pipeline/config.py:load_pipeline_config), so an OE's saved threshold/
    # weight override takes effect live - see pipeline/agents/verification.py
    # and pipeline/agents/risk.py.
    verification = VerificationAgent(
        data.blobs, embeddings, data.vectors,
        store=data.store, rules=rules, blocklist=blocklist, config_store=data.config,
        vision=vision,
    )
    policy = PolicyAgent(rules)
    risk = RiskAgent(config_store=data.config)

    if pcfg.engine == "sequential":
        from pipeline.sequential import SequentialPipeline

        return SequentialPipeline(
            store=data.store, writeback=writeback, extraction=extraction,
            verification=verification, policy=policy, risk=risk, cfg=pcfg,
            rule_version=rules.rule_version, latency_sink=latency_sink,
        )

    if pcfg.engine == "langgraph":
        from pipeline.checkpoint import build_sqlite_checkpointer
        from pipeline.graph import LangGraphPipeline

        cp = checkpointer or build_sqlite_checkpointer(settings.checkpoint_file)
        return LangGraphPipeline(
            store=data.store, writeback=writeback, extraction=extraction,
            verification=verification, policy=policy, risk=risk, cfg=pcfg,
            rule_version=rules.rule_version, checkpointer=cp, latency_sink=latency_sink,
        )

    raise ValueError(f"unknown pipeline engine: {pcfg.engine!r}")
