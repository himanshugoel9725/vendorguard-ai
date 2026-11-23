"""Chunks, retrieval results and citations."""

from typing import Annotated

from pydantic import Field, model_validator

from vendorguard.models._base import ContractModel, NonEmptyStr, NonNegInt, Probability


class Chunk(ContractModel):
    """A page-bounded span of text. ``chunk_id`` is ``<doc_id[:12]>:p<page>:c<n>``."""

    chunk_id: NonEmptyStr
    doc_id: NonEmptyStr
    page: Annotated[int, Field(ge=1)]
    text: NonEmptyStr
    char_start: NonNegInt
    char_end: NonNegInt

    @model_validator(mode="after")
    def _span_is_ordered(self) -> "Chunk":
        if self.char_end < self.char_start:
            raise ValueError("char_end must not be before char_start")
        return self


class ScoredChunk(ContractModel):
    """A retrieved chunk: the fused score, the two scaled signals and the two raw signals.

    ``score`` ranks chunks within one query. ``bm25_raw`` and ``vector_raw`` are the unscaled
    values, the only ones with an absolute meaning (for example for the triage gate).
    """

    chunk: Chunk
    score: float
    bm25: float
    vector: float | None = None
    bm25_raw: float = 0.0
    vector_raw: float | None = None


class DraftCitation(ContractModel):
    """What the LLM returns for one quote: the chunk it came from and the verbatim text."""

    chunk_id: NonEmptyStr
    quote: NonEmptyStr


class Citation(DraftCitation):
    """A draft citation after the citation checker ran (document, page, validity, similarity)."""

    doc_id: str | None = None
    page: Annotated[int, Field(ge=1)] | None = None
    valid: bool | None = None
    similarity: Probability | None = None


__all__ = ["Chunk", "Citation", "DraftCitation", "ScoredChunk"]
