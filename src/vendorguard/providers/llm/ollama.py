"""LLM provider for a local Ollama server: ``POST /api/chat`` with schema-constrained output."""

from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel
from tenacity import (
    RetryError,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

from vendorguard.config_models.providers import LlmSettings
from vendorguard.errors import LLMError
from vendorguard.models.llm import ChatMessage, LLMResult, Usage
from vendorguard.providers.llm._json import complete_with_repair
from vendorguard.utils.timeutil import monotonic_s

T = TypeVar("T", bound=BaseModel)
MAX_ERROR_CHARS = 200
_RETRY_CONNECT = (httpx.ConnectError, httpx.ConnectTimeout)


class _ServerError(Exception):
    """An HTTP 5xx answer; the only status that is retried."""


class OllamaLLM:
    """Calls Ollama's chat endpoint (temperature and seed from settings); failures are LLMError."""

    provider = "ollama"

    def __init__(self, settings: LlmSettings, client: httpx.Client | None = None) -> None:
        self.model = settings.model
        self._settings = settings
        self._url = f"{settings.base_url.rstrip('/')}/api/chat"
        self._client = client or httpx.Client(timeout=settings.timeout_s)

    def complete_json(
        self,
        messages: Sequence[ChatMessage],
        output_model: type[T],
        *,
        purpose: str,
        hints: Mapping[str, Any] | None = None,
    ) -> LLMResult[T]:
        """Run the chat and return the reply validated as ``output_model``.

        ``purpose`` and ``hints`` are only used by the mock provider. An invalid reply is re-asked
        ``llm.json_repair_attempts`` times, with the tokens of every call added up.
        """
        schema = output_model.model_json_schema()
        started = monotonic_s()
        parsed, usage = complete_with_repair(
            lambda conversation: self._chat(conversation, schema),
            messages,
            output_model,
            self._settings.json_repair_attempts,
        )
        return LLMResult[T](
            parsed=parsed,
            usage=usage,
            provider=self.provider,
            model=self.model,
            latency_ms=round((monotonic_s() - started) * 1000, 3),
        )

    def close(self) -> None:
        """Release the HTTP connection pool."""
        self._client.close()

    def _chat(self, messages: Sequence[ChatMessage], schema: dict[str, Any]) -> tuple[str, Usage]:
        s = self._settings
        body = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "format": schema,
            "stream": False,
            "options": {
                "temperature": s.temperature,
                "seed": s.seed,
                "top_p": s.top_p,
                "num_ctx": s.context_window,
                "num_predict": s.max_output_tokens,
            },
        }
        retrying = Retrying(
            stop=stop_after_attempt(s.max_retries + 1),
            wait=wait_fixed(s.retry_backoff_s),
            retry=retry_if_exception_type((*_RETRY_CONNECT, _ServerError)),
            reraise=False,
        )
        try:
            response = retrying(self._post, body)
        except RetryError as exc:
            cause = exc.last_attempt.exception()
            raise LLMError(
                f"Ollama failed after {s.max_retries + 1} attempts ({type(cause).__name__})"
            ) from cause
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama chat request failed ({type(exc).__name__})") from exc
        return _read_reply(response)

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        response = self._client.post(self._url, json=body)
        if response.status_code >= 500:
            raise _ServerError(f"HTTP {response.status_code}")
        return response


def _read_reply(response: httpx.Response) -> tuple[str, Usage]:
    if response.status_code != 200:
        raise LLMError(f"Ollama returned HTTP {response.status_code}: {_detail(response)}")
    try:
        data = response.json()
        content = data["message"]["content"]
    except (ValueError, KeyError, TypeError) as exc:
        raise LLMError("unusable Ollama chat response (no message content)") from exc
    if not isinstance(content, str):
        raise LLMError("unusable Ollama chat response (content is not text)")
    usage = Usage(
        tokens_in=_count(data.get("prompt_eval_count")),
        tokens_out=_count(data.get("eval_count")),
    )
    return content, usage


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _detail(response: httpx.Response) -> str:
    try:
        message = response.json().get("error", "")
    except (ValueError, AttributeError):
        message = response.text
    return str(message)[:MAX_ERROR_CHARS]


__all__ = ["OllamaLLM"]
