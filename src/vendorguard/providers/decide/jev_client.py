"""HTTP client of the Jev decision model (TypeSafe System One by default, or OpenRouter alpha).

Only transport lives here: auth, timeout, retries, payload and response mapping. ``POST
{base_url}{path}`` with ``{model, state, questions}`` and a Bearer key. TypeSafe (read from
docs.typesafe.ai, 2026-11-25): ``https://api.typesafe.ai`` + ``/v1/systemone``, model
``jev-latest``.
OpenRouter (alpha): ``https://openrouter.ai/api/alpha`` + ``/decisions``. A ``noul`` (yes/no)
question is answered ``{"type": "noul", "noul": <probability of yes>}`` and the reply carries
``usage.input_tokens`` / ``output_tokens`` in both. Every failure is a ``DeciderError``; no message
ever contains server text for an authentication failure or the key.
"""

from collections.abc import Mapping
from typing import Any

import httpx

from vendorguard.config_models.providers import JevSettings, LlmSettings
from vendorguard.errors import ConfigError, DeciderError, LLMError
from vendorguard.logging_setup import RedactingFilter
from vendorguard.models.llm import Usage
from vendorguard.providers.llm._http import MAX_ERROR_CHARS, post_json

AUTH_STATUSES = frozenset({401, 402, 403})
RATE_LIMIT_STATUS = 429
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class JevClient:
    """Asks yes/no questions about a piece of state; returns each answer as P(yes)."""

    def __init__(
        self, jev: JevSettings, llm: LlmSettings, client: httpx.Client | None = None
    ) -> None:
        self._key = jev.api_key.get_secret_value()
        if not self._key:
            raise ConfigError("no API key for decision.jev: set VG_DECISION__JEV__API_KEY in .env")
        url = httpx.URL(jev.base_url)
        if url.scheme != "https" and url.host not in LOOPBACK_HOSTS:
            raise ConfigError(
                "decision.jev.base_url must use https because every request carries the key"
            )
        self.model = jev.model
        self._llm = llm
        self._url = f"{jev.base_url.rstrip('/')}/{jev.path.lstrip('/')}"
        self._client = client or httpx.Client(timeout=jev.timeout_s)
        self._redact = RedactingFilter([self._key]).redact

    def close(self) -> None:
        """Release the HTTP connection pool."""
        self._client.close()

    def ask(
        self, state: Mapping[str, Any], questions: Mapping[str, Any]
    ) -> tuple[dict[str, float], Usage]:
        """Send the questions; return P(yes) per question name and the tokens used."""
        body = {"model": self.model, "state": state, "questions": questions}
        try:
            response = post_json(
                self._client,
                self._url,
                body,
                label="jev",
                headers={"Authorization": f"Bearer {self._key}"},
                max_retries=self._llm.max_retries,
                backoff_s=self._llm.retry_backoff_s,
                max_wait_s=self._llm.max_retry_wait_s,
                retry_statuses=frozenset({RATE_LIMIT_STATUS}),
            )
        except LLMError as exc:
            raise DeciderError(self._redact(str(exc))) from exc
        return self._parse(response, set(questions))

    def _parse(self, response: httpx.Response, names: set[str]) -> tuple[dict[str, float], Usage]:
        status = response.status_code
        if status in AUTH_STATUSES:  # never echo the server's text
            raise DeciderError(
                f"jev rejected the request (HTTP {status}): check the key and credits"
            )
        if status != 200:
            raise DeciderError(f"jev returned HTTP {status}: {self._detail(response)}")
        try:
            data = response.json()
            probabilities = {n: _probability(data["answers"][n], n) for n in sorted(names)}
            usage = Usage(
                tokens_in=int(data["usage"]["input_tokens"]),
                tokens_out=int(data["usage"]["output_tokens"]),
            )
        except DeciderError:
            raise
        except (ValueError, KeyError, TypeError) as exc:
            raise DeciderError(f"jev sent an unexpected reply ({type(exc).__name__})") from exc
        return probabilities, usage

    def _detail(self, response: httpx.Response) -> str:
        try:
            message = str(response.json()["error"]["message"])
        except (ValueError, KeyError, TypeError):
            message = "no error message"
        return self._redact(message)[:MAX_ERROR_CHARS]


def _probability(answer: Mapping[str, Any], name: str) -> float:
    """P(yes) of a ``noul`` answer; a refusal or any other shape is an error."""
    if answer.get("type") != "noul":
        raise DeciderError(f"jev gave no yes/no answer for '{name}' (type {answer.get('type')!r})")
    value = float(answer["noul"])
    if not 0.0 <= value <= 1.0:
        raise DeciderError(f"jev returned a probability outside 0..1 for '{name}'")
    return value


__all__ = ["JevClient"]
