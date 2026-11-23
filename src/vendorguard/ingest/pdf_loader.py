"""PDF loader: per-page text with pypdf. Encrypted and image-only (scanned) PDFs are refused."""

from io import BytesIO

from pypdf import PdfReader

from vendorguard.errors import IngestError
from vendorguard.models.document import Page

PDF_MAGIC = b"%PDF-"


def load_pdf_pages(data: bytes, max_pages: int) -> list[Page]:
    """Extract the text of every page; raises IngestError for anything that is not a usable PDF."""
    if not data.startswith(PDF_MAGIC):
        raise IngestError("the file is not a PDF (missing %PDF- header)")
    try:  # pypdf raises many exception types on corrupt input; all become IngestError
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise IngestError("the PDF is encrypted; remove the password and upload it again")
        if len(reader.pages) > max_pages:
            raise IngestError(
                f"the PDF has {len(reader.pages)} pages, more than the limit of {max_pages}"
            )
        pages = [
            Page(number=i, text=page.extract_text() or "")
            for i, page in enumerate(reader.pages, start=1)
        ]
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
