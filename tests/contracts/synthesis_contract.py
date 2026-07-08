from __future__ import annotations

from aegis_dx.domain import EvidenceSnippet, Finding, TriageDecision, UrgencyLevel
from aegis_dx.ports import SynthesisPort


def assert_synthesis_port_contract(adapter: SynthesisPort) -> None:
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
    triage = TriageDecision(
        modality="chest_xray",
        region="thorax",
        urgency=UrgencyLevel.ROUTINE,
    )

    differential = adapter.synthesize(findings, evidence, triage)

    assert differential
    assert differential[0].diagnosis
    assert 0.0 <= differential[0].confidence <= 1.0
    assert differential[0].rationale

