"""Page 1: upload vendor documents, start an assessment and watch it run."""

import time
from collections.abc import Callable

import streamlit as st

from vendorguard.config_models.core import UiSettings
from vendorguard.ui.api_client import ApiClient, RunView, UiApiError
from vendorguard.ui.cache import LISTS, forget_prefix
from vendorguard.ui.limits import UploadLimits
from vendorguard.ui.progress import wait_for_run
from vendorguard.ui.text import plain
from vendorguard.ui.validation import VENDOR_ID_PATTERN
from vendorguard.utils.timeutil import monotonic_s

PENDING = "pending_run"  # a run being followed: a rerun resumes the wait instead of losing it


def render(
    client: ApiClient,
    ui: UiSettings,
    limits: UploadLimits,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = monotonic_s,
) -> None:
    """Draw the page; a started run is remembered in ``st.session_state['run_id']``."""
    st.subheader("Assess a vendor")
    st.caption(
        "Upload the vendor's documents. The assessment runs on the API server, one at a time."
    )
    vendor_id = st.text_input("Vendor ID", help="Letters, digits, '.', '_' or '-'; e.g. nimbara-hr")
    files = st.file_uploader(
        "Documents (PDF, TXT or Markdown)",
        type=list(limits.extensions),
        accept_multiple_files=True,
    )
    if st.button("Start assessment", type="primary"):
        _start(client, ui, limits, vendor_id, files or [], sleep, clock)
    elif st.session_state.get(PENDING):  # the page was rerun while a run was being followed
        _follow(client, ui, st.session_state[PENDING], sleep, clock)


def _start(client, ui, limits, vendor_id, files, sleep, clock) -> None:  # type: ignore[no-untyped-def]
    if not VENDOR_ID_PATTERN.match(vendor_id):
        st.error("Enter a vendor ID of letters, digits, '.', '_' or '-' (at most 64 characters).")
        return
    if not files:
        st.error("Add at least one document.")
        return
    problems = limits.problems([(f.name, f.size) for f in files])  # sizes: before reading any file
    if problems:
        st.error(" ".join(problems))
        return
    try:
        run_id = client.start_assessment(vendor_id, [(f.name, f.getvalue()) for f in files])
    except UiApiError as exc:
        st.error(plain(exc.detail))
        return
    st.session_state["run_id"] = run_id
    st.session_state[PENDING] = run_id
    _follow(client, ui, run_id, sleep, clock)


def _follow(
    client: ApiClient,
    ui: UiSettings,
    run_id: str,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> None:
    st.text(f"Run {run_id}")
    with st.status("Assessment queued", expanded=True) as status:

        def tick(view: RunView) -> None:
            status.update(label=f"Assessment {view.status}")

        try:
            view = wait_for_run(
                client,
                run_id,
                interval_s=ui.poll_interval_s,
                timeout_s=ui.poll_timeout_s,
                sleep=sleep,
                clock=clock,
                on_tick=tick,
            )
        except UiApiError as exc:
            status.update(label="Stopped waiting", state="error")
            st.session_state.pop(PENDING, None)
            st.text(exc.detail)
            return
        st.session_state.pop(PENDING, None)
        forget_prefix(st.session_state, LISTS)  # a new result changes the vendor list
        if view.status == "done" and view.result is not None:
            status.update(label="Assessment done", state="complete")
            score = view.result.score
            st.text(f"Risk score {score.overall:g} / 100 ({score.band.value})")
            st.text("Open the Findings tab to review the evidence and record decisions.")
        else:
            status.update(label="Assessment failed", state="error")
            st.text(f"The run failed ({view.error or 'unknown error'}).")


__all__ = ["render"]
