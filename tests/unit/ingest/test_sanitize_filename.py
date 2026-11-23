"""sanitize_filename: only the base name, safe characters, bounded length."""

import pytest

from vendorguard.ingest.loader import sanitize_filename


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("..\\win.ini", "win.ini"),
        ("C:\\Users\\x\\report.pdf", "report.pdf"),
        (".hidden", "hidden"),
        ("...", "document"),
        ("", "document"),
        ("report (final) v2.pdf", "report_final_v2.pdf"),
        ("a   b\t\nc.txt", "a_b_c.txt"),
        ("Übersicht-数据.md", "_bersicht-_.md"),
        ("ok-name_1.2.txt", "ok-name_1.2.txt"),
    ],
)
def test_sanitize_filename_cases(name: str, expected: str) -> None:
    assert sanitize_filename(name, 120) == expected


def test_long_names_are_cut_to_the_limit_keeping_the_extension() -> None:
    out = sanitize_filename("a" * 300 + ".pdf", 120)
    assert len(out) == 120
    assert out.endswith(".pdf")


def test_limit_smaller_than_extension_still_returns_something() -> None:
    assert sanitize_filename("abcdef.pdf", 3) == "a.pdf"


def test_sanitize_is_idempotent_and_deterministic() -> None:
    once = sanitize_filename("we ird/../na me (1).PDF", 20)
    assert sanitize_filename(once, 20) == once
