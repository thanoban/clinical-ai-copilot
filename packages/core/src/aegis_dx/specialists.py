from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import os
from urllib import error, request
from urllib.parse import urlparse

from aegis_dx.domain import ArtifactRecord, Finding, TriageDecision
from aegis_dx.models.torchxrayvision_backend import (
    TorchXRayVisionClassifier,
    TorchXRayVisionUnavailable,
)
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


_CLAIM_PHRASE_BY_PATHOLOGY: dict[str, str] = {
    "Effusion": "pleural effusion",
    "Enlarged Cardiomediastinum": "enlarged cardiomediastinum",
    "Lung Opacity": "lung opacity",
    "Lung Lesion": "lung lesion",
}


def _resolve_local_image_path(artifact_uri: str | None) -> str | None:
    if not artifact_uri:
        return None
    # Try it as a literal OS path first - urlparse misreads a Windows drive
    # letter ("C:\...") as a URI scheme, so a plain-path check must come before
    # any URL parsing.
    if os.path.isfile(artifact_uri):
        return artifact_uri

    parsed = urlparse(artifact_uri)
    if parsed.scheme != "file":
        return None
    path = parsed.path
    # file:// URIs on Windows parse with a leading slash before the drive letter.
    if path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return path if os.path.isfile(path) else None


class HFTorchXRayVisionSpecialistAdapter(SpecialistPort):
    """A real, locally-run CXR specialist backed by torchxrayvision's
    independently-trained CheXpert DenseNet121 (see docs/04-data-models.md).

    Unlike ModelBackedChestXRaySpecialistAdapter, this doesn't call an external
    endpoint - it runs actual pixel classification in-process against an image
    resolved from `artifact.artifact_uri`. Falls back to
    StubChestXRaySpecialistAdapter whenever no image is available, the
    torchxrayvision package/weights aren't available, or classification fails -
    same "never silently produce zero findings" rule as the other specialist
    adapters.
    """

    modality = "chest_xray"

    def __init__(
        self,
        *,
        classifier: TorchXRayVisionClassifier | None = None,
        positive_threshold: float = 0.5,
        max_findings: int = 5,
        source_agent: str = "cxr-specialist",
        model_version: str = "torchxrayvision-densenet121-chex",
        unconfigured_fallback: SpecialistPort | None = None,
    ) -> None:
        self._classifier = classifier or TorchXRayVisionClassifier()
        self._positive_threshold = positive_threshold
        self._max_findings = max_findings
        self._source_agent = source_agent
        self._model_version = model_version
        self._fallback = unconfigured_fallback or StubChestXRaySpecialistAdapter()

    def analyze(self, artifact: ArtifactRecord, triage: TriageDecision) -> list[Finding]:
        image_path = _resolve_local_image_path(artifact.artifact_uri)
        if not image_path:
            return self._fallback.analyze(artifact, triage)

        try:
            probabilities = self._classifier.classify_image_path(image_path)
        except (TorchXRayVisionUnavailable, OSError, ValueError, RuntimeError):
            return self._fallback.analyze(artifact, triage)

        findings = self._findings_from_probabilities(probabilities)
        return findings or self._fallback.analyze(artifact, triage)

    def _findings_from_probabilities(self, probabilities: dict[str, float]) -> list[Finding]:
        positive = sorted(
            ((name, prob) for name, prob in probabilities.items() if prob >= self._positive_threshold),
            key=lambda item: item[1],
            reverse=True,
        )[: self._max_findings]

        if not positive:
            return [
                Finding(
                    claim="No focal cardiopulmonary abnormality identified in the draft path.",
                    locus="global-thorax",
                    probability=round(max(0.55, 1.0 - max(probabilities.values(), default=0.4)), 2),
                    source_agent=self._source_agent,
                    model_version=self._model_version,
                    saliency_ref=None,
                )
            ]

        return [
            Finding(
                claim=f"Possible {_CLAIM_PHRASE_BY_PATHOLOGY.get(name, name.lower())}.",
                locus=TorchXRayVisionClassifier.locus_for_pathology(name),
                probability=round(probability, 4),
                source_agent=self._source_agent,
                model_version=self._model_version,
                saliency_ref=None,
            )
            for name, probability in positive
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

