"""Page 3: vendor history and questions about it."""

import streamlit as st

from vendorguard.ui.api_client import ApiClient, UiApiError


def render(client: ApiClient) -> None:
    """Draw the vendor list, the history of the chosen vendor and the Ask form."""
    st.subheader("Vendors and history")
    try:
        vendors = client.vendors()
    except UiApiError as exc:
        st.error(exc.detail)
        return
    if not vendors:
        st.caption("No assessments are stored yet. Run one on the Assess tab.")
        return
    st.dataframe(
        [
            {"vendor": v.vendor_id, "name": v.name, "runs": v.runs, "latest band": v.latest_band}
            for v in vendors
        ],
        hide_index=True,
        use_container_width=True,
    )
    vendor_id = st.selectbox("Vendor", [v.vendor_id for v in vendors])
    _history(client, vendor_id)
    _ask(client, vendor_id)


def _history(client: ApiClient, vendor_id: str) -> None:
    try:
        history = client.history(vendor_id)
    except UiApiError as exc:
        st.error(exc.detail)
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
        use_container_width=True,
    )


def _ask(client: ApiClient, vendor_id: str) -> None:
    st.markdown("**Ask about this vendor**")
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
        st.error(exc.detail)
        return
    st.text(answer.text)
    st.caption(
        f"Cites runs: {', '.join(answer.cited_run_ids) or 'none'}; controls: "
        f"{', '.join(answer.cited_control_ids) or 'none'}; answered by {answer.provider}."
    )


__all__ = ["render"]
