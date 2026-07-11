from __future__ import annotations

from aegis_dx.domain import (
    ArtifactRecord,
    DifferentialItem,
    EscalationDecision,
    EvidenceSnippet,
    Finding,
    StructuredReport,
    TriageDecision,
    VerificationResult,
)
from aegis_dx.ports import ReportPort, RetrievalPort, SynthesisPort

MAX_REFLEXION_REVISIONS = 2
MIN_REFLEXION_QUALITY_SCORE = 0.7


class StubRetrievalAdapter(RetrievalPort):
    def retrieve(
        self,
        artifact: ArtifactRecord,
        triage: TriageDecision,
    ) -> list[EvidenceSnippet]:
        text = (artifact.de_identified_text or "").lower()
        if triage.modality == "chest_xray" and "pneumonia" in text:
            return [
                EvidenceSnippet(
                    source_id="guideline-cxr-pneumonia",
                    title="CXR pneumonia follow-up guidance",
                    snippet=(
                        "Focal lower-lobe opacity on chest radiography should be correlated "
                        "with air-space disease and clinician assessment."
                    ),
                    source_type="guideline",
                    uri="guideline://cxr/pneumonia",
                ),
                EvidenceSnippet(
                    source_id="prior-pattern-rll-opacity",
                    title="Reference pattern: right lower lung opacity",
                    snippet="Right lower lobe findings commonly map to focal infectious infiltrates.",
                    source_type="reference-case",
                    uri="reference://cxr/right-lower-lung-opacity",
                ),
            ]
        if triage.modality == "chest_xray" and "effusion" in text:
            return [
                EvidenceSnippet(
                    source_id="guideline-cxr-effusion",
                    title="Pleural effusion review note",
                    snippet="Costophrenic angle blunting is a common radiographic correlate of pleural effusion.",
                    source_type="guideline",
                    uri="guideline://cxr/effusion",
                )
            ]
        if triage.modality == "ecg":
            return [
                EvidenceSnippet(
                    source_id="triage-ecg-urgent-review",
                    title="ECG urgent review policy",
                    snippet="Stat ECG cases should be routed for supervisor review when no specialist is available.",
                    source_type="policy",
                    uri="policy://ecg/stat-review",
                )
            ]
        return [
            EvidenceSnippet(
                source_id="guideline-cxr-general",
                title="General chest radiography review checklist",
                snippet="Document whether there is focal opacity, pleural effusion, or acute cardiopulmonary abnormality.",
                source_type="guideline",
                uri="guideline://cxr/general-review",
            )
        ]


class StubSynthesisAdapter(SynthesisPort):
    def synthesize(
        self,
        findings: list[Finding],
        evidence: list[EvidenceSnippet],
        triage: TriageDecision,
    ) -> list[DifferentialItem]:
        if not findings:
            return []
        top_finding = findings[0]
        evidence_title = evidence[0].title if evidence else "retrieved case context"
        label = top_finding.claim.replace("Possible ", "").replace(".", "")
        return [
            DifferentialItem(
                diagnosis=label,
                confidence=round(top_finding.probability, 2),
                rationale=(
                    f"Derived from {top_finding.source_agent} at {top_finding.locus}, "
                    f"supported by {evidence_title}."
                ),
            )
        ]


class StubReportAdapter(ReportPort):
    def compose(
        self,
        artifact: ArtifactRecord,
        triage: TriageDecision,
        findings: list[Finding],
        evidence: list[EvidenceSnippet],
        differential: list[DifferentialItem],
        verification: list[VerificationResult],
        escalation: EscalationDecision,
    ) -> StructuredReport:
        evidence_links = [snippet.uri for snippet in evidence if snippet.uri]
        evidence_links.extend(
            finding.saliency_ref for finding in findings if finding.saliency_ref is not None
        )
        verification_by_claim = {item.claim: item for item in verification}
        report_findings: list[str] = []
        for finding in findings:
            line = f"{finding.claim} (confidence {finding.probability:.2f})"
            result = verification_by_claim.get(finding.claim)
            if result is not None:
                line = f"{line}; verifier agreement {result.agreement_score:.2f}"
                if result.critic_flags:
                    line = f"{line}; flags: {', '.join(result.critic_flags)}"
            report_findings.append(line)

        summary = (
            f"Draft clinician review package prepared for {triage.modality} analysis "
            "with retrieved evidence support."
        )
        if differential:
            summary = f"{summary} Top differential: {differential[0].diagnosis}."
        if verification:
            mean_agreement = sum(item.agreement_score for item in verification) / len(verification)
            summary = f"{summary} Independent verifier agreement: {mean_agreement:.2f}."
        if escalation.required:
            summary = f"{summary} Escalation required: {escalation.reason or 'manual review is required.'}"
        else:
            summary = f"{summary} Guardrail review did not require escalation."
        return StructuredReport(
            summary=summary,
            findings=report_findings,
            evidence_links=evidence_links,
        )


