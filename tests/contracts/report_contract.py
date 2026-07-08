from __future__ import annotations

from aegis_dx.domain import ArtifactRecord, DifferentialItem, EvidenceSnippet, Finding, TriageDecision, UrgencyLevel
from aegis_dx.ports import ReportPort


def assert_report_port_contract(adapter: ReportPort) -> None:
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
    findings = [
        Finding(
            claim="Possible right lower lobe pneumonia.",
            locus="right-lower-lung-zone",
            probability=0.76,
            source_agent="cxr-specialist",
            model_version="stub-medgemma-cxr-v1",
            saliency_ref="overlay://right-lower-lung-zone",
        )
    ]
    evidence = [
        EvidenceSnippet(
            source_id="guideline-cxr-pneumonia",
            title="CXR pneumonia follow-up guidance",
            snippet="Correlate lower-lobe opacity with clinical findings.",
            source_type="guideline",
            uri="guideline://cxr/pneumonia",
        )
    ]
    differential = [
        DifferentialItem(
            diagnosis="right lower lobe pneumonia",
            confidence=0.76,
            rationale="Derived from cxr-specialist at right-lower-lung-zone.",
        )
    ]

    report = adapter.compose(artifact, triage, findings, evidence, differential)

    assert report.summary
    assert report.findings
    assert report.evidence_links
    assert report.disclaimer
