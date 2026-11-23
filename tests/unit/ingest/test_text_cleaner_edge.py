"""Text cleaner edge cases not covered by test_text_cleaner.py."""

import pytest

from vendorguard.ingest.text_cleaner import (
    collapse_whitespace,
    dehyphenate,
    normalize_unicode,
    strip_repeated_lines,
    vocabulary,
)


def test_two_pages_a_shared_line_is_stripped() -> None:
    out = strip_repeated_lines(["Header\nbody one", "Header\nbody two"], 0.5)
    assert out == ["body one", "body two"]


def test_two_pages_with_ratio_one_needs_both_pages() -> None:
    assert strip_repeated_lines(["Hdr\na", "Hdr\nb"], 1.0) == ["a", "b"]
    assert strip_repeated_lines(["Hdr\na", "b"], 1.0) == ["Hdr\na", "b"]


def test_ratio_zero_still_requires_two_occurrences() -> None:
    pages = ["Once\nShared", "Shared\nx", "y"]
    assert strip_repeated_lines(pages, 0.0) == ["Once", "x", "y"]


def test_ratio_one_with_three_pages_needs_every_page() -> None:
    pages = ["H\na", "H\nb", "c"]
    assert strip_repeated_lines(pages, 1.0) == pages


def test_whitespace_only_lines_are_kept_and_not_counted() -> None:
    out = strip_repeated_lines(["Hdr\n   \ntext", "Hdr\n   \nmore"], 0.5)
    assert out == ["   \ntext", "   \nmore"]


def test_pages_of_different_lengths() -> None:
    pages = ["Foot\na\nb\nc\nd", "Foot", "", "Foot\nz"]
    assert strip_repeated_lines(pages, 0.5) == ["a\nb\nc\nd", "", "", "z"]


def test_empty_list_and_empty_pages() -> None:
    assert strip_repeated_lines([], 0.5) == []
    assert strip_repeated_lines(["", ""], 0.5) == ["", ""]


def test_single_page_result_is_a_new_list() -> None:
    pages = ["only"]
    assert strip_repeated_lines(pages, 0.5) is not pages


def test_nfkc_composes_combining_characters() -> None:
    assert normalize_unicode("é") == "é"
    assert normalize_unicode("ｆｕｌｌ１２") == "full12"
    assert normalize_unicode("") == ""


def test_several_hyphenated_words_in_one_paragraph() -> None:
    text = "The authen-\ntication of multi-\nfactor tokens and encryp-\ntion keys."
    known = vocabulary(["multi-factor"])
    assert dehyphenate(text, known) == (
        "The authentication of multi-factor tokens and encryption keys."
    )


def test_soft_hyphen_at_line_end_and_inside_word() -> None:
    assert dehyphenate("encryp­\ntion and se­cure", set()) == "encryption and secure"


def test_dehyphenate_unicode_words() -> None:
    assert dehyphenate("Sicherheits-\nüberprüfung", set()) == "Sicherheitsüberprüfung"


def test_trailing_hyphen_without_following_word_is_kept() -> None:
    assert dehyphenate("end-\n", set()) == "end-\n"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a\t\tb", "a b"),
        ("a  b", "a b"),
        ("a\r\nb", "a b"),
        ("a\rb", "a b"),
        ("a\r\n\r\nb", "a\n\nb"),
        ("a \n \n b", "a\n\nb"),
        ("\n\n\n", ""),
        ("", ""),
        ("p1\n\n\n\np2", "p1\n\np2"),
    ],
)
def test_collapse_whitespace_cases(text: str, expected: str) -> None:
    assert collapse_whitespace(text) == expected


def test_collapse_whitespace_large_input_is_stable() -> None:
    text = ("word  \t " * 100_000).strip()
    out = collapse_whitespace(text)
    assert out == " ".join(["word"] * 100_000)
    assert collapse_whitespace(out) == out
