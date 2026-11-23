"""Data contracts for LLM calls: chat messages, token usage and the result of a call."""

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

from vendorguard.models._base import ContractModel, NonEmptyStr, NonNegInt

T = TypeVar("T", bound=BaseModel)


class ChatMessage(ContractModel):
    """One message of a chat prompt."""

    role: Literal["system", "user", "assistant"]
    content: str


class Usage(ContractModel):
    """Tokens used by one call (zero for the mock provider and for cache hits)."""

    tokens_in: NonNegInt = 0
    tokens_out: NonNegInt = 0


class LLMResult(ContractModel, Generic[T]):  # noqa: UP046  (pydantic generics: keep Generic[T])
    """A validated model output plus how it was obtained."""

    parsed: T
    usage: Usage
    provider: NonEmptyStr
    model: NonEmptyStr
    cached: bool = False
    latency_ms: float = 0.0


__all__ = ["ChatMessage", "LLMResult", "Usage"]
