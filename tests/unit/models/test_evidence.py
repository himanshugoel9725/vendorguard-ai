"""Tests for vendorguard.models.evidence."""

import pytest
from pydantic import ValidationError

from vendorguard.models.evidence import Chunk, Citation, DraftCitation, ScoredChunk


def make_chunk(**kw: object) -> Chunk:
    data: dict = {
        "chunk_id": "abc:p1:c0",
        "doc_id": "abc",
        "page": 1,
        "text": "hello",
        "char_start": 0,
        "char_end": 5,
    }
    data.update(kw)
    return Chunk(**data)


def test_chunk_roundtrip_and_equal_span() -> None:
    c = make_chunk(char_start=3, char_end=3, text="日本")
    assert Chunk.model_validate_json(c.model_dump_json()) == c


@pytest.mark.parametrize(
    "kw",
    [
        {"char_start": 5, "char_end": 4},
        {"page": 0},
        {"text": ""},
        {"chunk_id": ""},
        {"doc_id": ""},
        {"char_start": -1},
        {"bogus": 1},
    ],
)
def test_chunk_rejects(kw: dict) -> None:
    with pytest.raises(ValidationError):
        make_chunk(**kw)


def test_chunk_frozen() -> None:
    with pytest.raises(ValidationError):
        make_chunk().text = "x"  # type: ignore[misc]


def test_scored_chunk_vector_optional_and_roundtrip() -> None:
    s = ScoredChunk(chunk=make_chunk(), score=0.5, bm25=1.0)
    assert s.vector is None
    assert ScoredChunk.model_validate_json(s.model_dump_json()) == s
    s2 = ScoredChunk(chunk=make_chunk(), score=0.5, bm25=1.0, vector=0.2)
    assert s2.vector == 0.2


def test_draft_citation_fields_only() -> None:
    assert set(DraftCitation.model_fields) == {"chunk_id", "quote"}
    with pytest.raises(ValidationError):
        DraftCitation(chunk_id="", quote="q")
    with pytest.raises(ValidationError):
        DraftCitation(chunk_id="c", quote="")
    with pytest.raises(ValidationError):
        DraftCitation(chunk_id="c", quote="q", page=1)  # type: ignore[call-arg]


def test_citation_defaults_and_roundtrip() -> None:
    c = Citation(chunk_id="c", quote="q")
    assert (c.doc_id, c.page, c.valid, c.similarity) == (None, None, None, None)
    full = Citation(chunk_id="c", quote="q", doc_id="d", page=2, valid=True, similarity=0.9)
    assert Citation.model_validate_json(full.model_dump_json()) == full


@pytest.mark.parametrize("kw", [{"page": 0}, {"similarity": -0.1}, {"similarity": 1.1}])
def test_citation_rejects(kw: dict) -> None:
    with pytest.raises(ValidationError):
        Citation(chunk_id="c", quote="q", **kw)


def test_citation_bounds_accepted() -> None:
    assert Citation(chunk_id="c", quote="q", similarity=0).similarity == 0
    assert Citation(chunk_id="c", quote="q", similarity=1).similarity == 1


def test_citation_is_draft_citation() -> None:
    assert isinstance(Citation(chunk_id="c", quote="q"), DraftCitation)
