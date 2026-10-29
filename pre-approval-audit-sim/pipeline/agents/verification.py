"""Verification agent (Milestone 5).

INDEPENDENT checks (Solution Design 5.3) run concurrently, each isolated so
one failing degrades that signal to 'unverified'/a recorded flag rather than
sinking the others or producing a silent pass:

  a. authenticity   - inspects the SIMULATED receipt metadata sidecar
                      (`.sim.json`) for tamper / AI-generation signals -
                      synthetic-generator test data only. Flags only; never
                      a verdict.
  b. subtotal       - reconciles employee-entered totals against the extracted
                      receipt values, within a configurable tips tolerance.
  c. duplicate      - embedding similarity search (vector index) within report,
                      across the employee's history, and org-wide.
  d. merchant/geo   - vendor name matched against a simulated sanctions/PEP
                      watchlist (BR-TE-AU-03); itinerary/geo cross-referencing
                      is unverified in simulation - no itinerary source.
  e. structuring    - velocity (rapid-succession same-category spending) and
                      split-transaction (sub-cap charges summing over cap)
                      detection, looking across the employee's history, not
                      just this submission (BR-TE-AU-19).
  f. forensics      - REAL (non-simulated) analysis of the actual uploaded
                      bytes: EXIF/PDF-metadata + Error-Level-Analysis
                      (common/forensics.py), plus an optional real
                      vision-model AI-generation second opinion
                      (VisionExtractor.assess_forensics). Unioned into the
                      same authenticity_flags as check (a) - see `run()`.
  g. peer_outlier   - statistical peer-group comparison: this submission's
                      category spend vs. the live-computed mean/stddev of
                      every OTHER employee's spend in the same OE+category
                      (AuditStore.category_amount_stats) - catches spend
                      that's "normal" against a flat authored cap but
                      abnormal against how peers actually spend.

Guardrail: this agent produces signals, not accept/reject decisions.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Optional

from adapters.embeddings import EmbeddingClient
from adapters.vision import VisionExtractor
from common.blocklist import MerchantBlocklist
from common.forensics import analyze_receipt_bytes
from common.policy import PolicyRuleSet
from common.schemas import (
    AuditState,
    DuplicateMatch,
    MerchantValidation,
    SubmissionCreatedEvent,
    VerificationResult,
)
from data.interfaces import AuditStore, BlobStore, ConfigStore, VectorIndex
from pipeline.config import (
    ForensicsConfig,
    MerchantNetworkConfig,
    PeerOutlierConfig,
    VerificationConfig,
    load_pipeline_config,
)

logger = logging.getLogger("pipeline.agents.verification")

_META_SUFFIX = ".sim.json"

# "Strong" forensics signals (a confirmed structural anomaly, or a real
# vision-model AI-generation call) vs. "weak" heuristic ones (missing EXIF
# alone, an editing-software tag) - RiskAgent scores these differently
# (pipeline/agents/risk.py's forensics_strong_signal weight), since a common
# e-receipt false positive must not carry the same weight as a confirmed
# paste anomaly.
STRONG_FORENSICS_FLAGS = frozenset({"ela_local_anomaly", "ai_generated_suspected_vision"})


class VerificationAgent:
    def __init__(
        self,
        blobs: BlobStore,
        embeddings: EmbeddingClient,
        vectors: VectorIndex,
        store: AuditStore | None = None,
        rules: PolicyRuleSet | None = None,
        blocklist: MerchantBlocklist | None = None,
        config_store: Optional[ConfigStore] = None,
        vision: Optional[VisionExtractor] = None,
    ):
        self._blobs = blobs
        self._emb = embeddings
        self._vectors = vectors
        self._store = store
        self._rules = rules
        self._blocklist = blocklist
        self._config_store = config_store
        self._vision = vision

    def run(self, state: AuditState, event: SubmissionCreatedEvent) -> None:
        # Resolved fresh per submission from event.oe_code, not bound once at
        # construction, so an OE's saved verification-threshold override
        # (Settings -> Risk & pipeline) takes effect live. Passed explicitly
        # into _duplicate/_structuring below (not stashed on self) since both
        # run concurrently in the thread pool and this agent instance is
        # shared/reused across submissions from every OE - no shared mutable
        # config state to race on.
        cfg: VerificationConfig = load_pipeline_config(event.oe_code, self._config_store).verification

        result = VerificationResult()
        # Run the checks concurrently but isolate each: a raised check
        # records a degraded signal instead of failing the whole node.
        with ThreadPoolExecutor(max_workers=7) as ex:
            futs = {
                "authenticity": ex.submit(self._authenticity, event),
                "subtotal": ex.submit(self._subtotal, state, event),
                "duplicate": ex.submit(self._duplicate, state, event, cfg),
                "merchant": ex.submit(self._merchant, state, event),
                "structuring": ex.submit(self._structuring, state, event, cfg),
                "forensics": ex.submit(self._image_forensics, event, cfg.forensics),
                "peer_outlier": ex.submit(self._peer_outlier, event, cfg.peer_outlier),
                "merchant_network": ex.submit(self._merchant_network, state, event, cfg.merchant_network),
            }
            outcomes = {}
            for name, fut in futs.items():
                try:
                    outcomes[name] = fut.result()
                except Exception as exc:  # isolate per-check
                    logger.warning("verification check %s failed: %s", name, exc)
                    outcomes[name] = None

        authenticity_outcome = outcomes["authenticity"] or (
            [] if outcomes["authenticity"] == [] else ["check_error:authenticity"]
        )
        forensics_outcome = outcomes["forensics"] or []
        # One union list: real forensics flags and the simulated-sidecar
        # flags feed the exact same authenticity_flags every existing
        # reader (RiskAgent, the Evidence tab, tests) already looks at.
        result.authenticity_flags = sorted(set(authenticity_outcome) | set(forensics_outcome))
        subtotal_outcome = outcomes["subtotal"]
        if subtotal_outcome is not None:
            (result.subtotal_variance_pct, result.subtotal_entered_total,
             result.subtotal_receipt_total) = subtotal_outcome
        result.duplicate_matches = outcomes["duplicate"] or []
        merchant_outcome = outcomes["merchant"]
        if merchant_outcome is not None:
            result.merchant_validation, result.merchant_flags = merchant_outcome
        else:
            result.merchant_validation = MerchantValidation.unverified
        structuring_outcome = outcomes["structuring"]
        if structuring_outcome is not None:
            (result.velocity_flags, result.split_transaction_flags,
             result.compliance_flags) = structuring_outcome
        result.peer_outlier_flags = outcomes["peer_outlier"] or []
        result.merchant_network_flags = outcomes["merchant_network"] or []

        # Index this submission's lines AFTER searching, so a later resubmission
        # matches against it (org-wide duplicate memory).
        self._index(state, event)
        self._track_merchants_seen(state)
        state.verification = result

    def _track_merchants_seen(self, state: AuditState) -> None:
        """First/last-seen tracking for the merchant registry - a failed
        write here must not affect this submission's own decision (same
        non-fatal pattern as _index()'s vector-upsert call)."""
        if self._store is None:
            return
        for el in state.extracted_lines:
            if not el.vendor:
                continue
            try:
                self._store.upsert_merchant_seen(el.vendor)
            except Exception as exc:
                logger.warning("merchant registry upsert failed for %r: %s", el.vendor, exc)

    # --------------------------------------------------------------- checks
    def _authenticity(self, event: SubmissionCreatedEvent) -> list[str]:
        import json

        flags: set[str] = set()
        for line in event.report_lines:
            try:
                meta = json.loads(self._blobs.get(line.receipt_url + _META_SUFFIX))["metadata"]
            except Exception:
                continue
            if meta.get("edited"):
                flags.add("tamper_marker")
            if float(meta.get("ai_generated_score", 0)) > 0.5:
                flags.add("ai_generated_suspected")
        return sorted(flags)

    def _image_forensics(
        self, event: SubmissionCreatedEvent, cfg: ForensicsConfig,
    ) -> list[str]:
        """Real (non-simulated) analysis of the actual uploaded bytes -
        common/forensics.py's EXIF/PDF-metadata + ELA checks, plus an
        optional real vision-model AI-generation second opinion. Runs
        against EVERY line's real bytes regardless of whether a `.sim.json`
        sidecar exists, so a real uploaded receipt (which has no sidecar at
        all) gets real scrutiny for the first time.

        `expected_format_hint` is left `None` today - `ReportLine`/
        `SubmissionCreatedEvent` carry no declared receipt-format field, so
        `missing_exif_camera_data` (the one flag that needs it) never fires
        yet; this is a deliberate no-guess default, not a bug - see
        common/forensics.py::analyze_image_metadata."""
        if not cfg.enabled:
            return []

        flags: set[str] = set()
        for line in event.report_lines:
            try:
                data = self._blobs.get(line.receipt_url)
            except Exception:
                continue
            line_flags = analyze_receipt_bytes(
                data,
                expected_format_hint=None,
                ela_quality=cfg.ela_quality,
                ela_diff_threshold=cfg.ela_diff_threshold,
                ela_region_frac_threshold=cfg.ela_region_frac_threshold,
            )
            flags.update(line_flags)

            if self._vision is None or not cfg.vision_second_opinion_enabled:
                continue
            if cfg.vision_second_opinion_gate == "on_suspicion" and not line_flags:
                continue  # cheap heuristics found nothing - skip the paid call
            try:
                score = self._vision.assess_forensics(self._blobs, line.receipt_url)
            except Exception as exc:
                logger.warning("vision forensics check failed for %s: %s", line.line_id, exc)
                continue
            if score > cfg.vision_ai_generated_threshold:
                flags.add("ai_generated_suspected_vision")

        return sorted(flags)

    def _subtotal(
        self, state: AuditState, event: SubmissionCreatedEvent
    ) -> tuple[float, float, float] | None:
        """Returns (variance_pct, entered_total, receipt_total) - the two
        totals are kept (not just the percentage) so the risk explanation and
        UI can show the actual calculation, not only its result."""
        entered = sum(l.entered_amount for l in event.report_lines)
        receipt = sum(
            (l.amount or 0) + (l.tax or 0)
            for l in state.extracted_lines
            if l.amount is not None
        )
        if receipt <= 0:
            return None
        variance_pct = round(abs(entered - receipt) / receipt * 100, 2)
        return variance_pct, round(entered, 2), round(receipt, 2)

    def _duplicate(
        self, state: AuditState, event: SubmissionCreatedEvent, cfg: VerificationConfig
    ) -> list[DuplicateMatch]:
        cat_by_line = {l.line_id: l.category for l in event.report_lines}
        tol = cfg.duplicate_amount_tolerance_pct / 100.0
        best: dict[str, tuple[float, str]] = {}  # submission_id -> (similarity, match_type)
        for el in state.extracted_lines:
            if el.amount is None:
                continue
            vec = self._emb.embed_receipt(
                vendor=el.vendor,
                currency=el.currency or event.currency,
                category=cat_by_line.get(el.line_id),
                amount=el.amount,
            )
            matches = self._vectors.search(
                vec, k=cfg.duplicate_top_k, exclude_submission_id=event.submission_id
            )
            for m in matches:
                if m.score < cfg.duplicate_similarity_threshold:
                    continue
                # Corroborating signals: a high vector score alone is not enough -
                # confirm same employee and a near-identical amount.
                if (
                    cfg.duplicate_require_same_employee
                    and m.employee_id is not None
                    and m.employee_id != event.employee_id
                ):
                    continue
                if m.amount is not None and abs(m.amount - el.amount) > tol * max(el.amount, 1.0):
                    continue
                if m.score > best.get(m.submission_id, (0.0, ""))[0]:
                    best[m.submission_id] = (m.score, "embedding")

            # Structured match: an exact (vendor, invoice_number) hit is
            # strictly stronger evidence than content-similarity search, and
            # doesn't require the amount/employee/threshold corroboration
            # above - it can catch a resubmission whose image was edited
            # enough to drop embedding similarity, but whose printed invoice
            # number is identical. Skips entirely (never an error, never a
            # forced match) when either field is missing, e.g. under the
            # default SimulatedVisionExtractor's older sidecars.
            if self._store is not None and el.vendor and el.invoice_number:
                for row in self._store.find_by_vendor_invoice(
                    el.vendor, el.invoice_number, exclude_submission_id=event.submission_id,
                ):
                    best[row["submission_id"]] = (1.0, "invoice_number")
        return [
            DuplicateMatch(submission_id=s, similarity=round(sc, 4), match_type=mt)
            for s, (sc, mt) in best.items()
        ]

    def _merchant(
        self, state: AuditState, event: SubmissionCreatedEvent
    ) -> tuple[MerchantValidation, list[str]]:
        """Vendor names against a simulated sanctions/PEP watchlist
        (BR-TE-AU-03; common/blocklist.py) UNIONED with the merchant_registry
        table (bootstrapped from that same YAML once, then updated by
        first-seen tracking, cross-employee network analysis, and admin
        overrides - see AuditStore.set_merchant_status/get_merchant). A real
        check against local data, not a real OFAC/PEP data feed. Itinerary/geo
        cross-referencing has no data source in simulation, so that half stays
        unverified rather than fabricating a pass."""
        have_blocklist = self._blocklist is not None and bool(self._blocklist.entries)
        have_registry = self._store is not None
        if not have_blocklist and not have_registry:
            return MerchantValidation.unverified, []
        flags: set[str] = set()
        for el in state.extracted_lines:
            if not el.vendor:
                continue
            if have_blocklist:
                for hit in self._blocklist.match(el.vendor):
                    flags.add(f"{hit.type}: {el.vendor!r} matches watchlist entry "
                              f"{hit.name!r} ({hit.reason})")
            if have_registry:
                merchant = self._store.get_merchant(el.vendor)
                if merchant and merchant.get("status") in ("watch", "blocked"):
                    detail = f" ({merchant['reason']})" if merchant.get("reason") else ""
                    flags.add(
                        f"{merchant['status']}: {el.vendor!r} matches merchant registry "
                        f"entry {merchant['display_name']!r}{detail}"
                    )
        if flags:
            return MerchantValidation.failed, sorted(flags)
        return MerchantValidation.passed, []

    def _structuring(
        self, state: AuditState, event: SubmissionCreatedEvent, cfg: VerificationConfig
    ) -> tuple[list[str], list[str], list[str]] | None:
        """Velocity (rapid-succession same-category spending), split-transaction
        (2+ sub-cap charges from this employee summing over the category cap -
        BR-TE-AU-19), and cumulative-compliance (rolling-window aggregate cap,
        e.g. an annual FCPA/anti-bribery gift-and-entertainment limit -
        BR-TE-AU-04) detection. All three look across the employee's OTHER
        submissions within a lookback window, not just this one, since that's
        where the real pattern lives (e.g. two $499 charges on separate reports
        instead of one $998, or many small entertainment charges to the same
        recipient across a year)."""
        if self._store is None or self._rules is None:
            return None  # not wired (e.g. a test harness) - degrade quietly

        extracted_by_line = {el.line_id: el for el in state.extracted_lines}
        lines_by_category: dict[str, list] = defaultdict(list)
        for line in event.report_lines:
            lines_by_category[line.category].append(line)

        velocity_flags: set[str] = set()
        split_flags: set[str] = set()
        compliance_flags: set[str] = set()

        for category, lines in lines_by_category.items():
            cumulative_rules = self._rules.cumulative_cap_rules_for(
                category=category, oe_code=event.oe_code, currency=event.currency,
            )
            cumulative_window = max([r.window_days or 0 for r in cumulative_rules], default=0)
            lookback_days = max(
                cfg.velocity_window_days, cfg.split_window_days, cumulative_window,
            )
            since = event.submitted_at.date() - timedelta(days=lookback_days)
            history = self._store.recent_employee_category_lines(
                event.employee_id, category, since.isoformat(),
                exclude_submission_id=event.submission_id,
            )
            entries: list[dict] = []
            for line in lines:
                el = extracted_by_line.get(line.line_id)
                if el and el.date:
                    entries.append({"amount": line.entered_amount, "txn_date": el.date})
            for h in history:
                if h.get("txn_date"):
                    entries.append({
                        "amount": h["entered_amount"],
                        "txn_date": date.fromisoformat(h["txn_date"]),
                    })

            # --- velocity: N+ charges in this category on the same calendar day ---
            by_date: dict[date, int] = defaultdict(int)
            for e in entries:
                by_date[e["txn_date"]] += 1
            for d, count in by_date.items():
                if count >= cfg.velocity_count_threshold:
                    velocity_flags.add(f"{category}: {count} charge(s) on {d.isoformat()}")

            # --- split-transaction: every individual charge under the cap, but
            # the sum within the split window is over it ---
            cap_rules = self._rules.amount_cap_rules_for(
                category=category, oe_code=event.oe_code, currency=event.currency,
            )
            if cap_rules:
                cap = min(r.cap_for(event.currency) for r in cap_rules)
                split_since = event.submitted_at.date() - timedelta(days=cfg.split_window_days)
                recent = [e for e in entries if e["txn_date"] >= split_since]
                if len(recent) >= 2:
                    total = sum(e["amount"] for e in recent)
                    if all(e["amount"] <= cap for e in recent) and total > cap:
                        split_flags.add(
                            f"{category}: {len(recent)} charge(s) totalling "
                            f"{total:.2f} {event.currency} > cap {cap:.2f}"
                        )

            # --- cumulative compliance: rolling-window aggregate over a cap
            # (e.g. FCPA-ENTERTAINMENT-ANNUAL-CUMULATIVE-01) ---
            for rule in cumulative_rules:
                rule_cap = rule.cap_for(event.currency)
                rule_since = event.submitted_at.date() - timedelta(days=rule.window_days or 0)
                windowed = [e for e in entries if e["txn_date"] >= rule_since]
                total = sum(e["amount"] for e in windowed)
                if total > rule_cap:
                    compliance_flags.add(
                        f"{rule.id}: {category} cumulative {total:.2f} {event.currency} over "
                        f"{rule.window_days} day(s) > cap {rule_cap:.2f}"
                    )

        return sorted(velocity_flags), sorted(split_flags), sorted(compliance_flags)

    def _peer_outlier(
        self, event: SubmissionCreatedEvent, cfg: PeerOutlierConfig,
    ) -> list[str]:
        """Statistical peer-group comparison: sums this submission's spend per
        category, compares each against the live-computed mean/stddev of
        every OTHER employee's spend in the same OE+category
        (AuditStore.category_amount_stats), and flags a category whose
        z-score clears the configured threshold. Independent of any flat
        authored cap - this is the one check in this agent that compares a
        submission against the population rather than a fixed number or the
        same employee's own history."""
        if self._store is None or not cfg.enabled:
            return []

        amount_by_category: dict[str, float] = defaultdict(float)
        for line in event.report_lines:
            amount_by_category[line.category] += line.entered_amount

        flags: set[str] = set()
        for category, amount in amount_by_category.items():
            stats = self._store.category_amount_stats(
                event.oe_code, category, exclude_employee_id=event.employee_id,
            )
            n = stats.get("n", 0)
            stddev = stats.get("stddev", 0.0)
            mean = stats.get("mean", 0.0)
            if n < cfg.min_peer_sample_size or stddev <= 0:
                continue  # too thin a sample, or a degenerate (zero-spread) baseline
            z = (amount - mean) / stddev
            if z >= cfg.z_score_threshold:
                flags.add(
                    f"{category}: {amount:.2f} {event.currency} is {z:.1f} std-dev above "
                    f"the {n}-peer average of {mean:.2f} {event.currency}"
                )
        return sorted(flags)

    def _merchant_network(
        self, state: AuditState, event: SubmissionCreatedEvent, cfg: MerchantNetworkConfig,
    ) -> list[str]:
        """Cross-employee merchant network analysis - distinct from
        _merchant()'s per-line blocklist/registry lookup, this looks at how a
        merchant is used ACROSS employees:
          - a rarely-seen merchant suddenly claimed by many distinct
            employees in a short window (possible collusion/shell vendor);
          - several different employees' amounts for the same vendor+category
            clustering just under an applicable cap (cross-employee
            structuring, distinct from _structuring's single-employee
            split-transaction check);
          - a fuzzy name-variant match (stdlib difflib) against a
            merchant_registry row already marked 'blocked', catching a
            watchlisted merchant reappearing under a slightly different
            spelling.
        Any vendor this fires for gets escalated in the registry (auto risk
        tier), unless an admin has already set an explicit override for it."""
        if self._store is None or not cfg.enabled:
            return []

        import difflib

        cat_by_line = {l.line_id: l.category for l in event.report_lines}
        spread_since = (event.submitted_at.date()
                        - timedelta(days=cfg.new_merchant_employee_spread_window_days)).isoformat()
        blocked_rows = self._store.list_merchant_registry(status="blocked")

        flags: set[str] = set()
        seen_vendors: set[str] = set()
        for el in state.extracted_lines:
            if not el.vendor or el.vendor in seen_vendors:
                continue
            seen_vendors.add(el.vendor)
            vendor_flags: list[str] = []

            merchant = self._store.get_merchant(el.vendor)
            prior_submissions = merchant.get("submission_count", 0) if merchant else 0
            if prior_submissions <= cfg.new_merchant_max_prior_submissions:
                spread = self._store.merchant_employee_spread(el.vendor, since_date=spread_since)
                if spread.get("distinct_employees", 0) >= cfg.new_merchant_employee_spread_threshold:
                    vendor_flags.append(
                        f"new_vendor_multi_employee: {el.vendor!r} used by "
                        f"{spread['distinct_employees']} distinct employees in the last "
                        f"{cfg.new_merchant_employee_spread_window_days} days despite being rarely seen before"
                    )

            category = cat_by_line.get(el.line_id)
            currency = el.currency or event.currency
            if category and el.amount is not None and self._rules is not None:
                caps = self._rules.amount_cap_rules_for(
                    category=category, oe_code=event.oe_code, currency=currency,
                )
                cap = caps[0].cap_for(currency) if caps else None
                if cap:
                    near_cap_since = (event.submitted_at.date()
                                     - timedelta(days=cfg.near_cap_clustering_window_days)).isoformat()
                    clustering = self._store.merchant_near_cap_clustering(
                        el.vendor, category, event.oe_code, cap,
                        tolerance_pct=cfg.near_cap_tolerance_pct, since_date=near_cap_since,
                    )
                    if clustering.get("distinct_employees_near_cap", 0) >= cfg.near_cap_min_distinct_employees:
                        vendor_flags.append(
                            f"cross_employee_threshold_clustering: "
                            f"{clustering['distinct_employees_near_cap']} distinct employees filed "
                            f"{category} amounts near the {cap} {currency} cap for {el.vendor!r}"
                        )

            el_key = el.vendor.strip().lower()
            for row in blocked_rows:
                if row["merchant_key"] == el_key:
                    continue  # exact match already caught by _merchant()
                ratio = difflib.SequenceMatcher(None, el_key, row["merchant_key"]).ratio()
                if ratio >= cfg.fuzzy_match_threshold:
                    vendor_flags.append(
                        f"fuzzy_watchlist_match: {el.vendor!r} closely resembles blocked merchant "
                        f"{row['display_name']!r} ({ratio:.2f} similarity)"
                    )

            if vendor_flags:
                flags.update(vendor_flags)
                try:
                    self._store.set_merchant_status(
                        el.vendor, status="watch", risk_tier="high",
                        reason="; ".join(vendor_flags), source="auto",
                    )
                except Exception as exc:
                    logger.warning("merchant registry auto-flag failed for %r: %s", el.vendor, exc)

        return sorted(flags)

    # --------------------------------------------------------------- indexing
    def _index(self, state: AuditState, event: SubmissionCreatedEvent) -> None:
        cat_by_line = {l.line_id: l.category for l in event.report_lines}
        for el in state.extracted_lines:
            if el.amount is None:
                continue
            vec = self._emb.embed_receipt(
                vendor=el.vendor,
                currency=el.currency or event.currency,
                category=cat_by_line.get(el.line_id),
                amount=el.amount,
            )
            try:
                self._vectors.upsert(
                    line_item_id=f"{event.submission_id}:{el.line_id}",
                    submission_id=event.submission_id,
                    employee_id=event.employee_id,
                    embedding=vec,
                    amount=el.amount,
                    txn_date=el.date,
                )
            except Exception as exc:
                # Non-fatal: a failed index write costs future recall, not this
                # submission's decision.
                logger.warning("vector upsert failed for %s: %s", el.line_id, exc)
