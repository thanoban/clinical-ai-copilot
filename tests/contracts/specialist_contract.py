from __future__ import annotations

from aegis_dx.domain import ArtifactRecord, TriageDecision, UrgencyLevel
from aegis_dx.ports import SpecialistPort


def assert_specialist_port_contract(adapter: SpecialistPort) -> None:
    artifact = ArtifactRecord(
        mime_type="application/dicom",
        de_identified=True,
        de_identified_text="Possible pneumonia in the right lower lobe.",
    )
    triage = TriageDecision(
        modality=adapter.modality,
        region="thorax",
        urgency=UrgencyLevel.ROUTINE,
    )

    findings = adapter.analyze(artifact, triage)

    assert findings
    for finding in findings:
        assert finding.claim
        assert finding.locus
        assert 0.0 <= finding.probability <= 1.0
        assert finding.source_agent
        assert finding.model_version

