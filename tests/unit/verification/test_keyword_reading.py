"""The shared keyword reading: sentences, signal phrases, statuses."""

from collections.abc import Callable

import pytest

from vendorguard.config import Settings
from vendorguard.config_models.providers import RuleDeciderSettings
from vendorguard.models.finding import DraftStatus
from vendorguard.verification.keyword_reading import (
    first_sentence_with,
    read_status,
    signals,
    split_sentences,
)


@pytest.fixture
def rules(settings_override: Callable[..., Settings]) -> RuleDeciderSettings:
    return settings_override().decision.rule


def test_split_sentences_keeps_decimals_and_standard_names_together() -> None:
    text = "Use TLS 1.2 or higher. ISO/IEC 27001:2022 applies! Really?  Yes"
    assert split_sentences(text) == [
        "Use TLS 1.2 or higher.", "ISO/IEC 27001:2022 applies!", "Really?", "Yes",
    ]  # fmt: skip
    assert split_sentences("  ") == [] and split_sentences("One.") == ["One."]


def test_signals_returns_partial_and_negative_hits(rules: RuleDeciderSettings) -> None:
    assert signals("MFA is being rolled out and is not enforced.", rules) == (
        ["being rolled out"],
        ["is not enforced", "not enforced", "is not"],  # all three are in the settings list
    )
    assert signals("MFA is enforced everywhere.", rules) == ([], [])


@pytest.mark.parametrize(
    ("sentence", "status"),
    [
        ("MFA is enforced for all staff.", DraftStatus.MET),
        ("MFA is planned for next year.", DraftStatus.PARTIAL),
        ("MFA is not enforced.", DraftStatus.NOT_MET),
        ("MFA is planned but not currently required.", DraftStatus.NOT_MET),  # negative wins
        ("", DraftStatus.MET),  # no signal means met; callers only read sentences with keywords
    ],
)
def test_read_status(rules: RuleDeciderSettings, sentence: str, status: DraftStatus) -> None:
    assert read_status(sentence, rules) is status


def test_first_sentence_with_keyword_scans_texts_and_sentences_in_order() -> None:
    texts = ["Nothing here. More nothing.", "Intro. We use MFA and SSO daily. MFA again."]
    assert first_sentence_with(texts, ["sso", "mfa"]) == (
        "We use MFA and SSO daily.",
        ["sso", "mfa"],
    )
    assert first_sentence_with(texts, ["firewall"]) is None
    assert first_sentence_with([], ["mfa"]) is None
    assert first_sentence_with(texts, []) is None


def test_whole_word_matching_is_used() -> None:
    assert first_sentence_with(["Backups are daily."], ["backup"]) is None
    assert first_sentence_with(["Backups are daily."], ["backups"]) is not None
