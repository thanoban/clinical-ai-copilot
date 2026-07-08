from __future__ import annotations

from aegis_dx.domain import EvidenceSnippet, Finding, TriageDecision, UrgencyLevel
from aegis_dx.ports import VerificationPort


def assert_verification_port_contract(adapter: VerificationPort) -> None:
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
    triage = TriageDecision(modality="chest_xray", region="thorax", urgency=UrgencyLevel.ROUTINE)

    verification = adapter.verify(findings, evidence, triage)

    assert verification
    for item in verification:
        assert item.claim
        assert 0.0 <= item.agreement_score <= 1.0
        assert isinstance(item.critic_flags, list)
        assert isinstance(item.requires_escalation, bool)

