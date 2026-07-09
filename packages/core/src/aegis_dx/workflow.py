from __future__ import annotations

from datetime import datetime, timezone
from queue import Empty, Queue
import threading
import uuid

from aegis_dx.adapters import StubIngestionAdapter, StubTriageAdapter
from aegis_dx.composition import StubReportAdapter, StubRetrievalAdapter, StubSynthesisAdapter
from aegis_dx.domain import (
    ActorRole,
    AuditEvent,
    CaseLifecycleEvent,
    CaseRecord,
    CaseReviewRequest,
    CaseStatus,
    CaseSubmissionRequest,
    EscalationDecision,
    Finding,
    HumanAction,
    HumanReviewRecord,
    Principal,
    PROCESSABLE_CASE_STATUSES,
    StructuredReport,
    TERMINAL_CASE_STATUSES,
    TriageDecision,
    VerificationResult,
)
from aegis_dx.ports import GuardrailPort, IngestionPort, ReportPort, RetrievalPort, SynthesisPort, TriagePort, VerificationPort
from aegis_dx.specialists import SpecialistRegistry, StubChestXRaySpecialistAdapter
from aegis_dx.store import SQLiteCaseStore
from aegis_dx.event_schemas import get_event_schema
from aegis_dx.tracing import bind_correlation_id, get_correlation_id
from aegis_dx.trust import StubGuardrailAdapter, StubVerificationAdapter


