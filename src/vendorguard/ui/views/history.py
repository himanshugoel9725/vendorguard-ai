"""Page 3: vendor history and questions about it."""

from collections.abc import Callable

import streamlit as st

from vendorguard.config_models.core import UiSettings
from vendorguard.ui.api_client import ApiClient, UiApiError
from vendorguard.ui.cache import LISTS, forget_prefix, fresh
from vendorguard.ui.text import plain, spreadsheet_safe
from vendorguard.ui.validation import VENDOR_ID_PATTERN
from vendorguard.utils.timeutil import monotonic_s


def render(client: ApiClient, ui: UiSettings, clock: Callable[[], float] = monotonic_s) -> None:
    """Draw the vendor list, the history of the chosen vendor and the Ask form."""
    st.subheader("Vendors and history")
    if st.button("Refresh"):
        forget_prefix(st.session_state, LISTS)
    try:
        vendors = fresh(
            st.session_state, f"{LISTS}vendors", ui.refresh_ttl_s, client.vendors, clock
        )
    except UiApiError as exc:
        st.error(plain(exc.detail))
        return
    if not vendors:
        st.caption("No assessments are stored yet. Run one on the Assess tab.")
        return
    st.dataframe(
        [
            {
                "vendor": spreadsheet_safe(v.vendor_id),
                "name": spreadsheet_safe(v.name),  # from an untrusted document
                "runs": v.runs,
                "latest band": v.latest_band,
            }
            for v in vendors
        ],
        hide_index=True,
        width="stretch",
    )
    vendor_id = st.selectbox(
        "Vendor", [v.vendor_id for v in vendors if VENDOR_ID_PATTERN.match(v.vendor_id)]
    )
    if vendor_id:
        _history(client, ui, vendor_id, clock)
        _ask(client, vendor_id)


def _history(client: ApiClient, ui: UiSettings, vendor_id: str, clock: Callable[[], float]) -> None:
    try:
        history = fresh(
            st.session_state,
            f"{LISTS}history:{vendor_id}",
            ui.refresh_ttl_s,
            lambda: client.history(vendor_id),
            clock,
        )
    except UiApiError as exc:
        st.error(plain(exc.detail))
        return
    st.dataframe(
        [
            {
                "run": h.run_id,
                "when": h.created_at.isoformat(timespec="seconds"),
                "score": h.overall,
                "band": h.band.value,
            }
            for h in history
        ],
        hide_index=True,
        width="stretch",
    )


def _ask(client: ApiClient, vendor_id: str) -> None:
    st.text("Ask about this vendor")
    with st.form("ask"):
        question = st.text_input("Question", placeholder="What changed since last year?")
        submitted = st.form_submit_button("Ask")
    if not submitted:
        return
    if not question.strip():
        st.error("Type a question.")
        return
    try:
        answer = client.ask(vendor_id, question.strip())
    except UiApiError as exc:
        st.error(plain(exc.detail))
        return
    st.text(answer.text)
    st.text(
        f"Cites runs: {', '.join(answer.cited_run_ids) or 'none'}; controls: "
        f"{', '.join(answer.cited_control_ids) or 'none'}; answered by {answer.provider}."
    )


__all__ = ["render"]
