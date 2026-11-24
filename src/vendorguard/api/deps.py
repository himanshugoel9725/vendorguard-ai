"""FastAPI dependencies: shared objects live on ``app.state`` (built once by the lifespan)."""

from typing import cast

from fastapi import Request

from vendorguard.config import Settings
from vendorguard.interfaces.memory import MemoryStore
from vendorguard.observability.metrics import Metrics


def get_settings(request: Request) -> Settings:
    """The settings the app was created with."""
    return cast(Settings, request.app.state.settings)


def get_metrics(request: Request) -> Metrics:
    """The process-wide Prometheus metrics."""
    return cast(Metrics, request.app.state.metrics)


def get_memory(request: Request) -> MemoryStore:
    """The memory store (one SQLite connection, shared and lock-guarded)."""
    return cast(MemoryStore, request.app.state.memory)


__all__ = ["get_memory", "get_metrics", "get_settings"]
