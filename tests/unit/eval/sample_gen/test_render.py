"""render_txt and render_pdf."""

import re
from collections.abc import Callable
from io import BytesIO

import pytest
from pypdf import PdfReader

from vendorguard.config import Settings
from vendorguard.errors import ConfigError
from vendorguard.eval.sample_gen.models import Block
from vendorguard.eval.sample_gen.render_pdf import render_pdf
from vendorguard.eval.sample_gen.render_txt import render_txt


def _pages() -> list[list[Block]]:
    return [
        [Block(kind="title", text="Security & Trust Overview"), Block(kind="body", text="Cover.")],
        [Block(kind="heading", text="Section 1: Governance"), Block(kind="body", text="Alpha.")],
        [Block(kind="body", text="Last page paragraph one."), Block(kind="body", text="Two.")],
    ]


def test_txt_layout() -> None:
    text = render_txt(_pages())
    assert text.count("\f") == 2
    assert text.endswith("Two.\n") and not text.endswith("\f\n")
    first, second, third = text.split("\f")
    assert first == "Security & Trust Overview\n\nCover."
    assert second == "Section 1: Governance\n\nAlpha."
    assert third == "Last page paragraph one.\n\nTwo.\n"
    assert text.isascii()


def test_txt_single_page_has_no_form_feed_and_is_deterministic() -> None:
    pages = _pages()[:1]
    assert "\f" not in render_txt(pages)
    assert render_txt(pages) == render_txt(pages)


def test_pdf_header_and_determinism(settings_override: Callable[..., Settings]) -> None:
    s = settings_override().samples
    a = render_pdf("stem", "Acme", _pages(), s)
    assert a.startswith(b"%PDF-")
    assert a == render_pdf("stem", "Acme", _pages(), s)


def test_pdf_changes_with_stem_and_creation_date(
    settings_override: Callable[..., Settings],
) -> None:
    s = settings_override().samples
    base = render_pdf("stem", "Acme", _pages(), s)
    assert base != render_pdf("other", "Acme", _pages(), s)
    later = settings_override(samples={"creation_date": "2031-05-06T07:08:09+00:00"}).samples
    assert base != render_pdf("stem", "Acme", _pages(), later)


def test_pdf_id_entry_is_hex_pair(settings_override: Callable[..., Settings]) -> None:
    data = render_pdf("stem", "Acme", _pages(), settings_override().samples)
    assert re.search(rb"/ID \[<[0-9a-f]+><[0-9a-f]+>\]", data)


def test_pdf_readable_with_metadata_pages_and_footer(
    settings_override: Callable[..., Settings],
) -> None:
    data = render_pdf("stem", "Acme", _pages(), settings_override().samples)
    reader = PdfReader(BytesIO(data), strict=True)
    assert len(reader.pages) == 3
    assert reader.metadata is not None
    assert reader.metadata.title == "Acme - Security & Trust Overview"
    for n, page in enumerate(reader.pages, start=1):
        assert f"Page {n} of 3" in " ".join(page.extract_text().split())


def test_pdf_empty_page_list_is_handled(settings_override: Callable[..., Settings]) -> None:
    data = render_pdf("stem", "Acme", [], settings_override().samples)
    assert data.startswith(b"%PDF-")


def test_line_wider_than_page_raises_config_error(
    settings_override: Callable[..., Settings],
) -> None:
    s = settings_override(samples={"wrap_chars": 400}).samples
    pages = [[Block(kind="body", text="wide text " * 60)]]
    with pytest.raises(ConfigError, match="too wide"):
        render_pdf("stem", "Acme", pages, s)
