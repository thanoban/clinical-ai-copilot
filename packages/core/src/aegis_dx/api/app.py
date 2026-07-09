from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status

from aegis_dx.config import Settings, load_settings
from aegis_dx.domain import (
    ActorRole,
    AuditEvent,
    CaseRecord,
    CaseLifecycleEvent,
    CaseReviewRequest,
    CaseSubmissionAccepted,
    CaseSubmissionRequest,
    EventSchemaDefinition,
    Principal,
)
from aegis_dx.event_schemas import CASE_EVENT_SCHEMAS
from aegis_dx.ports import CaseStorePort
from aegis_dx.queueing import CaseQueuePort, InProcessCaseQueue
from aegis_dx.specialists import ModelBackedChestXRaySpecialistAdapter, SpecialistRegistry
from aegis_dx.store import SQLiteCaseStore
from aegis_dx.tracing import (
    CORRELATION_ID_HEADER,
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from aegis_dx.trust import ModelBackedVerificationAdapter, assert_heterogeneous_verifier
from aegis_dx.workflow import WorkflowRuntime


def _build_store(settings: Settings) -> CaseStorePort:
    if settings.database_url:
        from aegis_dx.postgres_store import PostgresCaseStore

        return PostgresCaseStore(settings.database_url)
    return SQLiteCaseStore(settings.database_path)


def _build_queue(settings: Settings) -> CaseQueuePort:
    if settings.redis_url:
        from aegis_dx.queueing import RedisStreamCaseQueue

        return RedisStreamCaseQueue(settings.redis_url)
    return InProcessCaseQueue()


def _build_runtime(settings: Settings) -> WorkflowRuntime:
    assert_heterogeneous_verifier(
        settings.cxr_specialist_endpoint_url,
        settings.verifier_endpoint_url,
    )
    store = _build_store(settings)
    case_queue = _build_queue(settings)
    specialists = SpecialistRegistry(
        [
            ModelBackedChestXRaySpecialistAdapter(
                endpoint_url=settings.cxr_specialist_endpoint_url,
                api_key=settings.cxr_specialist_api_key,
                model_version=settings.cxr_specialist_model_version,
                request_timeout_seconds=settings.cxr_specialist_timeout_seconds,
            )
        ]
    )
    verifier = ModelBackedVerificationAdapter(
        endpoint_url=settings.verifier_endpoint_url,
        api_key=settings.verifier_api_key,
        model_version=settings.verifier_model_version,
        request_timeout_seconds=settings.verifier_timeout_seconds,
    )
    return WorkflowRuntime(
        store=store,
        case_queue=case_queue,
        specialists=specialists,
        verifier=verifier,
        worker_poll_interval_seconds=settings.worker_poll_interval_seconds,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or load_settings()
    runtime = _build_runtime(app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        runtime.start()
        yield
        runtime.stop()

    app = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        summary="Walking skeleton for the Aegis-Dx diagnostic workflow.",
        lifespan=lifespan,
    )
    app.state.runtime = runtime

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or new_correlation_id()
        token = set_correlation_id(correlation_id)
        request.state.correlation_id = correlation_id
        try:
            response = await call_next(request)
        finally:
            reset_correlation_id(token)
        response.headers.setdefault(CORRELATION_ID_HEADER, correlation_id)
        return response

    def get_runtime() -> WorkflowRuntime:
        return app.state.runtime

    def get_request_correlation_id(request: Request) -> str:
        return getattr(request.state, "correlation_id", new_correlation_id())

    def get_principal(
        x_actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
        x_actor_role: str | None = Header(default=None, alias="X-Actor-Role"),
        x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    ) -> Principal:
        if not x_actor_id or not x_actor_role or not x_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Missing identity headers. Provide X-Actor-Id, X-Actor-Role, "
                    "and X-Tenant-Id for the Phase 0 RBAC skeleton."
                ),
            )
        try:
            role = ActorRole(x_actor_role)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported role '{x_actor_role}'.",
            ) from exc
        return Principal(actor_id=x_actor_id, tenant_id=x_tenant_id, role=role)

    def require_roles(*roles: ActorRole):
        allowed = set(roles)

        def dependency(
            principal: Principal = Depends(get_principal),
        ) -> Principal:
            if principal.role not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Role is not allowed to access this endpoint.",
                )
            return principal

        return dependency

    @app.get("/healthz")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/cases", response_model=CaseSubmissionAccepted, status_code=status.HTTP_202_ACCEPTED)
    def submit_case(
        request: CaseSubmissionRequest,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        principal: Principal = Depends(
            require_roles(ActorRole.CLINICIAN, ActorRole.REVIEWER, ActorRole.ADMIN)
        ),
        runtime: WorkflowRuntime = Depends(get_runtime),
    ) -> CaseSubmissionAccepted:
        case, replayed = runtime.submit_case(
            request,
            principal,
            idempotency_key=idempotency_key,
        )
        response.headers[CORRELATION_ID_HEADER] = case.trace_id
        if idempotency_key:
            response.headers["Idempotency-Key"] = idempotency_key
        return CaseSubmissionAccepted(
            case_id=case.case_id,
            trace_id=case.trace_id,
            status=case.status,
            idempotency_replayed=replayed,
        )

    @app.get("/v1/cases", response_model=list[CaseRecord])
    def list_cases(
        response: Response,
        request: Request,
        principal: Principal = Depends(
            require_roles(
                ActorRole.CLINICIAN,
                ActorRole.REVIEWER,
                ActorRole.ADMIN,
                ActorRole.AUDITOR,
            )
        ),
        runtime: WorkflowRuntime = Depends(get_runtime),
    ) -> list[CaseRecord]:
        response.headers[CORRELATION_ID_HEADER] = get_request_correlation_id(request)
        return runtime.list_cases(principal)

    @app.get("/v1/cases/{case_id}", response_model=CaseRecord)
    def get_case(
        case_id: str,
        response: Response,
        principal: Principal = Depends(
            require_roles(
                ActorRole.CLINICIAN,
                ActorRole.REVIEWER,
                ActorRole.ADMIN,
                ActorRole.AUDITOR,
            )
        ),
        runtime: WorkflowRuntime = Depends(get_runtime),
    ) -> CaseRecord:
        try:
            case = runtime.get_case(case_id, principal, log_access=True)
            response.headers[CORRELATION_ID_HEADER] = case.trace_id
            return case
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Case is not in your tenant.") from exc

    @app.get("/v1/cases/{case_id}/audit", response_model=list[AuditEvent])
    def get_audit_log(
        case_id: str,
        response: Response,
        principal: Principal = Depends(
            require_roles(ActorRole.REVIEWER, ActorRole.ADMIN, ActorRole.AUDITOR)
        ),
        runtime: WorkflowRuntime = Depends(get_runtime),
    ) -> list[AuditEvent]:
        try:
            events = runtime.list_audit_events(case_id, principal)
            if events:
                response.headers[CORRELATION_ID_HEADER] = events[0].payload["trace_id"]
            return events
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Case is not in your tenant.") from exc

    @app.get("/v1/cases/{case_id}/events", response_model=list[CaseLifecycleEvent])
    def get_case_events(
        case_id: str,
        response: Response,
        principal: Principal = Depends(
            require_roles(
                ActorRole.CLINICIAN,
                ActorRole.REVIEWER,
                ActorRole.ADMIN,
                ActorRole.AUDITOR,
            )
        ),
        runtime: WorkflowRuntime = Depends(get_runtime),
    ) -> list[CaseLifecycleEvent]:
        try:
            events = runtime.list_case_events(case_id, principal)
            if events:
                response.headers[CORRELATION_ID_HEADER] = events[0].payload["trace_id"]
            return events
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Case is not in your tenant.") from exc

    @app.get("/v1/event-schemas", response_model=list[EventSchemaDefinition])
    def list_event_schemas(
        response: Response,
        request: Request,
        principal: Principal = Depends(
            require_roles(
                ActorRole.CLINICIAN,
                ActorRole.REVIEWER,
                ActorRole.ADMIN,
                ActorRole.AUDITOR,
            )
        ),
    ) -> list[EventSchemaDefinition]:
        response.headers[CORRELATION_ID_HEADER] = get_request_correlation_id(request)
        return list(CASE_EVENT_SCHEMAS.values())

    @app.post("/v1/cases/{case_id}/review", response_model=CaseRecord)
    def review_case(
        case_id: str,
        review: CaseReviewRequest,
        response: Response,
        principal: Principal = Depends(require_roles(ActorRole.CLINICIAN, ActorRole.REVIEWER)),
        runtime: WorkflowRuntime = Depends(get_runtime),
    ) -> CaseRecord:
        try:
            case = runtime.review_case(case_id, review, principal)
            response.headers[CORRELATION_ID_HEADER] = case.trace_id
            return case
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Case is not in your tenant.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return app


app = create_app()
