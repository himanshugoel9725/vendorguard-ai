"""Waiting for a running assessment: poll at the configured interval, give up after the timeout."""

from collections.abc import Callable

from vendorguard.ui.api_client import ApiClient, RunView, UiApiError

TERMINAL = ("done", "failed")
RATE_LIMITED = 429


def wait_for_run(
    client: ApiClient,
    run_id: str,
    *,
    interval_s: float,
    timeout_s: float,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    on_tick: Callable[[RunView], None] | None = None,
) -> RunView:
    """Poll ``run_id`` until it is ``done`` or ``failed``. The run keeps going on the server if
    the timeout is reached; that raises ``UiApiError`` so the page can say so."""
    started = clock()
    while True:
        try:
            view = client.get_run(run_id)
        except UiApiError as exc:
            if exc.status != RATE_LIMITED or clock() - started >= timeout_s:
                raise
            sleep(interval_s)  # the API asked us to slow down: wait and ask again
            continue
        if on_tick:
            on_tick(view)
        if view.status in TERMINAL:
            return view
        if clock() - started >= timeout_s:
            raise UiApiError(0, "still running: stopped waiting, check again later")
        sleep(interval_s)


__all__ = ["TERMINAL", "wait_for_run"]
