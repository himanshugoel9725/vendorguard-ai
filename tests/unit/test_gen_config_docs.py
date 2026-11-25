"""docs/CONFIG.md generator: comment scanning, types, secrets, and that the file is up to date."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from vendorguard.config import Settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def gen() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "gen_config_docs", ROOT / "scripts" / "gen_config_docs.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_split_comment_respects_quotes(gen: ModuleType) -> None:
    assert gen.split_comment('"#fcfcfb"   # the surface') == ('"#fcfcfb"', "the surface")
    assert gen.split_comment("INFO # level") == ("INFO", "level")
    assert gen.split_comment("a#b") == ("a#b", "")  # no space before the hash: not a comment
    assert gen.split_comment("'x # y'") == ("'x # y'", "")


def test_scan_yaml_trailing_block_and_section_comments(gen: ModuleType) -> None:
    text = (
        "# =====\n# The llm section.\n# ======\n"
        "llm:\n"
        "  # block above the key\n"
        "  model: qwen   # trailing\n"
        "  seed: 1\n"
        "  nested:\n"
        "    deep: 2     # deep note\n"
        "list:\n"
        "  - {a: 1}\n"
    )
    notes, intros = gen.scan_yaml(text)
    assert intros["llm"] == "The llm section."
    assert notes[("llm", "model")] == "block above the key trailing"
    assert notes[("llm", "seed")] == ""
    assert notes[("llm", "nested", "deep")] == "deep note"


def test_secrets_are_never_rendered(gen: ModuleType) -> None:
    text = 'api:\n  auth_key: "abcdefghijklmnop"   # would be a leak\n'
    out = gen.render(text, Settings)
    assert "abcdefghijklmnop" not in out and "set in `.env`" in out


def test_every_yaml_leaf_has_a_row_and_a_type(gen: ModuleType) -> None:
    text = (ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    out = gen.render(text, Settings)
    types_ = gen.field_types(Settings)
    for path in gen.leaves(yaml.safe_load(text), Settings):
        assert f"| `{'.'.join(path)}` |" in out, path
        assert path in types_, f"no model field for {'.'.join(path)}"


def test_type_names(gen: ModuleType) -> None:
    types_ = gen.field_types(Settings)
    assert types_[("llm", "provider")].startswith("ollama")
    assert types_[("api", "auth_key")] == "secret"
    assert "0" in types_[("verification", "citation_min_similarity")]  # a bounded number


def test_committed_config_md_is_up_to_date(gen: ModuleType) -> None:
    text = gen.render((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"), Settings)
    assert (ROOT / "docs" / "CONFIG.md").read_text(encoding="utf-8") == text, (
        "run `make docs-config`"
    )


def test_every_description_belongs_to_a_real_key(gen: ModuleType) -> None:
    """A line-based scanner could mistake a continuation line for a key: catch that here."""
    text = (ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    notes, _ = gen.scan_yaml(text)
    known = set(gen.field_types(Settings))
    sections = {path[:n] for path in known for n in range(1, len(path))}
    for path in notes:
        assert path in known or path in sections, f"description for unknown key {'.'.join(path)}"
