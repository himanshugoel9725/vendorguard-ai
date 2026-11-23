"""Validation of the sample generator data contracts."""

import pytest
from pydantic import ValidationError

from vendorguard.eval.sample_gen.models import (
    Block,
    ComposedSample,
    EvidenceEntry,
    EvidenceFile,
    GeneratedSample,
)
from vendorguard.eval.specs import SampleState


def test_block_kinds_and_defaults() -> None:
    for kind in ("title", "subtitle", "heading", "body", "injection"):
        assert Block(kind=kind, text="x").control_id is None  # type: ignore[arg-type]


def test_block_rejects_unknown_kind_empty_text_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Block(kind="footer", text="x")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Block(kind="body", text="")
    with pytest.raises(ValidationError):
        Block(kind="body", text="x", color="red")  # type: ignore[call-arg]


def test_block_is_frozen() -> None:
    block = Block(kind="body", text="x")
    with pytest.raises(ValidationError):
        block.text = "y"  # type: ignore[misc]


def test_evidence_entry_defaults_and_state_coercion() -> None:
    entry = EvidenceEntry(state="met")  # type: ignore[arg-type]
    assert entry.state is SampleState.MET
    assert entry.page is None and entry.sentence is None and entry.variant is None
    with pytest.raises(ValidationError):
        EvidenceEntry(state="unknown")  # type: ignore[arg-type]


def test_evidence_file_requires_names() -> None:
    entry = EvidenceEntry(state=SampleState.MISSING)
    ok = EvidenceFile(vendor_id="v", doc="v.pdf", page_count=2, controls={"GOV-01": entry})
    assert ok.controls["GOV-01"] is entry
    with pytest.raises(ValidationError):
        EvidenceFile(vendor_id="", doc="v.pdf", page_count=2, controls={})


def test_composed_sample_round_trips() -> None:
    sample = ComposedSample(pages=[[Block(kind="body", text="x")]], evidence={})
    assert ComposedSample.model_validate(sample.model_dump()) == sample


def test_generated_sample_requires_stem(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError):
        GeneratedSample(stem="", pdf=tmp_path, txt=tmp_path, evidence=tmp_path, sha256={})
