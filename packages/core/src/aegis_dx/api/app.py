from __future__ import annotations

from contextlib import asynccontextmanager
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from starlette.responses import PlainTextResponse

from aegis_dx.config import Settings, load_settings
from aegis_dx.domain import (
    ActorRole,
    AuditEvent,
    CaseRecord,
    CaseLifecycleEvent,
    CaseReviewRequest,
    SegmentationRefinementRequest,
    SegmentationRefinementResult,
    CaseSubmissionAccepted,
    CaseSubmissionRequest,
    EventSchemaDefinition,
    ModelRuntimeStatus,
    Principal,
)
from aegis_dx.ecg_specialists import ModelBackedECGSpecialistAdapter
from aegis_dx.event_schemas import CASE_EVENT_SCHEMAS
from aegis_dx.identity import (
    HeaderIdentityAdapter,
    IdentityAuthenticationError,
    IdentityAuthorizationError,
)
from aegis_dx.audit import StoreAuditAdapter
from aegis_dx.composition import ReflexiveSynthesisAdapter, StubSynthesisAdapter
from aegis_dx.metrics import InMemoryMetricsRegistry
from aegis_dx.model_readiness import endpoint_readiness, local_pretrained_readiness
from aegis_dx.ports import AuditPort, CaseStorePort, MetricsPort, SpecialistPort
from aegis_dx.queueing import CaseQueuePort, InProcessCaseQueue
from aegis_dx.specialists import (
    HFTorchXRayVisionSpecialistAdapter,
    ModelBackedChestXRaySpecialistAdapter,
    SpecialistRegistry,
)
from aegis_dx.segmentation import MedSAMSegmentationRefinerAdapter, SegmentationRefinementError
from aegis_dx.store import SQLiteCaseStore
from aegis_dx.tracing import (
    CORRELATION_ID_HEADER,
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from aegis_dx.trust import (
    HFTorchXRayVisionVerificationAdapter,
    ModelBackedVerificationAdapter,
    assert_heterogeneous_verifier,
)
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


def _build_cxr_specialist(settings: Settings) -> SpecialistPort:
    if settings.cxr_specialist_backend == "torchxrayvision-local":
        return HFTorchXRayVisionSpecialistAdapter()
    return ModelBackedChestXRaySpecialistAdapter(
        endpoint_url=settings.cxr_specialist_endpoint_url,
        api_key=settings.cxr_specialist_api_key,
        model_version=settings.cxr_specialist_model_version,
        request_timeout_seconds=settings.cxr_specialist_timeout_seconds,
    )


def _build_ecg_specialist(settings: Settings) -> SpecialistPort:
    return ModelBackedECGSpecialistAdapter(
        endpoint_url=settings.ecg_specialist_endpoint_url,
        api_key=settings.ecg_specialist_api_key,
        model_version=settings.ecg_specialist_model_version,
        request_timeout_seconds=settings.ecg_specialist_timeout_seconds,
    )


def _build_verifier(settings: Settings):
    if settings.verifier_backend == "torchxrayvision-local":
        return HFTorchXRayVisionVerificationAdapter()
    return ModelBackedVerificationAdapter(
        endpoint_url=settings.verifier_endpoint_url,
        api_key=settings.verifier_api_key,
        model_version=settings.verifier_model_version,
        request_timeout_seconds=settings.verifier_timeout_seconds,
    )


def _build_runtime(
    settings: Settings,
    *,
    metrics: MetricsPort | None = None,
    audit: AuditPort | None = None,
) -> WorkflowRuntime:
    assert_heterogeneous_verifier(
        specialist_backend=settings.cxr_specialist_backend,
        specialist_endpoint_url=settings.cxr_specialist_endpoint_url,
        verifier_backend=settings.verifier_backend,
        verifier_endpoint_url=settings.verifier_endpoint_url,
    )
    store = _build_store(settings)
    audit_adapter = audit or StoreAuditAdapter(store)
    case_queue = _build_queue(settings)
    specialists = SpecialistRegistry([_build_cxr_specialist(settings), _build_ecg_specialist(settings)])
    verifier = _build_verifier(settings)
    # Reflexion loop (docs/15 SS5.1): bounded self-critique wraps synthesis so a
    # differential that doesn't cite grounded evidence gets a chance to
    # self-correct before reaching the clinician, rather than being accepted
    # on the first pass.
    synthesis = ReflexiveSynthesisAdapter(StubSynthesisAdapter())
    return WorkflowRuntime(
        store=store,
        case_queue=case_queue,
        specialists=specialists,
        verifier=verifier,
        synthesis=synthesis,
        metrics=metrics,
        audit=audit_adapter,
        worker_poll_interval_seconds=settings.worker_poll_interval_seconds,
    )


def _build_segmentation_refiner(settings: Settings) -> MedSAMSegmentationRefinerAdapter:
    return MedSAMSegmentationRefinerAdapter(model_version=settings.medsam_checkpoint)


def _build_model_runtime_status(settings: Settings) -> list[ModelRuntimeStatus]:
    specialist_local = settings.cxr_specialist_backend == "torchxrayvision-local"
    verifier_local = settings.verifier_backend == "torchxrayvision-local"
    specialist_configured = specialist_local or bool(settings.cxr_specialist_endpoint_url)
    verifier_configured = verifier_local or bool(settings.verifier_endpoint_url)
    ecg_configured = bool(settings.ecg_specialist_endpoint_url)
    cxr_ready, cxr_reason = (
        local_pretrained_readiness(("torch", "torchxrayvision", "skimage"))
        if specialist_local
        else endpoint_readiness(settings.cxr_specialist_endpoint_url)
    )
    ecg_ready, ecg_reason = endpoint_readiness(settings.ecg_specialist_endpoint_url)
    verifier_ready, verifier_reason = (
        local_pretrained_readiness(("torch", "torchxrayvision", "skimage"))
        if verifier_local
        else endpoint_readiness(settings.verifier_endpoint_url)
    )
    segmentation_ready, segmentation_reason = local_pretrained_readiness(("torch", "transformers", "PIL"))
    return [
        ModelRuntimeStatus(
            component="cxr-specialist",
            backend=settings.cxr_specialist_backend,
            model_version=(
                "torchxrayvision-densenet121-chex"
                if specialist_local
                else settings.cxr_specialist_model_version
            ),
            execution_mode="local" if specialist_local else "remote" if specialist_configured else "fallback",
            configured=specialist_configured,
            fallback_available=True,
            runtime_ready=cxr_ready,
            readiness_reason=cxr_reason,
        ),
        ModelRuntimeStatus(
            component="ecg-specialist",
            backend=settings.ecg_specialist_backend,
            model_version=settings.ecg_specialist_model_version,
            execution_mode="remote" if ecg_configured else "fallback",
            configured=ecg_configured,
            fallback_available=True,
            runtime_ready=ecg_ready,
            readiness_reason=ecg_reason,
        ),
        ModelRuntimeStatus(
            component="verifier",
            backend=settings.verifier_backend,
            model_version=(
                "torchxrayvision-densenet121-chex"
                if verifier_local
                else settings.verifier_model_version
            ),
            execution_mode="local" if verifier_local else "remote" if verifier_configured else "fallback",
            configured=verifier_configured,
            fallback_available=True,
            runtime_ready=verifier_ready,
            readiness_reason=verifier_reason,
        ),
        ModelRuntimeStatus(
            component="segmentation",
            backend="medsam-local",
            model_version=settings.medsam_checkpoint,
            execution_mode="local",
            configured=bool(settings.medsam_checkpoint),
            fallback_available=False,
            runtime_ready=segmentation_ready and bool(settings.medsam_checkpoint),
            readiness_reason=(
                segmentation_reason
                if settings.medsam_checkpoint
                else "No MedSAM checkpoint is configured."
            ),
        ),
    ]


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or load_settings()
    metrics = InMemoryMetricsRegistry()
    runtime = _build_runtime(app_settings, metrics=metrics)
    segmentation_refiner = _build_segmentation_refiner(app_settings)
    identity = HeaderIdentityAdapter()

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
    app.state.metrics = metrics
    app.state.identity = identity

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or new_correlation_id()
        token = set_correlation_id(correlation_id)
        request.state.correlation_id = correlation_id
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
            metrics.inc(
                "aegis_dx_http_requests_total",
                labels={
                    "method": request.method,
                    "route": getattr(request.scope.get("route"), "path", "unmatched"),
                    "status": str(response.status_code),
                },
            )
            metrics.observe(
                "aegis_dx_http_request_duration_seconds",
                time.perf_counter() - started_at,
                labels={"method": request.method, "route": getattr(request.scope.get("route"), "path", "unmatched")},
            )
        finally:
            reset_correlation_id(token)
        response.headers.setdefault(CORRELATION_ID_HEADER, correlation_id)
        return response

    def get_runtime() -> WorkflowRuntime:
        return app.state.runtime

    def get_identity() -> HeaderIdentityAdapter:
        return app.state.identity

    def get_segmentation_refiner() -> MedSAMSegmentationRefinerAdapter:
        return segmentation_refiner

    def get_request_correlation_id(request: Request) -> str:
        return getattr(request.state, "correlation_id", new_correlation_id())

    def get_principal(
        request: Request,
        identity_adapter: HeaderIdentityAdapter = Depends(get_identity),
    ) -> Principal:
        try:
            return identity_adapter.authenticate(request.headers)
        except IdentityAuthenticationError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.detail,
            ) from exc

    def require_roles(*roles: ActorRole):
        allowed = set(roles)

        def dependency(
            principal: Principal = Depends(get_principal),
            identity_adapter: HeaderIdentityAdapter = Depends(get_identity),
        ) -> Principal:
            try:
                identity_adapter.require_roles(principal, allowed)
            except IdentityAuthorizationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=exc.detail,
                ) from exc
            return principal

        return dependency

    @app.get("/healthz")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
    def metrics_endpoint() -> PlainTextResponse:
        return PlainTextResponse(metrics.render_prometheus(), media_type="text/plain; version=0.0.4")

    @app.get("/v1/model-status", response_model=list[ModelRuntimeStatus])
    def model_status(
        principal: Principal = Depends(
            require_roles(
                ActorRole.CLINICIAN,
                ActorRole.REVIEWER,
                ActorRole.ADMIN,
                ActorRole.AUDITOR,
            )
        ),
    ) -> list[ModelRuntimeStatus]:
        del principal
        return _build_model_runtime_status(app_settings)

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

    @app.post("/v1/segmentations/refine", response_model=SegmentationRefinementResult)
    def refine_segmentation(
        request: SegmentationRefinementRequest,
        response: Response,
        principal: Principal = Depends(
            require_roles(
                ActorRole.CLINICIAN,
                ActorRole.REVIEWER,
                ActorRole.ADMIN,
                ActorRole.AUDITOR,
            )
        ),
        refiner: MedSAMSegmentationRefinerAdapter = Depends(get_segmentation_refiner),
    ) -> SegmentationRefinementResult:
        del principal
        try:
            result = refiner.refine(request)
            response.headers[CORRELATION_ID_HEADER] = new_correlation_id()
            return result
        except SegmentationRefinementError as exc:
            detail = str(exc)
            if "not installed" in detail or "Could not load MedSAM checkpoint" in detail:
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc

    return app


app = create_app()
