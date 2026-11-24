"""Edge tests for normalize_text."""

import pytest

from vendorguard.verification.text_normalize import normalize_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("   \n\t ", ""),
        ("A  B\n\nC", "a b c"),
        ("“Hi” ‘x’", "\"hi\" 'x'"),
        ("a–b—c−d‐e‑f‒g", "a-b-c-d-e-f-g"),
        ("ﬁle", "file"),  # NFKC ligature
        ("ＡＢ", "ab"),  # full-width letters
        ("STRASSE", "strasse"),
        ("Straße", "strasse"),  # casefold
        ("café", "café".replace("é", "é")),
        (" x ", "x"),  # NBSP stripped
    ],
)
def test_normalize_cases(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


def test_nfc_and_nfd_agree() -> None:
    assert normalize_text("café") == normalize_text("café")


def test_idempotent_and_deterministic() -> None:
    raw = "  “AES–256”   is  ﬁne \n"
    once = normalize_text(raw)
    assert normalize_text(once) == once == normalize_text(raw)


def test_large_input() -> None:
    assert normalize_text("ab " * 200_000) == " ".join(["ab"] * 200_000)
