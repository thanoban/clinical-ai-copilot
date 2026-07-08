from __future__ import annotations

from typing import Protocol

from aegis_dx.domain import (
    ArtifactInput,
    ArtifactRecord,
    AuditEvent,
    DifferentialItem,
    EvidenceSnippet,
    Finding,
    Principal,
    StructuredReport,
    TriageDecision,
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


class AuditPort(Protocol):
    def append(self, event: AuditEvent) -> AuditEvent:
        """Persist a new append-only audit event."""


class IdentityPort(Protocol):
    def authorize(self, principal: Principal, tenant_id: str) -> None:
        """Validate that the principal can act on the tenant-scoped resource."""
