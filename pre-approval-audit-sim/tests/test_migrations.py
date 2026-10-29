"""Milestone 1 exit criterion: all DDL tables (incl. is_synthetic) created;
vector store table present."""
from __future__ import annotations

EXPECTED_TABLES = {
    "submissions",
    "extracted_line_items",
    "verification_results",
    "policy_evaluations",
    "risk_decisions",
    "reviewer_actions",
    "receipt_embeddings",
}


def test_all_tables_created(data_layer):
    tables = set(data_layer.store.table_names())
    assert EXPECTED_TABLES.issubset(tables), f"missing: {EXPECTED_TABLES - tables}"


def test_health_true_after_migrate(data_layer):
    assert data_layer.health() is True


def test_is_synthetic_column_present(data_layer):
    # Insert a synthetic submission and read it back with the flag set.
    from datetime import datetime

    from common.schemas import SourceSystem, SubmissionCreatedEvent

    event = SubmissionCreatedEvent(
        submission_id="SUB-TEST-1",
        source_system=SourceSystem.simulation_harness,
        source_system_ref="SIM-1",
        oe_code="DE",
        employee_id="EMP-1",
        cost_center="CC-1",
        currency="EUR",
        submitted_at=datetime(2026, 7, 16, 8, 41, 0),
        report_lines=[],
    )
    data_layer.store.save_submission(event, is_synthetic=True)
    row = data_layer.store.get_submission("SUB-TEST-1")
    assert row is not None
    assert row["is_synthetic"] in (1, True)
    assert row["source_system"] == "simulation_harness"


def test_vector_index_roundtrip(data_layer, sim_settings):
    dim = sim_settings.embedding_dim
    a = [1.0] + [0.0] * (dim - 1)
    b = [0.9] + [0.1] * (dim - 1)
    c = [0.0] * (dim - 1) + [1.0]

    # Parent rows for FK integrity: receipt_embeddings.line_item_id references
    # extracted_line_items, which itself references submissions. This mirrors
    # the real pipeline ordering (extraction populates line items before
    # verification computes embeddings).
    from datetime import datetime

    from common.schemas import (
        AuditState,
        ExtractedLine,
        SourceSystem,
        SubmissionCreatedEvent,
    )

    for sid, lid in (("SUB-A", "LI-A"), ("SUB-B", "LI-B"), ("SUB-C", "LI-C")):
        data_layer.store.save_submission(
            SubmissionCreatedEvent(
                submission_id=sid,
                source_system=SourceSystem.simulation_harness,
                source_system_ref=f"SIM-{sid}",
                oe_code="DE",
                employee_id="EMP-1",
                currency="EUR",
                submitted_at=datetime(2026, 7, 16, 8, 41, 0),
                report_lines=[],
            ),
            is_synthetic=True,
        )
        data_layer.store.save_audit_state(
            AuditState(
                submission_id=sid,
                extracted_lines=[ExtractedLine(line_id=lid, confidence=0.9)],
            ),
            rule_version="policy-set-DE-2026-06",
            model_version="risk-router-v1.3",
        )

    from common.ids import line_item_id

    data_layer.vectors.upsert(line_item_id("SUB-A", "LI-A"), "SUB-A", "EMP-1", a)
    data_layer.vectors.upsert(line_item_id("SUB-B", "LI-B"), "SUB-B", "EMP-1", b)
    data_layer.vectors.upsert(line_item_id("SUB-C", "LI-C"), "SUB-C", "EMP-1", c)

    results = data_layer.vectors.search(a, k=2)
    assert results[0].submission_id == "SUB-A"  # exact match ranks first
    assert results[1].submission_id == "SUB-B"  # near-duplicate second

    excl = data_layer.vectors.search(a, k=2, exclude_submission_id="SUB-A")
    assert all(m.submission_id != "SUB-A" for m in excl)
    assert excl[0].submission_id == "SUB-B"
