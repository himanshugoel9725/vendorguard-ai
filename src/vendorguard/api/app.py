"""The FastAPI application: an app factory whose lifespan builds the shared objects once."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from vendorguard import __version__
from vendorguard.api.routes import system
from vendorguard.config import Settings, get_settings
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

    app = FastAPI(
        title=settings.app.name,
        version=__version__,
        description="Third-party security risk assessment: documents in, an auditable report out.",
        lifespan=lifespan,
    )
    app.include_router(system.router)
    return app


def main() -> None:
    """Serve on the host and port from the settings (``make api``)."""
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.api.host, port=settings.api.port)


if __name__ == "__main__":
    main()

__all__ = ["create_app", "main"]
