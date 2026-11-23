"""LLM provider for hosted OpenAI-compatible endpoints (OpenAI, Groq, Gemini, OpenRouter, ...).

One class serves every profile of ``llm.openai`` / ``llm.groq`` / ``llm.openai_compat``: the
profile name is the provider name, and each profile has its own endpoint, model and API key.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from vendorguard.config_models.providers import LlmSettings, OpenAICompatSettings
from vendorguard.errors import ConfigError, LLMError
from vendorguard.logging_setup import RedactingFilter
from vendorguard.models.llm import ChatMessage, LLMResult, Usage
from vendorguard.providers.llm._http import MAX_ERROR_CHARS, post_json
from vendorguard.providers.llm._json import run_chat

T = TypeVar("T", bound=BaseModel)
AUTH_STATUSES = frozenset({401, 403})
RATE_LIMIT_STATUS = 429


class OpenAICompatLLM:
    """Calls ``{base_url}/chat/completions`` with a Bearer key; failures are ``LLMError``."""

    def __init__(
        self,
        name: str,
        llm: LlmSettings,
        profile: OpenAICompatSettings,
        client: httpx.Client | None = None,
    ) -> None:
        self._key = profile.api_key.get_secret_value()
        self._env_name = f"VG_LLM__{name.upper()}__API_KEY"
        if not self._key:
            raise ConfigError(f"no API key for llm.{name}: set {self._env_name} in .env")
        self.provider = name
        self.model = profile.model
        self._llm = llm
        self._profile = profile
        self._url = f"{profile.base_url.rstrip('/')}/chat/completions"
        self._client = client or httpx.Client(timeout=llm.timeout_s)
        self._redact = RedactingFilter([self._key]).redact

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
            lambda conversation: self._chat(conversation, output_model.__name__, schema),
            messages,
            output_model,
            provider=self.provider,
            model=self.model,
            repair_attempts=self._llm.json_repair_attempts,
        )

    def close(self) -> None:
        """Release the HTTP connection pool."""
        self._client.close()

    def _chat(
        self, messages: Sequence[ChatMessage], name: str, schema: dict[str, Any]
    ) -> tuple[str, Usage]:
        response = post_json(
            self._client,
            self._url,
            self._body(messages, name, schema),
            label=self.provider,
            headers={"Authorization": f"Bearer {self._key}"},
            max_retries=self._llm.max_retries,
            backoff_s=self._llm.retry_backoff_s,
            max_wait_s=self._llm.max_retry_wait_s,
            retry_statuses=frozenset({RATE_LIMIT_STATUS}),
        )
        return self._read_reply(response)

    def _body(
        self, messages: Sequence[ChatMessage], name: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        llm, profile = self._llm, self._profile
        conversation = list(messages)
        if profile.response_format == "json_schema":
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {"name": name, "schema": schema},  # best effort, not strict
            }
        else:  # json_object mode has no schema field, so the schema goes into the prompt
            response_format = {"type": "json_object"}
            conversation.insert(
                0,
                ChatMessage(
                    role="system",
                    content="Reply with one JSON object matching this JSON schema: "
                    + json.dumps(schema, sort_keys=True),
                ),
            )
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump() for m in conversation],
            "response_format": response_format,
            profile.max_tokens_field: llm.max_output_tokens,
            "temperature": llm.temperature,
            "top_p": llm.top_p,
            "seed": llm.seed,
        }
        for field in profile.omit_params:
            body.pop(field, None)
        return body

    def _read_reply(self, response: httpx.Response) -> tuple[str, Usage]:
        status = response.status_code
        if status in AUTH_STATUSES:  # the server may echo part of the key: say nothing of its text
            raise LLMError(
                f"{self.provider} rejected the API key (HTTP {status}); check {self._env_name}"
            )
        if status != 200:
            raise LLMError(f"{self.provider} returned HTTP {status}: {self._detail(response)}")
        try:
            data = response.json()
            message = data["choices"][0]["message"]
            content = message.get("content")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise LLMError(f"unusable {self.provider} chat response (no message)") from exc
        if not isinstance(content, str) or not content.strip():
            reason = "the model refused" if message.get("refusal") else "empty reply"
            raise LLMError(f"unusable {self.provider} chat response ({reason})")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return content, Usage(
            tokens_in=_count(usage.get("prompt_tokens")),
            tokens_out=_count(usage.get("completion_tokens")),
        )

    def _detail(self, response: httpx.Response) -> str:
        try:
            error = response.json().get("error", "")
            message = error.get("message", "") if isinstance(error, dict) else error
        except (ValueError, AttributeError):
            message = response.text
        return self._redact(str(message))[:MAX_ERROR_CHARS]


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


__all__ = ["OpenAICompatLLM"]
