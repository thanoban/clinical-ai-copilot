from __future__ import annotations

from aegis_dx.domain import (
    ArtifactRecord,
    DifferentialItem,
    EvidenceSnippet,
    Finding,
    StructuredReport,
    TriageDecision,
)
from aegis_dx.ports import ReportPort, RetrievalPort, SynthesisPort


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
    ) -> StructuredReport:
        evidence_links = [snippet.uri for snippet in evidence if snippet.uri]
        evidence_links.extend(
            finding.saliency_ref for finding in findings if finding.saliency_ref is not None
        )
        summary = (
            f"Draft clinician review package prepared for {triage.modality} analysis "
            "with retrieved evidence support."
        )
        if differential:
            summary = f"{summary} Top differential: {differential[0].diagnosis}."
        return StructuredReport(
            summary=summary,
            findings=[finding.claim for finding in findings],
            evidence_links=evidence_links,
        )
