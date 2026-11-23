"""Load the phrase bank and lint it against the control keywords and signal phrases."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from vendorguard.config_models.providers import RuleDeciderSettings
from vendorguard.errors import ConfigError
from vendorguard.eval.sample_gen.keyword_check import signals, split_sentences
from vendorguard.eval.sample_gen.models import PhraseBank
from vendorguard.models.control import ControlSet
from vendorguard.models.vendor import DataCategory
from vendorguard.utils.keywords import matching_phrases

MIN_OWN_KEYWORDS = 2  # triage needs two keyword hits and verify a coverage of 2/6 (tasks 5.5)
COUNTS = {"met": (2, 3), "partial": (1, 2), "not_met": (1, 1)}


def load_phrases(path: Path) -> PhraseBank:
    """Load ``phrases.yaml``; raises ConfigError with the file name on any problem."""
    try:
        return PhraseBank.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read phrase bank {path}: {exc}") from exc
    except ValidationError as exc:
        fields = sorted(".".join(str(p) for p in e["loc"]) or "file" for e in exc.errors())
        raise ConfigError(f"invalid phrase bank {path}: problems in {', '.join(fields)}") from exc


def _all_strings(bank: PhraseBank) -> list[str]:
    out = [*bank.section_titles.values(), *bank.data_category_phrases.values()]
    for group in (bank.filler, bank.distractors):
        out += [t for texts in group.values() for t in texts]
    for phrases in bank.controls.values():
        out += [*phrases.met, *phrases.partial, *phrases.not_met]
    return out


def lint_bank(bank: PhraseBank, controls: ControlSet, rules: RuleDeciderSettings) -> list[str]:
    """Return every rule the bank breaks (empty list = clean)."""
    problems = [f"not ASCII: {t[:50]!r}" for t in _all_strings(bank) if not t.isascii()]
    ids = {c.id for c in controls.controls}
    coverage: list[tuple[str, set[Any], set[Any]]] = [
        ("controls", set(bank.controls), ids),
        ("section_titles", set(bank.section_titles), set(controls.domains)),
        ("filler", set(bank.filler), set(controls.domains)),
        ("distractors", set(bank.distractors), set(controls.domains)),
        ("data_category_phrases", set(bank.data_category_phrases), set(DataCategory)),
    ]
    for label, found, wanted in coverage:
        if found != wanted:
            want, got = sorted(str(x) for x in wanted), sorted(str(x) for x in found)
            problems.append(f"{label}: expected {want}, got {got}")
    every_keyword = [k for c in controls.controls for k in c.keywords]
    for control in controls.controls:
        phrases = bank.controls.get(control.id)
        if phrases is None:
            continue
        for state, texts in (
            ("met", phrases.met),
            ("partial", phrases.partial),
            ("not_met", phrases.not_met),
        ):
            low, high = COUNTS[state]
            if not low <= len(texts) <= high:
                problems.append(
                    f"{control.id}.{state}: needs {low}-{high} phrasings, has {len(texts)}"
                )
            for text in texts:
                problems += _lint_phrasing(control.id, state, text, control.keywords, rules)
    neutral = [*bank.section_titles.values(), *bank.data_category_phrases.values()]
    neutral += [t for g in (bank.filler, bank.distractors) for texts in g.values() for t in texts]
    for text in neutral:
        partial, negative = signals(text, rules)
        hits = matching_phrases(text, every_keyword)
        if partial or negative or hits:
            problems.append(
                f"neutral text has keywords/signals {hits + partial + negative}: {text[:50]!r}"
            )
    return problems


def _lint_phrasing(
    control_id: str, state: str, text: str, keywords: list[str], rules: RuleDeciderSettings
) -> list[str]:
    tag = f"{control_id}.{state}: {text[:45]!r}"
    problems = []
    if len(split_sentences(text)) != 1 or not text.endswith("."):
        problems.append(f"{tag} must be exactly one sentence ending with a full stop")
    if len(matching_phrases(text, keywords)) < MIN_OWN_KEYWORDS:
        problems.append(f"{tag} needs at least {MIN_OWN_KEYWORDS} of the control's keywords")
    partial, negative = signals(text, rules)
    if state == "met" and (partial or negative):
        problems.append(f"{tag} is 'met' but has signal phrases {partial + negative}")
    if state == "partial" and (not partial or negative):
        problems.append(f"{tag} is 'partial': needs a partial signal and no negative one")
    if state == "not_met" and (not negative or partial):
        problems.append(f"{tag} is 'not_met': needs a negative signal and no partial one")
    return problems


__all__ = ["lint_bank", "load_phrases"]
