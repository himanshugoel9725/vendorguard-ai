"""Shared HTTP helper: retry rules and Retry-After handling."""

import httpx
import pytest
import respx

from vendorguard.errors import LLMError
from vendorguard.providers.llm._http import post_json, retry_after_seconds

URL = "http://host/x"


def _post(client: httpx.Client, **kw: object) -> httpx.Response:
    params: dict[str, object] = {
        "label": "Test", "max_retries": 2, "backoff_s": 0.0, "max_wait_s": 5.0,
    }  # fmt: skip
    return post_json(client, URL, {"a": 1}, **{**params, **kw})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("3", 3.0),
        ("0.5", 0.5),
        ("0", 0.0),
        ("-2", None),
        ("soon", None),
        ("Wed, 21 Oct 2026 07:28:00 GMT", None),
    ],
)
def test_retry_after_seconds(header: str, expected: float | None) -> None:
    assert retry_after_seconds(httpx.Response(429, headers={"retry-after": header})) == expected
    assert retry_after_seconds(httpx.Response(429)) is None


@respx.mock
def test_statuses_below_500_are_returned_to_the_caller() -> None:
    for status in (200, 400, 404, 429):
        respx.post(URL).mock(return_value=httpx.Response(status))
        assert _post(httpx.Client()).status_code == status  # 429 is only retried when asked


@respx.mock
def test_429_is_retried_only_when_listed() -> None:
    route = respx.post(URL).mock(side_effect=[httpx.Response(429), httpx.Response(200)])
    assert _post(httpx.Client(), retry_statuses=frozenset({429})).status_code == 200
    assert route.call_count == 2


@respx.mock
def test_5xx_is_always_retried_and_headers_are_sent() -> None:
    route = respx.post(URL).mock(side_effect=[httpx.Response(500), httpx.Response(200)])
    _post(httpx.Client(), headers={"X-Test": "1"})
    assert route.calls[0].request.headers["x-test"] == "1" and route.call_count == 2


@respx.mock
def test_the_wait_is_the_longer_of_the_doubling_backoff_and_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[float] = []
    monkeypatch.setattr("tenacity.nap.time.sleep", waits.append)
    respx.post(URL).mock(
        side_effect=[
            httpx.Response(503, headers={"retry-after": "2"}),
            httpx.Response(503, headers={"retry-after": "0.5"}),
            httpx.Response(200),
        ]
    )
    _post(httpx.Client(), backoff_s=1.0, max_retries=2)
    assert waits == [2.0, 2.0]  # max(1, 2), then max(2, 0.5): the backoff doubled


@respx.mock
def test_the_wait_is_capped_and_an_over_long_retry_after_fails_at_once() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(503, headers={"retry-after": "100"}))
    with pytest.raises(LLMError, match=r"rate limited \(HTTP 503\).*100s.*5s"):
        _post(httpx.Client(), max_wait_s=5.0)
    assert route.call_count == 1


@respx.mock
def test_exhausted_retries_name_the_label_the_attempts_and_the_cause() -> None:
    respx.post(URL).mock(return_value=httpx.Response(502))
    with pytest.raises(LLMError, match=r"Test failed after 3 attempts \(HTTP 502\)"):
        _post(httpx.Client())
    respx.post(URL).mock(side_effect=httpx.ConnectTimeout("t"))
    with pytest.raises(LLMError, match=r"after 3 attempts \(ConnectTimeout\)"):
        _post(httpx.Client())


@respx.mock
def test_other_transport_errors_are_not_retried() -> None:
    route = respx.post(URL).mock(side_effect=httpx.RemoteProtocolError("bad"))
    with pytest.raises(LLMError, match=r"Test request failed \(RemoteProtocolError\)"):
        _post(httpx.Client(), max_retries=5)
    assert route.call_count == 1
