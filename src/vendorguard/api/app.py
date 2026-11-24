"""The FastAPI application: an app factory whose lifespan builds the shared objects once."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from vendorguard import __version__
from vendorguard.api.routes import system
from vendorguard.api.security import AccessGate, RateLimiter, check_startup
from vendorguard.config import Settings, get_settings
from vendorguard.errors import VendorGuardError
from vendorguard.factory import build_memory_store
from vendorguard.logging_setup import collect_secrets, setup_logging
from vendorguard.observability.metrics import Metrics

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
        try:
            yield
        finally:
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
    return app


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
