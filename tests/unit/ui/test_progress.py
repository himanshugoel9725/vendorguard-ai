"""wait_for_run: polls at the interval, stops on done/failed, gives up after the timeout."""

import pytest

from vendorguard.ui.api_client import RunView, UiApiError
from vendorguard.ui.progress import wait_for_run


class Scripted:
    def __init__(self, phases: list[str]) -> None:
        self.phases = phases
        self.calls = 0

    def get_run(self, run_id: str) -> RunView:
        phase = self.phases[min(self.calls, len(self.phases) - 1)]
        self.calls += 1
        return RunView(run_id=run_id, status=phase)  # type: ignore[arg-type]


def _wait(client: Scripted, timeout: float = 100.0) -> tuple[RunView, list[float], list[str]]:
    now = [0.0]
    sleeps: list[float] = []
    ticks: list[str] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    view = wait_for_run(
        client,  # type: ignore[arg-type]
        "run_1",
        interval_s=3.0,
        timeout_s=timeout,
        sleep=sleep,
        clock=lambda: now[0],
        on_tick=lambda v: ticks.append(v.status),
    )
    return view, sleeps, ticks


def test_polls_until_done_at_the_configured_interval() -> None:
    view, sleeps, ticks = _wait(Scripted(["queued", "running", "running", "done"]))
    assert view.status == "done" and sleeps == [3.0, 3.0, 3.0]
    assert ticks == ["queued", "running", "running", "done"]


def test_a_failed_run_ends_the_wait() -> None:
    view, sleeps, _ = _wait(Scripted(["running", "failed"]))
    assert view.status == "failed" and sleeps == [3.0]


def test_a_run_that_never_finishes_times_out_without_stopping_it() -> None:
    client = Scripted(["running"])
    with pytest.raises(UiApiError, match="still running"):
        _wait(client, timeout=10.0)
    assert client.calls == 5  # t = 0, 3, 6, 9, 12: the fifth poll sees the timeout


def test_an_api_error_while_polling_propagates() -> None:
    class Broken:
        def get_run(self, run_id: str) -> RunView:
            raise UiApiError(404, "no such assessment")

    with pytest.raises(UiApiError, match="no such assessment"):
        _wait(Broken())  # type: ignore[arg-type]


def test_rate_limiting_is_waited_out_not_fatal() -> None:
    class Limited:
        def __init__(self) -> None:
            self.calls = 0

        def get_run(self, run_id: str) -> RunView:
            self.calls += 1
            if self.calls <= 2:
                raise UiApiError(429, "too many requests")
            return RunView(run_id=run_id, status="done")

    client = Limited()
    view, sleeps, _ = _wait(client)  # type: ignore[arg-type]
    assert view.status == "done" and sleeps == [3.0, 3.0] and client.calls == 3


def test_endless_rate_limiting_still_ends_at_the_timeout() -> None:
    class Always429:
        def get_run(self, run_id: str) -> RunView:
            raise UiApiError(429, "too many requests")

    with pytest.raises(UiApiError) as info:
        _wait(Always429(), timeout=10.0)  # type: ignore[arg-type]
    assert info.value.status == 429
