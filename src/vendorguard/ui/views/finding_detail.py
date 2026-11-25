"""One finding: rationale, checked quotes and the analyst override form."""

import streamlit as st

from vendorguard.models.finding import ControlFinding, DraftStatus
from vendorguard.ui.api_client import ApiClient, UiApiError
from vendorguard.ui.cache import LISTS, forget_prefix
from vendorguard.ui.text import plain

FLASH = "flash"  # a message to show after the page reruns


def render(client: ApiClient, run_id: str, finding: ControlFinding) -> None:
    """Show the finding's evidence as plain text and its override form."""
    st.text(finding.rationale)
    for citation in finding.citations:
        if citation.valid:
            st.code(citation.quote, language=None)
            st.text(f"page {citation.page}" if citation.page else "page unknown")
    if finding.override:
        o = finding.override
        st.text(f"Overridden by {o.analyst} to {o.new_status.value}: {o.reason}")
    cid = finding.control_id
    with st.form(f"override-{cid}"):
        status = st.selectbox(
            "New status",
            [s.value for s in DraftStatus],
            index=None,
            placeholder="Choose a status",
            key=f"s-{cid}",
        )
        reason = st.text_area("Reason", key=f"r-{cid}")
        analyst = st.text_input("Your name", key=f"a-{cid}")
        if st.form_submit_button("Record decision"):
            _override(client, run_id, cid, status, reason, analyst)


def _override(
    client: ApiClient, run_id: str, control_id: str, status: str | None, reason: str, analyst: str
) -> None:
    if status is None or not reason.strip() or not analyst.strip():
        st.error("Choose a status and give a reason and your name: all three are required.")
        return
    try:
        outcome = client.override(
            run_id, control_id, DraftStatus(status), reason.strip(), analyst.strip()
        )
        view = client.get_run(run_id)
    except UiApiError as exc:
        st.error(plain(exc.detail))
        return
    if view.result is not None:
        st.session_state["result"] = view.result
    forget_prefix(st.session_state, LISTS)
    st.session_state[FLASH] = (
        f"Recorded. New risk score {outcome.score.overall:g} ({outcome.score.band.value})."
    )
    st.rerun()  # redraw the summary and the table with the new values


__all__ = ["FLASH", "render"]
