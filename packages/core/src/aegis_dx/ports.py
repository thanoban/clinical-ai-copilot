from __future__ import annotations

from typing import Protocol

from aegis_dx.domain import (
    ArtifactInput,
    ArtifactRecord,
    AuditEvent,
    CaseLifecycleEvent,
    CaseRecord,
    DifferentialItem,
    EscalationDecision,
    EvidenceSnippet,
    Finding,
    Principal,
    StructuredReport,
    TriageDecision,
    VerificationResult,
)


class IngestionPort(Protocol):
    def normalize(self, artifact: ArtifactInput) -> ArtifactRecord:
        """Convert a raw artifact into a de-identified normalized artifact."""


class TriagePort(Protocol):
    def classify(self, artifact: ArtifactRecord) -> TriageDecision:
        """Determine the modality, body region, and urgency for a case."""


class SpecialistPort(Protocol):
    modality: str

    def analyze(
        self,
        artifact: ArtifactRecord,
        triage: TriageDecision,
    ) -> list[Finding]:
        """Produce findings for a routed modality without leaking workflow concerns."""


class RetrievalPort(Protocol):
    def retrieve(
        self,
        artifact: ArtifactRecord,
        triage: TriageDecision,
    ) -> list[EvidenceSnippet]:
        """Fetch supporting evidence snippets for the current case context."""


class SynthesisPort(Protocol):
    def synthesize(
        self,
        findings: list[Finding],
        evidence: list[EvidenceSnippet],
        triage: TriageDecision,
    ) -> list[DifferentialItem]:
        """Fuse findings and retrieved evidence into a ranked differential."""


class ReportPort(Protocol):
    def compose(
        self,
        artifact: ArtifactRecord,
        triage: TriageDecision,
        findings: list[Finding],
        evidence: list[EvidenceSnippet],
        differential: list[DifferentialItem],
    ) -> StructuredReport:
        """Render the clinician-facing draft report."""


class VerificationPort(Protocol):
    def verify(
        self,
        findings: list[Finding],
        evidence: list[EvidenceSnippet],
        triage: TriageDecision,
    ) -> list[VerificationResult]:
        """Challenge specialist findings and emit agreement or escalation flags."""


class GuardrailPort(Protocol):
    def decide(
        self,
        findings: list[Finding],
        verification: list[VerificationResult],
        triage: TriageDecision,
    ) -> EscalationDecision:
        """Turn verification outcomes into an escalation decision."""


class AuditPort(Protocol):
    def append(self, event: AuditEvent) -> AuditEvent:
        """Persist a new append-only audit event."""


class IdentityPort(Protocol):
    def authorize(self, principal: Principal, tenant_id: str) -> None:
        """Validate that the principal can act on the tenant-scoped resource."""


class CaseStorePort(Protocol):
    """Structural contract shared by SQLiteCaseStore and PostgresCaseStore.

    Lets WorkflowRuntime accept either backend interchangeably - only
    config.py decides which concrete store gets constructed.
    """

    def save_case(self, case: CaseRecord) -> CaseRecord: ...

    def get_case(self, case_id: str) -> CaseRecord | None: ...

    def get_case_by_idempotency_key(self, tenant_id: str, idempotency_key: str) -> CaseRecord | None: ...

    def list_cases_for_tenant(self, tenant_id: str) -> list[CaseRecord]: ...

    def list_pending_case_ids(self) -> list[str]: ...

    def register_idempotency_key(
        self, tenant_id: str, idempotency_key: str, case_id: str, created_at: str
    ) -> None: ...

    def append_audit_event(self, event: AuditEvent) -> AuditEvent: ...

    def list_audit_events(self, case_id: str, tenant_id: str) -> list[AuditEvent]: ...

    def append_case_event(self, event: CaseLifecycleEvent) -> CaseLifecycleEvent: ...

    def list_case_events(self, case_id: str, tenant_id: str) -> list[CaseLifecycleEvent]: ...
