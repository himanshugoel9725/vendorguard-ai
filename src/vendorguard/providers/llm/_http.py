"""Shared HTTP call of the LLM providers: bounded retries, ``Retry-After``, clean errors."""

from collections.abc import Mapping
from typing import Any

import httpx
from tenacity import (
    RetryCallState,
    RetryError,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
)

from vendorguard.errors import LLMError

MAX_ERROR_CHARS = 200
_RETRY_TRANSPORT = (httpx.ConnectError, httpx.ConnectTimeout)


class _Retryable(Exception):
    """An HTTP status that is worth another attempt (5xx, and 429 for hosted providers)."""

    def __init__(self, status: int, retry_after: float | None) -> None:
        super().__init__(f"HTTP {status}")
        self.retry_after = retry_after


class _WaitTooLong(Exception):
    """The server asked for a longer pause than the configured cap."""

    def __init__(self, status: int, seconds: float) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.seconds = seconds


def retry_after_seconds(response: httpx.Response) -> float | None:
    """The ``Retry-After`` header as seconds (dates and junk are ignored)."""
    try:
        value = float(response.headers.get("retry-after", ""))
    except ValueError:
        return None
    return value if value >= 0 else None


def post_json(
    client: httpx.Client,
    url: str,
    body: dict[str, Any],
    *,
    label: str,
    headers: Mapping[str, str] | None = None,
    max_retries: int,
    backoff_s: float,
    max_wait_s: float,
    retry_statuses: frozenset[int] = frozenset(),
) -> httpx.Response:
    """POST ``body`` as JSON; retry connection errors, every 5xx and ``retry_statuses``.

    The pause before a retry is ``backoff_s`` doubled each attempt, or the server's ``Retry-After``
    if that is longer, never more than ``max_wait_s``.
    A ``Retry-After`` above ``max_wait_s`` fails at once. Any other status is returned to the
    caller. Raises LLMError (``label`` names the provider) when the call cannot be completed.
    """

    def attempt() -> httpx.Response:
        response = client.post(url, json=body, headers=headers)
        if response.status_code >= 500 or response.status_code in retry_statuses:
            wait = retry_after_seconds(response)
            if wait is not None and wait > max_wait_s:
                raise _WaitTooLong(response.status_code, wait)
            raise _Retryable(response.status_code, wait)
        return response

    def pause(state: RetryCallState) -> float:
        error = state.outcome.exception() if state.outcome else None
        asked = error.retry_after if isinstance(error, _Retryable) else None
        delay = float(backoff_s * 2 ** (state.attempt_number - 1))  # exponential, no jitter
        return min(max(delay, asked or 0.0), max_wait_s)

    retrying = Retrying(
        stop=stop_after_attempt(max_retries + 1),
        wait=pause,
        retry=retry_if_exception_type((*_RETRY_TRANSPORT, _Retryable)),
        reraise=False,
    )
    try:
        return retrying(attempt)
    except RetryError as exc:
        cause = exc.last_attempt.exception()
        raise LLMError(
            f"{label} failed after {max_retries + 1} attempts ({_describe(cause)})"
        ) from cause
    except _WaitTooLong as exc:
        raise LLMError(
            f"{label} is rate limited (HTTP {exc.status}): it asks to wait "
            f"{exc.seconds:g}s, longer than the {max_wait_s:g}s allowed by llm.max_retry_wait_s"
        ) from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"{label} request failed ({type(exc).__name__})") from exc


def _describe(error: BaseException | None) -> str:
    if isinstance(error, _Retryable):
        return str(error)
    return type(error).__name__


__all__ = ["MAX_ERROR_CHARS", "post_json", "retry_after_seconds"]
