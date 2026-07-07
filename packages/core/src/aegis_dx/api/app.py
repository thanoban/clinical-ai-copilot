from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status

from aegis_dx.config import Settings, load_settings
from aegis_dx.domain import (
    ActorRole,
    AuditEvent,
    CaseRecord,
    CaseReviewRequest,
    CaseSubmissionAccepted,
    CaseSubmissionRequest,
    Principal,
)
from aegis_dx.store import SQLiteCaseStore
from aegis_dx.workflow import WorkflowRuntime


def _build_runtime(settings: Settings) -> WorkflowRuntime:
    store = SQLiteCaseStore(settings.database_path)
    return WorkflowRuntime(
        store=store,
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

    def get_runtime() -> WorkflowRuntime:
        return app.state.runtime

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
        principal: Principal = Depends(
            require_roles(ActorRole.CLINICIAN, ActorRole.REVIEWER, ActorRole.ADMIN)
        ),
        runtime: WorkflowRuntime = Depends(get_runtime),
    ) -> CaseSubmissionAccepted:
        case = runtime.submit_case(request, principal)
        response.headers["X-Correlation-Id"] = case.trace_id
        return CaseSubmissionAccepted(
            case_id=case.case_id,
            trace_id=case.trace_id,
            status=case.status,
        )

    @app.get("/v1/cases", response_model=list[CaseRecord])
    def list_cases(
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
        return runtime.list_cases(principal)

    @app.get("/v1/cases/{case_id}", response_model=CaseRecord)
    def get_case(
        case_id: str,
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
            return runtime.get_case(case_id, principal, log_access=True)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Case is not in your tenant.") from exc

    @app.get("/v1/cases/{case_id}/audit", response_model=list[AuditEvent])
    def get_audit_log(
        case_id: str,
        principal: Principal = Depends(
            require_roles(ActorRole.REVIEWER, ActorRole.ADMIN, ActorRole.AUDITOR)
        ),
        runtime: WorkflowRuntime = Depends(get_runtime),
    ) -> list[AuditEvent]:
        try:
            return runtime.list_audit_events(case_id, principal)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Case is not in your tenant.") from exc

    @app.post("/v1/cases/{case_id}/review", response_model=CaseRecord)
    def review_case(
        case_id: str,
        review: CaseReviewRequest,
        principal: Principal = Depends(require_roles(ActorRole.CLINICIAN, ActorRole.REVIEWER)),
        runtime: WorkflowRuntime = Depends(get_runtime),
    ) -> CaseRecord:
        try:
            return runtime.review_case(case_id, review, principal)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Case is not in your tenant.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return app


app = create_app()
