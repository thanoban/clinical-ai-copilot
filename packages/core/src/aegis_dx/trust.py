from __future__ import annotations

from aegis_dx.domain import EscalationDecision, EvidenceSnippet, Finding, TriageDecision, UrgencyLevel, VerificationResult
from aegis_dx.ports import GuardrailPort, VerificationPort


class StubVerificationAdapter(VerificationPort):
    def verify(
        self,
        findings: list[Finding],
        evidence: list[EvidenceSnippet],
        triage: TriageDecision,
    ) -> list[VerificationResult]:
        evidence_count = len(evidence)
        results: list[VerificationResult] = []
        for finding in findings:
            critic_flags: list[str] = []
            requires_escalation = False

            if finding.probability < 0.7:
                critic_flags.append("low_confidence_finding")
                requires_escalation = True

            if evidence_count == 0:
                critic_flags.append("missing_supporting_evidence")
                requires_escalation = True

            if "possible" in finding.claim.lower():
                critic_flags.append("tentative_claim_language")

            agreement_score = round(
                min(0.98, max(0.55, finding.probability - 0.08 + min(evidence_count, 2) * 0.03)),
                2,
            )
            results.append(
                VerificationResult(
                    claim=finding.claim,
                    agreement_score=agreement_score,
                    critic_flags=critic_flags,
                    requires_escalation=requires_escalation,
                )
            )
        return results


class StubGuardrailAdapter(GuardrailPort):
    def decide(
        self,
        findings: list[Finding],
        verification: list[VerificationResult],
        triage: TriageDecision,
    ) -> EscalationDecision:
        if triage.urgency == UrgencyLevel.STAT:
            return EscalationDecision(required=True, reason="Stat cases require supervisor review.")

        if any("missing_supporting_evidence" in item.critic_flags for item in verification):
            return EscalationDecision(
                required=True,
                reason="Insufficient supporting evidence requires human escalation.",
            )

        if any(item.requires_escalation for item in verification):
            return EscalationDecision(
                required=True,
                reason="Low-confidence findings require human escalation.",
            )

        return EscalationDecision(required=False, reason=None)
