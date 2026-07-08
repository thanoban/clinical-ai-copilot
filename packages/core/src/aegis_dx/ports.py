from __future__ import annotations

from typing import Protocol

from aegis_dx.domain import (
    ArtifactInput,
    ArtifactRecord,
    AuditEvent,
    Finding,
    Principal,
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


class AuditPort(Protocol):
    def append(self, event: AuditEvent) -> AuditEvent:
        """Persist a new append-only audit event."""


class IdentityPort(Protocol):
    def authorize(self, principal: Principal, tenant_id: str) -> None:
        """Validate that the principal can act on the tenant-scoped resource."""
