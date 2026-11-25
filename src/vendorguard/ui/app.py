"""Streamlit entry point: ``make ui``. It is a client of the REST API (ADR-021).

Like ``cli/`` and ``api/``, this is an entry point and the only UI module that loads the settings.
"""

import streamlit as st

from vendorguard.config import load_settings
from vendorguard.config_models.core import UiSettings
from vendorguard.logging_setup import collect_secrets, setup_logging
from vendorguard.ui.api_client import ApiClient
from vendorguard.ui.views import assess, findings, history


@st.cache_resource
def _client() -> tuple[ApiClient, UiSettings]:
    settings = load_settings()
    setup_logging(settings.app, collect_secrets(settings))
    ui = settings.ui
    return ApiClient(ui.api_base_url, ui.api_key, ui.request_timeout_s), ui


def main() -> None:
    """Draw the page: a connection check in the sidebar and the three tabs."""
    client, ui = _client()
    st.set_page_config(page_title=ui.page_title, layout="wide")
    st.title(ui.page_title)
    with st.sidebar:
        st.text(f"API: {client.base_url}")
        st.text("Connected" if client.health() else "API not reachable: start it with `make api`")
        st.caption(
            "Local use only: this page has no login and uses the API key of whoever started it."
        )
    assess_tab, findings_tab, history_tab = st.tabs(["Assess", "Findings", "History and Ask"])
    with assess_tab:
        assess.render(client, ui)
    with findings_tab:
        findings.render(client)
    with history_tab:
        history.render(client)


main()
