"""Milestones 4-7 exit criteria: each agent benchmarked against generator ground
truth, thresholds sourced from config/thresholds.yaml."""
from __future__ import annotations

import yaml
import pytest

from common.policy import load_policy_rules
from common.schemas import AuditState, ExtractedLine
from config.settings import REPO_ROOT, get_settings
from data.factory import build_data_layer
from evaluation.scoring import (
    score_confidence,
    score_duplicates,
    score_extraction,
    score_policy,
)
from generator.config import load_generator_config
from generator.synthesize import Synthesizer
from pipeline.agents.policy import PolicyAgent
from pipeline.factory import build_pipeline

THRESH = yaml.safe_load((REPO_ROOT / "config" / "thresholds.yaml").read_text(encoding="utf-8"))


@pytest.fixture()
def acc_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite_local")
    monkeypatch.setenv("SIMULATION_MODE", "simulation")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setenv("EMBEDDING_DIM", "256")  # realistic dim (not the dim-8 unit fixture)
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture()
def run_states(acc_settings):
    """Generate a run and execute the real pipeline over it; return (gt, states)."""
    cfg = load_generator_config().model_copy(update={"volume": 250, "seed": 20260716})
    data = build_data_layer(acc_settings)
    data.migrate()
    rules = load_policy_rules()
    events, gt = Synthesizer(cfg, rules, data.blobs).generate()

    # persist submissions first (FK), then run the pipeline per submission
    pipeline = build_pipeline(data, acc_settings)
    states: dict[str, AuditState] = {}
    for ev in events:
        data.store.save_submission(ev, is_synthetic=True)
        states[ev.submission_id] = pipeline.run(ev)
    yield gt, states, rules, events
    data.close()


def test_extraction_field_accuracy(run_states):
    gt, states, _, _ = run_states
    score = score_extraction(gt, states)
    assert score.field_accuracy >= THRESH["extraction"]["field_accuracy_min"], score


def test_confidence_correlates_with_accuracy(run_states):
    gt, states, _, _ = run_states
    score = score_confidence(gt, states, THRESH["confidence"]["low_confidence_cutoff"])
    # low-confidence extractions must be materially less accurate (Spike obj 4)
    assert score.high_conf_accuracy > score.low_conf_accuracy
    assert score.gap >= THRESH["confidence"]["min_accuracy_gap"], score


def test_duplicate_recall_and_fp_rate(run_states):
    gt, states, _, _ = run_states
    score = score_duplicates(gt, states)
    assert score.recall >= THRESH["duplicate_detection"]["recall_min"], score
    assert score.false_positive_rate <= THRESH["duplicate_detection"]["false_positive_rate_max"], score


def test_authenticity_catches_manipulated(run_states):
    gt, states, _, _ = run_states
    manipulated = [s.submission_id for s in gt.submissions if s.manipulated]
    caught = [
        sid for sid in manipulated
        if states[sid].verification.authenticity_flags
        or (states[sid].verification.subtotal_variance_pct or 0) > 5.0
    ]
    # every manipulated submission trips at least one verification signal
    assert len(caught) == len(manipulated), (len(caught), len(manipulated))


def test_policy_engine_matches_ground_truth(run_states):
    """Deterministic engine on clean (ground-truth) inputs must match 100%."""
    gt, _states, rules, events = run_states
    agent = PolicyAgent(rules)
    by_id = {e.submission_id: e for e in events}
    verdicts: dict[str, tuple[bool, set[str]]] = {}

    for s in gt.submissions:
        ev = by_id[s.submission_id]
        state = AuditState(submission_id=s.submission_id)
        state.extracted_lines = [
            ExtractedLine(
                line_id=gl.line_id, vendor=gl.vendor, amount=gl.amount, tax=gl.tax,
                currency=gl.currency, confidence=1.0,
            )
            for gl in s.lines
        ]
        agent.run(state, ev)
        failed = {rr.rule_id for rr in state.policy_evaluation.rule_results if not rr.passed}
        verdicts[s.submission_id] = (bool(failed), failed)

    score = score_policy(gt, verdicts)
    assert score.verdict_match_rate == 1.0, score
