"""The three pages, driven with Streamlit's AppTest and a fake API client (no network)."""

from datetime import UTC, datetime
from typing import Any

from streamlit.testing.v1 import AppTest

from vendorguard.models.finding import ControlFinding, ControlStatus, DraftStatus
from vendorguard.models.run import Answer, AssessmentResult, AssessmentSummary, VendorSummary
from vendorguard.ui.api_client import OverrideOutcome, RunView, UiApiError
from vendorguard.ui.limits import UploadLimits
from vendorguard.ui.text import plain

TIMEOUT = 60  # the first table render imports the data libraries
LIMITS = UploadLimits(extensions=("pdf", "txt", "md"), max_file_mb=20, max_files=5)
MB = 1024 * 1024


def _result_dict(run_id: str = "run_1") -> dict[str, Any]:
    quote = {
        "chunk_id": "c1",
        "quote": "<script>alert(1)</script> We use MFA.",
        "doc_id": "d1",
        "page": 3,
        "valid": True,
        "similarity": 1.0,
        "relocated": False,
    }
    findings = [
        {
            "control_id": "DAT-01",
            "status": "no_evidence",
            "citations": [],
            "rationale": "none",
            "trace": [],
            "review_rounds": 0,
        },
        {
            "control_id": "IAM-02",
            "status": "met",
            "citations": [quote],
            "rationale": "**MFA** [x](http://e.com)",
            "trace": [],
            "review_rounds": 0,
        },
    ]
    return {
        "run_id": run_id,
        "vendor_id": "v",
        "created_at": "2026-01-01T00:00:00Z",
        "profile": {
            "vendor_name": "V Corp",
            "services": [],
            "hosting": [],
            "certifications": [],
            "subprocessors": [],
            "data_categories": [],
            "report_period": None,
        },
        "inherent_risk": {"tier": "medium", "reasons": ["r"]},
        "findings": findings,
        "score": {
            "overall": 41.5,
            "band": "medium",
            "domain_scores": {"Identity": 10.0},
            "triggered_rules": ["rule fired"],
        },
        "diff": {
            "previous_run_id": "run_0",
            "new_gaps": ["DAT-01"],
            "resolved_gaps": [],
            "changed": [],
            "score_delta": 2.5,
        },
        "summary": "Summary text",
        "cost": {
            "llm_calls": 0,
            "cache_hits": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "decider_calls": 0,
            "usd": 0.0,
        },
    }


class FakeClient:
    """Stands in for ApiClient: records calls, returns canned answers, can be told to fail."""

    base_url = "http://fake"

    def __init__(
        self,
        *,
        fail: UiApiError | None = None,
        phases: tuple[str, ...] = ("done",),
        vendor_name: str = "V Corp",
    ) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.fail = fail
        self.phases = list(phases)
        self.vendor_name = vendor_name
        self.score_overall = 41.5

    def _maybe_fail(self) -> None:
        if self.fail:
            raise self.fail

    def _result(self, run_id: str = "run_1") -> AssessmentResult:
        data = _result_dict(run_id)
        data["score"]["overall"] = self.score_overall
        return AssessmentResult.model_validate(data)

    def count(self, name: str) -> int:
        return sum(1 for c in self.calls if c[0] == name)

    def start_assessment(self, vendor_id: str, files: Any) -> str:
        self._maybe_fail()
        self.calls.append(("start", vendor_id, [(n, d) for n, d in files]))
        return "run_1"

    def get_run(self, run_id: str) -> RunView:
        self._maybe_fail()
        phase = self.phases.pop(0) if len(self.phases) > 1 else self.phases[0]
        done = phase == "done"
        return RunView(
            run_id=run_id,
            status=phase,  # type: ignore[arg-type]
            error="BoomError" if phase == "failed" else None,
            result=self._result(run_id) if done else None,
        )

    def get_report(self, run_id: str, fmt: str) -> bytes:
        self.calls.append(("report", run_id, fmt))
        return b"report-bytes"

    def override(
        self, run_id: str, control_id: str, status: DraftStatus, reason: str, analyst: str
    ) -> Any:
        self._maybe_fail()
        self.calls.append(("override", control_id, status.value, reason, analyst))
        self.score_overall = 28.0  # the server recomputes the score
        return OverrideOutcome(
            finding=ControlFinding(
                control_id=control_id,
                status=ControlStatus.MET,
                citations=[],
                rationale="r",
                trace=[],
                review_rounds=0,
            ),
            score=self._result(run_id).score,
        )

    def vendors(self) -> list[VendorSummary]:
        self._maybe_fail()
        self.calls.append(("vendors",))
        return [VendorSummary(vendor_id="v", name=self.vendor_name, runs=2, latest_band="low")]  # type: ignore[arg-type]

    def history(self, vendor_id: str) -> list[AssessmentSummary]:
        self.calls.append(("history", vendor_id))
        row = AssessmentSummary(
            run_id="run_1",
            vendor_id=vendor_id,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            overall=12.0,
            band="low",  # type: ignore[arg-type]
        )
        return [row]

    def ask(self, vendor_id: str, question: str) -> Answer:
        self._maybe_fail()
        self.calls.append(("ask", vendor_id, question))
        return Answer(
            text="IAM-02 is met",
            cited_run_ids=["run_1"],
            cited_control_ids=["IAM-02"],
            provider="local/mock",
        )


