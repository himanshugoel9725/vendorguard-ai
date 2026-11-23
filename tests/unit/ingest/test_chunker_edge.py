"""Chunker edge cases: unicode offsets, boundary settings, many pages, short doc ids."""

import pytest
from pydantic import ValidationError

from vendorguard.config_models.core import ChunkingSettings
from vendorguard.ingest.chunker import chunk_document, chunk_page
from vendorguard.models.document import Document, Page


def _doc(texts: list[str], doc_id: str = "abcdef0123456789") -> Document:
    return Document(
        doc_id=doc_id,
        filename="x.txt",
        media_type="text/plain",
        sha256="0" * 64,
        pages=[Page(number=i, text=t) for i, t in enumerate(texts, start=1)],
    )


def test_offsets_are_exact_with_multibyte_text() -> None:
    text = "Zürich speichert Daten. 数据在欧洲。 Données chiffrées! 🔒 Secure storage? Yes. " * 8
    settings = ChunkingSettings(chunk_chars=90, overlap_chars=20, min_chunk_chars=10)
    doc = _doc([text.strip()])
    chunks = chunk_document(doc, settings)
    assert len(chunks) > 3
    for c in chunks:
        assert doc.pages[0].text[c.char_start : c.char_end] == c.text
        assert c.text == c.text.strip()


def test_chinese_text_without_spaces_is_hard_cut_with_exact_offsets() -> None:
    text = "数据" * 100
    settings = ChunkingSettings(chunk_chars=50, overlap_chars=0, min_chunk_chars=5)
    spans = chunk_page(text, settings)
    assert all(end - start <= 50 + 5 for start, end in spans)
    assert "".join(text[s:e] for s, e in spans) == text


def test_overlap_just_below_chunk_chars_still_terminates_and_covers() -> None:
    settings = ChunkingSettings(chunk_chars=100, overlap_chars=99, min_chunk_chars=1)
    text = " ".join(f"Sentence number {i} here." for i in range(40))
    spans = chunk_page(text, settings)
    assert spans[0][0] == 0
    assert spans[-1][1] == len(text)
    assert all(a[0] < b[0] for a, b in zip(spans, spans[1:], strict=False))


def test_min_chunk_equal_to_chunk_chars_is_allowed() -> None:
    settings = ChunkingSettings(chunk_chars=60, overlap_chars=10, min_chunk_chars=60)
    text = " ".join(f"Item {i} is documented." for i in range(20))
    spans = chunk_page(text, settings)
    assert spans[-1][1] == len(text)
    assert spans[0][0] == 0


def test_validators_reject_inconsistent_sizes() -> None:
    with pytest.raises(ValidationError):
        ChunkingSettings(chunk_chars=50, overlap_chars=50, min_chunk_chars=10)
    with pytest.raises(ValidationError):
        ChunkingSettings(chunk_chars=50, overlap_chars=10, min_chunk_chars=51)


def test_many_pages_get_their_own_ids_and_stay_in_page_order() -> None:
    settings = ChunkingSettings(chunk_chars=80, overlap_chars=10, min_chunk_chars=10)
    texts = [f"Page {i} says something. It also says more here." for i in range(300)]
    chunks = chunk_document(_doc(texts), settings)
    assert [c.page for c in chunks] == sorted(c.page for c in chunks)
    assert {c.page for c in chunks} == set(range(1, 301))
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    assert chunks[-1].chunk_id.startswith("abcdef012345:p300:c")


def test_doc_id_shorter_than_twelve_characters_is_used_whole() -> None:
    settings = ChunkingSettings(chunk_chars=100, overlap_chars=10, min_chunk_chars=10)
    chunks = chunk_document(_doc(["Hello there."], doc_id="abc"), settings)
    assert chunks[0].chunk_id == "abc:p001:c000"
    assert chunks[0].doc_id == "abc"


def test_empty_document_and_whitespace_pages_give_no_chunks() -> None:
    settings = ChunkingSettings(chunk_chars=100, overlap_chars=10, min_chunk_chars=10)
    assert chunk_document(_doc([]), settings) == []
    assert chunk_document(_doc(["", "  \n\n "]), settings) == []


def test_page_numbers_above_999_widen_the_id() -> None:
    settings = ChunkingSettings(chunk_chars=100, overlap_chars=10, min_chunk_chars=10)
    doc = Document(
        doc_id="a" * 16,
        filename="x.txt",
        media_type="text/plain",
        sha256="0" * 64,
        pages=[Page(number=i, text="Hi.") for i in range(1, 1001)],
    )
    assert chunk_document(doc, settings)[-1].chunk_id == "a" * 12 + ":p1000:c000"
