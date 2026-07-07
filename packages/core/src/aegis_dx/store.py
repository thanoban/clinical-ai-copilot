from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import threading

from aegis_dx.domain import AuditEvent, CaseRecord, CaseStatus


class SQLiteCaseStore:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    actor_role TEXT,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    previous_hash TEXT,
                    entry_hash TEXT NOT NULL
                );
                """
            )

    def save_case(self, case: CaseRecord) -> CaseRecord:
        payload = json.dumps(case.model_dump(mode="json"), sort_keys=True)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO cases (case_id, tenant_id, status, payload, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    tenant_id = excluded.tenant_id,
                    status = excluded.status,
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (
                    case.case_id,
                    case.tenant_id,
                    case.status.value,
                    payload,
                    case.updated_at.isoformat(),
                ),
            )
        return case

    def get_case(self, case_id: str) -> CaseRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM cases WHERE case_id = ?",
                (case_id,),
            ).fetchone()
        if row is None:
            return None
        return CaseRecord.model_validate_json(row["payload"])

    def list_cases_for_tenant(self, tenant_id: str) -> list[CaseRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM cases
                WHERE tenant_id = ?
                ORDER BY updated_at DESC
                """,
                (tenant_id,),
            ).fetchall()
        return [CaseRecord.model_validate_json(row["payload"]) for row in rows]

    def list_pending_case_ids(self) -> list[str]:
        terminal_statuses = (
            CaseStatus.CONFIRMED.value,
            CaseStatus.EDITED.value,
            CaseStatus.REJECTED.value,
            CaseStatus.CLOSED.value,
            CaseStatus.AWAITING_REVIEW.value,
        )
        placeholders = ", ".join("?" for _ in terminal_statuses)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT case_id
                FROM cases
                WHERE status NOT IN ({placeholders})
                ORDER BY updated_at ASC
                """,
                terminal_statuses,
            ).fetchall()
        return [row["case_id"] for row in rows]

    def append_audit_event(self, event: AuditEvent) -> AuditEvent:
        with self._lock, self._connect() as connection:
            previous_row = connection.execute(
                """
                SELECT entry_hash
                FROM audit_log
                WHERE case_id = ?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (event.case_id,),
            ).fetchone()
            previous_hash = previous_row["entry_hash"] if previous_row else None
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
            cursor = connection.execute(
                """
                INSERT INTO audit_log (
                    case_id,
                    tenant_id,
                    event_type,
                    actor_id,
                    actor_role,
                    payload,
                    created_at,
                    previous_hash,
                    entry_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.case_id,
                    event.tenant_id,
                    event.event_type,
                    event.actor_id,
                    event.actor_role,
                    serialized_payload,
                    event.created_at.isoformat(),
                    previous_hash,
                    entry_hash,
                ),
            )

        return event.model_copy(
            update={
                "sequence": cursor.lastrowid,
                "previous_hash": previous_hash,
                "entry_hash": entry_hash,
            }
        )

    def list_audit_events(self, case_id: str, tenant_id: str) -> list[AuditEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sequence, case_id, tenant_id, event_type, actor_id, actor_role,
                       payload, created_at, previous_hash, entry_hash
                FROM audit_log
                WHERE case_id = ? AND tenant_id = ?
                ORDER BY sequence ASC
                """,
                (case_id, tenant_id),
            ).fetchall()

        events: list[AuditEvent] = []
        for row in rows:
            events.append(
                AuditEvent.model_validate(
                    {
                        "sequence": row["sequence"],
                        "case_id": row["case_id"],
                        "tenant_id": row["tenant_id"],
                        "event_type": row["event_type"],
                        "actor_id": row["actor_id"],
                        "actor_role": row["actor_role"],
                        "payload": json.loads(row["payload"]),
                        "created_at": row["created_at"],
                        "previous_hash": row["previous_hash"],
                        "entry_hash": row["entry_hash"],
                    }
                )
            )
        return events

