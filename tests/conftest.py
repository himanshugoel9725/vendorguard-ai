"""Shared fixtures: hermetic settings (mock LLM, no embeddings, temp state and run folders)."""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from vendorguard.config import DEFAULT_CONFIG, Settings, load_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Return ``base`` updated with ``extra``, merging nested dicts."""
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove VG_* variables so tests never depend on the developer's shell or .env."""
    for name in [n for n in os.environ if n.startswith("VG_") or n == "VENDORGUARD_CONFIG"]:
        monkeypatch.delenv(name)


@pytest.fixture
def project_root() -> Path:
    """Absolute path of the repository root."""
    return PROJECT_ROOT


@pytest.fixture
def default_config_path() -> Path:
    """Path of the committed config/settings.yaml."""
    return DEFAULT_CONFIG


@pytest.fixture
def settings_override(tmp_path: Path) -> Callable[..., Settings]:
    """Build Settings from the real YAML with test-safe defaults; pass nested overrides as kwargs.

    Defaults: mock LLM, ``none`` embeddings, rule decider, SQLite memory, CI environment and every
    state/run/cache path inside ``tmp_path``. ``.env`` is never read.
    Example: ``settings_override(llm={"seed": 7})``.
    """
    base: dict[str, Any] = {
        "app": {"environment": "ci"},
        "llm": {"provider": "mock"},
        "embeddings": {"provider": "none"},
        "decision": {"provider": "rule"},
        "memory": {"provider": "sqlite", "sqlite_path": tmp_path / "state" / "memory.db"},
        "cache": {
            "sqlite_path": tmp_path / "state" / "cache.db",
            "jsonl_dir": tmp_path / "cassettes",
        },
        "paths": {"state_dir": tmp_path / "state", "runs_dir": tmp_path / "runs"},
    }

    def build(**overrides: Any) -> Settings:
        return load_settings(overrides=_deep_merge(base, overrides), env_file=None)

    return build
