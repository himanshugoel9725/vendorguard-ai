"""End-to-end checks of the sample generator: determinism, drift, PDF text, y1 -> y2 wording."""

import json
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from vendorguard.config import Settings
from vendorguard.eval.sample_gen import generate_all
from vendorguard.eval.sample_gen.models import GeneratedSample
from vendorguard.eval.sample_gen.writer import verify_pdf
from vendorguard.eval.specs import load_spec

STEMS = ["brightdock", "nimbara-hr", "nimbara-hr-y2", "quillfield"]


@pytest.fixture
def generate(
    settings_override: Callable[..., Settings], project_root: Path
) -> Callable[[Path], list[GeneratedSample]]:
    """Run the generator on the committed specs and phrase bank into a given folder."""
    s = settings_override(
        samples={
            "specs_dir": project_root / "data/samples/specs",
            "phrases_file": project_root / "data/samples/phrases.yaml",
        },
        paths={"controls_file": project_root / "config/controls/baseline_v1.yaml"},
    )

    def run(out: Path) -> list[GeneratedSample]:
        return generate_all(s.samples, s.decision.rule, s.paths.controls_file, out)

    return run


def test_two_runs_give_identical_sha256_for_every_output(
    generate: Callable[[Path], list[GeneratedSample]], tmp_path: Path
) -> None:
    """`make sample` twice: every PDF, text twin and evidence file is byte-identical."""
    first, second = generate(tmp_path / "a"), generate(tmp_path / "b")
    assert [g.stem for g in first] == STEMS
    assert [g.sha256 for g in first] == [g.sha256 for g in second]
    assert sum(len(g.sha256) for g in first) == 12


def test_committed_samples_match_a_fresh_generation(
    generate: Callable[[Path], list[GeneratedSample]], tmp_path: Path, project_root: Path
) -> None:
    """If the generator, phrases or specs change, `make sample` must be re-run and committed."""
    for sample in generate(tmp_path):
        for path in (sample.pdf, sample.txt, sample.evidence):
            committed = project_root / "data/samples" / path.name
            assert committed.read_bytes() == path.read_bytes(), f"{path.name} is stale: make sample"


def test_pypdf_extracts_every_evidence_sentence_from_its_page(project_root: Path) -> None:
    """The PDF text layer holds each recorded evidence sentence on the recorded page."""
    for stem in STEMS:
        reader = PdfReader(project_root / f"data/samples/{stem}.pdf", strict=True)
        evidence = json.loads((project_root / f"data/samples/{stem}.evidence.json").read_text())
        assert len(reader.pages) == evidence["page_count"] > 1
        assert len(evidence["controls"]) == 25
        for control_id, entry in evidence["controls"].items():
            if entry["state"] == "missing":
                assert entry["page"] is None and entry["sentence"] is None, control_id
                continue
            text = " ".join(reader.pages[entry["page"] - 1].extract_text().split()).lower()
            assert " ".join(entry["sentence"].split()).lower() in text, (stem, control_id)


def test_text_twin_has_the_same_pages_as_the_pdf(project_root: Path) -> None:
    """Form feeds split the twin into as many pages as the PDF, with the same evidence sentences."""
    for stem in STEMS:
        pages = (project_root / f"data/samples/{stem}.txt").read_text().split("\f")
        evidence = json.loads((project_root / f"data/samples/{stem}.evidence.json").read_text())
        assert len(pages) == evidence["page_count"]
        for control_id, entry in evidence["controls"].items():
            if entry["sentence"]:
                assert entry["sentence"] in pages[entry["page"] - 1], (stem, control_id)


def test_year2_reuses_wording_except_for_the_declared_changes(project_root: Path) -> None:
    """Only the fixed gaps and the new gap get new sentences in the year-2 document."""

    def sentences(stem: str) -> dict[str, str | None]:
        data = json.loads((project_root / f"data/samples/{stem}.evidence.json").read_text())
        return {c: e["sentence"] for c, e in data["controls"].items()}

    y1, y2 = sentences("nimbara-hr"), sentences("nimbara-hr-y2")
    spec = load_spec(project_root / "data/samples/specs/nimbara-hr-y2.yaml")
    assert spec.changes is not None
    changed = {c for c in y1 if y1[c] != y2[c]}
    assert changed == set(spec.changes.fixed) | set(spec.changes.new_gaps)


def test_injection_is_in_the_quillfield_text_but_never_cited_as_evidence(
    project_root: Path,
) -> None:
    """The planted paragraph is part of the document and is not any control's evidence."""
    text = (project_root / "data/samples/quillfield.txt").read_text().lower()
    assert "ignore all previous instructions" in text
    for stem in STEMS:
        evidence = json.loads((project_root / f"data/samples/{stem}.evidence.json").read_text())
        assert not any(
            "ignore all previous" in (e["sentence"] or "").lower()
            for e in evidence["controls"].values()
        )
        other = (project_root / f"data/samples/{stem}.txt").read_text().lower()
        assert ("ignore all previous instructions" in other) == (stem == "quillfield")


def test_verify_pdf_reports_a_missing_sentence_and_a_page_count_mismatch(
    generate: Callable[[Path], list[GeneratedSample]], tmp_path: Path
) -> None:
    """The post-render check fails loudly when the PDF and the composition disagree."""
    from vendorguard.eval.sample_gen.models import ComposedSample, EvidenceEntry
    from vendorguard.eval.specs import SampleState

    sample = generate(tmp_path)[0]
    pdf = sample.pdf.read_bytes()
    pages = len(PdfReader(BytesIO(pdf)).pages)
    wrong_count = ComposedSample(pages=[[]] * (pages + 1), evidence={})
    assert "pages" in verify_pdf(pdf, wrong_count)[0]
    absent = EvidenceEntry(
        state=SampleState.MET, page=1, sentence="This sentence is not in the file."
    )
    wrong_text = ComposedSample(pages=[[]] * pages, evidence={"GOV-01": absent})
    assert "GOV-01" in verify_pdf(pdf, wrong_text)[0]
