"""Loader tests for vendorguard.config: precedence, YAML checks, secrets, fingerprint, caching."""

import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from vendorguard.config import (
    CONFIG_PATH_ENV,
    DEFAULT_CONFIG,
    Settings,
    get_settings,
    load_settings,
)
from vendorguard.errors import ConfigError

SECRET = "sk-super-secret-value-123"


def _yaml_copy(tmp_path: Path, mutate: Callable[[dict[str, Any]], None] | None = None) -> Path:
    data = yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    if mutate:
        mutate(data)
    out = tmp_path / "settings.yaml"
    out.write_text(yaml.safe_dump(data), encoding="utf-8")
    return out


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    return _yaml_copy(tmp_path)


# --- committed config -------------------------------------------------------------------------


def test_committed_yaml_loads_with_every_section() -> None:
    s = load_settings(DEFAULT_CONFIG, env_file=None)
    for name in Settings.model_fields:
        assert getattr(s, name) is not None
    assert len(Settings.model_fields) == 21
    assert s.llm.seed == 42
    assert s.llm.openai_compat.api_key.get_secret_value() == ""


def test_vendorguard_config_env_selects_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alt = _yaml_copy(tmp_path, lambda d: d["llm"].update(model="alt-model"))
    monkeypatch.setenv(CONFIG_PATH_ENV, str(alt))
    assert load_settings(env_file=None).llm.model == "alt-model"


def test_explicit_path_beats_config_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    alt = _yaml_copy(tmp_path, lambda d: d["llm"].update(model="alt-model"))
    monkeypatch.setenv(CONFIG_PATH_ENV, str(tmp_path / "missing.yaml"))
    assert load_settings(alt, env_file=None).llm.model == "alt-model"


# --- precedence -------------------------------------------------------------------------------


