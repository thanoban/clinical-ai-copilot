from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from urllib import error, request

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


ModelTransport = Callable[
    [str, dict[str, str], dict[str, object], float],
    Mapping[str, object],
]


def _post_json(
    endpoint_url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    timeout_seconds: float,
) -> Mapping[str, object]:
    body = json.dumps(payload).encode("utf-8")
    outbound_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        **headers,
    }
    http_request = request.Request(endpoint_url, data=body, headers=outbound_headers, method="POST")
    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except (error.HTTPError, error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("CXR specialist model request failed.") from exc


class ModelBackedChestXRaySpecialistAdapter(SpecialistPort):
    """Calls a configurable model endpoint (e.g. a hosted MedGemma deployment).

    Falls back to StubChestXRaySpecialistAdapter whenever no endpoint is
    configured, or the call fails/returns a malformed response - a case never
    silently gets zero findings just because the real model is unreachable;
    it degrades to the same keyword-based path already covered by
    docs/06's requirement that a gap is surfaced, never fabricated as a
    confident answer. (The workflow's Degraded state still triggers if the
    fallback itself also returns nothing.)
    """

    modality = "chest_xray"

    def __init__(
        self,
        *,
        endpoint_url: str | None = None,
        api_key: str | None = None,
        model_version: str = "medgemma-cxr-v1",
        request_timeout_seconds: float = 8.0,
        source_agent: str = "cxr-specialist",
        transport: ModelTransport | None = None,
        unconfigured_fallback: SpecialistPort | None = None,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._api_key = api_key
        self._model_version = model_version
        self._request_timeout_seconds = request_timeout_seconds
        self._source_agent = source_agent
        self._transport = transport or _post_json
        self._fallback = unconfigured_fallback or StubChestXRaySpecialistAdapter()

    def analyze(self, artifact: ArtifactRecord, triage: TriageDecision) -> list[Finding]:
        if not self._endpoint_url:
            return self._fallback.analyze(artifact, triage)

        try:
            response = self._transport(
                self._endpoint_url,
                self._build_headers(),
                self._build_payload(artifact, triage),
                self._request_timeout_seconds,
            )
            findings = self._parse_findings(response)
        except (KeyError, TypeError, ValueError, RuntimeError):
            return self._fallback.analyze(artifact, triage)

        return findings or self._fallback.analyze(artifact, triage)

    def _build_headers(self) -> dict[str, str]:
        if not self._api_key:
            return {}
        return {"Authorization": f"Bearer {self._api_key}"}

    def _build_payload(self, artifact: ArtifactRecord, triage: TriageDecision) -> dict[str, object]:
        return {
            "model": self._model_version,
            "modality": triage.modality,
            "region": triage.region,
            "urgency": triage.urgency.value,
            "artifact": {
                "mime_type": artifact.mime_type,
                "report_text": artifact.de_identified_text,
                "artifact_uri": artifact.artifact_uri,
            },
        }

    def _parse_findings(self, response: Mapping[str, object]) -> list[Finding]:
        raw_findings = response.get("findings")
        if not isinstance(raw_findings, list):
            raise ValueError("Model response did not include a findings list.")

        findings: list[Finding] = []
        for raw_finding in raw_findings:
            if not isinstance(raw_finding, Mapping):
                raise TypeError("Model finding payload must be an object.")

            probability = float(raw_finding["probability"])
            if probability < 0.0 or probability > 1.0:
                raise ValueError("Finding probability must be between 0 and 1.")

            findings.append(
                Finding(
                    claim=str(raw_finding["claim"]).strip(),
                    locus=str(raw_finding["locus"]).strip(),
                    probability=probability,
                    source_agent=str(raw_finding.get("source_agent") or self._source_agent),
                    model_version=str(raw_finding.get("model_version") or response.get("model_version") or self._model_version),
                    saliency_ref=self._coerce_saliency_ref(raw_finding.get("saliency_ref")),
                )
            )
        return findings

    @staticmethod
    def _coerce_saliency_ref(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


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

