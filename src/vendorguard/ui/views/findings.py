"""Page 2: the findings of a run, their evidence, analyst overrides and report downloads."""

import streamlit as st

from vendorguard.models.finding import ControlFinding, ControlStatus, DraftStatus
from vendorguard.models.run import AssessmentResult
from vendorguard.ui.api_client import ApiClient, UiApiError
from vendorguard.ui.validation import RUN_ID_PATTERN

REPORT_TYPES = {"html": "text/html", "md": "text/markdown", "json": "application/json"}


def render(client: ApiClient) -> None:
    """Draw the page for the run in ``st.session_state['run_id']`` or one typed in."""
    st.subheader("Findings")
    run_id = st.text_input("Run ID", value=st.session_state.get("run_id", ""))
    if st.button("Load run") and not _load(client, run_id):
        return
    result = st.session_state.get("result")
    if not isinstance(result, AssessmentResult):
        st.caption("Load a finished run to see its findings.")
        return
    _summary(result)
    _findings(client, result)
    _downloads(client, result.run_id)


def _load(client: ApiClient, run_id: str) -> bool:
    if not RUN_ID_PATTERN.match(run_id):
        st.error("A run ID has letters, digits, '_' and '-' only.")
        return False
    try:
        view = client.get_run(run_id)
    except UiApiError as exc:
        st.error(exc.detail)
        return False
    if view.status != "done" or view.result is None:
        st.info(f"This run is {view.status}." + (f" Error: {view.error}" if view.error else ""))
        return False
    st.session_state["result"] = view.result
    st.session_state["run_id"] = run_id
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
        st.warning(rule)
    if result.diff:
        d = result.diff
        st.text(
            f"Since {d.previous_run_id}: score change {d.score_delta:+g}; new gaps "
            f"{', '.join(d.new_gaps) or 'none'}; resolved {', '.join(d.resolved_gaps) or 'none'}."
        )


def _findings(client: ApiClient, result: AssessmentResult) -> None:
    wanted = st.multiselect(
        "Show statuses",
        [s.value for s in ControlStatus],
        default=[s.value for s in ControlStatus],
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
        use_container_width=True,
    )
    for finding in rows:
        with st.expander(f"{finding.control_id}: {finding.effective_status.value}"):
            _detail(client, result.run_id, finding)


def _detail(client: ApiClient, run_id: str, finding: ControlFinding) -> None:
    st.text(finding.rationale)
    for citation in finding.citations:
        if citation.valid:
            st.code(citation.quote, language=None)
            st.caption(f"page {citation.page}" if citation.page else "page unknown")
    if finding.override:
        o = finding.override
        st.text(f"Overridden by {o.analyst} to {o.new_status.value}: {o.reason}")
    with st.form(f"override-{finding.control_id}"):
        status = st.selectbox(
            "New status", [s.value for s in DraftStatus], key=f"s-{finding.control_id}"
        )
        reason = st.text_area("Reason", key=f"r-{finding.control_id}")
        analyst = st.text_input("Your name", key=f"a-{finding.control_id}")
        if st.form_submit_button("Record decision"):
            _override(client, run_id, finding.control_id, DraftStatus(status), reason, analyst)


def _override(
    client: ApiClient, run_id: str, control_id: str, status: DraftStatus, reason: str, analyst: str
) -> None:
    if not reason.strip() or not analyst.strip():
        st.error("A reason and your name are required.")
        return
    try:
        outcome = client.override(run_id, control_id, status, reason.strip(), analyst.strip())
        view = client.get_run(run_id)
    except UiApiError as exc:
        st.error(exc.detail)
        return
    if view.result is not None:
        st.session_state["result"] = view.result
    st.success(f"Recorded. New risk score {outcome.score.overall:g} ({outcome.score.band.value}).")


def _downloads(client: ApiClient, run_id: str) -> None:
    st.markdown("**Report**")
    fmt = st.radio("Format", list(REPORT_TYPES), horizontal=True)
    if st.button("Prepare download"):
        try:
            st.session_state["report"] = (fmt, client.get_report(run_id, fmt))  # type: ignore[arg-type]
        except UiApiError as exc:
            st.error(exc.detail)
            return
    prepared = st.session_state.get("report")
    if prepared:
        kind, data = prepared
        st.download_button(
            f"Download {kind} report", data, f"report-{run_id}.{kind}", REPORT_TYPES[kind]
        )


__all__ = ["render"]
