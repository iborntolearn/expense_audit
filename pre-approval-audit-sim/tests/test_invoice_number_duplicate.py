"""Structured invoice-number duplicate matching - AuditStore.
find_by_vendor_invoice, VerificationAgent._duplicate's second match path, and
RiskAgent's duplicate_match_structured weight. Complements the existing
embedding-only duplicate detection (tests/test_agents_accuracy.py) rather than
replacing it - a resubmission whose image is edited enough to drop embedding
similarity below threshold should still be caught if its printed invoice
number is identical to a prior submission's.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from adapters.embeddings import SimulatedEmbeddingClient
from common.schemas import (
    AuditState,
    ExtractedLine,
    ReportLine,
    SourceSystem,
    SubmissionCreatedEvent,
    VerificationResult,
)
from pipeline.agents.risk import RiskAgent
from pipeline.agents.verification import VerificationAgent
from pipeline.config import load_pipeline_config


def _event(sid, employee_id="EMP-1", oe="DE", currency="EUR") -> SubmissionCreatedEvent:
    return SubmissionCreatedEvent(
        submission_id=sid, source_system=SourceSystem.simulation_harness,
        source_system_ref=sid, oe_code=oe, employee_id=employee_id, currency=currency,
        submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        report_lines=[ReportLine(line_id="LN-1", category="meals", entered_amount=50.0,
                                  receipt_url=f"blob://{sid}/LN-1")],
    )


def _seed_line(data_layer, sid, *, vendor, invoice_number, amount=50.0, employee_id="EMP-1"):
    ev = _event(sid, employee_id=employee_id)
    data_layer.store.save_submission(ev, is_synthetic=True)
    data_layer.store.save_extracted_lines(sid, [
        ExtractedLine(line_id="LN-1", vendor=vendor, invoice_number=invoice_number, amount=amount,
                      tax=0.0, currency="EUR", confidence=1.0),
    ])


# --------------------------------------------------------------------------- #
# AuditStore.find_by_vendor_invoice
def test_find_by_vendor_invoice_exact_match(data_layer):
    _seed_line(data_layer, "SUB-A", vendor="Acme Travel", invoice_number="INV-100")
    rows = data_layer.store.find_by_vendor_invoice(
        "Acme Travel", "INV-100", exclude_submission_id="SUB-B",
    )
    assert [r["submission_id"] for r in rows] == ["SUB-A"]


def test_find_by_vendor_invoice_case_and_whitespace_insensitive(data_layer):
    _seed_line(data_layer, "SUB-A", vendor="  Acme Travel  ", invoice_number=" inv-100 ")
    rows = data_layer.store.find_by_vendor_invoice(
        "ACME TRAVEL", "INV-100", exclude_submission_id="SUB-B",
    )
    assert len(rows) == 1


def test_find_by_vendor_invoice_excludes_self(data_layer):
    _seed_line(data_layer, "SUB-A", vendor="Acme Travel", invoice_number="INV-100")
    rows = data_layer.store.find_by_vendor_invoice(
        "Acme Travel", "INV-100", exclude_submission_id="SUB-A",
    )
    assert rows == []


def test_find_by_vendor_invoice_no_match(data_layer):
    _seed_line(data_layer, "SUB-A", vendor="Acme Travel", invoice_number="INV-100")
    rows = data_layer.store.find_by_vendor_invoice(
        "Acme Travel", "INV-999", exclude_submission_id="SUB-B",
    )
    assert rows == []


# --------------------------------------------------------------------------- #
# VerificationAgent._duplicate - structured match path
@pytest.fixture()
def verification_agent(data_layer):
    return VerificationAgent(
        data_layer.blobs, SimulatedEmbeddingClient(8), data_layer.vectors, store=data_layer.store,
    )


@pytest.fixture()
def verification_cfg():
    return load_pipeline_config().verification


def test_structured_match_fires_despite_low_embedding_similarity(
    verification_agent, verification_cfg, data_layer,
):
    # Prior submission: same vendor+invoice_number, but a very different
    # amount/category so embedding similarity alone would never clear
    # duplicate_similarity_threshold.
    _seed_line(data_layer, "SUB-PRIOR", vendor="Acme Travel", invoice_number="INV-777", amount=12.34)

    state = AuditState(submission_id="SUB-NEW")
    state.extracted_lines = [
        ExtractedLine(line_id="LN-1", vendor="Acme Travel", invoice_number="INV-777",
                      amount=999.0, tax=0.0, currency="EUR", confidence=1.0),
    ]
    event = _event("SUB-NEW")
    matches = verification_agent._duplicate(state, event, verification_cfg)
    assert len(matches) == 1
    assert matches[0].submission_id == "SUB-PRIOR"
    assert matches[0].match_type == "invoice_number"
    assert matches[0].similarity == 1.0


def test_no_invoice_number_never_forces_a_match(verification_agent, verification_cfg):
    state = AuditState(submission_id="SUB-NEW")
    state.extracted_lines = [
        ExtractedLine(line_id="LN-1", vendor="Acme Travel", invoice_number=None,
                      amount=50.0, tax=0.0, currency="EUR", confidence=1.0),
    ]
    event = _event("SUB-NEW")
    matches = verification_agent._duplicate(state, event, verification_cfg)
    assert matches == []


def test_vendor_matches_but_invoice_differs_no_structured_match(
    verification_agent, verification_cfg, data_layer,
):
    _seed_line(data_layer, "SUB-PRIOR", vendor="Acme Travel", invoice_number="INV-777", amount=12.34)

    state = AuditState(submission_id="SUB-NEW")
    state.extracted_lines = [
        ExtractedLine(line_id="LN-1", vendor="Acme Travel", invoice_number="INV-DIFFERENT",
                      amount=999.0, tax=0.0, currency="EUR", confidence=1.0),
    ]
    event = _event("SUB-NEW")
    matches = verification_agent._duplicate(state, event, verification_cfg)
    assert matches == []


def test_no_store_degrades_quietly(verification_cfg, data_layer):
    # store=None only needs to guard the NEW invoice-number path here - the
    # pre-existing embedding path still needs a real vector index regardless
    # (it's unconditional, same as before this feature), so use data_layer's.
    agent = VerificationAgent(data_layer.blobs, SimulatedEmbeddingClient(8), data_layer.vectors, store=None)
    state = AuditState(submission_id="SUB-NEW")
    state.extracted_lines = [
        ExtractedLine(line_id="LN-1", vendor="Acme Travel", invoice_number="INV-777",
                      amount=999.0, tax=0.0, currency="EUR", confidence=1.0),
    ]
    event = _event("SUB-NEW")
    assert agent._duplicate(state, event, verification_cfg) == []


# --------------------------------------------------------------------------- #
# RiskAgent - duplicate_match_structured weight
def test_risk_agent_scores_structured_match_higher_than_embedding_only():
    weights = load_pipeline_config().risk.weights
    assert "duplicate_match_structured" in weights

    embedding_state = AuditState(submission_id="SUB-EMB")
    embedding_state.verification = VerificationResult(
        duplicate_matches=[{"submission_id": "SUB-OTHER", "similarity": 0.95, "match_type": "embedding"}],
    )
    RiskAgent().run(embedding_state, _event("SUB-EMB"))

    structured_state = AuditState(submission_id="SUB-STRUCT")
    structured_state.verification = VerificationResult(
        duplicate_matches=[{"submission_id": "SUB-OTHER", "similarity": 1.0, "match_type": "invoice_number"}],
    )
    RiskAgent().run(structured_state, _event("SUB-STRUCT"))

    assert structured_state.risk_score > embedding_state.risk_score
    assert "structured invoice-number match" in structured_state.explanation
