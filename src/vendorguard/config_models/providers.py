"""Settings sections for LLM, embeddings, decision layer, memory, cache and cost."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, model_validator

from vendorguard.config_models.base import (
    CacheBackendName,
    CacheMode,
    DeciderProvider,
    EmbeddingsProvider,
    LlmProvider,
    MemoryProvider,
    NonNegFloat,
    NonNegInt,
    PositiveFloat,
    PositiveInt,
    Probability,
    StrictModel,
)

Temperature = Annotated[float, Field(ge=0.0, le=2.0)]


class OpenAICompatSettings(StrictModel):
    """Hosted OpenAI-compatible endpoint (OpenAI, Groq, Gemini, OpenRouter). api_key is a secret."""

    base_url: str
    model: str
    response_format: Literal["json_schema", "json_object"]
    api_key: SecretStr


class LlmSettings(StrictModel):
    """LLM used by the worker agents."""

    provider: LlmProvider
    model: str
    base_url: str
    temperature: Temperature
    seed: int
    top_p: Probability
    max_output_tokens: PositiveInt
    context_window: PositiveInt
    timeout_s: PositiveFloat
    max_retries: NonNegInt
    json_repair_attempts: NonNegInt
    openai_compat: OpenAICompatSettings


class EmbeddingsSettings(StrictModel):
    """Embedding model used by hybrid retrieval."""

    provider: EmbeddingsProvider
    model: str
    base_url: str
    doc_prefix: str
    query_prefix: str
    batch_size: PositiveInt
    timeout_s: PositiveFloat


class RuleDeciderSettings(StrictModel):
    """Thresholds and phrase lists for the deterministic rule decider."""

    triage_min_keyword_hits: NonNegInt
    triage_min_retrieval_score: Probability
    verify_min_keyword_coverage: Probability
    partial_signal_phrases: list[str]
    negative_signal_phrases: list[str]


class JevSettings(StrictModel):
    """Optional Jev decision model. api_key is a secret."""

    base_url: str
    model: str
    timeout_s: PositiveFloat
    max_calls_per_run: PositiveInt
    fallback_provider: Literal["rule", "llm_judge", "mock"]
    api_key: SecretStr


class DecisionSettings(StrictModel):
    """Decision layer used by the triage and verify gates."""

    provider: DeciderProvider
    triage_threshold: Probability
    verify_threshold: Probability
    rule: RuleDeciderSettings
    jev: JevSettings


class LettaSettings(StrictModel):
    """Optional Letta memory agent. api_key is a secret (cloud mode only)."""

    mode: Literal["self_hosted", "cloud"]
    base_url: str
    model: str
    embedding: str
    agent_name_prefix: str
    block_char_limit: PositiveInt
    cloud_max_messages_per_day: NonNegInt
    api_key: SecretStr


class MemorySettings(StrictModel):
    """Vendor memory store."""

    provider: MemoryProvider
    sqlite_path: Path
    ask_max_history_runs: PositiveInt
    letta: LettaSettings


class CacheSettings(StrictModel):
    """Record/replay cache for model calls."""

    enabled: bool
    mode: CacheMode
    backend: CacheBackendName
    sqlite_path: Path
    jsonl_dir: Path


class PriceSettings(StrictModel):
    """Price in USD per million tokens."""

    input: NonNegFloat
    output: NonNegFloat


class CostSettings(StrictModel):
    """Budget guards and price table (keys are glob patterns such as ``ollama/*``)."""

    max_usd_per_run: NonNegFloat
    max_llm_calls_per_run: PositiveInt
    warn_at_fraction: Annotated[float, Field(gt=0.0, le=1.0)]
    prices_per_million_tokens: dict[str, PriceSettings]

    @model_validator(mode="after")
    def _has_prices(self) -> "CostSettings":
        if not self.prices_per_million_tokens:
            raise ValueError("prices_per_million_tokens must not be empty")
        return self


__all__ = [
    "CacheSettings",
    "CostSettings",
    "DecisionSettings",
    "EmbeddingsSettings",
    "JevSettings",
    "LettaSettings",
    "LlmSettings",
    "MemorySettings",
    "OpenAICompatSettings",
    "PriceSettings",
    "RuleDeciderSettings",
]
