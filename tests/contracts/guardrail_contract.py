from __future__ import annotations

from aegis_dx.domain import Finding, TriageDecision, UrgencyLevel, VerificationResult
from aegis_dx.ports import GuardrailPort


def assert_guardrail_port_contract(adapter: GuardrailPort) -> None:
    findings = [
        Finding(
            claim="Possible right lower lobe pneumonia.",
            locus="right-lower-lung-zone",
            probability=0.64,
            source_agent="cxr-specialist",
            model_version="stub-medgemma-cxr-v1",
        )
    ]
    verification = [
        VerificationResult(
            claim="Possible right lower lobe pneumonia.",
            agreement_score=0.59,
            critic_flags=["low_confidence_finding"],
            requires_escalation=True,
        )
    ]
    triage = TriageDecision(modality="chest_xray", region="thorax", urgency=UrgencyLevel.ROUTINE)

    decision = adapter.decide(findings, verification, triage)

    assert isinstance(decision.required, bool)
    if decision.required:
        assert decision.reason
