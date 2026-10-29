"""Real (non-simulated) receipt forensics - common/forensics.py's pure
functions, plus proof that a genuinely doctored receipt produced by the
generator's own rendering pipeline (not just a hand-built Pillow fixture) is
caught end-to-end by VerificationAgent, with zero `.sim.json` sidecar
involved."""
from __future__ import annotations

import io
import random
from datetime import date, datetime, timezone

import pytest
from PIL import Image, PngImagePlugin

from common.forensics import (
    analyze_image_metadata,
    analyze_receipt_bytes,
    error_level_analysis,
)
from common.schemas import (
    AuditState,
    ExtractedLine,
    ReportLine,
    SourceSystem,
    SubmissionCreatedEvent,
)
from generator.config import load_generator_config
from generator.synthesize import Synthesizer
from common.policy import load_policy_rules
from adapters.embeddings import SimulatedEmbeddingClient
from pipeline.agents.verification import VerificationAgent


def _smooth_gradient_jpeg(quality: int = 90) -> bytes:
    img = Image.new("RGB", (256, 256))
    px = img.load()
    for x in range(256):
        for y in range(256):
            px[x, y] = (int(100 + x / 4), int(100 + y / 4), 140)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _doctored_jpeg(seed: int = 7, quality: int = 90) -> bytes:
    """Smooth gradient with a high-frequency noise patch pasted in - a real
    quantization-error gap ELA is designed to catch."""
    img = Image.new("RGB", (256, 256))
    px = img.load()
    for x in range(256):
        for y in range(256):
            px[x, y] = (int(100 + x / 4), int(100 + y / 4), 140)
    rng = random.Random(seed)
    for x in range(30, 90):
        for y in range(30, 90):
            px[x, y] = (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


# --------------------------------------------------------------------- image metadata
def test_missing_camera_exif_flagged_only_for_photo_hint():
    clean = _smooth_gradient_jpeg()
    assert analyze_image_metadata(clean, expected_format_hint="photo") == ["missing_exif_camera_data"]
    # An e-receipt/scanned PDF legitimately has no camera EXIF - must never
    # be penalised for it.
    assert analyze_image_metadata(clean, expected_format_hint="e_receipt") == []
    assert analyze_image_metadata(clean, expected_format_hint=None) == []


def test_editing_software_signature_detected():
    img = Image.new("RGB", (100, 100), (50, 50, 50))
    exif = img.getexif()
    exif[305] = "Adobe Photoshop 25.0"  # Software tag
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    flags = analyze_image_metadata(buf.getvalue(), expected_format_hint="photo")
    assert "editing_software_signature" in flags


def test_ai_generator_png_chunk_detected_as_weak_signal():
    img = Image.new("RGB", (100, 100), (10, 20, 30))
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "Steps: 20, Sampler: Euler a, CFG scale: 7")
    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=info)
    flags = analyze_image_metadata(buf.getvalue(), expected_format_hint="photo")
    assert flags == ["ai_generator_metadata_signature"]
    # PNG never gets the missing-camera-EXIF flag, even with a "photo" hint -
    # phone screenshots saved as PNG have no camera-EXIF convention at all.
    assert "missing_exif_camera_data" not in flags


def test_clean_png_has_zero_flags():
    img = Image.new("RGB", (100, 100), (200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    assert analyze_image_metadata(buf.getvalue(), expected_format_hint="photo") == []


# --------------------------------------------------------------------- ELA
def test_ela_clean_jpeg_no_anomaly():
    assert error_level_analysis(_smooth_gradient_jpeg(), diff_threshold=15, region_frac_threshold=0.02) == []


def test_ela_catches_pasted_noise_patch():
    flags = error_level_analysis(_doctored_jpeg(), diff_threshold=15, region_frac_threshold=0.02)
    assert flags == ["ela_local_anomaly"]


def test_ela_skips_non_jpeg():
    img = Image.new("RGB", (100, 100), (1, 2, 3))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    assert error_level_analysis(buf.getvalue()) == []


def test_ela_degrades_quietly_on_garbage_bytes():
    assert error_level_analysis(b"not an image") == []


# --------------------------------------------------------------------- entry point
def test_analyze_receipt_bytes_unions_metadata_and_ela():
    flags = analyze_receipt_bytes(
        _doctored_jpeg(), expected_format_hint="photo",
        ela_diff_threshold=15, ela_region_frac_threshold=0.02,
    )
    assert "ela_local_anomaly" in flags
    assert "missing_exif_camera_data" in flags  # also no camera EXIF on this fixture


def test_analyze_receipt_bytes_clean_e_receipt_zero_flags():
    flags = analyze_receipt_bytes(_smooth_gradient_jpeg(), expected_format_hint="e_receipt")
    assert flags == []


# --------------------------------------------------------------------- end-to-end
@pytest.fixture()
def sim_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite_local")
    monkeypatch.setenv("SIMULATION_MODE", "simulation")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setenv("EMBEDDING_DIM", "8")

    from config.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    yield settings
    get_settings.cache_clear()


@pytest.mark.parametrize("flavor,expected_flag", [
    ("ela_paste", "ela_local_anomaly"),
    ("editing_software_tag", "editing_software_signature"),
])
def test_generator_produced_doctored_receipt_caught_end_to_end(sim_settings, flavor, expected_flag):
    """A receipt rendered by the generator's OWN pipeline (not a hand-built
    fixture), then genuinely doctored via `Synthesizer._apply_fraud_flavor`,
    must be caught by the real forensics check with NO `.sim.json` reliance -
    proving the new checks work against generator-realistic bytes, not just
    synthetic Pillow snippets built directly in this test file."""
    from data.factory import build_data_layer

    data = build_data_layer(sim_settings)
    data.migrate()
    try:
        cfg = load_generator_config().model_copy(update={"volume": 1, "seed": 99})
        rules = load_policy_rules()
        synth = Synthesizer(cfg, rules, data.blobs)

        url = synth._store_receipt(
            run_key="forensics-test/SUB-1/LN-1", vendor="Cafe Nord", txn_d=date(2026, 1, 1),
            currency="EUR", category="meals", net=20.0, line_tax=2.0, lang="en",
            manipulated=False, fraud_flavor=flavor,
        )

        embeddings = SimulatedEmbeddingClient(sim_settings.embedding_dim)
        agent = VerificationAgent(data.blobs, embeddings, data.vectors)

        event = SubmissionCreatedEvent(
            submission_id="SUB-FORENSICS-1", source_system=SourceSystem.simulation_harness,
            source_system_ref="SUB-FORENSICS-1", oe_code="DE", employee_id="EMP-1",
            currency="EUR", submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            report_lines=[ReportLine(line_id="LN-1", category="meals", entered_amount=22.0, receipt_url=url)],
        )
        state = AuditState(
            submission_id=event.submission_id,
            extracted_lines=[ExtractedLine(line_id="LN-1", vendor="Cafe Nord", date=date(2026, 1, 1),
                                            amount=20.0, tax=2.0, confidence=0.9)],
        )
        agent.run(state, event)
        assert expected_flag in state.verification.authenticity_flags
    finally:
        data.close()
