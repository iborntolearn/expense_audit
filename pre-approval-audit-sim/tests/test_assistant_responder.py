"""Ask AI responder adapter (assistant/responder.py) - the tool-calling layer
that lets a real LLM provider reason over the same data the deterministic
engine uses. `Anthropic*`/`AzureOpenAI*` responders are construction-tested
only (missing-credentials -> RuntimeError), same convention as
adapters/vision.py's real extractors (no live API call in this suite) - but
the provider-agnostic tool dispatch and answer-parsing logic is pure Python
and fully unit tested here.
"""
from __future__ import annotations

import pytest

from adapters.factory import build_assistant_responder
from assistant.engine import answer as deterministic_answer
from assistant.responder import (
    AnthropicAssistantResponder,
    AzureOpenAIAssistantResponder,
    SimulatedAssistantResponder,
    _answer_from_submit_args,
    _run_query_tool,
    _ToolContext,
)
from common.policy import load_policy_rules
from config.settings import Settings
from generator.config import load_generator_config
from generator.synthesize import Synthesizer
from integration.ingest import IngestService
from pipeline.checkpoint import build_memory_checkpointer
from pipeline.config import load_pipeline_config
from pipeline.factory import build_pipeline


@pytest.fixture()
def rows(data_layer, sim_settings):
    cfg = load_generator_config().model_copy(update={"volume": 60, "seed": 7})
    events, _gt = Synthesizer(cfg, load_policy_rules(), data_layer.blobs).generate()
    pipeline = build_pipeline(data_layer, sim_settings, checkpointer=build_memory_checkpointer())
    ingest = IngestService(data_layer.store, pipeline, is_synthetic=True)
    for ev in events:
        ingest.handle(ev)
    return data_layer.store.analytics_rows()


@pytest.fixture()
def ctx(rows):
    pcfg = load_pipeline_config()
    return _ToolContext(
        rows=rows,
        subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
        conf_cutoff=pcfg.extraction.confidence_cutoff,
        auto_approve_cutoff=pcfg.risk.auto_approve_cutoff,
        auto_reject_cutoff=pcfg.risk.auto_reject_cutoff,
    )


# --------------------------------------------------------------------------- #
# SimulatedAssistantResponder - must match the deterministic engine exactly.
def test_simulated_responder_matches_deterministic_engine(rows):
    pcfg = load_pipeline_config()
    responder = SimulatedAssistantResponder()
    for question in ("what is the automation rate?", "top spenders", "how many duplicates?"):
        got = responder.answer(
            question, rows,
            subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
            conf_cutoff=pcfg.extraction.confidence_cutoff,
            auto_approve_cutoff=pcfg.risk.auto_approve_cutoff,
            auto_reject_cutoff=pcfg.risk.auto_reject_cutoff,
            history=[{"role": "user", "content": "irrelevant prior turn"}],
        )
        want = deterministic_answer(
            question, rows,
            subtotal_tol=pcfg.verification.subtotal_tolerance_pct,
            conf_cutoff=pcfg.extraction.confidence_cutoff,
            auto_reject_cutoff=pcfg.risk.auto_reject_cutoff,
        )
        assert got == want


# --------------------------------------------------------------------------- #
# Real providers - construction-only (no live API call), same convention as
# adapters/vision.py's AnthropicVisionExtractor/AzureOpenAIVisionExtractor.
def test_anthropic_responder_requires_api_key():
    with pytest.raises(RuntimeError):
        AnthropicAssistantResponder(api_key="", model="claude-sonnet-5")


def test_azure_openai_responder_requires_key_and_endpoint():
    with pytest.raises(RuntimeError):
        AzureOpenAIAssistantResponder(
            api_key="", endpoint="", deployment="gpt-4.1", api_version="2024-08-01-preview"
        )
    with pytest.raises(RuntimeError):
        AzureOpenAIAssistantResponder(
            api_key="k", endpoint="", deployment="gpt-4.1", api_version="2024-08-01-preview"
        )


