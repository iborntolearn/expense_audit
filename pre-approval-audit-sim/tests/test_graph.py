"""Milestone 8: LangGraph orchestration - end-to-end run, conditional routing,
suspend/resume for human review, and fail-open inside the graph."""
from __future__ import annotations

import pytest

from adapters.vision import VisionExtractor
from common.policy import load_policy_rules
from common.schemas import AuditState, ExtractedLine, RoutingDecision
from config.settings import get_settings
from data.factory import build_data_layer
from generator.config import load_generator_config
from generator.synthesize import Synthesizer
from pipeline.factory import build_pipeline


@pytest.fixture()
def graph_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite_local")
    monkeypatch.setenv("SIMULATION_MODE", "simulation")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setenv("EMBEDDING_DIM", "256")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture()
def env(graph_settings):
    from pipeline.checkpoint import build_memory_checkpointer

    data = build_data_layer(graph_settings)
    data.migrate()
    cfg = load_generator_config().model_copy(update={"volume": 60, "seed": 99})
    events, gt = Synthesizer(cfg, load_policy_rules(), data.blobs).generate()
    pipeline = build_pipeline(data, graph_settings, checkpointer=build_memory_checkpointer())
    states = {}
    for ev in events:
        data.store.save_submission(ev, is_synthetic=True)
        states[ev.submission_id] = pipeline.run(ev)
    yield data, pipeline, events, gt, states
    data.close()


def test_full_dataset_runs_without_unhandled_errors(env):
    # Phase 0 gate (Tech Design 6): whole dataset through the graph, decisions
    # persisted for every submission.
    data, _pipeline, events, _gt, states = env
    assert len(states) == len(events)
    assert all(data.store.has_decision(ev.submission_id) for ev in events)


def test_auto_path_finalises(env):
    data, _pipeline, _events, _gt, states = env
    auto = [sid for sid, st in states.items()
            if st.routing_decision in (RoutingDecision.auto_approve, RoutingDecision.auto_reject)]
    assert auto, "expected at least one auto-decided submission"
    # auto decisions are terminal - no reviewer action row
    row = data.store.get_submission(auto[0])
    assert row is not None


def test_human_path_suspends_then_resumes(env):
    data, pipeline, _events, _gt, states = env
    human = [sid for sid, st in states.items()
             if st.routing_decision is RoutingDecision.human_review]
    assert human, "expected at least one human_review submission"
    sid = human[0]

    # suspended at the handoff, awaiting a reviewer
    assert pipeline.is_suspended(sid) is True

    audit = pipeline.resume_after_review(
        sid, reviewer_id="REV-1", decision="approved", notes="looks fine"
    )
    assert isinstance(audit, AuditState)
    assert pipeline.is_suspended(sid) is False  # run completed

    # reviewer action persisted
    with_conn = data.store
    import sqlite3  # sqlite_local backend
    assert isinstance(with_conn._conn, sqlite3.Connection)
    row = with_conn._conn.execute(
        "SELECT reviewer_id, final_decision FROM reviewer_actions WHERE submission_id=?",
        (sid,),
    ).fetchone()
    assert row is not None
    assert row["reviewer_id"] == "REV-1"
    assert row["final_decision"] == "approved"


def test_durable_checkpoint_suspend_resume(graph_settings, tmp_path):
    """Resume from a DURABLE SqliteSaver (reconstructs state) - guards the
    class-identity re-coercion bug that MemorySaver doesn't surface."""
    from pipeline.checkpoint import build_sqlite_checkpointer

    data = build_data_layer(graph_settings)
    data.migrate()
    cfg = load_generator_config().model_copy(update={"volume": 40, "seed": 71})
    events, _gt = Synthesizer(cfg, load_policy_rules(), data.blobs).generate()

    cp = build_sqlite_checkpointer(tmp_path / "cp.db")
    pipeline = build_pipeline(data, graph_settings, checkpointer=cp)

    human = None
    for ev in events:
        data.store.save_submission(ev, is_synthetic=True)
        st = pipeline.run(ev)
        if st.routing_decision is RoutingDecision.human_review:
            human = ev.submission_id
            break
    assert human, "expected a human_review case"
    assert pipeline.is_suspended(human) is True

    # a fresh pipeline on the SAME durable checkpoint file (separate process sim)
    cp2 = build_sqlite_checkpointer(tmp_path / "cp.db")
    pipeline2 = build_pipeline(data, graph_settings, checkpointer=cp2)
    audit = pipeline2.resume_after_review(human, reviewer_id="REV-2", decision="approved")
    assert audit.submission_id == human
    assert pipeline2.is_suspended(human) is False
    data.close()


def test_resume_falls_back_when_checkpoint_missing(graph_settings):
    """A human-review case whose checkpoint is absent (e.g. a fresh process with
    a different in-memory saver) is still finalised directly, not crashed."""
    from pipeline.checkpoint import build_memory_checkpointer

    data = build_data_layer(graph_settings)
    data.migrate()
    cfg = load_generator_config().model_copy(update={"volume": 40, "seed": 51})
    events, _gt = Synthesizer(cfg, load_policy_rules(), data.blobs).generate()

    p1 = build_pipeline(data, graph_settings, checkpointer=build_memory_checkpointer())
    human = None
    for ev in events:
        data.store.save_submission(ev, is_synthetic=True)
        st = p1.run(ev)
        if st.routing_decision is RoutingDecision.human_review:
            human = ev.submission_id
            break
    assert human

    # fresh pipeline with a BRAND-NEW saver => no checkpoint for `human`
    p2 = build_pipeline(data, graph_settings, checkpointer=build_memory_checkpointer())
    assert p2.is_suspended(human) is False
    audit = p2.resume_after_review(human, reviewer_id="REV-X", decision="rejected")
    assert audit.submission_id == human
    # reviewer action persisted -> case leaves the queue
    assert human not in {q["submission_id"] for q in data.store.list_review_queue()}
    data.close()


class _FailingExtractor(VisionExtractor):
    def extract(self, blobs, receipt_url, line_id, expected_currency):
        raise ValueError("simulated permanent extraction failure")


def test_fail_open_in_graph(graph_settings):
    from pipeline.agents.extraction import ExtractionAgent
    from pipeline.checkpoint import build_memory_checkpointer

    data = build_data_layer(graph_settings)
    data.migrate()
    cfg = load_generator_config().model_copy(update={"volume": 3, "seed": 5})
    events, _gt = Synthesizer(cfg, load_policy_rules(), data.blobs).generate()

    pipeline = build_pipeline(data, graph_settings, checkpointer=build_memory_checkpointer())
    # inject a failing extractor - permanent error, so no retry backoff delay
    pipeline._extraction = ExtractionAgent(data.blobs, _FailingExtractor())

    ev = events[0]
    data.store.save_submission(ev, is_synthetic=True)
    audit = pipeline.run(ev)

    assert audit.errors, "expected a recorded node error"
    assert audit.routing_decision is RoutingDecision.human_review  # fail-open
    data.close()
