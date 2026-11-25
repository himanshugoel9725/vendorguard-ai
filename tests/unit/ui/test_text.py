"""plain / spreadsheet_safe / host_allowed: the UI's safety helpers."""

import pytest

from vendorguard.ui.text import host_allowed, plain, spreadsheet_safe

ALLOWED = ["127.0.0.1", "localhost", "[::1]"]


def test_plain_escapes_every_markdown_construct() -> None:
    hostile = (
        "[click](http://evil) ![img](http://x/p.png) **bold** `code` <b>x</b> :smile: $E=mc^2$ # h"
    )
    out = plain(hostile)
    for ch in "[]()*`<>:$#!":
        assert f"\\{ch}" in out
    assert plain("ordinary text") == "ordinary text"
    assert plain("a\\b") == "a\\\\b"  # the backslash itself is escaped first


@pytest.mark.parametrize(
    "text", ['=HYPERLINK("http://x")', "+1+1", "-2", "@SUM(A1)", "\tcmd", "\rcmd"]
)
def test_spreadsheet_safe_defuses_formula_starts(text: str) -> None:
    assert spreadsheet_safe(text) == "'" + text


def test_spreadsheet_safe_leaves_normal_names_alone() -> None:
    assert spreadsheet_safe("Nimbara HR") == "Nimbara HR" and spreadsheet_safe("") == ""


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.0.0.1:8501",
        "localhost",
        "LOCALHOST:8501",
        "[::1]",
        "[::1]:8501",
        " localhost ",
    ],
)
def test_loopback_hosts_are_allowed(host: str) -> None:
    assert host_allowed(host, ALLOWED)


@pytest.mark.parametrize(
    "host",
    [
        "evil.test",
        "evil.test:8501",
        "127.0.0.1.evil.test",
        "localhost.evil.test:8501",
        "192.168.1.5:8501",
        "0.0.0.0:8501",
        "[::2]:8501",
        "",
        "evil.test:127.0.0.1",
    ],
)
def test_other_hosts_are_refused(host: str) -> None:
    assert not host_allowed(host, ALLOWED)


def test_a_request_without_a_host_header_is_not_an_attacker_chosen_name() -> None:
    assert host_allowed(None, ALLOWED)
