"""End-to-end batch replay (Milestone 3 exit criterion).

Generates a run if needed, then has the Simulation Harness replay every
submission through the ingest service and (stub) pipeline, writing a decision to
the store for each. Prints a routing-decision summary.

Usage (from repo root):
    python scripts/run_batch.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings  # noqa: E402
from data.factory import build_data_layer  # noqa: E402
from generator.config import load_generator_config  # noqa: E402
from generator.run import find_run, generate_run  # noqa: E402
from integration.bus import InProcessBus  # noqa: E402
from integration.harness import SimulationHarness  # noqa: E402
from integration.ingest import IngestService  # noqa: E402
from pipeline.factory import build_pipeline  # noqa: E402


def main() -> int:
    settings = get_settings()
    cfg = load_generator_config()

    run = find_run(settings, cfg.run_id)
    if run is None:
        print("no existing run found; generating…")
        run = generate_run(settings, cfg)

    data = build_data_layer(settings)
    data.migrate()
    try:
        pipeline = build_pipeline(data, settings)
        ingest = IngestService(
            data.store,
            pipeline,
            is_synthetic=settings.is_synthetic_data,
        )
        counts: Counter = Counter()

        def handler(event) -> None:
            result = ingest.handle(event)
            if result.accepted and result.state and result.state.routing_decision:
                counts[result.state.routing_decision.value] += 1
            else:
                counts[result.reason] += 1

        bus = InProcessBus()
        bus.subscribe(handler)
        emitted = SimulationHarness(bus).replay(run)
    finally:
        data.close()

    print(f"replayed {emitted} submissions from {run.run_id}")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
