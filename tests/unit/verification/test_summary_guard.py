"""Tests for the summary number/control-ID guard."""

from typing import Any

from vendorguard.verification.summary_guard import check_summary

FACTS: dict[str, Any] = {
    "vendor_name": "Acme 2000 Corp",
    "overall": 42.5,
    "band": "medium",
    "inherent_tier": "high",
    "counts": {"met": 20, "partial": 3, "not_met": 2, "no_evidence": 0},
    "gaps": ["IAM-01", "LOG-02"],
    "domain_scores": {"IAM": 30.0},
    "triggered_rules": ["critical_control_floor: IAM-01 is not_met, so the band is at least high"],
    "flag": True,
    "nothing": None,
}
MAX = 50


def test_clean_summary_passes() -> None:
    text = "Acme 2000 Corp scores 42.5 (medium); IAM-01 and LOG-02 are open. 20 controls are met."
    assert check_summary(text, FACTS, MAX) == []


def test_total_of_counts_is_allowed() -> None:
    assert check_summary("25 controls were assessed.", FACTS, MAX) == []


def test_invented_and_rounded_numbers_rejected() -> None:
    assert check_summary("The score is 43.", FACTS, MAX) == ["the number 43 is not in the result"]
    assert check_summary("The score is 42.50 here.", FACTS, MAX) == []  # equal value
    assert check_summary("Score 42.4.", FACTS, MAX) == ["the number 42.4 is not in the result"]


def test_numbers_inside_words_and_ids_are_not_counted() -> None:
    assert check_summary("AES256 is used; see IAM-01.", FACTS, MAX) == []


def test_unknown_control_id_rejected_and_id_digits_not_read_as_numbers() -> None:
    assert check_summary("Fix NET-07 first.", FACTS, MAX) == ["control NET-07 is not in the result"]


def test_control_ids_found_only_in_free_text_facts_are_allowed() -> None:
    # IAM-01 also appears inside triggered_rules; its digits must not become allowed numbers
    assert check_summary("IAM-01 failed; 1 issue.", FACTS, MAX) == [
        "the number 1 is not in the result"
    ]


def test_word_limit() -> None:
    text = " ".join(["word"] * 6)
    assert check_summary(text, FACTS, 6) == []
    assert check_summary(text, FACTS, 5) == ["the summary has 6 words, more than the limit of 5"]


def test_vendor_name_is_blanked_before_checking_numbers() -> None:
    assert check_summary("Acme 2000 Corp is medium.", FACTS, MAX) == []
    other = {**FACTS, "vendor_name": ""}
    assert check_summary("Acme 2000 Corp is medium.", other, MAX) == [
        "the number 2000 is not in the result"
    ]
    missing = {k: v for k, v in FACTS.items() if k != "vendor_name"}
    assert check_summary("Plain text.", missing, MAX) == []


def test_bool_and_none_facts_are_not_numbers() -> None:
    assert check_summary("It is 1.", {"flag": True, "x": None}, MAX) == [
        "the number 1 is not in the result"
    ]


def test_counts_not_a_mapping_adds_no_total() -> None:
    facts = {"counts": "n/a", "overall": 5.0}
    assert check_summary("Score 5.", facts, MAX) == []
    assert check_summary("Total 25.", facts, MAX) == ["the number 25 is not in the result"]


def test_counts_with_non_numeric_values_ignored_in_total() -> None:
    facts = {"counts": {"met": 2, "x": "many"}}
    assert check_summary("2 met.", facts, MAX) == []


def test_numbers_nested_in_lists_and_tuples_are_allowed() -> None:
    facts = {"items": [{"n": 7}, (8, 9.5)], "s": {10}}
    assert check_summary("7 8 9.5 10", facts, MAX) == []


def test_numbers_in_fact_strings_are_allowed() -> None:
    assert check_summary("Period 2024.", {"period": "FY2024 to 2024"}, MAX) == []


def test_problem_order_is_sorted_and_deterministic() -> None:
    text = "ZZZ-02 AAA-01 9 3"
    a = check_summary(text, {}, MAX)
    assert a == check_summary(text, {}, MAX)
    assert a == [
        "control AAA-01 is not in the result",
        "control ZZZ-02 is not in the result",
        "the number 3 is not in the result",
        "the number 9 is not in the result",
    ]


def test_unicode_text_and_empty_summary() -> None:
    assert check_summary("", FACTS, MAX) == []
    assert check_summary("Résumé – 数据 is fine.", FACTS, MAX) == []
