"""Shared data contracts used across every module.

These are the frozen interfaces the rest of the build codes against. The
`AuditState` object mirrors Detailed Technical Design 2.3 exactly; the webhook
payloads mirror 2.1 / 2.2. Keeping them here (and nowhere else) means two
components developed independently stay compatible.
"""
from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class SourceSystem(str, Enum):
    concur = "concur"
    cytric = "cytric"
    simulation_harness = "simulation_harness"


class MerchantValidation(str, Enum):
    passed = "pass"
    failed = "fail"
    unverified = "unverified"


class RoutingDecision(str, Enum):
    auto_approve = "auto_approve"
    auto_reject = "auto_reject"
    human_review = "human_review"


class DecisionStatus(str, Enum):
    approved = "approved"
    rejected = "rejected"
    pending_review = "pending_review"


# --------------------------------------------------------------------------- #
# Inbound / outbound webhook contracts (Tech Design 2.1 / 2.2)
# --------------------------------------------------------------------------- #
class ReportLine(BaseModel):
    line_id: str
    category: str
    entered_amount: float
    receipt_url: str


class SubmissionCreatedEvent(BaseModel):
    """POST /webhooks/submission-created payload."""

    event_type: str = "submission.created"
    submission_id: str
    source_system: SourceSystem
    source_system_ref: str
    oe_code: str
    employee_id: str
    cost_center: Optional[str] = None
    currency: str = Field(min_length=3, max_length=3)
    submitted_at: datetime
    report_lines: list[ReportLine]


class AuditDecisionWriteback(BaseModel):
    """POST /webhooks/audit-decision payload (to source system / mock logger)."""

    submission_id: str
    decision: DecisionStatus
    decision_timestamp: datetime
    risk_score: Optional[float] = None
    rule_ids_triggered: list[str] = Field(default_factory=list)
    rationale: Optional[str] = None
    model_version: Optional[str] = None
    rule_version: Optional[str] = None
    reviewer_id: Optional[str] = None


# --------------------------------------------------------------------------- #
# Master-data records (integration connectors - adapters/connectors/) - a
# reference-data lookup, not a submission source: no persistence, no policy/
# risk wiring yet. See adapters/connectors/base.py's EmployeeDirectoryConnector/
# FinanceMasterConnector.
# --------------------------------------------------------------------------- #
class EmployeeRecord(BaseModel):
    employee_id: str
    display_name: Optional[str] = None
    manager_id: Optional[str] = None
    cost_center: Optional[str] = None
    department: Optional[str] = None
    active: bool = True


class CostCenterRecord(BaseModel):
    cost_center: str
    oe_code: str
    active: bool = True


class VendorRecord(BaseModel):
    vendor_id: str
    name: str
    blocked: bool = False


# --------------------------------------------------------------------------- #
# LangGraph shared state (Tech Design 2.3)
# --------------------------------------------------------------------------- #
class ReceiptRef(BaseModel):
    line_id: str
    blob_url: str
    fmt: Optional[str] = None  # photo | scanned_pdf | e_receipt


class ExtractedLine(BaseModel):
    line_id: str
    vendor: Optional[str] = None
    # `_date` alias avoids the field name `date` shadowing the type in its own
    # annotation (with `from __future__ import annotations` active).
    date: Optional[_date] = None
    # Printed invoice/receipt/reference number, when the provider can read one
    # off the document - None under SimulatedVisionExtractor (its .sim.json
    # sidecar predates this field) and for any receipt with no such number
    # printed on it. Used for structured duplicate matching (VerificationAgent
    # ._duplicate) alongside embedding similarity - never required, never
    # inferred.
    invoice_number: Optional[str] = None
    amount: Optional[float] = None
    tax: Optional[float] = None
    currency: Optional[str] = None
    confidence: float = 0.0  # 0-1
    # ISO 639-1 code (e.g. "en", "de", "ja") the vision model read the receipt
    # in - not a translation of the receipt itself, just an audit trail so a
    # reviewer can see what language the original was in, since `vendor` etc.
    # above may already be normalised/translated by the model. None when the
    # provider didn't report one (e.g. an older sidecar with no language field).
    detected_language: Optional[str] = None


