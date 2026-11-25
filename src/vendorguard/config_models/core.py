"""Settings sections: app, paths, documents, retrieval, pipeline, reporting, API, eval."""

from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

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
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


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
    reserved_prompt_tags: list[str]


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
    stale_upload_max_age_s: PositiveInt

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


class UiSettings(StrictModel):
    """The Streamlit UI: it talks to the REST API like any other client. api_key is a secret."""

    api_base_url: str
    api_key: SecretStr
    request_timeout_s: PositiveFloat
    poll_interval_s: PositiveFloat
    poll_timeout_s: PositiveFloat
    page_title: str

    @model_validator(mode="after")
    def _key_travels_only_over_https_or_loopback(self) -> "UiSettings":
        url = urlsplit(self.api_base_url)
        if url.scheme not in {"http", "https"} or not url.hostname:
            raise ValueError("ui.api_base_url must be an http(s) URL")
        if url.scheme != "https" and url.hostname not in LOOPBACK_HOSTS:
            raise ValueError("ui.api_base_url must use https unless it points at this machine")
        return self


class ChartSettings(StrictModel):
    """Look of the evaluation charts (PNG). Colours follow the data-viz reference palette."""

    dpi: PositiveInt
    width_in: PositiveFloat
    row_height_in: PositiveFloat  # bar charts: height per config row
    cell_in: PositiveFloat  # confusion matrix: size of one cell
    bar_height: PositiveFloat  # bar thickness (fraction of the row)
    font_size: PositiveFloat  # value labels and cell numbers
    title_size: PositiveFloat
    contrast_threshold: (
        Probability  # heatmap cells darker than this share of the maximum get light text
    )
    surface: str
    ink: str
    ink_secondary: str
    grid: str
    muted: str  # de-emphasised bars
    primary: str  # categorical slot 1 (and the emphasised bar)
    secondary: str  # categorical slot 2
    ramp: list[str]  # sequential ramp, light to dark (heatmap)


class EvalSettings(StrictModel):
    """Evaluation runner settings."""

    results_dir: Path
    work_dir: Path
    cache_enabled: bool
    round_digits: NonNegInt
    charts: ChartSettings
    determinism_repeats: PositiveInt
    configs: list[EvalConfig]


__all__ = [
    "ApiSettings",
    "AppSettings",
    "ChunkingSettings",
    "ChartSettings",
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
    "UiSettings",
]
