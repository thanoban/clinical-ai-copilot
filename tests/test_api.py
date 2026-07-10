from __future__ import annotations

import time

from fastapi.testclient import TestClient
import pytest

from aegis_dx.api.app import create_app
from aegis_dx.config import Settings
import aegis_dx.specialists as specialists_module
import aegis_dx.trust as trust_module


CLINICIAN_HEADERS = {
    "X-Actor-Id": "clinician-1",
    "X-Actor-Role": "clinician",
    "X-Tenant-Id": "tenant-a",
}
AUDITOR_HEADERS = {
    "X-Actor-Id": "auditor-1",
    "X-Actor-Role": "auditor",
    "X-Tenant-Id": "tenant-a",
}
REVIEWER_HEADERS = {
    "X-Actor-Id": "reviewer-1",
    "X-Actor-Role": "reviewer",
    "X-Tenant-Id": "tenant-a",
}
OTHER_TENANT_HEADERS = {
    "X-Actor-Id": "clinician-2",
    "X-Actor-Role": "clinician",
    "X-Tenant-Id": "tenant-b",
}


def create_client(tmp_path, **overrides) -> TestClient:
    settings_kwargs: dict[str, object] = {
        "app_name": "Aegis-Dx Test API",
        "database_path": tmp_path / "aegis_dx_test.db",
        "database_url": None,
        "redis_url": None,
        "worker_poll_interval_seconds": 0.01,
        "cxr_specialist_backend": "http",
        "cxr_specialist_endpoint_url": None,
        "cxr_specialist_api_key": None,
        "cxr_specialist_model_version": "medgemma-cxr-v1",
        "cxr_specialist_timeout_seconds": 0.5,
        "verifier_endpoint_url": None,
        "verifier_api_key": None,
        "verifier_model_version": "verifier-critic-v1",
        "verifier_timeout_seconds": 0.5,
    }
    settings_kwargs.update(overrides)
    settings = Settings(**settings_kwargs)
    return TestClient(create_app(settings))


def wait_for_review(client: TestClient, case_id: str) -> dict:
    deadline = time.time() + 3
    while time.time() < deadline:
        response = client.get(f"/v1/cases/{case_id}", headers=CLINICIAN_HEADERS)
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] == "AwaitingReview":
            return payload
        time.sleep(0.05)
    raise AssertionError(f"Case {case_id} never reached AwaitingReview.")


def test_case_submission_runs_through_async_workflow(tmp_path) -> None:
    with create_client(tmp_path) as client:
        response = client.post(
            "/v1/cases",
            headers={**CLINICIAN_HEADERS, "X-Correlation-Id": "submit-correlation-id"},
            json={
                "site_id": "site-a",
                "artifact": {
                    "mime_type": "application/dicom",
                    "report_text": "Patient 123456 has possible pneumonia. Contact foo@example.com.",
                    "source_system": "unit-test",
                },
            },
        )

        assert response.status_code == 202
        accepted = response.json()
        assert response.headers["X-Correlation-Id"] == accepted["trace_id"]

        case = wait_for_review(client, accepted["case_id"])
        assert case["modality"] == "chest_xray"
        assert case["artifact"]["de_identified"] is True
        assert case["evidence"]
        assert case["evidence"][0]["source_type"] in {"guideline", "reference-case"}
        assert case["verification"]
        assert case["verification"][0]["requires_escalation"] is False
        assert "[redacted-id]" in case["artifact"]["de_identified_text"]
        assert "[redacted-email]" in case["artifact"]["de_identified_text"]
        assert case["report"]["disclaimer"].startswith("Research prototype only")
        assert "with retrieved evidence support" in case["report"]["summary"]
        assert any(link.startswith("guideline://") for link in case["report"]["evidence_links"])
        assert case["escalation"]["required"] is False

        audit_response = client.get(
            f"/v1/cases/{accepted['case_id']}/audit",
            headers=AUDITOR_HEADERS,
        )
        assert audit_response.status_code == 200
        assert audit_response.headers["X-Correlation-Id"] == accepted["trace_id"]
        submitted_event = audit_response.json()[0]
        assert submitted_event["payload"]["trace_id"] == accepted["trace_id"]
        assert submitted_event["payload"]["request_correlation_id"] == "submit-correlation-id"

        lifecycle_response = client.get(
            f"/v1/cases/{accepted['case_id']}/events",
            headers=CLINICIAN_HEADERS,
        )
        assert lifecycle_response.status_code == 200
        lifecycle_events = lifecycle_response.json()
        assert lifecycle_events[0]["schema_version"] == "1.0.0"
        assert lifecycle_events[0]["event_type"] == "case.submitted"
        assert any(event["event_type"] == "workflow.retrieved" for event in lifecycle_events)


