"""Streamlit entry point: ``make ui``. It is a client of the REST API (ADR-021).

Like ``cli/`` and ``api/``, this is an entry point and the only UI module that loads the settings.
"""

import atexit

import streamlit as st

from vendorguard.config import load_settings
from vendorguard.config_models.core import UiSettings
from vendorguard.logging_setup import collect_secrets, setup_logging
from vendorguard.ui.api_client import ApiClient
from vendorguard.ui.limits import UploadLimits
from vendorguard.ui.text import host_allowed
from vendorguard.ui.views import assess, findings, history


@st.cache_resource(show_spinner=False)
def _setup() -> tuple[ApiClient, UiSettings, UploadLimits]:
    settings = load_settings()
    setup_logging(settings.app, collect_secrets(settings))
    ui = settings.ui
    client = ApiClient(ui.api_base_url, ui.api_key, ui.request_timeout_s, ui.max_detail_chars)
    atexit.register(client.close)
    limits = UploadLimits(  # the same limits the API enforces, from the same settings file
        extensions=tuple(e.lstrip(".") for e in settings.ingest.allowed_extensions),
        max_file_mb=settings.api.max_upload_mb,
        max_files=settings.api.max_files_per_request,
    )
    return client, ui, limits


def main() -> None:
    """Draw the page: a host check, a connection check in the sidebar and the three tabs."""
    client, ui, limits = _setup()
    st.set_page_config(page_title=ui.page_title, layout="wide")
    if not host_allowed(st.context.headers.get("Host"), ui.allowed_hosts):
        # DNS rebinding: a hostile web page reached this machine under its own name. Do nothing.
        st.error("This page only answers on the addresses listed in ui.allowed_hosts.")
        st.stop()
    st.title(ui.page_title)
    with st.sidebar:
        st.text(f"API: {client.base_url}")
        st.text("Connected" if client.health() else "API not reachable: start it with `make api`")
        if not ui.api_key.get_secret_value():
            st.text("No key: set VG_UI__API_KEY in .env (the same value as the API's key)")
        st.caption("Local use only: no login; it uses the API key of whoever started it.")
    assess_tab, findings_tab, history_tab = st.tabs(["Assess", "Findings", "History and Ask"])
    with assess_tab:
        assess.render(client, ui, limits)
    with findings_tab:
        findings.render(client)
    with history_tab:
        history.render(client, ui)


main()
