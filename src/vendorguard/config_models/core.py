"""Settings sections: app, paths, documents, retrieval, pipeline, reporting, API, eval."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, SecretStr, model_validator

from vendorguard.config_models.base import (
    DeciderProvider,
    EmbeddingsProvider,
    LlmProvider,
    NonNegFloat,
    NonNegInt,
    PositiveFloat,
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
    doctor_timeout_s: PositiveFloat


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
    max_filename_chars: PositiveInt
    max_text_chars: PositiveInt
    strip_repeated_lines: bool
    repeated_line_scan_lines: PositiveInt
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
    bm25_k1: PositiveFloat
    bm25_b: Probability
    stop_words: list[str]
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


class ObservabilitySettings(StrictModel):
    """Audit log, run manifest and Prometheus metrics."""

    latency_buckets_s: Annotated[list[PositiveFloat], Field(min_length=1)]
    git_timeout_s: PositiveFloat


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
    auth_key_min_chars: PositiveInt
    auth_key_min_distinct_chars: PositiveInt
    docs_enabled: bool
    trust_proxy_headers: bool
    cors_origins: list[str]
    max_upload_mb: PositiveInt
    max_files_per_request: PositiveInt
    max_form_fields: PositiveInt
    max_json_body_kb: PositiveInt
    max_queued_jobs: PositiveInt
    max_finished_jobs_kept: PositiveInt
    rate_limit_per_minute: PositiveInt
    rate_limit_max_principals: PositiveInt
    retry_after_s: PositiveInt
    multipart_overhead: float = Field(ge=1.0, le=2.0)
    max_override_reason_chars: PositiveInt
    max_override_analyst_chars: PositiveInt
    shutdown_wait_s: float = Field(ge=0)

    @model_validator(mode="after")
    def _cors_has_no_wildcards(self) -> "ApiSettings":
        bad = [o for o in self.cors_origins if o.strip().lower() in {"*", "null"}]
        if bad:
            raise ValueError("cors_origins must list real origins, not '*' or 'null'")
        return self


class SamplesSettings(StrictModel):
    """Synthetic sample-vendor generator: input locations and PDF layout."""

    specs_dir: Path
    phrases_file: Path
    creation_date: AwareDatetime
    wrap_chars: PositiveInt
    lines_per_page: PositiveInt
    font_size_pt: PositiveFloat
    title_font_size_pt: PositiveFloat
    heading_font_size_pt: PositiveFloat
    line_height_mm: PositiveFloat
    margin_mm: PositiveFloat


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
    "SamplesSettings",
]
