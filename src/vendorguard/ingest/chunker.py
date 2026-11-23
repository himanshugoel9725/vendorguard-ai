"""Page-aware, sentence-boundary chunking with character offsets into the cleaned page text.

A chunk never crosses a page. ``chunk_chars`` is a soft limit: when the last chunk of a page adds
fewer than ``min_chunk_chars`` of new text (beyond the overlap), it is merged into the previous
chunk, which can then exceed ``chunk_chars`` by less than ``min_chunk_chars``. Chunk IDs are
``<doc_id[:12]>:p<page>:c<n>`` with the page 1-based and ``n`` the 0-based index of the chunk on
its page, so the same document and settings always give the same IDs.
"""

import re

from vendorguard.config_models.core import ChunkingSettings
from vendorguard.models.document import Document
from vendorguard.models.evidence import Chunk

ID_DOC_CHARS = 12
_BREAK = re.compile(r"(?<=[.!?])\s+|\n{2,}")
Span = tuple[int, int]


def sentence_spans(text: str) -> list[Span]:
    """(start, end) offsets of each sentence or paragraph fragment, without surrounding space."""
    spans: list[Span] = []
    start = 0
    for match in [*_BREAK.finditer(text), None]:
        end = match.start() if match else len(text)
        piece = text[start:end]
        lead = len(piece) - len(piece.lstrip())
        if piece.strip():
            spans.append((start + lead, start + len(piece.rstrip())))
        start = match.end() if match else end
    return spans


def _split_long(text: str, span: Span, limit: int) -> list[Span]:
    """Cut a span longer than ``limit`` at spaces (hard cut only inside an over-long word)."""
    start, end = span
    pieces: list[Span] = []
    while end - start > limit:
        cut = text.rfind(" ", start + 1, start + limit + 1)
        cut = cut if cut > start else start + limit
        pieces.append((start, cut))
        start = cut
        while start < end and text[start].isspace():
            start += 1
    pieces.append((start, end))
    return pieces


def _pack(units: list[Span], chunk_chars: int, overlap_chars: int) -> list[Span]:
    """Greedily fill chunks; each next chunk re-uses trailing units up to ``overlap_chars``."""
    chunks: list[Span] = []
    first = 0
    while first < len(units):
        last = first + 1
        while last < len(units) and units[last][1] - units[first][0] <= chunk_chars:
            last += 1
        chunks.append((units[first][0], units[last - 1][1]))
        if last >= len(units):
            break
        nxt = last
        while nxt - 1 > first and units[last - 1][1] - units[nxt - 1][0] <= overlap_chars:
            nxt -= 1
        first = nxt
    return chunks


def chunk_page(text: str, settings: ChunkingSettings) -> list[Span]:
    """Chunk spans of one page of cleaned text."""
    units = [
        piece
        for span in sentence_spans(text)
        for piece in _split_long(text, span, settings.chunk_chars)
    ]
    chunks = _pack(units, settings.chunk_chars, settings.overlap_chars)
    if len(chunks) >= 2:
        before, tail = chunks[-2], chunks[-1]
        if tail[1] - max(tail[0], before[1]) < settings.min_chunk_chars:
            chunks[-2:] = [(before[0], tail[1])]
    return chunks


def chunk_document(document: Document, settings: ChunkingSettings) -> list[Chunk]:
    """All chunks of a (cleaned) document, in page order."""
    chunks: list[Chunk] = []
    for page in document.pages:
        for index, (start, end) in enumerate(chunk_page(page.text, settings)):
            chunks.append(
                Chunk(
                    chunk_id=f"{document.doc_id[:ID_DOC_CHARS]}:p{page.number:03d}:c{index:03d}",
                    doc_id=document.doc_id,
                    page=page.number,
                    text=page.text[start:end],
                    char_start=start,
                    char_end=end,
                )
            )
    return chunks


__all__ = ["chunk_document", "chunk_page", "sentence_spans"]
