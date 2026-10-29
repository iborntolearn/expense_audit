"""Simulation Harness - the mock T&E system (Solution Design 5.10, 7.4).

Replays a generated run, emitting each submission through the identical webhook
schema a live T&E system would use. Nothing downstream is aware the events are
synthetic - that is the whole point of the SIMULATION_MODE design: swapping the
harness for a live connector is a substitution, not a rewrite.
"""
from __future__ import annotations

import logging

from generator.run import GeneratedRun, load_run_events
from integration.bus import EventBus

logger = logging.getLogger("integration.harness")


class SimulationHarness:
    def __init__(self, bus: EventBus):
        self._bus = bus

    def replay(self, run: GeneratedRun) -> int:
        """Emit every submission in `run` onto the bus. Returns count emitted."""
        events = load_run_events(run)
        logger.info("harness replaying %d submissions from %s", len(events), run.run_id)
        for ev in events:
            self._bus.publish(ev)
        return len(events)