# --------------------------------------------------------------------------- #
# Factory selection (adapters/factory.py::build_assistant_responder).
def test_factory_defaults_to_simulated():
    pcfg = load_pipeline_config()
    responder = build_assistant_responder(Settings(), pcfg)
    assert isinstance(responder, SimulatedAssistantResponder)


def test_factory_raises_for_unknown_provider():
    pcfg = load_pipeline_config().model_copy(
        update={"assistant": load_pipeline_config().assistant.model_copy(update={"provider": "bogus"})}
    )
    with pytest.raises(ValueError):
        build_assistant_responder(Settings(), pcfg)


def test_factory_anthropic_requires_key_via_settings():
    pcfg = load_pipeline_config().model_copy(
        update={"assistant": load_pipeline_config().assistant.model_copy(update={"provider": "anthropic"})}
    )
    with pytest.raises(RuntimeError):
        build_assistant_responder(Settings(anthropic_api_key=""), pcfg)


# --------------------------------------------------------------------------- #
# Tool dispatch - the provider-agnostic logic both real responders share.
def test_dashboard_summary_tool(ctx):
    result = _run_query_tool("dashboard_summary", {}, ctx)
    assert "kpis" in result and "total_submissions" in result["kpis"]


def test_expense_reports_tool_filters_and_limits(ctx):
    result = _run_query_tool("expense_reports", {"limit": 3}, ctx)
    assert result["count"] >= len(result["reports"])
    assert len(result["reports"]) <= 3

    banded = _run_query_tool("expense_reports", {"risk_band": "HIGH"}, ctx)
    assert all(r["risk_band"] == "HIGH" for r in banded["reports"])


def test_employee_analytics_tool_known_and_unknown_employee(ctx):
    someone = _run_query_tool("list_employees", {}, ctx)["employees"][0]
    result = _run_query_tool("employee_analytics", {"employee_id": someone}, ctx)
    assert result["employee_id"] == someone
    assert "kpis" in result

    bad = _run_query_tool("employee_analytics", {"employee_id": "NO-SUCH-EMP"}, ctx)
    assert "error" in bad


def test_behaviour_scores_tool_sorted_ascending(ctx):
    result = _run_query_tool("behaviour_scores", {}, ctx)
    scores = [s["abi_score"] for s in result["scores"]]
    assert scores == sorted(scores)


def test_submission_insights_tool_known_and_unknown_submission(ctx):
    sid = _run_query_tool("expense_reports", {"limit": 1}, ctx)["reports"][0]["submission_id"]
    result = _run_query_tool("submission_insights", {"submission_id": sid}, ctx)
    assert result["report"]["submission_id"] == sid
    assert isinstance(result["insights"], list)

    bad = _run_query_tool("submission_insights", {"submission_id": "SUB-NOPE"}, ctx)
    assert "error" in bad


def test_list_employees_tool(ctx):
    result = _run_query_tool("list_employees", {}, ctx)
    assert result["employees"] == sorted(result["employees"])


def test_unknown_tool_name_returns_error(ctx):
    result = _run_query_tool("not_a_real_tool", {}, ctx)
    assert "error" in result


# --------------------------------------------------------------------------- #
# submit_answer argument parsing (LLM's structured final answer -> Answer).
def test_answer_from_submit_args_full():
    args = {
        "text": "Automation rate is 68%.",
        "metric": {"label": "Automation rate", "value": "68%"},
        "chart": {"label": "Employee", "value": "Spend", "data": [{"Employee": "E1", "Spend": 100}]},
        "table": [{"a": 1}],
    }
    ans = _answer_from_submit_args(args)
    assert ans.text == "Automation rate is 68%."
    assert ans.metric == ("Automation rate", "68%")
    assert ans.chart == args["chart"]
    assert ans.table == args["table"]


def test_answer_from_submit_args_minimal():
    ans = _answer_from_submit_args({"text": "Just a fact."})
    assert ans.text == "Just a fact."
    assert ans.metric is None
    assert ans.chart is None
    assert ans.table is None


def test_answer_from_submit_args_missing_text_falls_back():
    ans = _answer_from_submit_args({})
    assert ans.text
