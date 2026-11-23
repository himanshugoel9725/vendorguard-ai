"""The shared fixtures themselves."""

from collections.abc import Callable

from vendorguard.config import Settings


def test_settings_override_defaults_are_hermetic(
    settings_override: Callable[..., Settings],
) -> None:
    """Defaults use the mock LLM, no embeddings and temp paths."""
    s = settings_override()
    assert (s.llm.provider, s.embeddings.provider, s.decision.provider) == ("mock", "none", "rule")
    assert "pytest" in str(s.paths.runs_dir)


def test_settings_override_merges_nested_values(settings_override: Callable[..., Settings]) -> None:
    """A nested override changes one key and keeps its siblings from the YAML."""
    s = settings_override(llm={"seed": 7})
    assert s.llm.seed == 7
    assert s.llm.provider == "mock"
    assert s.llm.temperature == 0.0
