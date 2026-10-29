"""Latency capture for the reporting harness.

`run_node` already times every node; a LatencySink just collects those timings
(per node, and end-to-end per submission) so the reporter can compute
percentiles. Passing a sink is opt-in and never changes pipeline behaviour.
"""
from __future__ import annotations

from collections import defaultdict


class LatencySink:
    def __init__(self) -> None:
        self._by_node: dict[str, list[float]] = defaultdict(list)
        self._end_to_end: list[float] = []

    def record_node(self, node: str, latency_s: float) -> None:
        self._by_node[node].append(latency_s)

    def record_end_to_end(self, latency_s: float) -> None:
        self._end_to_end.append(latency_s)

    @staticmethod
    def _percentile(values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        # nearest-rank percentile
        k = max(0, min(len(s) - 1, int(round(pct / 100.0 * (len(s) - 1)))))
        return s[k]

    def summary(self) -> dict:
        nodes = {}
        for node, vals in self._by_node.items():
            nodes[node] = {
                "count": len(vals),
                "p50_s": round(self._percentile(vals, 50), 4),
                "p95_s": round(self._percentile(vals, 95), 4),
                "max_s": round(max(vals), 4) if vals else 0.0,
            }
        return {
            "per_node": nodes,
            "end_to_end": {
                "count": len(self._end_to_end),
                "p50_s": round(self._percentile(self._end_to_end, 50), 4),
                "p95_s": round(self._percentile(self._end_to_end, 95), 4),
                "max_s": round(max(self._end_to_end), 4) if self._end_to_end else 0.0,
            },
        }