def test_review_and_audit_log_are_recorded(tmp_path) -> None:
    with create_client(tmp_path) as client:
        create_response = client.post(
            "/v1/cases",
            headers=CLINICIAN_HEADERS,
            json={
                "artifact": {
                    "mime_type": "application/dicom",
                    "report_text": "Urgent follow-up. Small effusion noted.",
                }
            },
        )
        case_id = create_response.json()["case_id"]
        wait_for_review(client, case_id)

        review_response = client.post(
            f"/v1/cases/{case_id}/review",
            headers=REVIEWER_HEADERS,
            json={
                "action": "edit",
                "edited_summary": "Reviewer adjusted the draft summary before confirmation.",
                "note": "Escalated urgent cases should be reviewed first.",
            },
        )

        assert review_response.status_code == 200
        assert review_response.json()["status"] == "Edited"
        assert review_response.headers["X-Correlation-Id"] == case_id
        assert (
            review_response.json()["report"]["summary"]
            == "Reviewer adjusted the draft summary before confirmation."
        )

        audit_response = client.get(
            f"/v1/cases/{case_id}/audit",
            headers=AUDITOR_HEADERS,
        )
        assert audit_response.status_code == 200
        audit_events = audit_response.json()
        assert any(event["event_type"] == "workflow.triaged" for event in audit_events)
        assert audit_events[-1]["event_type"] == "case.review.edit"
        assert any(
            event["payload"].get("specialist_modality") == "chest_xray"
            for event in audit_events
            if event["event_type"] == "workflow.analysis_completed"
        )
        assert any(
            event["payload"].get("evidence_count", 0) >= 1
            for event in audit_events
            if event["event_type"] == "workflow.retrieved"
        )
        assert any(
            event["payload"].get("escalated_findings") == 0
            for event in audit_events
            if event["event_type"] == "workflow.verification_completed"
        )

        previous_hash = None
        for event in audit_events:
            assert event["previous_hash"] == previous_hash
            previous_hash = event["entry_hash"]


def test_idempotency_key_replays_the_original_case(tmp_path) -> None:
    with create_client(tmp_path) as client:
        headers = {**CLINICIAN_HEADERS, "Idempotency-Key": "same-request-1"}
        first_response = client.post(
            "/v1/cases",
            headers=headers,
            json={"artifact": {"mime_type": "application/dicom", "report_text": "possible pneumonia"}},
        )
        second_response = client.post(
            "/v1/cases",
            headers=headers,
            json={"artifact": {"mime_type": "application/dicom", "report_text": "possible pneumonia"}},
        )

        assert first_response.status_code == 202
        assert second_response.status_code == 202
        first_payload = first_response.json()
        second_payload = second_response.json()
        assert first_payload["case_id"] == second_payload["case_id"]
        assert first_payload["trace_id"] == second_payload["trace_id"]
        assert first_payload["idempotency_replayed"] is False
        assert second_payload["idempotency_replayed"] is True

        events_response = client.get(
            f"/v1/cases/{first_payload['case_id']}/events",
            headers=CLINICIAN_HEADERS,
        )
        assert events_response.status_code == 200
        submitted_events = [
            event for event in events_response.json() if event["event_type"] == "case.submitted"
        ]
        assert len(submitted_events) == 1


