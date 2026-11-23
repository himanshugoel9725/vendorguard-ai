"""Settings sections for application, paths, documents, retrieval, pipeline, reporting, API, eval."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, model_validator

from vendorguard.config_models.base import (
    DeciderProvider,
    EmbeddingsProvider,
    LlmProvider,
    NonNegFloat,
    NonNegInt,
    PositiveInt,
    Probability,
    StrictModel,
)

PromptVersion = Annotated[str, Field(pattern=r"^v\d+$")]


class AppSettings(StrictModel):
    """General application settings."""

    name: str
    environment: Literal["local", "ci", "demo", "prod"]
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
    log_json: bool


class PathsSettings(StrictModel):
    """Filesystem locations (all relative to the working directory unless absolute)."""

    samples_dir: Path
    golden_dir: Path
    inbox_dir: Path
    runs_dir: Path
    state_dir: Path
    prompts_dir: Path
    controls_file: Path


class PromptsSettings(StrictModel):
    """Active prompt version per agent."""

    intake: PromptVersion
    mapper: PromptVersion
    reviewer: PromptVersion
    judge: PromptVersion
    reporter: PromptVersion
    ask: PromptVersion


class IngestSettings(StrictModel):
    """Document loading limits and cleaning."""

    allowed_extensions: list[str]
    max_file_mb: PositiveInt
    max_pages: PositiveInt
    strip_repeated_lines: bool
    repeated_line_min_ratio: Probability


class ChunkingSettings(StrictModel):
    """Page-aware chunk sizes."""

    chunk_chars: PositiveInt
    overlap_chars: NonNegInt
    min_chunk_chars: PositiveInt

    @model_validator(mode="after")
    def _sizes_consistent(self) -> "ChunkingSettings":
        if self.overlap_chars >= self.chunk_chars:
            raise ValueError("overlap_chars must be smaller than chunk_chars")
        if self.min_chunk_chars > self.chunk_chars:
            raise ValueError("min_chunk_chars must not exceed chunk_chars")
        return self


class RetrievalSettings(StrictModel):
    """Hybrid retrieval weights and limits."""

    top_k: PositiveInt
    bm25_weight: NonNegFloat
    embedding_weight: NonNegFloat
    min_score: Probability

    @model_validator(mode="after")
    def _weights_positive_sum(self) -> "RetrievalSettings":
        if self.bm25_weight + self.embedding_weight <= 0:
            raise ValueError("bm25_weight + embedding_weight must be greater than 0")
        return self


class IntakeSettings(StrictModel):
    """Intake Agent input size."""

    max_chunks: PositiveInt


class PipelineSettings(StrictModel):
    """Orchestrator behaviour."""

    controls_subset: list[str]
    max_concurrency: PositiveInt
    triage_enabled: bool
    max_review_rounds: NonNegInt
    review_extra_chunks: NonNegInt
    deterministic_run_ids: bool


class ReportingSettings(StrictModel):
    """Report rendering."""

    formats: list[Literal["json", "md", "html"]]
    summary_max_words: PositiveInt
    include_audit_trail: bool


class ApiSettings(StrictModel):
    """REST API settings. auth_key is a secret and comes only from the environment."""

    host: str
    port: Annotated[int, Field(ge=1, le=65535)]
    auth_enabled: bool
    auth_key: SecretStr
    cors_origins: list[str]
    max_upload_mb: PositiveInt
    rate_limit_per_minute: PositiveInt


class EvalConfig(StrictModel):
    """One row of the evaluation matrix."""

    name: str
    llm: LlmProvider
    decider: DeciderProvider
    embeddings: EmbeddingsProvider


class EvalSettings(StrictModel):
    """Evaluation runner settings."""

    results_dir: Path
    determinism_repeats: PositiveInt
    configs: list[EvalConfig]


__all__ = [
    "ApiSettings",
    "AppSettings",
    "ChunkingSettings",
    "EvalConfig",
    "EvalSettings",
    "IngestSettings",
    "IntakeSettings",
    "PathsSettings",
    "PipelineSettings",
    "PromptsSettings",
    "ReportingSettings",
    "RetrievalSettings",
]
