"""The LLM provider interface (docs/PLAN.md section 6)."""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from vendorguard.models.llm import ChatMessage, LLMResult

T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    """Returns schema-validated JSON. Implementations: Ollama, OpenAI-compatible, mock, cached."""

    provider: str
    model: str

    def complete_json(
        self,
        messages: Sequence[ChatMessage],
        output_model: type[T],
        *,
        purpose: str,
        hints: Mapping[str, Any] | None = None,
    ) -> LLMResult[T]:
        """Run the chat and return the output validated as ``output_model``.

        ``purpose`` is one of intake, mapper, reviewer, judge, reporter, ask. ``hints`` carries
        structured context that only the mock provider reads.
        """
        ...


__all__ = ["LLMClient"]