def test_tenant_isolation_and_role_guards(tmp_path) -> None:
    with create_client(tmp_path) as client:
        create_response = client.post(
            "/v1/cases",
            headers=CLINICIAN_HEADERS,
            json={"artifact": {"mime_type": "application/dicom", "report_text": "normal cxr"}},
        )
        case_id = create_response.json()["case_id"]
        wait_for_review(client, case_id)

        tenant_response = client.get(f"/v1/cases/{case_id}", headers=OTHER_TENANT_HEADERS)
        assert tenant_response.status_code == 403

        audit_response = client.get(
            f"/v1/cases/{case_id}/audit",
            headers=CLINICIAN_HEADERS,
        )
        assert audit_response.status_code == 403

        events_response = client.get(
            f"/v1/cases/{case_id}/events",
            headers=OTHER_TENANT_HEADERS,
        )
        assert events_response.status_code == 403


def test_unsupported_modality_degrades_transparently(tmp_path) -> None:
    with create_client(tmp_path) as client:
        create_response = client.post(
            "/v1/cases",
            headers=CLINICIAN_HEADERS,
            json={
                "artifact": {
                    "mime_type": "application/ecg",
                    "report_text": "Stat ECG review requested.",
                }
            },
        )
        case_id = create_response.json()["case_id"]
        case = wait_for_review(client, case_id)

        assert case["modality"] == "ecg"
        assert case["escalation"]["required"] is True
        assert "No specialist is registered for modality 'ecg'." == case["escalation"]["reason"]
        assert case["findings"] == []
        assert case["report"] is not None
        assert "No specialist is registered for modality 'ecg'." in case["report"]["summary"]
        assert case["report"]["disclaimer"]

        events_response = client.get(
            f"/v1/cases/{case_id}/events",
            headers=CLINICIAN_HEADERS,
        )
        assert events_response.status_code == 200
        degraded_event = next(
            event for event in events_response.json() if event["event_type"] == "workflow.degraded"
        )
        assert degraded_event["payload"]["modality"] == "ecg"
        assert degraded_event["payload"]["report_ready"] is True


def test_low_confidence_case_is_escalated_by_guardrail(tmp_path) -> None:
    with create_client(tmp_path) as client:
        create_response = client.post(
            "/v1/cases",
            headers=CLINICIAN_HEADERS,
            json={
                "artifact": {
                    "mime_type": "application/dicom",
                    "report_text": "General chest xray follow-up with no focal issue described.",
                }
            },
        )
        case_id = create_response.json()["case_id"]
        case = wait_for_review(client, case_id)

        assert case["verification"][0]["requires_escalation"] is True
        assert "low_confidence_finding" in case["verification"][0]["critic_flags"]
        assert case["escalation"]["required"] is True
        assert case["escalation"]["reason"] == "Low-confidence findings require human escalation."

        events_response = client.get(
            f"/v1/cases/{case_id}/events",
            headers=CLINICIAN_HEADERS,
        )
        assert events_response.status_code == 200
        calibrated_event = next(
            event for event in events_response.json() if event["event_type"] == "workflow.calibrated"
        )
        assert calibrated_event["payload"]["required"] is True
        assert calibrated_event["payload"]["reason"] == "Low-confidence findings require human escalation."


def test_healthcheck_returns_generated_correlation_id(tmp_path) -> None:
    with create_client(tmp_path) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.headers["X-Correlation-Id"]


def test_event_schema_registry_is_exposed(tmp_path) -> None:
    with create_client(tmp_path) as client:
        response = client.get("/v1/event-schemas", headers=AUDITOR_HEADERS)
        assert response.status_code == 200
        payload = response.json()
        assert any(item["event_type"] == "workflow.triaged" for item in payload)
        assert any(item["event_type"] == "workflow.retrieved" for item in payload)
        assert any(item["event_type"] == "workflow.verification_completed" for item in payload)
        triaged = next(item for item in payload if item["event_type"] == "workflow.triaged")
        assert "modality" in triaged["required_payload_fields"]


