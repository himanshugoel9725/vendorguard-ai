"""Plain-text and Markdown loader: a form feed is a page break."""

from vendorguard.errors import IngestError
from vendorguard.models.document import Page

PAGE_BREAK = "\f"


def load_text_pages(data: bytes, max_pages: int) -> list[Page]:
    """Decode UTF-8 (a BOM is ignored), normalise newlines and split pages at form feeds."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IngestError("the file is not valid UTF-8 text") from exc
    if "\x00" in text:
        raise IngestError("the file contains NUL bytes, so it is not a text document")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    parts = text.split(PAGE_BREAK)
    if len(parts) > 1 and not parts[-1].strip():
        parts.pop()  # a trailing form feed does not start an empty page
    if not any(part.strip() for part in parts):
        raise IngestError("the file has no text")
    if len(parts) > max_pages:
        raise IngestError(f"the file has {len(parts)} pages, more than the limit of {max_pages}")
    return [Page(number=i, text=part) for i, part in enumerate(parts, start=1)]


__all__ = ["load_text_pages"]
