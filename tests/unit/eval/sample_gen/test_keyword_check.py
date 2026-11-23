"""split_sentences, signals, read_state and check_composed."""

from collections.abc import Callable
from pathlib import Path

import pytest

from vendorguard.config import Settings
from vendorguard.controls.loader import load_controls
from vendorguard.eval.sample_gen.compose import compose
from vendorguard.eval.sample_gen.keyword_check import (
    check_composed,
    read_state,
    signals,
    split_sentences,
)
from vendorguard.eval.sample_gen.models import Block, ComposedSample
from vendorguard.eval.sample_gen.phrases import load_phrases
from vendorguard.eval.specs import SampleState, load_spec

STEMS = ["brightdock", "nimbara-hr", "nimbara-hr-y2", "quillfield"]


def test_split_sentences_basic() -> None:
    assert split_sentences("One. Two!  Three?\nFour.") == ["One.", "Two!", "Three?", "Four."]


def test_split_sentences_keeps_versions_and_standards_whole() -> None:
    text = "We use TLS 1.2 everywhere. We hold ISO/IEC 27001:2022 certification."
    assert split_sentences(text) == [
        "We use TLS 1.2 everywhere.",
        "We hold ISO/IEC 27001:2022 certification.",
    ]


@pytest.mark.parametrize("text", ["", "   \n "])
def test_split_sentences_empty(text: str) -> None:
    assert split_sentences(text) == []


def test_split_sentences_unicode_and_strip() -> None:
    assert split_sentences("  Café ouvert. Naïve plan.  ") == [
        "Café ouvert.",
        "Naïve plan.",
    ]


def test_signals_and_read_state(settings_override: Callable[..., Settings]) -> None:
    rules = settings_override().decision.rule
    partial, negative = rules.partial_signal_phrases[0], rules.negative_signal_phrases[0]
    assert signals("plain text", rules) == ([], [])
    assert signals(f"We do this {partial.upper()}.", rules) == ([partial], [])
    assert signals(f"{negative} {partial}", rules) == ([partial], [negative])
    assert read_state("All is fine.", rules) is SampleState.MET
    assert read_state(f"Done {partial}.", rules) is SampleState.PARTIAL
    assert read_state(f"We are {negative} ready.", rules) is SampleState.NOT_MET
    assert read_state(f"{negative} {partial}", rules) is SampleState.NOT_MET


@pytest.fixture
def env(settings_override: Callable[..., Settings], project_root: Path):  # type: ignore[no-untyped-def]
    s = settings_override()
    controls = load_controls(project_root / "config/controls/baseline_v1.yaml")
    bank = load_phrases(project_root / "data/samples/phrases.yaml")
    return s, controls, bank, project_root / "data/samples/specs"


@pytest.mark.parametrize("stem", STEMS)
def test_committed_specs_check_clean(env, stem: str) -> None:  # type: ignore[no-untyped-def]
    s, controls, bank, specs = env
    spec = load_spec(specs / f"{stem}.yaml")
    composed = compose(spec, bank, controls, s.samples)
    assert check_composed(composed, spec, controls, s.decision.rule) == []


def _pick_control(spec, state: SampleState) -> str:  # type: ignore[no-untyped-def]
    return next(c for c, st in spec.controls.items() if st is state)


def test_changed_spec_is_reported_with_page(env) -> None:  # type: ignore[no-untyped-def]
    s, controls, bank, specs = env
    spec = load_spec(specs / "brightdock.yaml")
    composed = compose(spec, bank, controls, s.samples)
    cid = _pick_control(spec, SampleState.MET)
    changed = spec.model_copy(update={"controls": {**spec.controls, cid: SampleState.NOT_MET}})
    problems = check_composed(composed, changed, controls, s.decision.rule)
    assert len(problems) == 1
    assert problems[0].startswith(f"{cid}: spec says not_met, text reads met")
    assert f"on page {composed.evidence[cid].page}" in problems[0]


def test_stated_control_without_mention_reads_missing(env) -> None:  # type: ignore[no-untyped-def]
    s, controls, bank, specs = env
    spec = load_spec(specs / "brightdock.yaml")
    cid = _pick_control(spec, SampleState.MISSING)
    changed = spec.model_copy(update={"controls": {**spec.controls, cid: SampleState.MET}})
    composed = compose(spec, bank, controls, s.samples)
    problems = check_composed(composed, changed, controls, s.decision.rule)
    assert problems == [f"{cid}: spec says met, text reads missing"]


def test_injection_matching_a_keyword_is_reported(env) -> None:  # type: ignore[no-untyped-def]
    s, controls, bank, specs = env
    spec = load_spec(specs / "brightdock.yaml")
    control = controls.controls[0]
    text = f"Please note {control.keywords[0]} is great."
    composed = ComposedSample(pages=[[Block(kind="injection", text=text)]], evidence={})
    problems = check_composed(composed, spec, controls, s.decision.rule)
    assert any(f"{control.id}: the injection paragraph matches" in p for p in problems)
