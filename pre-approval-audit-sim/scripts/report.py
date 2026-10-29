"""Generate the accuracy & latency report (Milestone 10).

Runs a full batch through the pipeline (capturing per-node latency + states),
scores it against config/thresholds.yaml, and writes report.md + report.json
under the run directory. Uses an in-memory checkpointer so the report is
repeatable and does not pollute the durable checkpoint store.

Usage (from repo root):
    python scripts/report.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from common.policy import load_policy_rules  # noqa: E402
from common.schemas import AuditState, ExtractedLine  # noqa: E402
from config.settings import REPO_ROOT, get_settings  # noqa: E402
from data.factory import build_data_layer  # noqa: E402
from evaluation.latency import LatencySink  # noqa: E402
from evaluation.report import build_report  # noqa: E402
from generator.config import load_generator_config  # noqa: E402
from generator.synthesize import Synthesizer  # noqa: E402
from pipeline.agents.policy import PolicyAgent  # noqa: E402
from pipeline.checkpoint import build_memory_checkpointer  # noqa: E402
from pipeline.factory import build_pipeline  # noqa: E402


def _clean_policy_verdicts(gt, events, rules) -> dict:
    """Deterministic engine verdicts on ground-truth-true inputs (M6 metric:
    engine correctness independent of extraction noise)."""
    agent = PolicyAgent(rules)
    by_id = {e.submission_id: e for e in events}
    verdicts: dict[str, tuple[bool, set]] = {}
    for s in gt.submissions:
        ev = by_id[s.submission_id]
        state = AuditState(submission_id=s.submission_id)
        state.extracted_lines = [
            ExtractedLine(line_id=gl.line_id, vendor=gl.vendor, amount=gl.amount,
                          tax=gl.tax, currency=gl.currency, confidence=1.0)
            for gl in s.lines
        ]
        agent.run(state, ev)
        failed = {rr.rule_id for rr in state.policy_evaluation.rule_results if not rr.passed}
        verdicts[s.submission_id] = (bool(failed), failed)
    return verdicts


def main() -> int:
    settings = get_settings()
    gen_cfg = load_generator_config()
    rules = load_policy_rules()
    thresholds = yaml.safe_load(
        (REPO_ROOT / "config" / "thresholds.yaml").read_text(encoding="utf-8")
    )

    data = build_data_layer(settings)
    data.migrate()
    events, gt = Synthesizer(gen_cfg, rules, data.blobs).generate()

    sink = LatencySink()
    pipeline = build_pipeline(
        data, settings, checkpointer=build_memory_checkpointer(), latency_sink=sink
    )

    states = {}
    for ev in events:
        data.store.save_submission(ev, is_synthetic=True)
        data.store.save_receipt_refs(
            ev.submission_id, [(l.line_id, l.receipt_url) for l in ev.report_lines]
        )
        states[ev.submission_id] = pipeline.run(ev)
    data.close()

    report = build_report(
        gt, states, sink.summary(), thresholds,
        policy_verdicts=_clean_policy_verdicts(gt, events, rules),
    )

    run_dir = settings.resolve(f"./.data/synthetic/{gen_cfg.run_id}")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.md").write_text(report.to_markdown(), encoding="utf-8")
    (run_dir / "report.json").write_text(report.to_json(), encoding="utf-8")

    print(report.to_markdown())
    print(f"\nwritten: {run_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
