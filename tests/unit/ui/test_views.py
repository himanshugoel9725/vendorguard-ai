"""The three pages, driven with Streamlit's AppTest and a fake API client (no network)."""

from datetime import UTC, datetime
from typing import Any

from streamlit.testing.v1 import AppTest

from vendorguard.models.finding import ControlFinding, ControlStatus, DraftStatus
from vendorguard.models.run import Answer, AssessmentSummary, VendorSummary
from vendorguard.ui.api_client import OverrideOutcome, RunView, UiApiError

TIMEOUT = 60  # the first table render imports the data libraries


def _result_dict() -> dict[str, Any]:
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
        "run_id": "run_1",
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
        self, *, fail: UiApiError | None = None, phases: tuple[str, ...] = ("done",)
    ) -> None:
        from vendorguard.models.run import AssessmentResult

        self.calls: list[tuple[Any, ...]] = []
        self.fail = fail
        self.phases = list(phases)
        self.result = AssessmentResult.model_validate(_result_dict())

    def _maybe_fail(self) -> None:
        if self.fail:
            raise self.fail

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
            status=phase,
            error=None if phase != "failed" else "BoomError",
            result=self.result if done else None,
        )  # type: ignore[arg-type]

    def get_report(self, run_id: str, fmt: str) -> bytes:
        self.calls.append(("report", run_id, fmt))
        return b"report-bytes"

    def override(
        self, run_id: str, control_id: str, status: DraftStatus, reason: str, analyst: str
    ) -> Any:
        self._maybe_fail()
        self.calls.append(("override", control_id, status.value, reason, analyst))
        return OverrideOutcome(
            finding=ControlFinding(
                control_id=control_id,
                status=ControlStatus.MET,
                citations=[],
                rationale="r",
                trace=[],
                review_rounds=0,
            ),
            score=self.result.score,
        )

    def vendors(self) -> list[VendorSummary]:
        self._maybe_fail()
        return [VendorSummary(vendor_id="v", name="V Corp", runs=2, latest_band="low")]  # type: ignore[arg-type]

    def history(self, vendor_id: str) -> list[AssessmentSummary]:
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


def _assess_script(client, ui):  # type: ignore[no-untyped-def]  # source only: no annotations
    from vendorguard.ui.views import assess

    assess.render(client, ui, sleep=lambda s: None)


def _findings_script(client):  # type: ignore[no-untyped-def]
    from vendorguard.ui.views import findings

    findings.render(client)


def _history_script(client):  # type: ignore[no-untyped-def]
    from vendorguard.ui.views import history

    history.render(client)


def _texts(at: AppTest, kind: str) -> list[str]:
    return [str(e.value) for e in getattr(at, kind)]


# --- Assess -------------------------------------------------------------------------------------


def test_assess_refuses_a_bad_vendor_id_and_missing_files() -> None:
    fake = FakeClient()
    at = AppTest.from_function(
        _assess_script, args=(fake, _ui_settings()), default_timeout=TIMEOUT
    ).run()
    at.text_input[0].set_value("../evil")
    at.button[0].click().run()
    assert "letters, digits" in _texts(at, "error")[0] and not fake.calls
    at.text_input[0].set_value("nimbara-hr")
    at.button[0].click().run()
    assert "at least one document" in _texts(at, "error")[0] and not fake.calls


def test_assess_shows_an_api_refusal_as_its_own_message() -> None:
    fake = FakeClient(fail=UiApiError(415, "unsupported file type"))
    at = AppTest.from_function(
        _assess_script, args=(fake, _ui_settings()), default_timeout=TIMEOUT
    ).run()
    at.text_input[0].set_value("v")
    at.file_uploader[0].upload("a.txt", b"hello")  # type: ignore[attr-defined]
    at.button[0].click().run()
    assert _texts(at, "error") == ["unsupported file type"]


def test_assess_starts_a_run_and_reports_the_result() -> None:
    fake = FakeClient(phases=("queued", "running", "done"))
    at = AppTest.from_function(
        _assess_script, args=(fake, _ui_settings()), default_timeout=TIMEOUT
    ).run()
    at.text_input[0].set_value("nimbara-hr")
    at.file_uploader[0].upload("a.txt", b"hello")  # type: ignore[attr-defined]
    at.button[0].click().run()
    assert not at.exception
    assert fake.calls[0] == ("start", "nimbara-hr", [("a.txt", b"hello")])
    assert at.session_state["run_id"] == "run_1"
    assert any("41.5" in t for t in _texts(at, "text"))


def test_assess_reports_a_failed_run() -> None:
    fake = FakeClient(phases=("failed",))
    at = AppTest.from_function(
        _assess_script, args=(fake, _ui_settings()), default_timeout=TIMEOUT
    ).run()
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
    # model/document text is shown verbatim as text/code, never rendered as Markdown or HTML
    assert "**MFA** [x](http://e.com)" in texts
    assert any("<script>alert(1)</script>" in str(c.value) for c in at.code)
    assert [m.label for m in at.metric] == ["Risk score", "Band", "Inherent risk"]
    assert at.warning[0].value == "rule fired"


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


def test_override_needs_a_reason_and_a_name_then_is_sent() -> None:
    fake = FakeClient()
    at = _loaded_findings(fake)
    at.get("form_submit_button")[0].click().run()  # nothing filled in
    assert "required" in _texts(at, "error")[0] and not any(c[0] == "override" for c in fake.calls)
    at.text_area[0].set_value("  restore tests seen  ")
    at.text_input[1].set_value(" Ana ")
    at.get("form_submit_button")[0].click().run()
    assert ("override", "IAM-02", "met", "restore tests seen", "Ana") in fake.calls or any(
        c[0] == "override" and c[3] == "restore tests seen" and c[4] == "Ana" for c in fake.calls
    )
    assert any("Recorded" in str(s.value) for s in at.success)


def test_findings_download_is_prepared_on_request_only() -> None:
    fake = FakeClient()
    at = _loaded_findings(fake)
    assert not any(c[0] == "report" for c in fake.calls)
    prepare = [b for b in at.button if b.label == "Prepare download"][0]
    prepare.click().run()
    assert ("report", "run_1", "html") in fake.calls
    assert at.get("download_button")


def test_findings_show_an_api_error_from_load() -> None:
    fake = FakeClient(fail=UiApiError(404, "no such assessment"))
    at = AppTest.from_function(_findings_script, args=(fake,), default_timeout=TIMEOUT).run()
    at.text_input[0].set_value("run_9")
    at.button[0].click().run()
    assert _texts(at, "error") == ["no such assessment"]


# --- History and Ask ----------------------------------------------------------------------------


def test_history_lists_vendors_and_answers_a_question() -> None:
    fake = FakeClient()
    at = AppTest.from_function(_history_script, args=(fake,), default_timeout=TIMEOUT).run()
    assert not at.exception and len(at.dataframe) == 2
    at.text_input[0].set_value("What changed?")
    at.get("form_submit_button")[0].click().run()
    assert ("ask", "v", "What changed?") in fake.calls
    assert "IAM-02 is met" in _texts(at, "text")


def test_history_empty_question_and_api_errors() -> None:
    at = AppTest.from_function(_history_script, args=(FakeClient(),), default_timeout=TIMEOUT).run()
    at.get("form_submit_button")[0].click().run()
    assert _texts(at, "error") == ["Type a question."]
    down = FakeClient(fail=UiApiError(0, "cannot reach the API at http://fake"))
    at2 = AppTest.from_function(_history_script, args=(down,), default_timeout=TIMEOUT).run()
    assert "cannot reach" in _texts(at2, "error")[0]