def _ui_settings() -> Any:
    from vendorguard.config import load_settings

    return load_settings(env_file=None).ui


def _assess_script(client, ui, limits):  # type: ignore[no-untyped-def]  # source only: no annotations
    from vendorguard.ui.views import assess

    assess.render(client, ui, limits, sleep=lambda s: None)


def _findings_script(client):  # type: ignore[no-untyped-def]
    from vendorguard.ui.views import findings

    findings.render(client)


def _history_script(client, ui):  # type: ignore[no-untyped-def]
    from vendorguard.ui.views import history

    history.render(client, ui)


def _texts(at: AppTest, kind: str) -> list[str]:
    return [str(e.value) for e in getattr(at, kind)]


def _assess(fake: FakeClient) -> AppTest:
    args = (fake, _ui_settings(), LIMITS)
    return AppTest.from_function(_assess_script, args=args, default_timeout=TIMEOUT).run()


# --- Assess -------------------------------------------------------------------------------------


def test_assess_refuses_a_bad_vendor_id_and_missing_files() -> None:
    fake = FakeClient()
    at = _assess(fake)
    at.text_input[0].set_value("../evil")
    at.button[0].click().run()
    assert "letters, digits" in _texts(at, "error")[0] and not fake.calls
    at.text_input[0].set_value("nimbara-hr")
    at.button[0].click().run()
    assert "at least one document" in _texts(at, "error")[0] and not fake.calls


def test_assess_checks_file_size_before_reading_or_sending_anything() -> None:
    fake = FakeClient()
    at = _assess(fake)
    at.text_input[0].set_value("v")
    at.file_uploader[0].upload("big.txt", b"x" * (21 * MB))  # type: ignore[attr-defined]
    at.button[0].click().run()
    assert "at most 20 MB" in _texts(at, "error")[0] and not fake.calls


def test_assess_shows_an_api_refusal_escaped_as_plain_text() -> None:
    hostile = "unsupported [click](http://evil.test) ![x](http://evil.test/p.png)"
    fake = FakeClient(fail=UiApiError(415, hostile))
    at = _assess(fake)
    at.text_input[0].set_value("v")
    at.file_uploader[0].upload("a.txt", b"hello")  # type: ignore[attr-defined]
    at.button[0].click().run()
    assert _texts(at, "error") == [plain(hostile)]


def test_assess_starts_a_run_and_reports_the_result() -> None:
    fake = FakeClient(phases=("queued", "running", "done"))
    at = _assess(fake)
    at.text_input[0].set_value("nimbara-hr")
    at.file_uploader[0].upload("a.txt", b"hello")  # type: ignore[attr-defined]
    at.button[0].click().run()
    assert not at.exception
    assert fake.calls[0] == ("start", "nimbara-hr", [("a.txt", b"hello")])
    assert at.session_state["run_id"] == "run_1" and "pending_run" not in at.session_state
    assert any("41.5" in t for t in _texts(at, "text"))


def test_a_rerun_while_waiting_resumes_the_wait_instead_of_losing_the_run() -> None:
    """Audit 12.7: any click reruns the script; the pending run must be picked up again."""
    fake = FakeClient(phases=("running", "done"))
    at = AppTest.from_function(
        _assess_script, args=(fake, _ui_settings(), LIMITS), default_timeout=TIMEOUT
    )
    at.session_state["pending_run"] = "run_1"
    at.run()
    assert not at.exception and fake.count("start") == 0  # nothing was uploaded again
    assert any("41.5" in t for t in _texts(at, "text")) and "pending_run" not in at.session_state


def test_assess_reports_a_failed_run() -> None:
    fake = FakeClient(phases=("failed",))
    at = _assess(fake)
    at.text_input[0].set_value("v")
    at.file_uploader[0].upload("a.txt", b"x")  # type: ignore[attr-defined]
    at.button[0].click().run()
    assert any("BoomError" in t for t in _texts(at, "text"))


# --- Findings -----------------------------------------------------------------------------------


def _loaded_findings(fake: FakeClient) -> AppTest:
    at = AppTest.from_function(_findings_script, args=(fake,), default_timeout=TIMEOUT).run()
    at.text_input[0].set_value("run_1")
    at.button[0].click().run()
    return at


def test_findings_load_shows_summary_evidence_and_diff_as_plain_text() -> None:
    at = _loaded_findings(FakeClient())
    assert not at.exception
    texts = _texts(at, "text")
    assert "Summary text" in texts and any("Since run_0" in t for t in texts)
    assert "Rule: rule fired" in texts
    # model/document text is shown verbatim as text/code, never rendered as Markdown or HTML
    assert "**MFA** [x](http://e.com)" in texts
    assert any("<script>alert(1)</script>" in str(c.value) for c in at.code)
    assert [m.label for m in at.metric] == ["Risk score", "Band", "Inherent risk"]


