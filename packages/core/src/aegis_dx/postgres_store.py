from __future__ import annotations

from hashlib import sha256
import json
import threading

import psycopg2
import psycopg2.extras
import psycopg2.pool

from aegis_dx.domain import AuditEvent, CaseLifecycleEvent, CaseRecord, CaseStatus


class PostgresCaseStore:
    """Production case/audit store backed by Postgres.

    Mirrors SQLiteCaseStore's method surface exactly so WorkflowRuntime can use
    either interchangeably behind the same store contract - only config.py
    decides which one gets constructed.
    """

    def __init__(self, database_url: str, *, minconn: int = 1, maxconn: int = 10) -> None:
        self._pool = psycopg2.pool.ThreadedConnectionPool(minconn, maxconn, dsn=database_url)
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self):
        return self._pool.getconn()

    def _release(self, connection) -> None:
        self._pool.putconn(connection)

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cases (
                        case_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_cases_tenant_updated
                        ON cases (tenant_id, updated_at DESC);

                    CREATE TABLE IF NOT EXISTS audit_log (
                        sequence BIGSERIAL PRIMARY KEY,
                        case_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        actor_role TEXT,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        previous_hash TEXT,
                        entry_hash TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_audit_log_case
                        ON audit_log (case_id, tenant_id, sequence ASC);

                    CREATE TABLE IF NOT EXISTS case_events (
                        sequence BIGSERIAL PRIMARY KEY,
                        case_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        schema_version TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_case_events_case
                        ON case_events (case_id, tenant_id, sequence ASC);

                    CREATE TABLE IF NOT EXISTS idempotency_keys (
                        tenant_id TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        case_id TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        PRIMARY KEY (tenant_id, idempotency_key)
                    );
                    """
                )
            connection.commit()
        finally:
            self._release(connection)

    def save_case(self, case: CaseRecord) -> CaseRecord:
        payload = json.dumps(case.model_dump(mode="json"), sort_keys=True)
        connection = self._connect()
        try:
            with self._lock, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO cases (case_id, tenant_id, status, payload, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (case_id) DO UPDATE SET
                        tenant_id = EXCLUDED.tenant_id,
                        status = EXCLUDED.status,
                        payload = EXCLUDED.payload,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (case.case_id, case.tenant_id, case.status.value, payload, case.updated_at),
                )
            connection.commit()
        finally:
            self._release(connection)
        return case

    def get_case(self, case_id: str) -> CaseRecord | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT payload FROM cases WHERE case_id = %s", (case_id,))
                row = cursor.fetchone()
        finally:
            self._release(connection)
        if row is None:
            return None
        return CaseRecord.model_validate(row[0])

    def get_case_by_idempotency_key(self, tenant_id: str, idempotency_key: str) -> CaseRecord | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT c.payload
                    FROM idempotency_keys k
                    JOIN cases c ON c.case_id = k.case_id
                    WHERE k.tenant_id = %s AND k.idempotency_key = %s
                    """,
                    (tenant_id, idempotency_key),
                )
                row = cursor.fetchone()
        finally:
            self._release(connection)
        if row is None:
            return None
        return CaseRecord.model_validate(row[0])

    def list_cases_for_tenant(self, tenant_id: str) -> list[CaseRecord]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT payload
                    FROM cases
                    WHERE tenant_id = %s
                    ORDER BY updated_at DESC
                    """,
                    (tenant_id,),
                )
                rows = cursor.fetchall()
        finally:
            self._release(connection)
        return [CaseRecord.model_validate(row[0]) for row in rows]

    def list_pending_case_ids(self) -> list[str]:
        terminal_statuses = (
            CaseStatus.CONFIRMED.value,
            CaseStatus.EDITED.value,
            CaseStatus.REJECTED.value,
            CaseStatus.CLOSED.value,
            CaseStatus.AWAITING_REVIEW.value,
        )
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT case_id
                    FROM cases
                    WHERE status NOT IN %s
                    ORDER BY updated_at ASC
                    """,
                    (terminal_statuses,),
                )
                rows = cursor.fetchall()
        finally:
            self._release(connection)
        return [row[0] for row in rows]

    def register_idempotency_key(
        self,
        tenant_id: str,
        idempotency_key: str,
        case_id: str,
        created_at: str,
    ) -> None:
        connection = self._connect()
        try:
            with self._lock, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO idempotency_keys (tenant_id, idempotency_key, case_id, created_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                    """,
                    (tenant_id, idempotency_key, case_id, created_at),
                )
            connection.commit()
        finally:
            self._release(connection)

    def append_audit_event(self, event: AuditEvent) -> AuditEvent:
        connection = self._connect()
        try:
            with self._lock, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT entry_hash
                    FROM audit_log
                    WHERE case_id = %s
                    ORDER BY sequence DESC
                    LIMIT 1
                    """,
                    (event.case_id,),
                )
                previous_row = cursor.fetchone()
                previous_hash = previous_row[0] if previous_row else None
                serialized_payload = json.dumps(event.payload, sort_keys=True)
                entry_hash = sha256(
                    "|".join(
                        [
                            previous_hash or "",
                            event.case_id,
                            event.tenant_id,
                            event.event_type,
                            event.actor_id,
                            event.created_at.isoformat(),
                            serialized_payload,
                        ]
                    ).encode("utf-8")
                ).hexdigest()
                cursor.execute(
                    """
                    INSERT INTO audit_log (
                        case_id, tenant_id, event_type, actor_id, actor_role,
                        payload, created_at, previous_hash, entry_hash
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING sequence
                    """,
                    (
                        event.case_id,
                        event.tenant_id,
                        event.event_type,
                        event.actor_id,
                        event.actor_role,
                        serialized_payload,
                        event.created_at,
                        previous_hash,
                        entry_hash,
                    ),
                )
                sequence = cursor.fetchone()[0]
            connection.commit()
        finally:
            self._release(connection)

        return event.model_copy(
            update={
                "sequence": sequence,
                "previous_hash": previous_hash,
                "entry_hash": entry_hash,
            }
        )

    def list_audit_events(self, case_id: str, tenant_id: str) -> list[AuditEvent]:
        connection = self._connect()
        try:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT sequence, case_id, tenant_id, event_type, actor_id, actor_role,
                           payload, created_at, previous_hash, entry_hash
                    FROM audit_log
                    WHERE case_id = %s AND tenant_id = %s
                    ORDER BY sequence ASC
                    """,
                    (case_id, tenant_id),
                )
                rows = cursor.fetchall()
        finally:
            self._release(connection)
        return [AuditEvent.model_validate(dict(row)) for row in rows]

    def append_case_event(self, event: CaseLifecycleEvent) -> CaseLifecycleEvent:
        serialized_payload = json.dumps(event.payload, sort_keys=True)
        connection = self._connect()
        try:
            with self._lock, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO case_events (
                        case_id, tenant_id, event_type, schema_version, payload, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING sequence
                    """,
                    (
                        event.case_id,
                        event.tenant_id,
                        event.event_type,
                        event.schema_version,
                        serialized_payload,
                        event.created_at,
                    ),
                )
                sequence = cursor.fetchone()[0]
            connection.commit()
        finally:
            self._release(connection)
        return event.model_copy(update={"sequence": sequence})

    def list_case_events(self, case_id: str, tenant_id: str) -> list[CaseLifecycleEvent]:
        connection = self._connect()
        try:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT sequence, case_id, tenant_id, event_type, schema_version, payload, created_at
                    FROM case_events
                    WHERE case_id = %s AND tenant_id = %s
                    ORDER BY sequence ASC
                    """,
                    (case_id, tenant_id),
                )
                rows = cursor.fetchall()
        finally:
            self._release(connection)
        return [CaseLifecycleEvent.model_validate(dict(row)) for row in rows]
