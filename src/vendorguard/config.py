"""Typed Settings: YAML + .env + VG_* environment variables (see docs/PLAN.md section 5).

Precedence, highest first: explicit overrides (CLI flags) > environment variables > .env > YAML.
Only ``cli/`` and ``api/`` may call :func:`get_settings`; other modules receive their section.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import SecretStr, ValidationError
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from vendorguard.config_models.core import (
    ApiSettings,
    AppSettings,
    ChunkingSettings,
    EvalSettings,
    IngestSettings,
    IntakeSettings,
    PathsSettings,
    PipelineSettings,
    PromptsSettings,
    ReportingSettings,
    RetrievalSettings,
)
from vendorguard.config_models.providers import (
    CacheSettings,
    CostSettings,
    DecisionSettings,
    EmbeddingsSettings,
    LlmSettings,
    MemorySettings,
)
from vendorguard.config_models.scoring import ScoringSettings, VerificationSettings
from vendorguard.errors import ConfigError
from vendorguard.utils.hashing import hash_obj

SECRET_KEYS = frozenset({"api_key", "auth_key"})
CONFIG_PATH_ENV = "VENDORGUARD_CONFIG"
ENV_PREFIX = "VG_"
DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "settings.yaml"


class Settings(BaseSettings):
    """Root settings object: one typed section per top-level YAML key."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_nested_delimiter="__",
        env_file_encoding="utf-8",
        extra="ignore",  # unrelated .env entries are fine; the YAML is checked in load_settings
        frozen=True,
    )

    app: AppSettings
    paths: PathsSettings
    prompts: PromptsSettings
    llm: LlmSettings
    embeddings: EmbeddingsSettings
    ingest: IngestSettings
    chunking: ChunkingSettings
    retrieval: RetrievalSettings
    intake: IntakeSettings
    pipeline: PipelineSettings
    decision: DecisionSettings
    verification: VerificationSettings
    scoring: ScoringSettings
    memory: MemorySettings
    cache: CacheSettings
    cost: CostSettings
    reporting: ReportingSettings
    api: ApiSettings
    eval: EvalSettings

    def fingerprint(self) -> str:
        """SHA-256 of the canonical non-secret configuration (stored in every run manifest)."""
        return hash_obj(_strip_secrets(self.model_dump()))


class _DictSource(PydanticBaseSettingsSource):
    """Lowest-priority source: values read from the YAML file."""

    def __init__(self, settings_cls: type[BaseSettings], data: dict[str, Any]) -> None:
        super().__init__(settings_cls)
        self._data = data

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        """Return the raw YAML value for one field."""
        return self._data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        """Return the whole YAML mapping."""
        return dict(self._data)


def _strip_secrets(value: Any) -> Any:
    """Copy ``value`` without SecretStr values or keys named in SECRET_KEYS, at any depth."""
    if isinstance(value, dict):
        return {
            k: _strip_secrets(v)
            for k, v in value.items()
            if k not in SECRET_KEYS and not isinstance(v, SecretStr)
        }
    if isinstance(value, list | tuple):
        return [_strip_secrets(v) for v in value if not isinstance(v, SecretStr)]
    return value


def _reject_yaml_secrets(value: Any, path: tuple[str, ...] = ()) -> None:
    """Raise ConfigError if any api_key / auth_key in the YAML holds a value (lists included)."""
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_yaml_secrets(item, (*path, str(index)))
    elif isinstance(value, dict):
        for key, child in value.items():
            here = (*path, str(key))
            empty = child is None or (isinstance(child, str) and not child.strip())
            if key in SECRET_KEYS and not empty:
                env_name = ENV_PREFIX + "__".join(p.upper() for p in here)
                raise ConfigError(
                    f"secret '{'.'.join(here)}' must stay empty in the YAML file; "
                    f"set {env_name} in .env instead"
                )
            _reject_yaml_secrets(child, here)


def _describe(exc: ValidationError) -> str:
    """Summarise validation errors by field path (never echoes input values)."""
    lines = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err["loc"])
        lines.append(f"{where}: missing" if err["type"] == "missing" else f"{where}: {err['msg']}")
    return "invalid configuration:\n  " + "\n  ".join(sorted(lines))


def _settings_class(yaml_data: dict[str, Any]) -> type[Settings]:
    """Build a Settings subclass whose sources are overrides > env > .env > YAML."""

    class _Loaded(Settings):
        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            """Order the sources."""
            return (
                init_settings,
                env_settings,
                dotenv_settings,
                _DictSource(settings_cls, yaml_data),
            )

    return _Loaded


def load_settings(
    path: Path | None = None,
    overrides: dict[str, Any] | None = None,
    env_file: Path | str | None = ".env",
) -> Settings:
    """Load and validate settings; raises ConfigError naming any missing or invalid key."""
    config_path = path or Path(os.environ.get(CONFIG_PATH_ENV, DEFAULT_CONFIG))
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read config file {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"config file {config_path} must contain a YAML mapping")
    unknown = sorted(set(raw) - set(Settings.model_fields))
    if unknown:
        raise ConfigError(
            f"unknown top-level key(s) in {config_path}: {', '.join(map(str, unknown))}"
        )
    _reject_yaml_secrets(raw)
    try:
        return _settings_class(raw)(_env_file=env_file, **(overrides or {}))
    except ValidationError as exc:
        raise ConfigError(_describe(exc)) from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings for entry points (cli/ and api/ only)."""
    return load_settings()


__all__ = ["Settings", "get_settings", "load_settings"]
