from __future__ import annotations

import pytest

from aegis_dx.domain import ArtifactRecord, Finding, TriageDecision, UrgencyLevel
from aegis_dx.specialists import ModelBackedChestXRaySpecialistAdapter
from aegis_dx.trust import ModelBackedVerificationAdapter, assert_heterogeneous_verifier


ARTIFACT = ArtifactRecord(
    mime_type="application/dicom",
    de_identified=True,
    de_identified_text="Possible pneumonia in the right lower lobe.",
)
TRIAGE = TriageDecision(modality="chest_xray", region="thorax", urgency=UrgencyLevel.ROUTINE)


def test_specialist_falls_back_to_stub_when_unconfigured() -> None:
    adapter = ModelBackedChestXRaySpecialistAdapter()

    findings = adapter.analyze(ARTIFACT, TRIAGE)

    assert findings
    assert findings[0].model_version == "stub-medgemma-cxr-v1"


def test_specialist_parses_a_well_formed_model_response() -> None:
    def fake_transport(endpoint_url, headers, payload, timeout_seconds):
        assert endpoint_url == "https://models.example.test/cxr"
        assert headers["Authorization"] == "Bearer secret-key"
        assert payload["modality"] == "chest_xray"
        return {
            "model_version": "medgemma-cxr-2026-07-10",
            "findings": [
                {
                    "claim": "Right lower lobe airspace opacity concerning for pneumonia.",
                    "locus": "right-lower-lung-zone",
                    "probability": 0.91,
                    "saliency_ref": "overlay://right-lower-lung-zone",
                }
            ],
        }

    adapter = ModelBackedChestXRaySpecialistAdapter(
        endpoint_url="https://models.example.test/cxr",
        api_key="secret-key",
        transport=fake_transport,
    )

    findings = adapter.analyze(ARTIFACT, TRIAGE)

    assert len(findings) == 1
    assert findings[0].claim == "Right lower lobe airspace opacity concerning for pneumonia."
    assert findings[0].probability == 0.91
    assert findings[0].model_version == "medgemma-cxr-2026-07-10"
    assert findings[0].source_agent == "cxr-specialist"


def test_specialist_falls_back_on_transport_failure() -> None:
    def failing_transport(endpoint_url, headers, payload, timeout_seconds):
        raise RuntimeError("upstream timeout")

    adapter = ModelBackedChestXRaySpecialistAdapter(
        endpoint_url="https://models.example.test/cxr",
        transport=failing_transport,
    )

    findings = adapter.analyze(ARTIFACT, TRIAGE)

    assert findings
    assert findings[0].model_version == "stub-medgemma-cxr-v1"


def test_specialist_falls_back_on_malformed_response() -> None:
    def malformed_transport(endpoint_url, headers, payload, timeout_seconds):
        return {"findings": [{"claim": "missing locus and probability"}]}

    adapter = ModelBackedChestXRaySpecialistAdapter(
        endpoint_url="https://models.example.test/cxr",
        transport=malformed_transport,
    )

    findings = adapter.analyze(ARTIFACT, TRIAGE)

    assert findings
    assert findings[0].model_version == "stub-medgemma-cxr-v1"


def test_specialist_falls_back_on_empty_findings_from_a_working_call() -> None:
    def empty_transport(endpoint_url, headers, payload, timeout_seconds):
        return {"findings": []}

    adapter = ModelBackedChestXRaySpecialistAdapter(
        endpoint_url="https://models.example.test/cxr",
        transport=empty_transport,
    )

    findings = adapter.analyze(ARTIFACT, TRIAGE)

    assert findings
    assert findings[0].model_version == "stub-medgemma-cxr-v1"


def _sample_finding() -> Finding:
    return Finding(
        claim="Possible right lower lobe pneumonia.",
        locus="right-lower-lung-zone",
        probability=0.8,
        source_agent="cxr-specialist",
        model_version="medgemma-cxr-v1",
    )


def test_verifier_falls_back_to_stub_when_unconfigured() -> None:
    adapter = ModelBackedVerificationAdapter()

    results = adapter.verify([_sample_finding()], [], TRIAGE)

    assert results
    assert results[0].claim == "Possible right lower lobe pneumonia."


def test_verifier_parses_a_well_formed_model_response() -> None:
    def fake_transport(endpoint_url, headers, payload, timeout_seconds):
        assert endpoint_url == "https://critic.example.test/verify"
        assert payload["findings"][0]["claim"] == "Possible right lower lobe pneumonia."
        return {
            "results": [
                {
                    "claim": "Possible right lower lobe pneumonia.",
                    "agreement_score": 0.87,
                    "critic_flags": ["independent_confirmation"],
                    "requires_escalation": False,
                }
            ]
        }

    adapter = ModelBackedVerificationAdapter(
        endpoint_url="https://critic.example.test/verify",
        transport=fake_transport,
    )

    results = adapter.verify([_sample_finding()], [], TRIAGE)

    assert len(results) == 1
    assert results[0].agreement_score == 0.87
    assert results[0].critic_flags == ["independent_confirmation"]
    assert results[0].requires_escalation is False


def test_verifier_falls_back_on_transport_failure() -> None:
    def failing_transport(endpoint_url, headers, payload, timeout_seconds):
        raise RuntimeError("upstream timeout")

    adapter = ModelBackedVerificationAdapter(
        endpoint_url="https://critic.example.test/verify",
        transport=failing_transport,
    )

    results = adapter.verify([_sample_finding()], [], TRIAGE)

    assert results


def test_verifier_skips_the_call_entirely_when_there_are_no_findings() -> None:
    calls: list[object] = []

    def tracking_transport(endpoint_url, headers, payload, timeout_seconds):
        calls.append(payload)
        return {"results": []}

    adapter = ModelBackedVerificationAdapter(
        endpoint_url="https://critic.example.test/verify",
        transport=tracking_transport,
    )

    results = adapter.verify([], [], TRIAGE)

    assert results == []
    assert calls == []


def test_assert_heterogeneous_verifier_allows_distinct_endpoints() -> None:
    assert_heterogeneous_verifier("https://specialist.example.test", "https://critic.example.test")
    assert_heterogeneous_verifier(None, None)
    assert_heterogeneous_verifier("https://specialist.example.test", None)


def test_assert_heterogeneous_verifier_rejects_identical_endpoints() -> None:
    with pytest.raises(ValueError, match="heterogeneous-verifier"):
        assert_heterogeneous_verifier("https://same.example.test", "https://same.example.test")