def test_env_var_beats_yaml(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VG_LLM__MODEL", "from-env")
    assert load_settings(cfg, env_file=None).llm.model == "from-env"


def test_overrides_beat_env(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VG_LLM__SEED", "5")
    s = load_settings(cfg, overrides={"llm": {"seed": 9}}, env_file=None)
    assert s.llm.seed == 9


def test_env_beats_dotenv_beats_yaml(
    cfg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("VG_LLM__SEED=7\nVG_LLM__MODEL=dotenv-model\nUNRELATED_VAR=1\n")
    s = load_settings(cfg, env_file=env_file)
    assert (s.llm.seed, s.llm.model) == (7, "dotenv-model")
    monkeypatch.setenv("VG_LLM__MODEL", "env-model")
    s = load_settings(cfg, env_file=env_file)
    assert (s.llm.seed, s.llm.model) == (7, "env-model")


def test_dotenv_unrelated_variables_ignored(cfg: Path, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SOMETHING_ELSE=abc\nVG_NOT_A_SECTION=1\n")
    assert load_settings(cfg, env_file=env_file).llm.seed == 42


def test_nested_secret_from_env(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VG_LLM__OPENAI_COMPAT__API_KEY", SECRET)
    s = load_settings(cfg, env_file=None)
    assert s.llm.openai_compat.api_key.get_secret_value() == SECRET
    # sibling YAML values survive the nested env override
    assert s.llm.openai_compat.response_format == "json_schema"


def test_secret_from_dotenv(cfg: Path, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"VG_API__AUTH_KEY={SECRET}\n")
    assert load_settings(cfg, env_file=env_file).api.auth_key.get_secret_value() == SECRET


def test_env_value_failing_validation_raises(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VG_LLM__PROVIDER", "nope")
    with pytest.raises(ConfigError, match=r"llm\.provider"):
        load_settings(cfg, env_file=None)


# --- YAML errors ------------------------------------------------------------------------------


def test_missing_key_names_field_path(tmp_path: Path) -> None:
    path = _yaml_copy(tmp_path, lambda d: d["llm"].pop("seed"))
    with pytest.raises(ConfigError, match=r"llm\.seed: missing"):
        load_settings(path, env_file=None)


def test_missing_section_names_section(tmp_path: Path) -> None:
    path = _yaml_copy(tmp_path, lambda d: d.pop("cost"))
    with pytest.raises(ConfigError, match=r"cost: missing"):
        load_settings(path, env_file=None)


def test_unknown_top_level_key(tmp_path: Path) -> None:
    path = _yaml_copy(tmp_path, lambda d: d.update(bogus_section={"a": 1}))
    with pytest.raises(ConfigError, match="bogus_section"):
        load_settings(path, env_file=None)


def test_unknown_nested_key(tmp_path: Path) -> None:
    path = _yaml_copy(tmp_path, lambda d: d["llm"].update(sead=1))
    with pytest.raises(ConfigError, match=r"llm\.sead"):
        load_settings(path, env_file=None)


def test_unreadable_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read config file"):
        load_settings(tmp_path / "nope.yaml", env_file=None)


def test_invalid_yaml_syntax(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [unclosed\n")
    with pytest.raises(ConfigError, match="cannot read config file"):
        load_settings(bad, env_file=None)


@pytest.mark.parametrize("content", ["", "- a\n- b\n", "just a string\n"])
def test_non_mapping_yaml(tmp_path: Path, content: str) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(content)
    with pytest.raises(ConfigError, match="YAML mapping"):
        load_settings(bad, env_file=None)


def test_validation_error_does_not_echo_values(tmp_path: Path) -> None:
    path = _yaml_copy(tmp_path, lambda d: d["llm"].update(top_p="leaky-value-xyz"))
    with pytest.raises(ConfigError) as exc:
        load_settings(path, env_file=None)
    assert "leaky-value-xyz" not in str(exc.value)


# --- secrets in YAML --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mutate", "field", "env_name"),
    [
        (lambda d: d["api"].update(auth_key=SECRET), "api.auth_key", "VG_API__AUTH_KEY"),
        (
            lambda d: d["llm"]["openai_compat"].update(api_key=SECRET),
            "llm.openai_compat.api_key",
            "VG_LLM__OPENAI_COMPAT__API_KEY",
        ),
        (
            lambda d: d["decision"]["jev"].update(api_key=SECRET),
            "decision.jev.api_key",
            "VG_DECISION__JEV__API_KEY",
        ),
        (
            lambda d: d["memory"]["letta"].update(api_key=SECRET),
            "memory.letta.api_key",
            "VG_MEMORY__LETTA__API_KEY",
        ),
    ],
)
def test_yaml_secret_rejected_without_echo(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None], field: str, env_name: str
) -> None:
    path = _yaml_copy(tmp_path, mutate)
    with pytest.raises(ConfigError) as exc:
        load_settings(path, env_file=None)
    message = str(exc.value)
    assert field in message
    assert env_name in message
    assert SECRET not in message


def test_yaml_secret_in_unknown_location_still_rejected(tmp_path: Path) -> None:
    path = _yaml_copy(tmp_path, lambda d: d["eval"].update(api_key=SECRET))
    with pytest.raises(ConfigError, match=r"VG_EVAL__API_KEY") as exc:
        load_settings(path, env_file=None)
    assert SECRET not in str(exc.value)


def test_yaml_null_secret_is_allowed(tmp_path: Path) -> None:
    path = _yaml_copy(tmp_path, lambda d: d["api"].update(auth_key=None))
    # null is "empty" for the YAML check; the field type then decides (str required)
    try:
        load_settings(path, env_file=None)
    except ConfigError as exc:
        assert "keep" not in str(exc) and "must stay empty" not in str(exc)


# --- fingerprint ------------------------------------------------------------------------------


def test_fingerprint_is_64_hex_and_deterministic(
    settings_override: Callable[..., Settings],
) -> None:
    fp = settings_override().fingerprint()
    assert re.fullmatch(r"[0-9a-f]{64}", fp)
    assert settings_override().fingerprint() == fp


def test_fingerprint_ignores_secrets(settings_override: Callable[..., Settings]) -> None:
    a = settings_override(api={"auth_key": "one"}, llm={"openai_compat": {"api_key": "x"}})
    b = settings_override(api={"auth_key": "two"}, llm={"openai_compat": {"api_key": "y"}})
    assert a.fingerprint() == b.fingerprint()


@pytest.mark.parametrize(
    "change",
    [
        {"llm": {"seed": 43}},
        {"llm": {"model": "other"}},
        {"retrieval": {"top_k": 9}},
        {"scoring": {"bands": {"low": 20}}},
        {"cost": {"prices_per_million_tokens": {"x/*": {"input": 1.0, "output": 1.0}}}},
        {"app": {"name": "Ünïcode ✓"}},
    ],
)
def test_fingerprint_changes_with_non_secret_values(
    settings_override: Callable[..., Settings], change: dict[str, Any]
) -> None:
    assert settings_override(**change).fingerprint() != settings_override().fingerprint()


def test_fingerprint_stable_across_processes(tmp_path: Path) -> None:
    code = (
        "from vendorguard.config import load_settings, DEFAULT_CONFIG;"
        "print(load_settings(DEFAULT_CONFIG, env_file=None).fingerprint())"
    )
    outputs = set()
    for seed in ("0", "1", "12345"):
        env = {k: v for k, v in os.environ.items() if not k.startswith("VG_")}
        env["PYTHONHASHSEED"] = seed
        env.pop(CONFIG_PATH_ENV, None)
        res = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            env=env,
            cwd=tmp_path,
        )
        outputs.add(res.stdout.strip())
    assert len(outputs) == 1
    assert re.fullmatch(r"[0-9a-f]{64}", outputs.pop())


# --- get_settings -----------------------------------------------------------------------------


def test_get_settings_cached(cfg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(CONFIG_PATH_ENV, str(cfg))
    get_settings.cache_clear()
    try:
        first = get_settings()
        assert get_settings() is first
        assert isinstance(first, Settings)
    finally:
        get_settings.cache_clear()


def test_yaml_secret_guard_checks_lists_and_whitespace_values() -> None:
    """A key hidden in a list of dicts is caught; blank or null secrets are allowed."""
    from vendorguard.config import _reject_yaml_secrets

    with pytest.raises(ConfigError, match=r"eval\.configs\.0\.api_key"):
        _reject_yaml_secrets({"eval": {"configs": [{"api_key": "sk-hidden"}]}})
    with pytest.raises(ConfigError, match="api_key"):
        _reject_yaml_secrets({"llm": {"api_key": "x"}})
    _reject_yaml_secrets({"llm": {"api_key": ""}, "a": [{"auth_key": "   "}, {"auth_key": None}]})


def test_fingerprint_drops_secretstr_fields_whatever_they_are_called(
    settings_override: Callable[..., Any],
) -> None:
    """Secrets are removed by type, so a renamed SecretStr field could not leak into the hash."""
    from pydantic import SecretStr

    from vendorguard.config import _strip_secrets

    cleaned = _strip_secrets(
        {"a": SecretStr("topsecret"), "nested": [{"b": SecretStr("x"), "c": 1}]}
    )
    assert cleaned == {"nested": [{"c": 1}]}
    assert len(settings_override().fingerprint()) == 64


def test_fingerprint_ignores_pipeline_max_concurrency(
    settings_override: Callable[..., Settings],
) -> None:
    a = settings_override(pipeline={"max_concurrency": 1})
    b = settings_override(pipeline={"max_concurrency": 8})
    assert a.pipeline.max_concurrency != b.pipeline.max_concurrency
    assert a.fingerprint() == b.fingerprint()


@pytest.mark.parametrize(
    "change",
    [
        {"triage_enabled": False},
        {"max_review_rounds": 3},
        {"review_extra_chunks": 5},
    ],
)
def test_fingerprint_changes_with_other_pipeline_fields(
    settings_override: Callable[..., Settings], change: dict[str, Any]
) -> None:
    base = settings_override().fingerprint()
    assert settings_override(pipeline=change).fingerprint() != base
