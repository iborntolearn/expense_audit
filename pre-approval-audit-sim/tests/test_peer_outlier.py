"""Peer-group statistical anomaly detection - AuditStore.category_amount_stats,
VerificationAgent._peer_outlier, RiskAgent's peer_amount_outlier weight, the
generator's peer_outlier anomaly type, and consolidated_insights surfacing.
"""
from __future__ import annotations

import statistics
from datetime import date, datetime, timezone

import pytest

from adapters.embeddings import SimulatedEmbeddingClient
from common.policy import load_policy_rules
from common.schemas import (
    AuditState,
    ReportLine,
    RoutingDecision,
    SourceSystem,
    SubmissionCreatedEvent,
    VerificationResult,
)
from dashboard.queries import consolidated_insights
from generator.config import load_generator_config
from generator.synthesize import Synthesizer
from integration.ingest import IngestService
from pipeline.agents.risk import RiskAgent
from pipeline.agents.verification import VerificationAgent
from pipeline.checkpoint import build_memory_checkpointer
from pipeline.config import PeerOutlierConfig, load_pipeline_config
from pipeline.factory import build_pipeline


def _event(sid, oe, employee_id, category, amount, currency="EUR") -> SubmissionCreatedEvent:
    return SubmissionCreatedEvent(
        submission_id=sid, source_system=SourceSystem.simulation_harness,
        source_system_ref=sid, oe_code=oe, employee_id=employee_id, currency=currency,
        submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        report_lines=[ReportLine(line_id="LN-1", category=category, entered_amount=amount,
                                  receipt_url=f"blob://{sid}/LN-1")],
    )


# --------------------------------------------------------------------------- #
# AuditStore.category_amount_stats
def test_category_amount_stats_empty(data_layer):
    stats = data_layer.store.category_amount_stats("DE", "meals")
    assert stats == {"mean": 0.0, "stddev": 0.0, "n": 0}


def test_category_amount_stats_computes_population_mean_and_stddev(data_layer):
    amounts = [20.0, 22.0, 18.0, 25.0, 21.0]
    for i, amt in enumerate(amounts):
        ev = _event(f"SUB-STAT-{i}", "DE", f"EMP-{i}", "meals", amt)
        data_layer.store.save_submission(ev, is_synthetic=True)
        data_layer.store.save_report_lines(
            ev.submission_id, [("LN-1", "meals", amt, "EUR")]
        )
    stats = data_layer.store.category_amount_stats("DE", "meals")
    assert stats["n"] == 5
    assert stats["mean"] == pytest.approx(statistics.fmean(amounts))
    assert stats["stddev"] == pytest.approx(statistics.pstdev(amounts))


def test_category_amount_stats_excludes_one_employee(data_layer):
    for i, amt in enumerate([10.0, 12.0, 11.0]):
        ev = _event(f"SUB-EXC-{i}", "US", f"EMP-PEER-{i}", "lodging", amt, currency="USD")
        data_layer.store.save_submission(ev, is_synthetic=True)
        data_layer.store.save_report_lines(ev.submission_id, [("LN-1", "lodging", amt, "USD")])
    # This employee's own huge outlier line must not appear in their own baseline.
    ev = _event("SUB-EXC-SELF", "US", "EMP-SELF", "lodging", 999.0, currency="USD")
    data_layer.store.save_submission(ev, is_synthetic=True)
    data_layer.store.save_report_lines(ev.submission_id, [("LN-1", "lodging", 999.0, "USD")])

    stats = data_layer.store.category_amount_stats("US", "lodging", exclude_employee_id="EMP-SELF")
    assert stats["n"] == 3
    assert stats["mean"] == pytest.approx(statistics.fmean([10.0, 12.0, 11.0]))

    unfiltered = data_layer.store.category_amount_stats("US", "lodging")
    assert unfiltered["n"] == 4


def test_category_amount_stats_scoped_by_oe_and_category(data_layer):
    ev1 = _event("SUB-SCOPE-1", "DE", "EMP-1", "meals", 20.0)
    data_layer.store.save_submission(ev1, is_synthetic=True)
    data_layer.store.save_report_lines(ev1.submission_id, [("LN-1", "meals", 20.0, "EUR")])
    # Different OE - must not leak into DE's baseline.
    ev2 = _event("SUB-SCOPE-2", "US", "EMP-2", "meals", 500.0, currency="USD")
    data_layer.store.save_submission(ev2, is_synthetic=True)
    data_layer.store.save_report_lines(ev2.submission_id, [("LN-1", "meals", 500.0, "USD")])
    # Different category - must not leak into meals' baseline.
    ev3 = _event("SUB-SCOPE-3", "DE", "EMP-3", "lodging", 500.0)
    data_layer.store.save_submission(ev3, is_synthetic=True)
    data_layer.store.save_report_lines(ev3.submission_id, [("LN-1", "lodging", 500.0, "EUR")])

    stats = data_layer.store.category_amount_stats("DE", "meals")
    assert stats == {"mean": 20.0, "stddev": 0.0, "n": 1}


