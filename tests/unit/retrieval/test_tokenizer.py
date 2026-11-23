"""Tokenizer: lower-case alphanumeric tokens without stop words."""

import pytest

from vendorguard.retrieval.tokenizer import Tokenizer


@pytest.fixture
def tokenizer() -> Tokenizer:
    return Tokenizer(["the", "and", "of"])


def test_lowercases_and_splits_on_non_alphanumerics(tokenizer: Tokenizer) -> None:
    assert tokenizer.tokenize("Role-Based Access, RBAC; TLS 1.2!") == [
        "role", "based", "access", "rbac", "tls", "1", "2",
    ]  # fmt: skip


def test_removes_stop_words_case_insensitively(tokenizer: Tokenizer) -> None:
    assert tokenizer.tokenize("The Policy AND the plan of ACTION") == ["policy", "plan", "action"]


def test_stop_words_given_in_upper_case_still_apply() -> None:
    assert Tokenizer(["THE"]).tokenize("the cat") == ["cat"]


def test_keeps_negations_when_they_are_not_stop_words() -> None:
    assert Tokenizer(["the"]).tokenize("MFA is not enforced and no log") == [
        "mfa", "is", "not", "enforced", "and", "no", "log",
    ]  # fmt: skip


def test_underscores_and_punctuation_separate_tokens(tokenizer: Tokenizer) -> None:
    assert tokenizer.tokenize("pen_test--results (annual)") == ["pen", "test", "results", "annual"]


def test_unicode_letters_and_digits_are_tokens(tokenizer: Tokenizer) -> None:
    assert tokenizer.tokenize("Café 中文 2FA") == ["café", "中文", "2fa"]


def test_empty_and_symbol_only_text_gives_no_tokens(tokenizer: Tokenizer) -> None:
    assert tokenizer.tokenize("") == []
    assert tokenizer.tokenize("  ... --- !!! ") == []
    assert tokenizer.tokenize("the and of") == []


def test_no_stop_words_means_everything_is_kept() -> None:
    assert Tokenizer([]).tokenize("The and of") == ["the", "and", "of"]


def test_repeated_calls_are_identical(tokenizer: Tokenizer) -> None:
    text = "Backups are encrypted and stored offsite."
    assert tokenizer.tokenize(text) == tokenizer.tokenize(text)
