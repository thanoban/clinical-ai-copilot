from __future__ import annotations

from typing import Protocol

from aegis_dx.domain import ArtifactInput, ArtifactRecord, AuditEvent, Principal, TriageDecision


class IngestionPort(Protocol):
    def normalize(self, artifact: ArtifactInput) -> ArtifactRecord:
        """Convert a raw artifact into a de-identified normalized artifact."""


class TriagePort(Protocol):
    def classify(self, artifact: ArtifactRecord) -> TriageDecision:
        """Determine the modality, body region, and urgency for a case."""


class AuditPort(Protocol):
    def append(self, event: AuditEvent) -> AuditEvent:
        """Persist a new append-only audit event."""


class IdentityPort(Protocol):
    def authorize(self, principal: Principal, tenant_id: str) -> None:
        """Validate that the principal can act on the tenant-scoped resource."""

