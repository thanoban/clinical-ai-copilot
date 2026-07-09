from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from urllib import error, request

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


VerifierTransport = Callable[
    [str, dict[str, str], dict[str, object], float],
    Mapping[str, object],
]


def _post_verification_json(
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
        raise RuntimeError("Verifier model request failed.") from exc


class ModelBackedVerificationAdapter(VerificationPort):
    """Calls a configurable, independent critic model/provider.

    Per D6 (docs/07): the verifier must be a genuinely different model from the
    specialist, not the same backbone asked to grade its own work. This adapter
    doesn't enforce that itself - see `assert_heterogeneous_verifier` below,
    which the composition root calls at startup - but it exists as a distinct
    class/endpoint so the two are never accidentally the same call path.
    Falls back to StubVerificationAdapter whenever no endpoint is configured or
    the call fails, so verification never silently no-ops.
    """

    def __init__(
        self,
        *,
        endpoint_url: str | None = None,
        api_key: str | None = None,
        model_version: str = "verifier-critic-v1",
        request_timeout_seconds: float = 8.0,
        transport: VerifierTransport | None = None,
        unconfigured_fallback: VerificationPort | None = None,
    ) -> None:
        self.endpoint_url = endpoint_url
        self._api_key = api_key
        self._model_version = model_version
        self._request_timeout_seconds = request_timeout_seconds
        self._transport = transport or _post_verification_json
        self._fallback = unconfigured_fallback or StubVerificationAdapter()

    def verify(
        self,
        findings: list[Finding],
        evidence: list[EvidenceSnippet],
        triage: TriageDecision,
    ) -> list[VerificationResult]:
        if not self.endpoint_url or not findings:
            return self._fallback.verify(findings, evidence, triage)

        try:
            response = self._transport(
                self.endpoint_url,
                self._build_headers(),
                self._build_payload(findings, evidence, triage),
                self._request_timeout_seconds,
            )
            results = self._parse_results(response)
        except (KeyError, TypeError, ValueError, RuntimeError):
            return self._fallback.verify(findings, evidence, triage)

        return results or self._fallback.verify(findings, evidence, triage)

    def _build_headers(self) -> dict[str, str]:
        if not self._api_key:
            return {}
        return {"Authorization": f"Bearer {self._api_key}"}

    def _build_payload(
        self,
        findings: list[Finding],
        evidence: list[EvidenceSnippet],
        triage: TriageDecision,
    ) -> dict[str, object]:
        return {
            "model": self._model_version,
            "modality": triage.modality,
            "urgency": triage.urgency.value,
            "findings": [
                {"claim": finding.claim, "locus": finding.locus, "probability": finding.probability}
                for finding in findings
            ],
            "evidence": [
                {"title": snippet.title, "snippet": snippet.snippet} for snippet in evidence
            ],
        }

    def _parse_results(self, response: Mapping[str, object]) -> list[VerificationResult]:
        raw_results = response.get("results")
        if not isinstance(raw_results, list):
            raise ValueError("Verifier response did not include a results list.")

        results: list[VerificationResult] = []
        for raw_result in raw_results:
            if not isinstance(raw_result, Mapping):
                raise TypeError("Verifier result payload must be an object.")

            agreement_score = float(raw_result["agreement_score"])
            if agreement_score < 0.0 or agreement_score > 1.0:
                raise ValueError("agreement_score must be between 0 and 1.")

            raw_flags = raw_result.get("critic_flags") or []
            if not isinstance(raw_flags, list):
                raise TypeError("critic_flags must be a list.")

            results.append(
                VerificationResult(
                    claim=str(raw_result["claim"]).strip(),
                    agreement_score=agreement_score,
                    critic_flags=[str(flag) for flag in raw_flags],
                    requires_escalation=bool(raw_result.get("requires_escalation", False)),
                )
            )
        return results


def assert_heterogeneous_verifier(specialist_endpoint_url: str | None, verifier_endpoint_url: str | None) -> None:
    """Fail fast at startup rather than silently let a model verify itself.

    Per D6: the verifier must be a genuinely different model/provider from the
    specialist. An identical, non-empty endpoint URL for both is a
    configuration error, not a valid deployment - refuse to start rather than
    produce verification that looks independent but isn't.
    """

    if specialist_endpoint_url and verifier_endpoint_url and specialist_endpoint_url == verifier_endpoint_url:
        raise ValueError(
            "Specialist and verifier are configured with the identical model endpoint. "
            "The heterogeneous-verifier rule (D6) requires a genuinely different model/provider "
            "for verification - point AEGIS_DX_VERIFIER_ENDPOINT_URL at a different deployment."
        )


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
