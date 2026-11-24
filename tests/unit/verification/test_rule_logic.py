"""Edge tests for the shared rule decider formula."""

from typing import Any

import pytest

from vendorguard.config_models.providers import RuleDeciderSettings
from vendorguard.models.decision import DecisionLabel
from vendorguard.models.finding import DraftStatus
from vendorguard.verification.rule_logic import UNSURE_CONFIDENCE, triage_verdict, verify_verdict


@pytest.fixture
def rules(settings_override: Any) -> RuleDeciderSettings:
    return settings_override().decision.rule


KW = ["encryption", "backup", "mfa", "audit"]


def test_triage_enough_hits_is_addressed_with_scaled_confidence(rules: RuleDeciderSettings) -> None:
    texts = ["Encryption and backup are in place."]
    v = triage_verdict(texts, KW, 0.0, rules)
    assert v.label is DecisionLabel.ADDRESSED
    assert v.hits == ["encryption", "backup"]
    assert v.confidence == pytest.approx(UNSURE_CONFIDENCE + UNSURE_CONFIDENCE * 2 / 4)


def test_triage_all_keywords_gives_confidence_one(rules: RuleDeciderSettings) -> None:
    v = triage_verdict([" ".join(KW)], KW, 0.0, rules)
    assert v.confidence == 1.0


def test_triage_no_hits_low_cosine_is_confident_not_addressed(rules: RuleDeciderSettings) -> None:
    v = triage_verdict(["nothing relevant"], KW, 0.0, rules)
    assert (v.label, v.confidence, v.hits) == (DecisionLabel.NOT_ADDRESSED, 1.0, [])


def test_triage_near_miss_is_not_confident(rules: RuleDeciderSettings) -> None:
    assert rules.triage_min_keyword_hits > 1
    v = triage_verdict(["only mfa here"], KW, 0.0, rules)
    assert v.label is DecisionLabel.NOT_ADDRESSED
    assert v.confidence == UNSURE_CONFIDENCE


def test_triage_cosine_floor_is_inclusive(rules: RuleDeciderSettings) -> None:
    floor = rules.triage_min_retrieval_score
    at = triage_verdict(["x"], KW, floor, rules)
    below = triage_verdict(["x"], KW, floor - 0.001, rules)
    assert (at.label, at.confidence) == (DecisionLabel.ADDRESSED, UNSURE_CONFIDENCE)
    assert below.label is DecisionLabel.NOT_ADDRESSED


def test_triage_empty_inputs(rules: RuleDeciderSettings) -> None:
    v = triage_verdict([], [], 0.0, rules)
    assert v.label is DecisionLabel.NOT_ADDRESSED and v.hits == []


def test_triage_min_hits_zero_is_treated_as_one(rules: RuleDeciderSettings) -> None:
    r = rules.model_copy(update={"triage_min_keyword_hits": 0})
    assert triage_verdict(["mfa"], KW, 0.0, r).label is DecisionLabel.ADDRESSED
    assert triage_verdict(["nothing"], KW, 0.0, r).label is DecisionLabel.NOT_ADDRESSED


def test_triage_is_deterministic(rules: RuleDeciderSettings) -> None:
    a = triage_verdict(["Backup, MFA"], KW, 0.1, rules)
    assert a == triage_verdict(["Backup, MFA"], KW, 0.1, rules)


def test_verify_met_needs_coverage_and_no_signals(rules: RuleDeciderSettings) -> None:
    ok = verify_verdict(DraftStatus.MET, ["Encryption and backup and mfa are enforced."], KW, rules)
    assert ok.label is DecisionLabel.SUPPORTED and ok.confidence == 1.0
    partial = verify_verdict(
        DraftStatus.MET, ["Encryption, backup and mfa are planned."], KW, rules
    )
    assert partial.label is DecisionLabel.UNSUPPORTED
    negative = verify_verdict(
        DraftStatus.MET, ["The vendor does not use encryption, backup or mfa."], KW, rules
    )
    assert negative.label is DecisionLabel.UNSUPPORTED


def test_verify_partial_and_not_met_need_their_signal(rules: RuleDeciderSettings) -> None:
    assert (
        verify_verdict(DraftStatus.PARTIAL, ["Encryption and backup are planned."], KW, rules).label
        is DecisionLabel.SUPPORTED
    )
    assert (
        verify_verdict(
            DraftStatus.NOT_MET, ["Encryption and backup are not in place."], KW, rules
        ).label
        is DecisionLabel.SUPPORTED
    )
    assert (
        verify_verdict(
            DraftStatus.NOT_MET, ["Encryption and backup are enforced."], KW, rules
        ).label
        is DecisionLabel.UNSUPPORTED
    )


def test_verify_signal_in_second_quote_counts_whole_text(rules: RuleDeciderSettings) -> None:
    v = verify_verdict(
        DraftStatus.MET, ["Encryption and backup exist.", "Audit is planned."], KW, rules
    )
    assert v.label is DecisionLabel.UNSUPPORTED


def test_verify_no_evidence_supported_only_without_quotes(rules: RuleDeciderSettings) -> None:
    assert verify_verdict(DraftStatus.NO_EVIDENCE, [], KW, rules).label is DecisionLabel.SUPPORTED
    assert (
        verify_verdict(DraftStatus.NO_EVIDENCE, ["encryption"], KW, rules).label
        is DecisionLabel.UNSUPPORTED
    )


def test_verify_met_without_quotes_or_with_low_coverage_is_unsupported(
    rules: RuleDeciderSettings,
) -> None:
    assert verify_verdict(DraftStatus.MET, [], KW, rules).label is DecisionLabel.UNSUPPORTED
    low = verify_verdict(DraftStatus.MET, ["unrelated sentence."], KW, rules)
    assert low.label is DecisionLabel.UNSUPPORTED and low.hits == []


def test_verify_coverage_threshold_from_settings(rules: RuleDeciderSettings) -> None:
    strict = rules.model_copy(update={"verify_min_keyword_coverage": 1.0})
    text = ["Encryption and backup exist."]
    assert verify_verdict(DraftStatus.MET, text, KW, rules).label is DecisionLabel.SUPPORTED
    assert verify_verdict(DraftStatus.MET, text, KW, strict).label is DecisionLabel.UNSUPPORTED


def test_verify_empty_keywords_does_not_divide_by_zero(rules: RuleDeciderSettings) -> None:
    zero = rules.model_copy(update={"verify_min_keyword_coverage": 0.0})
    assert verify_verdict(DraftStatus.MET, ["anything"], [], zero).label is DecisionLabel.SUPPORTED
