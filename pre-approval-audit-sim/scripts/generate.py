"""Generate a synthetic run (Milestone 2).

Usage (from repo root):
    python scripts/generate.py
Reads config/generator.yaml and config/policy_rules.yaml; writes submissions,
receipts (blob store), and ground_truth.json under .data/synthetic/<run_id>/.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generator.run import generate_run  # noqa: E402


def main() -> int:
    run = generate_run()
    print(f"generated run: {run.run_id}")
    print(f"  dir:               {run.run_dir}")
    print(f"  submissions:       {run.n_submissions}")
    print(f"  duplicates:        {run.n_duplicates}")
    print(f"  policy violations: {run.n_policy_violations}")
    print(f"  manipulated:       {run.n_manipulated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
