"""load_phrases and lint_bank, including one mutation per lint rule."""

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from vendorguard.config import Settings
from vendorguard.controls.loader import load_controls
from vendorguard.errors import ConfigError
from vendorguard.eval.sample_gen.models import PhraseBank
from vendorguard.eval.sample_gen.phrases import lint_bank, load_phrases


@pytest.fixture
def ctx(settings_override: Callable[..., Settings], project_root: Path):  # type: ignore[no-untyped-def]
    controls = load_controls(project_root / "config/controls/baseline_v1.yaml")
    bank = load_phrases(project_root / "data/samples/phrases.yaml")
    return bank, controls, settings_override().decision.rule


def _lint(ctx, mutate: Callable[[dict[str, Any]], None]) -> list[str]:  # type: ignore[no-untyped-def]
    bank, controls, rules = ctx
    data = copy.deepcopy(bank.model_dump(mode="json"))
    mutate(data)
    return lint_bank(PhraseBank.model_validate(data), controls, rules)


def test_committed_bank_loads_and_is_clean(ctx) -> None:  # type: ignore[no-untyped-def]
    bank, controls, rules = ctx
    assert len(bank.controls) == 25
    assert lint_bank(bank, controls, rules) == []


def test_load_errors_name_the_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    with pytest.raises(ConfigError, match="nope.yaml"):
        load_phrases(missing)
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="bad.yaml"):
        load_phrases(bad)
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("version: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid.yaml"):
        load_phrases(invalid)


def _first(d: dict[str, Any]) -> str:
    return next(iter(sorted(d)))


def test_non_ascii(ctx) -> None:  # type: ignore[no-untyped-def]
    def m(d: dict[str, Any]) -> None:
        d["section_titles"]["GOV"] = "Gouvernance é"

    assert any("not ASCII" in p for p in _lint(ctx, m))


def test_missing_and_extra_control(ctx) -> None:  # type: ignore[no-untyped-def]
    def drop(d: dict[str, Any]) -> None:
        del d["controls"]["GOV-01"]

    def extra(d: dict[str, Any]) -> None:
        d["controls"]["ZZZ-99"] = copy.deepcopy(d["controls"]["GOV-01"])

    assert any(p.startswith("controls:") and "GOV-01" in p for p in _lint(ctx, drop))
    assert any(p.startswith("controls:") and "ZZZ-99" in p for p in _lint(ctx, extra))


@pytest.mark.parametrize("section", ["section_titles", "filler", "distractors"])
def test_wrong_domain_keys(ctx, section: str) -> None:  # type: ignore[no-untyped-def]
    def m(d: dict[str, Any]) -> None:
        d[section]["XXX"] = d[section].pop("GOV")

    assert any(p.startswith(f"{section}:") for p in _lint(ctx, m))


def test_missing_data_category_phrase(ctx) -> None:  # type: ignore[no-untyped-def]
    def m(d: dict[str, Any]) -> None:
        del d["data_category_phrases"]["pii"]

    assert any(p.startswith("data_category_phrases:") for p in _lint(ctx, m))


@pytest.mark.parametrize(
    ("state", "count"), [("met", 1), ("met", 4), ("partial", 0), ("partial", 3), ("not_met", 2)]
)
def test_wrong_phrasing_counts(ctx, state: str, count: int) -> None:  # type: ignore[no-untyped-def]
    def m(d: dict[str, Any]) -> None:
        texts = d["controls"]["GOV-01"][state]
        d["controls"]["GOV-01"][state] = (texts * 5)[:count]

    assert any(f"GOV-01.{state}: needs" in p for p in _lint(ctx, m))


def _set(state: str, text: str) -> Callable[[dict[str, Any]], None]:
    def m(d: dict[str, Any]) -> None:
        d["controls"]["GOV-01"][state] = [text]

    return m


def _keywords(ctx) -> str:  # type: ignore[no-untyped-def]
    control = next(c for c in ctx[1].controls if c.id == "GOV-01")
    return " and ".join(control.keywords[:2])


def test_sentence_shape_rules(ctx) -> None:  # type: ignore[no-untyped-def]
    kw = _keywords(ctx)
    two = _lint(ctx, _set("met", f"We have {kw}. We also do more."))
    assert any("exactly one sentence" in p for p in two)
    no_stop = _lint(ctx, _set("met", f"We have {kw}"))
    assert any("exactly one sentence" in p for p in no_stop)


def test_too_few_own_keywords(ctx) -> None:  # type: ignore[no-untyped-def]
    problems = _lint(ctx, _set("met", "We are very good at things."))
    assert any("at least 2" in p for p in problems)


def test_signal_rules_per_state(ctx) -> None:  # type: ignore[no-untyped-def]
    rules = ctx[2]
    kw = _keywords(ctx)
    part, neg = rules.partial_signal_phrases[0], rules.negative_signal_phrases[0]
    assert any("is 'met'" in p for p in _lint(ctx, _set("met", f"We have {kw} {part}.")))
    assert any("is 'met'" in p for p in _lint(ctx, _set("met", f"We have {kw} {neg}.")))
    assert any("is 'partial'" in p for p in _lint(ctx, _set("partial", f"We have {kw}.")))
    assert any("is 'partial'" in p for p in _lint(ctx, _set("partial", f"{kw} {part} {neg}.")))
    assert any("is 'not_met'" in p for p in _lint(ctx, _set("not_met", f"We have {kw}.")))
    assert any("is 'not_met'" in p for p in _lint(ctx, _set("not_met", f"{kw} {neg} {part}.")))


@pytest.mark.parametrize("group", ["filler", "distractors"])
def test_neutral_text_with_keyword_or_signal(ctx, group: str) -> None:  # type: ignore[no-untyped-def]
    kw = ctx[1].controls[0].keywords[0]
    sig = ctx[2].negative_signal_phrases[0]

    def with_kw(d: dict[str, Any]) -> None:
        d[group]["GOV"][0] = f"Something about {kw} here."

    def with_sig(d: dict[str, Any]) -> None:
        d[group]["GOV"][0] = f"Something {sig} here."

    assert any("neutral text" in p for p in _lint(ctx, with_kw))
    assert any("neutral text" in p for p in _lint(ctx, with_sig))


def test_section_title_with_keyword(ctx) -> None:  # type: ignore[no-untyped-def]
    kw = ctx[1].controls[0].keywords[0]

    def m(d: dict[str, Any]) -> None:
        d["section_titles"]["GOV"] = kw

    assert any("neutral text" in p for p in _lint(ctx, m))
