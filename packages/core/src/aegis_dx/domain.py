from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


RESEARCH_ONLY_DISCLAIMER = (
    "Research prototype only. This draft is not for clinical use and must be "
    "confirmed, edited, or rejected by a licensed clinician."
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CaseStatus(str, Enum):
    RECEIVED = "Received"
    DEIDENTIFIED = "DeIdentified"
    TRIAGED = "Triaged"
    ANALYZING = "Analyzing"
    VERIFYING = "Verifying"
    SYNTHESIZED = "Synthesized"
    CALIBRATED = "Calibrated"
    ESCALATED = "Escalated"
    DEGRADED = "Degraded"
    AWAITING_REVIEW = "AwaitingReview"
    CONFIRMED = "Confirmed"
    EDITED = "Edited"
    REJECTED = "Rejected"
    CLOSED = "Closed"


class ActorRole(str, Enum):
    CLINICIAN = "clinician"
    REVIEWER = "reviewer"
    ADMIN = "admin"
    AUDITOR = "auditor"
    SERVICE = "service"


class UrgencyLevel(str, Enum):
    ROUTINE = "routine"
    URGENT = "urgent"
    STAT = "stat"


class HumanAction(str, Enum):
    CONFIRM = "confirm"
    EDIT = "edit"
    REJECT = "reject"


TERMINAL_CASE_STATUSES = {
    CaseStatus.CONFIRMED,
    CaseStatus.EDITED,
    CaseStatus.REJECTED,
    CaseStatus.CLOSED,
}


PROCESSABLE_CASE_STATUSES = {
    CaseStatus.RECEIVED,
    CaseStatus.DEIDENTIFIED,
    CaseStatus.TRIAGED,
    CaseStatus.ANALYZING,
    CaseStatus.VERIFYING,
    CaseStatus.SYNTHESIZED,
    CaseStatus.CALIBRATED,
    CaseStatus.ESCALATED,
    CaseStatus.DEGRADED,
}


class Principal(BaseModel):
    actor_id: str
    tenant_id: str
    role: ActorRole


class ArtifactInput(BaseModel):
    mime_type: str = "application/dicom"
    report_text: str | None = None
    artifact_uri: str | None = None
    source_system: str = "manual-upload"


class ArtifactRecord(ArtifactInput):
    de_identified: bool = False
    de_identified_text: str | None = None


class TriageDecision(BaseModel):
    modality: str
    region: str
    urgency: UrgencyLevel = UrgencyLevel.ROUTINE


class Finding(BaseModel):
    claim: str
    locus: str
    probability: float
    source_agent: str
    model_version: str
    saliency_ref: str | None = None


class EvidenceSnippet(BaseModel):
    source_id: str
    title: str
    snippet: str
    source_type: str
    uri: str | None = None


class VerificationResult(BaseModel):
    claim: str
    agreement_score: float
    critic_flags: list[str] = Field(default_factory=list)
    requires_escalation: bool = False


class DifferentialItem(BaseModel):
    diagnosis: str
    confidence: float
    rationale: str


class EscalationDecision(BaseModel):
    required: bool = False
    reason: str | None = None


class StructuredReport(BaseModel):
    summary: str
    findings: list[str] = Field(default_factory=list)
    evidence_links: list[str] = Field(default_factory=list)
    disclaimer: str = RESEARCH_ONLY_DISCLAIMER


class SegmentationBox(BaseModel):
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @model_validator(mode="after")
    def validate_ordered_coordinates(self) -> "SegmentationBox":
        if min(self.x_min, self.y_min, self.x_max, self.y_max) < 0:
            raise ValueError("Segmentation box coordinates must be non-negative.")
        if self.x_min >= self.x_max or self.y_min >= self.y_max:
            raise ValueError("Segmentation box maximum coordinates must exceed minimum coordinates.")
        return self


class SegmentationRefinementRequest(BaseModel):
    artifact_uri: str
    box: SegmentationBox


class SegmentationRefinementResult(BaseModel):
    artifact_uri: str
    model_version: str
    mask_encoding: str = "rle"
    mask_shape: tuple[int, int]
    positive_pixels: int
    rle: list[int] = Field(default_factory=list)


class HumanReviewRecord(BaseModel):
    action: HumanAction
    actor_id: str
    acted_at: datetime = Field(default_factory=utc_now)
    note: str | None = None
    edited_summary: str | None = None


class CaseRecord(BaseModel):
    case_id: str
    trace_id: str
    tenant_id: str
    site_id: str | None = None
    status: CaseStatus
    artifact: ArtifactRecord
    modality: str | None = None
    region: str | None = None
    urgency: UrgencyLevel = UrgencyLevel.ROUTINE
    evidence: list[EvidenceSnippet] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    verification: list[VerificationResult] = Field(default_factory=list)
    verification_round: int = 0
    consensus_kappa: float | None = None
    complexity_tier: str | None = None
    differential: list[DifferentialItem] = Field(default_factory=list)
    reflexion_revisions: int = 0
    reflexion_incomplete: bool = False
    escalation: EscalationDecision = Field(default_factory=EscalationDecision)
    report: StructuredReport | None = None
    human_review: HumanReviewRecord | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CaseSubmissionRequest(BaseModel):
    artifact: ArtifactInput
    site_id: str | None = None
    patient_reference: str | None = None


class CaseSubmissionAccepted(BaseModel):
    case_id: str
    trace_id: str
    status: CaseStatus
    idempotency_replayed: bool = False


class CaseReviewRequest(BaseModel):
    action: HumanAction
    note: str | None = None
    edited_summary: str | None = None


class AuditEvent(BaseModel):
    sequence: int | None = None
    case_id: str
    tenant_id: str
    event_type: str
    actor_id: str
    actor_role: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    previous_hash: str | None = None
    entry_hash: str | None = None


class CaseLifecycleEvent(BaseModel):
    sequence: int | None = None
    case_id: str
    tenant_id: str
    event_type: str
    schema_version: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class EventSchemaDefinition(BaseModel):
    event_type: str
    schema_version: str
    description: str
    required_payload_fields: list[str] = Field(default_factory=list)


class ModelRuntimeStatus(BaseModel):
    component: str
    backend: str
    model_version: str
    execution_mode: str
    configured: bool
    fallback_available: bool
    runtime_ready: bool
    readiness_reason: str
