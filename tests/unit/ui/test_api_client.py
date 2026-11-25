"""The UI's API client: routes, validation with the server's models, safe errors (no network)."""

import json

import httpx
import pytest
import respx
from pydantic import SecretStr

from vendorguard.models.finding import DraftStatus
from vendorguard.ui.api_client import ApiClient, UiApiError

BASE = "http://127.0.0.1:8000"
KEY = "k" * 32
FINDING = {
    "control_id": "IAM-02",
    "status": "not_met",
    "citations": [],
    "rationale": "r",
    "trace": [],
    "review_rounds": 0,
}
SCORE = {
    "overall": 30.5,
    "band": "medium",
    "domain_scores": {"Identity": 10.0},
    "triggered_rules": [],
}


@pytest.fixture
def client() -> ApiClient:
    return ApiClient(BASE, SecretStr(KEY), 5.0, 300)


@respx.mock
def test_every_request_carries_the_key_and_start_uploads_multipart(client: ApiClient) -> None:
    route = respx.post(f"{BASE}/v1/assessments").respond(
        202, json={"run_id": "run_abc", "status": "queued", "status_url": "/x"}
    )
    run_id = client.start_assessment("nimbara-hr", [("a.txt", b"hello"), ("b.pdf", b"%PDF-1")])
    assert run_id == "run_abc"
    request = route.calls.last.request
    assert request.headers["x-api-key"] == KEY
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert b'name="vendor_id"' in request.content and b"nimbara-hr" in request.content
    assert request.content.count(b'name="files"') == 2


@respx.mock
def test_get_run_validates_with_the_server_model(client: ApiClient) -> None:
    respx.get(f"{BASE}/v1/assessments/run_1").respond(
        200, json={"run_id": "run_1", "status": "running", "error": None, "result": None}
    )
    view = client.get_run("run_1")
    assert view.status == "running" and view.result is None


@respx.mock
def test_report_override_vendors_history_and_ask(client: ApiClient) -> None:
    respx.get(f"{BASE}/v1/assessments/run_1/report").respond(200, content=b"<html>")
    assert client.get_report("run_1", "html") == b"<html>"
    patch = respx.patch(f"{BASE}/v1/assessments/run_1/findings/IAM-02").respond(
        200, json={"finding": FINDING, "score": SCORE}
    )
    outcome = client.override("run_1", "IAM-02", DraftStatus.MET, "evidence seen", "Ana")
    assert json.loads(patch.calls.last.request.content) == {
        "status": "met",
        "reason": "evidence seen",
        "analyst": "Ana",
    }
    assert outcome.score.overall == 30.5 and outcome.finding.control_id == "IAM-02"
    respx.get(f"{BASE}/v1/vendors").respond(
        200, json=[{"vendor_id": "v", "name": "V Corp", "runs": 2, "latest_band": "low"}]
    )
    assert client.vendors()[0].name == "V Corp"
    respx.get(f"{BASE}/v1/vendors/v/history").respond(
        200,
        json=[
            {
                "run_id": "r",
                "vendor_id": "v",
                "created_at": "2026-01-01T00:00:00Z",
                "overall": 12.0,
                "band": "low",
            }
        ],
    )
    assert client.history("v")[0].overall == 12.0
    respx.post(f"{BASE}/v1/vendors/v/ask").respond(
        200,
        json={
            "text": "IAM-02 is not_met",
            "cited_run_ids": ["r"],
            "cited_control_ids": ["IAM-02"],
            "provider": "local/mock",
        },
    )
    assert client.ask("v", "what?").cited_control_ids == ["IAM-02"]


@pytest.mark.parametrize(
    "bad", ["../vendors", "a/b", "a?x=1", "a#f", "%2e%2e", "a b", "", "x" * 65]
)
def test_a_crafted_id_never_reaches_the_network(client: ApiClient, bad: str) -> None:
    """Every id is checked against the server's pattern before a path is built (audit 12.7, L3)."""
    with respx.mock(assert_all_called=False) as mock:
        for call in (
            lambda: client.history(bad),
            lambda: client.ask(bad, "q"),
            lambda: client.get_run(bad),
            lambda: client.get_report(bad, "html"),
            lambda: client.override(bad, "IAM-02", DraftStatus.MET, "r", "a"),
            lambda: client.override("run_1", bad, DraftStatus.MET, "r", "a"),
        ):
            with pytest.raises(UiApiError, match="invalid identifier"):
                call()
        assert not mock.calls


@respx.mock
@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            httpx.Response(401, json={"detail": "invalid or missing API key"}),
            "invalid or missing API key",
        ),
        (
            httpx.Response(422, json={"detail": [{"loc": ["x"], "msg": "bad id", "type": "v"}]}),
            "bad id",
        ),
        (httpx.Response(404, text="not json"), "HTTP 404"),
        (httpx.Response(500, json={"detail": "x" * 1000}), "x" * 300),
    ],
)
def test_errors_carry_the_apis_message_only(
    client: ApiClient, response: httpx.Response, expected: str
) -> None:
    respx.get(f"{BASE}/v1/vendors").mock(return_value=response)
    with pytest.raises(UiApiError) as info:
        client.vendors()
    assert expected in info.value.detail and len(info.value.detail) <= 300
    assert KEY not in info.value.detail and info.value.status == response.status_code


@respx.mock
def test_unreachable_api_and_bad_answers_never_leak_the_key(client: ApiClient) -> None:
    respx.get(f"{BASE}/v1/vendors").mock(side_effect=httpx.ConnectError("boom " + KEY))
    with pytest.raises(UiApiError) as down:
        client.vendors()
    assert (
        down.value.status == 0
        and KEY not in down.value.detail
        and "cannot reach" in down.value.detail
    )
    respx.get(f"{BASE}/v1/assessments/r").respond(200, json={"nonsense": True})
    with pytest.raises(UiApiError, match="does not understand"):
        client.get_run("r")
    respx.get(f"{BASE}/v1/assessments/s").respond(200, text="<html>not json</html>")
    with pytest.raises(UiApiError, match="unreadable"):
        client.get_run("s")


@respx.mock
def test_health_needs_no_key_and_never_raises(client: ApiClient) -> None:
    route = respx.get(f"{BASE}/health").respond(200, json={"status": "ok"})
    assert client.health() is True and "x-api-key" not in route.calls.last.request.headers
    respx.get(f"{BASE}/health").mock(side_effect=httpx.ConnectError("down"))
    assert client.health() is False
    respx.get(f"{BASE}/health").respond(503)
    assert client.health() is False


@respx.mock
def test_the_error_length_limit_is_a_setting() -> None:
    short = ApiClient(BASE, SecretStr(KEY), 5.0, 10)
    respx.get(f"{BASE}/v1/vendors").respond(500, json={"detail": "y" * 100})
    with pytest.raises(UiApiError) as info:
        short.vendors()
    assert info.value.detail == "y" * 10


@respx.mock
def test_a_redirect_is_never_followed_with_the_key(client: ApiClient) -> None:
    respx.get(f"{BASE}/v1/vendors").respond(302, headers={"location": "http://evil.test/steal"})
    with pytest.raises(UiApiError):
        client.vendors()
    assert len(respx.calls) == 1  # only the first request was made
