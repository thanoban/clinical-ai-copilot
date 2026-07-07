from __future__ import annotations

import re

from aegis_dx.domain import ArtifactInput, ArtifactRecord, TriageDecision, UrgencyLevel
from aegis_dx.ports import IngestionPort, TriagePort


class StubIngestionAdapter(IngestionPort):
    _mrn_pattern = re.compile(r"\b\d{6,}\b")
    _email_pattern = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")

    def normalize(self, artifact: ArtifactInput) -> ArtifactRecord:
        text = artifact.report_text or ""
        text = self._mrn_pattern.sub("[redacted-id]", text)
        text = self._email_pattern.sub("[redacted-email]", text)
        return ArtifactRecord(
            **artifact.model_dump(),
            de_identified=True,
            de_identified_text=text or None,
        )


class StubTriageAdapter(TriagePort):
    def classify(self, artifact: ArtifactRecord) -> TriageDecision:
        text = (artifact.de_identified_text or "").lower()
        if "stat" in text or "critical" in text:
            urgency = UrgencyLevel.STAT
        elif "urgent" in text:
            urgency = UrgencyLevel.URGENT
        else:
            urgency = UrgencyLevel.ROUTINE

        if "ecg" in artifact.mime_type.lower():
            return TriageDecision(modality="ecg", region="cardiac", urgency=urgency)

        return TriageDecision(
            modality="chest_xray",
            region="thorax",
            urgency=urgency,
        )

