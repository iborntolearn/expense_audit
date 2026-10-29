"""Generate and persist a full synthetic run.

Layout under <repo>/.data/synthetic/<run_id>/:
    submissions/<submission_id>.json   one webhook payload each
    ground_truth.json                  exact expected values (GroundTruth)
    manifest.json                      run config + counts
Receipt artifacts are written to the BlobStore (blob://...), referenced by
receipt_url in each submission.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from common.policy import load_policy_rules
from common.schemas import SubmissionCreatedEvent
from config.settings import Settings, get_settings
from data.factory import build_data_layer
from generator.config import GeneratorConfig, load_generator_config
from generator.ground_truth import GroundTruth
from generator.synthesize import Synthesizer


@dataclass(frozen=True)
class GeneratedRun:
    run_dir: Path
    run_id: str
    n_submissions: int
    n_duplicates: int
    n_policy_violations: int
    n_manipulated: int

    @property
    def submissions_dir(self) -> Path:
        return self.run_dir / "submissions"

    @property
    def ground_truth_path(self) -> Path:
        return self.run_dir / "ground_truth.json"

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / "manifest.json"


def _run_dir(settings: Settings, run_id: str) -> Path:
    return settings.resolve(f"./.data/synthetic/{run_id}")


def generate_run(
    settings: Settings | None = None,
    config: GeneratorConfig | None = None,
) -> GeneratedRun:
    settings = settings or get_settings()
    config = config or load_generator_config()
    rules = load_policy_rules()

    data = build_data_layer(settings)
    try:
        synth = Synthesizer(config, rules, data.blobs)
        events, gt = synth.generate()
    finally:
        data.close()

    run_dir = _run_dir(settings, config.run_id)
    subs_dir = run_dir / "submissions"
    subs_dir.mkdir(parents=True, exist_ok=True)

    for ev in events:
        (subs_dir / f"{ev.submission_id}.json").write_text(
            ev.model_dump_json(indent=2), encoding="utf-8"
        )
    gt.write(run_dir / "ground_truth.json")

    counts = {
        "n_submissions": len(events),
        "n_duplicates": sum(1 for s in gt.submissions if s.is_duplicate_of),
        "n_policy_violations": sum(1 for s in gt.submissions if s.policy.verdict == "fail"),
        "n_manipulated": sum(1 for s in gt.submissions if s.manipulated),
    }
    manifest = {"run_id": config.run_id, "config": config.model_dump(), **counts}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return GeneratedRun(run_dir=run_dir, run_id=config.run_id, **counts)


def load_run_events(run: GeneratedRun) -> list[SubmissionCreatedEvent]:
    events = []
    for p in sorted(run.submissions_dir.glob("*.json")):
        events.append(SubmissionCreatedEvent.model_validate_json(p.read_text(encoding="utf-8")))
    return events


def find_run(settings: Settings, run_id: str) -> GeneratedRun | None:
    run_dir = _run_dir(settings, run_id)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    return GeneratedRun(
        run_dir=run_dir,
        run_id=m["run_id"],
        n_submissions=m["n_submissions"],
        n_duplicates=m["n_duplicates"],
        n_policy_violations=m["n_policy_violations"],
        n_manipulated=m["n_manipulated"],
    )