# --------------------------------------------------------------------------- #
# VerificationAgent._peer_outlier
@pytest.fixture()
def verification_agent(data_layer):
    return VerificationAgent(
        data_layer.blobs, SimulatedEmbeddingClient(8), data_layer.vectors, store=data_layer.store,
    )


def test_peer_outlier_flags_when_z_score_exceeds_threshold(verification_agent, data_layer):
    for i, amt in enumerate([20.0, 22.0, 18.0, 21.0, 19.0, 20.0, 21.0, 19.0, 20.0, 22.0]):
        ev = _event(f"SUB-PEER-BASE-{i}", "DE", f"EMP-BASE-{i}", "meals", amt)
        data_layer.store.save_submission(ev, is_synthetic=True)
        data_layer.store.save_report_lines(ev.submission_id, [("LN-1", "meals", amt, "EUR")])

    cfg = PeerOutlierConfig(enabled=True, z_score_threshold=2.5, min_peer_sample_size=10)
    outlier_event = _event("SUB-PEER-TEST", "DE", "EMP-OUTLIER", "meals", 500.0)
    flags = verification_agent._peer_outlier(outlier_event, cfg)
    assert len(flags) == 1
    assert "meals" in flags[0]
    assert "std-dev above" in flags[0]


def test_peer_outlier_no_flag_below_threshold(verification_agent, data_layer):
    for i, amt in enumerate([20.0, 22.0, 18.0, 21.0, 19.0, 20.0, 21.0, 19.0, 20.0, 22.0]):
        ev = _event(f"SUB-PEER-OK-{i}", "DE", f"EMP-OK-{i}", "meals", amt)
        data_layer.store.save_submission(ev, is_synthetic=True)
        data_layer.store.save_report_lines(ev.submission_id, [("LN-1", "meals", amt, "EUR")])

    cfg = PeerOutlierConfig(enabled=True, z_score_threshold=2.5, min_peer_sample_size=10)
    normal_event = _event("SUB-PEER-NORMAL", "DE", "EMP-NORMAL", "meals", 21.0)
    assert verification_agent._peer_outlier(normal_event, cfg) == []


def test_peer_outlier_guards_thin_peer_sample(verification_agent, data_layer):
    # Only 3 peers - well under min_peer_sample_size, even though the amount
    # would clear the z-score threshold against such a tiny/unstable baseline.
    for i, amt in enumerate([20.0, 21.0, 19.0]):
        ev = _event(f"SUB-PEER-THIN-{i}", "DE", f"EMP-THIN-{i}", "meals", amt)
        data_layer.store.save_submission(ev, is_synthetic=True)
        data_layer.store.save_report_lines(ev.submission_id, [("LN-1", "meals", amt, "EUR")])

    cfg = PeerOutlierConfig(enabled=True, z_score_threshold=2.5, min_peer_sample_size=10)
    outlier_event = _event("SUB-PEER-THIN-TEST", "DE", "EMP-THIN-TEST", "meals", 500.0)
    assert verification_agent._peer_outlier(outlier_event, cfg) == []


def test_peer_outlier_disabled_returns_no_flags(verification_agent, data_layer):
    for i, amt in enumerate([20.0] * 15):
        ev = _event(f"SUB-PEER-DIS-{i}", "DE", f"EMP-DIS-{i}", "meals", amt)
        data_layer.store.save_submission(ev, is_synthetic=True)
        data_layer.store.save_report_lines(ev.submission_id, [("LN-1", "meals", amt, "EUR")])

    cfg = PeerOutlierConfig(enabled=False, z_score_threshold=2.5, min_peer_sample_size=10)
    outlier_event = _event("SUB-PEER-DIS-TEST", "DE", "EMP-DIS-TEST", "meals", 500.0)
    assert verification_agent._peer_outlier(outlier_event, cfg) == []


def test_peer_outlier_no_store_degrades_quietly():
    agent = VerificationAgent(None, SimulatedEmbeddingClient(8), None, store=None)
    cfg = PeerOutlierConfig(enabled=True, z_score_threshold=2.5, min_peer_sample_size=10)
    event = _event("SUB-NO-STORE", "DE", "EMP-1", "meals", 500.0)
    assert agent._peer_outlier(event, cfg) == []


# --------------------------------------------------------------------------- #
# RiskAgent weight wiring
def test_risk_agent_applies_peer_outlier_weight():
    state = AuditState(submission_id="SUB-RISK-1")
    state.verification = VerificationResult(peer_outlier_flags=["meals: 500.00 EUR is 12.0 std-dev above..."])
    event = _event("SUB-RISK-1", "DE", "EMP-1", "meals", 500.0)
    RiskAgent().run(state, event)
    weight = load_pipeline_config().risk.weights["peer_amount_outlier"]
    assert state.risk_score >= weight
    assert "peer-group outlier" in state.explanation


