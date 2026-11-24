"""FastAPI dependencies: shared objects live on ``app.state`` (built once by the lifespan)."""

from typing import cast

from fastapi import Request

from vendorguard.api.jobs import JobRegistry
from vendorguard.config import Settings
from vendorguard.interfaces.memory import MemoryStore
from vendorguard.models.control import ControlSet
from vendorguard.observability.metrics import Metrics


def get_settings(request: Request) -> Settings:
    """The settings the app was created with."""
    return cast(Settings, request.app.state.settings)


def get_metrics(request: Request) -> Metrics:
    """The process-wide Prometheus metrics."""
    return cast(Metrics, request.app.state.metrics)


def get_jobs(request: Request) -> JobRegistry:
    """The job registry (one worker thread)."""
    return cast(JobRegistry, request.app.state.jobs)


def get_controls(request: Request) -> ControlSet:
    """The control set, loaded once at startup."""
    return cast(ControlSet, request.app.state.controls)


def get_principal(request: Request) -> str:
    """Who the gate let in (``key`` or ``ip:<address>``); set by ``AccessGate``."""
    return str(request.state.principal)


def get_memory(request: Request) -> MemoryStore:
    """The memory store (one SQLite connection, shared and lock-guarded)."""
    return cast(MemoryStore, request.app.state.memory)


__all__ = [
    "get_controls",
    "get_jobs",
    "get_memory",
    "get_metrics",
    "get_principal",
    "get_settings",
]
