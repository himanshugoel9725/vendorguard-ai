"""PDF loader: per-page text with pypdf. Encrypted and image-only (scanned) PDFs are refused."""

from io import BytesIO

from pypdf import PdfReader

from vendorguard.errors import IngestError
from vendorguard.ingest.control_chars import remove_control_characters
from vendorguard.models.document import Page

PDF_MAGIC = b"%PDF-"


def load_pdf_pages(data: bytes, max_pages: int, max_chars: int | None = None) -> list[Page]:
    """Extract the text of every page; raises IngestError for anything that is not a usable PDF.

    Extraction stops as soon as the text exceeds ``max_chars`` (when given), so a small PDF that
    expands into a huge amount of text cannot exhaust memory.
    """
    if not data.startswith(PDF_MAGIC):
        raise IngestError("the file is not a PDF (missing %PDF- header)")
    pages: list[Page] = []
    total = 0
    try:  # pypdf raises many exception types on corrupt input; all become IngestError
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise IngestError("the PDF is encrypted; remove the password and upload it again")
        if len(reader.pages) > max_pages:
            raise IngestError(
                f"the PDF has {len(reader.pages)} pages, more than the limit of {max_pages}"
            )
        for number, page in enumerate(reader.pages, start=1):
            text = remove_control_characters(page.extract_text() or "")
            total += len(text)
            if max_chars is not None and total > max_chars:
                raise IngestError(
                    f"the PDF text is longer than the limit of {max_chars} characters"
                )
            pages.append(Page(number=number, text=text))
    except IngestError:
        raise
    except Exception as exc:
        raise IngestError(f"the PDF cannot be read ({type(exc).__name__})") from exc
    if not any(page.text.strip() for page in pages):
        raise IngestError(
            "the PDF has no extractable text; scanned PDFs need OCR, which is not supported"
        )
    return pages


__all__ = ["load_pdf_pages"]