# --------------------------------------------------------------------------- #
# consolidated_insights surfacing
def test_consolidated_insights_surfaces_peer_outlier():
    rows = {
        "verification": [{"submission_id": "SUB-1", "peer_outlier_flags": ["meals: unusual"]}],
        "policy_evaluations": [],
        "extracted_line_items": [],
    }
    insights = consolidated_insights("SUB-1", rows, subtotal_tol=10.0, conf_cutoff=0.7)
    kinds = {i["type"] for i in insights}
    assert "peer_outlier" in kinds


# --------------------------------------------------------------------------- #
# Generator: peer_outlier anomaly type is injected, labeled, and inflated
def test_generator_injects_peer_outlier_anomaly():
    cfg = load_generator_config().model_copy(update={
        "volume": 40, "seed": 77,
        "anomaly_injection": load_generator_config().anomaly_injection.model_copy(
            update={"peer_outlier_rate": 0.25, "duplicate_rate": 0.0,
                    "policy_violation_rate": 0.0, "manipulated_receipt_rate": 0.0}
        ),
    })
    rules = load_policy_rules()

    class _NullBlobs:
        def put(self, key, data, content_type="application/octet-stream"):
            return f"blob://{key}"

        def get(self, url):
            return b""

    synth = Synthesizer(cfg, rules, _NullBlobs())
    _events, gt = synth.generate()

    outliers = [s for s in gt.submissions if s.peer_outlier]
    normals = [s for s in gt.submissions if not s.peer_outlier and s.policy.verdict == "pass"
               and not s.manipulated and s.is_duplicate_of is None]
    assert outliers  # the 25% rate over 40 submissions must inject at least one
    assert normals

    # Every peer_outlier submission's line amounts must be inflated relative
    # to what a normal line in the same category would plausibly be.
    avg_normal = statistics.fmean(l.amount for s in normals for l in s.lines)
    avg_outlier = statistics.fmean(l.amount for s in outliers for l in s.lines)
    assert avg_outlier > avg_normal * 2  # comfortably above, given a 6x config multiplier

    # peer_outlier is orthogonal to `manipulated` (never both) - but NOT
    # orthogonal to the amount_cap policy check: the multiplier can (and, for
    # a capped category, almost always does) push the amount over that
    # category's cap too, which ground truth must reflect (see the elif
    # peer_outlier: branch in _make_fresh) so PolicyAgent's own independent
    # cap check agrees with ground truth - not something this generator
    # should hide.
    for s in outliers:
        assert s.manipulated is False


# --------------------------------------------------------------------------- #
# End-to-end: generate a real population, ingest through the full pipeline,
# and confirm the peer-outlier submission is genuinely flagged in storage.
def test_end_to_end_peer_outlier_flagged_through_pipeline(data_layer, sim_settings):
    base = load_generator_config()
    cfg = base.model_copy(update={
        "volume": 120, "seed": 321,
        # Concentrate every submission into one OE + one category (one line
        # each) so peer volume in that single bucket grows deterministically
        # with ingestion order (submission i has i prior peers) - spreading
        # across the default 3 OEs x 5 categories would leave most buckets
        # under min_peer_sample_size (10) for most of the run.
        "oe_codes": ["DE"],
        "categories": ["meals"],
        "lines_per_submission": base.lines_per_submission.model_copy(update={"min": 1, "max": 1}),
        "anomaly_injection": base.anomaly_injection.model_copy(
            update={"peer_outlier_rate": 0.05, "duplicate_rate": 0.0,
                    "policy_violation_rate": 0.0, "manipulated_receipt_rate": 0.0}
        ),
    })
    rules = load_policy_rules()
    synth = Synthesizer(cfg, rules, data_layer.blobs)
    events, gt = synth.generate()

    pipeline = build_pipeline(data_layer, sim_settings, checkpointer=build_memory_checkpointer())
    ingest = IngestService(data_layer.store, pipeline, is_synthetic=True)
    for ev in events:
        ingest.handle(ev)

    outlier_sids = {s.submission_id for s in gt.submissions if s.peer_outlier}
    assert outlier_sids

    rows = data_layer.store.analytics_rows()
    ver_by_sid = {v["submission_id"]: v for v in rows["verification"]}
    risk_by_sid = {r["submission_id"]: r for r in rows["risk_decisions"]}

    flagged_count = sum(
        1 for sid in outlier_sids if ver_by_sid.get(sid, {}).get("peer_outlier_flags")
    )
    assert flagged_count > 0  # the live-computed peer baseline genuinely caught it

    for sid in outlier_sids:
        if ver_by_sid.get(sid, {}).get("peer_outlier_flags"):
            assert "peer-group outlier" in (risk_by_sid.get(sid, {}).get("explanation") or "")
