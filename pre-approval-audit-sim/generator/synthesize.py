"""Core synthetic-data synthesis: submissions + receipts + exact ground truth.

Anomalies are injected *by construction* and mutually exclusive per submission,
so the ground truth is exact. Deterministic under a fixed seed.

Each receipt is stored with a `.sim.json` sidecar carrying:
  * content  - the fields printed on the receipt (what a perfect OCR reads)
  * metadata - simulated EXIF/provenance the authenticity check inspects
This keeps "what's on the receipt" separate from "expected pipeline behaviour"
(ground_truth.json). They diverge precisely for the injected anomalies.

Manipulation model (submission-level): the employee-entered amount is inflated
relative to the receipt (padding), and the receipt metadata is marked edited.
That gives verification two independent signals - a subtotal variance AND an
authenticity flag - so each check can be benchmarked on its own.
"""
from __future__ import annotations

import io
import json
import random
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from PIL import Image

from common.policy import PolicyRuleSet
from common.schemas import ReportLine, SourceSystem, SubmissionCreatedEvent
from data.interfaces import BlobStore
from generator.config import GeneratorConfig
from generator.ground_truth import GroundTruth, GTLine, GTPolicy, GTSubmission
from generator.receipts import ReceiptLine, render

_BASE_TS = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
_MANIPULATION_FACTOR = 1.20  # employee inflates entered amount 20% over the receipt
_SIDECAR_SUFFIX = ".sim.json"

_VENDORS = {
    "meals": ["Bistro Lumen", "Cafe Nord", "Trattoria Sole", "Kantine 12"],
    "lodging": ["Grand Rivera Hotel", "CityStay Inn", "Hotel Adler", "Parkview Suites"],
    "transport": ["MetroTaxi", "RailEuropa", "UrbanRide", "AirportShuttle"],
    "entertainment": ["Club Aurora", "Cinema Palast", "The Vault Bar"],
    "misc": ["OfficeMart", "QuickPrint", "SundriesCo"],
}