def test_case_submission_uses_model_backed_cxr_specialist_when_configured(
    tmp_path,
    monkeypatch,
) -> None:
    captured_payload: dict[str, object] = {}

    def fake_post_json(endpoint_url, headers, payload, timeout_seconds):
        captured_payload.update(payload)
        return {
            "model_version": "medgemma-cxr-2026-07-10",
            "findings": [
                {
                    "claim": "Right lower lobe airspace opacity concerning for pneumonia.",
                    "locus": "right-lower-lung-zone",
                    "probability": 0.93,
                    "source_agent": "cxr-specialist",
                    "saliency_ref": "overlay://right-lower-lung-zone",
                }
            ],
        }

    monkeypatch.setattr(specialists_module, "_post_json", fake_post_json)

    with create_client(
        tmp_path,
        cxr_specialist_endpoint_url="https://models.example.test/cxr",
        cxr_specialist_api_key="secret-key",
    ) as client:
        create_response = client.post(
            "/v1/cases",
            headers=CLINICIAN_HEADERS,
            json={"artifact": {"mime_type": "application/dicom", "report_text": "Possible pneumonia."}},
        )
        case = wait_for_review(client, create_response.json()["case_id"])

        assert captured_payload["modality"] == "chest_xray"
        assert case["findings"][0]["claim"] == "Right lower lobe airspace opacity concerning for pneumonia."
        assert case["findings"][0]["model_version"] == "medgemma-cxr-2026-07-10"


def test_configured_cxr_specialist_failure_degrades_to_review_queue(
    tmp_path,
    monkeypatch,
) -> None:
    def failing_post_json(endpoint_url, headers, payload, timeout_seconds):
        raise RuntimeError("upstream timeout")

    monkeypatch.setattr(specialists_module, "_post_json", failing_post_json)

    with create_client(
        tmp_path,
        cxr_specialist_endpoint_url="https://models.example.test/cxr",
    ) as client:
        create_response = client.post(
            "/v1/cases",
            headers=CLINICIAN_HEADERS,
            json={"artifact": {"mime_type": "application/dicom", "report_text": "Possible pneumonia."}},
        )
        case = wait_for_review(client, create_response.json()["case_id"])

        # The transport failed, so the adapter falls back to its keyword-based
        # path rather than degrading the whole case - a model outage doesn't
        # mean zero findings when a safe fallback exists.
        assert case["modality"] == "chest_xray"
        assert case["findings"]
        assert case["findings"][0]["model_version"] == "stub-medgemma-cxr-v1"


def test_case_submission_uses_model_backed_verifier_when_configured(
    tmp_path,
    monkeypatch,
) -> None:
    captured_payload: dict[str, object] = {}

    def fake_post_verification_json(endpoint_url, headers, payload, timeout_seconds):
        captured_payload.update(payload)
        return {
            "results": [
                {
                    "claim": payload["findings"][0]["claim"],
                    "agreement_score": 0.95,
                    "critic_flags": ["independent_model_confirmation"],
                    "requires_escalation": False,
                }
            ]
        }

    monkeypatch.setattr(trust_module, "_post_verification_json", fake_post_verification_json)

    with create_client(
        tmp_path,
        verifier_endpoint_url="https://critic.example.test/verify",
    ) as client:
        create_response = client.post(
            "/v1/cases",
            headers=CLINICIAN_HEADERS,
            json={"artifact": {"mime_type": "application/dicom", "report_text": "Possible pneumonia."}},
        )
        case = wait_for_review(client, create_response.json()["case_id"])

        assert captured_payload
        assert case["verification"][0]["agreement_score"] == 0.95
        assert "independent_model_confirmation" in case["verification"][0]["critic_flags"]


def test_app_refuses_to_start_with_identical_specialist_and_verifier_endpoints(tmp_path) -> None:
    with pytest.raises(ValueError, match="heterogeneous-verifier"):
        create_client(
            tmp_path,
            cxr_specialist_endpoint_url="https://same.example.test",
            verifier_endpoint_url="https://same.example.test",
        )
