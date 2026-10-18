import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from jobpilot.api import (
    routes_applications,
    routes_auth_profile,
    routes_dashboard,
    routes_jobs,
    routes_notifications,
    routes_ops,
    routes_search,
    routes_settings,
)
from jobpilot.api.deps import csrf_protect
from jobpilot.config import get_settings
from jobpilot.domain.errors import DomainError
from jobpilot.security import HardeningMiddleware, check_settings

logging.basicConfig(level=logging.INFO, format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}')


def _error(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "details": details or {}}}, status_code=status)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if app.state.run_bootstrap:
        from jobpilot.bootstrap import bootstrap
        from jobpilot.db.session import SessionLocal

        db = SessionLocal()
        try:
            bootstrap(db)
        finally:
            db.close()
    yield


def create_app(run_bootstrap: bool = True) -> FastAPI:
    settings = get_settings()
    check_settings(settings)  # raises in production when the secret or admin password is weak
    docs = settings.api_docs if settings.api_docs is not None else settings.env != "production"
    app = FastAPI(title="JobPilot Europe API", version="1.0.0", lifespan=lifespan,
                  docs_url="/docs" if docs else None, redoc_url=None, openapi_url="/openapi.json" if docs else None)
    app.add_middleware(HardeningMiddleware, max_bytes=settings.max_request_bytes)
    app.state.run_bootstrap = run_bootstrap
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-Requested-With"],
    )

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError):
        return _error(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        return _error(422, "validation_error", "Request body failed validation",
                      {"errors": [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]})

    deps = [Depends(csrf_protect)]
    for r in (routes_auth_profile.auth, routes_auth_profile.router, routes_search.router, routes_jobs.router,
              routes_applications.router, routes_dashboard.router, routes_settings.router,
              routes_notifications.router, routes_ops.router):
        app.include_router(r, prefix="/api/v1", dependencies=deps)
    return app


app = create_app()
