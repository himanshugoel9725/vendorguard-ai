"""Report download: fetched on request, offered only for the run it belongs to."""

from typing import cast

import streamlit as st

from vendorguard.ui.api_client import ApiClient, ReportFormat, UiApiError
from vendorguard.ui.text import plain

REPORT_TYPES: dict[str, str] = {
    "html": "text/html",
    "md": "text/markdown",
    "json": "application/json",
}
KEY = "report"


def render(client: ApiClient, run_id: str) -> None:
    """Draw the format choice, the prepare button and, once prepared, the download button."""
    st.text("Report")
    fmt = st.radio("Format", list(REPORT_TYPES), horizontal=True)
    if st.button("Prepare download"):
        try:
            data = client.get_report(run_id, cast(ReportFormat, fmt))
        except UiApiError as exc:
            st.error(plain(exc.detail))
            return
        st.session_state[KEY] = (run_id, fmt, data)
    prepared = st.session_state.get(KEY)
    if prepared and prepared[0] == run_id:  # never offer another run's report
        _, kind, data = prepared
        st.download_button(
            f"Download {kind} report", data, f"report-{run_id}.{kind}", REPORT_TYPES[kind]
        )


__all__ = ["KEY", "REPORT_TYPES", "render"]
