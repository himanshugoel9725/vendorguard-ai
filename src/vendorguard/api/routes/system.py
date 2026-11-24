"""System routes: liveness, version and Prometheus metrics."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from vendorguard import __version__
from vendorguard.api.deps import get_metrics, get_settings
from vendorguard.config import Settings
from vendorguard.observability.metrics import CONTENT_TYPE, Metrics

public_router = APIRouter(tags=["system"])  # no key: probes must work
protected_router = APIRouter(tags=["system"])  # behind ``require_access``


class Health(BaseModel):
    """Liveness answer."""

    status: str


class Version(BaseModel):
    """What is running."""

    name: str
    version: str


@public_router.get("/health", summary="Liveness check")
def health() -> Health:
    """Returns ``ok`` while the process serves requests (no dependencies are probed)."""
    return Health(status="ok")


@protected_router.get("/version", summary="Application name and version")
def version(settings: Annotated[Settings, Depends(get_settings)]) -> Version:
    """The application name (from the settings) and the package version."""
    return Version(name=settings.app.name, version=__version__)


@protected_router.get("/metrics", summary="Prometheus metrics", response_class=Response)
def metrics(metrics: Annotated[Metrics, Depends(get_metrics)]) -> Response:
    """The metrics in the Prometheus text format."""
    return Response(content=metrics.render(), media_type=CONTENT_TYPE)


__all__ = ["protected_router", "public_router"]
