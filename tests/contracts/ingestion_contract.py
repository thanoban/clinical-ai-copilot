from __future__ import annotations

from aegis_dx.domain import ArtifactInput
from aegis_dx.ports import IngestionPort


def assert_ingestion_port_contract(adapter: IngestionPort) -> None:
    artifact = ArtifactInput(
        mime_type="application/dicom",
        report_text="Patient 123456 can be reached at foo@example.com.",
        source_system="contract-test",
    )

    normalized = adapter.normalize(artifact)

    assert normalized.mime_type == artifact.mime_type
    assert normalized.source_system == artifact.source_system
    assert normalized.de_identified is True
    assert normalized.de_identified_text is not None
    assert "123456" not in normalized.de_identified_text
    assert "foo@example.com" not in normalized.de_identified_text

