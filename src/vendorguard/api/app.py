"""The FastAPI application: an app factory whose lifespan builds the shared objects once."""

import logging
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from vendorguard import __version__
from vendorguard.api.jobs import Job, JobRegistry
from vendorguard.api.routes import assessments, system, vendors
from vendorguard.api.security import AccessGate, RateLimiter, check_startup
from vendorguard.config import Settings, get_settings
from vendorguard.controls.loader import load_controls
from vendorguard.errors import (
    BudgetExceededError,
    ConfigError,
    IngestError,
    MemoryStoreError,
    ProviderError,
    VendorGuardError,
)
from vendorguard.factory import build_memory_store
from vendorguard.logging_setup import collect_secrets, setup_logging
from vendorguard.observability.metrics import Metrics
from vendorguard.pipeline.orchestrator import run_assessment

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Only here (and in the CLI) are settings read from the environment.

    The lifespan creates the metrics registry and the memory store once. Providers are NOT
    shared: every assessment builds its own, because the cost budget is per run.
    """
    settings = settings or get_settings()
    check_startup(settings)  # no key (or a weak one) with auth on: refuse to start

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        setup_logging(settings.app, collect_secrets(settings))
        app.state.settings = settings
        app.state.metrics = Metrics(settings.observability)
        app.state.memory = build_memory_store(settings)
        app.state.controls = load_controls(settings.paths.controls_file)

        def work(job: Job) -> None:
            """Run one queued assessment (own providers: the budget is per run), then delete
            the uploaded files."""
            try:
                run_assessment(
                    settings,
                    job.vendor_id,
                    job.files,
                    memory=app.state.memory,
                    metrics=app.state.metrics,
                    run_id=job.run_id,
                )
            finally:
                shutil.rmtree(job.folder, ignore_errors=True)

        app.state.jobs = JobRegistry(
            work, settings.api.max_queued_jobs, settings.api.max_finished_jobs_kept
        )
        try:
            yield
        finally:
            app.state.jobs.close()
            close = getattr(app.state.memory, "close", None)
            if callable(close):
                close()

    docs = settings.api.docs_enabled
    app = FastAPI(
        title=settings.app.name,
        version=__version__,
        description="Third-party security risk assessment: documents in, an auditable report out.",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    limiter = RateLimiter(
        settings.api.rate_limit_per_minute, settings.api.rate_limit_max_principals
    )
    app.state.limiter = limiter

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, exc: RequestValidationError) -> JSONResponse:
        """422 without echoing the offending input (it may be a key or document text)."""
        errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    # Added first = innermost. CORS is added last (outermost) so the gate's refusals carry CORS
    # headers and a browser UI can read them.
    app.add_middleware(AccessGate, settings=settings, limiter=limiter)
    if settings.api.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api.cors_origins,
            allow_methods=["GET", "POST", "PATCH"],
            allow_headers=["X-API-Key", "Content-Type"],
            allow_credentials=False,
        )
    app.include_router(system.public_router)
    app.include_router(system.protected_router)
    app.include_router(assessments.router)
    app.include_router(vendors.router)
    _map_errors(app)
    return app


# Fixed messages: the text of a provider, ingest or storage error is never sent to a client.
ERROR_RESPONSES: list[tuple[type[VendorGuardError], int, str]] = [
    (IngestError, 422, "a document could not be read"),
    (BudgetExceededError, 429, "the cost budget of this request is used up"),
    (MemoryStoreError, 500, "the memory store failed"),  # before ProviderError: it is a subclass
    (ProviderError, 502, "a model provider failed"),
]


def _map_errors(app: FastAPI) -> None:
    """Turn the program's errors into JSON answers without leaking internals."""

    @app.exception_handler(ConfigError)
    async def config_error(_request: Request, exc: ConfigError) -> JSONResponse:
        """Our own messages about the request (an unknown ID, a refused override): safe to show."""
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(VendorGuardError)
    async def program_error(_request: Request, exc: VendorGuardError) -> JSONResponse:
        """Everything else: a fixed message by class, never ``str(exc)``."""
        for kind, status, detail in ERROR_RESPONSES:
            if isinstance(exc, kind):
                return JSONResponse(status_code=status, content={"detail": detail})
        return JSONResponse(status_code=500, content={"detail": "internal error"})


def main() -> None:
    """Serve on the host and port from the settings (``make api``)."""
    settings = get_settings()
    try:
        app = create_app(settings)
    except VendorGuardError as exc:
        raise SystemExit(f"error: {exc}") from exc
    # proxy_headers=False: X-Forwarded-For must not choose a client's rate-limit identity.
    uvicorn.run(
        app,
        host=settings.api.host,
        port=settings.api.port,
        proxy_headers=settings.api.trust_proxy_headers,
    )


if __name__ == "__main__":
    main()

__all__ = ["create_app", "main"]