class ReflexiveSynthesisAdapter(SynthesisPort):
    """Reflexion loop (docs/15-agentic-architecture.md SS5.1) wrapping any SynthesisPort.

    Actor (the wrapped `inner` synthesizer) produces a differential -> a
    self-evaluator scores it against explicit grounding/confidence criteria ->
    below threshold, revise and retry -> bounded to `max_revisions`. Per D18
    ("agents in loops for sure things"): the loop always terminates, and a
    persistent failure sets `last_incomplete` for the caller to surface rather
    than silently accepting a low-quality differential.

    The evaluator/reviser here are deterministic, matching the rest of this
    codebase's "no new model training" constraint - but the interface is the
    same one a real self-critique LLM call would implement, so wiring an
    LLM-backed `inner` synthesizer later is a drop-in change, not a redesign.
    """

    def __init__(
        self,
        inner: SynthesisPort,
        *,
        max_revisions: int = MAX_REFLEXION_REVISIONS,
        min_quality_score: float = MIN_REFLEXION_QUALITY_SCORE,
    ) -> None:
        self._inner = inner
        self._max_revisions = max_revisions
        self._min_quality_score = min_quality_score
        self.last_revisions = 0
        self.last_incomplete = False

    def synthesize(
        self,
        findings: list[Finding],
        evidence: list[EvidenceSnippet],
        triage: TriageDecision,
    ) -> list[DifferentialItem]:
        differential = self._inner.synthesize(findings, evidence, triage)
        revisions = 0

        while True:
            score, _issues = self._evaluate(differential, findings)
            if score >= self._min_quality_score or revisions >= self._max_revisions:
                self.last_revisions = revisions
                self.last_incomplete = score < self._min_quality_score
                return differential

            revisions += 1
            differential = self._revise(differential, findings, evidence, triage)

    def _evaluate(
        self,
        differential: list[DifferentialItem],
        findings: list[Finding],
    ) -> tuple[float, list[str]]:
        """Self-evaluator criteria: every differential item must (1) cite a
        specific finding's locus or source agent in its rationale - not just a
        generic-sounding sentence - and (2) not claim confidence meaningfully
        higher than the strongest finding that could support it. Both are
        concrete, checkable proxies for "is this grounded in evidence" per
        docs/15's reflexion quality bar (near 1.0 for medical agents).
        """
        if not differential:
            return (1.0, []) if not findings else (0.0, ["no differential was produced from findings"])

        max_finding_probability = max((finding.probability for finding in findings), default=0.0)
        issues: list[str] = []
        grounded_count = 0

        for item in differential:
            is_grounded = any(
                finding.locus in item.rationale or finding.source_agent in item.rationale
                for finding in findings
            )
            is_overconfident = item.confidence > max_finding_probability + 0.1
            if is_grounded and not is_overconfident:
                grounded_count += 1
            else:
                if not is_grounded:
                    issues.append(f"'{item.diagnosis}' rationale does not cite a specific finding locus")
                if is_overconfident:
                    issues.append(f"'{item.diagnosis}' confidence exceeds the strongest supporting finding")

        return grounded_count / len(differential), issues

    def _revise(
        self,
        differential: list[DifferentialItem],
        findings: list[Finding],
        evidence: list[EvidenceSnippet],
        triage: TriageDecision,
    ) -> list[DifferentialItem]:
        """Bounded self-correction: re-run the actor, then deterministically
        repair whatever the evaluator flagged - explicit locus grounding, and
        confidence clamped to the strongest supporting finding. A real
        LLM-backed actor would instead condition its next generation on the
        evaluator's critique text directly; this keeps the same loop shape.
        """
        revised = self._inner.synthesize(findings, evidence, triage) or differential
        if not findings:
            return revised

        top_finding = findings[0]
        max_finding_probability = max(finding.probability for finding in findings)
        repaired: list[DifferentialItem] = []
        for item in revised:
            rationale = item.rationale
            if not any(finding.locus in rationale or finding.source_agent in rationale for finding in findings):
                rationale = f"{rationale} Grounded in {top_finding.source_agent} finding at {top_finding.locus}."
            confidence = min(item.confidence, round(max_finding_probability, 2))
            repaired.append(
                DifferentialItem(diagnosis=item.diagnosis, confidence=confidence, rationale=rationale)
            )
        return repaired
