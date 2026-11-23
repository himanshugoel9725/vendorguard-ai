"""Phase 3 review fixes: header/footer zones, control characters, text cap, hyphen rule."""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from vendorguard.config import Settings
from vendorguard.errors import IngestError
from vendorguard.ingest import pdf_loader
from vendorguard.ingest.chunker import ID_DOC_CHARS
from vendorguard.ingest.control_chars import remove_control_characters
from vendorguard.ingest.loader import DOC_ID_CHARS, load_document
from vendorguard.ingest.pdf_loader import load_pdf_pages
from vendorguard.ingest.text_cleaner import clean_document, dehyphenate, strip_repeated_lines
from vendorguard.ingest.text_loader import load_text_pages
from vendorguard.models.document import Document, Page


def _doc(*texts: str) -> Document:
    return Document(
        doc_id="d" * 16,
        filename="x.txt",
        media_type="text/plain",
        sha256="0" * 64,
        pages=[Page(number=i, text=t) for i, t in enumerate(texts, start=1)],
    )


# --- header / footer zone ------------------------------------------------------------------------


def test_body_lines_that_differ_only_in_digits_survive_in_a_two_page_document() -> None:
    """The reviewer's case: both retention periods are evidence, not footers."""
    pages = [
        "Retention\nBackups kept 30 days\nWe test restores.\nMore text.\nAnd more.\nFooter 1",
        "Retention\nBackups kept 90 days\nLogs are kept a year.\nOther.\nAnd more.\nFooter 2",
    ]
    out = strip_repeated_lines(pages, 0.6, scan_lines=1)
    assert "Backups kept 30 days" in out[0] and "Backups kept 90 days" in out[1]
    assert not any("Footer" in p for p in out)  # the true footer (last line) is still removed
    assert not any(p.startswith("Retention") for p in out)  # and so is the true header


def test_only_the_first_and_last_lines_are_candidates() -> None:
    pages = [f"top\nbody {n} unique\nmiddle repeated\nbody {n} other\nbottom" for n in range(4)]
    out = strip_repeated_lines(pages, 0.6, scan_lines=1)
    assert all("middle repeated" in p for p in out)
    assert not any(p.startswith("top") or p.endswith("bottom") for p in out)


def test_scan_lines_larger_than_the_page_covers_every_line() -> None:
    pages = ["a\nb", "a\nb", "a\nb"]
    assert strip_repeated_lines(pages, 0.6, scan_lines=50) == ["", "", ""]


def test_clean_document_uses_the_configured_scan_depth(
    settings_override: Callable[..., Settings],
) -> None:
    doc = _doc(*[f"Header\nSecond line\nbody {n}\nFooter {n}" for n in range(3)])
    narrow = clean_document(doc, settings_override(ingest={"repeated_line_scan_lines": 1}).ingest)
    wide = clean_document(doc, settings_override(ingest={"repeated_line_scan_lines": 2}).ingest)
    assert "Second line" in narrow.pages[0].text and "Second line" not in wide.pages[0].text


# --- control characters --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("a\x01b\x7fc", "abc"),  # C0 control and DEL
        ("a\x85b\x9fc", "abc"),  # C1 controls
        ("a\ud800b", "ab"),  # lone surrogate: breaks UTF-8 encoding and hashing later
        ("a‮b⁦c", "abc"),  # bidirectional override and isolate
        ("a​b﻿c", "abc"),  # zero-width space and byte-order mark inside text
        ("line\nnext\tcol\fpage", "line\nnext\tcol\fpage"),  # layout characters stay
        ("fire­wall", "fire­wall"),  # soft hyphen is left for the cleaner
        ("café 中文 \U0001f600", "café 中文 \U0001f600"),
    ],
)
def test_remove_control_characters(raw: str, clean: str) -> None:
    assert remove_control_characters(raw) == clean
    assert remove_control_characters(clean) == clean  # idempotent
    remove_control_characters(raw).encode("utf-8")  # always encodable


def test_text_loader_drops_other_control_characters_but_still_rejects_nul() -> None:
    pages = load_text_pages("a\x01b‮c\n".encode(), 10)
    assert pages[0].text == "abc\n"
    with pytest.raises(IngestError, match="NUL"):
        load_text_pages(b"a\x00b", 10)


def test_pdf_text_is_stripped_of_control_characters(monkeypatch: pytest.MonkeyPatch) -> None:
    """pypdf can emit NULs and lone surrogates; they must not reach hashing or JSON."""

    class FakePage:
        def extract_text(self) -> str:
            return "Clean\x00 text\ud800 here‮."

    class FakeReader:
        is_encrypted = False
        pages = [FakePage(), FakePage()]

        def __init__(self, stream: Any) -> None:
            pass

    monkeypatch.setattr(pdf_loader, "PdfReader", FakeReader)
    pages = load_pdf_pages(b"%PDF-1.4 fake", 10)
    assert [p.text for p in pages] == ["Clean text here."] * 2
    pages[0].text.encode("utf-8")


# --- text size cap and bounded read --------------------------------------------------------------


def test_text_over_the_character_limit_is_refused() -> None:
    assert len(load_text_pages(b"x" * 100, 10, max_chars=100)) == 1
    with pytest.raises(IngestError, match="longer than the limit of 99 characters"):
        load_text_pages(b"x" * 100, 10, max_chars=99)


def test_pdf_extraction_stops_at_the_character_limit(project_root: Path) -> None:
    data = (project_root / "data/samples/quillfield.pdf").read_bytes()
    assert len(load_pdf_pages(data, 300, max_chars=100_000)) == 9
    with pytest.raises(IngestError, match="longer than the limit of 500 characters"):
        load_pdf_pages(data, 300, max_chars=500)


def test_load_document_applies_max_text_chars_from_settings(
    tmp_path: Path, settings_override: Callable[..., Settings]
) -> None:
    path = tmp_path / "big.txt"
    path.write_text("word " * 100, encoding="utf-8")
    with pytest.raises(IngestError, match=r"^big\.txt: the text is longer than the limit of 100"):
        load_document(path, settings_override(ingest={"max_text_chars": 100}).ingest)
    assert load_document(path, settings_override().ingest).pages


def test_the_read_is_bounded_even_if_the_file_grows_after_the_size_check(
    tmp_path: Path, settings_override: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The size is decided by what is actually read, not by an earlier stat()."""
    path = tmp_path / "grows.txt"
    path.write_text("small", encoding="utf-8")
    ingest = settings_override(ingest={"max_file_mb": 1}).ingest
    real_stat = os.stat_result
    monkeypatch.setattr(
        Path, "stat", lambda self, **kw: real_stat((0o100644, 0, 0, 1, 0, 0, 5, 0, 0, 0))
    )
    path.write_bytes(b"x" * (1024 * 1024 + 1))  # grows after the (patched) size check
    with pytest.raises(IngestError, match="larger than the limit of 1 MB"):
        load_document(path, ingest)


# --- hyphen rule and shared constants ------------------------------------------------------------


def test_markdown_table_rules_are_not_joined() -> None:
    table = "| a | b |\n|---|---|\n---\n|---|"
    assert dehyphenate(table, set()) == table


def test_a_hyphen_after_a_letter_or_digit_still_joins_across_the_break() -> None:
    assert dehyphenate("ISO-\n27001 and TLS-\n1", set()) == "ISO-27001 and TLS-1"


def test_chunk_ids_never_need_more_of_the_doc_id_than_the_loader_provides() -> None:
    assert ID_DOC_CHARS <= DOC_ID_CHARS
