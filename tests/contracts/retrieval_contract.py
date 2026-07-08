from __future__ import annotations

from aegis_dx.domain import ArtifactRecord, TriageDecision, UrgencyLevel
from aegis_dx.ports import RetrievalPort


def assert_retrieval_port_contract(adapter: RetrievalPort) -> None:
    artifact = ArtifactRecord(
        mime_type="application/dicom",
        de_identified=True,
        de_identified_text="Possible pneumonia in the right lower lobe.",
    )
    triage = TriageDecision(
        modality="chest_xray",
        region="thorax",
        urgency=UrgencyLevel.ROUTINE,
    )

    evidence = adapter.retrieve(artifact, triage)

    assert evidence
    for snippet in evidence:
        assert snippet.source_id
        assert snippet.title
        assert snippet.snippet
        assert snippet.source_type