class ItemizedEntry(BaseModel):
    """One auto-detected line item read off a single multi-item invoice/receipt.

    Produced by `VisionExtractor.extract_items()` - one vision read of the whole
    document, split into N candidate expense lines instead of the human
    pre-declaring how many lines exist and what category each is.
    """

    description: Optional[str] = None
    vendor: Optional[str] = None
    date: Optional[_date] = None
    invoice_number: Optional[str] = None
    amount: Optional[float] = None
    tax: Optional[float] = None
    currency: Optional[str] = None
    category: str = "misc"
    confidence: float = 0.0  # 0-1
    detected_language: Optional[str] = None


class DuplicateMatch(BaseModel):
    submission_id: str
    similarity: float
    # "embedding" (content/amount similarity search) or "invoice_number" (exact
    # structured match on vendor+invoice_number) - the latter overrides the
    # former for the same submission_id, since an exact structured match is
    # strictly stronger evidence than a fuzzy content match.
    match_type: Literal["embedding", "invoice_number"] = "embedding"


class VerificationResult(BaseModel):
    authenticity_flags: list[str] = Field(default_factory=list)
    duplicate_matches: list[DuplicateMatch] = Field(default_factory=list)
    subtotal_variance_pct: Optional[float] = None
    # The two operands behind subtotal_variance_pct - kept alongside the
    # percentage so the UI/explanation can show the actual calculation
    # (entered vs receipt amount+tax), not just the resulting number.
    subtotal_entered_total: Optional[float] = None
    subtotal_receipt_total: Optional[float] = None
    # Rapid-succession same-category spending (e.g. 3+ meals same day) - BR-TE-AU-19.
    velocity_flags: list[str] = Field(default_factory=list)
    # 2+ same-category charges from one employee, each under the category cap
    # individually, summing over it within a short window - BR-TE-AU-19.
    split_transaction_flags: list[str] = Field(default_factory=list)
    merchant_validation: MerchantValidation = MerchantValidation.unverified
    # Sanctions/PEP watchlist hits (simulated - BR-TE-AU-03), one entry per match.
    merchant_flags: list[str] = Field(default_factory=list)
    # Rolling-window cumulative-cap breaches (e.g. annual FCPA/anti-bribery
    # gift-and-entertainment aggregate limits) - BR-TE-AU-04.
    compliance_flags: list[str] = Field(default_factory=list)
    # Statistical peer-group outliers: a category's spend on this submission
    # is far above the population baseline (mean/stddev computed live across
    # every OTHER employee in the same OE+category), even though no flat
    # authored cap was ever breached - catches spend that's "normal" against
    # a fixed threshold but abnormal against how peers actually spend.
    peer_outlier_flags: list[str] = Field(default_factory=list)
    # Cross-employee merchant network analysis (distinct from merchant_flags'
    # per-line blocklist/registry lookup): a rarely-seen merchant suddenly
    # used by many distinct employees, several employees' amounts clustering
    # just under a cap for the same vendor, or a fuzzy name-variant match
    # against an already-blocked registry entry.
    merchant_network_flags: list[str] = Field(default_factory=list)


class RuleResult(BaseModel):
    rule_id: str
    passed: bool


class PolicyEvaluation(BaseModel):
    rule_results: list[RuleResult] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    advisory_notes: list[str] = Field(default_factory=list)  # learned layer, advisory only


class NodeError(BaseModel):
    node: str
    message: str
    recoverable: bool


class AuditState(BaseModel):
    """Single mutable object passed through every LangGraph node (Tech Design 2.3).

    Each node reads what it needs and appends its own results; nodes never mutate
    another node's section.
    """

    submission_id: str
    raw_receipts: list[ReceiptRef] = Field(default_factory=list)
    extracted_lines: list[ExtractedLine] = Field(default_factory=list)
    verification: VerificationResult = Field(default_factory=VerificationResult)
    policy_evaluation: PolicyEvaluation = Field(default_factory=PolicyEvaluation)
    risk_score: Optional[float] = None
    routing_decision: Optional[RoutingDecision] = None
    explanation: Optional[str] = None
    errors: list[NodeError] = Field(default_factory=list)
