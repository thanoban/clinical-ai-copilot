from __future__ import annotations

from datetime import datetime, timezone
import os
import uuid

import psycopg2
import pytest

from aegis_dx.domain import (
    ArtifactRecord,
    AuditEvent,
    CaseLifecycleEvent,
    CaseRecord,
    CaseStatus,
)
from aegis_dx.postgres_store import PostgresCaseStore


DATABASE_URL = os.getenv(
    "AEGIS_DX_TEST_DATABASE_URL",
    "postgresql://aegis_dx:aegis_dx@localhost:5432/aegis_dx",
)


def _postgres_available() -> bool:
    try:
        connection = psycopg2.connect(DATABASE_URL, connect_timeout=2)
        connection.close()
        return True
    except psycopg2.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_available(),
    reason="No reachable Postgres at AEGIS_DX_TEST_DATABASE_URL (start it with `docker compose up -d postgres`).",
)


def _make_case(tenant_id: str = "tenant-a") -> CaseRecord:
    case_id = str(uuid.uuid4())
    return CaseRecord(
        case_id=case_id,
        trace_id=case_id,
        tenant_id=tenant_id,
        status=CaseStatus.RECEIVED,
        artifact=ArtifactRecord(mime_type="application/dicom", de_identified=True),
    )


@pytest.fixture
def store() -> PostgresCaseStore:
    return PostgresCaseStore(DATABASE_URL)


def test_save_and_get_case_round_trips(store: PostgresCaseStore) -> None:
    case = _make_case()
    store.save_case(case)

    fetched = store.get_case(case.case_id)

    assert fetched is not None
    assert fetched.case_id == case.case_id
    assert fetched.tenant_id == case.tenant_id
    assert fetched.status == CaseStatus.RECEIVED


def test_save_case_upserts_on_conflict(store: PostgresCaseStore) -> None:
    case = _make_case()
    store.save_case(case)

    case.status = CaseStatus.TRIAGED
    case.region = "thorax"
    store.save_case(case)

    fetched = store.get_case(case.case_id)
    assert fetched is not None
    assert fetched.status == CaseStatus.TRIAGED
    assert fetched.region == "thorax"


def test_list_cases_for_tenant_is_isolated_by_tenant(store: PostgresCaseStore) -> None:
    tenant_a_case = _make_case(tenant_id="tenant-a")
    tenant_b_case = _make_case(tenant_id="tenant-b")
    store.save_case(tenant_a_case)
    store.save_case(tenant_b_case)

    tenant_a_cases = store.list_cases_for_tenant("tenant-a")

    assert any(case.case_id == tenant_a_case.case_id for case in tenant_a_cases)
    assert all(case.case_id != tenant_b_case.case_id for case in tenant_a_cases)


def test_idempotency_key_resolves_to_original_case(store: PostgresCaseStore) -> None:
    case = _make_case()
    store.save_case(case)
    store.register_idempotency_key("tenant-a", "idem-key-1", case.case_id, datetime.now(timezone.utc).isoformat())

    resolved = store.get_case_by_idempotency_key("tenant-a", "idem-key-1")

    assert resolved is not None
    assert resolved.case_id == case.case_id


def test_list_pending_case_ids_excludes_terminal_statuses(store: PostgresCaseStore) -> None:
    pending_case = _make_case()
    pending_case.status = CaseStatus.ANALYZING
    store.save_case(pending_case)

    closed_case = _make_case()
    closed_case.status = CaseStatus.CLOSED
    store.save_case(closed_case)

    pending_ids = store.list_pending_case_ids()

    assert pending_case.case_id in pending_ids
    assert closed_case.case_id not in pending_ids


def test_audit_log_hash_chains_successive_entries(store: PostgresCaseStore) -> None:
    case = _make_case()
    store.save_case(case)

    first = store.append_audit_event(
        AuditEvent(
            case_id=case.case_id,
            tenant_id=case.tenant_id,
            event_type="case.submitted",
            actor_id="clinician-1",
        )
    )
    second = store.append_audit_event(
        AuditEvent(
            case_id=case.case_id,
            tenant_id=case.tenant_id,
            event_type="case.viewed",
            actor_id="clinician-1",
        )
    )

    assert first.previous_hash is None
    assert first.entry_hash
    assert second.previous_hash == first.entry_hash
    assert second.entry_hash != first.entry_hash

    events = store.list_audit_events(case.case_id, case.tenant_id)
    assert [event.event_type for event in events] == ["case.submitted", "case.viewed"]


def test_case_events_round_trip_with_schema_version(store: PostgresCaseStore) -> None:
    case = _make_case()
    store.save_case(case)

    store.append_case_event(
        CaseLifecycleEvent(
            case_id=case.case_id,
            tenant_id=case.tenant_id,
            event_type="workflow.triaged",
            schema_version="1.0.0",
            payload={"status": "Triaged"},
        )
    )

    events = store.list_case_events(case.case_id, case.tenant_id)
    assert len(events) == 1
    assert events[0].event_type == "workflow.triaged"
    assert events[0].payload["status"] == "Triaged"
