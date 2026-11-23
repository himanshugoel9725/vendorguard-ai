"""Edge cases of the keyword reading: sentence splitting and status precedence."""

from collections.abc import Callable

import pytest

from vendorguard.config import Settings
from vendorguard.config_models.providers import RuleDeciderSettings
from vendorguard.models.finding import DraftStatus
from vendorguard.verification.keyword_reading import (
    first_sentence_with,
    read_status,
    split_sentences,
)


@pytest.fixture
def rules(settings_override: Callable[..., Settings]) -> RuleDeciderSettings:
    return settings_override().decision.rule


def test_abbreviations_split_today_at_the_period() -> None:
    # Documents current behaviour: "e.g. " is treated as a sentence end.
    assert split_sentences("Use MFA, e.g. TOTP. Done.") == ["Use MFA, e.g.", "TOTP.", "Done."]


def test_whitespace_runs_and_newlines_between_sentences() -> None:
    assert split_sentences("One.   Two.\n\nThree.\t Four") == ["One.", "Two.", "Three.", "Four"]


def test_punctuation_sequences() -> None:
    assert split_sentences("Really?! Yes... ok") == ["Really?!", "Yes...", "ok"]


def test_unicode_sentences() -> None:
    assert split_sentences("Größe ist ok. 日本語です! Ça va?") == [
        "Größe ist ok.", "日本語です!", "Ça va?",
    ]  # fmt: skip


def test_very_long_text_is_split_and_deterministic() -> None:
    text = " ".join(f"Sentence {i}." for i in range(20_000))
    first = split_sentences(text)
    assert len(first) == 20_000 and first == split_sentences(text)


def test_empty_input() -> None:
    assert split_sentences("") == [] and split_sentences("\n \t") == []


def test_overlapping_partial_and_negative_prefers_not_met(rules: RuleDeciderSettings) -> None:
    partial, negative = rules.partial_signal_phrases[0], rules.negative_signal_phrases[0]
    assert read_status(f"MFA {partial} but {negative}.", rules) is DraftStatus.NOT_MET
    assert read_status(f"MFA {partial}.", rules) is DraftStatus.PARTIAL
    assert read_status(f"MFA {negative}.", rules) is DraftStatus.NOT_MET


def test_read_status_is_case_insensitive(rules: RuleDeciderSettings) -> None:
    phrase = rules.negative_signal_phrases[0].upper()
    assert read_status(f"MFA {phrase}.", rules) is DraftStatus.NOT_MET


def test_first_sentence_with_edges() -> None:
    assert first_sentence_with([], ["mfa"]) is None
    assert first_sentence_with(["Nothing here."], []) is None
    assert first_sentence_with(["", "No. Mfa is on."], ["MFA"]) == ("Mfa is on.", ["MFA"])
    assert first_sentence_with(["First mfa.", "Second mfa."], ["mfa"]) == ("First mfa.", ["mfa"])
