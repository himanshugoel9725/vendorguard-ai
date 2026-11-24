"""Tests for the app factory and the system routes (no model, no network)."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vendorguard import __version__
from vendorguard.api import app as app_module
from vendorguard.api.app import create_app
from vendorguard.config import Settings

Make = Callable[..., Settings]


def _auth(s: Settings) -> dict[str, str]:
    return {"X-API-Key": s.api.auth_key.get_secret_value()}


@pytest.fixture
def client(settings_override: Make) -> Any:
    s = settings_override()
    with TestClient(create_app(s), headers=_auth(s)) as c:
        yield c


def test_health_is_ok(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_version_reports_name_and_package_version(
    client: TestClient, settings_override: Make
) -> None:
    r = client.get("/version")
    assert r.status_code == 200
    assert r.json() == {"name": settings_override().app.name, "version": __version__}


def test_metrics_are_prometheus_text(client: TestClient) -> None:
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "# HELP vg_runs_total" in r.text and "# TYPE vg_step_latency_seconds histogram" in r.text


def test_docs_and_openapi_list_the_system_routes(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/health", "/version", "/metrics"} <= set(paths)


def test_unknown_routes_and_methods_are_refused(client: TestClient) -> None:
    assert client.get("/nope").status_code == 404
    assert client.post("/health").status_code == 405


def test_the_app_uses_the_settings_it_is_given_not_the_environment(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> None:
        raise AssertionError("get_settings must not be called")

    monkeypatch.setattr(app_module, "get_settings", boom)
    with TestClient(create_app(settings_override())) as c:
        assert c.get("/health").status_code == 200


def test_the_memory_store_is_built_once_and_closed_on_shutdown(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    class Memory:
        def close(self) -> None:
            events.append("closed")

    def build(_settings: Settings) -> Memory:
        events.append("built")
        return Memory()

    monkeypatch.setattr(app_module, "build_memory_store", build)
    with TestClient(create_app(settings_override())) as c:
        c.get("/health")
        c.get("/health")
        assert events == ["built"]
    assert events == ["built", "closed"]


def test_two_apps_do_not_share_metrics(settings_override: Make) -> None:
    s = settings_override()
    a, b = create_app(s), create_app(s)
    with TestClient(a, headers=_auth(s)) as ca, TestClient(b, headers=_auth(s)) as cb:
        assert a.state.metrics is not b.state.metrics
        assert ca.get("/metrics").status_code == cb.get("/metrics").status_code == 200


def test_main_serves_on_the_configured_host_and_port(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = settings_override(api={"host": "127.0.0.1", "port": 8123})
    called: dict[str, Any] = {}
    monkeypatch.setattr(app_module, "get_settings", lambda: s)
    monkeypatch.setattr(app_module.uvicorn, "run", lambda app, **kw: called.update(kw, app=app))
    app_module.main()
    assert (
        called["host"] == "127.0.0.1"
        and called["port"] == 8123
        and called["app"].title == s.app.name
    )
