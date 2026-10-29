"""Deep Receipt Understanding: itemization distinguishes alcohol from meals
(not just lumping every food/drink line under "meals"), and extraction
reports a detected_language for audit traceability - real behavior, not just
the underlying vision model's inherent (untested-here) multilingual OCR
capability."""
from __future__ import annotations

from datetime import date

import pytest

from adapters.factory import build_vision_extractor
from adapters.vision import ITEMIZE_CATEGORIES, _clamp_category
from common.policy import load_policy_rules
from generator.config import load_generator_config
from generator.receipts import _LABELS, render, ReceiptLine
from generator.synthesize import Synthesizer
from pipeline.config import load_pipeline_config


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


def test_itemize_categories_include_alcohol_distinct_from_meals():
    assert "alcohol" in ITEMIZE_CATEGORIES
    assert "meals" in ITEMIZE_CATEGORIES
    assert _clamp_category("alcohol", ITEMIZE_CATEGORIES) == "alcohol"
    assert _clamp_category("wine", ITEMIZE_CATEGORIES) == "misc"  # off-list guess never silently accepted


def test_alcohol_policy_rule_applies_to_the_itemize_category():
    """ITEMIZE_CATEGORIES' "alcohol" value must be the exact string
    policy_rules.yaml's ALCOHOL-PROHIBITED-01 matches on - otherwise an
    itemized alcohol line would silently skip the prohibited-category check."""
    rules = load_policy_rules()
    alcohol_rules = [r for r in rules.rules if r.applies_to.category == "alcohol"]
    assert alcohol_rules, "expected at least one policy_rules.yaml rule scoped to category=alcohol"


@pytest.mark.parametrize("lang", ["en", "de", "fr", "es", "it"])
def test_receipt_labels_exist_for_every_configured_language(lang):
    gen_cfg = load_generator_config()
    assert lang in gen_cfg.language_mix
    assert lang in _LABELS
    # Rendering must not raise for any configured language.
    rendered = render(
        "e_receipt", vendor="Test Vendor", txn_date=date(2026, 1, 1), currency="EUR",
        lines=[ReceiptLine(description="meals", amount=20.0)], tax=2.0, printed_total=22.0, lang=lang,
    )
    assert rendered.data


def test_itemization_distinguishes_alcohol_from_meals_and_reports_language(sim_settings):
    """End-to-end: a receipt the generator's own rendering pipeline produced
    (French labels, category=alcohol) is re-read by the real extraction
    adapter (simulated provider) and comes back correctly categorised and
    language-tagged - not silently lumped into "misc"/"meals" or missing a
    language altogether."""
    from data.factory import build_data_layer

    data = build_data_layer(sim_settings)
    data.migrate()
    try:
        cfg = load_generator_config().model_copy(update={"volume": 1, "seed": 42})
        rules = load_policy_rules()
        synth = Synthesizer(cfg, rules, data.blobs)

        url = synth._store_receipt(
            run_key="deep-understanding-test/SUB-1/LN-1", vendor="Trattoria Sole",
            txn_d=date(2026, 1, 1), currency="EUR", category="alcohol", net=15.0,
            line_tax=1.5, lang="fr", manipulated=False,
        )

        pcfg = load_pipeline_config()
        extractor = build_vision_extractor(sim_settings, pcfg)
        items = extractor.extract_items(data.blobs, url, "EUR", ITEMIZE_CATEGORIES)

        assert len(items) == 1
        assert items[0].category == "alcohol"
        assert items[0].detected_language == "fr"
    finally:
        data.close()


def test_extracted_line_has_no_language_when_sidecar_predates_the_field(tmp_path, sim_settings):
    """A pre-existing sidecar written before `language`/`category` existed in
    the content dict must still extract cleanly - detected_language falls
    back to None, category falls back to "misc" - never a KeyError."""
    import json

    from data.factory import build_data_layer

    data = build_data_layer(sim_settings)
    data.migrate()
    try:
        old_sidecar = {
            "content": {
                "vendor": "Old Vendor", "date": "2026-01-01", "amount": 10.0,
                "tax": 1.0, "currency": "EUR", "printed_total": 11.0,
            },
            "metadata": {"edited": False, "ai_generated_score": 0.1},
        }
        key = "legacy/SUB-OLD/LN-1"
        url = data.blobs.put(key + ".png", b"fake-png-bytes", "image/png")
        data.blobs.put(key + ".png.sim.json", json.dumps(old_sidecar).encode(), "application/json")

        pcfg = load_pipeline_config()
        extractor = build_vision_extractor(sim_settings, pcfg)
        line = extractor.extract(data.blobs, url, "LN-1", "EUR")
        assert line.detected_language is None

        items = extractor.extract_items(data.blobs, url, "EUR", ITEMIZE_CATEGORIES)
        assert items[0].category == "misc"
        assert items[0].detected_language is None
    finally:
        data.close()
