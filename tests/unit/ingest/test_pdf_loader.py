"""pdf_loader.load_pdf_pages: text extraction and every refusal path (PDFs built in tmp_path)."""

from io import BytesIO

import pytest
from fpdf import FPDF
from pypdf import PdfReader, PdfWriter

from vendorguard.errors import IngestError
from vendorguard.ingest.pdf_loader import load_pdf_pages

MAX = 50


def _text_pdf(*page_texts: str) -> bytes:
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    for text in page_texts:
        pdf.add_page()
        pdf.cell(text=text)
    return bytes(pdf.output())


def _blank_pdf(pages: int = 1, password: str | None = None) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    if password:
        writer.encrypt(password)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_text_is_extracted_per_page_numbered_from_one() -> None:
    pages = load_pdf_pages(_text_pdf("Alpha policy", "Beta controls"), MAX)
    assert [p.number for p in pages] == [1, 2]
    assert "Alpha policy" in pages[0].text
    assert "Beta controls" in pages[1].text


def test_blank_page_between_text_pages_is_kept_as_empty_text() -> None:
    out = PdfWriter()
    out.append(PdfReader(BytesIO(_text_pdf("First page text"))))
    out.add_blank_page(width=200, height=200)
    out.append(PdfReader(BytesIO(_text_pdf("Third page text"))))
    buf = BytesIO()
    out.write(buf)
    pages = load_pdf_pages(buf.getvalue(), MAX)
    assert [p.number for p in pages] == [1, 2, 3]
    assert pages[1].text.strip() == ""
    assert "Third page text" in pages[2].text


def test_single_text_page_is_extracted_exactly() -> None:
    pages = load_pdf_pages(_text_pdf("Plain ASCII text"), MAX)
    assert pages[0].text.strip() == "Plain ASCII text"


def test_extraction_is_deterministic() -> None:
    data = _text_pdf("Same bytes", "Same result")
    assert load_pdf_pages(data, MAX) == load_pdf_pages(data, MAX)


@pytest.mark.parametrize("data", [b"", b"hello", b"PK\x03\x04zip", b" %PDF-1.4"])
def test_missing_pdf_header_is_rejected(data: bytes) -> None:
    with pytest.raises(IngestError, match="missing %PDF- header"):
        load_pdf_pages(data, MAX)


@pytest.mark.parametrize(
    "data", [b"%PDF-", b"%PDF-1.4\ngarbage garbage", b"%PDF-1.4\n" + b"\x00" * 100]
)
def test_corrupt_pdf_is_rejected(data: bytes) -> None:
    with pytest.raises(IngestError, match="cannot be read"):
        load_pdf_pages(data, MAX)


def test_truncated_pdf_is_rejected() -> None:
    data = _text_pdf("Some text on a page")
    with pytest.raises(IngestError):
        load_pdf_pages(data[: len(data) // 3], MAX)


def test_encrypted_pdf_is_rejected() -> None:
    with pytest.raises(IngestError, match="is encrypted"):
        load_pdf_pages(_blank_pdf(password="pw"), MAX)


def test_blank_pdf_needs_ocr() -> None:
    with pytest.raises(IngestError, match="scanned PDFs need OCR"):
        load_pdf_pages(_blank_pdf(2), MAX)


def test_too_many_pages_is_rejected_and_the_limit_is_inclusive() -> None:
    data = _text_pdf("a", "b", "c")
    assert len(load_pdf_pages(data, 3)) == 3
    with pytest.raises(IngestError, match="3 pages, more than the limit of 2"):
        load_pdf_pages(data, 2)


def test_page_limit_is_checked_before_text_extraction() -> None:
    with pytest.raises(IngestError, match="more than the limit"):
        load_pdf_pages(_blank_pdf(5), 4)
