"""Data contracts of the sample generator: phrase bank, composed document, evidence map."""

from pathlib import Path
from typing import Literal

from vendorguard.eval.specs import SampleState
from vendorguard.models._base import ContractModel, NonEmptyStr
from vendorguard.models.vendor import DataCategory


class ControlPhrases(ContractModel):
    """Alternative one-sentence phrasings of one control in each non-missing state."""

    met: list[str]
    partial: list[str]
    not_met: list[str]


class PhraseBank(ContractModel):
    """Everything the generator may write: control sentences, filler, headings, cover wording."""

    version: int
    section_titles: dict[str, str]
    data_category_phrases: dict[DataCategory, str]
    filler: dict[str, list[str]]
    distractors: dict[str, list[str]]
    controls: dict[str, ControlPhrases]


class Block(ContractModel):
    """One paragraph, heading or title of the document."""

    kind: Literal["title", "subtitle", "heading", "body", "injection"]
    text: NonEmptyStr
    control_id: str | None = None


class EvidenceEntry(ContractModel):
    """Where the true evidence of one control sits (``None`` when the document is silent)."""

    state: SampleState
    page: int | None = None
    sentence: str | None = None
    variant: int | None = None


class EvidenceFile(ContractModel):
    """Contents of ``<stem>.evidence.json``: one entry per control."""

    vendor_id: NonEmptyStr
    doc: NonEmptyStr
    page_count: int
    controls: dict[str, EvidenceEntry]


class ComposedSample(ContractModel):
    """A document as pages of blocks, plus the evidence map (pages are 1-based, cover is 1)."""

    pages: list[list[Block]]
    evidence: dict[str, EvidenceEntry]


class GeneratedSample(ContractModel):
    """Files written for one spec and their SHA-256 hashes."""

    stem: NonEmptyStr
    pdf: Path
    txt: Path
    evidence: Path
    sha256: dict[str, str]


__all__ = [
    "Block",
    "ComposedSample",
    "ControlPhrases",
    "EvidenceEntry",
    "EvidenceFile",
    "GeneratedSample",
    "PhraseBank",
]
