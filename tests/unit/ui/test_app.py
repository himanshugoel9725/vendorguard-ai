"""The Streamlit entry point: settings, host check, connection check and the three tabs."""

from collections.abc import Callable
from pathlib import Path

import pytest
import streamlit as st
from streamlit.runtime.context import ContextProxy
from streamlit.testing.v1 import AppTest

from vendorguard.config import Settings
from vendorguard.ui.api_client import ApiClient

APP = Path(__file__).resolve().parents[3] / "src" / "vendorguard" / "ui" / "app.py"
SENTINEL = "ui-key-SENTINEL-" + "z" * 24


@pytest.fixture
def app(settings_override: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch) -> AppTest:
    settings = settings_override(ui={"api_key": SENTINEL})
    monkeypatch.setattr("vendorguard.config.load_settings", lambda *a, **k: settings)  # never .env
    monkeypatch.setattr(ApiClient, "health", lambda self: False)  # no connection attempt at all
    st.cache_resource.clear()
    return AppTest.from_file(str(APP), default_timeout=60)


def _host(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    headers = {} if value is None else {"Host": value}
    monkeypatch.setattr(ContextProxy, "headers", property(lambda self: headers))


def test_app_draws_the_title_tabs_and_a_connection_warning(app: AppTest) -> None:
    app.run()
    assert not app.exception
    assert app.title[0].value == "VendorGuard AI"
    assert [t.label for t in app.tabs] == ["Assess", "Findings", "History and Ask"]
    sidebar_text = [str(t.value) for t in app.sidebar.text]
    assert "API: http://127.0.0.1:8000" in sidebar_text
    assert any("API not reachable" in t for t in sidebar_text)


def test_app_never_shows_the_api_key_anywhere(app: AppTest) -> None:
    app.run()
    assert SENTINEL not in repr(app.main) + repr(app.sidebar) + repr(app.session_state)
    assert not any(SENTINEL in str(e.value) for e in (*app.exception, *app.error, *app.warning))


def test_app_hints_when_no_ui_key_is_set(
    settings_override: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_override()
    monkeypatch.setattr("vendorguard.config.load_settings", lambda *a, **k: settings)
    monkeypatch.setattr(ApiClient, "health", lambda self: False)
    st.cache_resource.clear()
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert any("VG_UI__API_KEY" in str(t.value) for t in at.sidebar.text)


@pytest.mark.parametrize("host", ["127.0.0.1:8501", "localhost:8501", "[::1]:8501", None])
def test_the_page_answers_on_this_machine(
    app: AppTest, monkeypatch: pytest.MonkeyPatch, host: str | None
) -> None:
    _host(monkeypatch, host)
    app.run()
    assert not app.exception and app.title
    assert not any(
        "only answers" in str(e.value) for e in app.error
    )  # (the API is down: other errors are fine)


@pytest.mark.parametrize("host", ["evil.test:8501", "127.0.0.1.evil.test", "192.168.1.9:8501"])
def test_dns_rebinding_gets_a_refusal_and_no_api_call(
    app: AppTest, monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    """Audit 12.7 (M1): a hostile page that rebinds its own name to this machine is ignored."""
    calls: list[str] = []
    monkeypatch.setattr(ApiClient, "health", lambda self: calls.append("health") or True)
    monkeypatch.setattr(ApiClient, "vendors", lambda self: calls.append("vendors") or [])
    _host(monkeypatch, host)
    app.run()
    assert "only answers on the addresses" in str(app.error[0].value)
    assert not app.title and not app.tabs and calls == []  # nothing drawn, nothing fetched
