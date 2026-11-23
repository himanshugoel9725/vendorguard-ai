"""LLM provider for a local Ollama server: ``POST /api/chat`` with schema-constrained output."""

from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from vendorguard.config_models.providers import LlmSettings
from vendorguard.errors import LLMError
from vendorguard.models.llm import ChatMessage, LLMResult, Usage
from vendorguard.providers.llm._http import MAX_ERROR_CHARS, post_json
from vendorguard.providers.llm._json import run_chat, with_paid_usage

T = TypeVar("T", bound=BaseModel)


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
        return run_chat(
            lambda conversation: self._chat(conversation, schema),
            messages,
            output_model,
            provider=self.provider,
            model=self.model,
            repair_attempts=self._settings.json_repair_attempts,
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
        response = post_json(
            self._client,
            self._url,
            body,
            label="Ollama",
            max_retries=s.max_retries,
            backoff_s=s.retry_backoff_s,
            max_wait_s=s.max_retry_wait_s,
        )
        return _read_reply(response)


def _read_reply(response: httpx.Response) -> tuple[str, Usage]:
    if response.status_code != 200:
        raise LLMError(f"Ollama returned HTTP {response.status_code}: {_detail(response)}")
    try:
        data = response.json()
        content = data["message"]["content"]
    except (ValueError, KeyError, TypeError) as exc:
        raise LLMError("unusable Ollama chat response (no message content)") from exc
    usage = Usage(
        tokens_in=_count(data.get("prompt_eval_count")),
        tokens_out=_count(data.get("eval_count")),
    )
    if not isinstance(content, str):
        raise with_paid_usage(
            LLMError("unusable Ollama chat response (content is not text)"), usage
        )
    if data.get("done_reason") == "length":
        raise with_paid_usage(
            LLMError(
                "Ollama: the reply was cut off at llm.max_output_tokens; raise it "
                "(or use a larger context_window)"
            ),
            usage,
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
