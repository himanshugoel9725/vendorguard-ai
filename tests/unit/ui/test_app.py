"""The Streamlit entry point: settings, connection check and the three tabs (no server involved)."""

from collections.abc import Callable
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from vendorguard.config import Settings

APP = Path(__file__).resolve().parents[3] / "src" / "vendorguard" / "ui" / "app.py"
CLOSED_PORT_URL = "http://127.0.0.1:9"  # the discard port: nothing listens, nothing is contacted


@pytest.fixture
def app(settings_override: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch) -> AppTest:
    settings = settings_override(ui={"api_base_url": CLOSED_PORT_URL})
    monkeypatch.setattr("vendorguard.config.load_settings", lambda *a, **k: settings)  # never .env
    st.cache_resource.clear()
    return AppTest.from_file(str(APP), default_timeout=60)


def test_app_draws_the_title_tabs_and_a_connection_warning(app: AppTest) -> None:
    app.run()
    assert not app.exception
    assert app.title[0].value == "VendorGuard AI"
    assert [t.label for t in app.tabs] == ["Assess", "Findings", "History and Ask"]
    sidebar_text = [str(t.value) for t in app.sidebar.text]
    assert f"API: {CLOSED_PORT_URL}" in sidebar_text
    assert any("API not reachable" in t for t in sidebar_text)


def test_app_never_shows_the_api_key(app: AppTest) -> None:
    app.run()
    rendered = " ".join(str(el.value) for el in (*app.text, *app.sidebar.text, *app.caption))
    assert "api_key" not in rendered.lower() and "x-api-key" not in rendered.lower()
