"""Generate every sample vendor: compose, check, render, verify the PDF, write the files."""

import json
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from vendorguard.config_models.core import SamplesSettings
from vendorguard.config_models.providers import RuleDeciderSettings
from vendorguard.controls.loader import load_controls
from vendorguard.errors import ConfigError
from vendorguard.eval.sample_gen.compose import compose
from vendorguard.eval.sample_gen.keyword_check import check_composed
from vendorguard.eval.sample_gen.models import ComposedSample, EvidenceFile, GeneratedSample
from vendorguard.eval.sample_gen.phrases import lint_bank, load_phrases
from vendorguard.eval.sample_gen.render_pdf import render_pdf
from vendorguard.eval.sample_gen.render_txt import render_txt
from vendorguard.eval.specs import VendorSpec, check_covers, load_spec
from vendorguard.utils.hashing import sha256_bytes


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def verify_pdf(pdf: bytes, composed: ComposedSample) -> list[str]:
    """Check with pypdf that the page count and every evidence sentence match the composition."""
    reader = PdfReader(BytesIO(pdf))
    if len(reader.pages) != len(composed.pages):
        return [f"PDF has {len(reader.pages)} pages, composition has {len(composed.pages)}"]
    problems = []
    for control_id, entry in composed.evidence.items():
        if entry.page is None or entry.sentence is None:
            continue
        text = _norm(reader.pages[entry.page - 1].extract_text())
        if _norm(entry.sentence) not in text:
            problems.append(f"{control_id}: sentence not found on PDF page {entry.page}")
    return problems


def _evidence_json(stem: str, spec: VendorSpec, composed: ComposedSample) -> str:
    file = EvidenceFile(
        vendor_id=spec.vendor_id,
        doc=f"{stem}.pdf",
        page_count=len(composed.pages),
        controls=composed.evidence,
    )
    return json.dumps(file.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"


def generate_all(
    samples: SamplesSettings, rules: RuleDeciderSettings, controls_file: Path, out_dir: Path
) -> list[GeneratedSample]:
    """Write ``<stem>.pdf``, ``<stem>.txt`` and ``<stem>.evidence.json`` for every spec file.

    Raises ConfigError, listing every problem at once, if the phrase bank or a spec is inconsistent,
    if a keyword reading of a document disagrees with its spec, or if a PDF fails verification.
    """
    controls = load_controls(controls_file)
    bank = load_phrases(samples.phrases_file)
    if problems := lint_bank(bank, controls, rules):
        raise ConfigError("phrase bank problems:\n  " + "\n  ".join(problems))
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for path in sorted(samples.specs_dir.glob("*.yaml"), key=lambda p: p.stem):
        spec = load_spec(path)
        check_covers(spec, [c.id for c in controls.controls])
        composed = compose(spec, bank, controls, samples)
        pdf = render_pdf(path.stem, spec.vendor_name, composed.pages, samples)
        problems = check_composed(composed, spec, controls, rules) + verify_pdf(pdf, composed)
        if problems:
            raise ConfigError(f"sample {path.stem} is inconsistent:\n  " + "\n  ".join(problems))
        files = {
            f"{path.stem}.pdf": pdf,
            f"{path.stem}.txt": render_txt(composed.pages).encode("ascii"),
            f"{path.stem}.evidence.json": _evidence_json(path.stem, spec, composed).encode("ascii"),
        }
        for name, data in files.items():
            (out_dir / name).write_bytes(data)
        results.append(
            GeneratedSample(
                stem=path.stem,
                pdf=out_dir / f"{path.stem}.pdf",
                txt=out_dir / f"{path.stem}.txt",
                evidence=out_dir / f"{path.stem}.evidence.json",
                sha256={name: sha256_bytes(data) for name, data in files.items()},
            )
        )
    return results


__all__ = ["generate_all", "verify_pdf"]