class WorkflowRuntime:
    def __init__(
        self,
        store: SQLiteCaseStore,
        ingestion: IngestionPort | None = None,
        triage: TriagePort | None = None,
        specialists: SpecialistRegistry | None = None,
        retrieval: RetrievalPort | None = None,
        synthesis: SynthesisPort | None = None,
        reporter: ReportPort | None = None,
        verifier: VerificationPort | None = None,
        guardrail: GuardrailPort | None = None,
        worker_poll_interval_seconds: float = 0.05,
    ) -> None:
        self._store = store
        self._ingestion = ingestion or StubIngestionAdapter()
        self._triage = triage or StubTriageAdapter()
        self._specialists = specialists or SpecialistRegistry([StubChestXRaySpecialistAdapter()])
        self._retrieval = retrieval or StubRetrievalAdapter()
        self._synthesis = synthesis or StubSynthesisAdapter()
        self._reporter = reporter or StubReportAdapter()
        self._verifier = verifier or StubVerificationAdapter()
        self._guardrail = guardrail or StubGuardrailAdapter()
        self._worker_poll_interval_seconds = worker_poll_interval_seconds
        self._queue: Queue[str] = Queue()
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        for case_id in self._store.list_pending_case_ids():
            self.enqueue(case_id)
        self._worker_thread = threading.Thread(
            target=self._run_worker,
            name="aegis-dx-worker",
            daemon=True,
        )
        self._worker_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)

    def enqueue(self, case_id: str) -> None:
        self._queue.put(case_id)

    def submit_case(
        self,
        request: CaseSubmissionRequest,
        principal: Principal,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[CaseRecord, bool]:
        if idempotency_key:
            existing_case = self._store.get_case_by_idempotency_key(principal.tenant_id, idempotency_key)
            if existing_case is not None:
                return existing_case, True

        case_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        case = CaseRecord(
            case_id=case_id,
            trace_id=case_id,
            tenant_id=principal.tenant_id,
            site_id=request.site_id,
            status=CaseStatus.RECEIVED,
            artifact=self._ingestion.normalize(request.artifact),
            created_at=now,
            updated_at=now,
        )
        self._store.save_case(case)
        if idempotency_key:
            self._store.register_idempotency_key(
                principal.tenant_id,
                idempotency_key,
                case.case_id,
                now.isoformat(),
            )
        self._append_audit(
            case,
            event_type="case.submitted",
            principal=principal,
            payload={"site_id": request.site_id, "source_system": request.artifact.source_system},
        )
        self._append_case_event(
            case,
            event_type="case.submitted",
            payload={"site_id": request.site_id, "source_system": request.artifact.source_system},
        )
        self.enqueue(case.case_id)
        return case, False

    def list_cases(self, principal: Principal) -> list[CaseRecord]:
        return self._store.list_cases_for_tenant(principal.tenant_id)

    def get_case(
        self,
        case_id: str,
        principal: Principal,
        *,
        log_access: bool = False,
    ) -> CaseRecord:
        case = self._store.get_case(case_id)
        if case is None:
            raise KeyError(case_id)
        if case.tenant_id != principal.tenant_id:
            raise PermissionError(case_id)
        if log_access:
            self._append_audit(
                case,
                event_type="case.viewed",
                principal=principal,
                payload={"status": case.status.value},
            )
        return case

    def review_case(
        self,
        case_id: str,
        review: CaseReviewRequest,
        principal: Principal,
    ) -> CaseRecord:
        case = self.get_case(case_id, principal, log_access=False)
        if case.status != CaseStatus.AWAITING_REVIEW:
            raise ValueError(f"Case {case_id} is not awaiting review.")
        if review.action == HumanAction.EDIT and not review.edited_summary:
            raise ValueError("Edited cases require edited_summary.")

        if review.action == HumanAction.CONFIRM:
            case.status = CaseStatus.CONFIRMED
        elif review.action == HumanAction.EDIT:
            case.status = CaseStatus.EDITED
            if case.report is not None:
                case.report.summary = review.edited_summary or case.report.summary
        else:
            case.status = CaseStatus.REJECTED

        case.human_review = HumanReviewRecord(
            action=review.action,
            actor_id=principal.actor_id,
            note=review.note,
            edited_summary=review.edited_summary,
        )
        case.updated_at = datetime.now(timezone.utc)
        self._store.save_case(case)
        self._append_audit(
            case,
            event_type=f"case.review.{review.action.value}",
            principal=principal,
            payload={
                "note": review.note,
                "edited_summary": review.edited_summary,
            },
        )
        return case

    def list_audit_events(self, case_id: str, principal: Principal) -> list[AuditEvent]:
        case = self.get_case(case_id, principal, log_access=False)
        return self._store.list_audit_events(case.case_id, case.tenant_id)

    def list_case_events(self, case_id: str, principal: Principal) -> list[CaseLifecycleEvent]:
        case = self.get_case(case_id, principal, log_access=False)
        return self._store.list_case_events(case.case_id, case.tenant_id)

    def _run_worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                case_id = self._queue.get(timeout=self._worker_poll_interval_seconds)
            except Empty:
                continue
            try:
                self._process_case(case_id)
            finally:
                self._queue.task_done()

    def _process_case(self, case_id: str) -> None:
        service_principal = Principal(
            actor_id="workflow-service",
            tenant_id="system",
            role=ActorRole.SERVICE,
        )
        case = self._store.get_case(case_id)
        if case is None or case.status in TERMINAL_CASE_STATUSES:
            return

        service_principal = service_principal.model_copy(update={"tenant_id": case.tenant_id})
        with bind_correlation_id(case.trace_id):
            while case.status in PROCESSABLE_CASE_STATUSES:
                if case.status == CaseStatus.RECEIVED:
                    case.status = CaseStatus.DEIDENTIFIED
                    self._transition(case, service_principal, "workflow.deidentified")
                    continue

                if case.status == CaseStatus.DEIDENTIFIED:
                    decision = self._triage.classify(case.artifact)
                    case.modality = decision.modality
                    case.region = decision.region
                    case.urgency = decision.urgency
                    case.status = CaseStatus.TRIAGED
                    self._transition(
                        case,
                        service_principal,
                        "workflow.triaged",
                        payload=decision.model_dump(mode="json"),
                    )
                    continue

                if case.status == CaseStatus.TRIAGED:
                    triage = TriageDecision(
                        modality=case.modality or "unknown",
                        region=case.region or "unknown",
                        urgency=case.urgency,
                    )
                    case.evidence = self._retrieval.retrieve(case.artifact, triage)
                    self._record_event(
                        case,
                        service_principal,
                        "workflow.retrieved",
                        payload={
                            "status": case.status.value,
                            "evidence_count": len(case.evidence),
                            "modality": triage.modality,
                        },
                    )
                    case.status = CaseStatus.ANALYZING
                    self._transition(case, service_principal, "workflow.analysis_started")
                    continue

                if case.status == CaseStatus.ANALYZING:
                    specialist = self._specialists.resolve(case.modality)
                    if specialist is None:
                        case.status = CaseStatus.DEGRADED
                        case.escalation = EscalationDecision(
                            required=True,
                            reason=f"No specialist is registered for modality '{case.modality}'.",
                        )
                        case.report = self._degraded_report(case.modality, case.escalation.reason)
                        self._transition(
                            case,
                            service_principal,
                            "workflow.degraded",
                            payload={
                                "reason": case.escalation.reason,
                                "modality": case.modality,
                                "report_ready": case.report is not None,
                            },
                        )
                    else:
                        triage = TriageDecision(
                            modality=case.modality or "unknown",
                            region=case.region or "unknown",
                            urgency=case.urgency,
                        )
                        case.findings = specialist.analyze(case.artifact, triage)
                        if not case.findings:
                            case.status = CaseStatus.DEGRADED
                            case.escalation = EscalationDecision(
                                required=True,
                                reason=(
                                    f"Specialist '{specialist.modality}' returned no findings for "
                                    "this artifact."
                                ),
                            )
                            case.report = self._degraded_report(case.modality, case.escalation.reason)
                            self._transition(
                                case,
                                service_principal,
                                "workflow.degraded",
                                payload={
                                    "reason": case.escalation.reason,
                                    "modality": case.modality,
                                    "specialist_modality": specialist.modality,
                                    "report_ready": case.report is not None,
                                },
                            )
                        else:
                            case.status = CaseStatus.VERIFYING
                            self._transition(
                                case,
                                service_principal,
                                "workflow.analysis_completed",
                                payload={
                                    "findings": len(case.findings),
                                    "specialist_modality": specialist.modality,
                                },
                            )
                    continue

                if case.status == CaseStatus.VERIFYING:
                    triage = TriageDecision(
                        modality=case.modality or "unknown",
                        region=case.region or "unknown",
                        urgency=case.urgency,
                    )
                    case.verification = self._verifier.verify(case.findings, case.evidence, triage)
                    case.status = CaseStatus.SYNTHESIZED
                    self._transition(
                        case,
                        service_principal,
                        "workflow.verification_completed",
                        payload={
                            "flags": sum(len(item.critic_flags) for item in case.verification),
                            "escalated_findings": sum(
                                1 for item in case.verification if item.requires_escalation
                            ),
                        },
                    )
                    continue

                if case.status == CaseStatus.SYNTHESIZED:
                    triage = TriageDecision(
                        modality=case.modality or "unknown",
                        region=case.region or "unknown",
                        urgency=case.urgency,
                    )
                    case.differential = self._synthesis.synthesize(
                        case.findings,
                        case.evidence,
                        triage,
                    )
                    case.report = self._reporter.compose(
                        case.artifact,
                        triage,
                        case.findings,
                        case.evidence,
                        case.differential,
                    )
                    case.status = CaseStatus.CALIBRATED
                    self._transition(
                        case,
                        service_principal,
                        "workflow.synthesized",
                        payload={
                            "differential": len(case.differential),
                            "evidence_count": len(case.evidence),
                        },
                    )
                    continue

                if case.status == CaseStatus.CALIBRATED:
                    triage = TriageDecision(
                        modality=case.modality or "unknown",
                        region=case.region or "unknown",
                        urgency=case.urgency,
                    )
                    case.escalation = self._guardrail.decide(
                        case.findings,
                        case.verification,
                        triage,
                    )
                    case.status = (
                        CaseStatus.ESCALATED if case.escalation.required else CaseStatus.AWAITING_REVIEW
                    )
                    self._transition(
                        case,
                        service_principal,
                        "workflow.calibrated",
                        payload=case.escalation.model_dump(mode="json"),
                    )
                    continue

                if case.status in {CaseStatus.ESCALATED, CaseStatus.DEGRADED}:
                    case.status = CaseStatus.AWAITING_REVIEW
                    self._transition(case, service_principal, "workflow.awaiting_review")
                    continue

        self._store.save_case(case)

    def _degraded_report(self, modality: str | None, reason: str | None) -> StructuredReport:
        summary = (
            f"Analysis unavailable for {modality or 'this case'}: "
            f"{reason or 'no specialist findings could be produced.'} "
            "This case has been routed for direct clinician review."
        )
        return StructuredReport(summary=summary)

    def _transition(
        self,
        case: CaseRecord,
        principal: Principal,
        event_type: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        self._record_event(
            case,
            principal,
            event_type,
            payload={"status": case.status.value, **(payload or {})},
        )

    def _record_event(
        self,
        case: CaseRecord,
        principal: Principal,
        event_type: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        case.updated_at = datetime.now(timezone.utc)
        self._store.save_case(case)
        self._append_audit(
            case,
            event_type=event_type,
            principal=principal,
            payload=payload or {},
        )
        self._append_case_event(
            case,
            event_type=event_type,
            payload=payload or {},
        )

    def _append_audit(
        self,
        case: CaseRecord,
        event_type: str,
        principal: Principal,
        payload: dict[str, object] | None = None,
    ) -> AuditEvent:
        correlation_id = get_correlation_id()
        base_payload: dict[str, object] = {"trace_id": case.trace_id}
        if correlation_id is not None:
            base_payload["request_correlation_id"] = correlation_id
        event = AuditEvent(
            case_id=case.case_id,
            tenant_id=case.tenant_id,
            event_type=event_type,
            actor_id=principal.actor_id,
            actor_role=principal.role.value,
            payload={**base_payload, **(payload or {})},
        )
        return self._store.append_audit_event(event)

    def _append_case_event(
        self,
        case: CaseRecord,
        event_type: str,
        payload: dict[str, object] | None = None,
    ) -> CaseLifecycleEvent:
        correlation_id = get_correlation_id()
        base_payload: dict[str, object] = {"trace_id": case.trace_id}
        if correlation_id is not None:
            base_payload["request_correlation_id"] = correlation_id
        schema = get_event_schema(event_type)
        event = CaseLifecycleEvent(
            case_id=case.case_id,
            tenant_id=case.tenant_id,
            event_type=event_type,
            schema_version=schema.schema_version,
            payload={**base_payload, **(payload or {})},
        )
        return self._store.append_case_event(event)

