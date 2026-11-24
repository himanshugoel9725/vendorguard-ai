"""The negative signal phrases of settings flip a sentence to not_met."""

from collections.abc import Callable

import pytest

from vendorguard.config import Settings
from vendorguard.config_models.providers import RuleDeciderSettings
from vendorguard.models.finding import DraftStatus
from vendorguard.utils.keywords import phrase_in
from vendorguard.verification.keyword_reading import read_status

NEW = ["is not", "are not", "was not", "were not", "don't", "doesn't", "didn't", "cannot",
       "can't", "lacks", "unable to", "no policy", "no plan", "no process"]  # fmt: skip


@pytest.fixture
def rules(settings_override: Callable[..., Settings]) -> RuleDeciderSettings:
    return settings_override().decision.rule


def test_settings_contain_the_new_phrases(rules: RuleDeciderSettings) -> None:
    assert set(NEW) <= set(rules.negative_signal_phrases)


def test_every_negative_phrase_flips_a_sentence_to_not_met(rules: RuleDeciderSettings) -> None:
    for phrase in rules.negative_signal_phrases:
        assert read_status(f"The vendor {phrase} apply MFA.", rules) is DraftStatus.NOT_MET


def test_curly_apostrophe_matches_straight_phrase(rules: RuleDeciderSettings) -> None:
    for text in ("Staff don’t use MFA.", "It doesn’t support MFA.", "We can’t do MFA."):
        assert read_status(text, rules) is DraftStatus.NOT_MET
    assert phrase_in("They didn’t", "didn't") and phrase_in("They didn't", "didn't")


def test_whole_word_matching_still_holds(rules: RuleDeciderSettings) -> None:
    assert not phrase_in("There is nothing to report.", "is not")
    assert read_status("There is nothing to report on MFA.", rules) is DraftStatus.MET
    assert read_status("Staff cannotate MFA.", rules) is DraftStatus.MET
    assert read_status("The plan is notable.", rules) is DraftStatus.MET


def test_negative_still_beats_partial(rules: RuleDeciderSettings) -> None:
    partial = rules.partial_signal_phrases[0]
    assert read_status(f"MFA is {partial} but we don't enforce it.", rules) is DraftStatus.NOT_MET
    assert read_status(f"MFA is {partial}.", rules) is DraftStatus.PARTIAL
