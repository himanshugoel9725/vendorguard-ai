"""Shared base model and constrained types for the settings sections."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base for every settings section: unknown keys are errors, instances are immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


Probability = Annotated[float, Field(ge=0.0, le=1.0)]
PositiveInt = Annotated[int, Field(gt=0)]
NonNegInt = Annotated[int, Field(ge=0)]
PositiveFloat = Annotated[float, Field(gt=0.0)]
NonNegFloat = Annotated[float, Field(ge=0.0)]

LlmProvider = Literal["ollama", "openai", "groq", "openai_compat", "mock"]
EmbeddingsProvider = Literal["ollama", "none"]
DeciderProvider = Literal["rule", "llm_judge", "jev", "mock"]
MemoryProvider = Literal["sqlite", "letta"]
CacheBackendName = Literal["sqlite", "jsonl"]
CacheMode = Literal["off", "read_write", "read_only"]
Criticality = Literal["low", "medium", "high", "critical"]
FindingStatus = Literal["met", "partial", "not_met", "no_evidence"]

__all__ = [
    "CacheBackendName",
    "CacheMode",
    "Criticality",
    "DeciderProvider",
    "EmbeddingsProvider",
    "FindingStatus",
    "LlmProvider",
    "MemoryProvider",
    "NonNegFloat",
    "NonNegInt",
    "PositiveFloat",
    "PositiveInt",
    "Probability",
    "StrictModel",
]
