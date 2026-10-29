"""Milestone 10: accuracy & latency report generation."""
from __future__ import annotations

import yaml
import pytest

from common.policy import load_policy_rules
from common.schemas import AuditState, ExtractedLine
from config.settings import REPO_ROOT, get_settings
from data.factory import build_data_layer
from evaluation.latency import LatencySink
from evaluation.report import build_report
from generator.config import load_generator_config
from generator.synthesize import Synthesizer
from pipeline.agents.policy import PolicyAgent
from pipeline.checkpoint import build_memory_checkpointer
from pipeline.factory import build_pipeline

THRESH = yaml.safe_load((REPO_ROOT / "config" / "thresholds.yaml").read_text(encoding="utf-8"))


@pytest.fixture()
def report(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite_local")
    monkeypatch.setenv("SIMULATION_MODE", "simulation")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setenv("EMBEDDING_DIM", "256")
    get_settings.cache_clear()
    settings = get_settings()

    data = build_data_layer(settings)
    data.migrate()
    cfg = load_generator_config().model_copy(update={"volume": 150, "seed": 20260716})
    rules = load_policy_rules()
    events, gt = Synthesizer(cfg, rules, data.blobs).generate()

    sink = LatencySink()
    pipeline = build_pipeline(
        data, settings, checkpointer=build_memory_checkpointer(), latency_sink=sink
    )
    states = {}
    for ev in events:
        data.store.save_submission(ev, is_synthetic=True)
        states[ev.submission_id] = pipeline.run(ev)

    # clean policy verdicts (deterministic engine)
    agent = PolicyAgent(rules)
    by_id = {e.submission_id: e for e in events}
    verdicts = {}
    for s in gt.submissions:
        st = AuditState(submission_id=s.submission_id)
        st.extracted_lines = [
            ExtractedLine(line_id=gl.line_id, vendor=gl.vendor, amount=gl.amount,
                          tax=gl.tax, currency=gl.currency, confidence=1.0)
            for gl in s.lines
        ]
        agent.run(st, by_id[s.submission_id])
        failed = {rr.rule_id for rr in st.policy_evaluation.rule_results if not rr.passed}
        verdicts[s.submission_id] = (bool(failed), failed)

    rep = build_report(gt, states, sink.summary(), THRESH, policy_verdicts=verdicts)
    data.close()
    yield rep
    get_settings.cache_clear()


def test_report_has_all_threshold_rows(report):
    names = {r.metric for r in report.rows}
    assert "Extraction field accuracy" in names
    assert "Duplicate recall" in names
    assert "Duplicate false-positive rate" in names
    assert "Confidence accuracy gap" in names
    assert "Policy verdict match (deterministic engine)" in names
    assert "Extraction p95 latency (s)" in names
    assert "Pipeline p95 latency (s)" in names


def test_report_metrics_meet_informative_bars(report):
    by = {r.metric: r for r in report.rows}
    assert by["Extraction field accuracy"].meets is True
    assert by["Duplicate recall"].meets is True
    assert by["Duplicate false-positive rate"].meets is True
    assert by["Policy verdict match (deterministic engine)"].meets is True


def test_report_latency_and_routing_present(report):
    assert "extraction" in report.latency["per_node"]
    assert report.latency["end_to_end"]["count"] == report.n_submissions
    assert sum(report.routing_distribution.values()) == report.n_submissions


def test_report_renders(report):
    md = report.to_markdown()
    assert "Accuracy & Latency Report" in md
    assert "NOT a go-live gate" in md
    import json

    parsed = json.loads(report.to_json())
    assert parsed["run_id"] == report.run_id
    assert parsed["metrics"]
