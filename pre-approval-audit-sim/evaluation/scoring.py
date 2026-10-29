"""Accuracy/recall scoring against generator ground truth.

Reused by the Phase 2 agent tests and the Phase 5 reporting harness. Scores are
computed by comparing pipeline output (AuditState per submission) to the exact
GroundTruth the generator emitted.
"""
from __future__ import annotations

from dataclasses import dataclass

from common.schemas import AuditState
from generator.ground_truth import GroundTruth

_AMOUNT_EPS = 0.005


@dataclass
class ExtractionScore:
    total_fields: int
    correct_fields: int
    field_accuracy: float
    vendor_accuracy: float
    date_accuracy: float
    amount_accuracy: float


@dataclass
class ConfidenceScore:
    high_conf_accuracy: float
    low_conf_accuracy: float
    gap: float
    low_conf_cutoff: float


@dataclass
class DuplicateScore:
    gt_duplicates: int
    detected_true_positives: int
    recall: float
    false_positives: int
    negatives: int
    false_positive_rate: float
    precision: float


@dataclass
class PolicyScore:
    total: int
    verdict_matches: int
    verdict_match_rate: float


def _amount_eq(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) <= _AMOUNT_EPS


def score_extraction(gt: GroundTruth, states: dict[str, AuditState]) -> ExtractionScore:
    total = correct = 0
    v_ok = v_tot = d_ok = d_tot = a_ok = a_tot = 0
    for s in gt.submissions:
        st = states.get(s.submission_id)
        if not st:
            continue
        ext_by_line = {e.line_id: e for e in st.extracted_lines}
        for gl in s.lines:
            e = ext_by_line.get(gl.line_id)
            vendor_ok = bool(e and e.vendor == gl.vendor)
            date_ok = bool(e and e.date and e.date.isoformat() == gl.date)
            amount_ok = bool(e and _amount_eq(e.amount, gl.amount))
            v_tot += 1; d_tot += 1; a_tot += 1
            v_ok += vendor_ok; d_ok += date_ok; a_ok += amount_ok
            total += 3
            correct += int(vendor_ok) + int(date_ok) + int(amount_ok)
    return ExtractionScore(
        total_fields=total,
        correct_fields=correct,
        field_accuracy=(correct / total) if total else 0.0,
        vendor_accuracy=(v_ok / v_tot) if v_tot else 0.0,
        date_accuracy=(d_ok / d_tot) if d_tot else 0.0,
        amount_accuracy=(a_ok / a_tot) if a_tot else 0.0,
    )


def score_confidence(
    gt: GroundTruth, states: dict[str, AuditState], low_conf_cutoff: float
) -> ConfidenceScore:
    hi_ok = hi_tot = lo_ok = lo_tot = 0
    for s in gt.submissions:
        st = states.get(s.submission_id)
        if not st:
            continue
        gl_by_line = {gl.line_id: gl for gl in s.lines}
        for e in st.extracted_lines:
            gl = gl_by_line.get(e.line_id)
            if not gl:
                continue
            # a line is "correct" if the amount is right (the field that matters most)
            correct = _amount_eq(e.amount, gl.amount)
            if e.confidence >= low_conf_cutoff:
                hi_tot += 1; hi_ok += int(correct)
            else:
                lo_tot += 1; lo_ok += int(correct)
    hi = (hi_ok / hi_tot) if hi_tot else 0.0
    lo = (lo_ok / lo_tot) if lo_tot else 0.0
    return ConfidenceScore(hi, lo, round(hi - lo, 4), low_conf_cutoff)


def score_duplicates(gt: GroundTruth, states: dict[str, AuditState]) -> DuplicateScore:
    gt_dupes = {s.submission_id for s in gt.submissions if s.is_duplicate_of}
    all_ids = {s.submission_id for s in gt.submissions}
    detected = {
        sid for sid, st in states.items() if st.verification.duplicate_matches
    }
    tp = gt_dupes & detected
    negatives = all_ids - gt_dupes
    fp = detected - gt_dupes
    return DuplicateScore(
        gt_duplicates=len(gt_dupes),
        detected_true_positives=len(tp),
        recall=(len(tp) / len(gt_dupes)) if gt_dupes else 1.0,
        false_positives=len(fp),
        negatives=len(negatives),
        false_positive_rate=(len(fp) / len(negatives)) if negatives else 0.0,
        precision=(len(tp) / len(detected)) if detected else 1.0,
    )


def score_policy(
    gt: GroundTruth, verdicts: dict[str, tuple[bool, set[str]]]
) -> PolicyScore:
    """verdicts: submission_id -> (is_fail, {violated_rule_ids})."""
    total = matches = 0
    for s in gt.submissions:
        if s.submission_id not in verdicts:
            continue
        total += 1
        is_fail, rule_ids = verdicts[s.submission_id]
        gt_fail = s.policy.verdict == "fail"
        if is_fail == gt_fail and (not gt_fail or set(s.policy.violated_rule_ids) <= rule_ids):
            matches += 1
    return PolicyScore(total, matches, (matches / total) if total else 0.0)
