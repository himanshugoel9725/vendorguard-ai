"""phrase_in / matching_phrases: case-insensitive whole-word matching."""

import pytest

from vendorguard.utils.keywords import matching_phrases, phrase_in


@pytest.mark.parametrize(
    ("text", "phrase", "expected"),
    [
        ("Backups are daily", "backup", False),
        ("Backups are daily", "backups", True),
        ("KMS-managed keys", "KMS", True),
        ("TLS 1.2 or higher", "TLS 1.2", True),
        ("We use TLS 1.2.", "TLS 1.2", True),
        ("corporate policy", "RPO", False),
        ("We enforce MULTI-FACTOR Authentication.", "multi-factor authentication", True),
        ("data uses crypto-shredding on exit", "crypto-shredding", True),
        ("we use C++ daily", "C++", True),
        ("axb", "a.b", False),
        ("a.b", "a.b", True),
        ("", "backup", False),
        ("ünïcode Straße policy", "straße", True),
        ("ünïcode Straße policy", "stra", False),
    ],
)
def test_phrase_in(text: str, phrase: str, expected: bool) -> None:
    assert phrase_in(text, phrase) is expected


def test_phrase_in_on_very_large_text() -> None:
    text = "filler " * 200_000 + "needle"
    assert phrase_in(text, "needle")
    assert not phrase_in(text, "needl")


def test_matching_phrases_keeps_given_order() -> None:
    text = "We run backups, use MFA and keep a security policy."
    assert matching_phrases(text, ["security policy", "absent", "MFA", "backups"]) == [
        "security policy",
        "MFA",
        "backups",
    ]


def test_matching_phrases_none_and_empty() -> None:
    assert matching_phrases("nothing relevant", ["alpha", "beta"]) == []
    assert matching_phrases("anything", []) == []
    assert matching_phrases("", ["alpha"]) == []


def test_repeated_calls_are_identical() -> None:
    text = "Backups and KMS-managed keys"
    phrases = ["backups", "kms", "nope"]
    assert [matching_phrases(text, phrases) for _ in range(3)] == [["backups", "kms"]] * 3