class Synthesizer:
    def __init__(self, config: GeneratorConfig, rules: PolicyRuleSet, blobs: BlobStore):
        self.cfg = config
        self.rules = rules
        self.blobs = blobs
        self.rng = random.Random(config.seed)

    # ------------------------------------------------------------------ public
    def generate(self) -> tuple[list[SubmissionCreatedEvent], GroundTruth]:
        types = self._assign_anomaly_types()
        events: list[SubmissionCreatedEvent] = []
        gts: list[GTSubmission] = []
        normal_pool: list[tuple[SubmissionCreatedEvent, GTSubmission]] = []

        for i in range(self.cfg.volume):
            kind = types[i]
            if kind == "duplicate" and normal_pool:
                ev, gt = self._make_duplicate(i, normal_pool)
            else:
                ev, gt = self._make_fresh(
                    i,
                    policy_violation=(kind == "policy_violation"),
                    manipulated=(kind == "manipulated"),
                    peer_outlier=(kind == "peer_outlier"),
                )
                if kind in ("normal", "duplicate", "peer_outlier"):
                    # A peer_outlier submission is still legitimate content
                    # (just a statistically unusual amount, not fabricated) -
                    # eligible as a duplicate-source candidate exactly like
                    # "normal", so introducing this anomaly type doesn't
                    # change normal_pool's size/timing relative to before it
                    # existed, which would otherwise perturb every downstream
                    # self.rng.choice(normal_pool) call's result (Python's
                    # random.choice consumption depends on len(seq)) and
                    # silently desync the rest of this run's RNG stream from
                    # runs generated before this anomaly type was added -
                    # exactly the kind of change that would invalidate the
                    # calibrated thresholds in tests/test_agents_accuracy.py
                    # and tests/test_report.py, which assume today's default
                    # config/generator.yaml reproduces a specific known run.
                    normal_pool.append((ev, gt))
            events.append(ev)
            gts.append(gt)

        gt = GroundTruth(
            run_id=self.cfg.run_id,
            generator_config=self.cfg.model_dump(),
            policy_rule_version=self.rules.rule_version,
            submissions=gts,
        )
        return events, gt

    # --------------------------------------------------------------- internals
    def _assign_anomaly_types(self) -> list[str]:
        n = self.cfg.volume
        a = self.cfg.anomaly_injection
        n_dup = round(n * a.duplicate_rate)
        n_pol = round(n * a.policy_violation_rate)
        n_man = round(n * a.manipulated_receipt_rate)
        n_peer = round(n * a.peer_outlier_rate)

        idxs = list(range(n))
        self.rng.shuffle(idxs)
        types = ["normal"] * n
        cursor = 0

        def take(count: int, label: str) -> None:
            nonlocal cursor
            for j in idxs[cursor : cursor + count]:
                types[j] = label
            cursor += count

        take(n_pol, "policy_violation")
        take(n_man, "manipulated")
        take(n_dup, "duplicate")
        take(n_peer, "peer_outlier")
        return types

    def _ts(self, i: int) -> datetime:
        return _BASE_TS + timedelta(minutes=i * 7)

    def _sid(self, i: int) -> str:
        return f"SUB-{self.cfg.seed}-{i:05d}"

    def _pick_capped_category(self, oe: str, currency: str) -> str:
        candidates = [
            c
            for c in self.cfg.categories
            if self.rules.amount_cap_rules_for(category=c, oe_code=oe, currency=currency)
        ]
        return self.rng.choice(candidates) if candidates else self.rng.choice(self.cfg.categories)

    def _normal_amount(
        self, category: str, oe: str, currency: str, *, peer_outlier: bool = False,
    ) -> float:
        caps = self.rules.amount_cap_rules_for(category=category, oe_code=oe, currency=currency)
        if caps:
            cap = min(r.cap_for(currency) for r in caps)
            amount = self.rng.uniform(0.20 * cap, 0.85 * cap)
        else:
            amount = self.rng.uniform(5, 40)
        if peer_outlier:
            # Inflate far outside the population this same method produces,
            # so VerificationAgent._peer_outlier's live-computed peer baseline
            # (mean/stddev over every OTHER employee's amounts in this same
            # OE+category) genuinely separates this submission from the rest.
            amount *= self.cfg.anomaly_injection.peer_outlier_multiplier
        return round(amount, 2)

    def _apply_fraud_flavor(self, rendered_data: bytes, flavor: str) -> tuple[bytes, str, str]:
        """Turns an already-rendered base receipt (PNG or, if the randomly-
        chosen format was `scanned_pdf`, a PDF - rasterised first) into a
        genuinely doctored JPEG that exercises the REAL forensics checks
        (common/forensics.py / VerificationAgent._image_forensics) - not the
        `.sim.json` simulated `edited`/`ai_generated_score` signal every
        other receipt here relies on. Not wired into the random
        anomaly_injection distribution (`_assign_anomaly_types`) - that
        distribution feeds `tests/test_agents_accuracy.py`/`test_report.py`'s
        calibrated accuracy/recall thresholds, which this must not perturb.
        Called directly by `tests/test_forensics.py` instead, to prove the
        real forensics engine catches a receipt the generator's own
        rendering pipeline produced (not a hand-built Pillow fixture)."""
        from adapters.pdf_render import is_pdf, pdf_first_page_to_png

        if is_pdf(rendered_data):
            rendered_data = pdf_first_page_to_png(rendered_data)
        img = Image.open(io.BytesIO(rendered_data)).convert("RGB")

        if flavor == "ela_paste":
            # A high-frequency noise patch pasted onto the smooth rendered
            # receipt - the quantization-error gap between "just pasted,
            # never JPEG-compressed" and "already part of a stable
            # compression" is exactly what error_level_analysis measures.
            # Sized as a fraction of the canvas (not a fixed pixel count) so
            # it clears error_level_analysis's region_frac_threshold
            # regardless of the receipt's actual rendered dimensions.
            w, h = img.size
            pw, ph = w // 4, h // 4
            x0, y0 = w // 3, h // 3
            patch = Image.new("RGB", (pw, ph))
            px = patch.load()
            for x in range(pw):
                for y in range(ph):
                    px[x, y] = (self.rng.randint(0, 255), self.rng.randint(0, 255),
                                self.rng.randint(0, 255))
            img.paste(patch, (x0, y0))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
            return buf.getvalue(), "image/jpeg", "jpg"

        if flavor == "editing_software_tag":
            exif = img.getexif()
            exif[305] = "Adobe Photoshop 25.0"  # EXIF Software tag
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90, exif=exif)
            return buf.getvalue(), "image/jpeg", "jpg"

        raise ValueError(f"unknown fraud_flavor: {flavor!r}")

    def _store_receipt(
        self,
        *,
        run_key: str,
        vendor: str,
        txn_d: date,
        currency: str,
        category: str,
        net: float,
        line_tax: float,
        lang: str,
        manipulated: bool,
        fraud_flavor: Optional[str] = None,
    ) -> str:
        printed_total = round(net + line_tax, 2)  # receipt itself is internally consistent
        fmt = self.rng.choice(self.cfg.receipt_format_mix)
        rendered = render(
            fmt,
            vendor=vendor,
            txn_date=txn_d,
            currency=currency,
            lines=[ReceiptLine(description=category, amount=net)],
            tax=line_tax,
            printed_total=printed_total,
            lang=lang,
            manipulated=manipulated,
        )
        data, content_type, ext = rendered.data, rendered.content_type, rendered.ext
        if fraud_flavor is not None:
            data, content_type, ext = self._apply_fraud_flavor(rendered.data, fraud_flavor)
        key = f"{run_key}.{ext}"
        url = self.blobs.put(key, data, content_type)

        sidecar = {
            "content": {
                "vendor": vendor,
                "date": txn_d.isoformat(),
                "amount": net,
                "tax": line_tax,
                "currency": currency,
                "printed_total": printed_total,
                "category": category,
                "language": lang,
            },
            "metadata": {
                "edited": manipulated,
                "ai_generated_score": round(
                    self.rng.uniform(0.60, 0.95) if manipulated else self.rng.uniform(0.0, 0.25),
                    3,
                ),
                "software": "PhotoEditor" if manipulated else "CameraApp",
            },
        }
        self.blobs.put(url.split("://", 1)[1] + _SIDECAR_SUFFIX,
                       json.dumps(sidecar).encode("utf-8"), "application/json")
        return url

    def _make_fresh(
        self, i: int, *, policy_violation: bool, manipulated: bool, peer_outlier: bool = False,
    ) -> tuple[SubmissionCreatedEvent, GTSubmission]:
        sid = self._sid(i)
        oe = self.rng.choice(self.cfg.oe_codes)
        currency = self.rng.choice(self.cfg.currency_mix)
        lang = self.rng.choice(self.cfg.language_mix)
        n_lines = self.rng.randint(
            self.cfg.lines_per_submission.min, self.cfg.lines_per_submission.max
        )
        txn_d = self._ts(i).date()
        violate_idx = self.rng.randrange(n_lines) if policy_violation else -1

        report_lines: list[ReportLine] = []
        gt_lines: list[GTLine] = []
        violated_rule_ids: list[str] = []
        sum_receipt = 0.0
        sum_entered = 0.0

        for li in range(n_lines):
            line_id = f"LN-{li + 1}"
            category = (
                self._pick_capped_category(oe, currency)
                if li == violate_idx
                else self.rng.choice(self.cfg.categories)
            )
            vendor = self.rng.choice(_VENDORS.get(category, _VENDORS["misc"]))
            net = self._normal_amount(category, oe, currency, peer_outlier=peer_outlier)

            if li == violate_idx:
                caps = self.rules.amount_cap_rules_for(
                    category=category, oe_code=oe, currency=currency
                )
                if caps:
                    rule = caps[0]
                    net = round(rule.cap_for(currency) * self.rng.uniform(1.15, 1.60), 2)
                    violated_rule_ids.append(rule.id)
            elif peer_outlier:
                # The peer_outlier multiplier can push an amount over a
                # category's cap by construction (e.g. 6x a normal meal
                # amount is comfortably over any meal cap) even though this
                # line was never deliberately chosen to violate one - ground
                # truth must reflect that real breach (PolicyAgent will
                # independently flag it via its own amount_cap check,
                # `amount &lt;= cap`), or test_agents_accuracy.py's ground-truth
                # comparison would see a false disagreement.
                for rule in self.rules.amount_cap_rules_for(
                    category=category, oe_code=oe, currency=currency
                ):
                    if net > rule.cap_for(currency):
                        violated_rule_ids.append(rule.id)

            line_tax = round(net * 0.10, 2)
            receipt_value = round(net + line_tax, 2)
            entered = round(receipt_value * (_MANIPULATION_FACTOR if manipulated else 1.0), 2)

            url = self._store_receipt(
                run_key=f"{self.cfg.run_id}/{sid}/{line_id}",
                vendor=vendor, txn_d=txn_d, currency=currency, category=category,
                net=net, line_tax=line_tax, lang=lang, manipulated=manipulated,
            )

            report_lines.append(
                ReportLine(line_id=line_id, category=category, entered_amount=entered,
                           receipt_url=url)
            )
            gt_lines.append(
                GTLine(line_id=line_id, vendor=vendor, date=txn_d.isoformat(), amount=net,
                       tax=line_tax, currency=currency, category=category)
            )
            sum_receipt += receipt_value
            sum_entered += entered

        variance_pct = (
            round((sum_entered - sum_receipt) / sum_receipt * 100, 2) if sum_receipt else 0.0
        )
        event = SubmissionCreatedEvent(
            submission_id=sid,
            source_system=SourceSystem.simulation_harness,
            source_system_ref=f"SIM-{i:05d}",
            oe_code=oe,
            employee_id=f"EMP-{(i % 40) + 1:04d}",
            cost_center=f"CC-{(i % 12) + 1:03d}",
            currency=currency,
            submitted_at=self._ts(i),
            report_lines=report_lines,
        )
        gt = GTSubmission(
            submission_id=sid,
            is_duplicate_of=None,
            manipulated=manipulated,
            expected_authenticity_flags=["tamper_marker"] if manipulated else [],
            expected_subtotal_variance_pct=variance_pct,
            peer_outlier=peer_outlier,
            policy_violation=policy_violation,
            policy=GTPolicy(
                verdict="fail" if violated_rule_ids else "pass",
                violated_rule_ids=violated_rule_ids,
            ),
            lines=gt_lines,
        )
        return event, gt

    def _make_duplicate(
        self, i: int, normal_pool: list[tuple[SubmissionCreatedEvent, GTSubmission]]
    ) -> tuple[SubmissionCreatedEvent, GTSubmission]:
        src_ev, src_gt = self.rng.choice(normal_pool)
        sid = self._sid(i)
        txn_d = self._ts(i).date()
        lang = self.rng.choice(self.cfg.language_mix)

        report_lines: list[ReportLine] = []
        gt_lines: list[GTLine] = []
        for src_line, src_gtl in zip(src_ev.report_lines, src_gt.lines):
            net = round(src_gtl.amount * self.rng.uniform(0.99, 1.01), 2)  # near-duplicate jitter
            line_tax = round(net * 0.10, 2)
            entered = round(net + line_tax, 2)
            url = self._store_receipt(
                run_key=f"{self.cfg.run_id}/{sid}/{src_line.line_id}",
                vendor=src_gtl.vendor, txn_d=txn_d, currency=src_gtl.currency,
                category=src_gtl.category, net=net, line_tax=line_tax, lang=lang,
                manipulated=False,
            )
            report_lines.append(
                ReportLine(line_id=src_line.line_id, category=src_gtl.category,
                           entered_amount=entered, receipt_url=url)
            )
            gt_lines.append(
                GTLine(line_id=src_line.line_id, vendor=src_gtl.vendor,
                       date=txn_d.isoformat(), amount=net, tax=line_tax,
                       currency=src_gtl.currency, category=src_gtl.category)
            )

        event = SubmissionCreatedEvent(
            submission_id=sid,
            source_system=SourceSystem.simulation_harness,
            source_system_ref=f"SIM-{i:05d}",
            oe_code=src_ev.oe_code,
            employee_id=src_ev.employee_id,
            cost_center=src_ev.cost_center,
            currency=src_ev.currency,
            submitted_at=self._ts(i),
            report_lines=report_lines,
        )
        gt = GTSubmission(
            submission_id=sid,
            is_duplicate_of=src_ev.submission_id,
            manipulated=False,
            expected_authenticity_flags=[],
            expected_subtotal_variance_pct=0.0,
            policy=GTPolicy(verdict=src_gt.policy.verdict,
                            violated_rule_ids=list(src_gt.policy.violated_rule_ids)),
            lines=gt_lines,
        )
        return event, gt
