from __future__ import annotations

import time

from fastapi.testclient import TestClient

from aegis_dx.api.app import create_app
from aegis_dx.config import Settings


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


def create_client(tmp_path) -> TestClient:
    settings = Settings(
        app_name="Aegis-Dx Test API",
        database_path=tmp_path / "aegis_dx_test.db",
        worker_poll_interval_seconds=0.01,
    )
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
        assert "[redacted-id]" in case["artifact"]["de_identified_text"]
        assert "[redacted-email]" in case["artifact"]["de_identified_text"]
        assert case["report"]["disclaimer"].startswith("Research prototype only")
        assert "with retrieved evidence support" in case["report"]["summary"]
        assert any(link.startswith("guideline://") for link in case["report"]["evidence_links"])

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

        events_response = client.get(
            f"/v1/cases/{case_id}/events",
            headers=CLINICIAN_HEADERS,
        )
        assert events_response.status_code == 200
        degraded_event = next(
            event for event in events_response.json() if event["event_type"] == "workflow.degraded"
        )
        assert degraded_event["payload"]["modality"] == "ecg"


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
        triaged = next(item for item in payload if item["event_type"] == "workflow.triaged")
        assert "modality" in triaged["required_payload_fields"]
