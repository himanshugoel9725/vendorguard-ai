"""Load a vendor document: extension allowlist, size limit, content hash, page-aware text."""

import os
import re
from pathlib import Path, PurePath

from vendorguard.config_models.core import IngestSettings
from vendorguard.errors import IngestError
from vendorguard.ingest.pdf_loader import load_pdf_pages
from vendorguard.ingest.text_loader import load_text_pages
from vendorguard.models.document import Document
from vendorguard.utils.hashing import sha256_bytes

DOC_ID_CHARS = 16  # chunk IDs use the first 12 characters of the document ID
BYTES_PER_MB = 1024 * 1024
FALLBACK_NAME = "document"
MEDIA_TYPES = {".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown"}
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(name: str, max_chars: int) -> str:
    """Base name only, safe characters only; never empty, hidden or longer than ``max_chars``."""
    base = PurePath(name.replace("\\", "/")).name
    cleaned = _UNSAFE.sub("_", base).lstrip(".")
    stem, ext = os.path.splitext(cleaned or FALLBACK_NAME)
    return stem[: max(max_chars - len(ext), 1)] + ext


def load_document(path: Path, settings: IngestSettings) -> Document:
    """Read ``path`` into a ``Document``; raises IngestError (naming the file) on any problem."""
    shown = sanitize_filename(path.name, settings.max_filename_chars)
    extension = path.suffix.lower()
    if extension not in {e.lower() for e in settings.allowed_extensions}:
        raise IngestError(f"{shown}: file type '{extension}' is not allowed")
    limit = settings.max_file_mb * BYTES_PER_MB
    try:
        if not path.is_file():
            raise IngestError(f"{shown}: not a file")
        with path.open("rb") as handle:
            data = handle.read(limit + 1)  # bounded read: a file that grows cannot exceed the limit
    except OSError as exc:
        raise IngestError(f"{shown}: cannot be read ({type(exc).__name__})") from exc
    if len(data) > limit:
        raise IngestError(f"{shown}: larger than the limit of {settings.max_file_mb} MB")
    try:
        if extension == ".pdf":
            pages = load_pdf_pages(data, settings.max_pages, settings.max_text_chars)
        else:
            pages = load_text_pages(data, settings.max_pages, settings.max_text_chars)
    except IngestError as exc:
        raise IngestError(f"{shown}: {exc}") from exc
    digest = sha256_bytes(data)
    return Document(
        doc_id=digest[:DOC_ID_CHARS],
        filename=shown,
        media_type=MEDIA_TYPES.get(extension, "application/octet-stream"),
        sha256=digest,
        pages=pages,
    )


__all__ = ["load_document", "sanitize_filename"]
