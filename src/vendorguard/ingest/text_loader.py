"""Plain-text and Markdown loader: a form feed is a page break."""

from vendorguard.errors import IngestError
from vendorguard.ingest.control_chars import remove_control_characters
from vendorguard.models.document import Page

PAGE_BREAK = "\f"


def load_text_pages(data: bytes, max_pages: int, max_chars: int | None = None) -> list[Page]:
    """Decode UTF-8 (a BOM is ignored), normalise newlines and split pages at form feeds."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IngestError("the file is not valid UTF-8 text") from exc
    if "\x00" in text:
        raise IngestError("the file contains NUL bytes, so it is not a text document")
    text = remove_control_characters(text.replace("\r\n", "\n").replace("\r", "\n"))
    parts = text.split(PAGE_BREAK)
    if len(parts) > 1 and not parts[-1].strip():
        parts.pop()  # a trailing form feed does not start an empty page
    if not any(part.strip() for part in parts):
        raise IngestError("the file has no text")
    if len(parts) > max_pages:
        raise IngestError(f"the file has {len(parts)} pages, more than the limit of {max_pages}")
    if max_chars is not None and sum(len(part) for part in parts) > max_chars:
        raise IngestError(f"the text is longer than the limit of {max_chars} characters")
    return [Page(number=i, text=part) for i, part in enumerate(parts, start=1)]


__all__ = ["load_text_pages"]