def test_findings_rejects_a_bad_run_id_and_unfinished_runs() -> None:
    at = AppTest.from_function(
        _findings_script, args=(FakeClient(),), default_timeout=TIMEOUT
    ).run()
    at.text_input[0].set_value("../x")
    at.button[0].click().run()
    assert "letters, digits" in _texts(at, "error")[0]
    pending = FakeClient(phases=("running",))
    at2 = AppTest.from_function(_findings_script, args=(pending,), default_timeout=TIMEOUT).run()
    at2.text_input[0].set_value("run_1")
    at2.button[0].click().run()
    assert any("running" in str(i.value) for i in at2.info)


def test_override_needs_a_status_a_reason_and_a_name() -> None:
    fake = FakeClient()
    at = _loaded_findings(fake)
    at.get("form_submit_button")[0].click().run()  # DAT-01 form, nothing chosen
    assert "all three are required" in _texts(at, "error")[0] and fake.count("override") == 0
    at.text_area[0].set_value("reason only")
    at.get("form_submit_button")[0].click().run()
    assert fake.count("override") == 0  # still no status and no name


def test_override_is_sent_trimmed_and_the_screen_shows_the_new_score() -> None:
    """Audit 12.7: after 'Record decision' the metrics must show the recomputed score at once."""
    fake = FakeClient()
    at = _loaded_findings(fake)
    assert at.metric[0].value == "41.5 / 100"
    at.selectbox(key="s-DAT-01").select("met")
    at.text_area(key="r-DAT-01").set_value("  restore tests seen  ")
    at.text_input(key="a-DAT-01").set_value(" Ana ")
    at.get("form_submit_button")[0].click().run()
    assert ("override", "DAT-01", "met", "restore tests seen", "Ana") in fake.calls
    assert at.metric[0].value == "28 / 100"  # redrawn, not stale
    assert any("Recorded" in str(s.value) for s in at.success)


def test_a_prepared_report_is_never_offered_for_another_run() -> None:
    """Audit 12.7: a report prepared for run A must not be downloadable under run B."""
    fake = FakeClient()
    at = _loaded_findings(fake)
    assert not any(c[0] == "report" for c in fake.calls)  # nothing is fetched until asked
    [b for b in at.button if b.label == "Prepare download"][0].click().run()
    assert ("report", "run_1", "html") in fake.calls and at.get("download_button")
    at.text_input[0].set_value("run_2")
    [b for b in at.button if b.label == "Load run"][0].click().run()
    assert at.session_state["run_id"] == "run_2" and not at.get("download_button")


def test_findings_show_an_api_error_from_load() -> None:
    fake = FakeClient(fail=UiApiError(404, "no such assessment"))
    at = AppTest.from_function(_findings_script, args=(fake,), default_timeout=TIMEOUT).run()
    at.text_input[0].set_value("run_9")
    at.button[0].click().run()
    assert _texts(at, "error") == [plain("no such assessment")]


# --- History and Ask ----------------------------------------------------------------------------


def _history(fake: FakeClient) -> AppTest:
    args = (fake, _ui_settings())
    return AppTest.from_function(_history_script, args=args, default_timeout=TIMEOUT).run()


def test_history_lists_vendors_and_answers_a_question() -> None:
    fake = FakeClient()
    at = _history(fake)
    assert not at.exception and len(at.dataframe) == 2
    at.text_input[0].set_value("What changed?")
    at.get("form_submit_button")[0].click().run()
    assert ("ask", "v", "What changed?") in fake.calls
    assert "IAM-02 is met" in _texts(at, "text")


def test_lists_are_fetched_once_per_refresh_interval_not_on_every_rerun() -> None:
    """Audit 12.7: every widget click reruns the page; it must not hit the API's rate limit."""
    fake = FakeClient()
    at = _history(fake)
    at.run().run()
    assert fake.count("vendors") == 1 and fake.count("history") == 1
    [b for b in at.button if b.label == "Refresh"][0].click().run()
    assert fake.count("vendors") == 2


def test_a_vendor_name_that_looks_like_a_formula_is_defused_in_the_table() -> None:
    at = _history(FakeClient(vendor_name='=HYPERLINK("http://evil.test","x")'))
    cells = at.dataframe[0].value.to_dict("records")
    assert cells[0]["name"].startswith("'=HYPERLINK")


def test_history_empty_question_and_api_errors() -> None:
    at = _history(FakeClient())
    at.get("form_submit_button")[0].click().run()
    assert _texts(at, "error") == ["Type a question."]
    down = FakeClient(fail=UiApiError(0, "cannot reach the API at http://fake"))
    at2 = _history(down)
    assert "cannot reach" in _texts(at2, "error")[0]
