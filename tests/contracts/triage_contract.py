from __future__ import annotations

from aegis_dx.domain import ArtifactRecord, UrgencyLevel
from aegis_dx.ports import TriagePort


def assert_triage_port_contract(adapter: TriagePort) -> None:
    routine_artifact = ArtifactRecord(
        mime_type="application/dicom",
        de_identified=True,
        de_identified_text="Follow-up chest xray with stable outpatient findings.",
    )
    urgent_artifact = ArtifactRecord(
        mime_type="application/dicom",
        de_identified=True,
        de_identified_text="Urgent review requested for effusion.",
    )
    stat_signal_artifact = ArtifactRecord(
        mime_type="application/ecg",
        de_identified=True,
        de_identified_text="Critical stat ECG review requested.",
    )

    routine = adapter.classify(routine_artifact)
    urgent = adapter.classify(urgent_artifact)
    stat_signal = adapter.classify(stat_signal_artifact)

    assert routine.modality == "chest_xray"
    assert routine.region == "thorax"
    assert routine.urgency == UrgencyLevel.ROUTINE

    assert urgent.urgency == UrgencyLevel.URGENT

    assert stat_signal.modality == "ecg"
    assert stat_signal.region == "cardiac"
    assert stat_signal.urgency == UrgencyLevel.STAT
