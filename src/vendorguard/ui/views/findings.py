"""Page 2: the findings of a run, their evidence, overrides and report downloads."""

import streamlit as st

from vendorguard.models.finding import ControlStatus
from vendorguard.models.run import AssessmentResult
from vendorguard.ui.api_client import ApiClient, UiApiError
from vendorguard.ui.text import plain
from vendorguard.ui.validation import RUN_ID_PATTERN
from vendorguard.ui.views import finding_detail, report_download


def render(client: ApiClient) -> None:
    """Draw the page for the run in ``st.session_state['run_id']`` or one typed in."""
    st.subheader("Findings")
    flash = st.session_state.pop(finding_detail.FLASH, None)
    if flash:
        st.success(flash)
    run_id = st.text_input("Run ID", value=st.session_state.get("run_id", ""))
    if st.button("Load run") and not _load(client, run_id):
        return
    result = st.session_state.get("result")
    if not isinstance(result, AssessmentResult):
        st.caption("Load a finished run to see its findings.")
        return
    _summary(result)
    _findings(client, result)
    report_download.render(client, result.run_id)


def _load(client: ApiClient, run_id: str) -> bool:
    if not RUN_ID_PATTERN.match(run_id):
        st.error("A run ID has letters, digits, '_' and '-' only.")
        return False
    try:
        view = client.get_run(run_id)
    except UiApiError as exc:
        st.error(plain(exc.detail))
        return False
    if view.status != "done" or view.result is None:
        st.info(
            plain(f"This run is {view.status}." + (f" Error: {view.error}" if view.error else ""))
        )
        return False
    st.session_state["result"] = view.result
    st.session_state["run_id"] = run_id
    st.session_state.pop(report_download.KEY, None)  # a report belongs to one run
    return True


def _summary(result: AssessmentResult) -> None:
    score = result.score
    left, middle, right = st.columns(3)
    left.metric("Risk score", f"{score.overall:g} / 100")
    middle.metric("Band", score.band.value)
    right.metric("Inherent risk", result.inherent_risk.tier.value)
    st.text(result.summary)
    st.text(
        "Domain scores: " + ", ".join(f"{k} {v:g}" for k, v in sorted(score.domain_scores.items()))
    )
    for rule in score.triggered_rules:
        st.text(f"Rule: {rule}")
    if result.diff:
        d = result.diff
        st.text(
            f"Since {d.previous_run_id}: score change {d.score_delta:+g}; new gaps "
            f"{', '.join(d.new_gaps) or 'none'}; resolved {', '.join(d.resolved_gaps) or 'none'}."
        )


def _findings(client: ApiClient, result: AssessmentResult) -> None:
    wanted = st.multiselect(
        "Show statuses", [s.value for s in ControlStatus], default=[s.value for s in ControlStatus]
    )
    rows = [f for f in result.findings if f.effective_status.value in wanted]
    st.dataframe(
        [
            {
                "control": f.control_id,
                "status": f.effective_status.value,
                "system status": f.status.value,
                "overridden": f.override is not None,
                "quotes": len([c for c in f.citations if c.valid]),
            }
            for f in rows
        ],
        hide_index=True,
        width="stretch",
    )
    for finding in rows:
        with st.expander(f"{plain(finding.control_id)}: {finding.effective_status.value}"):
            finding_detail.render(client, result.run_id, finding)


__all__ = ["render"]
