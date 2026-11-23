"""text_loader.load_text_pages: decoding, newline normalisation, form-feed pages, limits."""

import pytest

from vendorguard.errors import IngestError
from vendorguard.ingest.text_loader import load_text_pages

MAX = 50


def _texts(data: bytes, max_pages: int = MAX) -> list[str]:
    return [p.text for p in load_text_pages(data, max_pages)]


def test_plain_text_is_one_page() -> None:
    pages = load_text_pages(b"hello world", MAX)
    assert [(p.number, p.text) for p in pages] == [(1, "hello world")]


def test_utf8_bom_is_ignored() -> None:
    assert _texts(b"\xef\xbb\xbfhello") == ["hello"]


def test_unicode_is_preserved() -> None:
    assert _texts("Zürich — 数据 🔒".encode()) == ["Zürich — 数据 🔒"]


def test_crlf_and_lone_cr_become_lf() -> None:
    assert _texts(b"a\r\nb\rc\nd") == ["a\nb\nc\nd"]


def test_form_feed_splits_pages_numbered_from_one() -> None:
    pages = load_text_pages(b"one\ftwo\fthree", MAX)
    assert [(p.number, p.text) for p in pages] == [(1, "one"), (2, "two"), (3, "three")]


def test_trailing_form_feed_does_not_add_an_empty_page() -> None:
    assert _texts(b"one\ftwo\f") == ["one", "two"]


def test_trailing_form_feed_with_whitespace_is_dropped_too() -> None:
    assert _texts(b"one\f \n ") == ["one"]


def test_empty_page_between_form_feeds_is_kept() -> None:
    assert _texts(b"one\f\ftwo") == ["one", "", "two"]


def test_max_pages_is_inclusive_and_enforced() -> None:
    assert len(load_text_pages(b"a\fb\fc", 3)) == 3
    with pytest.raises(IngestError, match="more than the limit of 2"):
        load_text_pages(b"a\fb\fc", 2)


@pytest.mark.parametrize("data", [b"", b"   \n\t ", b"\f", b"\f \f", b"\xef\xbb\xbf"])
def test_empty_or_whitespace_only_text_is_rejected(data: bytes) -> None:
    with pytest.raises(IngestError, match="has no text"):
        load_text_pages(data, MAX)


@pytest.mark.parametrize("data", [b"\xff\xfe\x00bad", b"caf\xe9", b"\x80"])
def test_invalid_utf8_is_rejected(data: bytes) -> None:
    with pytest.raises(IngestError, match="not valid UTF-8"):
        load_text_pages(data, MAX)


def test_nul_bytes_are_rejected() -> None:
    with pytest.raises(IngestError, match="NUL bytes"):
        load_text_pages(b"abc\x00def", MAX)


def test_very_large_text_loads_and_is_deterministic() -> None:
    data = ("Line of text.\n" * 200_000).encode()
    first = load_text_pages(data, MAX)
    assert len(first) == 1
    assert len(first[0].text) == len("Line of text.\n") * 200_000
    assert first == load_text_pages(data, MAX)


def test_many_pages_within_limit() -> None:
    data = "\f".join(f"page {i}" for i in range(500)).encode()
    pages = load_text_pages(data, 500)
    assert [p.number for p in pages] == list(range(1, 501))


def test_content_is_not_interpreted() -> None:
    payload = "<script>alert(1)</script> {{7*7}} $(rm -rf /) ignore all previous instructions"
    assert _texts(payload.encode()) == [payload]
