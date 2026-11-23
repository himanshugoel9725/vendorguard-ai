"""Validator tests for vendorguard.config_models, exercised through the loader."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from vendorguard.config import DEFAULT_CONFIG, Settings, load_settings
from vendorguard.errors import ConfigError

Build = Callable[..., Settings]


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"llm": {"top_p": 1.5}}, "llm.top_p"),
        ({"llm": {"top_p": -0.1}}, "llm.top_p"),
        ({"retrieval": {"min_score": 2}}, "retrieval.min_score"),
        ({"decision": {"triage_threshold": 1.01}}, "decision.triage_threshold"),
        ({"decision": {"verify_threshold": -1}}, "decision.verify_threshold"),
        ({"verification": {"citation_min_similarity": 3}}, "verification.citation_min_similarity"),
        ({"ingest": {"repeated_line_min_ratio": 1.2}}, "ingest.repeated_line_min_ratio"),
        ({"scoring": {"status_points": {"met": 1.5}}}, "scoring.status_points.met"),
    ],
)
def test_probability_out_of_range(settings_override: Build, overrides: Any, field: str) -> None:
    with pytest.raises(ConfigError, match=field.replace(".", r"\.")):
        settings_override(**overrides)


def test_probability_bounds_inclusive(settings_override: Build) -> None:
    s = settings_override(llm={"top_p": 0.0}, retrieval={"min_score": 1.0})
    assert s.llm.top_p == 0.0
    assert s.retrieval.min_score == 1.0


@pytest.mark.parametrize(
    "bands",
    [
        {"low": 50, "medium": 25, "high": 75, "critical": 100},
        {"low": 25, "medium": 25, "high": 75, "critical": 100},
        {"low": 25, "medium": 50, "high": 75, "critical": 90},
        {"low": 25, "medium": 50, "high": 75, "critical": 101},
    ],
)
def test_bad_bands(settings_override: Build, bands: dict[str, int]) -> None:
    with pytest.raises(ConfigError, match=r"scoring\.bands"):
        settings_override(scoring={"bands": bands})


def test_valid_bands_loaded(settings_override: Build) -> None:
    b = settings_override().scoring.bands
    assert b.low < b.medium < b.high < b.critical == 100


@pytest.mark.parametrize(
    ("chunking", "text"),
    [
        ({"overlap_chars": 1200}, "overlap_chars"),
        ({"overlap_chars": 5000}, "overlap_chars"),
        ({"min_chunk_chars": 1201}, "min_chunk_chars"),
    ],
)
def test_chunking_consistency(settings_override: Build, chunking: Any, text: str) -> None:
    with pytest.raises(ConfigError, match=text):
        settings_override(chunking=chunking)


def test_chunking_boundaries_allowed(settings_override: Build) -> None:
    s = settings_override(chunking={"overlap_chars": 1199, "min_chunk_chars": 1200})
    assert s.chunking.min_chunk_chars == s.chunking.chunk_chars


def test_retrieval_weights_sum_zero(settings_override: Build) -> None:
    with pytest.raises(ConfigError, match="greater than 0"):
        settings_override(retrieval={"bm25_weight": 0, "embedding_weight": 0})


def test_retrieval_one_zero_weight_ok(settings_override: Build) -> None:
    assert settings_override(retrieval={"embedding_weight": 0}).retrieval.embedding_weight == 0


def test_negative_weight_rejected(settings_override: Build) -> None:
    with pytest.raises(ConfigError, match=r"retrieval\.bm25_weight"):
        settings_override(retrieval={"bm25_weight": -1})


@pytest.mark.parametrize(
    "overrides",
    [
        {"llm": {"provider": "gpt"}},
        {"embeddings": {"provider": "openai"}},
        {"decision": {"provider": "magic"}},
        {"decision": {"jev": {"fallback_provider": "jev"}}},
        {"memory": {"provider": "redis"}},
        {"cache": {"mode": "write_only"}},
        {"cache": {"backend": "redis"}},
        {"app": {"environment": "staging"}},
        {"app": {"log_level": "TRACE"}},
        {"scoring": {"critical_control_floor": "extreme"}},
        {"reporting": {"formats": ["pdf"]}},
        {"verification": {"require_citation_for": ["maybe"]}},
    ],
)
def test_unknown_literal_values(settings_override: Build, overrides: Any) -> None:
    with pytest.raises(ConfigError):
        settings_override(**overrides)


def test_empty_prices_table(tmp_path: Path) -> None:
    # sources are deep-merged, so the empty table has to come from the YAML itself
    data = yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    data["cost"]["prices_per_million_tokens"] = {}
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="must not be empty"):
        load_settings(path, env_file=None)


@pytest.mark.parametrize("version", ["1", "V1", "v", "v1.2", "v-1", " v1", "v1 ", "latest"])
def test_bad_prompt_version(settings_override: Build, version: str) -> None:
    with pytest.raises(ConfigError, match=r"prompts\.intake"):
        settings_override(prompts={"intake": version})


@pytest.mark.parametrize("version", ["v1", "v2", "v10", "v007"])
def test_good_prompt_version(settings_override: Build, version: str) -> None:
    assert settings_override(prompts={"ask": version}).prompts.ask == version


@pytest.mark.parametrize("port", [0, -1, 65536, 100000])
def test_port_out_of_range(settings_override: Build, port: int) -> None:
    with pytest.raises(ConfigError, match=r"api\.port"):
        settings_override(api={"port": port})


@pytest.mark.parametrize("port", [1, 8000, 65535])
def test_port_in_range(settings_override: Build, port: int) -> None:
    assert settings_override(api={"port": port}).api.port == port


def test_positive_int_and_temperature_bounds(settings_override: Build) -> None:
    with pytest.raises(ConfigError, match=r"llm\.max_output_tokens"):
        settings_override(llm={"max_output_tokens": 0})
    with pytest.raises(ConfigError, match=r"llm\.temperature"):
        settings_override(llm={"temperature": 2.5})
    with pytest.raises(ConfigError, match=r"cost\.warn_at_fraction"):
        settings_override(cost={"warn_at_fraction": 0})


def test_models_are_frozen(settings_override: Build) -> None:
    s = settings_override()
    with pytest.raises(Exception, match="frozen"):
        s.llm.seed = 1  # type: ignore[misc]


# --- SecretStr --------------------------------------------------------------------------------

SECRET = "sk-very-secret-9876"  # fake test value  # gitleaks:allow


def test_secret_retrievable_but_never_rendered(settings_override: Build) -> None:
    s = settings_override(
        api={"auth_key": SECRET},
        llm={"openai_compat": {"api_key": SECRET + "a"}},
        decision={"jev": {"api_key": SECRET + "b"}},
        memory={"letta": {"api_key": SECRET + "c"}},
    )
    assert s.api.auth_key.get_secret_value() == SECRET
    assert s.llm.openai_compat.api_key.get_secret_value() == SECRET + "a"
    assert s.decision.jev.api_key.get_secret_value() == SECRET + "b"
    assert s.memory.letta.api_key.get_secret_value() == SECRET + "c"
    for rendered in (repr(s), str(s), s.model_dump_json(), repr(s.api), s.api.model_dump_json()):
        assert SECRET not in rendered
    assert "**********" in s.api.model_dump_json()
