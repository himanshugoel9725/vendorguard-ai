"""Source documents: pages of text with a content hash."""

from typing import Annotated

from pydantic import Field, model_validator

from vendorguard.models._base import ContractModel, NonEmptyStr, Sha256


class Page(ContractModel):
    """One page of extracted text (1-based number)."""

    number: Annotated[int, Field(ge=1)]
    text: str


class Document(ContractModel):
    """A loaded vendor document. ``doc_id`` is a prefix of ``sha256``."""

    doc_id: NonEmptyStr
    filename: NonEmptyStr
    media_type: NonEmptyStr
    sha256: Sha256
    pages: list[Page]

    @model_validator(mode="after")
    def _pages_numbered_in_order(self) -> "Document":
        if [p.number for p in self.pages] != list(range(1, len(self.pages) + 1)):
            raise ValueError("pages must be numbered 1..n in order")
        return self


__all__ = ["Document", "Page"]
