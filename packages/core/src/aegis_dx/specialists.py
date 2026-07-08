from __future__ import annotations

from aegis_dx.domain import ArtifactRecord, Finding, TriageDecision
from aegis_dx.ports import SpecialistPort


class StubChestXRaySpecialistAdapter(SpecialistPort):
    modality = "chest_xray"

    def analyze(
        self,
        artifact: ArtifactRecord,
        triage: TriageDecision,
    ) -> list[Finding]:
        text = (artifact.de_identified_text or "").lower()
        if "pneumonia" in text:
            return [
                Finding(
                    claim="Possible right lower lobe pneumonia.",
                    locus="right-lower-lung-zone",
                    probability=0.76,
                    source_agent="cxr-specialist",
                    model_version="stub-medgemma-cxr-v1",
                    saliency_ref="overlay://right-lower-lung-zone",
                )
            ]
        if "effusion" in text:
            return [
                Finding(
                    claim="Small left pleural effusion.",
                    locus="left-costophrenic-angle",
                    probability=0.71,
                    source_agent="cxr-specialist",
                    model_version="stub-medgemma-cxr-v1",
                    saliency_ref="overlay://left-costophrenic-angle",
                )
            ]
        return [
            Finding(
                claim="No focal cardiopulmonary abnormality identified in the draft path.",
                locus="global-thorax",
                probability=0.63,
                source_agent="cxr-specialist",
                model_version="stub-medgemma-cxr-v1",
                saliency_ref="overlay://global-thorax",
            )
        ]


class SpecialistRegistry:
    def __init__(self, specialists: list[SpecialistPort] | None = None) -> None:
        self._specialists: dict[str, SpecialistPort] = {}
        for specialist in specialists or []:
            self.register(specialist)

    def register(self, specialist: SpecialistPort) -> None:
        self._specialists[specialist.modality] = specialist

    def resolve(self, modality: str | None) -> SpecialistPort | None:
        if modality is None:
            return None
        return self._specialists.get(modality)

