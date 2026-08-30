"""Core domain models shared across all verification engines."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, computed_field


class Severity(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CheckStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    REQUIRES_REVIEW = "requires_review"


class CheckCategory(str, Enum):
    FORMAT_VALIDATION = "format_validation"
    MATHEMATICAL_VALIDATION = "mathematical_validation"
    STATISTICAL_ANALYSIS = "statistical_analysis"
    STRUCTURAL_VALIDATION = "structural_validation"
    CONSISTENCY_CHECK = "consistency_check"
    SEMANTIC_ANALYSIS = "semantic_analysis"
    EXTERNAL_VERIFICATION = "external_verification"
    ARITHMETIC_VERIFICATION = "arithmetic_verification"


class InputType(str, Enum):
    AUTO = "auto"
    MANUAL_NUMBER = "manual_number"
    MANUAL_DATASET = "manual_dataset"
    MANUAL_TEXT = "manual_text"
    STRUCTURED_JSON = "structured_json"
    IMAGE = "image"
    PDF = "pdf"
    CSV = "csv"
    XLSX = "xlsx"


class DocumentType(str, Enum):
    """Controlled enum for document-type classification."""
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    NATIONAL_ID = "national_id"
    PASSPORT = "passport"
    DRIVER_LICENSE = "driver_license"
    INVOICE = "invoice"
    BANK_STATEMENT = "bank_statement"
    RECEIPT = "receipt"
    TRANSACTION_DOCUMENT = "transaction_document"
    OTHER = "other"


class ValueType(str, Enum):
    """Controlled enum for value-type classification."""
    CARD_NUMBER = "card_number"
    ID_NUMBER = "id_number"
    CNIC = "cnic"
    PASSPORT_NUMBER = "passport_number"
    LICENSE_NUMBER = "license_number"
    INVOICE_NUMBER = "invoice_number"
    TRANSACTION_ID = "transaction_id"
    FINANCIAL_AMOUNT = "financial_amount"
    DATE = "date"
    PHONE_NUMBER = "phone_number"
    EMAIL = "email"
    URL = "url"
    GENERIC_IDENTIFIER = "generic_identifier"
    UNKNOWN = "unknown"


class OverallStatus(str, Enum):
    LIKELY_VALID = "likely_valid"
    VALID_WITH_WARNINGS = "valid_with_warnings"
    ANOMALOUS = "anomalous"
    REQUIRES_REVIEW = "requires_review"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    INVALID = "invalid"


# Presentation-layer mapping: internal granularity → 3-value UX display string.
_STATUS_DISPLAY: dict[OverallStatus, str] = {
    OverallStatus.LIKELY_VALID: "LIKELY VALID",
    OverallStatus.VALID_WITH_WARNINGS: "INSUFFICIENT EVIDENCE",
    OverallStatus.ANOMALOUS: "INSUFFICIENT EVIDENCE",
    OverallStatus.REQUIRES_REVIEW: "INSUFFICIENT EVIDENCE",
    OverallStatus.INVALID: "INVALID / FRAUD DETECTED",
    OverallStatus.INSUFFICIENT_EVIDENCE: "INSUFFICIENT EVIDENCE",
}


def simplify_status(status: OverallStatus) -> str:
    """Map an internal OverallStatus to one of three user-facing display strings."""
    return _STATUS_DISPLAY[status]


class Evidence(BaseModel):
    check: str = Field(..., description="Name of the check performed")
    category: CheckCategory
    status: CheckStatus
    confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="How confident the system is in this check result (not fraud probability)",
    )
    severity: Severity = Severity.NONE
    message: str = Field(default="", description="Human-readable explanation")
    details: dict[str, object] = Field(default_factory=dict)


class ClassificationCandidate(BaseModel):
    type: str = Field(..., description="Classification type identifier")
    label: str = Field(..., description="Human-readable label")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Classification confidence score")
    reason: str = Field(default="", description="Short explanation for this classification")
    layer: str = Field(
        default="value",
        description="Which classification layer this candidate belongs to: 'document' or 'value'",
    )


class InputClassification(BaseModel):
    type: str = Field(..., description="Detected input category")
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    candidates: list[ClassificationCandidate] = Field(default_factory=list)


class RiskAssessment(BaseModel):
    risk_score: int = Field(
        ..., ge=0, le=100,
        description="How suspicious the evidence is (0 = not suspicious, 100 = very suspicious)",
    )
    confidence: int = Field(
        ..., ge=0, le=100,
        description="How confident the system is in its own analysis",
    )
    level: str = Field(
        ...,
        description="Human-readable risk level: low, moderate, elevated, high, unknown",
    )
    checks_determinate: int = Field(
        default=0, ge=0,
        description="Checks that actually returned a verdict (passed/failed/warning/review)",
    )
    checks_total: int = Field(
        default=0, ge=0,
        description="Checks attempted, including those that could not run",
    )


class AnalysisResponse(BaseModel):
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    input_classification: InputClassification | None = None
    classification_source: str = Field(
        default="automatic",
        description="How the classification was determined: 'automatic' or 'confirmed'",
    )
    extracted_data: dict[str, object] = Field(default_factory=dict)
    checks: list[Evidence] = Field(default_factory=list)
    statistical_analysis: dict[str, object] = Field(default_factory=dict)
    consistency_analysis: dict[str, object] = Field(default_factory=dict)
    external_verification: dict[str, object] = Field(default_factory=dict)
    risk_assessment: RiskAssessment | None = None
    overall_status: OverallStatus = OverallStatus.INSUFFICIENT_EVIDENCE
    limitations: list[str] = Field(default_factory=list)
    recommendation: str = ""
    explanation: str = ""
    document_candidates: list[ClassificationCandidate] = Field(default_factory=list)
    value_candidates: list[ClassificationCandidate] = Field(default_factory=list)
    top_document_type: str = Field(default="", description="Highest-confidence document type")
    top_value_type: str = Field(default="", description="Highest-confidence value type")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def display_status(self) -> str:
        """Simplified user-facing status derived from overall_status."""
        return simplify_status(self.overall_status)


class ClassificationResponse(BaseModel):
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    classification_id: str = Field(
        default="",
        description="Opaque token linking this classification to a subsequent /api/analyze confirmation.",
    )
    input_value: str = Field(..., description="Original input value (may be masked)")
    candidates: list[ClassificationCandidate] = Field(default_factory=list)
    recommended_type: str = Field(default="", description="Highest-confidence value type (backward compat)")
    recommended_label: str = Field(default="", description="Human-readable recommended type")
    document_candidates: list[ClassificationCandidate] = Field(default_factory=list)
    value_candidates: list[ClassificationCandidate] = Field(default_factory=list)
    top_document_type: str = Field(default="", description="Highest-confidence document type")
    top_value_type: str = Field(default="", description="Highest-confidence value type")
